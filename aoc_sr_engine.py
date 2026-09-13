# ══════════════════════════════════════════════════════════════════
#  AOC (Advance Option Chain) Support & Resistance Engine
#  Custom 1 ITM to OTM S/R Logic (OI, OI Change, Volume: 100% & >=75%)
# ══════════════════════════════════════════════════════════════════
import math
from greeks_calculator import calculate_greeks_and_reversal

def evaluate_aoc_level_status(main_strike, candidates_data, option_type, is_trend_increasing=True):
    """
    Evaluates whether Support/Resistance is:
      - STRONG (No weakness or all 3 metrics aligned or percentage decreasing)
      - STT / WTT (Shifting Towards Top -> Shifting to a HIGHER strike -> BULLISH Pressure)
      - STB / WTB (Shifting Towards Bottom -> Shifting to a LOWER strike -> BEARISH Pressure)
    """
    if not main_strike or not candidates_data:
        return {
            "status": "STRONG",
            "type": "STRONG",
            "target_strike": main_strike,
            "pct": 100.0,
            "description": "Strong Level (No Weakness)",
            "pressure": "NEUTRAL",
            "shift_text": f"{'R' if option_type == 'CE' else 'S'}: {int(main_strike or 0)} (STRONG)"
        }

    # Find candidate strikes with >= 75% relative percentage (excluding main_strike)
    yellow_boxes = [c for c in candidates_data if c["strike"] != main_strike and c["pct"] >= 75.0]
    
    if not yellow_boxes:
        return {
            "status": "STRONG",
            "type": "STRONG",
            "target_strike": main_strike,
            "pct": 100.0,
            "description": f"{'Resistance' if option_type == 'CE' else 'Support'} is STRONG at {int(main_strike)}",
            "pressure": "NEUTRAL",
            "shift_text": f"{'R' if option_type == 'CE' else 'S'}: {int(main_strike)} (STRONG)"
        }

    # Pick the strongest candidate (highest percentage >= 75%)
    best_candidate = max(yellow_boxes, key=lambda x: x["pct"])
    target_strike = best_candidate["strike"]
    target_pct = round(best_candidate["pct"], 1)

    if target_strike == main_strike:
        return {
            "status": "STRONG",
            "type": "STRONG",
            "target_strike": main_strike,
            "pct": 100.0,
            "description": f"{'Resistance' if option_type == 'CE' else 'Support'} is STRONG at {int(main_strike)}",
            "pressure": "NEUTRAL",
            "shift_text": f"{'R' if option_type == 'CE' else 'S'}: {int(main_strike)} (STRONG)"
        }

    if not is_trend_increasing:
        return {
            "status": "STRONG",
            "type": "STRONG",
            "target_strike": main_strike,
            "pct": target_pct,
            "description": f"Yellow Box at {int(target_strike)} ({target_pct}%) is Decreasing -> Level remains STRONG at {int(main_strike)}",
            "pressure": "NEUTRAL",
            "shift_text": f"{'R' if option_type == 'CE' else 'S'}: {int(main_strike)} (STRONG - Fading)"
        }

    if target_strike > main_strike:
        # Higher Strike -> STT (Shifting Towards Top) -> BULLISH Pressure!
        return {
            "status": f"WTT ({target_pct}%)",
            "type": "STT",
            "target_strike": target_strike,
            "pct": target_pct,
            "description": f"{'Resistance' if option_type == 'CE' else 'Support'} WTT at {int(target_strike)} ({target_pct}%) [STT - Bullish Pressure]",
            "pressure": "BULLISH",
            "shift_text": f"SFT {int(main_strike)} -> {int(target_strike)} ({target_pct}%)"
        }
    else:
        # Lower Strike -> STB (Shifting Towards Bottom) -> BEARISH Pressure!
        return {
            "status": f"WTB ({target_pct}%)",
            "type": "STB",
            "target_strike": target_strike,
            "pct": target_pct,
            "description": f"{'Resistance' if option_type == 'CE' else 'Support'} WTB at {int(target_strike)} ({target_pct}%) [STB - Bearish Pressure]",
            "pressure": "BEARISH",
            "shift_text": f"SFB {int(main_strike)} -> {int(target_strike)} ({target_pct}%)"
        }

# In-memory store for 9:30 AM Benchmark Baseline levels
_930_BENCHMARK_CACHE = {
    "date": None,
    "avg_resistance": None,
    "avg_res_rev": None,
    "avg_support": None,
    "avg_sup_rev": None,
    "locked": False
}

def calculate_aoc_sr(ticks, spot_price, current_timestamp=None):
    """
    Calculates Support & Resistance according to User's Strict Rules:
    
    1. Scope:
       - CALL side (Resistance): From 1 ITM (highest strike <= spot) towards OTM (strikes >= 1 ITM).
       - PUT side (Support): From 1 ITM (lowest strike >= spot) towards OTM (strikes <= 1 ITM).
       
    2. Metrics (OI, OI Change, Volume):
       - Highest in each metric = 100% (RED on Call, GREEN on Put).
       - Other strikes = (value / max_value) * 100.
       - Any strike >= 75% is YELLOW.
       
    3. S/R Identification:
       - Resistance (Call side): Look from 1 ITM towards OTM.
         The candidate strike closest to Spot having 100% RED or >=75% YELLOW is chosen.
         If OI, OI Chg, and Volume are all 100% RED on the same strike -> STRONG RESISTANCE (Triple Red).
       - Support (Put side): Look from 1 ITM towards OTM.
         The candidate strike closest to Spot having 100% GREEN or >=75% YELLOW is chosen.
         If OI, OI Chg, and Volume are all 100% GREEN on the same strike -> STRONG SUPPORT (Triple Green).
         
    4. Exact Greeks-Adjusted Reversals & TradingView Chart Price Lines.
    """
    if not ticks or spot_price <= 0:
        return None

    strikes_map = {}
    ts_str = str(current_timestamp or ticks[0].get("timestamp") or "")
    cur_date = ts_str[:10] if ts_str else None
    cur_time = ts_str.split("T")[1] if "T" in ts_str else (ts_str.split(" ")[1] if " " in ts_str else "")

    for t in ticks:
        st = float(t.get("strike", 0))
        opt_type = str(t.get("type", "CE")).upper()
        if st not in strikes_map:
            strikes_map[st] = {"CE": {}, "PE": {}}
        strikes_map[st][opt_type] = t

    sorted_strikes = sorted(list(strikes_map.keys()))
    if not sorted_strikes:
        return None

    # Determine 1 ITM strikes for Call and Put
    # Call 1 ITM: Highest strike <= spot_price
    strikes_le_spot = [st for st in sorted_strikes if st <= spot_price]
    call_1_itm = strikes_le_spot[-1] if strikes_le_spot else sorted_strikes[0]

    # Put 1 ITM: Lowest strike >= spot_price
    strikes_ge_spot = [st for st in sorted_strikes if st >= spot_price]
    put_1_itm = strikes_ge_spot[0] if strikes_ge_spot else sorted_strikes[-1]

    # 1. CALL SIDE (From 1 ITM to OTM: 10 strikes)
    call_1_itm_idx = sorted_strikes.index(call_1_itm)
    ce_strikes = sorted_strikes[call_1_itm_idx:call_1_itm_idx + 10]
    if not ce_strikes:
        ce_strikes = sorted_strikes

    max_ce_oi = 0.0
    max_ce_oic = 0.0
    max_ce_vol = 0.0
    max_ce_oi_st = None
    max_ce_oic_st = None
    max_ce_vol_st = None

    for st in ce_strikes:
        ce_t = strikes_map[st].get("CE", {})
        oi = float(ce_t.get("oi") or 0)
        vol = float(ce_t.get("volume") or 0)
        oic = float(ce_t.get("oi_change") or 0)
        if oic == 0 and oi > 0:
            oic = abs(oi * float(ce_t.get("oi_change_pct") or 0) / 100.0)
        else:
            oic = abs(oic)

        if oi > max_ce_oi:
            max_ce_oi = oi
            max_ce_oi_st = st
        if vol > max_ce_vol:
            max_ce_vol = vol
            max_ce_vol_st = st
        if oic > max_ce_oic:
            max_ce_oic = oic
            max_ce_oic_st = st

    # 2. PUT SIDE (From 1 ITM to OTM: 10 strikes)
    put_1_itm_idx = sorted_strikes.index(put_1_itm)
    pe_start_idx = max(0, put_1_itm_idx - 9)
    pe_strikes = sorted_strikes[pe_start_idx:put_1_itm_idx + 1]
    if not pe_strikes:
        pe_strikes = sorted_strikes

    max_pe_oi = 0.0
    max_pe_oic = 0.0
    max_pe_vol = 0.0
    max_pe_oi_st = None
    max_pe_oic_st = None
    max_pe_vol_st = None

    for st in pe_strikes:
        pe_t = strikes_map[st].get("PE", {})
        oi = float(pe_t.get("oi") or 0)
        vol = float(pe_t.get("volume") or 0)
        oic = float(pe_t.get("oi_change") or 0)
        if oic == 0 and oi > 0:
            oic = abs(oi * float(pe_t.get("oi_change_pct") or 0) / 100.0)
        else:
            oic = abs(oic)

        if oi > max_pe_oi:
            max_pe_oi = oi
            max_pe_oi_st = st
        if vol > max_pe_vol:
            max_pe_vol = vol
            max_pe_vol_st = st
        if oic > max_pe_oic:
            max_pe_oic = oic
            max_pe_oic_st = st

    # Calculate percentages for Call candidate strikes
    ce_candidates = []
    for st in ce_strikes:
        ce_t = strikes_map[st].get("CE", {})
        oi = float(ce_t.get("oi") or 0)
        vol = float(ce_t.get("volume") or 0)
        oic = float(ce_t.get("oi_change") or 0)
        if oic == 0 and oi > 0:
            oic = abs(oi * float(ce_t.get("oi_change_pct") or 0) / 100.0)
        else:
            oic = abs(oic)

        oi_pct = (oi / max_ce_oi * 100.0) if max_ce_oi > 0 else 0.0
        oic_pct = (oic / max_ce_oic * 100.0) if max_ce_oic > 0 else 0.0
        vol_pct = (vol / max_ce_vol * 100.0) if max_ce_vol > 0 else 0.0
        max_pct = max(oi_pct, oic_pct, vol_pct)

        # Record metrics that qualify as 100% (RED) or >=75% (YELLOW)
        tags = []
        if oi_pct >= 99.9: tags.append("OI 100% (RED)")
        elif oi_pct >= 75.0: tags.append(f"OI {oi_pct:.0f}% (YEL)")

        if oic_pct >= 99.9: tags.append("OIC 100% (RED)")
        elif oic_pct >= 75.0: tags.append(f"OIC {oic_pct:.0f}% (YEL)")

        if vol_pct >= 99.9: tags.append("VOL 100% (RED)")
        elif vol_pct >= 75.0: tags.append(f"VOL {vol_pct:.0f}% (YEL)")

        ce_candidates.append({
            "strike": st,
            "pct": max_pct,
            "oi_pct": oi_pct,
            "oic_pct": oic_pct,
            "vol_pct": vol_pct,
            "is_triple_red": (oi_pct >= 99.9 and oic_pct >= 99.9 and vol_pct >= 99.9),
            "is_any_red": (oi_pct >= 99.9 or oic_pct >= 99.9 or vol_pct >= 99.9),
            "is_yellow": (max_pct >= 75.0),
            "tags": tags,
            "dist_from_spot": abs(st - spot_price)
        })

    # Calculate percentages for Put candidate strikes
    pe_candidates = []
    for st in pe_strikes:
        pe_t = strikes_map[st].get("PE", {})
        oi = float(pe_t.get("oi") or 0)
        vol = float(pe_t.get("volume") or 0)
        oic = float(pe_t.get("oi_change") or 0)
        if oic == 0 and oi > 0:
            oic = abs(oi * float(pe_t.get("oi_change_pct") or 0) / 100.0)
        else:
            oic = abs(oic)

        oi_pct = (oi / max_pe_oi * 100.0) if max_pe_oi > 0 else 0.0
        oic_pct = (oic / max_pe_oic * 100.0) if max_pe_oic > 0 else 0.0
        vol_pct = (vol / max_pe_vol * 100.0) if max_pe_vol > 0 else 0.0
        max_pct = max(oi_pct, oic_pct, vol_pct)

        # Record metrics that qualify as 100% (GREEN) or >=75% (YELLOW)
        tags = []
        if oi_pct >= 99.9: tags.append("OI 100% (GRN)")
        elif oi_pct >= 75.0: tags.append(f"OI {oi_pct:.0f}% (YEL)")

        if oic_pct >= 99.9: tags.append("OIC 100% (GRN)")
        elif oic_pct >= 75.0: tags.append(f"OIC {oic_pct:.0f}% (YEL)")

        if vol_pct >= 99.9: tags.append("VOL 100% (GRN)")
        elif vol_pct >= 75.0: tags.append(f"VOL {vol_pct:.0f}% (YEL)")

        pe_candidates.append({
            "strike": st,
            "pct": max_pct,
            "oi_pct": oi_pct,
            "oic_pct": oic_pct,
            "vol_pct": vol_pct,
            "is_triple_green": (oi_pct >= 99.9 and oic_pct >= 99.9 and vol_pct >= 99.9),
            "is_any_green": (oi_pct >= 99.9 or oic_pct >= 99.9 or vol_pct >= 99.9),
            "is_yellow": (max_pct >= 75.0),
            "tags": tags,
            "dist_from_spot": abs(st - spot_price)
        })

    # --- RESISTANCE RESOLUTION (Call Side) ---
    # User Rule: Collect all strikes having 100% RED in OI, Volume, or OI Change (from 1 ITM to OTM).
    # Out of these 100% RED strikes, the strike closest to Spot is the Resistance (R1).
    # It can be formed by 1 red, 2 reds, or all 3 reds.
    ce_100_strikes = set()
    if max_ce_oi_st is not None: ce_100_strikes.add(max_ce_oi_st)
    if max_ce_vol_st is not None: ce_100_strikes.add(max_ce_vol_st)
    if max_ce_oic_st is not None: ce_100_strikes.add(max_ce_oic_st)
    if not ce_100_strikes:
        ce_100_strikes.add(call_1_itm)

    r1_strike = min(ce_100_strikes, key=lambda st: abs(st - spot_price))

    r1_tags = []
    if r1_strike == max_ce_oi_st: r1_tags.append("OI 100% RED")
    if r1_strike == max_ce_vol_st: r1_tags.append("VOL 100% RED")
    if r1_strike == max_ce_oic_st: r1_tags.append("OIC 100% RED")

    if len(r1_tags) == 3:
        r1_strength = "STRONG (Triple Red: OI+VOL+OIC 100%)"
    elif len(r1_tags) == 2:
        r1_strength = f"STRONG ({'+'.join(r1_tags)})"
    else:
        r1_strength = f"ACTIVE ({r1_tags[0] if r1_tags else '100% RED'})"

    # --- SUPPORT RESOLUTION (Put Side) ---
    # User Rule: Collect all strikes having 100% GREEN in OI, Volume, or OI Change (from 1 ITM to OTM).
    # Out of these 100% GREEN strikes, the strike closest to Spot is the Support (S1).
    # It can be formed by 1 green, 2 greens, or all 3 greens.
    pe_100_strikes = set()
    if max_pe_oi_st is not None: pe_100_strikes.add(max_pe_oi_st)
    if max_pe_vol_st is not None: pe_100_strikes.add(max_pe_vol_st)
    if max_pe_oic_st is not None: pe_100_strikes.add(max_pe_oic_st)
    if not pe_100_strikes:
        pe_100_strikes.add(put_1_itm)

    s1_strike = min(pe_100_strikes, key=lambda st: abs(st - spot_price))

    s1_tags = []
    if s1_strike == max_pe_oi_st: s1_tags.append("OI 100% GRN")
    if s1_strike == max_pe_vol_st: s1_tags.append("VOL 100% GRN")
    if s1_strike == max_pe_oic_st: s1_tags.append("OIC 100% GRN")

    if len(s1_tags) == 3:
        s1_strength = "STRONG (Triple Green: OI+VOL+OIC 100%)"
    elif len(s1_tags) == 2:
        s1_strength = f"STRONG ({'+'.join(s1_tags)})"
    else:
        s1_strength = f"ACTIVE ({s1_tags[0] if s1_tags else '100% GREEN'})"

    # Evaluate 5-Step AOC Classification (STRONG vs STT vs STB)
    res_status = evaluate_aoc_level_status(r1_strike, ce_candidates, "CE", is_trend_increasing=True)
    sup_status = evaluate_aoc_level_status(s1_strike, pe_candidates, "PE", is_trend_increasing=True)

    # Exact Greeks-Adjusted Reversal Formulas
    r1_ce_data = strikes_map.get(r1_strike, {}).get("CE", {})
    s1_pe_data = strikes_map.get(s1_strike, {}).get("PE", {})

    r1_ce_iv = float(r1_ce_data.get("iv") or 0.12)
    s1_pe_iv = float(s1_pe_data.get("iv") or 0.12)

    r_rev_info = calculate_greeks_and_reversal(spot_price, r1_strike, ce_ltp=r1_ce_data.get("ltp"), tte=2/365, iv=r1_ce_iv)
    s_rev_info = calculate_greeks_and_reversal(spot_price, s1_strike, pe_ltp=s1_pe_data.get("ltp"), tte=2/365, iv=s1_pe_iv)

    ce_ltp_r1 = float(r1_ce_data.get("ltp") or 0.0)
    pe_ltp_s1 = float(s1_pe_data.get("ltp") or 0.0)
    if ce_ltp_r1 <= 0:
        ce_ltp_r1 = float(r_rev_info.get("ce_val") or 25.0)
    if pe_ltp_s1 <= 0:
        pe_ltp_s1 = float(s_rev_info.get("pe_val") or 25.0)

    r1 = r1_strike
    r2 = round(r1_strike + ce_ltp_r1, 1)  # Exact Reversal Level (Strike + CE Value)
    r3 = r1_strike + 50.0

    s1 = s1_strike
    s2 = round(s1_strike - pe_ltp_s1, 1)  # Exact Reversal Level (Strike - PE Value)
    s3 = s1_strike - 50.0

    # 9:30 AM Benchmark Baseline Lock & Update
    global _930_BENCHMARK_CACHE
    if _930_BENCHMARK_CACHE["date"] != cur_date:
        _930_BENCHMARK_CACHE["date"] = cur_date
        _930_BENCHMARK_CACHE["avg_resistance"] = r1
        _930_BENCHMARK_CACHE["avg_res_rev"] = r2
        _930_BENCHMARK_CACHE["avg_support"] = s1
        _930_BENCHMARK_CACHE["avg_sup_rev"] = s2
        _930_BENCHMARK_CACHE["locked"] = False

    if not _930_BENCHMARK_CACHE["locked"] and cur_time >= "09:30:00":
        _930_BENCHMARK_CACHE["avg_resistance"] = r1
        _930_BENCHMARK_CACHE["avg_res_rev"] = r2
        _930_BENCHMARK_CACHE["avg_support"] = s1
        _930_BENCHMARK_CACHE["avg_sup_rev"] = s2
        _930_BENCHMARK_CACHE["locked"] = True

    avg_r = _930_BENCHMARK_CACHE.get("avg_resistance") or r1
    avg_r_rev = _930_BENCHMARK_CACHE.get("avg_res_rev") or r2
    avg_s = _930_BENCHMARK_CACHE.get("avg_support") or s1
    avg_s_rev = _930_BENCHMARK_CACHE.get("avg_sup_rev") or s2

    # Clean non-colliding TradingView chart lines (Concise S/R Titles + SPOT & ATM Lines)
    atm_strike = round(spot_price / 50.0) * 50.0
    chart_lines = [
        # Resistance Lines
        {"price": r3, "color": "#f87171", "title": f"R3 {int(r3)}", "lineStyle": 2, "lineWidth": 1},
        {"price": r2, "color": "#ef4444", "title": f"R Rev {r2}", "lineStyle": 1, "lineWidth": 2},
        {"price": r1, "color": "#dc2626", "title": f"R {int(r1)}", "lineStyle": 0, "lineWidth": 2},

        # SPOT & ATM Price Lines
        {"price": round(spot_price, 2), "color": "#00f0ff", "title": f"⚡ SPOT {round(spot_price, 2)}", "lineStyle": 0, "lineWidth": 2},
        {"price": atm_strike, "color": "#f59e0b", "title": f"🎯 ATM {int(atm_strike)}", "lineStyle": 2, "lineWidth": 2},

        # Support Lines
        {"price": s1, "color": "#16a34a", "title": f"S {int(s1)}", "lineStyle": 0, "lineWidth": 2},
        {"price": s2, "color": "#22c55e", "title": f"S Rev {s2}", "lineStyle": 1, "lineWidth": 2},
        {"price": s3, "color": "#4ade80", "title": f"S3 {int(s3)}", "lineStyle": 2, "lineWidth": 1},
    ]

    return {
        "spot_price": spot_price,
        "call_1_itm": call_1_itm,
        "put_1_itm": put_1_itm,
        "resistance": r1,
        "resistance_primary": r1,
        "resistance_strength": r1_strength,
        "resistance_reversal": r2,
        "resistance_upper": r3,
        "resistance_status": res_status,
        "support": s1,
        "support_primary": s1,
        "support_strength": s1_strength,
        "support_reversal": s2,
        "support_lower": s3,
        "support_status": sup_status,
        "max_ce_oi_strike": max_ce_oi_st,
        "max_ce_oic_strike": max_ce_oic_st,
        "max_ce_vol_strike": max_ce_vol_st,
        "max_pe_oi_strike": max_pe_oi_st,
        "max_pe_oic_strike": max_pe_oic_st,
        "max_pe_vol_strike": max_pe_vol_st,
        "avg_resistance": avg_r,
        "avg_res_rev": avg_r_rev,
        "avg_support": avg_s,
        "avg_sup_rev": avg_s_rev,
        "ce_delta": r_rev_info.get("ce_delta", 0.0),
        "pe_delta": s_rev_info.get("pe_delta", 0.0),
        "shifting_ce": f"R: {int(r1)} ({r1_strength})",
        "shifting_pe": f"S: {int(s1)} ({s1_strength})",
        "overall_market_bias": "BULLISH" if (res_status["pressure"] == "BULLISH" or sup_status["pressure"] == "BULLISH") else ("BEARISH" if (res_status["pressure"] == "BEARISH" or sup_status["pressure"] == "BEARISH") else "NEUTRAL"),
        "chart_lines": chart_lines
    }

