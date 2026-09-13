# ══════════════════════════════════════════════════════════════════
#  MULTI-USER VIRTUAL TRADING MANAGER (Multi-Tenant Execution Desk)
#  Manages User Margin, Manual & Algo Orders, Live Tick PnL & TSL
# ══════════════════════════════════════════════════════════════════
import os
import time
import sqlite3
from datetime import datetime
from typing import Dict, List, Any, Optional

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
from user_database import user_db

QTY_PER_LOT = 65
BROKERAGE_PER_LOT = 70.0

class MultiUserTradingManager:
    def __init__(self, db=user_db):
        self.db = db

    def get_user_portfolio(self, user_id: int) -> Dict[str, Any]:
        """Fetch complete isolated portfolio, margins, and active positions for a user."""
        user = self.db.get_user_by_id(user_id)
        if not user:
            return {"status": "error", "message": "User not found"}

        with self.db.get_connection() as conn:
            cursor = conn.cursor()

            # 1. Fetch active positions
            cursor.execute("SELECT * FROM user_positions WHERE user_id = ? AND status = 'OPEN' ORDER BY id DESC", (user_id,))
            open_positions = [dict(r) for r in cursor.fetchall()]

            # 2. Fetch today's closed trades
            today_str = datetime.now().strftime("%Y-%m-%d")
            cursor.execute("""
                SELECT * FROM user_trades 
                WHERE user_id = ? AND date = ? 
                ORDER BY id DESC
            """, (user_id, today_str))
            today_trades = [dict(r) for r in cursor.fetchall()]

            # 3. Fetch all-time trades summary
            cursor.execute("""
                SELECT COUNT(*) as total_trades,
                       SUM(CASE WHEN net_pnl > 0 THEN 1 ELSE 0 END) as win_trades,
                       SUM(CASE WHEN net_pnl <= 0 THEN 1 ELSE 0 END) as loss_trades,
                       COALESCE(SUM(net_pnl), 0.0) as all_time_realized_pnl
                FROM user_trades 
                WHERE user_id = ?
            """, (user_id,))
            summary = dict(cursor.fetchone())

        cash_balance = float(user["cash_balance"])
        utilized_margin = sum(float(p["entry_price"]) * int(p["quantity"]) for p in open_positions)
        available_margin = max(0.0, cash_balance - utilized_margin)
        unrealized_pnl = sum(float(p["live_pnl_rupees"]) for p in open_positions)
        net_equity = cash_balance + unrealized_pnl

        today_realized_pnl = sum(float(t["net_pnl"]) for t in today_trades)
        today_total_pnl = today_realized_pnl + unrealized_pnl

        total_trades = summary.get("total_trades", 0) or 0
        win_trades = summary.get("win_trades", 0) or 0
        win_rate = round((win_trades / total_trades * 100.0), 1) if total_trades > 0 else 0.0

        return {
            "status": "ok",
            "user_id": user["id"],
            "username": user["username"],
            "full_name": user["full_name"],
            "role": user["role"],
            "initial_capital": float(user["initial_capital"]),
            "cash_balance": round(cash_balance, 2),
            "utilized_margin": round(utilized_margin, 2),
            "available_margin": round(available_margin, 2),
            "unrealized_pnl": round(unrealized_pnl, 2),
            "net_equity": round(net_equity, 2),
            "today_realized_pnl": round(today_realized_pnl, 2),
            "today_total_pnl": round(today_total_pnl, 2),
            "all_time_realized_pnl": round(float(summary.get("all_time_realized_pnl", 0.0)), 2),
            "total_trades": total_trades,
            "win_trades": win_trades,
            "loss_trades": summary.get("loss_trades", 0) or 0,
            "win_rate": win_rate,
            "active_positions": open_positions,
            "recent_trades": today_trades[:15]
        }

    def place_order(self, user_id: int, direction: str, strike: float, lots: int = 1,
                    entry_price: float = 0.0, target_pts: float = 18.0, sl_pts: float = 7.5,
                    spot_price: float = 0.0, order_type: str = "MARKET") -> Dict[str, Any]:
        """Places a manual or virtual trade order for a specific user with strict margin enforcement."""
        user = self.db.get_user_by_id(user_id)
        if not user:
            return {"status": "error", "message": "User not found"}
        if user["status"] != "active":
            return {"status": "error", "message": "Your account has been disabled"}

        direction = direction.upper()
        if direction not in ("CALL", "PUT"):
            return {"status": "error", "message": "Invalid direction. Must be CALL or PUT"}

        option_type = "CE" if direction == "CALL" else "PE"
        lots = max(1, int(lots))
        qty = lots * QTY_PER_LOT
        strike = float(strike)

        # If live market data is not passed, fetch latest quote from DuckDB
        if entry_price <= 0 or spot_price <= 0:
            try:
                from duckdb_engine import duckdb_engine
                df = duckdb_engine.get_latest_option_chain()
                if df is not None and not df.empty:
                    if spot_price <= 0:
                        spot_price = float(df['spot_price'].iloc[0])
                    if strike <= 0:
                        spot_price_atm = round(spot_price / 50.0) * 50.0
                        strike = (spot_price_atm - 50.0) if direction == "CALL" else (spot_price_atm + 50.0)
                    if entry_price <= 0:
                        matched = df[(df['strike'] == strike) & (df['type'] == option_type)]
                        if not matched.empty:
                            entry_price = float(matched['ltp'].iloc[0])
            except Exception as e:
                print("Error auto-fetching market price:", e)

        if entry_price <= 0:
            entry_price = 120.0  # Fallback
        if spot_price <= 0:
            spot_price = strike

        margin_required = round(entry_price * qty, 2)

        # Margin check: Verify user has sufficient cash
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT cash_balance FROM users WHERE id = ?", (user_id,))
            current_cash = float(cursor.fetchone()["cash_balance"])

            cursor.execute("SELECT SUM(entry_price * quantity) as util FROM user_positions WHERE user_id = ? AND status = 'OPEN'", (user_id,))
            util_row = cursor.fetchone()
            current_util = float(util_row["util"]) if util_row and util_row["util"] else 0.0

            available_margin = current_cash - current_util
            if margin_required > available_margin:
                return {
                    "status": "error",
                    "message": f"Insufficient Virtual Margin! Needed: ₹{margin_required:,.2f} | Available: ₹{available_margin:,.2f}"
                }

            now_dt = datetime.now()
            ts = now_dt.strftime("%Y-%m-%d %H:%M:%S")
            trade_id = f"TRD_U{user_id}_{now_dt.strftime('%Y%m%d_%H%M%S_%f')}"
            contract = f"NIFTY {int(strike)} {option_type}"

            target_price = round(entry_price + target_pts, 2)
            sl_price = max(1.0, round(entry_price - sl_pts, 2))

            cursor.execute("""
                INSERT INTO user_positions 
                (trade_id, user_id, timestamp, direction, option_type, contract, strike,
                 lots, quantity, entry_spot, entry_price, current_ltp, stop_loss_price,
                 initial_sl_price, target_price, peak_pts, trailed_to_cost, tsl_stage,
                 live_pnl_rupees, live_pnl_pct, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0.0, 0, 'INITIAL', 0.0, 0.0, 'OPEN')
            """, (trade_id, user_id, ts, direction, option_type, contract, strike,
                  lots, qty, spot_price, entry_price, entry_price, sl_price,
                  sl_price, target_price))
            conn.commit()

        return {
            "status": "ok",
            "message": f"Order Placed: {contract} @ ₹{entry_price:.2f} (Qty: {qty}) | Target: ₹{target_price:.2f} | SL: ₹{sl_price:.2f}",
            "trade_id": trade_id,
            "margin_required": margin_required
        }

    def close_position(self, user_id: int, trade_id: str, exit_price: Optional[float] = None, 
                       outcome: str = "MANUAL_CLOSE", exit_spot: Optional[float] = None) -> Dict[str, Any]:
        """Closes an active position, calculates realized PnL with brokerage, and credits user wallet."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM user_positions WHERE trade_id = ? AND user_id = ? AND status = 'OPEN'", (trade_id, user_id))
            pos = cursor.fetchone()
            if not pos:
                return {"status": "error", "message": f"Active position {trade_id} not found"}

            pos = dict(pos)
            entry_price = float(pos["entry_price"])
            qty = int(pos["quantity"])
            lots = int(pos["lots"])

            actual_exit = float(exit_price) if exit_price is not None and exit_price > 0 else float(pos["current_ltp"])
            actual_exit = round(actual_exit, 2)

            pnl_pts = round(actual_exit - entry_price, 2)
            gross_pnl = round(pnl_pts * qty, 2)
            brokerage = round(lots * BROKERAGE_PER_LOT, 2)
            net_pnl = round(gross_pnl - brokerage, 2)
            pnl_pct = round((pnl_pts / entry_price * 100.0), 2) if entry_price > 0 else 0.0

            now_dt = datetime.now()
            exit_ts = now_dt.strftime("%Y-%m-%d %H:%M:%S")
            date_str = now_dt.strftime("%Y-%m-%d")
            s_spot = float(exit_spot) if exit_spot else float(pos["entry_spot"])

            # 1. Insert into user_trades ledger
            cursor.execute("""
                INSERT INTO user_trades 
                (trade_id, user_id, entry_timestamp, exit_timestamp, date, direction, option_type,
                 contract, strike, lots, quantity, entry_spot, entry_price, exit_spot, exit_price,
                 exit_reason, pnl_pts, gross_pnl, brokerage, net_pnl, pnl_pct, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'CLOSED')
            """, (pos["trade_id"], user_id, pos["timestamp"], exit_ts, date_str, pos["direction"],
                  pos["option_type"], pos["contract"], pos["strike"], pos["lots"], pos["quantity"],
                  pos["entry_spot"], entry_price, s_spot, actual_exit, outcome, pnl_pts,
                  gross_pnl, brokerage, net_pnl, pnl_pct))

            # 2. Update user cash balance (Realized Net PnL added/deducted)
            cursor.execute("UPDATE users SET cash_balance = cash_balance + ? WHERE id = ?", (net_pnl, user_id))

            # 3. Delete from open positions
            cursor.execute("DELETE FROM user_positions WHERE trade_id = ?", (trade_id,))
            conn.commit()

        return {
            "status": "ok",
            "message": f"Position Closed: {pos['contract']} @ ₹{actual_exit:.2f} | Net PnL: ₹{net_pnl:+,.2f} ({pnl_pts:+.2f} pts)",
            "net_pnl": net_pnl,
            "pnl_pts": pnl_pts
        }

    def trail_sl_to_cost(self, user_id: int, trade_id: str) -> Dict[str, Any]:
        """Locks Stop Loss to Entry Cost + ₹0.50 (Risk-Free Trade)."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT entry_price, stop_loss_price FROM user_positions WHERE trade_id = ? AND user_id = ?", (trade_id, user_id))
            row = cursor.fetchone()
            if not row:
                return {"status": "error", "message": "Position not found"}

            entry_p = float(row["entry_price"])
            locked_sl = round(entry_p + 0.50, 2)
            cursor.execute("""
                UPDATE user_positions 
                SET stop_loss_price = ?, trailed_to_cost = 1, tsl_stage = 'COST+0.5' 
                WHERE trade_id = ?
            """, (locked_sl, trade_id))
            conn.commit()
            return {"status": "ok", "message": f"Stop Loss Trailed to Cost (₹{locked_sl:.2f})"}

    def update_all_positions_with_ticks(self, ticks: List[Dict[str, Any]], spot_price: float):
        """
        High-Frequency Engine: Updates MTM, trailing SL, and checks Target/SL 
        for ALL active positions across ALL users on every incoming tick!
        """
        if not ticks or spot_price <= 0:
            return

        # Build quick price map: (strike, type) -> LTP
        price_map = {}
        for t in ticks:
            try:
                stk = float(t.get("strike", 0))
                typ = t.get("type", "").upper()
                ltp = float(t.get("ltp", 0.0) or 0.0)
                if ltp > 0:
                    price_map[(stk, typ)] = ltp
            except Exception:
                continue

        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM user_positions WHERE status = 'OPEN'")
            positions = [dict(r) for r in cursor.fetchall()]

            to_close = []

            for p in positions:
                stk = float(p["strike"])
                typ = p["option_type"].upper()
                live_ltp = price_map.get((stk, typ), float(p["current_ltp"]))

                if live_ltp <= 0:
                    continue

                entry_p = float(p["entry_price"])
                qty = int(p["quantity"])
                target_p = float(p["target_price"])
                sl_p = float(p["stop_loss_price"])

                cur_gain = round(live_ltp - entry_p, 2)
                peak_pts = max(float(p.get("peak_pts", 0.0) or 0.0), cur_gain)

                # 4-Tier Asymmetric Trailing SL
                tsl_stage = p.get("tsl_stage", "INITIAL")
                trailed = p.get("trailed_to_cost", 0)
                new_sl = sl_p

                # Tier 3: +12.0+ pts -> Lock 80%
                if peak_pts >= 12.0:
                    cand = round(entry_p + (peak_pts * 0.80), 2)
                    if cand > new_sl:
                        new_sl = cand
                        tsl_stage = f"MEGA 80% (+{round(peak_pts*0.80, 1)})"
                # Tier 2: +6.0 to 11.9 pts -> Lock 65%
                elif peak_pts >= 6.0:
                    cand = round(entry_p + (peak_pts * 0.65), 2)
                    if cand > new_sl:
                        new_sl = cand
                        tsl_stage = f"MID 65% (+{round(peak_pts*0.65, 1)})"
                # Tier 1: +3.0 to 5.9 pts -> Cost + 0.50
                elif peak_pts >= 3.0:
                    cand = round(entry_p + 0.50, 2)
                    if cand > new_sl:
                        new_sl = cand
                        trailed = 1
                        tsl_stage = "COST +0.5"

                # Check Exits:
                if live_ltp <= new_sl:
                    reason = f"🛡️ Trailing SL Hit (+{round(new_sl - entry_p, 2)} pts)" if new_sl > entry_p else f"🛑 Stop Loss Hit (-{round(entry_p - new_sl, 2)} pts)"
                    to_close.append((p["user_id"], p["trade_id"], new_sl, reason, spot_price))
                    continue

                if live_ltp >= target_p:
                    reason = f"🎯 Target Hit (+{round(target_p - entry_p, 2)} pts)"
                    to_close.append((p["user_id"], p["trade_id"], target_p, reason, spot_price))
                    continue

                # Live MTM Updates
                live_pnl_rupees = round(cur_gain * qty, 2)
                live_pnl_pct = round((cur_gain / entry_p * 100.0), 2) if entry_p > 0 else 0.0

                cursor.execute("""
                    UPDATE user_positions 
                    SET current_ltp = ?, peak_pts = ?, stop_loss_price = ?,
                        trailed_to_cost = ?, tsl_stage = ?,
                        live_pnl_rupees = ?, live_pnl_pct = ?
                    WHERE trade_id = ?
                """, (live_ltp, peak_pts, new_sl, trailed, tsl_stage, live_pnl_rupees, live_pnl_pct, p["trade_id"]))

            conn.commit()

        # Execute pending auto-exits
        for uid, tid, exit_p, outcome, s_spot in to_close:
            try:
                self.close_position(user_id=uid, trade_id=tid, exit_price=exit_p, outcome=outcome, exit_spot=s_spot)
            except Exception as e:
                print(f"Error auto-closing position {tid}:", e)

    def broadcast_signal(self, signal_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Broadcasts an incoming algorithmic confluence signal across all active users.
        - If user has auto_trade_enabled=1 and direction matches -> Auto-executes order.
        - If user has auto_trade_enabled=0 -> Creates interactive notification alert (Execute/Cancel).
        """
        signal_dir = signal_data.get("direction", "CALL").upper()
        strike = float(signal_data.get("strike", 0.0))
        contract = signal_data.get("contract", f"NIFTY {int(strike)} {'CE' if signal_dir == 'CALL' else 'PE'}")
        spot = float(signal_data.get("spot", 0.0))
        suggested_price = float(signal_data.get("suggested_price", 120.0))
        signal_id = signal_data.get("signal_id", f"SIG_{int(time.time()*1000)}")

        auto_trades_placed = []
        alerts_created = []

        all_users = self.db.get_all_users()
        for u in all_users:
            if u["status"] != "active":
                continue
            user_id = u["id"]

            # Prevent duplicate entry if user already has an open position in this contract
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT COUNT(*) FROM user_positions 
                    WHERE user_id = ? AND contract = ? AND status = 'OPEN'
                """, (user_id, contract))
                if cursor.fetchone()[0] > 0:
                    continue

            user_cfg = self.db.get_user_settings(user_id)
            user_pref_dir = user_cfg.get("trade_direction", "BOTH").upper()

            # Filter direction: BOTH, CALL, or PUT
            if user_pref_dir != "BOTH" and user_pref_dir != signal_dir:
                continue

            lots = int(user_cfg.get("lots", 1))
            target_pts = float(user_cfg.get("target_pts", 35.0))
            sl_pts = float(user_cfg.get("sl_pts", 25.0))

            if user_cfg.get("auto_trade_enabled", 0) == 1:
                # ── Auto-Trade Mode: Execute instantly ──
                res = self.place_order(
                    user_id=user_id,
                    direction=signal_dir,
                    strike=strike,
                    lots=lots,
                    entry_price=suggested_price,
                    target_pts=target_pts,
                    sl_pts=sl_pts,
                    spot_price=spot,
                    order_type="ALGO_AUTO"
                )
                if res.get("status") == "ok":
                    auto_trades_placed.append({"user_id": user_id, "trade_id": res.get("trade_id")})
            else:
                # ── Semi-Auto / Notification Mode: Push alert with Execute/Cancel ──
                target_p = round(suggested_price + target_pts, 2)
                sl_p = max(1.0, round(suggested_price - sl_pts, 2))
                alert_id = self.db.create_signal_alert(user_id, {
                    "signal_id": signal_id,
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "direction": signal_dir,
                    "option_type": "CE" if signal_dir == "CALL" else "PE",
                    "strike": strike,
                    "contract": contract,
                    "spot": spot,
                    "suggested_price": suggested_price,
                    "target_price": target_p,
                    "sl_price": sl_p,
                    "lots": lots
                })
                alerts_created.append({"user_id": user_id, "alert_id": alert_id})

        return {
            "status": "ok",
            "auto_trades_placed": auto_trades_placed,
            "alerts_created": alerts_created
        }

    def execute_alert(self, user_id: int, alert_id: int) -> Dict[str, Any]:
        """User clicks 'Execute' button on a signal notification."""
        alert = self.db.get_alert_by_id(alert_id, user_id)
        if not alert:
            return {"status": "error", "message": "Signal alert not found"}
        if alert["status"] != "PENDING":
            return {"status": "error", "message": f"Alert already {alert['status'].lower()}"}

        # User settings for SL/Target
        cfg = self.db.get_user_settings(user_id)
        lots = alert["lots"] or cfg.get("lots", 1)
        target_pts = float(cfg.get("target_pts", 35.0))
        sl_pts = float(cfg.get("sl_pts", 25.0))

        res = self.place_order(
            user_id=user_id,
            direction=alert["direction"],
            strike=float(alert["strike"]),
            lots=lots,
            entry_price=float(alert["suggested_price"]),
            target_pts=target_pts,
            sl_pts=sl_pts,
            spot_price=float(alert["spot"]),
            order_type="SIGNAL_MANUAL_EXEC"
        )

        if res.get("status") == "ok":
            self.db.update_alert_status(alert_id, user_id, "EXECUTED")
            return {
                "status": "ok",
                "message": f"Signal Executed! Order {res.get('trade_id')} active.",
                "trade_id": res.get("trade_id")
            }
        else:
            return res

    def cancel_alert(self, user_id: int, alert_id: int) -> Dict[str, Any]:
        """User clicks 'Cancel' button to dismiss a signal notification."""
        success = self.db.update_alert_status(alert_id, user_id, "CANCELLED")
        if success:
            return {"status": "ok", "message": "Signal dismissed"}
        return {"status": "error", "message": "Failed to cancel alert or alert not found"}

    def get_all_platform_open_positions(self) -> List[Dict[str, Any]]:
        """Used by Admin to monitor live open trades of all users."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT p.*, u.username, u.full_name
                FROM user_positions p
                JOIN users u ON p.user_id = u.id
                WHERE p.status = 'OPEN'
                ORDER BY p.id DESC
            """)
            return [dict(r) for r in cursor.fetchall()]

    def get_all_platform_trades(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Used by Admin to view global live trade feed."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT t.*, u.username, u.full_name
                FROM user_trades t
                JOIN users u ON t.user_id = u.id
                ORDER BY t.id DESC
                LIMIT ?
            """, (limit,))
            return [dict(r) for r in cursor.fetchall()]

multi_user_trader = MultiUserTradingManager()
