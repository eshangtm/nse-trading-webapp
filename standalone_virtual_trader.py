# ══════════════════════════════════════════════════════════════════
#  STANDALONE VIRTUAL TRADING SYSTEM (100% ISOLATED & INDEPENDENT)
#  Dedicated Virtual Wallet, Order Manager, Trailing SL & Trade Ledger
# ══════════════════════════════════════════════════════════════════
import os
import json
import sqlite3
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "collected_data")
os.makedirs(DATA_DIR, exist_ok=True)

STANDALONE_DB_FILE = os.path.join(DATA_DIR, "standalone_virtual_trader.db")
STANDALONE_WALLET_FILE = os.path.join(DATA_DIR, "standalone_wallet.json")

class StandaloneVirtualTrader:
    """
    Dedicated Virtual Trading System:
    - Completely isolated from any existing signal engine or wallet.
    - Manages its own wallet, capital, active positions, and trade ledger.
    - Real-time PnL tracking, Trailing SL, Target management, and win-rate metrics.
    """

    def __init__(self):
        self._init_db()
        self.wallet = self._load_wallet()

    def _init_db(self):
        conn = sqlite3.connect(STANDALONE_DB_FILE, timeout=30.0)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS virtual_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trade_id TEXT UNIQUE,
                timestamp TEXT,
                date TEXT,
                direction TEXT,
                option_type TEXT,
                contract TEXT,
                strike REAL,
                lots INTEGER,
                quantity INTEGER,
                entry_spot REAL,
                entry_price REAL,
                stop_loss_price REAL,
                target_price REAL,
                exit_timestamp TEXT,
                exit_spot REAL,
                exit_price REAL,
                exit_reason TEXT,
                pnl_pts REAL,
                pnl_rupees REAL,
                pnl_pct REAL,
                status TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
        conn.close()

    def _load_wallet(self):
        default_wallet = {
            "initial_capital": 100000.0,
            "cash_balance": 100000.0,
            "utilized_margin": 0.0,
            "realized_pnl": 0.0,
            "total_pnl_pct": 0.0,
            "today_pnl": 0.0,
            "total_trades": 0,
            "win_trades": 0,
            "loss_trades": 0,
            "win_rate": 0.0,
            "auto_pilot_enabled": True,
            "active_positions": []
        }
        if os.path.exists(STANDALONE_WALLET_FILE):
            try:
                with open(STANDALONE_WALLET_FILE, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                    default_wallet.update(saved)
            except Exception:
                pass
        return default_wallet

    def _save_wallet(self):
        try:
            with open(STANDALONE_WALLET_FILE, "w", encoding="utf-8") as f:
                json.dump(self.wallet, f, indent=2)
        except Exception as e:
            print("Error saving standalone wallet:", e)

    def get_live_market_data(self):
        """Fetches latest real live spot, ATM strike, and nearest strikes with CE/PE LTP from DuckDB"""
        try:
            from duckdb_engine import duckdb_engine
            df = duckdb_engine.get_latest_option_chain()
            if df is None or df.empty:
                return {"status": "empty", "spot_price": 23650.0, "atm_strike": 23650, "strikes": []}

            spot_price = float(df['spot_price'].iloc[0])
            atm_strike = int(round(spot_price / 50.0) * 50)

            # Nearest strikes: 4 below ATM to 4 above ATM
            strike_range = [atm_strike + (step * 50) for step in range(-4, 5)]

            strikes_data = []
            for s in strike_range:
                ce_row = df[(df['strike'] == s) & (df['type'] == 'CE')]
                pe_row = df[(df['strike'] == s) & (df['type'] == 'PE')]
                ce_ltp = float(ce_row['ltp'].iloc[0]) if not ce_row.empty else 0.0
                pe_ltp = float(pe_row['ltp'].iloc[0]) if not pe_row.empty else 0.0
                ce_oi = float(ce_row['oi'].iloc[0]) if not ce_row.empty else 0.0
                pe_oi = float(pe_row['oi'].iloc[0]) if not pe_row.empty else 0.0

                strikes_data.append({
                    "strike": s,
                    "ce_ltp": round(ce_ltp, 2),
                    "pe_ltp": round(pe_ltp, 2),
                    "ce_oi": ce_oi,
                    "pe_oi": pe_oi,
                    "is_atm": (s == atm_strike),
                    "label": f"{s} {'(ATM)' if s == atm_strike else ('(ITM CE)' if s < atm_strike else '(OTM CE)')}"
                })

            return {
                "status": "ok",
                "timestamp": str(df['timestamp'].iloc[0]) if 'timestamp' in df.columns else "",
                "spot_price": round(spot_price, 2),
                "atm_strike": atm_strike,
                "strikes": strikes_data
            }
        except Exception as e:
            return {"status": "error", "message": str(e), "spot_price": 23650.0, "atm_strike": 23650, "strikes": []}

    def update_positions_with_live_ticks(self, df=None):
        """Updates unrealized PnL and executes the 4-Tier Asymmetric Trailing Runner based on real live ticks from DuckDB"""
        active_positions = self.wallet.get("active_positions", [])
        if not active_positions:
            return

        try:
            if df is None:
                from duckdb_engine import duckdb_engine
                df = duckdb_engine.get_latest_option_chain()

            if df is None or df.empty:
                return

            spot_price = float(df['spot_price'].iloc[0])
            to_close = []

            for p in list(active_positions):
                strike = float(p.get("strike", 0))
                opt_type = p.get("option_type", "CE")
                entry_price = float(p.get("entry_price", 0))
                qty = int(p.get("qty", 65))
                target_p = float(p.get("target_price", entry_price + 15))
                sl_p = float(p.get("stop_loss_price", entry_price - 7.5))

                matched = df[(df['strike'] == strike) & (df['type'] == opt_type)]
                if not matched.empty:
                    live_ltp = float(matched['ltp'].iloc[0])
                    if live_ltp > 0:
                        p["current_ltp"] = round(live_ltp, 2)
                        p["live_pnl_pts"] = round(live_ltp - entry_price, 2)
                        p["live_pnl_rupees"] = round(p["live_pnl_pts"] * qty, 2)

                        cur_gain = round(live_ltp - entry_price, 2)
                        peak_pts = max(p.get("peak_pts", 0.0), cur_gain)
                        p["peak_pts"] = round(peak_pts, 2)
                        p["peak_ltp"] = round(entry_price + peak_pts, 2)

                        # ══════════════════════════════════════════════════════════
                        # 4-TIER ASYMMETRIC TRAILING RUNNER SYSTEM
                        # ══════════════════════════════════════════════════════════
                        # Tier 3: +12.0+ pts Mega Runner -> Lock 80% of peak gain (Captures 20-40+ pt swings!)
                        if peak_pts >= 12.0:
                            locked_sl = round(entry_price + (peak_pts * 0.80), 2)
                            if locked_sl > p.get("stop_loss_price", 0.0):
                                p["stop_loss_price"] = locked_sl
                                p["tsl_stage"] = f"🚀 MEGA RUNNER 80% (Locked: +{round(peak_pts * 0.80, 1)} pts)"
                        # Tier 2: +6.0 to +11.9 pts Mid Runner -> Lock 65% of peak gain
                        elif peak_pts >= 6.0:
                            locked_sl = round(entry_price + (peak_pts * 0.65), 2)
                            if locked_sl > p.get("stop_loss_price", 0.0):
                                p["stop_loss_price"] = locked_sl
                                p["tsl_stage"] = f"🎯 MID RUNNER 65% (Locked: +{round(peak_pts * 0.65, 1)} pts)"
                        # Tier 1: +3.0 to +5.9 pts Early Risk-Free -> Move SL to Cost (+0.50 pts)
                        elif peak_pts >= 3.0:
                            locked_sl = round(entry_price + 0.50, 2)
                            if locked_sl > p.get("stop_loss_price", 0.0):
                                p["stop_loss_price"] = locked_sl
                                p["trailed_to_cost"] = True
                                p["tsl_stage"] = "🛡️ ZERO RISK (Cost Locked +0.5 pts)"

                        # Auto Exit Evaluation
                        # 1. Trailing SL Hit
                        if live_ltp <= p["stop_loss_price"]:
                            if p.get("trailed_to_cost") or peak_pts >= 3.0:
                                lock_pts = round(p['stop_loss_price'] - entry_price, 1)
                                reason = f"⚡ Auto TSL Lock (+{lock_pts} pts)"
                            else:
                                sl_pts_val = round(entry_price - p['stop_loss_price'], 1)
                                reason = f"🛑 Auto Stop Loss Hit (-{sl_pts_val} pts)"
                            to_close.append((p["trade_id"], p["stop_loss_price"], reason, spot_price))
                        # 2. Predicted Terminal Target Hit
                        elif live_ltp >= target_p:
                            tgt_pts_val = round(target_p - entry_price, 1)
                            to_close.append((p["trade_id"], target_p, f"🎯 Auto Target Hit (+{tgt_pts_val} pts)", spot_price))

            for tid, exit_p, outcome, s_price in to_close:
                self.close_position(tid, exit_price=exit_p, outcome=outcome, exit_spot=s_price)

            self._save_wallet()
        except Exception as e:
            print("Error in update_positions_with_live_ticks:", e)

    def get_wallet(self):
        # Update live positions against real live market ticks
        self.update_positions_with_live_ticks()

        # Calculate unrealized live PnL across active positions
        unrealized_pnl = sum(p.get("live_pnl_rupees", 0.0) for p in self.wallet.get("active_positions", []))
        utilized_margin = sum(p.get("margin_required", 0.0) for p in self.wallet.get("active_positions", []))
        
        available_margin = max(0.0, self.wallet["cash_balance"] - utilized_margin)
        net_equity = self.wallet["cash_balance"] + unrealized_pnl

        return {
            "initial_capital": self.wallet["initial_capital"],
            "cash_balance": self.wallet["cash_balance"],
            "available_margin": round(available_margin, 2),
            "utilized_margin": round(utilized_margin, 2),
            "unrealized_pnl": round(unrealized_pnl, 2),
            "realized_pnl": self.wallet["realized_pnl"],
            "net_equity": round(net_equity, 2),
            "total_pnl_pct": self.wallet["total_pnl_pct"],
            "today_pnl": self.wallet["today_pnl"],
            "total_trades": self.wallet["total_trades"],
            "win_trades": self.wallet["win_trades"],
            "loss_trades": self.wallet["loss_trades"],
            "win_rate": self.wallet["win_rate"],
            "auto_pilot_enabled": self.wallet.get("auto_pilot_enabled", True),
            "active_positions": self.wallet.get("active_positions", [])
        }

    def place_order(self, direction="CALL", strike=0.0, lots=2, entry_price=0.0,
                    target_pts=15.0, sl_pts=7.5, spot_price=0.0,
                    projected_target_spot=0.0, target_reason="", setup_type="MANUAL"):
        """
        Executes a virtual trade order with Predictive Target Projection and 4-Tier Runner tracking.
        """
        now_dt = datetime.now()
        ts = now_dt.strftime("%Y-%m-%d %H:%M:%S")
        trade_id = f"VTRD_{now_dt.strftime('%Y%m%d_%H%M%S_%f')}"

        direction = direction.upper()
        option_type = "CE" if direction == "CALL" else "PE"
        lots = max(1, int(lots))
        qty = lots * 65
        strike = float(strike)
        entry_price = float(entry_price)
        target_pts = float(target_pts)
        sl_pts = float(sl_pts)
        spot_price = float(spot_price)

        # Auto-fetch live market data if strike or entry_price is not specified
        try:
            from duckdb_engine import duckdb_engine
            df = duckdb_engine.get_latest_option_chain()
            if df is not None and not df.empty:
                if spot_price <= 0:
                    spot_price = float(df['spot_price'].iloc[0])
                if strike <= 0:
                    strike = float(round(spot_price / 50.0) * 50)
                if entry_price <= 0:
                    matched = df[(df['strike'] == strike) & (df['type'] == option_type)]
                    if not matched.empty:
                        entry_price = float(matched['ltp'].iloc[0])
        except Exception as e:
            print("Error auto-fetching live price:", e)

        if strike <= 0:
            strike = 23650.0
        if entry_price <= 0:
            entry_price = 50.0  # Safe fallback if feed was empty
        if spot_price <= 0:
            spot_price = strike

        target_price = round(entry_price + target_pts, 2)
        sl_price = max(1.0, round(entry_price - sl_pts, 2))
        margin_required = round(entry_price * qty, 2)

        # Margin check
        current_utilized = sum(p.get("margin_required", 0.0) for p in self.wallet.get("active_positions", []))
        if (current_utilized + margin_required) > (self.wallet["cash_balance"] * 1.5):
            return {
                "status": "error",
                "message": f"Insufficient virtual capital! Margin needed: ₹{margin_required:,.2f}, Available: ₹{(self.wallet['cash_balance'] - current_utilized):,.2f}"
            }

        contract_name = f"NIFTY {int(strike)} {option_type}"

        new_position = {
            "trade_id": trade_id,
            "timestamp": ts,
            "date": ts[:10],
            "direction": direction,
            "option_type": option_type,
            "contract": contract_name,
            "strike": strike,
            "lots": lots,
            "qty": qty,
            "entry_spot": spot_price,
            "entry_price": entry_price,
            "current_ltp": entry_price,
            "live_pnl_pts": 0.0,
            "live_pnl_rupees": 0.0,
            "peak_ltp": entry_price,
            "peak_pts": 0.0,
            "target_price": target_price,
            "target_pts": target_pts,
            "stop_loss_price": sl_price,
            "stop_loss_pts": sl_pts,
            "projected_target_spot": projected_target_spot if projected_target_spot > 0 else (spot_price + 35.0 if direction == "CALL" else spot_price - 35.0),
            "projected_target_pts": target_pts,
            "projected_target_ltp": target_price,
            "target_reason": target_reason or ("AOC Resistance Target" if direction == "CALL" else "AOC Support Target"),
            "setup_type": setup_type,
            "tsl_stage": f"INITIAL (SL: ₹{sl_price:.1f})",
            "margin_required": margin_required,
            "trailed_to_cost": False,
            "status": "OPEN"
        }

        # Add to active positions
        if "active_positions" not in self.wallet:
            self.wallet["active_positions"] = []
        self.wallet["active_positions"].append(new_position)
        self._save_wallet()

        # Insert into DB
        try:
            conn = sqlite3.connect(STANDALONE_DB_FILE, timeout=30.0)
            conn.execute("""
                INSERT INTO virtual_trades 
                (trade_id, timestamp, date, direction, option_type, contract, strike,
                 lots, quantity, entry_spot, entry_price, stop_loss_price, target_price, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'OPEN')
            """, (trade_id, ts, ts[:10], direction, option_type, contract_name, strike,
                  lots, qty, spot_price, entry_price, sl_price, target_price))
            conn.commit()
            conn.close()
        except Exception as e:
            print("Error inserting into standalone DB:", e)

        return {
            "status": "ok",
            "message": f"Order executed: {contract_name} ({direction}) @ ₹{entry_price} | Predicted Target: ₹{target_price} (+{target_pts} pts)",
            "trade": new_position
        }

    def auto_execute_signal(self, direction, spot_price, target_spot, reason="QUANT_FORECAST_SIGNAL", lots=2):
        """
        Algorithmic Auto-Execution of verified High-Probability S/R Swing Signals.
        Enforces strict single-trade lifecycle (1 active trade at a time).
        """
        if not self.wallet.get("auto_pilot_enabled", True):
            return {"status": "skipped", "message": "Auto-Pilot is currently disabled"}

        # Strict Single-Trade rule: Never enter a second trade if one is running
        if self.wallet.get("active_positions"):
            return {"status": "skipped", "message": "Position already active (1 trade at a time rule)"}

        # Select Delta ~0.68 ITM Strike
        # For CALL: 1 strike below ATM (spot_price - 50)
        # For PUT: 1 strike above ATM (spot_price + 50)
        atm_strike = round(spot_price / 50.0) * 50.0
        if direction.upper() == "CALL":
            selected_strike = atm_strike - 50.0
        else:
            selected_strike = atm_strike + 50.0

        # Calculate projected option target based on spot distance * 0.68 Delta
        expected_spot_move = abs(target_spot - spot_price)
        projected_option_pts = max(18.0, round(expected_spot_move * 0.68, 1))

        res = self.place_order(
            direction=direction,
            strike=selected_strike,
            lots=lots,
            target_pts=projected_option_pts,
            sl_pts=7.5,
            spot_price=spot_price,
            projected_target_spot=target_spot,
            target_reason=reason,
            setup_type="AUTO_PILOT"
        )
        return res

    def toggle_autopilot(self):
        cur = self.wallet.get("auto_pilot_enabled", True)
        self.wallet["auto_pilot_enabled"] = not cur
        self._save_wallet()
        return {"status": "ok", "auto_pilot_enabled": self.wallet["auto_pilot_enabled"]}

    def close_position(self, trade_id, exit_price=None, outcome="MANUAL_CLOSE", exit_spot=None):
        """Closes an active position and books realized profit/loss"""
        matched = None
        pos_list = self.wallet.get("active_positions", [])

        for p in pos_list:
            if p["trade_id"] == trade_id:
                matched = p
                break

        if not matched:
            return {"status": "error", "message": f"Position {trade_id} not found"}

        now_dt = datetime.now()
        exit_ts = now_dt.strftime("%Y-%m-%d %H:%M:%S")

        entry_price = float(matched["entry_price"])
        qty = int(matched["qty"])

        actual_exit = float(exit_price if exit_price is not None else matched.get("current_ltp", entry_price))
        pts = round(actual_exit - entry_price, 2)

        if outcome == "TARGET_HIT":
            actual_exit = float(matched.get("target_price", actual_exit))
            pts = round(actual_exit - entry_price, 2)
            exit_reason = f"🎯 Auto Target Hit (+{pts:+.1f} pts)"
        elif outcome == "SL_HIT":
            actual_exit = float(matched.get("stop_loss_price", actual_exit))
            pts = round(actual_exit - entry_price, 2)
            exit_reason = f"🛑 Auto Stop Loss Hit ({pts:+.1f} pts)"
        elif outcome == "TRAIL_SL_COST":
            actual_exit = entry_price
            pts = 0.0
            exit_reason = "🛡️ Auto Trailed SL Exit at Cost (+0.0 pts)"
        elif outcome == "MANUAL_CLOSE":
            exit_reason = f"⚡ Manual Exit ({pts:+.1f} pts)"
        elif isinstance(outcome, str) and any(k in outcome for k in ["TSL", "Target", "SL", "Stop Loss", "Cost", "Auto", "Lock", "🎯", "🛑", "⚡", "🛡️"]):
            exit_reason = outcome
        else:
            if pts >= 0:
                exit_reason = f"⚡ Auto TSL Profit Lock ({pts:+.1f} pts)"
            else:
                exit_reason = f"🛑 Auto Stop Loss Exit ({pts:+.1f} pts)"

        pnl_pts = round(actual_exit - entry_price, 2)
        pnl_rupees = round(pnl_pts * qty, 2)
        pnl_pct = round((pnl_pts / entry_price * 100.0), 2) if entry_price > 0 else 0.0

        # Remove from active positions
        self.wallet["active_positions"] = [p for p in pos_list if p["trade_id"] != trade_id]

        # Update wallet statistics
        self.wallet["realized_pnl"] = round(self.wallet.get("realized_pnl", 0.0) + pnl_rupees, 2)
        self.wallet["cash_balance"] = round(self.wallet.get("initial_capital", 100000.0) + self.wallet["realized_pnl"], 2)
        self.wallet["total_pnl_pct"] = round((self.wallet["realized_pnl"] / self.wallet["initial_capital"]) * 100.0, 2)
        self.wallet["today_pnl"] = round(self.wallet.get("today_pnl", 0.0) + pnl_rupees, 2)
        self.wallet["total_trades"] = self.wallet.get("total_trades", 0) + 1

        if pnl_rupees > 0:
            self.wallet["win_trades"] = self.wallet.get("win_trades", 0) + 1
        elif pnl_rupees < 0:
            self.wallet["loss_trades"] = self.wallet.get("loss_trades", 0) + 1

        tot = self.wallet["win_trades"] + self.wallet["loss_trades"]
        self.wallet["win_rate"] = round((self.wallet["win_trades"] / tot * 100.0), 1) if tot > 0 else 0.0

        self._save_wallet()

        # Update DB
        try:
            conn = sqlite3.connect(STANDALONE_DB_FILE, timeout=30.0)
            conn.execute("""
                UPDATE virtual_trades
                SET exit_timestamp = ?, exit_spot = ?, exit_price = ?, exit_reason = ?,
                    pnl_pts = ?, pnl_rupees = ?, pnl_pct = ?, status = 'CLOSED'
                WHERE trade_id = ?
            """, (exit_ts, exit_spot or matched["entry_spot"], actual_exit, exit_reason,
                  pnl_pts, pnl_rupees, pnl_pct, trade_id))
            conn.commit()
            conn.close()
        except Exception as e:
            print("Error updating trade exit in standalone DB:", e)

        return {
            "status": "ok",
            "message": f"Position closed: {exit_reason} -> P&L: ₹{pnl_rupees:+,.2f} ({pnl_pct:+.1f}%)",
            "pnl_rupees": pnl_rupees,
            "pnl_pts": pnl_pts,
            "wallet": self.get_wallet()
        }

    def trail_sl_to_cost(self, trade_id):
        """Locks SL to Entry Price (Cost-to-Cost)"""
        pos_list = self.wallet.get("active_positions", [])
        for p in pos_list:
            if p["trade_id"] == trade_id:
                p["stop_loss_price"] = p["entry_price"]
                p["trailed_to_cost"] = True
                self._save_wallet()
                return {"status": "ok", "message": f"SL Trailed to Cost (₹{p['entry_price']:.2f})"}
        return {"status": "error", "message": "Trade not found"}

    def update_live_positions(self, ticks, spot_price):
        """Updates live LTP, PnL, Trailing SL, and auto-exits on target or SL"""
        if not self.wallet.get("active_positions") or not ticks:
            return

        pos_list = list(self.wallet["active_positions"])
        modified = False

        for p in pos_list:
            stk = p["strike"]
            opt_type = p["option_type"]

            # Find matching tick
            for t in ticks:
                if t.get("type") == opt_type and float(t.get("strike", 0)) == float(stk):
                    cur_ltp = float(t.get("ltp") or p["entry_price"])
                    p["current_ltp"] = cur_ltp
                    diff = round(cur_ltp - p["entry_price"], 2)
                    p["live_pnl_pts"] = diff
                    p["live_pnl_rupees"] = round(diff * p["qty"], 2)

                    if cur_ltp > p["peak_ltp"]:
                        p["peak_ltp"] = cur_ltp
                        p["peak_pts"] = diff

                    # Trailing SL auto-lock if profit crosses 50% target
                    if not p["trailed_to_cost"] and diff >= (p["target_pts"] * 0.5):
                        p["stop_loss_price"] = p["entry_price"]
                        p["trailed_to_cost"] = True

                    # Check Target Hit
                    if cur_ltp >= p["target_price"]:
                        self.close_position(p["trade_id"], exit_price=cur_ltp, outcome="TARGET_HIT", exit_spot=spot_price)
                        modified = True
                        break

                    # Check Stop Loss Hit
                    if cur_ltp <= p["stop_loss_price"]:
                        outcome = "TRAIL_SL_COST" if p["trailed_to_cost"] else "SL_HIT"
                        self.close_position(p["trade_id"], exit_price=cur_ltp, outcome=outcome, exit_spot=spot_price)
                        modified = True
                        break

                    modified = True
                    break

        if modified and self.wallet.get("active_positions"):
            self._save_wallet()

    def get_trades_history(self, limit=500, date=None):
        """Returns closed trades ledger from DB, optionally filtered by date (YYYY-MM-DD)"""
        try:
            conn = sqlite3.connect(STANDALONE_DB_FILE, timeout=30.0)
            conn.row_factory = sqlite3.Row
            if date:
                rows = conn.execute("""
                    SELECT * FROM virtual_trades 
                    WHERE date = ? OR timestamp LIKE ?
                    ORDER BY id DESC LIMIT ?
                """, (date, f"{date}%", limit)).fetchall()
            else:
                rows = conn.execute("""
                    SELECT * FROM virtual_trades ORDER BY id DESC LIMIT ?
                """, (limit,)).fetchall()
            conn.close()
            return [dict(r) for r in rows]
        except Exception:
            return []

    def export_trades_csv(self, date=None):
        """Generates a CSV formatted string of manual virtual trades, optionally filtered by date"""
        import csv
        import io
        trades = self.get_trades_history(limit=5000, date=date)
        output = io.StringIO()
        fieldnames = [
            "trade_id", "date", "timestamp", "exit_timestamp", "direction",
            "option_type", "contract", "strike", "lots", "quantity",
            "entry_spot", "entry_price", "stop_loss_price", "target_price",
            "exit_spot", "exit_price", "exit_reason", "pnl_pts", "pnl_rupees",
            "pnl_pct", "status"
        ]
        writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction='ignore')
        writer.writeheader()
        for t in trades:
            writer.writerow(t)
        return output.getvalue()

    def delete_trade(self, trade_id):
        try:
            conn = sqlite3.connect(STANDALONE_DB_FILE, timeout=30.0)
            conn.execute("DELETE FROM virtual_trades WHERE trade_id = ?", (trade_id,))
            conn.commit()
            conn.close()
            return {"status": "ok", "message": f"Trade {trade_id} deleted."}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def reset_wallet(self, initial_capital=100000.0):
        """Wipes virtual trades and resets capital back to fresh amount"""
        initial_capital = float(initial_capital)
        self.wallet = {
            "initial_capital": initial_capital,
            "cash_balance": initial_capital,
            "utilized_margin": 0.0,
            "realized_pnl": 0.0,
            "total_pnl_pct": 0.0,
            "today_pnl": 0.0,
            "total_trades": 0,
            "win_trades": 0,
            "loss_trades": 0,
            "win_rate": 0.0,
            "active_positions": []
        }
        self._save_wallet()
        try:
            conn = sqlite3.connect(STANDALONE_DB_FILE, timeout=30.0)
            conn.execute("DELETE FROM virtual_trades;")
            conn.commit()
            conn.close()
        except Exception:
            pass

        return {
            "status": "ok",
            "message": f"Virtual wallet successfully reset to fresh ₹{initial_capital:,.2f}!",
            "wallet": self.get_wallet()
        }

# Global Standalone Instance
standalone_virtual_trader = StandaloneVirtualTrader()
