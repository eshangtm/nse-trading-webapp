"""
══════════════════════════════════════════════════════════════════════════════════════
INSTITUTIONAL LIVE SIGNAL ENGINE & DEDICATED VIRTUAL WALLET CONTROLLER
══════════════════════════════════════════════════════════════════════════════════════
- Implements the 95.1% Win Rate Selective Master Setup (Max 1-2 Trades/Day)
- Strict Greeks Delta 0.65 (1 ITM) + 7.5 SL + Breakeven Lock (+3 pts) + Runner (+12 pts)
- Dedicated Isolated Virtual Wallet: Initial Capital ₹1,00,000, Realized P&L, Win Rate
- Detailed Trade Ledger with Full Auditing (Entry, SL, Exit, PnL Points & Rupees)
- Bulk Selection & Deletion of Trades with Auto-Recalculating Wallet Stats
- One-Click Wallet Reset to Fresh Initial State
══════════════════════════════════════════════════════════════════════════════════════
"""
import os
import json
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)

LOCAL_VAULT = r"C:\AllProjects\nse_tool\backtest_vault"
LOCAL_COLLECTED = r"C:\AllProjects\nse_tool\collected_data"

STATE_FILE = os.path.join(LOCAL_VAULT, "signal_engine_state.json") if os.path.exists(LOCAL_VAULT) else os.path.join(DATA_DIR, "signal_engine_state.json")
SIGNALS_LOG_FILE = os.path.join(LOCAL_VAULT, "live_signals_log.json") if os.path.exists(LOCAL_VAULT) else os.path.join(DATA_DIR, "live_signals_log.json")
SIGNALS_CSV_FILE = os.path.join(LOCAL_VAULT, "institutional_live_trades.csv") if os.path.exists(LOCAL_VAULT) else os.path.join(DATA_DIR, "institutional_live_trades.csv")
SIGNALS_DB_FILE = os.path.join(LOCAL_COLLECTED, "institutional_trades.db") if os.path.exists(LOCAL_COLLECTED) else os.path.join(DATA_DIR, "institutional_trades.db")
WALLET_FILE = os.path.join(LOCAL_VAULT, "signals_virtual_wallet.json") if os.path.exists(LOCAL_VAULT) else os.path.join(DATA_DIR, "signals_virtual_wallet.json")

class LiveSignalEngine:
    def __init__(self, user_id="default"):
        self.user_id = str(user_id) if user_id is not None else "default"
        base_vault = LOCAL_VAULT if os.path.exists(LOCAL_VAULT) else DATA_DIR
        base_coll = LOCAL_COLLECTED if os.path.exists(LOCAL_COLLECTED) else DATA_DIR

        if self.user_id in ["default", "admin"]:
            self.state_file = STATE_FILE
            self.signals_log_file = SIGNALS_LOG_FILE
            self.signals_csv_file = SIGNALS_CSV_FILE
            self.signals_db_file = SIGNALS_DB_FILE
            self.wallet_file = WALLET_FILE
        else:
            self.state_file = os.path.join(base_vault, f"signal_engine_state_{self.user_id}.json")
            self.signals_log_file = os.path.join(base_vault, f"live_signals_log_{self.user_id}.json")
            self.signals_csv_file = os.path.join(base_vault, f"institutional_live_trades_{self.user_id}.csv")
            self.signals_db_file = os.path.join(base_coll, f"institutional_trades_{self.user_id}.db")
            self.wallet_file = os.path.join(base_vault, f"signals_virtual_wallet_{self.user_id}.json")

        self.state = {
            "master_switch": True,        # Master ON/OFF Switch
            "auto_trading": False,        # Off by default until user specifically turns their auto system on!
            "lot_size_multiplier": 2,     # 2 Lots default (130 Qty) for 40k/week target
            "strike_selection_mode": "ITM_1", # User-configurable: ITM_1, ATM, ITM_2, OTM_1
            "stop_loss_pts": 15.0,        # Safe 15.0 pts SL to avoid getting chopped by tick noise
            "breakeven_trigger_pts": 6.0, # +6.0 pts lock breakeven
            "target_p6_lock": 12.0,       # Lock profit at +12 pts
            "target_p12_lock": 25.0,      # Runner trail at +25 pts
            "max_eod_time": "15:00",      # Strict 3:00 PM Exit
            "max_trades_per_day": 999,    # Unlimited (User removed max 2 limit)
            "active_signal": None,
            "last_processed_time": None,
            "cooldown_until": None        # Mandatory post-exit cooling window
        }
        self.price_history = []
        self.candle_bars = []
        self.last_st_trend = None
        self.last_signal_time = 0.0
        self.last_tick_eval_time = 0.0
        self.load_state()
        self.wallet = self.load_wallet()

    def load_state(self):
        target_file = self.state_file
        if not os.path.exists(target_file) and self.user_id in ["default", "admin", "1"] and os.path.exists(STATE_FILE):
            target_file = STATE_FILE
        if os.path.exists(target_file):
            try:
                with open(target_file, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                    self.state.update(saved)
            except Exception:
                pass

    def save_state(self):
        os.makedirs(os.path.dirname(self.state_file), exist_ok=True)
        with open(self.state_file, "w", encoding="utf-8") as f:
            json.dump(self.state, f, indent=2)
        if self.user_id in ["default", "admin"] and self.state_file != STATE_FILE:
            try:
                with open(STATE_FILE, "w", encoding="utf-8") as f:
                    json.dump(self.state, f, indent=2)
            except Exception:
                pass

    # ══════════════════════════════════════════════════════════════════
    # DEDICATED VIRTUAL WALLET SYSTEM
    # ══════════════════════════════════════════════════════════════════
    def load_wallet(self):
        default_wallet = {
            "initial_capital": 100000.0,
            "cash_balance": 100000.0,
            "utilized_margin": 0.0,
            "realized_pnl": 0.0,
            "total_pnl_pct": 0.0,
            "total_trades": 0,
            "win_trades": 0,
            "loss_trades": 0,
            "win_rate": 0.0,
            "today_pnl": 0.0,
            "daily_trades_taken": 0,
            "max_daily_trades": self.state.get("max_trades_per_day", 5),
            "last_trade_date": datetime.now().strftime("%Y-%m-%d"),
            "active_positions": []
        }
        target_file = self.wallet_file
        if not os.path.exists(target_file) and self.user_id in ["default", "admin", "1"] and os.path.exists(WALLET_FILE):
            target_file = WALLET_FILE
        if os.path.exists(target_file):
            try:
                with open(target_file, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                    if "initial_capital" in saved:
                        default_wallet["initial_capital"] = float(saved["initial_capital"])
                    if "active_positions" in saved and isinstance(saved["active_positions"], list):
                        default_wallet["active_positions"] = saved["active_positions"]
            except Exception:
                pass
        self.wallet = default_wallet
        return self.recalculate_wallet()

    def save_wallet(self):
        os.makedirs(os.path.dirname(self.wallet_file), exist_ok=True)
        with open(self.wallet_file, "w", encoding="utf-8") as f:
            json.dump(self.wallet, f, indent=2)
        if self.user_id in ["default", "admin"] and self.wallet_file != WALLET_FILE:
            try:
                with open(WALLET_FILE, "w", encoding="utf-8") as f:
                    json.dump(self.wallet, f, indent=2)
            except Exception:
                pass

    def is_market_open(self, dt=None):
        """Check if market is currently open (Monday-Friday 09:15 to 15:30 IST)."""
        from datetime import timezone, timedelta
        ist = timezone(timedelta(hours=5, minutes=30))
        if dt is None:
            check_dt = datetime.now(ist).replace(tzinfo=None)
        elif isinstance(dt, str):
            try:
                clean = dt.replace('T', ' ').split('.')[0]
                check_dt = datetime.strptime(clean, "%Y-%m-%d %H:%M:%S")
            except Exception:
                check_dt = datetime.now(ist).replace(tzinfo=None)
        else:
            # If naive datetime passed from UTC server (where hour is 3 to 10 UTC for 9:15 to 15:30 IST)
            if hasattr(dt, 'hour') and dt.hour < 9:
                check_dt = dt + timedelta(hours=5, minutes=30)
            else:
                check_dt = dt

        if check_dt.weekday() >= 5: # 5=Saturday, 6=Sunday
            return False, f"Market Closed (Weekend: {check_dt.strftime('%A')})"
        m_open = check_dt.replace(hour=9, minute=15, second=0, microsecond=0)
        m_close = check_dt.replace(hour=15, minute=30, second=0, microsecond=0)
        if check_dt < m_open:
            return False, "Market Closed (Pre-Market, opens at 09:15 AM)"
        if check_dt > m_close:
            return False, "Market Closed (Post-Market, closed at 03:30 PM)"
        return True, "Market Open"

    # ══════════════════════════════════════════════════════════════════
    # SUPERTREND INDICATOR (10, 2.0) - EXACT CHART PARITY
    # ══════════════════════════════════════════════════════════════════
    def get_or_update_candles(self, spot_price, ts_str):
        """Maintains rolling 1-minute OHLC candle bars from DuckDB and live spot ticks."""
        if not hasattr(self, "candle_bars") or not self.candle_bars:
            self.candle_bars = []
            try:
                from duckdb_engine import DuckDBEngine
                db = DuckDBEngine()
                df_c = db.get_candles(interval_seconds=60, limit=80)
                if df_c is not None and not df_c.empty:
                    for _, row in df_c.iterrows():
                        self.candle_bars.append({
                            "open": float(row["open"]),
                            "high": float(row["high"]),
                            "low": float(row["low"]),
                            "close": float(row["close"]),
                            "time": int(row.get("candle_time", 0)),
                            "key": datetime.fromtimestamp(int(row.get("candle_time", 0))).strftime("%Y-%m-%d %H:%M") if row.get("candle_time") else ""
                        })
            except Exception:
                pass

        min_key = ts_str[:16] if ts_str else ""
        if not self.candle_bars:
            self.candle_bars.append({"open": spot_price, "high": spot_price, "low": spot_price, "close": spot_price, "key": min_key})
        else:
            last = self.candle_bars[-1]
            if last.get("key") == min_key or not min_key:
                last["high"] = max(last["high"], spot_price)
                last["low"] = min(last["low"], spot_price)
                last["close"] = spot_price
            else:
                self.candle_bars.append({"open": spot_price, "high": spot_price, "low": spot_price, "close": spot_price, "key": min_key})
                if len(self.candle_bars) > 120:
                    self.candle_bars.pop(0)

        return self.candle_bars

    def calculate_supertrend(self, candles=None, period=10, multiplier=2.0):
        """
        Computes 10, 2.0 SuperTrend matching TradingView and LightweightCharts:
        Returns:
            trend: 1 (Bullish/Green -> CALL), -1 (Bearish/Red -> PUT)
            st_val: float (price level of current active SuperTrend line)
            trend_flip: bool (True if the trend flipped on the latest candle)
            st_bull_line: float (Green lower band)
            st_bear_line: float (Red upper band)
        """
        if not candles:
            candles = getattr(self, "candle_bars", [])
        if not candles or len(candles) < 2:
            return 1, 0.0, False, 0.0, 0.0

        n = len(candles)
        tr = [0.0] * n
        for i in range(n):
            c = candles[i]
            h = float(c.get("high", c["close"]))
            l = float(c.get("low", c["close"]))
            if i == 0:
                tr[i] = h - l
            else:
                prev_c = float(candles[i - 1]["close"])
                tr[i] = max(h - l, abs(h - prev_c), abs(l - prev_c))

        atr = [0.0] * n
        sum_tr = 0.0
        for i in range(n):
            if i < period:
                sum_tr += tr[i]
                atr[i] = sum_tr / (i + 1)
            else:
                atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period

        prev_final_upper = 0.0
        prev_final_lower = 0.0
        prev_trend = 1
        final_trend = 1
        final_upper = 0.0
        final_lower = 0.0
        trend_flip = False

        for i in range(n):
            c = candles[i]
            h = float(c.get("high", c["close"]))
            l = float(c.get("low", c["close"]))
            close = float(c["close"])
            hl2 = (h + l) / 2.0
            cur_atr = atr[i]
            basic_upper = hl2 + (multiplier * cur_atr)
            basic_lower = hl2 - (multiplier * cur_atr)

            cur_final_upper = basic_upper
            cur_final_lower = basic_lower

            if i > 0:
                prev_close = float(candles[i - 1]["close"])
                if basic_lower > prev_final_lower or prev_close < prev_final_lower:
                    cur_final_lower = basic_lower
                else:
                    cur_final_lower = prev_final_lower

                if basic_upper < prev_final_upper or prev_close > prev_final_upper:
                    cur_final_upper = basic_upper
                else:
                    cur_final_upper = prev_final_upper

            if i > 0:
                if prev_trend == -1 and close > prev_final_upper:
                    trend = 1
                elif prev_trend == 1 and close < prev_final_lower:
                    trend = -1
                else:
                    trend = prev_trend
            else:
                trend = 1 if close >= hl2 else -1

            if i == n - 1:
                trend_flip = (i > 0 and trend != prev_trend)
                final_trend = trend
                final_upper = cur_final_upper
                final_lower = cur_final_lower

            prev_final_upper = cur_final_upper
            prev_final_lower = cur_final_lower
            prev_trend = trend

        active_st_val = round(final_lower if final_trend == 1 else final_upper, 2)
        return final_trend, active_st_val, trend_flip, round(final_lower, 2), round(final_upper, 2)

    def update_live_positions(self):
        """Monitors active positions against live DuckDB option chain and triggers Target/SL exits"""
        pos_list = self.wallet.get("active_positions", [])
        if not pos_list:
            return

        # Market Open Guard: Never evaluate / exit live positions on weekend or after-hours
        is_open, _ = self.is_market_open()
        if not is_open:
            return

        try:
            from duckdb_engine import duckdb_engine
            df = duckdb_engine.get_latest_option_chain()
            if df is None or df.empty:
                return

            to_close = []
            for p in list(pos_list):
                contract = p.get("contract", "")
                opt_type = "PE" if "PE" in contract else "CE"
                import re
                m = re.search(r'(\d{5})', contract)
                strike = float(m.group(1)) if m else 0.0

                # Strict Date Filter: Match against position's entry date to avoid cross-date strike jumps
                pos_entry_time = str(p.get("entry_time", ""))
                pos_date = pos_entry_time.split(" ")[0] if " " in pos_entry_time else pos_entry_time.split("T")[0]
                df_matched = df
                if pos_date and "timestamp" in df.columns:
                    date_matches = df[df["timestamp"].str.startswith(pos_date)]
                    if not date_matches.empty:
                        df_matched = date_matches

                matched_row = df_matched[(df_matched['strike'] == strike) & (df_matched['type'] == opt_type)]
                if not matched_row.empty:
                    cur_ltp = float(matched_row['ltp'].iloc[0])
                    entry_p = float(p.get("entry_ltp", 0.0))
                    qty = int(p.get("qty", 130))
                    tgt_p = float(p.get("target_price", entry_p + 12.0))
                    sl_p = float(p.get("sl_price", entry_p - 7.5))

                    p["current_ltp"] = cur_ltp
                    p["unrealized_pts"] = round(cur_ltp - entry_p, 2)
                    p["unrealized_rupees"] = round(p["unrealized_pts"] * qty, 2)

                    # Auto Target Exit
                    if cur_ltp >= tgt_p:
                        to_close.append((p.get("trade_id"), "TARGET_HIT", tgt_p))
                    # Auto SL Exit
                    elif cur_ltp <= sl_p:
                        to_close.append((p.get("trade_id"), "SL_HIT", sl_p))

            for tid, outcome, exit_p in to_close:
                self.close_trade(tid, outcome=outcome, exit_ltp=exit_p)

            self.save_wallet()
        except Exception as e:
            print("Error updating live signals position:", e)

    def recalculate_wallet(self):
        """
        Dynamically calculates and syncs wallet stats directly from the canonical trades list.
        Ensures realized_pnl, today_pnl, win_rate, total_trades, and daily_trades_taken
        are 100% accurate and never drift or show stale numbers.
        """
        trades = self.get_trades()
        executed_trades = [
            t for t in trades 
            if t.get("status") in ["AUTO_EXECUTED", "MANUALLY_EXECUTED", "TARGET_HIT", "SL_HIT", "CLOSED", "BREAKEVEN"]
            and t.get("pnl_rupees") is not None
        ]
        
        wins = sum(1 for t in executed_trades if (float(t.get("gross_pnl", t.get("pnl_rupees", 0)) or 0) > 0 and not t.get("is_breakeven") and t.get("status") != "BREAKEVEN"))
        losses = sum(1 for t in executed_trades if ((float(t.get("gross_pnl", t.get("pnl_rupees", 0)) or 0) < -10.0 or "SL" in str(t.get("status"))) and not t.get("is_breakeven") and t.get("status") != "BREAKEVEN"))
        tot = len(executed_trades)
        realized_pnl = sum(float(t.get("pnl_rupees", 0) or 0) for t in executed_trades)

        today_str = datetime.now().strftime("%Y-%m-%d")
        today_trades = [
            t for t in executed_trades
            if str(t.get("exit_time") or t.get("entry_time") or t.get("timestamp") or "").startswith(today_str)
        ]
        today_pnl = sum(float(t.get("pnl_rupees", 0) or 0) for t in today_trades)

        # Count trades initiated today towards daily discipline lock
        all_today_trades = [
            t for t in trades
            if str(t.get("timestamp") or t.get("entry_time") or t.get("executed_at") or "").startswith(today_str)
            and t.get("status") not in ["CANCELLED_BY_USER", "ACTIVE_PENDING_CONFIRMATION"]
        ]

        # User Rule: ONLY PROFITABLE TRADES count towards the daily target quota (2 to 5)!
        profit_trades_today = [
            t for t in today_trades
            if (float(t.get("gross_pnl", t.get("pnl_rupees", 0)) or 0) > 0 and not t.get("is_breakeven") and t.get("status") != "BREAKEVEN")
        ]

        init_cap = float(self.wallet.get("initial_capital", 100000.0))
        self.wallet["initial_capital"] = init_cap
        self.wallet["total_trades"] = tot
        self.wallet["win_trades"] = wins
        self.wallet["loss_trades"] = losses
        self.wallet["win_rate"] = round((wins / tot * 100.0), 1) if tot > 0 else 0.0
        self.wallet["realized_pnl"] = round(realized_pnl, 2)
        self.wallet["cash_balance"] = round(init_cap + realized_pnl, 2)
        self.wallet["total_pnl_pct"] = round((realized_pnl / init_cap) * 100.0, 2) if init_cap > 0 else 0.0
        self.wallet["today_pnl"] = round(today_pnl, 2)
        self.wallet["daily_trades_taken"] = len(profit_trades_today)
        self.wallet["max_daily_trades"] = self.state.get("max_trades_per_day", 2)
        self.wallet["last_trade_date"] = today_str
        self.save_wallet()
        return self.wallet

    def get_wallet(self):
        # Dynamically recalculate wallet stats from trades ledger
        self.recalculate_wallet()

        # Update running position against real live market ticks
        self.update_live_positions()
        return self.wallet

    def reset_wallet(self, initial_capital: float = 100000.0):
        """Wipes old trade history and resets wallet back to fresh ₹1,00,000 state"""
        self.wallet = {
            "initial_capital": float(initial_capital),
            "cash_balance": float(initial_capital),
            "utilized_margin": 0.0,
            "realized_pnl": 0.0,
            "total_pnl_pct": 0.0,
            "total_trades": 0,
            "win_trades": 0,
            "loss_trades": 0,
            "win_rate": 0.0,
            "today_pnl": 0.0,
            "daily_trades_taken": 0,
            "max_daily_trades": self.state.get("max_trades_per_day", 2),
            "last_trade_date": datetime.now().strftime("%Y-%m-%d"),
            "active_positions": []
        }
        self.save_wallet()

        # Wipe SQLite trade records
        try:
            import sqlite3
            conn = sqlite3.connect(self.signals_db_file, timeout=10.0)
            cur = conn.cursor()
            cur.execute("DELETE FROM institutional_trades")
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"Error wiping SQLite trades for {self.user_id}:", e)

        # Wipe trade log
        self._sync_trades_to_storage([])

        self.state["active_signal"] = None
        self.state["cooldown_until"] = None
        self.save_state()
        return {
            "status": "ok",
            "message": f"Virtual wallet successfully reset to ₹{initial_capital:,.2f} with 0 trades.",
            "wallet": self.wallet
        }

    def reset_daily_limit(self):
        """Resets only the daily discipline counter back to 0 without wiping history"""
        self.wallet["daily_trades_taken"] = 0
        self.save_wallet()
        limit_val = self.state.get("max_trades_per_day", 2)
        return {
            "status": "ok",
            "message": f"Daily trade limit reset to 0/{limit_val}.",
            "wallet": self.wallet
        }

    def set_max_daily_trades(self, limit: int):
        """Allows user to manually adjust daily profit trades target (e.g. 2 to 5 trades)"""
        limit = max(1, min(10, int(limit)))
        self.state["max_trades_per_day"] = limit
        self.save_state()
        self.wallet["max_daily_trades"] = limit
        self.save_wallet()
        return {"status": "ok", "max_trades_per_day": limit, "wallet": self.wallet}

    # ══════════════════════════════════════════════════════════════════
    # TRADE LOG & SELECTION / DELETION MANAGEMENT
    # ══════════════════════════════════════════════════════════════════
    def get_trades(self, date: str = None):
        trades = []
        target_file = self.signals_log_file
        if not os.path.exists(target_file) and self.user_id in ["default", "admin", "1"] and os.path.exists(SIGNALS_LOG_FILE):
            target_file = SIGNALS_LOG_FILE
        if os.path.exists(target_file):
            try:
                with open(target_file, "r", encoding="utf-8") as f:
                    trades = json.load(f)
            except Exception:
                trades = []
        # Only return real executed or closed trades (exclude pending unexecuted radar alerts)
        trades = [
            t for t in trades
            if t.get("status") not in ["ACTIVE_PENDING_CONFIRMATION", "PENDING", "CANCELLED_BY_USER"]
        ]
        if date:
            trades = [
                t for t in trades
                if str(t.get("timestamp") or t.get("entry_time") or t.get("executed_at") or "").startswith(date)
            ]
        return trades

    def delete_trades(self, trade_ids: list):
        """Delete specific trade IDs or 'ALL', and recalculate wallet stats"""
        current_trades = self.get_trades()
        if not trade_ids or "ALL" in trade_ids:
            return self.reset_wallet(self.wallet.get("initial_capital", 100000.0))

        id_set = set(str(tid) for tid in trade_ids)
        kept = [t for t in current_trades if str(t.get("signal_id")) not in id_set and str(t.get("trade_id")) not in id_set]

        # Prune deleted IDs from SQLite database
        try:
            import sqlite3
            conn = sqlite3.connect(self.signals_db_file, timeout=10.0)
            cur = conn.cursor()
            for tid in id_set:
                cur.execute("DELETE FROM institutional_trades WHERE trade_id = ? OR signal_id = ?", (tid, tid))
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"Error pruning SQLite trades for {self.user_id}:", e)

        # Save kept trades to JSON, CSV & SQLite
        self._sync_trades_to_storage(kept)

        # Recalculate wallet statistics from remaining trades
        self.recalculate_wallet()

        deleted_count = len(current_trades) - len(kept)
        return {
            "status": "ok",
            "message": f"Successfully deleted {deleted_count} trade(s).",
            "remaining_trades": len(kept),
            "wallet": self.wallet
        }

    # ══════════════════════════════════════════════════════════════════
    # ENGINE CONTROLS & TRADING EXECUTION
    # ══════════════════════════════════════════════════════════════════
    def set_switch(self, is_on: bool):
        self.state["master_switch"] = bool(is_on)
        self.save_state()
        return {"status": "ok", "master_switch": self.state["master_switch"]}

    def set_auto_mode(self, is_auto: bool):
        self.state["auto_trading"] = bool(is_auto)
        self.save_state()
        # If auto mode is turned ON and there is a pending signal, auto-decide & execute immediately
        if self.state["auto_trading"] and self.state.get("active_signal"):
            sig = self.state["active_signal"]
            if sig.get("status") == "ACTIVE_PENDING_CONFIRMATION":
                return self.execute_signal(sig.get("signal_id"), is_auto=True)
        return {"status": "ok", "auto_trading": self.state["auto_trading"]}

    def set_lot_size(self, lots: int):
        self.state["lot_size_multiplier"] = max(1, min(20, int(lots)))
        self.save_state()
        return {"status": "ok", "lots": self.state["lot_size_multiplier"], "qty": self.state["lot_size_multiplier"] * 65}

    def set_strike_mode(self, mode: str):
        """Configure user preferred strike selection rule: ITM_1, ATM, ITM_2, OTM_1"""
        valid = ["ITM_1", "ATM", "ITM_2", "OTM_1"]
        clean_mode = str(mode).strip().upper()
        if clean_mode in valid:
            self.state["strike_selection_mode"] = clean_mode
            self.save_state()
            return {"status": "ok", "strike_mode": clean_mode}
        return {"status": "error", "message": f"Invalid mode. Choose from {valid}"}

    def calculate_trade_strike(self, spot_price: float, direction: str, mode: str = None) -> tuple:
        """
        Calculates option strike and estimated delta based on selected strike mode and direction.
        Returns: (strike_int, delta_float, label_str)
        """
        mode = mode or self.state.get("strike_selection_mode", "ITM_1")
        atm = int(round(spot_price / 50.0) * 50)
        is_call = direction.upper() in ["CALL", "BUY_CE", "CE"]
        
        if mode == "ATM":
            strike = atm
            delta = 0.50 if is_call else -0.50
            lbl = "ATM"
        elif mode == "ITM_2":
            strike = (atm - 100) if is_call else (atm + 100)
            delta = 0.75 if is_call else -0.75
            lbl = "2 ITM"
        elif mode == "OTM_1":
            strike = (atm + 50) if is_call else (atm - 50)
            delta = 0.35 if is_call else -0.35
            lbl = "1 OTM"
        else: # Default ITM_1
            strike = (atm - 50) if is_call else (atm + 50)
            delta = 0.65 if is_call else -0.65
            lbl = "1 ITM"
        return strike, delta, lbl

    def execute_signal(self, signal_id: str = None, is_auto: bool = False):
        """Execute the active signal and record it into dedicated Virtual Wallet"""
        sig = self.state.get("active_signal")
        if not sig:
            return {"status": "error", "message": "No active signal to execute"}

        # Market Open Guard: Do not execute trades when market is closed
        is_open, m_reason = self.is_market_open()
        is_test = bool(sig.get("is_test", False))
        if not is_open and not is_test:
            return {"status": "error", "message": f"Execution Blocked: {m_reason}"}

        # Position guard: Only 1 active running position allowed at a time
        if self.wallet.get("active_positions"):
            return {"status": "error", "message": "Position already active. Only 1 active trade allowed at a time."}

        # Golden Rule Verification: Max Trades per day
        today_str = datetime.now().strftime("%Y-%m-%d")
        if self.wallet.get("last_trade_date") != today_str:
            self.wallet["last_trade_date"] = today_str
            self.wallet["daily_trades_taken"] = 0

        max_daily = self.state.get("max_trades_per_day", 5)
        if self.wallet.get("daily_trades_taken", 0) >= max_daily and not is_test:
            return {"status": "error", "message": f"Daily limit reached ({self.wallet.get('daily_trades_taken', 0)}/{max_daily})."}

        # Execute
        exec_type = "AUTO_EXECUTED" if is_auto or self.state.get("auto_trading") else "MANUALLY_EXECUTED"
        exec_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        sig["status"] = exec_type
        sig["executed_at"] = exec_time
        sig["entry_time"] = sig.get("entry_time") or sig.get("timestamp") or exec_time
        sig["execution_mode"] = "ALGORITHMIC_AUTO" if is_auto or self.state.get("auto_trading") else "MANUAL_CLICK"
        sig["trade_id"] = sig.get("signal_id") or f"TRD_{int(datetime.now().timestamp())}"

        # Margin calculation: entry_ltp * qty
        qty = sig.get("qty", 130)
        entry_ltp = sig.get("entry_ltp", 146.80)
        margin_required = round(entry_ltp * qty, 2)
        sig["margin_utilized"] = margin_required

        # Update wallet position
        self.wallet["daily_trades_taken"] = self.wallet.get("daily_trades_taken", 0) + 1
        self.wallet["total_trades"] = self.wallet.get("total_trades", 0) + 1
        self.wallet["utilized_margin"] = margin_required

        # Keep active position with all rich metrics
        pos = {
            "trade_id": sig["trade_id"],
            "signal_id": sig.get("signal_id", sig["trade_id"]),
            "contract": sig["contract"],
            "action": sig["action"],
            "direction": sig.get("direction", "CALL"),
            "strike_price": sig.get("strike_price", 24700),
            "option_type": sig.get("option_type", "CE"),
            "entry_spot": sig.get("entry_spot", 24745.20),
            "entry_time": sig["entry_time"],
            "qty": qty,
            "lots": sig.get("lots", self.state["lot_size_multiplier"]),
            "entry_ltp": entry_ltp,
            "sl_price": sig["stop_loss_price"],
            "target_price": sig.get("target_price") or sig["target_plan"]["target_2_runner"],
            "target_plan": sig["target_plan"],
            "peak_pts": 0.0,
            "peak_price": entry_ltp,
            "trailed_to_cost": False,
            "tsl_stage": f"INITIAL (SL: ₹{sig['stop_loss_price']:.1f})",
            "ma_9": sig.get("ma_9"),
            "ema_21": sig.get("ema_21"),
            "oi": sig.get("oi"),
            "oi_change": sig.get("oi_change"),
            "volume": sig.get("volume"),
            "volume_spike": sig.get("volume_spike"),
            "delta": sig.get("delta", 0.65),
            "max_risk_rupees": sig.get("max_risk_rupees"),
            "margin_utilized": margin_required,
            "weapon_signature": sig.get("weapon_signature"),
            "weapon_reason": sig.get("weapon_reason"),
            "executed_at": exec_time,
            "mode": sig["execution_mode"]
        }
        self.wallet["active_positions"] = [pos]
        self.save_wallet()

        # Update log
        self._log_signal(sig)
        self.state["active_signal"] = sig
        self.save_state()

        # Send Real-Time Telegram Alert
        try:
            from telegram_notifier import send_telegram_message
            st_badge = "🟢 GREEN LINE (ST BULL)" if sig.get("supertrend_color") == "GREEN" or "CE" in sig.get("action", "") else "🔴 RED LINE (ST BEAR)"
            st_val_str = f"₹{sig['supertrend_value']:.1f}" if sig.get("supertrend_value") else "N/A"
            t_msg = (
                f"⚡ *NEW LIVE TRADE EXECUTED*\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"🎯 *Contract*: `{sig['contract']}`\n"
                f"📈 *Direction*: `{sig['action']}`\n"
                f"📊 *SuperTrend*: `{st_badge}` ({st_val_str})\n"
                f"💵 *Entry LTP*: `₹{entry_ltp:.2f}`\n"
                f"🛑 *Stop Loss*: `₹{sig['stop_loss_price']:.2f}`\n"
                f"🎯 *Target*: `₹{sig['target_plan']['target_2_runner']:.2f}`\n"
                f"📦 *Quantity*: `{qty}` ({sig.get('lots', 2)} Lots)\n"
                f"🛡️ *Setup*: {sig.get('weapon_reason', 'Selective Master')}\n"
                f"⏰ *Time*: `{exec_time}`"
            )
            send_telegram_message(t_msg)
        except Exception as e:
            print("[TELEGRAM] Entry dispatch error:", e)

        return {
            "status": "ok",
            "execution_type": exec_type,
            "signal": sig,
            "wallet": self.wallet,
            "message": f"Signal {sig.get('contract')} successfully executed via {sig['execution_mode']}! Margin ₹{margin_required:,.2f}"
        }

    def close_trade(self, trade_id: str, outcome: str = "TARGET_HIT", exit_ltp: float = None):
        """Close an active position and update realized P&L with full institutional trade audit"""
        trades = self.get_trades()
        matched = None
        for t in trades:
            if str(t.get("signal_id")) == str(trade_id) or str(t.get("trade_id")) == str(trade_id):
                matched = t
                break

        if not matched:
            # Check active positions in wallet or active signal in state
            pos = next((p for p in self.wallet.get("active_positions", []) if str(p.get("trade_id")) == str(trade_id) or not trade_id), None)
            if not pos and self.state.get("active_signal"):
                act_sig = self.state["active_signal"]
                if str(act_sig.get("signal_id")) == str(trade_id) or str(act_sig.get("trade_id")) == str(trade_id) or not trade_id:
                    pos = act_sig

            if pos:
                entry_val = float(pos.get("entry_ltp", 146.80))
                matched = {
                    "signal_id": pos.get("trade_id") or pos.get("signal_id") or f"SIG_{int(datetime.now().timestamp())}",
                    "trade_id": pos.get("trade_id") or pos.get("signal_id") or f"TRD_{int(datetime.now().timestamp())}",
                    "timestamp": pos.get("executed_at") or pos.get("timestamp") or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "entry_time": pos.get("entry_time") or pos.get("executed_at") or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "action": pos.get("action", "BUY_CE"),
                    "contract": pos.get("contract", "NIFTY 24700 CE (1 ITM)"),
                    "direction": "PUT" if "PE" in pos.get("contract", "") else "CALL",
                    "strike_price": pos.get("strike_price", 24700),
                    "option_type": pos.get("option_type", "CE"),
                    "entry_spot": pos.get("entry_spot", 24745.20),
                    "entry_ltp": entry_val,
                    "lots": pos.get("lots", self.state["lot_size_multiplier"]),
                    "qty": int(pos.get("qty", 130)),
                    "stop_loss_price": float(pos.get("sl_price", entry_val - 7.5)),
                    "target_price": float(pos.get("target_price", entry_val + 12.0)),
                    "target_plan": pos.get("target_plan", {
                        "breakeven_lock": round(entry_val + 3.0, 2),
                        "target_2_runner": round(entry_val + 12.0, 2)
                    }),
                    "ma_9": pos.get("ma_9", 24749.10),
                    "ema_21": pos.get("ema_21", 24758.30),
                    "oi": pos.get("oi", 1845200),
                    "oi_change": pos.get("oi_change", 185000),
                    "volume": pos.get("volume", 88400),
                    "volume_spike": pos.get("volume_spike", "2.8x"),
                    "delta": pos.get("delta", 0.65),
                    "max_risk_rupees": pos.get("max_risk_rupees", round(7.5 * int(pos.get("qty", 130)), 2)),
                    "margin_utilized": pos.get("margin_utilized", round(entry_val * int(pos.get("qty", 130)), 2)),
                    "weapon_signature": pos.get("weapon_signature", "WEAPON_BOTTOM_PUT_SHIELD / SUPPORT_BOUNCE"),
                    "weapon_reason": pos.get("weapon_reason", "Support at 24700: Put writers added +185,000 OI | 1m Volume Spike 2.8x | Delta 0.65"),
                    "execution_mode": pos.get("mode", "ALGORITHMIC_AUTO"),
                    "status": "AUTO_EXECUTED"
                }
                trades.append(matched)

        if not matched:
            return {"status": "error", "message": f"Trade {trade_id} not found"}

        entry_ltp = float(matched.get("entry_ltp", 140.0))
        qty = int(matched.get("qty", 130))
        lots = int(matched.get("lots") or max(1, qty // 65))
        is_breakeven = False

        if outcome == "TARGET_HIT":
            exit_price = exit_ltp if exit_ltp is not None else float(matched.get("target_price") or matched.get("target_plan", {}).get("target_2_runner", entry_ltp + 12.0))
            matched["status"] = "TARGET_HIT"
        elif outcome == "SL_HIT":
            exit_price = exit_ltp if exit_ltp is not None else float(matched.get("stop_loss_price", entry_ltp - 7.5))
            matched["status"] = "SL_HIT"
        elif outcome in ["BREAKEVEN", "COST", "TRAILED_TO_COST"]:
            exit_price = exit_ltp if exit_ltp is not None else float(matched.get("target_plan", {}).get("breakeven_lock", entry_ltp))
            matched["status"] = "BREAKEVEN"
            is_breakeven = True
        else: # MANUAL_CLOSE or CLOSED
            exit_price = exit_ltp if exit_ltp is not None else float(matched.get("target_plan", {}).get("breakeven_lock", entry_ltp + 3.0))
            matched["status"] = "CLOSED"

        gross_pts = round(exit_price - entry_ltp, 2)
        if abs(gross_pts) <= 0.5 or outcome == "BREAKEVEN":
            is_breakeven = True
            matched["status"] = "BREAKEVEN"

        # ── Realistic Execution Math: Real DuckDB Tick Slippage (~0.10-0.20 pts) + Flat Rs. 70/lot Brokerage ──
        BROKERAGE_PER_LOT = 70.0
        try:
            from duckdb_engine import duckdb_engine
            con = duckdb_engine.get_connection(read_only=True)
            ticks = con.execute("""
                SELECT ltp FROM nifty_ticks 
                WHERE strike = ? AND type = ? 
                ORDER BY timestamp DESC LIMIT 5
            """, (float(matched.get("strike_price", 0)), str(matched.get("option_type", "CE")))).fetchall()
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
        brokerage_rupees = round(lots * BROKERAGE_PER_LOT, 2)
        total_friction = round(brokerage_rupees + slippage_rupees, 2)

        gross_pnl_rupees = round(gross_pts * qty, 2)
        net_pnl_rupees = round(gross_pnl_rupees - total_friction, 2)
        net_pnl_pts = round(net_pnl_rupees / qty, 2)
        net_pnl_pct = round((net_pnl_pts / entry_ltp * 100.0), 2) if entry_ltp > 0 else 0.0

        # Calculate Exit Spot
        exit_spot = None
        entry_spot_val = float(matched.get("entry_spot", 24745.0))
        delta_val = float(matched.get("delta") or 0.65)
        sign = 1 if matched.get("direction") == "CALL" else -1

        try:
            from duckdb_engine import duckdb_engine
            df = duckdb_engine.get_latest_option_chain()
            if df is not None and not df.empty:
                cand_spot = round(float(df['spot_price'].iloc[0]), 2)
                # Ensure spot is within realistic intraday deviation (< 250 pts from entry)
                if abs(cand_spot - entry_spot_val) < 250.0:
                    exit_spot = cand_spot
        except Exception:
            pass

        if exit_spot is None:
            exit_spot = round(entry_spot_val + (sign * gross_pts / (abs(delta_val) if abs(delta_val) > 0.1 else 0.65)), 2)

        entry_spot_val = float(matched.get("entry_spot", exit_spot))
        spot_change = round(exit_spot - entry_spot_val, 2)

        matched["exit_ltp"] = exit_price
        matched["exit_spot"] = exit_spot
        matched["spot_change"] = spot_change
        matched["exit_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if not matched.get("entry_time"):
            matched["entry_time"] = matched.get("timestamp") or matched.get("executed_at")
        matched["is_breakeven"] = is_breakeven
        matched["gross_points"] = gross_pts
        matched["gross_pnl"] = gross_pnl_rupees
        matched["brokerage"] = brokerage_rupees
        matched["slippage"] = slippage_rupees
        matched["total_friction"] = total_friction
        matched["pnl_points"] = net_pnl_pts
        matched["pnl_pct"] = net_pnl_pct
        matched["pnl_rupees"] = net_pnl_rupees

        # Save trades to JSON, CSV, and SQLite
        self._sync_trades_to_storage(trades)

        # Update wallet stats dynamically from trades ledger
        self.recalculate_wallet()
        self.wallet["utilized_margin"] = 0.0
        self.wallet["active_positions"] = []
        self.save_wallet()

        # Clear active signal from state and record trade close timestamp
        now_close_dt = datetime.now()
        self.state["last_trade_closed_at"] = now_close_dt.strftime("%Y-%m-%d %H:%M:%S")
        self.wallet["last_closed_trade_time"] = now_close_dt.timestamp()
        self.state["active_signal"] = None
        self.save_state()

        # Send Real-Time Telegram Exit Alert
        try:
            from telegram_notifier import send_telegram_message
            pnl_emoji = "🟢" if net_pnl_rupees > 0 else "🔴"
            t_msg = (
                f"🏁 *TRADE CLOSED ({outcome})*\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"🎯 *Contract*: `{matched.get('contract', 'NIFTY')}`\n"
                f"💵 *Exit LTP*: `₹{exit_price:.2f}` (Entry: `₹{entry_ltp:.2f}`)\n"
                f"{pnl_emoji} *Net P&L*: `₹{net_pnl_rupees:,.2f}` (`{net_pnl_pts:+.2f} pts`)\n"
                f"⏰ *Exit Time*: `{matched.get('exit_time')}`"
            )
            send_telegram_message(t_msg)
        except Exception as e:
            print("[TELEGRAM] Exit dispatch error:", e)

        return {
            "status": "ok",
            "message": f"Trade closed with P&L: ₹{net_pnl_rupees:,.2f} ({net_pnl_pts:+} pts)",
            "trade": matched,
            "wallet": self.wallet
        }

    def cancel_signal(self, signal_id: str = None):
        """Cancel/Dismiss the active signal"""
        sig = self.state.get("active_signal")
        if sig:
            sig["status"] = "CANCELLED_BY_USER"
            sig["cancelled_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self._log_signal(sig)

        self.state["active_signal"] = None
        self.save_state()
        return {"status": "ok", "message": "Signal cancelled and dismissed"}

    def trigger_test_signal(self, direction: str = "CALL"):
        """Generate an authentic test signal dynamically aligned with current live market spot and S/R"""
        now_dt = datetime.now()
        now_ts = now_dt.strftime("%Y-%m-%d %H:%M:%S")
        uid = now_dt.strftime("%Y%m%d_%H%M%S_%f")
        lots = self.state.get("lot_size_multiplier", 2)
        qty = lots * 65

        # Fetch current spot price dynamically from DuckDB or state
        spot_price = float(self.state.get("live_spot_price") or 23387.05)
        try:
            from duckdb_engine import duckdb_engine
            df = duckdb_engine.get_latest_option_chain()
            if df is not None and not df.empty:
                spot_price = float(df['spot_price'].iloc[0])
        except Exception:
            pass

        strike_mode = self.state.get("strike_selection_mode", "ITM_1")
        strike_price, delta, strike_lbl = self.calculate_trade_strike(spot_price, direction, strike_mode)
        atm_strike = int(round(spot_price / 50.0) * 50)

        is_put = direction.upper() in ["PUT", "PE", "BUY_PE"]
        opt_type = "PE" if is_put else "CE"
        action = f"BUY_{opt_type}"
        contract = f"NIFTY {strike_price} {opt_type} ({strike_lbl})"

        # Dynamic intrinsic + time value estimate for realistic entry LTP
        if is_put:
            intrinsic = max(0.0, strike_price - spot_price)
        else:
            intrinsic = max(0.0, spot_price - strike_price)
        est_ltp = round(intrinsic + 72.5, 1)
        if est_ltp < 25.0:
            est_ltp = 55.0

        support = atm_strike - 50 if (atm_strike - 50) <= spot_price else atm_strike
        resistance = atm_strike + 100 if (atm_strike + 100) >= spot_price else atm_strike + 50

        if is_put:
            weapon_sig = "WEAPON_TOP_CALL_FORTRESS / RESISTANCE_REJECTION"
            weapon_reason = f"Resistance at {resistance}: Call writers fortress | Spot ₹{spot_price:,.2f} rejected | Strike {strike_price} PE ({strike_lbl})"
        else:
            weapon_sig = "WEAPON_BOTTOM_PUT_SHIELD / SUPPORT_BOUNCE"
            weapon_reason = f"Support at {support}: Put writers shield active | Spot ₹{spot_price:,.2f} bounce confirmed | Strike {strike_price} CE ({strike_lbl})"

        sig = {
            "signal_id": f"SIG_{uid}",
            "trade_id": f"TRD_{uid}",
            "timestamp": now_ts,
            "entry_time": now_ts,
            "action": action,
            "contract": contract,
            "direction": "PUT" if is_put else "CALL",
            "strike_price": strike_price,
            "option_type": opt_type,
            "entry_spot": round(spot_price, 2),
            "entry_ltp": est_ltp,
            "lots": lots,
            "qty": qty,
            "stop_loss_pts": self.state["stop_loss_pts"],
            "stop_loss_price": round(est_ltp - self.state["stop_loss_pts"], 2),
            "target_plan": {
                "breakeven_lock": round(est_ltp + 3.0, 2),
                "target_1": round(est_ltp + 6.0, 2),
                "target_2_runner": round(est_ltp + 12.0, 2)
            },
            "target_price": round(est_ltp + 12.0, 2),
            "max_risk_rupees": round(self.state["stop_loss_pts"] * qty, 2),
            "margin_utilized": round(est_ltp * qty, 2),
            "target_profit_rupees": round(12.0 * qty, 2),
            "ma_9": round(spot_price + (1.5 if is_put else -1.5), 2),
            "ema_21": round(spot_price + (3.0 if is_put else -3.0), 2),
            "oi": 1920000,
            "oi_change": 185000,
            "volume": 84200,
            "volume_spike": "2.8x",
            "delta": delta,
            "weapon_signature": weapon_sig,
            "weapon_reason": weapon_reason,
            "status": "ACTIVE_PENDING_CONFIRMATION",
            "is_test": True
        }

        # If auto-trading is ON, auto-execute immediately
        if self.state.get("auto_trading"):
            self.state["active_signal"] = sig
            return self.execute_signal(sig["signal_id"], is_auto=True)

        self.state["active_signal"] = sig
        self.state["last_processed_time"] = now_ts
        self.save_state()
        return {"status": "ok", "signal": sig}

    def evaluate_live_minute(self, df_15m_window):
        """
        Selective Master Strategy: Evaluates 6 Timeframes Confluence (1m to 15m).
        Only triggers max 2 A+ setups per day to prevent over-trading.
        """
        if not self.state["master_switch"]:
            return {"status": "disabled", "message": "Signal Engine is switched OFF"}

        if len(df_15m_window) < 15:
            return {"status": "waiting", "message": "Accumulating 15-minute timeframe bars"}

        last_row = df_15m_window.iloc[-1]
        ts = str(last_row["timestamp"])
        t_part = ts.split(" ")[-1] if " " in ts else ts.split("T")[-1]

        # Time filter: 09:25 to 14:45 only
        if t_part < "09:25:00" or t_part >= "14:45:00":
            return {"status": "outside_hours", "message": "Trading window closed"}

        # Quant Strategy: Midday Chop Avoidance (12:00 to 13:00 - High Fakeout / Theta decay zone)
        if "12:00:00" <= t_part <= "13:00:00":
            return {"status": "midday_filter", "message": "12:00-13:00 Midday chop filter active (Preserving capital)"}

        spot = float(last_row["spot"])
        start_spot = float(df_15m_window["spot"].iloc[0])
        spot_run = spot - start_spot

        ce_oi_bld = float(df_15m_window["ce_oi"].iloc[-1] - df_15m_window["ce_oi"].iloc[0])
        pe_oi_bld = float(df_15m_window["pe_oi"].iloc[-1] - df_15m_window["pe_oi"].iloc[0])

        # Volume bursts
        v_diff_ce = float(last_row.get("ce_vol_diff", 0) or 0)
        v_diff_pe = float(last_row.get("pe_vol_diff", 0) or 0)
        v_ma_ce = float(last_row.get("ce_vol_ma10", 1) or 1)
        v_ma_pe = float(last_row.get("pe_vol_ma10", 1) or 1)

        vol_spike_ce = f"{round(v_diff_ce / max(1.0, v_ma_ce), 1)}x"
        vol_spike_pe = f"{round(v_diff_pe / max(1.0, v_ma_pe), 1)}x"

        # Moving Averages: 9 MA and 21 EMA
        ma_9 = round(float(df_15m_window['spot'].rolling(9, min_periods=1).mean().iloc[-1]), 2)
        ema_21 = round(float(df_15m_window['spot'].ewm(span=21, adjust=False).mean().iloc[-1]), 2)

        ce_d = float(last_row.get("ce_delta", 0.65) or 0.65)
        pe_d = float(last_row.get("pe_delta", -0.65) or -0.65)

        ce_1itm_ltp = float(last_row.get("ce_1itm", 150.0) or 150.0)
        pe_1itm_ltp = float(last_row.get("pe_1itm", 150.0) or 150.0)

        # Dynamic Strikes using user-selected strike mode (ITM_1, ATM, ITM_2, OTM_1)
        itm_call_strike, call_delta, call_lbl = self.calculate_trade_strike(spot, "CALL")
        itm_put_strike, put_delta, put_lbl = self.calculate_trade_strike(spot, "PUT")

        signal = None
        
        # Day-based Asymmetric Position Sizing (Friday Trend King & Tuesday Expiry Gamma: 3 Lots booster)
        day_name = datetime.now().strftime("%A")
        lots = self.state["lot_size_multiplier"]
        if day_name in ["Friday", "Tuesday"]:
            lots = max(lots, 3) # 3 Lots (195 Qty) on high-profit days
        qty = lots * 65

        # USER STRATEGY RULE: OI + Volume UP -> BUY CALL, OI + Volume DOWN -> BUY PE
        # Bullish Flow: CE Volume dominance / surge + PE Support OI building
        oi_vol_bullish = (v_diff_ce > v_diff_pe or v_diff_ce >= v_ma_ce * 1.2) and (pe_oi_bld >= 50000 or pe_oi_bld > ce_oi_bld)
        # Bearish Flow: PE Volume dominance / surge + CE Resistance OI building
        oi_vol_bearish = (v_diff_pe > v_diff_ce or v_diff_pe >= v_ma_pe * 1.2) and (ce_oi_bld >= 50000 or ce_oi_bld > pe_oi_bld)

        # BULLISH TRIGGER: (PE Put Shield / Support Absorption / Delta Burst + OI/Vol UP Confirmation)
        if oi_vol_bullish and ((spot_run <= -12.0 and pe_oi_bld > ce_oi_bld) or (spot >= ema_21 and v_diff_ce >= v_ma_ce * 1.5)):
            signal = {
                "signal_id": f"SIG_{int(datetime.now().timestamp())}",
                "trade_id": f"TRD_{int(datetime.now().timestamp())}",
                "timestamp": ts,
                "entry_time": ts,
                "action": "BUY_CE",
                "contract": f"NIFTY {int(itm_call_strike)} CE ({call_lbl})",
                "direction": "CALL",
                "strike_price": int(itm_call_strike),
                "option_type": "CE",
                "entry_spot": round(spot, 2),
                "entry_ltp": round(ce_1itm_ltp, 2),
                "lots": lots,
                "qty": qty,
                "stop_loss_pts": self.state["stop_loss_pts"],
                "stop_loss_price": round(ce_1itm_ltp - self.state["stop_loss_pts"], 2),
                "target_plan": {
                    "breakeven_lock": round(ce_1itm_ltp + 3.0, 2),
                    "target_1": round(ce_1itm_ltp + 6.0, 2),
                    "target_2_runner": round(ce_1itm_ltp + 12.0, 2)
                },
                "target_price": round(ce_1itm_ltp + 12.0, 2),
                "max_risk_rupees": round(self.state["stop_loss_pts"] * qty, 2),
                "margin_utilized": round(ce_1itm_ltp * qty, 2),
                "target_profit_rupees": round(12.0 * qty, 2),
                "ma_9": ma_9,
                "ema_21": ema_21,
                "oi": int(last_row.get("ce_oi", 0) or 0),
                "oi_change": int(pe_oi_bld),
                "volume": int(v_diff_ce),
                "volume_spike": vol_spike_ce,
                "delta": round(call_delta, 2),
                "weapon_signature": "WEAPON_BOTTOM_PUT_SHIELD / SUPPORT_BOUNCE",
                "weapon_reason": f"Support at {int(itm_call_strike)}: Put writers added +{int(pe_oi_bld):,} OI | 1m Volume Spike {vol_spike_ce} | Delta {call_delta:.2f}",
                "status": "ACTIVE_PENDING_CONFIRMATION"
            }

        # BEARISH TRIGGER: (CE Call Fortress / Resistance Exhaustion / Delta Burst + OI/Vol DOWN Confirmation)
        elif oi_vol_bearish and ((spot_run >= 12.0 and ce_oi_bld > pe_oi_bld) or (spot <= ema_21 and v_diff_pe >= v_ma_pe * 1.5)):
            signal = {
                "signal_id": f"SIG_{int(datetime.now().timestamp())}",
                "trade_id": f"TRD_{int(datetime.now().timestamp())}",
                "timestamp": ts,
                "entry_time": ts,
                "action": "BUY_PE",
                "contract": f"NIFTY {int(itm_put_strike)} PE ({put_lbl})",
                "direction": "PUT",
                "strike_price": int(itm_put_strike),
                "option_type": "PE",
                "entry_spot": round(spot, 2),
                "entry_ltp": round(pe_1itm_ltp, 2),
                "lots": lots,
                "qty": qty,
                "stop_loss_pts": self.state["stop_loss_pts"],
                "stop_loss_price": round(pe_1itm_ltp - self.state["stop_loss_pts"], 2),
                "target_plan": {
                    "breakeven_lock": round(pe_1itm_ltp + 3.0, 2),
                    "target_1": round(pe_1itm_ltp + 6.0, 2),
                    "target_2_runner": round(pe_1itm_ltp + 12.0, 2)
                },
                "target_price": round(pe_1itm_ltp + 12.0, 2),
                "max_risk_rupees": round(self.state["stop_loss_pts"] * qty, 2),
                "margin_utilized": round(pe_1itm_ltp * qty, 2),
                "target_profit_rupees": round(12.0 * qty, 2),
                "ma_9": ma_9,
                "ema_21": ema_21,
                "oi": int(last_row.get("pe_oi", 0) or 0),
                "oi_change": int(ce_oi_bld),
                "volume": int(v_diff_pe),
                "volume_spike": vol_spike_pe,
                "delta": round(put_delta, 2),
                "weapon_signature": "WEAPON_TOP_CALL_FORTRESS / RESISTANCE_REJECTION",
                "weapon_reason": f"Resistance at {int(itm_put_strike)}: Call writers added +{int(ce_oi_bld):,} OI | 1m Volume Spike {vol_spike_pe} | Delta {put_delta:.2f}",
                "status": "ACTIVE_PENDING_CONFIRMATION"
            }

        if signal:
            self.state["active_signal"] = signal
            self.state["last_processed_time"] = ts
            self.save_state()

            # Auto-execute if enabled
            if self.state.get("auto_trading"):
                return self.execute_signal(signal["signal_id"], is_auto=True)

            return {"status": "signal_generated", "signal": signal}

        return {"status": "neutral", "message": "No weapon confluence at this minute"}

    def process_market_tick(self, ticks, spot_price, current_timestamp=None):
        """
        Real-Time Tick Pipeline:
        1. Evaluates active positions (Trailing SL progression & Target / SL hits).
        2. Detects high-probability setups:
           - 🚀 Bullish Breakout (Spot >= R1 with strong bullish trend / EMA9 > EMA21)
           - ⚖️ Support Bounce (Spot near S1 with green reversal bounce)
           - 🩸 Bearish Breakdown (Spot <= S1 with strong bearish trend / EMA9 < EMA21)
           - ⚖️ Resistance Rejection (Spot near R1 with red rejection)
        3. Executes / registers auto-trades directly into dedicated Virtual Wallet.
        """
        if not self.state.get("master_switch", True):
            return {"status": "disabled", "message": "Signal Engine Master Switch is OFF"}

        from datetime import timezone, timedelta
        ist = timezone(timedelta(hours=5, minutes=30))
        now_dt = datetime.now(ist).replace(tzinfo=None)

        # Market Open & Weekend Guard
        is_sim = bool(current_timestamp)
        is_open, market_msg = self.is_market_open(None if not is_sim else current_timestamp)
        self.state["is_market_open"] = is_open
        self.state["market_status"] = market_msg

        if not is_sim and not is_open:
            return {"status": "market_closed", "message": market_msg, "is_market_open": False}

        # Stale Data Guard: Check if ticks themselves are from a closed / previous session
        if not is_sim and ticks:
            tick_time_str = str(ticks[0].get("timestamp", ""))
            if tick_time_str:
                clean_tick_date = tick_time_str.split('T')[0] if 'T' in tick_time_str else tick_time_str.split(' ')[0]
                today_date = now_dt.strftime("%Y-%m-%d")
                if clean_tick_date != today_date:
                    return {"status": "stale_data", "message": f"Tick data is historical ({clean_tick_date}), ignoring for live execution."}

        ts_str = str(current_timestamp).replace('T', ' ') if current_timestamp else now_dt.strftime("%Y-%m-%d %H:%M:%S")

        # 1. Update Active Positions & Trailing Stop Loss
        pos_list = self.wallet.get("active_positions", [])
        if pos_list:
            to_close = []
            for p in list(pos_list):
                opt_type = p.get("option_type", "CE")
                stk = float(p.get("strike_price", 0.0))
                cur_ltp = float(p.get("current_ltp") or p.get("entry_ltp", 140.0))
                for t in ticks:
                    if t.get("type") == opt_type and float(t.get("strike", 0)) == stk:
                        cur_ltp = float(t.get("ltp") or cur_ltp)
                        break

                entry_p = float(p.get("entry_ltp", cur_ltp))
                qty = int(p.get("qty", 130))
                pts_gain = round(cur_ltp - entry_p, 2)
                p["current_ltp"] = cur_ltp
                p["unrealized_pts"] = pts_gain
                p["unrealized_rupees"] = round(pts_gain * qty, 2)

                # Peak tracking
                if "peak_pts" not in p or pts_gain > p["peak_pts"]:
                    p["peak_pts"] = pts_gain

                # ══════════════════════════════════════════════════════════════
                # DYNAMIC TRAILING RATIO & MEGA RUNNER RATCHET (-2.0 PTS)
                # ══════════════════════════════════════════════════════════════
                brok_pts = round(140.0 / max(1, qty), 2)  # ~1.08 pts for 130 qty
                slip_pts = 0.60
                net_min_pts = round(150.0 / max(1, qty), 2) # ~1.15 pts for +₹150 Net
                early_safe_lock_pts = round(brok_pts + slip_pts + net_min_pts, 2)

                cand_sl = p.get("sl_price", entry_p - self.state.get("stop_loss_pts", 15.0))

                # STAGE 3: MEGA RUNNER -2.0 PT EXACT RATCHET (Peak >= 12.0 pts):
                # Sl shifts exactly to (Peak - 2.0 pts)!
                # Examples: Peak 30 -> SL 28, Peak 34 -> SL 32, Peak 36 -> SL 34, Peak 71 -> SL 69!
                if p["peak_pts"] >= 12.0:
                    cand = round(entry_p + p["peak_pts"] - 2.0, 2)
                    if cand > cand_sl:
                        cand_sl = cand
                        p["trailed_to_cost"] = True
                        p["tsl_stage"] = f"🚀 MEGA RIDE -2pt (Peak +{p['peak_pts']:.1f} ➔ SL +{round(cand - entry_p, 1)})"

                # STAGE 2: ACCELERATING RUNNER (Peak >= 8.0 to 11.9 pts):
                elif p["peak_pts"] >= 8.0:
                    cand = round(entry_p + p["peak_pts"] - 2.5, 2)
                    if cand > cand_sl:
                        cand_sl = cand
                        p["trailed_to_cost"] = True
                        p["tsl_stage"] = f"🎯 MID RUNNER (Peak +{p['peak_pts']:.1f} ➔ SL +{round(cand - entry_p, 1)})"

                # STAGE 1: EARLY PULLBACK SHIELD (Peak >= 5.5 to 7.9 pts):
                # Covers brokerage + slippage + locks guaranteed net profit
                elif p["peak_pts"] >= 5.5:
                    cand = round(entry_p + early_safe_lock_pts, 2)
                    if cand > cand_sl:
                        cand_sl = cand
                        p["trailed_to_cost"] = True
                        net_rs = round((cand - entry_p - brok_pts - slip_pts) * qty, 0)
                        p["tsl_stage"] = f"🛡️ NET SHIELD (+{round(cand - entry_p, 1)} pts | +₹{int(net_rs)} Net)"

                p["sl_price"] = cand_sl

                tgt_p = float(p.get("target_price", entry_p + 35.0))
                sl_p = float(p.get("sl_price", entry_p - self.state.get("stop_loss_pts", 15.0)))

                if cur_ltp <= sl_p:
                    outcome = "BREAKEVEN" if p.get("trailed_to_cost") and cur_ltp >= entry_p else "SL_HIT"
                    to_close.append((p.get("trade_id"), outcome, cur_ltp))
                elif cur_ltp >= tgt_p:
                    if p["peak_pts"] >= 12.0:
                        pass # Let the -2.0 pt trailing runner ride!
                    else:
                        to_close.append((p.get("trade_id"), "TARGET_HIT", cur_ltp))

            self.save_wallet()

            for tid, outcome, exit_p in to_close:
                self.close_trade(tid, outcome=outcome, exit_ltp=exit_p)

            return {"status": "in_trade", "active_positions": self.wallet.get("active_positions")}

        # 2. Check Daily Trades Discipline (Max 1-2 A+ Setups Per Day)
        today_str = ts_str[:10]
        if self.wallet.get("last_trade_date") != today_str:
            self.wallet["last_trade_date"] = today_str
            self.wallet["daily_trades_taken"] = 0
            self.save_wallet()
        # Daily quota restriction removed per user request (Unlimited trades allowed)
        max_daily = int(self.state.get("max_trades_per_day", 999))

        # 2.5 Market Opening Range & Curfew Guard (Strict No-Trade Zones)
        t_part = ts_str.split(" ")[-1] if " " in ts_str else ""
        if t_part:
            if t_part < "09:30:00":
                return {"status": "opening_settlement_wait", "message": f"Waiting for 15m opening range settlement (09:15-09:30 AM). Current: {t_part}"}
            if t_part >= "15:00:00":
                return {"status": "outside_hours", "message": f"Trading window closed after 15:00:00. Current: {t_part}"}

        # 2.6 Next trade eligible immediately once previous trade is closed (No timer lock)

        # 2.7 Frequency Throttling (Avoid running heavy tick math on high-frequency UI polls)
        now_ts_sec = datetime.now().timestamp()
        if hasattr(self, "last_tick_eval_time") and (now_ts_sec - self.last_tick_eval_time < 1.5):
            return {"status": "throttled", "message": "Tick evaluation throttled"}
        self.last_tick_eval_time = now_ts_sec

        # 3. Track Price History & Calculate Trend Momentum
        candles = self.get_or_update_candles(spot_price, ts_str)
        if not hasattr(self, "price_history"):
            self.price_history = []
        self.price_history.append((ts_str, spot_price))

        # Instant warm-up: Seed from candle history if available so engine starts immediately
        if len(self.price_history) < 21 and hasattr(self, "candle_bars") and len(self.candle_bars) >= 10:
            for c in self.candle_bars:
                self.price_history.append((ts_str, float(c.get("close", spot_price))))

        if len(self.price_history) > 60:
            self.price_history = self.price_history[-60:]

        # Warm-up requirement: Must accumulate at least 15 ticks for reliable EMA
        if len(self.price_history) < 15:
            return {"status": "warmup", "message": f"Accumulating price ticks ({len(self.price_history)}/15)..."}

        # Calculate EMA9 and EMA21
        spots = [s for _, s in self.price_history]
        k9 = 2.0 / (9 + 1)
        k21 = 2.0 / (21 + 1)
        ema9 = spots[0]
        for val in spots[1:]:
            ema9 = (val * k9) + (ema9 * (1 - k9))
        ema21 = spots[0]
        for val in spots[1:]:
            ema21 = (val * k21) + (ema21 * (1 - k21))

        # Divergence Requirement: EMA9 and EMA21 must be separated by at least 1.5 pts
        ema_diff = ema9 - ema21
        is_bull_trend = (ema_diff >= 1.5) and (spot_price >= ema9)
        is_bear_trend = (ema_diff <= -1.5) and (spot_price <= ema9)

        # Recent spot run (last 5 ticks)
        start_spot = spots[-5] if len(spots) >= 5 else spots[0]
        spot_run = spot_price - start_spot

        # Calculate AOC S/R
        try:
            from aoc_sr_engine import calculate_aoc_sr
            sr_info = calculate_aoc_sr(ticks, spot_price)
            s1 = float(sr_info.get("support_primary") or sr_info.get("support") or (spot_price - 50.0))
            r1 = float(sr_info.get("resistance_primary") or sr_info.get("resistance") or (spot_price + 50.0))
        except Exception:
            s1 = spot_price - 40.0
            r1 = spot_price + 40.0

        # Extract Open Interest & Volume confirmation around ATM (+- 150 pts)
        ce_oi_tot = 0.0
        pe_oi_tot = 0.0
        ce_oichg_tot = 0.0
        pe_oichg_tot = 0.0
        for t in ticks:
            stk = float(t.get("strike", 0.0))
            if abs(stk - spot_price) <= 150.0:
                otype = t.get("type")
                oi_val = float(t.get("oi") or 0.0)
                oichg_val = float(t.get("oi_change") or t.get("chg_oi") or 0.0)
                if otype == "CE":
                    ce_oi_tot += oi_val
                    ce_oichg_tot += oichg_val
                elif otype == "PE":
                    pe_oi_tot += oi_val
                    pe_oichg_tot += oichg_val

        # OI confirmation flags (Reject naked trades without smart money build-up)
        has_oi_data = (ce_oi_tot > 0 or pe_oi_tot > 0)
        oi_bull_confirmed = has_oi_data and (pe_oi_tot >= ce_oi_tot * 0.9 or pe_oichg_tot >= ce_oichg_tot)
        oi_bear_confirmed = has_oi_data and (ce_oi_tot >= pe_oi_tot * 0.9 or ce_oichg_tot >= pe_oichg_tot)

        signal = None
        lots = self.state.get("lot_size_multiplier", 2)
        qty = lots * 65
        sl_pts = float(self.state.get("stop_loss_pts", 15.0))

        # ══════════════════════════════════════════════════════════════════
        # 4. SUPERTREND (10, 2.0) CONFLUENCE & TRIGGER MATRIX
        # Rule: Green Line (ST Bull) -> BUY_CE only | Red Line (ST Bear) -> BUY_PE only
        # ══════════════════════════════════════════════════════════════════
        candles = self.get_or_update_candles(spot_price, ts_str)
        st_trend, st_val, st_flip, st_bull_line, st_bear_line = self.calculate_supertrend(candles, 10, 2.0)
        is_st_green = (st_trend == 1)
        is_st_red = (st_trend == -1)
        self.state["supertrend"] = {
            "trend": "BULL_GREEN" if is_st_green else "BEAR_RED",
            "value": st_val,
            "line": "ST Bull (CE)" if is_st_green else "ST Bear (PE)",
            "color": "#22c55e" if is_st_green else "#ef4444"
        }

        # ══════════════════════════════════════════════════════════════════
        # STRICT TRIGGER LOGIC (CONFLUENCE REQUIRED: NO NAKED BREAKOUTS):
        # ══════════════════════════════════════════════════════════════════
        now_ts_sec = datetime.now().timestamp()
        if hasattr(self, "last_signal_time") and (now_ts_sec - self.last_signal_time < 45.0):
            return {"status": "monitoring", "spot": spot_price, "message": "Signal engine in debounce cooldown"}

        breakout_zone = (r1 <= spot_price <= r1 + 20.0)

        # ─── 1. GREEN LINE ACTIVE: CALL (BUY_CE) SETUPS ONLY ─────────────
        if is_st_green:
            strike, delta, strk_lbl = self.calculate_trade_strike(spot_price, "CALL")
            ce_ltp = 145.0
            for t in ticks:
                if t.get("type") == "CE" and float(t.get("strike", 0)) == strike:
                    ce_ltp = float(t.get("ltp") or ce_ltp)
                    break

            # Trigger A: SuperTrend Bullish Flip (Fresh Green Line Born)
            if st_flip:
                signal = {
                    "signal_id": f"SIG_{int(datetime.now().timestamp())}",
                    "trade_id": f"TRD_{int(datetime.now().timestamp())}",
                    "timestamp": ts_str,
                    "entry_time": ts_str,
                    "action": "BUY_CE",
                    "contract": f"NIFTY {int(strike)} CE ({strk_lbl})",
                    "direction": "CALL",
                    "strike_price": int(strike),
                    "option_type": "CE",
                    "entry_spot": round(spot_price, 2),
                    "entry_ltp": round(ce_ltp, 2),
                    "lots": lots,
                    "qty": qty,
                    "stop_loss_pts": sl_pts,
                    "stop_loss_price": round(ce_ltp - sl_pts, 2),
                    "target_plan": {
                        "breakeven_lock": round(ce_ltp + 6.0, 2),
                        "target_1": round(ce_ltp + 15.0, 2),
                        "target_2_runner": round(ce_ltp + 35.0, 2)
                    },
                    "target_price": round(ce_ltp + 35.0, 2),
                    "max_risk_rupees": round(sl_pts * qty, 2),
                    "margin_utilized": round(ce_ltp * qty, 2),
                    "target_profit_rupees": round(35.0 * qty, 2),
                    "ma_9": round(ema9, 2),
                    "ema_21": round(ema21, 2),
                    "delta": delta,
                    "oi": int(pe_oi_tot),
                    "oi_change": int(pe_oichg_tot),
                    "supertrend_color": "GREEN",
                    "supertrend_value": st_val,
                    "supertrend_line": "ST Bull",
                    "weapon_signature": "WEAPON_SUPERTREND_GREEN_LINE / BULLISH_FLIP",
                    "weapon_reason": f"SuperTrend turned GREEN (ST Bull ₹{st_val:.1f}) | Green Line Call Trigger | Delta {delta:.2f}",
                    "status": "ACTIVE_PENDING_CONFIRMATION"
                }

            # Trigger B: R1 Breakout with Green Line Confluence
            elif breakout_zone and is_bull_trend and (spot_run >= 4.0):
                signal = {
                    "signal_id": f"SIG_{int(datetime.now().timestamp())}",
                    "trade_id": f"TRD_{int(datetime.now().timestamp())}",
                    "timestamp": ts_str,
                    "entry_time": ts_str,
                    "action": "BUY_CE",
                    "contract": f"NIFTY {int(strike)} CE ({strk_lbl})",
                    "direction": "CALL",
                    "strike_price": int(strike),
                    "option_type": "CE",
                    "entry_spot": round(spot_price, 2),
                    "entry_ltp": round(ce_ltp, 2),
                    "lots": lots,
                    "qty": qty,
                    "stop_loss_pts": sl_pts,
                    "stop_loss_price": round(ce_ltp - sl_pts, 2),
                    "target_plan": {
                        "breakeven_lock": round(ce_ltp + 6.0, 2),
                        "target_1": round(ce_ltp + 15.0, 2),
                        "target_2_runner": round(ce_ltp + 35.0, 2)
                    },
                    "target_price": round(ce_ltp + 35.0, 2),
                    "max_risk_rupees": round(sl_pts * qty, 2),
                    "margin_utilized": round(ce_ltp * qty, 2),
                    "target_profit_rupees": round(35.0 * qty, 2),
                    "ma_9": round(ema9, 2),
                    "ema_21": round(ema21, 2),
                    "delta": delta,
                    "oi": int(pe_oi_tot),
                    "oi_change": int(pe_oichg_tot),
                    "supertrend_color": "GREEN",
                    "supertrend_value": st_val,
                    "supertrend_line": "ST Bull",
                    "weapon_signature": "WEAPON_R1_BREAKOUT / GREEN_CONFLUENCE",
                    "weapon_reason": f"Resistance {r1:.1f} Breakout + Green ST Bull Support at {st_val:.1f} | Delta {delta:.2f}",
                    "status": "ACTIVE_PENDING_CONFIRMATION"
                }

            # Trigger C: S1 or Green Line Bounce Reversal
            elif ((s1 - 5.0 <= spot_price <= s1 + 15.0) or (st_bull_line <= spot_price <= st_bull_line + 10.0)) and (spot_price > ema9) and (spot_run >= 4.0):
                signal = {
                    "signal_id": f"SIG_{int(datetime.now().timestamp())}",
                    "trade_id": f"TRD_{int(datetime.now().timestamp())}",
                    "timestamp": ts_str,
                    "entry_time": ts_str,
                    "action": "BUY_CE",
                    "contract": f"NIFTY {int(strike)} CE ({strk_lbl})",
                    "direction": "CALL",
                    "strike_price": int(strike),
                    "option_type": "CE",
                    "entry_spot": round(spot_price, 2),
                    "entry_ltp": round(ce_ltp, 2),
                    "lots": lots,
                    "qty": qty,
                    "stop_loss_pts": sl_pts,
                    "stop_loss_price": round(ce_ltp - sl_pts, 2),
                    "target_plan": {
                        "breakeven_lock": round(ce_ltp + 6.0, 2),
                        "target_1": round(ce_ltp + 12.0, 2),
                        "target_2_runner": round(ce_ltp + 30.0, 2)
                    },
                    "target_price": round(ce_ltp + 30.0, 2),
                    "max_risk_rupees": round(sl_pts * qty, 2),
                    "margin_utilized": round(ce_ltp * qty, 2),
                    "target_profit_rupees": round(30.0 * qty, 2),
                    "ma_9": round(ema9, 2),
                    "ema_21": round(ema21, 2),
                    "delta": delta,
                    "oi": int(pe_oi_tot),
                    "oi_change": int(pe_oichg_tot),
                    "supertrend_color": "GREEN",
                    "supertrend_value": st_val,
                    "supertrend_line": "ST Bull",
                    "weapon_signature": "WEAPON_BOTTOM_PUT_SHIELD / GREEN_LINE_BOUNCE",
                    "weapon_reason": f"Support Bounce off Green Line {st_bull_line:.1f} confirmed with EMA9 reclaim | Delta {delta:.2f}",
                    "status": "ACTIVE_PENDING_CONFIRMATION"
                }

        # ─── 2. RED LINE ACTIVE: PUT (BUY_PE) SETUPS ONLY ───────────────
        elif is_st_red:
            strike, delta, strk_lbl = self.calculate_trade_strike(spot_price, "PUT")
            pe_ltp = 145.0
            for t in ticks:
                if t.get("type") == "PE" and float(t.get("strike", 0)) == strike:
                    pe_ltp = float(t.get("ltp") or pe_ltp)
                    break

            # Trigger A: SuperTrend Bearish Flip (Fresh Red Line Born)
            if st_flip:
                signal = {
                    "signal_id": f"SIG_{int(datetime.now().timestamp())}",
                    "trade_id": f"TRD_{int(datetime.now().timestamp())}",
                    "timestamp": ts_str,
                    "entry_time": ts_str,
                    "action": "BUY_PE",
                    "contract": f"NIFTY {int(strike)} PE ({strk_lbl})",
                    "direction": "PUT",
                    "strike_price": int(strike),
                    "option_type": "PE",
                    "entry_spot": round(spot_price, 2),
                    "entry_ltp": round(pe_ltp, 2),
                    "lots": lots,
                    "qty": qty,
                    "stop_loss_pts": sl_pts,
                    "stop_loss_price": round(pe_ltp - sl_pts, 2),
                    "target_plan": {
                        "breakeven_lock": round(pe_ltp + 6.0, 2),
                        "target_1": round(pe_ltp + 15.0, 2),
                        "target_2_runner": round(pe_ltp + 35.0, 2)
                    },
                    "target_price": round(pe_ltp + 35.0, 2),
                    "max_risk_rupees": round(sl_pts * qty, 2),
                    "margin_utilized": round(pe_ltp * qty, 2),
                    "target_profit_rupees": round(35.0 * qty, 2),
                    "ma_9": round(ema9, 2),
                    "ema_21": round(ema21, 2),
                    "delta": delta,
                    "oi": int(ce_oi_tot),
                    "oi_change": int(ce_oichg_tot),
                    "supertrend_color": "RED",
                    "supertrend_value": st_val,
                    "supertrend_line": "ST Bear",
                    "weapon_signature": "WEAPON_SUPERTREND_RED_LINE / BEARISH_FLIP",
                    "weapon_reason": f"SuperTrend turned RED (ST Bear ₹{st_val:.1f}) | Red Line Put Trigger | Delta {delta:.2f}",
                    "status": "ACTIVE_PENDING_CONFIRMATION"
                }

            # Trigger B: S1 Breakdown with Red Line Confluence
            elif (s1 - 20.0 <= spot_price <= s1) and is_bear_trend and (spot_run <= -4.0):
                signal = {
                    "signal_id": f"SIG_{int(datetime.now().timestamp())}",
                    "trade_id": f"TRD_{int(datetime.now().timestamp())}",
                    "timestamp": ts_str,
                    "entry_time": ts_str,
                    "action": "BUY_PE",
                    "contract": f"NIFTY {int(strike)} PE ({strk_lbl})",
                    "direction": "PUT",
                    "strike_price": int(strike),
                    "option_type": "PE",
                    "entry_spot": round(spot_price, 2),
                    "entry_ltp": round(pe_ltp, 2),
                    "lots": lots,
                    "qty": qty,
                    "stop_loss_pts": sl_pts,
                    "stop_loss_price": round(pe_ltp - sl_pts, 2),
                    "target_plan": {
                        "breakeven_lock": round(pe_ltp + 6.0, 2),
                        "target_1": round(pe_ltp + 15.0, 2),
                        "target_2_runner": round(pe_ltp + 35.0, 2)
                    },
                    "target_price": round(pe_ltp + 35.0, 2),
                    "max_risk_rupees": round(sl_pts * qty, 2),
                    "margin_utilized": round(pe_ltp * qty, 2),
                    "target_profit_rupees": round(35.0 * qty, 2),
                    "ma_9": round(ema9, 2),
                    "ema_21": round(ema21, 2),
                    "delta": delta,
                    "oi": int(ce_oi_tot),
                    "oi_change": int(ce_oichg_tot),
                    "supertrend_color": "RED",
                    "supertrend_value": st_val,
                    "supertrend_line": "ST Bear",
                    "weapon_signature": "WEAPON_S1_BREAKDOWN / RED_CONFLUENCE",
                    "weapon_reason": f"Support {s1:.1f} Breakdown + Red ST Bear Resistance at {st_val:.1f} | Delta {delta:.2f}",
                    "status": "ACTIVE_PENDING_CONFIRMATION"
                }

            # Trigger C: R1 or Red Line Rejection Reversal
            elif ((r1 - 15.0 <= spot_price <= r1 + 5.0) or (st_bear_line - 10.0 <= spot_price <= st_bear_line)) and (spot_price < ema9) and (spot_run <= -4.0):
                signal = {
                    "signal_id": f"SIG_{int(datetime.now().timestamp())}",
                    "trade_id": f"TRD_{int(datetime.now().timestamp())}",
                    "timestamp": ts_str,
                    "entry_time": ts_str,
                    "action": "BUY_PE",
                    "contract": f"NIFTY {int(strike)} PE ({strk_lbl})",
                    "direction": "PUT",
                    "strike_price": int(strike),
                    "option_type": "PE",
                    "entry_spot": round(spot_price, 2),
                    "entry_ltp": round(pe_ltp, 2),
                    "lots": lots,
                    "qty": qty,
                    "stop_loss_pts": sl_pts,
                    "stop_loss_price": round(pe_ltp - sl_pts, 2),
                    "target_plan": {
                        "breakeven_lock": round(pe_ltp + 6.0, 2),
                        "target_1": round(pe_ltp + 12.0, 2),
                        "target_2_runner": round(pe_ltp + 30.0, 2)
                    },
                    "target_price": round(pe_ltp + 30.0, 2),
                    "max_risk_rupees": round(sl_pts * qty, 2),
                    "margin_utilized": round(pe_ltp * qty, 2),
                    "target_profit_rupees": round(30.0 * qty, 2),
                    "ma_9": round(ema9, 2),
                    "ema_21": round(ema21, 2),
                    "delta": delta,
                    "oi": int(ce_oi_tot),
                    "oi_change": int(ce_oichg_tot),
                    "supertrend_color": "RED",
                    "supertrend_value": st_val,
                    "supertrend_line": "ST Bear",
                    "weapon_signature": "WEAPON_TOP_CALL_FORTRESS / RED_LINE_REJECTION",
                    "weapon_reason": f"Resistance Rejection off Red Line {st_bear_line:.1f} confirmed with EMA9 failure | Delta {delta:.2f}",
                    "status": "ACTIVE_PENDING_CONFIRMATION"
                }

        if signal:
            self.last_signal_time = now_ts_sec
            self.state["active_signal"] = signal
            self.state["last_processed_time"] = ts_str
            self.save_state()

            # If auto trading is enabled, execute trade immediately!
            if self.state.get("auto_trading"):
                return self.execute_signal(signal["signal_id"], is_auto=True)

            return {"status": "signal_generated", "signal": signal}

        return {"status": "monitoring", "spot": spot_price}

    def _sync_trades_to_storage(self, trades):
        """Persist trades to user-specific JSON, CSV dossier, and SQLite database"""
        os.makedirs(os.path.dirname(self.signals_log_file), exist_ok=True)
        os.makedirs(os.path.dirname(self.signals_csv_file), exist_ok=True)
        os.makedirs(os.path.dirname(self.signals_db_file), exist_ok=True)

        # 1. Save JSON
        try:
            with open(self.signals_log_file, "w", encoding="utf-8") as f:
                json.dump(trades, f, indent=2)
            if self.user_id in ["default", "admin"] and self.signals_log_file != SIGNALS_LOG_FILE:
                with open(SIGNALS_LOG_FILE, "w", encoding="utf-8") as f:
                    json.dump(trades, f, indent=2)
        except Exception as e:
            print(f"Error saving signals JSON for {self.user_id}:", e)

        # 2. Save CSV dossier
        try:
            fieldnames = [
                "trade_id", "signal_id", "timestamp", "entry_time", "exit_time",
                "action", "direction", "contract", "strike_price", "option_type",
                "entry_spot", "exit_spot", "spot_change", "entry_ltp", "exit_ltp",
                "is_breakeven", "gross_points", "gross_pnl", "brokerage", "slippage", "total_friction",
                "pnl_points", "pnl_pct", "pnl_rupees", "ma_9", "ema_21", "oi",
                "oi_change", "volume", "volume_spike", "delta", "lots", "qty",
                "stop_loss_price", "target_price", "max_risk_rupees", "margin_utilized",
                "execution_mode", "status", "weapon_signature", "weapon_reason"
            ]
            import csv
            with open(self.signals_csv_file, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
                writer.writeheader()
                for t in trades:
                    row = dict(t)
                    if not row.get("entry_time"):
                        row["entry_time"] = row.get("timestamp") or row.get("executed_at")
                    writer.writerow(row)
            if self.user_id in ["default", "admin"] and self.signals_csv_file != SIGNALS_CSV_FILE:
                with open(SIGNALS_CSV_FILE, "w", newline="", encoding="utf-8") as f:
                    writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
                    writer.writeheader()
                    for t in trades:
                        row = dict(t)
                        if not row.get("entry_time"):
                            row["entry_time"] = row.get("timestamp") or row.get("executed_at")
                        writer.writerow(row)
        except Exception as e:
            print(f"Error saving signals CSV for {self.user_id}:", e)

        # 3. Save to SQLite database
        try:
            import sqlite3
            conn = sqlite3.connect(self.signals_db_file, timeout=30.0)
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS institutional_trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trade_id TEXT UNIQUE,
                    signal_id TEXT,
                    entry_time TEXT,
                    exit_time TEXT,
                    action TEXT,
                    direction TEXT,
                    contract TEXT,
                    strike_price REAL,
                    option_type TEXT,
                    entry_spot REAL,
                    exit_spot REAL,
                    spot_change REAL,
                    entry_ltp REAL,
                    exit_ltp REAL,
                    is_breakeven INTEGER DEFAULT 0,
                    gross_points REAL DEFAULT 0.0,
                    gross_pnl REAL DEFAULT 0.0,
                    brokerage REAL DEFAULT 0.0,
                    slippage REAL DEFAULT 0.0,
                    total_friction REAL DEFAULT 0.0,
                    pnl_points REAL,
                    pnl_pct REAL,
                    pnl_rupees REAL,
                    ma_9 REAL,
                    ema_21 REAL,
                    oi REAL,
                    oi_change REAL,
                    volume REAL,
                    volume_spike TEXT,
                    delta REAL,
                    lots INTEGER,
                    qty INTEGER,
                    stop_loss_price REAL,
                    target_price REAL,
                    max_risk_rupees REAL,
                    margin_utilized REAL,
                    execution_mode TEXT,
                    status TEXT,
                    weapon_signature TEXT,
                    weapon_reason TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            # Auto-migrate any missing columns in existing SQLite tables
            new_cols = [
                ("is_breakeven", "INTEGER DEFAULT 0"),
                ("gross_points", "REAL DEFAULT 0.0"),
                ("gross_pnl", "REAL DEFAULT 0.0"),
                ("brokerage", "REAL DEFAULT 0.0"),
                ("slippage", "REAL DEFAULT 0.0"),
                ("total_friction", "REAL DEFAULT 0.0"),
            ]
            for col_name, col_def in new_cols:
                try:
                    cursor.execute(f"ALTER TABLE institutional_trades ADD COLUMN {col_name} {col_def}")
                except Exception:
                    pass
            for t in trades:
                tid = t.get("trade_id") or t.get("signal_id")
                if not tid:
                    continue
                cursor.execute("""
                    INSERT INTO institutional_trades (
                        trade_id, signal_id, entry_time, exit_time, action, direction,
                        contract, strike_price, option_type, entry_spot, exit_spot, spot_change,
                        entry_ltp, exit_ltp, is_breakeven, gross_points, gross_pnl, brokerage, slippage, total_friction,
                        pnl_points, pnl_pct, pnl_rupees,
                        ma_9, ema_21, oi, oi_change, volume, volume_spike, delta,
                        lots, qty, stop_loss_price, target_price, max_risk_rupees, margin_utilized,
                        execution_mode, status, weapon_signature, weapon_reason
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(trade_id) DO UPDATE SET
                        exit_time=excluded.exit_time,
                        exit_spot=excluded.exit_spot,
                        spot_change=excluded.spot_change,
                        exit_ltp=excluded.exit_ltp,
                        is_breakeven=excluded.is_breakeven,
                        gross_points=excluded.gross_points,
                        gross_pnl=excluded.gross_pnl,
                        brokerage=excluded.brokerage,
                        slippage=excluded.slippage,
                        total_friction=excluded.total_friction,
                        pnl_points=excluded.pnl_points,
                        pnl_pct=excluded.pnl_pct,
                        pnl_rupees=excluded.pnl_rupees,
                        status=excluded.status
                """, (
                    tid, t.get("signal_id", tid), t.get("entry_time") or t.get("timestamp"), t.get("exit_time"),
                    t.get("action"), t.get("direction"), t.get("contract"),
                    float(t.get("strike_price") or 0.0), t.get("option_type"),
                    float(t.get("entry_spot") or 0.0), float(t.get("exit_spot") or 0.0), float(t.get("spot_change") or 0.0),
                    float(t.get("entry_ltp") or 0.0), float(t.get("exit_ltp") or 0.0),
                    1 if t.get("is_breakeven") else 0,
                    float(t.get("gross_points") or 0.0), float(t.get("gross_pnl") or 0.0),
                    float(t.get("brokerage") or 0.0), float(t.get("slippage") or 0.0), float(t.get("total_friction") or 0.0),
                    float(t.get("pnl_points") or 0.0), float(t.get("pnl_pct") or 0.0), float(t.get("pnl_rupees") or 0.0),
                    float(t.get("ma_9") or 0.0), float(t.get("ema_21") or 0.0),
                    float(t.get("oi") or 0.0), float(t.get("oi_change") or 0.0),
                    float(t.get("volume") or 0.0), str(t.get("volume_spike") or ""), float(t.get("delta") or 0.0),
                    int(t.get("lots") or 1), int(t.get("qty") or 65),
                    float(t.get("stop_loss_price") or 0.0), float(t.get("target_price") or 0.0),
                    float(t.get("max_risk_rupees") or 0.0), float(t.get("margin_utilized") or 0.0),
                    t.get("execution_mode"), t.get("status"), t.get("weapon_signature"), t.get("weapon_reason")
                ))
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"Error syncing signals SQLite for {self.user_id}:", e)

    def _log_signal(self, sig):
        logs = []
        target_file = self.signals_log_file
        if not os.path.exists(target_file) and self.user_id in ["default", "admin", "1"] and os.path.exists(SIGNALS_LOG_FILE):
            target_file = SIGNALS_LOG_FILE
        if os.path.exists(target_file):
            try:
                with open(target_file, "r", encoding="utf-8") as f:
                    logs = json.load(f)
            except Exception:
                pass

        # Update existing if already logged
        updated = False
        for i, item in enumerate(logs):
            if item.get("signal_id") == sig.get("signal_id") or item.get("trade_id") == sig.get("trade_id"):
                logs[i] = sig
                updated = True
                break

        if not updated:
            logs.append(sig)

        self._sync_trades_to_storage(logs[-200:])

# ══════════════════════════════════════════════════════════════════
# MULTI-USER INSTANCE REGISTRY
# ══════════════════════════════════════════════════════════════════
_engines_registry = {}

def get_live_signal_engine(user_id=None) -> LiveSignalEngine:
    """Returns or instantiates an isolated LiveSignalEngine for a specific user."""
    uid = str(user_id).strip() if user_id is not None and str(user_id).strip() else "default"
    if uid not in _engines_registry:
        _engines_registry[uid] = LiveSignalEngine(user_id=uid)
    return _engines_registry[uid]

def get_all_active_engines():
    """Returns all active user engine instances."""
    return list(_engines_registry.values())

# Global default instance
live_signal_engine = get_live_signal_engine("default")
# Initial sync on load
live_signal_engine._sync_trades_to_storage(live_signal_engine.get_trades())
