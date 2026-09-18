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

try:
    from telegram_notifier import send_telegram_trade_entry, send_telegram_tsl_update, send_telegram_trade_exit
except Exception:
    send_telegram_trade_entry = None
    send_telegram_tsl_update = None
    send_telegram_trade_exit = None

QTY_PER_LOT = 65
BROKERAGE_PER_LOT = 70.0

class MultiUserTradingManager:
    def __init__(self, db=user_db):
        self.db = db
        self._last_signal_time: Dict[int, float] = {}
        self._last_trade_closed_time: Dict[int, float] = {}
        self._last_notified_sl: Dict[str, float] = {}

    def get_last_closed_trade_time(self, user_id: int) -> float:
        """Returns unix epoch timestamp of user's most recently closed trade."""
        if user_id in self._last_trade_closed_time:
            return self._last_trade_closed_time[user_id]
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT exit_timestamp FROM user_trades 
                WHERE user_id = ? 
                ORDER BY id DESC LIMIT 1
            """, (user_id,))
            row = cursor.fetchone()
            if row and row["exit_timestamp"]:
                try:
                    clean = str(row["exit_timestamp"]).replace('T', ' ').split('.')[0].strip()
                    dt = datetime.strptime(clean, "%Y-%m-%d %H:%M:%S")
                    val = dt.timestamp()
                    self._last_trade_closed_time[user_id] = val
                    return val
                except Exception:
                    pass
        return 0.0

    def _parse_signal_timestamp(self, signal_data: Dict[str, Any], fallback: float) -> float:
        """Extracts and parses generation timestamp from incoming signal."""
        for k in ["timestamp", "entry_time", "created_at", "signal_time"]:
            val = signal_data.get(k)
            if val:
                if isinstance(val, (int, float)):
                    return float(val)
                if isinstance(val, str):
                    try:
                        clean = val.replace('T', ' ').split('.')[0].strip()
                        dt = datetime.strptime(clean, "%Y-%m-%d %H:%M:%S")
                        return dt.timestamp()
                    except Exception:
                        pass
        sig_id = str(signal_data.get("signal_id", ""))
        if sig_id.startswith("SIG_"):
            parts = sig_id[4:].split('_')
            if parts and parts[0].isdigit():
                try:
                    val = int(parts[0])
                    if val > 1e11:  # milliseconds
                        val /= 1000.0
                    if val > 1e8:
                        return float(val)
                except Exception:
                    pass
        return fallback

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

            # Rule: Auto-trading allows strictly 1 open position at a time
            if order_type == "ALGO_AUTO":
                cursor.execute("SELECT COUNT(*) FROM user_positions WHERE user_id = ? AND status = 'OPEN'", (user_id,))
                cur_open_pos = cursor.fetchone()[0]
                if cur_open_pos >= 1:
                    return {
                        "status": "error",
                        "message": "Auto-trading allows strictly 1 open position at a time. Previous trade must close first."
                    }

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

        # Dispatch Telegram Notification for Order Entry
        try:
            if send_telegram_trade_entry:
                send_telegram_trade_entry({
                    "contract": contract,
                    "direction": direction,
                    "entry_price": entry_price,
                    "sl_price": sl_price,
                    "target_price": target_price,
                    "quantity": qty,
                    "lots": lots,
                    "spot_price": spot_price,
                    "reason": f"Order Placed ({order_type})"
                })
        except Exception as e:
            print("[TELEGRAM] Failed to send entry alert:", e)

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

            # Realistic Friction: Rs. 70/lot brokerage + Real Market Option Execution Slippage (from DuckDB tick data)
            # Replaces old fixed 1.0% formula (which penalized up to ₹1,462 on 10 lots) with real market tick gaps
            try:
                from duckdb_engine import duckdb_engine
                con = duckdb_engine.get_connection(read_only=True)
                ticks = con.execute("""
                    SELECT ltp FROM nifty_ticks 
                    WHERE strike = ? AND type = ? 
                    ORDER BY timestamp DESC LIMIT 5
                """, (float(pos.get("strike", 0)), str(pos.get("option_type", "CE")))).fetchall()
                if ticks and len(ticks) >= 2:
                    p_list = [r[0] for r in ticks if r[0] is not None]
                    gaps = [abs(p_list[i] - p_list[i+1]) for i in range(len(p_list)-1)]
                    slip_leg = max(0.05, min(0.35, round(sum(gaps)/len(gaps), 2)))
                else:
                    slip_leg = 0.15
            except Exception:
                slip_leg = 0.15

            slip_entry_pts = slip_leg
            slip_exit_pts = slip_leg
            slippage_pts = round(slip_entry_pts + slip_exit_pts, 2)
            slippage_rupees = round(slippage_pts * qty, 2)
            brokerage = round(lots * BROKERAGE_PER_LOT, 2)
            net_pnl = round(gross_pnl - brokerage - slippage_rupees, 2)
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
                 exit_reason, pnl_pts, gross_pnl, brokerage, slippage, net_pnl, pnl_pct, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'CLOSED')
            """, (pos["trade_id"], user_id, pos["timestamp"], exit_ts, date_str, pos["direction"],
                  pos["option_type"], pos["contract"], pos["strike"], pos["lots"], pos["quantity"],
                  pos["entry_spot"], entry_price, s_spot, actual_exit, outcome, pnl_pts,
                  gross_pnl, brokerage, slippage_rupees, net_pnl, pnl_pct))

            # 2. Update user cash balance (Realized Net PnL added/deducted)
            cursor.execute("UPDATE users SET cash_balance = cash_balance + ? WHERE id = ?", (net_pnl, user_id))

            # 3. Delete from open positions
            cursor.execute("DELETE FROM user_positions WHERE trade_id = ?", (trade_id,))
            conn.commit()

        # Update last closed trade timestamp for user (ensures subsequent auto-trades only take fresh post-close signals)
        self._last_trade_closed_time[user_id] = now_dt.timestamp()

        # Dismiss any outdated pending alerts for this user
        try:
            self.db.dismiss_all_alerts(user_id)
        except Exception:
            pass

        # Clean tracking & dispatch Telegram Exit Alert
        self._last_notified_sl.pop(trade_id, None)
        try:
            if send_telegram_trade_exit:
                send_telegram_trade_exit({
                    "contract": pos.get("contract", f"NIFTY {int(pos.get('strike', 0))} {pos.get('option_type', '')}"),
                    "direction": pos.get("direction", "CALL"),
                    "entry_price": entry_price,
                    "exit_price": actual_exit,
                    "quantity": qty,
                    "lots": lots,
                    "brokerage": brokerage,
                    "slippage": slippage_rupees,
                    "net_pnl": net_pnl,
                    "exit_reason": outcome,
                    "entry_timestamp": pos.get("timestamp", ""),
                    "exit_timestamp": exit_ts
                })
        except Exception as e:
            print("[TELEGRAM] Failed to send exit alert:", e)

        return {
            "status": "ok",
            "message": f"Position Closed: {pos['contract']} @ ₹{actual_exit:.2f} | Net PnL: ₹{net_pnl:+,.2f} ({pnl_pts:+.2f} pts)",
            "net_pnl": net_pnl,
            "pnl_pts": pnl_pts
        }

    def trail_sl_to_cost(self, user_id: int, trade_id: str) -> Dict[str, Any]:
        """Locks Stop Loss to Early Shield (+4.4 pts) guaranteeing net profit after brokerage & slippage."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT entry_price, stop_loss_price, quantity, lots FROM user_positions WHERE trade_id = ? AND user_id = ?", (trade_id, user_id))
            row = cursor.fetchone()
            if not row:
                return {"status": "error", "message": "Position not found"}

            entry_p = float(row["entry_price"])
            qty = int(row["quantity"])
            lots = int(row["lots"])
            brok_pts = round((BROKERAGE_PER_LOT * lots) / max(1, qty), 2)
            slip_pts = 0.60
            net_min_pts = round(120.0 / max(1, qty), 2)
            locked_sl = round(entry_p + brok_pts + slip_pts + net_min_pts, 2) # ~4.40 pts

            cursor.execute("""
                UPDATE user_positions 
                SET stop_loss_price = ?, trailed_to_cost = 1, tsl_stage = 'EARLY_NET_SHIELD' 
                WHERE trade_id = ?
            """, (locked_sl, trade_id))
            conn.commit()
            return {"status": "ok", "message": f"Stop Loss Trailed to Early Net Shield (+₹120 Net at ₹{locked_sl:.2f})"}

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

                # Cost & Friction Math
                lots = max(1, qty // 50)
                brok_pts = round((70.0 * lots) / max(1, qty), 2)  # ~1.40 pts for 50 qty
                slip_pts = 0.60  # Buffer for execution slippage
                net_min_pts = round(120.0 / max(1, qty), 2) # ~2.40 pts guaranteed net profit
                early_safe_lock_pts = round(brok_pts + slip_pts + net_min_pts, 2) # ~4.40 pts

                tsl_stage = p.get("tsl_stage", "INITIAL")
                trailed = p.get("trailed_to_cost", 0)
                new_sl = sl_p

                # ══════════════════════════════════════════════════════════════
                # DYNAMIC TRAILING RATIO & MEGA RUNNER RATCHET (-2.0 PTS)
                # ══════════════════════════════════════════════════════════════
                # STAGE 3: MEGA RUNNER -2.0 PT EXACT RATCHET (Peak >= 12.0 pts):
                # When trade is flying, trail strictly 2 points behind the highest peak!
                # Examples: Peak 30 -> SL 28, Peak 34 -> SL 32, Peak 36 -> SL 34, Peak 71 -> SL 69!
                tid = p["trade_id"]
                last_notified = self._last_notified_sl.get(tid, 0.0)

                if peak_pts >= 12.0:
                    cand = round(entry_p + peak_pts - 2.0, 2)
                    if cand > new_sl:
                        new_sl = cand
                        trailed = 1
                        tsl_stage = f"🚀 MEGA RIDE -2pt (Peak +{peak_pts:.1f} ➔ SL +{round(cand - entry_p, 1)})"
                        if send_telegram_tsl_update and (abs(cand - last_notified) >= 2.0 or last_notified < entry_p):
                            self._last_notified_sl[tid] = cand
                            try:
                                send_telegram_tsl_update({
                                    "contract": p["contract"],
                                    "peak_pts": peak_pts,
                                    "new_sl": cand,
                                    "entry_price": entry_p,
                                    "quantity": qty
                                })
                            except Exception as e:
                                print("[TELEGRAM] TSL alert error:", e)

                # STAGE 2: ACCELERATING RUNNER (Peak >= 8.0 to 11.9 pts):
                # Trail at Peak - 2.5 pts to lock in solid gain
                elif peak_pts >= 8.0:
                    cand = round(entry_p + peak_pts - 2.5, 2)
                    if cand > new_sl:
                        new_sl = cand
                        trailed = 1
                        tsl_stage = f"🎯 MID RUNNER (Peak +{peak_pts:.1f} ➔ SL +{round(cand - entry_p, 1)})"
                        if send_telegram_tsl_update and (abs(cand - last_notified) >= 2.0 or last_notified < entry_p):
                            self._last_notified_sl[tid] = cand
                            try:
                                send_telegram_tsl_update({
                                    "contract": p["contract"],
                                    "peak_pts": peak_pts,
                                    "new_sl": cand,
                                    "entry_price": entry_p,
                                    "quantity": qty
                                })
                            except Exception as e:
                                print("[TELEGRAM] TSL alert error:", e)

                # STAGE 1: EARLY PULLBACK SHIELD (Peak >= 5.5 to 7.9 pts):
                # Covers ₹70 brokerage + slippage + locks ₹100-₹150 guaranteed net profit
                elif peak_pts >= 5.5:
                    cand = round(entry_p + early_safe_lock_pts, 2)
                    if cand > new_sl:
                        new_sl = cand
                        trailed = 1
                        net_rs = round((cand - entry_p - brok_pts - slip_pts) * qty, 0)
                        tsl_stage = f"🛡️ NET SHIELD (+{round(cand - entry_p, 1)} pts | +₹{int(net_rs)} Net)"
                        if send_telegram_tsl_update and last_notified < cand:
                            self._last_notified_sl[tid] = cand
                            try:
                                send_telegram_tsl_update({
                                    "contract": p["contract"],
                                    "peak_pts": peak_pts,
                                    "new_sl": cand,
                                    "entry_price": entry_p,
                                    "quantity": qty,
                                    "net_rs": net_rs
                                })
                            except Exception as e:
                                print("[TELEGRAM] TSL alert error:", e)

                # Check Exits:
                if live_ltp <= new_sl:
                    pts_captured = round(new_sl - entry_p, 2)
                    if new_sl > entry_p:
                        reason = f"🛡️ Trailing SL Hit (+{pts_captured} pts)"
                    else:
                        reason = f"🛑 Stop Loss Hit (-{round(entry_p - new_sl, 2)} pts)"
                    to_close.append((p["user_id"], p["trade_id"], new_sl, reason, spot_price))
                    continue

                # Target Handling:
                # If peak_pts >= 12.0, trade is in MEGA RUNNER mode (-2.0 pt ratchet).
                # Do NOT cut off a mega runner at target! Let it ride all the way to 30, 36, 71+ pts!
                if live_ltp >= target_p:
                    if peak_pts >= 12.0:
                        pass # Let the -2.0 pt trailing runner ride!
                    else:
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

    def broadcast_signal(self, signal_data: Dict[str, Any], master_auto: bool = False) -> Dict[str, Any]:
        """
        Broadcasts an incoming algorithmic confluence signal across all active users.
        - If master_auto is True or user has auto_trade_enabled=1 and direction matches -> Auto-executes order.
        - If user has auto_trade_enabled=0 -> Creates interactive notification alert (Execute/Cancel).
        """
        # ══════════════════════════════════════════════════════════════
        # TIME-OF-DAY QUALITY FILTER:
        # Trading Window: 09:20 to 14:45 IST (Avoid 3 PM closing wild chop and 12:00-12:45 lunch chop)
        # ══════════════════════════════════════════════════════════════
        from datetime import datetime, timezone, timedelta
        ist_now = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=5, minutes=30)
        time_str = ist_now.strftime("%H:%M")
        if time_str < "09:20" or time_str > "14:45":
            return {"status": "skipped", "message": f"Outside allowed trading window (09:20 - 14:45 IST). Current time: {time_str}"}
        if "12:00" <= time_str <= "12:45":
            return {"status": "skipped", "message": f"Midday chop avoidance window (12:00 - 12:45 IST). Current time: {time_str}"}

        signal_dir = signal_data.get("direction", "CALL").upper()
        strike = float(signal_data.get("strike", 0.0) or signal_data.get("strike_price", 0.0))
        contract = signal_data.get("contract", f"NIFTY {int(strike)} {'CE' if signal_dir == 'CALL' else 'PE'}")
        spot = float(signal_data.get("spot", 0.0) or signal_data.get("entry_spot", 0.0))
        suggested_price = float(signal_data.get("suggested_price", 0.0) or signal_data.get("entry_ltp", 120.0))
        signal_id = signal_data.get("signal_id", f"SIG_{int(time.time()*1000)}")

        auto_trades_placed = []
        alerts_created = []

        now_time = time.time()
        all_users = self.db.get_all_users()
        for u in all_users:
            if u["status"] != "active":
                continue
            user_id = u["id"]

            user_cfg = self.db.get_user_settings(user_id)
            user_pref_dir = user_cfg.get("trade_direction", "BOTH").upper()

            # Filter direction: BOTH, CALL, or PUT
            if user_pref_dir != "BOTH" and user_pref_dir != signal_dir:
                continue

            is_auto_active = bool(master_auto or user_cfg.get("auto_trade_enabled", 0) == 1)

            # 1. Strict Signal Throttle: At least 45 seconds between signals/trades per user
            last_time = self._last_signal_time.get(user_id, 0)
            if now_time - last_time < 45.0:
                continue

            # 2. Check Maximum Active Open Positions Limit:
            # Rule 1: "auto mode on per ye ek traid ek barme lega"
            # In Auto Mode, STRICTLY only 1 trade at a time is permitted!
            max_open = 1 if is_auto_active else int(user_cfg.get("max_open_positions", 1))
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM user_positions WHERE user_id = ? AND status = 'OPEN'", (user_id,))
                cur_open = cursor.fetchone()[0]
                if cur_open >= max_open:
                    continue

                # 3. Prevent duplicate entry if user already has an open position in this strike & option_type
                opt_type = "CE" if signal_dir == "CALL" else "PE"
                cursor.execute("""
                    SELECT COUNT(*) FROM user_positions 
                    WHERE user_id = ? AND strike = ? AND option_type = ? AND status = 'OPEN'
                """, (user_id, strike, opt_type))
                if cursor.fetchone()[0] > 0:
                    continue

            # 4. Post-Close Signal Verification for Auto Mode:
            # Rule 2: "jab wo close hogi tabhi dusri traid close hone ke badke time ki traid lega"
            # When previous trade closes, next trade MUST ONLY take a signal generated AFTER the close time.
            if is_auto_active:
                last_closed_ts = self.get_last_closed_trade_time(user_id)
                if last_closed_ts > 0:
                    sig_ts = self._parse_signal_timestamp(signal_data, fallback=now_time)
                    # If signal timestamp is <= the previous trade's exit timestamp, REJECT it!
                    if sig_ts <= last_closed_ts:
                        continue
                    # Cooldown buffer (20 seconds) after trade exit so market establishes a fresh setup
                    if now_time - last_closed_ts < 20.0:
                        continue

            lots = int(user_cfg.get("lots", 1))
            target_pts = float(user_cfg.get("target_pts", 35.0))
            sl_pts = float(user_cfg.get("sl_pts", 25.0))

            if is_auto_active:
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
                    self._last_signal_time[user_id] = now_time
                    auto_trades_placed.append({"user_id": user_id, "trade_id": res.get("trade_id")})
            else:
                # ── Semi-Auto / Notification Mode: Push alert only if notifications are enabled ──
                if user_cfg.get("notifications_enabled", 1) == 0:
                    continue

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
                if alert_id:
                    self._last_signal_time[user_id] = now_time
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
