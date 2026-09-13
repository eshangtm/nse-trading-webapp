# ══════════════════════════════════════════════════════════════════
#  AOC Chapter 5: Table of Trade (TOT) Decision Engine
#  Includes SW/2 & RW/2 Midpoint Rules, TOT Matrix, and Entry Levels
# ══════════════════════════════════════════════════════════════════
import math

def calculate_tot_decision(aoc_sr_data, spot_price):
    """
    Calculates Chapter 5 Table of Trade (TOT) decision matrix:
    - S, S+1, S-1, SW, SW/2 (Lower strike rule for support midpoint)
    - R, R+1, R-1, RW, RW/2 (Higher strike rule for resistance midpoint)
    - TOT Decision Matrix (Bull Run, Range Bound, Squeeze, Bearish, Bloodbath)
    - Specific Call (CE) & Put (PE) entry strike & price levels
    """
    if not aoc_sr_data or spot_price <= 0:
        return None

    r1 = aoc_sr_data.get("resistance_primary", 24200.0)
    s1 = aoc_sr_data.get("support_primary", 24150.0)

    res_status = aoc_sr_data.get("resistance_status", {})
    sup_status = aoc_sr_data.get("support_status", {})

    r_type = res_status.get("type", "STRONG")  # STRONG, STT, STB
    s_type = sup_status.get("type", "STRONG")  # STRONG, STT, STB

    r_target = res_status.get("target_strike", r1)
    s_target = sup_status.get("target_strike", s1)

    strike_interval = 50.0  # NIFTY Strike Interval

    # --- Support Terminology ---
    s_exact = float(s1)
    s_plus_1 = s_exact + strike_interval
    s_minus_1 = s_exact - strike_interval
    sw = float(s_target) if s_type in ["STT", "STB"] else s_exact

    # SW/2 (Halfway Level) with Support Midpoint Rule:
    # If midpoint falls between strikes, pick the LOWER strike price!
    raw_sw_mid = (s_exact + sw) / 2.0
    sw_half = math.floor(raw_sw_mid / strike_interval) * strike_interval

    # --- Resistance Terminology ---
    r_exact = float(r1)
    r_plus_1 = r_exact + strike_interval
    r_minus_1 = r_exact - strike_interval
    rw = float(r_target) if r_type in ["STT", "STB"] else r_exact

    # RW/2 (Halfway Level) with Resistance Midpoint Rule:
    # If midpoint falls between strikes, pick the HIGHER strike price!
    raw_rw_mid = (r_exact + rw) / 2.0
    rw_half = math.ceil(raw_rw_mid / strike_interval) * strike_interval

    # --- Table of Trade (TOT) Decision Chart Matrix ---
    sentiment = "RANGE_BOUND"
    ce_action = "WAIT_FOR_SUPPORT"
    pe_action = "WAIT_FOR_RESISTANCE"
    recommended_signal = "NEUTRAL_EXIT"
    tot_rule_id = 2
    reason_desc = ""

    if s_type == "STT" and r_type == "STT":
        sentiment = "BULL_RUN"
        ce_action = f"BUY CE at Every Bottom (From S: {int(s_exact)} / S-1: {int(s_minus_1)})"
        pe_action = "AVOID PE (Do NOT buy Put trades)"
        recommended_signal = "BUY_CE"
        tot_rule_id = 1
        reason_desc = "Both Support & Resistance are STT (Shifting Towards Top) -> Super Bullish Trend!"

    elif s_type == "STRONG" and r_type == "STRONG":
        sentiment = "RANGE_BOUND"
        ce_action = f"BUY CE near Support S ({int(s_exact)})"
        pe_action = f"BUY PE near Resistance R ({int(r_exact)})"
        if spot_price <= (s_exact + 15.0):
            recommended_signal = "BUY_CE"
        elif spot_price >= (r_exact - 15.0):
            recommended_signal = "BUY_PE"
        else:
            recommended_signal = "NEUTRAL_EXIT"
        tot_rule_id = 2
        reason_desc = "Both Support & Resistance are STRONG -> Range Bound Market between S & R."

    elif s_type == "STT" and r_type == "STB":
        sentiment = "SQUEEZE_CONSOLIDATION"
        ce_action = "NO TRADE (Squeeze Mode)"
        pe_action = "NO TRADE (Squeeze Mode)"
        recommended_signal = "NEUTRAL_EXIT"
        tot_rule_id = 3
        reason_desc = "Support STT + Resistance STB -> Range Squeeze / Market Compression (No Trade Zone)."

    elif s_type == "STRONG" and r_type == "STB":
        sentiment = "BEARISH"
        ce_action = f"BUY CE from S-1 ({int(s_minus_1)}) [Risky Bounce Only]"
        pe_action = f"BUY PE from R ({int(r_exact)}) to RW/2 ({int(rw_half)})"
        recommended_signal = "BUY_PE"
        tot_rule_id = 4
        reason_desc = "Support Strong + Resistance STB -> Mandi / Bearish Pressure."

    elif s_type == "STB" and r_type == "STB":
        sentiment = "BLOODBATH"
        ce_action = "AVOID CE (Do NOT buy Call trades)"
        pe_action = f"BUY PE at Every Top (From R: {int(r_exact)} / R+1: {int(r_plus_1)})"
        recommended_signal = "BUY_PE"
        tot_rule_id = 5
        reason_desc = "Both Support & Resistance are STB (Shifting Towards Bottom) -> Bloodbath Bearish Trend!"

    elif s_type == "STB" and r_type == "STRONG":
        sentiment = "BEARISH_BREAKOUT"
        ce_action = "AVOID CE"
        pe_action = f"BUY PE from R ({int(r_exact)}) or RW/2 ({int(rw_half)})"
        recommended_signal = "BUY_PE"
        tot_rule_id = 6
        reason_desc = "Support STB + Resistance Strong -> Bearish Breakdown Pressure."

    return {
        "spot_price": spot_price,
        "sentiment": sentiment,
        "tot_rule_id": tot_rule_id,
        "reason_description": reason_desc,
        "recommended_signal": recommended_signal,
        "support_levels": {
            "S": s_exact,
            "S_plus_1": s_plus_1,
            "S_minus_1": s_minus_1,
            "SW": sw,
            "SW_half": sw_half,
            "status": s_type
        },
        "resistance_levels": {
            "R": r_exact,
            "R_plus_1": r_plus_1,
            "R_minus_1": r_minus_1,
            "RW": rw,
            "RW_half": rw_half,
            "status": r_type
        },
        "trade_execution_plan": {
            "call_ce_action": ce_action,
            "put_pe_action": pe_action,
            "ce_entry_target": s_exact,
            "pe_entry_target": r_exact,
            "sl_points": 15.0,
            "target_points": 35.0
        }
    }
