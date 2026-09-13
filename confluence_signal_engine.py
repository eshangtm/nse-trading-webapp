# ══════════════════════════════════════════════════════════════════
#  Confluence 9-Rule Signal Engine & Dynamic Auto Paper Trader
# ══════════════════════════════════════════════════════════════════
import os
import json
import sqlite3
import threading
import pandas as pd
from datetime import datetime, timedelta, timezone
from aoc_sr_engine import calculate_aoc_sr
from tot_signal_engine import calculate_tot_decision

IST_OFFSET = timedelta(hours=5, minutes=30)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "paper_trades.db")

def now_ist_str():
    return (datetime.now(timezone.utc).replace(tzinfo=None) + IST_OFFSET).strftime("%Y-%m-%d %H:%M:%S")

def evaluate_9_rules(call_oi_chg_pct, put_oi_chg_pct, spot_price=24175.0):
    """
    Evaluates the 9 Confluence Matrix Rules based on Call OI Change % and Put OI Change %.
    
    Returns dict with:
      - rule_id (1..9)
      - matrix ("Matrix 1", "Matrix 2", "Matrix 3")
      - signal ("BUY_CE", "BUY_PE", "NEUTRAL_EXIT")
      - name (Rule Title)
      - confidence (0-100)
      - call_state ("HEAVY_INC", "INC", "STABLE", "DEC", "HEAVY_DEC")
      - put_state ("HEAVY_INC", "INC", "STABLE", "DEC", "HEAVY_DEC")
    """
    c_chg = float(call_oi_chg_pct or 0.0)
    p_chg = float(put_oi_chg_pct or 0.0)

    # Classify Call OI State
    if c_chg >= 5.0: c_state = "HEAVY_INC"
    elif c_chg > 1.0: c_state = "INC"
    elif c_chg < -5.0: c_state = "HEAVY_DEC"
    elif c_chg < -1.0: c_state = "DEC"
    else: c_state = "STABLE"

    # Classify Put OI State
    if p_chg >= 5.0: p_state = "HEAVY_INC"
    elif p_chg > 1.0: p_state = "INC"
    elif p_chg < -5.0: p_state = "HEAVY_DEC"
    elif p_chg < -1.0: p_state = "DEC"
    else: p_state = "STABLE"

    # --- Matrix 3: Full Confluence Cross Matrix (Best Results) ---
    if c_state in ["DEC", "HEAVY_DEC"] and p_state in ["INC", "HEAVY_INC"]:
        return {
            "rule_id": 8,
            "matrix": "Matrix 3: Full Confluence Cross",
            "signal": "BUY_CE",
            "name": "Super Bullish (Bull Run)",
            "reason": f"Call OI Heavily Decreasing ({c_chg:+.1f}%) + Put OI Heavily Increasing ({p_chg:+.1f}%)",
            "confidence": 98.0,
            "call_state": c_state, "put_state": p_state
        }
    if c_state in ["INC", "HEAVY_INC"] and p_state in ["DEC", "HEAVY_DEC"]:
        return {
            "rule_id": 9,
            "matrix": "Matrix 3: Full Confluence Cross",
            "signal": "BUY_PE",
            "name": "Super Bearish (Bloodbath)",
            "reason": f"Call OI Heavily Increasing ({c_chg:+.1f}%) + Put OI Heavily Decreasing ({p_chg:+.1f}%)",
            "confidence": 98.0,
            "call_state": c_state, "put_state": p_state
        }
    if c_state in ["DEC", "HEAVY_DEC"] and p_state in ["DEC", "HEAVY_DEC"]:
        return {
            "rule_id": 7,
            "matrix": "Matrix 3: Full Confluence Cross",
            "signal": "NEUTRAL_EXIT",
            "name": "SideWays (Unpredictable Unwinding)",
            "reason": f"Call OI Decreasing ({c_chg:+.1f}%) + Put OI Decreasing ({p_chg:+.1f}%)",
            "confidence": 70.0,
            "call_state": c_state, "put_state": p_state
        }

    # --- Matrix 2: Call Shift Rules ---
    if c_state in ["INC", "HEAVY_INC"] and p_state in ["INC", "HEAVY_INC"]:
        return {
            "rule_id": 4,
            "matrix": "Matrix 2: Call Shift",
            "signal": "NEUTRAL_EXIT",
            "name": "SideWays (Rangebound Tug-of-War)",
            "reason": f"Call OI Increasing ({c_chg:+.1f}%) + Put OI Increasing ({p_chg:+.1f}%)",
            "confidence": 75.0,
            "call_state": c_state, "put_state": p_state
        }
    if c_state in ["DEC", "HEAVY_DEC"] and p_state == "STABLE":
        return {
            "rule_id": 5,
            "matrix": "Matrix 2: Call Shift",
            "signal": "BUY_CE",
            "name": "Bullish (Call Cover Breakout)",
            "reason": f"Call OI Decreasing ({c_chg:+.1f}%) + Put OI Stable ({p_chg:+.1f}%)",
            "confidence": 88.0,
            "call_state": c_state, "put_state": p_state
        }
    if c_state in ["INC", "HEAVY_INC"] and p_state == "STABLE":
        return {
            "rule_id": 6,
            "matrix": "Matrix 2: Call Shift",
            "signal": "BUY_PE",
            "name": "Bearish (Call Resistance Build-up)",
            "reason": f"Call OI Increasing ({c_chg:+.1f}%) + Put OI Stable ({p_chg:+.1f}%)",
            "confidence": 88.0,
            "call_state": c_state, "put_state": p_state
        }

    # --- Matrix 1: Baseline Stable Rules ---
    if c_state == "STABLE" and p_state in ["INC", "HEAVY_INC"]:
        return {
            "rule_id": 2,
            "matrix": "Matrix 1: Baseline Stable",
            "signal": "BUY_CE",
            "name": "Bullish (Call Breakout)",
            "reason": f"Call OI Stable ({c_chg:+.1f}%) + Put OI Heavily Increasing ({p_chg:+.1f}%)",
            "confidence": 85.0,
            "call_state": c_state, "put_state": p_state
        }
    if c_state == "STABLE" and p_state in ["DEC", "HEAVY_DEC"]:
        return {
            "rule_id": 3,
            "matrix": "Matrix 1: Baseline Stable",
            "signal": "BUY_PE",
            "name": "Bearish (Support Breakdown)",
            "reason": f"Call OI Stable ({c_chg:+.1f}%) + Put OI Heavily Decreasing ({p_chg:+.1f}%)",
            "confidence": 85.0,
            "call_state": c_state, "put_state": p_state
        }

    # Default Rule 1
    return {
        "rule_id": 1,
        "matrix": "Matrix 1: Baseline Stable",
        "signal": "NEUTRAL_EXIT",
        "name": "SideWays (Unpredictable / Stable)",
        "reason": f"Call OI Stable ({c_chg:+.1f}%) + Put OI Stable ({p_chg:+.1f}%)",
        "confidence": 60.0,
        "call_state": c_state, "put_state": p_state
    }


class ConfluencePaperTrader:
    """
    Manages Dynamic Paper Trading Execution based on 9-Rule Confluence Matrix:
    - Auto Entry: Rule 2, 5, 8 -> BUY_CE; Rule 3, 6, 9 -> BUY_PE
    - Auto Exit: Switched to opposite signal or NEUTRAL_EXIT -> TURANT CLOSE
    """
    def __init__(self, db_path=DB_PATH):
        self.db_path = db_path
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._lock = threading.Lock()
        self.auto_trader_enabled = True
        self.active_position = None  # Dict of active trade or None
        self._init_db()
        self._load_active_position()

    def get_connection(self):
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._lock:
            conn = self.get_connection()
            try:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS confluence_paper_trades (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        trade_id TEXT UNIQUE,
                        entry_time TEXT,
                        exit_time TEXT,
                        symbol TEXT,
                        strike REAL,
                        option_type TEXT,
                        rule_id INTEGER,
                        rule_name TEXT,
                        entry_price REAL,
                        exit_price REAL,
                        quantity INTEGER,
                        pnl REAL,
                        pnl_pct REAL,
                        status TEXT,
                        exit_reason TEXT
                    );
                """)
                conn.commit()
            finally:
                conn.close()

    def _load_active_position(self):
        with self._lock:
            conn = self.get_connection()
            try:
                row = conn.execute("SELECT * FROM confluence_paper_trades WHERE status = 'OPEN' ORDER BY id DESC LIMIT 1;").fetchone()
                if row:
                    self.active_position = dict(row)
                else:
                    self.active_position = None
            except Exception as e:
                print("Error loading position:", e)
            finally:
                conn.close()

    def process_tick(self, ticks, spot_price, current_timestamp=None):
        """
        Process latest option ticks, calculate 9-Rule signal, execute Auto-Entry & Auto-Exit
        with Target (+35 pts), Stop Loss (-15 pts), and Trailing Stop Loss (TSL) to Cost-to-Cost.
        """
        if not ticks or spot_price <= 0:
            return None

        # Group ticks by strike and sort
        strikes_map = {}
        for t in ticks:
            st = t.get("strike", 0)
            st_type = t.get("type", "CE")
            if st not in strikes_map: strikes_map[st] = {}
            strikes_map[st][st_type] = t

        sorted_strikes = sorted(list(strikes_map.keys()))
        if not sorted_strikes:
            return None

        # Find ATM Strike
        atm_strike = sorted_strikes[0]
        min_diff = abs(spot_price - atm_strike)
        for st in sorted_strikes:
            diff = abs(spot_price - st)
            if diff < min_diff:
                min_diff = diff
                atm_strike = st

        # Focus OI change calculations on ATM ± 4 strikes (institutional active band)
        atm_idx = sorted_strikes.index(atm_strike)
        start_idx = max(0, atm_idx - 4)
        end_idx = min(len(sorted_strikes), atm_idx + 5)
        active_band_strikes = sorted_strikes[start_idx:end_idx]

        total_ce_oic_pct = 0.0
        total_pe_oic_pct = 0.0
        ce_count = 0
        pe_count = 0

        for st in active_band_strikes:
            ce_tick = strikes_map.get(st, {}).get("CE")
            pe_tick = strikes_map.get(st, {}).get("PE")
            if ce_tick and (ce_tick.get("oi") or 0) > 0:
                total_ce_oic_pct += float(ce_tick.get("oi_change_pct") or 0.0)
                ce_count += 1
            if pe_tick and (pe_tick.get("oi") or 0) > 0:
                total_pe_oic_pct += float(pe_tick.get("oi_change_pct") or 0.0)
                pe_count += 1

        avg_ce_oic = (total_ce_oic_pct / ce_count) if ce_count > 0 else 0.0
        avg_pe_oic = (total_pe_oic_pct / pe_count) if pe_count > 0 else 0.0

        # Evaluate 9-Rule Confluence Matrix & Chapter 5 TOT Engine
        signal_info = evaluate_9_rules(avg_ce_oic, avg_pe_oic, spot_price=spot_price)
        conf_signal = signal_info["signal"]
        rule_id = signal_info["rule_id"]

        sr_data = calculate_aoc_sr(ticks, spot_price, current_timestamp=current_timestamp)
        tot_data = calculate_tot_decision(sr_data, spot_price)
        tot_signal = tot_data.get("recommended_signal", "NEUTRAL_EXIT") if tot_data else "NEUTRAL_EXIT"

        # Combined Final Signal Decision: Trigger on Confluence OR TOT Signal
        final_signal = conf_signal
        trade_name = signal_info["name"]
        if conf_signal == "NEUTRAL_EXIT" and tot_signal in ["BUY_CE", "BUY_PE"]:
            final_signal = tot_signal
            trade_name = f"TOT Engine ({tot_data.get('sentiment')})"

        signal = final_signal

        atm_ce_tick = strikes_map.get(atm_strike, {}).get("CE", {})
        atm_pe_tick = strikes_map.get(atm_strike, {}).get("PE", {})

        # Current Active Position Check & Live PnL Update
        current_pnl = 0.0
        current_pnl_pct = 0.0
        current_pts = 0.0
        current_option_ltp = 0.0
        target_pts = 35.0
        sl_pts = 15.0

        if self.active_position:
            pos_type = self.active_position["option_type"]
            matched_tick = atm_ce_tick if pos_type == "CE" else atm_pe_tick
            current_option_ltp = float(matched_tick.get("ltp") or self.active_position["entry_price"])
            entry_p = float(self.active_position["entry_price"])
            qty = int(self.active_position["quantity"])

            current_pts = round(current_option_ltp - entry_p, 2)
            current_pnl = round(current_pts * qty, 2)
            current_pnl_pct = round((current_pts / entry_p * 100.0), 2) if entry_p > 0 else 0.0

            target_price = entry_p + target_pts
            initial_sl_price = max(1.0, entry_p - sl_pts)
            
            # Trailing SL Logic: At 50% target (+17.5 pts), trail SL to Entry Cost-to-Cost
            trailing_sl_price = entry_p if current_pts >= (target_pts * 0.5) else initial_sl_price

            # --- AUTO-EXIT ENGINE ---
            should_exit = False
            exit_reason = ""

            if current_option_ltp >= target_price:
                should_exit = True
                exit_reason = f"🎯 Target Hit (+{current_pts:.1f} pts / +{current_pnl_pct:.1f}%)"
            elif current_option_ltp <= trailing_sl_price:
                should_exit = True
                if trailing_sl_price >= entry_p:
                    exit_reason = f"🛡️ Trailing SL Hit at Cost (₹{entry_p:.1f})"
                else:
                    exit_reason = f"🛑 Stop Loss Hit (-{abs(current_pts):.1f} pts)"
            elif pos_type == "CE" and signal == "BUY_PE":
                should_exit = True
                exit_reason = f"⚡ Reversal to {trade_name}"
            elif pos_type == "PE" and signal == "BUY_CE":
                should_exit = True
                exit_reason = f"⚡ Reversal to {trade_name}"

            if should_exit and self.auto_trader_enabled:
                self._execute_exit(current_option_ltp, exit_reason, timestamp=current_timestamp)

        # --- AUTO-ENTRY ENGINE ---
        if not self.active_position and self.auto_trader_enabled:
            if signal == "BUY_CE":
                target_tick = atm_ce_tick
                if target_tick and target_tick.get("ltp"):
                    entry_ltp = float(target_tick["ltp"])
                    symbol = target_tick.get("symbol", f"NSE:NIFTY26AUG{int(atm_strike)}CE")
                    self._execute_entry(symbol, atm_strike, "CE", entry_ltp, rule_id, trade_name, qty=65, timestamp=current_timestamp)

            elif signal == "BUY_PE":
                target_tick = atm_pe_tick
                if target_tick and target_tick.get("ltp"):
                    entry_ltp = float(target_tick["ltp"])
                    symbol = target_tick.get("symbol", f"NSE:NIFTY26AUG{int(atm_strike)}PE")
                    self._execute_entry(symbol, atm_strike, "PE", entry_ltp, rule_id, trade_name, qty=65, timestamp=current_timestamp)

        # Construct status summary
        return {
            "timestamp": current_timestamp or now_ist_str(),
            "spot_price": spot_price,
            "avg_ce_oic": round(avg_ce_oic, 2),
            "avg_pe_oic": round(avg_pe_oic, 2),
            "signal": signal_info,
            "tot_data": tot_data,
            "auto_trader_enabled": self.auto_trader_enabled,
            "active_position": {
                **self.active_position,
                "current_ltp": current_option_ltp,
                "current_pts": current_pts,
                "current_pnl": current_pnl,
                "current_pnl_pct": current_pnl_pct,
                "target_price": round(float(self.active_position["entry_price"]) + target_pts, 2),
                "sl_price": round(max(0.5, float(self.active_position["entry_price"]) - sl_pts), 2),
                "trailing_sl_price": round(float(self.active_position["entry_price"]) if current_pts >= (target_pts * 0.5) else max(0.5, float(self.active_position["entry_price"]) - sl_pts), 2)
            } if self.active_position else None,
            "total_stats": self.get_trade_statistics()
        }

    def _execute_entry(self, symbol, strike, option_type, entry_price, rule_id, rule_name, qty=65, timestamp=None):
        import uuid
        trade_id = str(uuid.uuid4())[:8]
        now_str = timestamp or now_ist_str()

        with self._lock:
            conn = self.get_connection()
            try:
                conn.execute("""
                    INSERT INTO confluence_paper_trades (
                        trade_id, entry_time, symbol, strike, option_type,
                        rule_id, rule_name, entry_price, quantity, status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'OPEN');
                """, (trade_id, now_str, symbol, strike, option_type, rule_id, rule_name, entry_price, qty))
                conn.commit()

                self.active_position = {
                    "trade_id": trade_id,
                    "entry_time": now_str,
                    "symbol": symbol,
                    "strike": strike,
                    "option_type": option_type,
                    "rule_id": rule_id,
                    "rule_name": rule_name,
                    "entry_price": entry_price,
                    "quantity": qty,
                    "status": "OPEN"
                }
                try:
                    print(f"[AUTO-ENTRY] {option_type} Position Opened at Rs.{entry_price} (Rule {rule_id}: {rule_name}) - Qty: {qty}")
                except Exception:
                    pass
            except Exception as e:
                print("Error executing entry:", e)
            finally:
                conn.close()

    def _execute_exit(self, exit_price, exit_reason, timestamp=None):
        if not self.active_position:
            return

        trade_id = self.active_position["trade_id"]
        entry_price = float(self.active_position["entry_price"])
        qty = int(self.active_position["quantity"])
        pnl = round((exit_price - entry_price) * qty, 2)
        pnl_pct = round(((exit_price - entry_price) / entry_price * 100.0), 2) if entry_price > 0 else 0.0
        now_str = timestamp or now_ist_str()

        with self._lock:
            conn = self.get_connection()
            try:
                conn.execute("""
                    UPDATE confluence_paper_trades
                    SET exit_time = ?, exit_price = ?, pnl = ?, pnl_pct = ?, status = 'CLOSED', exit_reason = ?
                    WHERE trade_id = ?;
                """, (now_str, exit_price, pnl, pnl_pct, exit_reason, trade_id))
                conn.commit()

                self.active_position = None
                try:
                    print(f"[AUTO-EXIT] Position Closed at Rs.{exit_price} | PnL: Rs.{pnl} ({pnl_pct}%) | Reason: {exit_reason}")
                except Exception:
                    pass
            except Exception as e:
                print("Error executing exit:", e)
            finally:
                conn.close()

    def close_active_position_manual(self):
        if not self.active_position:
            return {"status": "error", "message": "No active position."}

        ltp = float(self.active_position.get("current_ltp") or self.active_position["entry_price"])
        self._execute_exit(ltp, "Manually Closed by User")
        return {"status": "ok", "message": "Position closed manually."}

    def toggle_auto_trader(self, enabled: bool):
        self.auto_trader_enabled = enabled
        return {"status": "ok", "auto_trader_enabled": self.auto_trader_enabled}

    def get_trade_history(self, limit=500):
        with self._lock:
            conn = self.get_connection()
            try:
                rows = conn.execute("SELECT * FROM confluence_paper_trades ORDER BY id DESC LIMIT ?;", (limit,)).fetchall()
                results = []
                for r in rows:
                    item = dict(r)
                    entry_p = float(item.get("entry_price") or 0.0)
                    exit_p = float(item.get("exit_price") or 0.0)
                    
                    if item.get("status") == "CLOSED" and exit_p > 0:
                        pts = round(exit_p - entry_p, 2)
                    elif self.active_position and item.get("id") == self.active_position.get("id"):
                        cur_ltp = float(self.active_position.get("current_ltp") or entry_p)
                        pts = round(cur_ltp - entry_p, 2)
                        exit_p = cur_ltp
                    else:
                        pts = round(exit_p - entry_p, 2) if exit_p > 0 else 0.0
                    
                    item["points"] = pts
                    item["target_price"] = round(entry_p + 35.0, 2)
                    item["stop_loss"] = round(max(0.5, entry_p - 15.0), 2)

                    # Robust Duration Calculation
                    en_t = str(item.get("entry_time") or "").replace('T', ' ').strip()
                    ex_t = str(item.get("exit_time") or "").replace('T', ' ').strip()
                    dur_str = "—"
                    if en_t and ex_t:
                        try:
                            t1_clean = en_t.split('.')[0]
                            t2_clean = ex_t.split('.')[0]
                            dt1 = datetime.strptime(t1_clean, "%Y-%m-%d %H:%M:%S")
                            dt2 = datetime.strptime(t2_clean, "%Y-%m-%d %H:%M:%S")
                            diff_sec = int(abs((dt2 - dt1).total_seconds()))
                            m, s = divmod(diff_sec, 60)
                            h, m = divmod(m, 60)
                            dur_str = f"{h}h {m}m {s}s" if h > 0 else (f"{m}m {s}s" if m > 0 else f"{s}s")
                        except Exception:
                            dur_str = "—"
                    elif en_t and item.get("status") == "OPEN":
                        dur_str = "🟢 Active"
                    item["duration"] = dur_str
                    results.append(item)
                return results
            finally:
                conn.close()

    def clear_trade_history(self):
        """Clears closed paper trades from database."""
        with self._lock:
            conn = self.get_connection()
            try:
                conn.execute("DELETE FROM confluence_paper_trades WHERE status = 'CLOSED';")
                conn.commit()
                return {"status": "ok", "message": "Closed trade history cleared."}
            finally:
                conn.close()

    def get_trade_statistics(self):
        with self._lock:
            conn = self.get_connection()
            try:
                rows = conn.execute("SELECT pnl FROM confluence_paper_trades WHERE status = 'CLOSED';").fetchall()
                pnls = [r["pnl"] for r in rows if r["pnl"] is not None]
                if not pnls:
                    return {
                        "total_trades": 0, "win_trades": 0, "loss_trades": 0,
                        "win_rate": 0.0, "total_pnl": 0.0, "gross_profit": 0.0,
                        "gross_loss": 0.0, "profit_factor": 0.0, "avg_profit": 0.0,
                        "avg_loss": 0.0, "initial_capital": 100000.0, "current_balance": 100000.0
                    }

                wins = [p for p in pnls if p > 0]
                losses = [p for p in pnls if p <= 0]
                total_pnl = round(sum(pnls), 2)
                gross_profit = round(sum(wins), 2) if wins else 0.0
                gross_loss = round(abs(sum(losses)), 2) if losses else 0.0
                profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else (gross_profit if gross_profit > 0 else 0.0)
                win_rate = round(len(wins) / len(pnls) * 100.0, 1)
                avg_profit = round(gross_profit / len(wins), 2) if wins else 0.0
                avg_loss = round(gross_loss / len(losses), 2) if losses else 0.0

                stats = {
                    "total_trades": len(pnls),
                    "win_trades": len(wins),
                    "loss_trades": len(losses),
                    "win_rate": win_rate,
                    "total_pnl": total_pnl,
                    "gross_profit": gross_profit,
                    "gross_loss": gross_loss,
                    "profit_factor": profit_factor,
                    "avg_profit": avg_profit,
                    "avg_loss": avg_loss,
                    "initial_capital": 100000.0,
                    "current_balance": round(100000.0 + total_pnl, 2)
                }
                return stats
            finally:
                conn.close()

    def get_wallet_summary(self):
        """Returns virtual wallet capital status (₹1,00,000 starting balance)."""
        stats = self.get_trade_statistics()
        tot_pnl = stats.get("total_pnl", 0.0)
        initial = 100000.0
        current_balance = round(initial + tot_pnl, 2)
        
        used_margin = 0.0
        if self.active_position:
            used_margin = round(float(self.active_position.get("entry_price", 0)) * int(self.active_position.get("quantity", 0)), 2)

        available_margin = round(current_balance - used_margin, 2)

        return {
            "initial_capital": initial,
            "current_balance": current_balance,
            "realized_pnl": tot_pnl,
            "used_margin": used_margin,
            "available_margin": available_margin,
            "stats": stats
        }

    def get_chart_markers(self):
        """Returns TradingView formatted chart markers for entries, exits, and signals."""
        markers = []
        with self._lock:
            conn = self.get_connection()
            try:
                rows = conn.execute("SELECT * FROM confluence_paper_trades ORDER BY id ASC;").fetchall()
                for r in rows:
                    row = dict(r)
                    entry_time_str = row.get("entry_time", "")
                    exit_time_str = row.get("exit_time", "")
                    opt_type = row.get("option_type", "CE")
                    entry_px = float(row.get("entry_price") or 0)
                    exit_px = float(row.get("exit_price") or 0)
                    rule_nm = row.get("rule_name", "Confluence Signal")
                    pnl_val = float(row.get("pnl") or 0)
                    pnl_pct_val = float(row.get("pnl_pct") or 0)
                    reason = row.get("exit_reason", "")
                    pts_val = round(exit_px - entry_px, 2) if opt_type == "CE" else round(entry_px - exit_px, 2)

                    # Parse entry epoch timestamp
                    try:
                        if "T" in entry_time_str:
                            dt = datetime.fromisoformat(entry_time_str)
                        else:
                            dt = datetime.strptime(entry_time_str, "%Y-%m-%d %H:%M:%S")
                        entry_epoch = int(dt.timestamp())
                    except Exception:
                        entry_epoch = None

                    if entry_epoch:
                        if opt_type == "CE":
                            markers.append({
                                "time": entry_epoch,
                                "position": "belowBar",
                                "color": "#22c55e",
                                "shape": "arrowUp",
                                "text": f"🚀 BUY CE @ {entry_px:.1f}",
                                "details": {
                                    "title": "🟢 LONG CE ENTRY",
                                    "symbol": row.get("symbol", "NIFTY CE"),
                                    "time_str": entry_time_str.split("T")[-1] if "T" in entry_time_str else entry_time_str,
                                    "entry_price": f"₹{entry_px:.2f}",
                                    "rule": rule_nm,
                                    "target": f"₹{float(row.get('target_price') or entry_px+35):.2f} (+35 pts)",
                                    "sl": f"₹{float(row.get('stop_loss') or entry_px-15):.2f} (-15 pts)",
                                    "status": row.get("status", "OPEN")
                                }
                            })
                        else:
                            markers.append({
                                "time": entry_epoch,
                                "position": "aboveBar",
                                "color": "#ef4444",
                                "shape": "arrowDown",
                                "text": f"🩸 BUY PE @ {entry_px:.1f}",
                                "details": {
                                    "title": "🔴 LONG PE ENTRY",
                                    "symbol": row.get("symbol", "NIFTY PE"),
                                    "time_str": entry_time_str.split("T")[-1] if "T" in entry_time_str else entry_time_str,
                                    "entry_price": f"₹{entry_px:.2f}",
                                    "rule": rule_nm,
                                    "target": f"₹{float(row.get('target_price') or entry_px+35):.2f} (+35 pts)",
                                    "sl": f"₹{float(row.get('stop_loss') or entry_px-15):.2f} (-15 pts)",
                                    "status": row.get("status", "OPEN")
                                }
                            })

                    # Parse exit epoch timestamp if closed
                    if row.get("status") == "CLOSED" and exit_time_str and exit_px > 0:
                        try:
                            if "T" in exit_time_str:
                                dt_ex = datetime.fromisoformat(exit_time_str)
                            else:
                                dt_ex = datetime.strptime(exit_time_str, "%Y-%m-%d %H:%M:%S")
                            exit_epoch = int(dt_ex.timestamp())
                        except Exception:
                            exit_epoch = None

                        if exit_epoch:
                            is_win = pnl_val >= 0
                            is_tgt = "Target" in reason or "35" in reason or pts_val >= 30
                            marker_text = f"🎯 +{pts_val:.1f}pts" if is_tgt else (f"🛡️ TSL {pts_val:+.1f}pts" if "TSL" in reason or "Trailing" in reason else f"❌ {pts_val:+.1f}pts")
                            marker_color = "#38bdf8" if is_tgt else ("#22c55e" if is_win else "#ef4444")
                            
                            markers.append({
                                "time": exit_epoch,
                                "position": "aboveBar" if opt_type == "CE" else "belowBar",
                                "color": marker_color,
                                "shape": "circle",
                                "text": marker_text,
                                "details": {
                                    "title": f"{'🎯 TARGET REACHED' if is_tgt else ('🛡️ TSL EXIT' if 'TSL' in reason else '🏁 TRADE CLOSED')}",
                                    "symbol": row.get("symbol", ""),
                                    "time_str": exit_time_str.split("T")[-1] if "T" in exit_time_str else exit_time_str,
                                    "entry_price": f"₹{entry_px:.2f}",
                                    "exit_price": f"₹{exit_px:.2f}",
                                    "points": f"{pts_val:+.2f} pts",
                                    "pnl": f"{'+' if pnl_val>=0 else ''}₹{pnl_val:.2f} ({'+' if pnl_pct_val>=0 else ''}{pnl_pct_val:.2f}%)",
                                    "reason": reason,
                                    "status": "CLOSED"
                                }
                            })
            finally:
                conn.close()
        
        # Sort markers chronologically by time
        markers.sort(key=lambda m: m["time"])
        return markers

# Singleton Instance
confluence_paper_trader = ConfluencePaperTrader()
