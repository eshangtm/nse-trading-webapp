# ══════════════════════════════════════════════════════════════════
#  AOC Data Engine — High-Speed Reader for Advance Option Chain Data
#  Connects directly to 213 Trading Days of authentic AOC CSVs:
#  C:\AllProjects\AOC_Backtester\data\AOC_YYYY-MM-DD.csv
# ══════════════════════════════════════════════════════════════════
import os
import glob
import re
import duckdb
import pandas as pd
from datetime import datetime
from typing import List, Dict, Any, Optional

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_AOC_DIR = r"C:\AllProjects\AOC_Backtester\data" if os.path.exists(r"C:\AllProjects\AOC_Backtester\data") else os.path.join(BASE_DIR, "data", "aoc")

class AOCDataEngine:
    """Provides ultra-fast, authentic Advance Option Chain historical data."""

    def __init__(self, data_dir: str = DEFAULT_AOC_DIR):
        self.data_dir = data_dir
        self._dates_cache: Optional[List[str]] = None
        self._current_day_df: Optional[pd.DataFrame] = None
        self._current_day_date: Optional[str] = None
        self._conn = duckdb.connect()

    def is_available(self) -> bool:
        return os.path.exists(self.data_dir)

    def is_aoc_available_for_date(self, target_date: str) -> bool:
        """Check if an AOC CSV file exists for target_date (YYYY-MM-DD)."""
        if not target_date:
            return False
        clean_date = str(target_date)[:10]
        csv_file = os.path.join(self.data_dir, f"AOC_{clean_date}.csv")
        return os.path.exists(csv_file)

    def get_available_dates(self) -> List[str]:
        """Returns sorted list of all 213 AOC trading dates (YYYY-MM-DD) descending."""
        if not self.is_available():
            return []
        if self._dates_cache is not None:
            return self._dates_cache

        files = glob.glob(os.path.join(self.data_dir, "AOC_*.csv"))
        dates = []
        for f in files:
            m = re.search(r'AOC_(\d{4}-\d{2}-\d{2})\.csv', os.path.basename(f))
            if m:
                dates.append(m.group(1))

        self._dates_cache = sorted(list(set(dates)), reverse=True)
        return self._dates_cache

    def get_available_expiries(self, target_date: str) -> List[str]:
        """Reads the exact Expiry_Date from the AOC CSV file for target_date."""
        clean_date = str(target_date)[:10]
        csv_file = os.path.join(self.data_dir, f"AOC_{clean_date}.csv")
        if not os.path.exists(csv_file):
            return []

        try:
            query = f"SELECT DISTINCT Expiry_Date FROM read_csv_auto('{csv_file.replace(chr(92), '/')}') WHERE Expiry_Date IS NOT NULL;"
            res = self._conn.execute(query).fetchdf()
            if res is not None and not res.empty:
                exp_list = res['Expiry_Date'].dropna().tolist()
                # Format into standard human readable: e.g. '27-Jan-2026' -> '27 Jan 2026'
                formatted = [e.replace('-', ' ') for e in exp_list if e]
                return sorted(list(set(formatted)))
        except Exception as e:
            print(f"Error reading AOC expiries for {clean_date}:", e)

        return []

    def get_timestamps_for_date(self, target_date: str) -> List[str]:
        """Returns all 1-minute unique timestamps formatted as 'YYYY-MM-DDTHH:MM:SS'."""
        clean_date = str(target_date)[:10]
        csv_file = os.path.join(self.data_dir, f"AOC_{clean_date}.csv")
        if not os.path.exists(csv_file):
            return []

        try:
            query = f"""
            SELECT DISTINCT Timestamp 
            FROM read_csv_auto('{csv_file.replace(chr(92), '/')}') 
            ORDER BY Timestamp ASC;
            """
            res = self._conn.execute(query).fetchdf()
            if res is not None and not res.empty:
                ts_list = res['Timestamp'].dropna().tolist()
                return [f"{clean_date}T{t}" for t in ts_list]
        except Exception as e:
            print(f"Error reading AOC timestamps for {clean_date}:", e)

        return []

    def _load_day_df(self, target_date: str) -> Optional[pd.DataFrame]:
        """Loads and caches the entire day CSV into a pandas DataFrame."""
        clean_date = str(target_date)[:10]
        if self._current_day_date == clean_date and self._current_day_df is not None:
            return self._current_day_df

        csv_file = os.path.join(self.data_dir, f"AOC_{clean_date}.csv")
        if not os.path.exists(csv_file):
            return None

        try:
            df = pd.read_csv(csv_file)
            self._current_day_df = df
            self._current_day_date = clean_date
            return df
        except Exception as e:
            print(f"Error loading AOC day CSV {csv_file}:", e)
            return None

    def get_option_chain_snapshot(self, target_timestamp: str) -> Optional[pd.DataFrame]:
        """
        Extracts the exact AOC option chain snapshot at or immediately before target_timestamp.
        Returns a DataFrame formatted with standard tick columns:
        timestamp, symbol, strike, type, spot_price, open, high, low, close, ltp, oi, volume,
        oi_change, oi_change_pct, delta, gamma, theta, vega, iv, rsi, slope, signal, expiry.
        """
        clean_ts = str(target_timestamp).replace('T', ' ')
        target_date = clean_ts[:10]
        time_part = clean_ts[11:] if len(clean_ts) > 11 else "09:15:00"

        df_day = self._load_day_df(target_date)
        if df_day is None or df_day.empty:
            return None

        # Filter rows <= time_part
        matching_times = df_day[df_day['Timestamp'] <= time_part]['Timestamp']
        if matching_times.empty:
            # Fall back to earliest available timestamp
            chosen_time = df_day['Timestamp'].min()
        else:
            chosen_time = matching_times.max()

        snap_df = df_day[df_day['Timestamp'] == chosen_time].copy()
        if snap_df.empty:
            return None

        records = []
        for _, row in snap_df.iterrows():
            strike_val = float(row.get('Strike_Price', 0))
            spot_val = float(row.get('Spot_Price', 0))
            expiry_val = str(row.get('Expiry_Date', '')).replace('-', ' ')
            ts_iso = f"{target_date}T{chosen_time}"

            # CE Record
            ce_vol = float(row.get('CE_Volume', 0) or 0)
            ce_oi = float(row.get('CE_Total_OI', 0) or 0)
            ce_oic = float(row.get('CE_OI_Chg', 0) or 0)
            ce_oic_pct = float(row.get('CE_OI_Chg_Pct', 0) or 0)
            ce_iv = float(row.get('CE_IV', 0) or 0)
            ce_delta = float(row.get('CE_Delta', 0) or 0)
            ce_ltp = float(row.get('CE_LTP', 0) or 0)
            ce_slope = float(row.get('CE_Change', 0) or 0)
            ce_intrinsic = max(0.0, spot_val - strike_val)
            ce_tv = max(0.0, ce_ltp - ce_intrinsic)

            records.append({
                "timestamp": ts_iso,
                "symbol": str(row.get('CE_Contract', f"NIFTY {expiry_val} {int(strike_val)} CE")),
                "strike": strike_val,
                "type": "CE",
                "spot_price": spot_val,
                "open": float(row.get('Spot_Open', spot_val) or spot_val),
                "high": float(row.get('Spot_High', spot_val) or spot_val),
                "low": float(row.get('Spot_Low', spot_val) or spot_val),
                "close": float(row.get('Spot_Close', spot_val) or spot_val),
                "ltp": ce_ltp,
                "oi": ce_oi,
                "volume": ce_vol,
                "oi_change": ce_oic,
                "oi_change_pct": ce_oic_pct,
                "delta": ce_delta,
                "gamma": float(row.get('CE_Gamma', 0) or 0),
                "theta": float(row.get('CE_Theta', 0) or 0),
                "vega": float(row.get('CE_Vega', 0) or 0),
                "iv": ce_iv,
                "rsi": 50.0,
                "slope": ce_slope,
                "intrinsic_value": round(ce_intrinsic, 2),
                "time_value": round(ce_tv, 2),
                "signal": "NEUTRAL",
                "expiry": expiry_val
            })

            # PE Record
            pe_vol = float(row.get('PE_Volume', 0) or 0)
            pe_oi = float(row.get('PE_Total_OI', 0) or 0)
            pe_oic = float(row.get('PE_OI_Chg', 0) or 0)
            pe_oic_pct = float(row.get('PE_OI_Chg_Pct', 0) or 0)
            pe_iv = float(row.get('PE_IV', 0) or 0)
            pe_delta = float(row.get('PE_Delta', 0) or 0)
            pe_ltp = float(row.get('PE_LTP', 0) or 0)
            pe_slope = float(row.get('PE_Change', 0) or 0)
            pe_intrinsic = max(0.0, strike_val - spot_val)
            pe_tv = max(0.0, pe_ltp - pe_intrinsic)

            records.append({
                "timestamp": ts_iso,
                "symbol": str(row.get('PE_Contract', f"NIFTY {expiry_val} {int(strike_val)} PE")),
                "strike": strike_val,
                "type": "PE",
                "spot_price": spot_val,
                "open": float(row.get('Spot_Open', spot_val) or spot_val),
                "high": float(row.get('Spot_High', spot_val) or spot_val),
                "low": float(row.get('Spot_Low', spot_val) or spot_val),
                "close": float(row.get('Spot_Close', spot_val) or spot_val),
                "ltp": pe_ltp,
                "oi": pe_oi,
                "volume": pe_vol,
                "oi_change": pe_oic,
                "oi_change_pct": pe_oic_pct,
                "delta": pe_delta,
                "gamma": float(row.get('PE_Gamma', 0) or 0),
                "theta": float(row.get('PE_Theta', 0) or 0),
                "vega": float(row.get('PE_Vega', 0) or 0),
                "iv": pe_iv,
                "rsi": 50.0,
                "slope": pe_slope,
                "intrinsic_value": round(pe_intrinsic, 2),
                "time_value": round(pe_tv, 2),
                "signal": "NEUTRAL",
                "expiry": expiry_val
            })

        out_df = pd.DataFrame(records)
        return out_df.sort_values(by=["strike", "type"], ascending=[True, False]).reset_index(drop=True)

    def get_candles(self, symbol: str = "SPOT", interval_seconds: int = 60, date: str = None) -> Optional[pd.DataFrame]:
        """Generates OHLCV candles from AOC Spot / Futures price series."""
        if not date:
            return None
        clean_date = str(date)[:10]
        df_day = self._load_day_df(clean_date)
        if df_day is None or df_day.empty:
            return None

        # Distinct timestamps and spots
        spots = df_day[['Timestamp', 'Spot_Price', 'Spot_Open', 'Spot_High', 'Spot_Low', 'Spot_Close']].drop_duplicates('Timestamp').sort_values('Timestamp')
        if spots.empty:
            return None

        candles = []
        for _, row in spots.iterrows():
            ts_str = f"{clean_date} {row['Timestamp']}"
            try:
                try:
                    from zoneinfo import ZoneInfo
                    dt_obj = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=ZoneInfo("Asia/Kolkata"))
                except Exception:
                    dt_obj = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
                epoch_sec = int(dt_obj.timestamp())
            except Exception:
                epoch_sec = 0

            spot_p = float(row.get('Spot_Price', 0) or 0)
            candles.append({
                "candle_time": epoch_sec,
                "open": float(row.get('Spot_Open', spot_p) or spot_p),
                "high": float(row.get('Spot_High', spot_p) or spot_p),
                "low": float(row.get('Spot_Low', spot_p) or spot_p),
                "close": float(row.get('Spot_Close', spot_p) or spot_p),
                "volume": 1000.0
            })

        return pd.DataFrame(candles)

    def load_day_minute_snapshots(self, target_date: str) -> List[Dict[str, Any]]:
        """
        Loads, aggregates, and structures all minute snapshots of an authentic AOC trading day:
          - Groups ticks by minute.
          - Calculates cumulative baseline OI changes from 09:15 AM.
          - Structures ticks ready for Logic 1 to Logic 5 engines.
        """
        clean_date = str(target_date)[:10]
        csv_file = os.path.join(self.data_dir, f"AOC_{clean_date}.csv")
        if not os.path.exists(csv_file):
            return []

        try:
            q = f"""
            WITH ce_recs AS (
                SELECT 
                    '{clean_date}T' || CAST(Timestamp AS VARCHAR) as timestamp,
                    Strike_Price as strike,
                    'CE' as type,
                    Spot_Price as spot_price,
                    CE_LTP as ltp,
                    CE_Total_OI as oi,
                    CE_OI_Chg_Pct as oi_change_pct,
                    CE_Volume as volume,
                    CE_Delta as delta,
                    CE_Gamma as gamma,
                    CE_Theta as theta,
                    CE_Vega as vega,
                    50.0 as rsi,
                    CE_Change as slope,
                    ROUND(GREATEST(0.0, CAST(Spot_Price AS DOUBLE) - CAST(Strike_Price AS DOUBLE)), 2) as intrinsic_value,
                    ROUND(GREATEST(0.0, CAST(CE_LTP AS DOUBLE) - GREATEST(0.0, CAST(Spot_Price AS DOUBLE) - CAST(Strike_Price AS DOUBLE))), 2) as time_value
                FROM read_csv_auto('{csv_file.replace(chr(92), '/')}')
            ),
            pe_recs AS (
                SELECT 
                    '{clean_date}T' || CAST(Timestamp AS VARCHAR) as timestamp,
                    Strike_Price as strike,
                    'PE' as type,
                    Spot_Price as spot_price,
                    PE_LTP as ltp,
                    PE_Total_OI as oi,
                    PE_OI_Chg_Pct as oi_change_pct,
                    PE_Volume as volume,
                    PE_Delta as delta,
                    PE_Gamma as gamma,
                    PE_Theta as theta,
                    PE_Vega as vega,
                    50.0 as rsi,
                    PE_Change as slope,
                    ROUND(GREATEST(0.0, CAST(Strike_Price AS DOUBLE) - CAST(Spot_Price AS DOUBLE)), 2) as intrinsic_value,
                    ROUND(GREATEST(0.0, CAST(PE_LTP AS DOUBLE) - GREATEST(0.0, CAST(Strike_Price AS DOUBLE) - CAST(Spot_Price AS DOUBLE))), 2) as time_value
                FROM read_csv_auto('{csv_file.replace(chr(92), '/')}')
            )
            SELECT * FROM ce_recs
            UNION ALL
            SELECT * FROM pe_recs
            ORDER BY timestamp ASC, strike ASC, type DESC;
            """
            df = self._conn.execute(q).fetchdf()
            if df is None or df.empty:
                return []

            snapshots = []
            for ts, group in df.groupby("timestamp", sort=False):
                records = group.to_dict("records")
                spot_val = float(records[0].get("spot_price") or 24200.0)
                snapshots.append({
                    "timestamp": str(ts),
                    "date": clean_date,
                    "spot_price": round(spot_val, 2),
                    "ticks": records
                })

            # Calculate Cumulative Baseline OI Change % from market open
            if snapshots and len(snapshots) > 1:
                baseline_oi = {}
                for t in snapshots[0].get("ticks", []):
                    stk = float(t.get("strike") or 0.0)
                    typ = str(t.get("type") or "").upper()
                    oi_val = float(t.get("oi") or 0.0)
                    if oi_val > 0:
                        baseline_oi[(stk, typ)] = oi_val

                for snap in snapshots:
                    for t in snap.get("ticks", []):
                        stk = float(t.get("strike") or 0.0)
                        typ = str(t.get("type") or "").upper()
                        cur_oi = float(t.get("oi") or 0.0)
                        base = baseline_oi.get((stk, typ), 0.0)
                        if base > 0:
                            t["baseline_oi_change_pct"] = round(((cur_oi - base) / base) * 100.0, 2)
                        else:
                            t["baseline_oi_change_pct"] = 0.0

            return snapshots
        except Exception as e:
            print(f"Error loading AOC snapshots for {clean_date}:", e)
            return []

    def get_csv_path_for_date(self, target_date: str) -> Optional[str]:
        if not target_date:
            return None
        clean_date = str(target_date)[:10]
        csv_file = os.path.join(self.data_dir, f"AOC_{clean_date}.csv")
        return csv_file if os.path.exists(csv_file) else None

    def get_strike_percentage_history(self, date: str, strike: float, option_type: str = "CE") -> list:
        """
        Fetch intraday minute percentage trajectories (Volume %, OI %, OIChng %)
        for a specific strike and option_type (CE/PE) on date YYYY-MM-DD.
        """
        clean_date = str(date)[:10]
        csv_file = self.get_csv_path_for_date(clean_date)
        if not csv_file or not os.path.exists(csv_file):
            return []

        opt_type = str(option_type).upper()
        col_prefix = "CE" if opt_type == "CE" else "PE"

        try:
            q = f"""
            WITH max_per_ts AS (
                SELECT 
                    Timestamp,
                    MAX({col_prefix}_Total_OI) as max_oi,
                    MAX({col_prefix}_Volume) as max_vol,
                    MAX(abs({col_prefix}_OI_Chg)) as max_oic
                FROM read_csv_auto('{csv_file.replace(chr(92), '/')}')
                GROUP BY Timestamp
            )
            SELECT 
                CAST(t.Timestamp AS VARCHAR) as timestamp,
                CAST(t.Strike_Price AS DOUBLE) as strike,
                '{opt_type}' as type,
                CAST(t.{col_prefix}_Volume AS BIGINT) as volume,
                ROUND(COALESCE(t.{col_prefix}_Volume_Pct, (t.{col_prefix}_Volume / NULLIF(m.max_vol, 0)) * 100.0), 2) as vol_pct,
                CAST(t.{col_prefix}_Total_OI AS BIGINT) as oi,
                ROUND((t.{col_prefix}_Total_OI / NULLIF(m.max_oi, 0)) * 100.0, 2) as oi_pct,
                CAST(t.{col_prefix}_OI_Chg AS BIGINT) as oi_change,
                ROUND(COALESCE(t.{col_prefix}_OI_Chg_Pct, (abs(t.{col_prefix}_OI_Chg) / NULLIF(m.max_oic, 0)) * 100.0), 2) as oic_pct,
                CAST(t.{col_prefix}_LTP AS DOUBLE) as ltp,
                CAST(t.Spot_Price AS DOUBLE) as spot_price
            FROM read_csv_auto('{csv_file.replace(chr(92), '/')}') t
            JOIN max_per_ts m ON t.Timestamp = m.Timestamp
            WHERE t.Strike_Price = {float(strike)}
            ORDER BY t.Timestamp ASC;
            """
            df = self._conn.execute(q).fetchdf()
            if df is None or df.empty:
                return []
            return df.to_dict("records")
        except Exception as e:
            print(f"Error fetching percentage history for {clean_date} strike {strike} {opt_type}:", e)
            return []

# Global Singleton Instance
aoc_data_engine = AOCDataEngine()

