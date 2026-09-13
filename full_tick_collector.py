# ══════════════════════════════════════════════════════════════════
#  Full Tick Collector Engine for NIFTY50 Complete Option Chain
#  Connects Fyers WebSocket -> Calculates Greeks/RSI -> DuckDB Engine
# ══════════════════════════════════════════════════════════════════
import os
import sys
import time
import math
import random
import threading
from datetime import datetime, date

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

try:
    from common_fyers import load_fyers, get_access_token, INDEX_SYMBOLS, api_option_chain, api_expiries, resolve_strikecount
    HAS_FYERS = True
except Exception:
    HAS_FYERS = False
    INDEX_SYMBOLS = {"NIFTY": "NSE:NIFTY50-INDEX"}
    load_fyers = lambda: None
    get_access_token = lambda: None
    api_option_chain = lambda *args, **kwargs: (None, "Fyers not installed")
    api_expiries = lambda *args, **kwargs: (None, "Fyers not installed")
    resolve_strikecount = lambda *args: 20

from duckdb_engine import duckdb_engine
from greeks_calculator import black_scholes_greeks, implied_volatility, calculate_rsi, calculate_slope, compute_signal

try:
    from log_utils import log_error
except Exception:
    def log_error(*args, **kwargs): pass

try:
    from fyers_apiv3.FyersWebsocket.data_ws import FyersDataSocket
    HAS_WS = True
except Exception:
    HAS_WS = False

class FullTickCollector:
    """Collects tick-by-tick NIFTY50 option chain data and writes to DuckDB."""
    
    def __init__(self, symbol="NSE:NIFTY50-INDEX", strike_count=20, allow_simulation=False):
        self.symbol = symbol
        self.strike_count = strike_count
        self.allow_simulation = allow_simulation
        self.fyers = None
        self._running = False
        self._subscribed_symbols = []
        self._history_buffer = {}  # symbol -> list of price history for RSI/slope
        self._prev_snapshot = {}  # symbol -> last record
        self._lock = threading.Lock()
        self._last_token_warning_time = 0
        self._connected_status = (False, "Initializing")

        self._init_fyers()

    def _init_fyers(self):
        try:
            self.fyers = load_fyers()
            if self.fyers:
                self._connected_status = (True, "Connected")
        except Exception as e:
            self.fyers = None
            self._connected_status = (False, str(e))

    def is_fyers_connected(self):
        """Check if Fyers API is properly logged in and token is valid (non-blocking)."""
        if hasattr(self, '_connected_status') and self._connected_status[0]:
            return self._connected_status
        if not self.fyers:
            self._init_fyers()
        return getattr(self, '_connected_status', (False, "Not connected"))

    def get_available_expiries(self):
        """Fetch list of active expiry dates from live Fyers API formatted as 'DD Mon YYYY' (cached 300s)."""
        now = time.time()
        if hasattr(self, '_expiries_cache') and (now - getattr(self, '_expiries_cache_time', 0) < 300):
            return self._expiries_cache
        if not self.fyers:
            self._init_fyers()
        if not self.fyers:
            return []
        try:
            exp_list, err = api_expiries(self.fyers, self.symbol)
            if exp_list and not err:
                labels = []
                for exp in exp_list:
                    dt_str = exp.get("date", "")
                    if dt_str:
                        parsed = False
                        for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d-%b-%Y", "%d-%B-%Y"):
                            try:
                                dt_obj = datetime.strptime(dt_str, fmt)
                                labels.append(dt_obj.strftime("%d %b %Y"))
                                parsed = True
                                break
                            except Exception:
                                pass
                        if not parsed:
                            labels.append(dt_str)
                self._expiries_cache = labels
                self._expiries_cache_time = now
                return labels
        except Exception:
            pass
        return getattr(self, '_expiries_cache', [])

    def fetch_current_nifty_chain(self):
        """Fetch option chain snapshot from Fyers API & calculate all fields."""
        if not self.fyers:
            self._init_fyers()

        if not self.fyers:
            if self.allow_simulation:
                return self._generate_simulated_nifty_chain()
            return None

        exp_list, err = api_expiries(self.fyers, self.symbol)
        if not exp_list or err:
            # Try reloading token once
            self._init_fyers()
            if self.fyers:
                exp_list, err = api_expiries(self.fyers, self.symbol)

        if not exp_list or err:
            self._connected_status = (False, f"Fyers feed offline / token expired: {err}")
            cur_time = time.time()
            if cur_time - self._last_token_warning_time > 30:
                print(f"⚠️ [Collector Notice] Live Fyers feed offline / token expired: {err}. Serving DuckDB real dataset.")
                self._last_token_warning_time = cur_time
            if self.allow_simulation:
                return self._generate_simulated_nifty_chain()
            return None

        expiry_epoch = exp_list[0].get("expiry", "")
        res = api_option_chain(self.fyers, self.symbol, self.strike_count, expiry_epoch)
        if res[0] is None or res[0].empty:
            self._connected_status = (False, "Empty option chain received from Fyers")
            if self.allow_simulation:
                return self._generate_simulated_nifty_chain()
            return None

        self._connected_status = (True, "Connected")
        df_chain, summary, spot_price = res
        now_str = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

        records = []
        spot_p = spot_price or 24499.9

        for _, row in df_chain.iterrows():
            sym = row.get("symbol", "")
            strike = float(row.get("strike_price", 0))
            opt_type = str(row.get("option_type", "CE")).upper()
            ltp = float(row.get("ltp", 0.0))
            oi = float(row.get("oi", 0.0))
            vol = float(row.get("volume", 0.0))
            prev_oi = float(row.get("prev_oi", oi))

            # Maintain price history for RSI & slope
            with self._lock:
                if sym not in self._history_buffer:
                    self._history_buffer[sym] = []
                self._history_buffer[sym].append(ltp)
                if len(self._history_buffer[sym]) > 50:
                    self._history_buffer[sym].pop(0)

                prices = self._history_buffer[sym]

            # Greeks calculation
            t_years = max(1 / 365.0, 7 / 365.0)  # ~7 days to expiry default
            iv = implied_volatility(ltp, spot_p, strike, t_years, opt_type)
            greeks = black_scholes_greeks(spot_p, strike, t_years, iv, opt_type)

            rsi = calculate_rsi(prices)
            slope = calculate_slope(prices)

            # OI change & signal
            oi_change = float(row.get("oi_change", oi - prev_oi))
            oi_change_pct = float(row.get("oi_change_pct", round((oi_change / prev_oi * 100.0), 2) if prev_oi > 0 else 0.0))
            prev_ltp = self._prev_snapshot.get(sym, {}).get("ltp", ltp)
            price_change = ltp - prev_ltp

            signal = compute_signal(price_change, oi_change, opt_type)

            rec = {
                "timestamp": now_str,
                "symbol": sym,
                "strike": strike,
                "type": opt_type,
                "spot_price": spot_p,
                "open": float(row.get("open", ltp)),
                "high": float(row.get("high", ltp)),
                "low": float(row.get("low", ltp)),
                "close": float(row.get("close", ltp)),
                "ltp": ltp,
                "oi": oi,
                "volume": vol,
                "delta": greeks["delta"],
                "gamma": greeks["gamma"],
                "theta": greeks["theta"],
                "vega": greeks["vega"],
                "rsi": rsi,
                "slope": oi_change, # Store real oi_change in slope column for DuckDB ticks compatibility
                "oi_change_pct": oi_change_pct,
                "signal": signal
            }
            records.append(rec)
            self._prev_snapshot[sym] = rec

        return records

    def _generate_simulated_nifty_chain(self):
        """Simulate complete NIFTY50 option chain ticks when market is offline or testing."""
        now_str = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        spot_p = round(24500.0 + random.uniform(-15.0, 15.0), 2)
        base_strikes = list(range(23500, 25550, 50))

        records = []
        for strike in base_strikes:
            for opt_type in ["CE", "PE"]:
                sym = f"NSE:NIFTY26AUG{strike}{opt_type}"
                dist = (strike - spot_p) if opt_type == "CE" else (spot_p - strike)
                
                # Approximate intrinsic + extrinsic value
                if opt_type == "CE":
                    intrinsic = max(0, spot_p - strike)
                else:
                    intrinsic = max(0, strike - spot_p)

                time_val = max(5.0, 200.0 - abs(strike - spot_p) * 0.15)
                ltp = round(intrinsic + time_val + random.uniform(-1.0, 1.0), 2)
                oi = int(10000 + abs(25000 - strike) * 15 + random.randint(-500, 500))
                vol = int(5000 + random.randint(100, 3000))
                prev_oi = oi - random.randint(-200, 300)

                with self._lock:
                    if sym not in self._history_buffer:
                        self._history_buffer[sym] = [ltp]
                    else:
                        self._history_buffer[sym].append(ltp)
                        if len(self._history_buffer[sym]) > 50:
                            self._history_buffer[sym].pop(0)

                    prices = self._history_buffer[sym]

                t_years = 7 / 365.0
                iv = implied_volatility(ltp, spot_p, strike, t_years, opt_type)
                greeks = black_scholes_greeks(spot_p, strike, t_years, iv, opt_type)

                rsi = calculate_rsi(prices)
                slope = calculate_slope(prices)

                oi_change = oi - prev_oi
                oi_change_pct = round((oi_change / prev_oi * 100.0), 2) if prev_oi > 0 else 0.0
                prev_ltp = self._prev_snapshot.get(sym, {}).get("ltp", ltp)
                price_change = ltp - prev_ltp

                signal = compute_signal(price_change, oi_change, opt_type)

                rec = {
                    "timestamp": now_str,
                    "symbol": sym,
                    "strike": float(strike),
                    "type": opt_type,
                    "spot_price": spot_p,
                    "open": round(ltp - random.uniform(0, 2), 2),
                    "high": round(ltp + random.uniform(0, 3), 2),
                    "low": round(ltp - random.uniform(0, 3), 2),
                    "close": ltp,
                    "ltp": ltp,
                    "oi": float(oi),
                    "volume": float(vol),
                    "delta": greeks["delta"],
                    "gamma": greeks["gamma"],
                    "theta": greeks["theta"],
                    "vega": greeks["vega"],
                    "iv": round(iv * 100.0, 2),
                    "rsi": rsi,
                    "slope": slope,
                    "oi_change_pct": oi_change_pct,
                    "signal": signal
                }
                records.append(rec)
                self._prev_snapshot[sym] = rec

        return records

    def run_collector_loop(self, interval_sec=2):
        """Continuously collect NIFTY50 ticks and insert into DuckDB."""
        self._running = True
        print(f"🚀 NIFTY50 DuckDB Tick Collector started (Interval: {interval_sec}s)...")
        while self._running:
            try:
                records = self.fetch_current_nifty_chain()
                if records:
                    duckdb_engine.insert_ticks(records)
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] Saved {len(records)} NIFTY50 ticks into DuckDB.")
            except Exception as e:
                log_error("full_tick_collector", "run_collector_loop", e)
            time.sleep(interval_sec)

    def stop(self):
        self._running = False

if __name__ == "__main__":
    collector = FullTickCollector()
    try:
        collector.run_collector_loop(interval_sec=2)
    except KeyboardInterrupt:
        collector.stop()
        print("Collector stopped.")
