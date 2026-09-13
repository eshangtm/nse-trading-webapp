# ══════════════════════════════════════════════════════════════════════════════
#  AOC Support & Resistance Breakdown & Benchmark Engine
# ══════════════════════════════════════════════════════════════════════════════
import math
from typing import Dict, Any, List, Optional
from greeks_calculator import calculate_greeks_and_reversal

class AOCStaircaseSREngine:
    """
    Computes exact AOC Support & Resistance values for every strike:
      - Average S/R Values (9:30 AM Benchmark)
      - Current S/R Values (Real-time Live Feed / Break-Even Reversals)
    """

    def __init__(self):
        self._930_cache: Dict[str, Dict[float, Dict[str, float]]] = {}

    def _get_930_benchmark(self, cur_date: str) -> Dict[float, Dict[str, float]]:
        """Loads and caches the 09:30 AM benchmark for a given date."""
        if not cur_date or cur_date == "default":
            return {}
        if cur_date in self._930_cache:
            return self._930_cache[cur_date]
        
        bench_map = {}
        try:
            from duckdb_engine import duckdb_engine
            # Try fetching the 09:30 AM snapshot
            df_930 = duckdb_engine.get_option_chain_at_timestamp(f"{cur_date} 09:30:00")
            if df_930 is not None and not df_930.empty:
                ticks_930 = df_930.to_dict("records")
                spot_930 = float(ticks_930[0].get("spot_price") or 0.0)
                
                # Group 9:30 ticks
                stk_930 = {}
                for t in ticks_930:
                    stk = float(t.get("strike") or 0.0)
                    typ = str(t.get("type") or "CE").upper()
                    if stk not in stk_930:
                        stk_930[stk] = {"CE": {}, "PE": {}}
                    stk_930[stk][typ] = t
                
                raw_930 = {}
                for stk, data in stk_930.items():
                    ce_t = data.get("CE", {})
                    pe_t = data.get("PE", {})
                    ce_ltp = float(ce_t.get("ltp") or 0.0)
                    pe_ltp = float(pe_t.get("ltp") or 0.0)
                    ce_iv = float(ce_t.get("iv") or 12.0)
                    pe_iv = float(pe_t.get("iv") or 14.0)

                    r_info = calculate_greeks_and_reversal(spot_930, stk, ce_ltp=ce_ltp, tte=2/365, iv=ce_iv)
                    s_info = calculate_greeks_and_reversal(spot_930, stk, pe_ltp=pe_ltp, tte=2/365, iv=pe_iv)

                    raw_930[stk] = {
                        "res": round(r_info["resistance"], 4),
                        "sup": round(s_info["support"], 4),
                        "ce_iv": round(ce_iv if ce_iv > 1.0 else ce_iv * 100.0, 2),
                        "pe_iv": round(pe_iv if pe_iv > 1.0 else pe_iv * 100.0, 2)
                    }

                # Apply AOC Staircase Linking Law to 9:30 benchmark: Support(K) = Resistance(K - 50)
                for stk in raw_930:
                    prev_stk = stk - 50.0
                    avg_res = raw_930[stk]["res"]
                    avg_sup = raw_930[prev_stk]["res"] if prev_stk in raw_930 else raw_930[stk]["sup"]
                    bench_map[stk] = {
                        "avg_resistance": round(avg_res, 4),
                        "avg_support": round(avg_sup, 4),
                        "weighted_call_iv": raw_930[stk]["ce_iv"],
                        "weighted_put_iv": raw_930[stk]["pe_iv"]
                    }
                self._930_cache[cur_date] = bench_map
        except Exception as e:
            print("Error loading 9:30 benchmark:", e)
            
        return bench_map

    def compute_strike_levels(
        self,
        ticks: List[Dict[str, Any]],
        spot_price: float,
        timestamp: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Computes the complete dictionary of S/R levels for every strike in the option chain
        enforcing the AOC Staircase Law: Support(K) = Resistance(K - 50).
        """
        if not ticks or spot_price <= 0:
            return {}

        ts_str = str(timestamp or ticks[0].get("timestamp") or "")
        cur_date = ts_str[:10] if ts_str and len(ts_str) >= 10 else "default"
        cur_time = ts_str.split("T")[1] if "T" in ts_str else (ts_str.split(" ")[1] if " " in ts_str else "")

        # Group ticks by strike
        strikes_map: Dict[float, Dict[str, Any]] = {}
        for t in ticks:
            stk = float(t.get("strike") or 0.0)
            if stk <= 0:
                continue
            typ = str(t.get("type") or "CE").upper()
            if stk not in strikes_map:
                strikes_map[stk] = {"CE": {}, "PE": {}}
            strikes_map[stk][typ] = t

        sorted_strikes = sorted(list(strikes_map.keys()))
        if not sorted_strikes:
            return {}

        bench_930 = self._get_930_benchmark(cur_date)

        # Step 1: Calculate raw canonical reversal levels for all strikes
        raw_map: Dict[float, Dict[str, Any]] = {}
        for stk in sorted_strikes:
            ce_tick = strikes_map[stk].get("CE", {})
            pe_tick = strikes_map[stk].get("PE", {})

            ce_ltp = float(ce_tick.get("ltp") or 0.0)
            pe_ltp = float(pe_tick.get("ltp") or 0.0)
            ce_iv = float(ce_tick.get("iv") or 12.0)
            pe_iv = float(pe_tick.get("iv") or 14.0)

            r_info = calculate_greeks_and_reversal(spot_price, stk, ce_ltp=ce_ltp, tte=2/365, iv=ce_iv)
            s_info = calculate_greeks_and_reversal(spot_price, stk, pe_ltp=pe_ltp, tte=2/365, iv=pe_iv)

            raw_map[stk] = {
                "res": round(r_info["resistance"], 4),
                "sup": round(s_info["support"], 4),
                "ce_iv": round(ce_iv if ce_iv > 1.0 else ce_iv * 100.0, 2),
                "pe_iv": round(pe_iv if pe_iv > 1.0 else pe_iv * 100.0, 2)
            }

        # Step 2: Apply the AOC Staircase Law: Support(K) = Resistance(K - 50)
        results: Dict[str, Dict[str, Any]] = {}
        for stk in sorted_strikes:
            prev_stk = stk - 50.0
            cur_res = raw_map[stk]["res"]
            cur_sup = raw_map[prev_stk]["res"] if prev_stk in raw_map else raw_map[stk]["sup"]
            c_iv_clean = raw_map[stk]["ce_iv"]
            p_iv_clean = raw_map[stk]["pe_iv"]

            # 9:30 AM Benchmark
            b_data = bench_930.get(stk, {})
            avg_res = b_data.get("avg_resistance")
            avg_sup = b_data.get("avg_support")
            w_c_iv = b_data.get("weighted_call_iv", c_iv_clean)
            w_p_iv = b_data.get("weighted_put_iv", p_iv_clean)

            if avg_res is None or avg_sup is None:
                # If before 09:30 AM or live stream, record/lock when reaching 09:30
                if cur_time >= "09:30:00" and cur_date not in self._930_cache:
                    if cur_date not in self._930_cache:
                        self._930_cache[cur_date] = {}
                    self._930_cache[cur_date][stk] = {
                        "avg_resistance": cur_res,
                        "avg_support": cur_sup,
                        "weighted_call_iv": c_iv_clean,
                        "weighted_put_iv": p_iv_clean
                    }
                avg_res = cur_res
                avg_sup = cur_sup

            results[str(int(stk))] = {
                "strike": int(stk),
                "avg_resistance": round(avg_res, 4),
                "avg_support": round(avg_sup, 4),
                "current_resistance": round(cur_res, 4),
                "current_support": round(cur_sup, 4),
                "weighted_call_iv": w_c_iv,
                "weighted_put_iv": w_p_iv,
                "current_call_iv": c_iv_clean,
                "current_put_iv": p_iv_clean
            }

        return results

# Singleton Instance
aoc_staircase_engine = AOCStaircaseSREngine()
