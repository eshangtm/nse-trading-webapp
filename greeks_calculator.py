# ══════════════════════════════════════════════════════════════════
#  Real-Time Greeks, Technicals & Signal Engine for NIFTY50 Options
# ══════════════════════════════════════════════════════════════════
import math
import numpy as np
from scipy.stats import norm

RISK_FREE_RATE = 0.07  # 7% standard Indian risk-free rate

def black_scholes_greeks(spot, strike, t_years, sigma, option_type="CE", r=RISK_FREE_RATE):
    """Calculate Black-Scholes Price, Delta, Gamma, Theta, Vega."""
    if spot <= 0 or strike <= 0 or t_years <= 0 or sigma <= 0:
        return {"price": 0.0, "delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0}

    d1 = (math.log(spot / strike) + (r + 0.5 * sigma ** 2) * t_years) / (sigma * math.sqrt(t_years))
    d2 = d1 - sigma * math.sqrt(t_years)

    if option_type == "CE":
        price = spot * norm.cdf(d1) - strike * math.exp(-r * t_years) * norm.cdf(d2)
        delta = norm.cdf(d1)
        theta = (- (spot * norm.pdf(d1) * sigma) / (2 * math.sqrt(t_years))
                 - r * strike * math.exp(-r * t_years) * norm.cdf(d2)) / 365.0
    else:  # PE
        price = strike * math.exp(-r * t_years) * norm.cdf(-d2) - spot * norm.cdf(-d1)
        delta = norm.cdf(d1) - 1.0
        theta = (- (spot * norm.pdf(d1) * sigma) / (2 * math.sqrt(t_years))
                 + r * strike * math.exp(-r * t_years) * norm.cdf(-d2)) / 365.0

    gamma = norm.pdf(d1) / (spot * sigma * math.sqrt(t_years))
    vega = (spot * norm.pdf(d1) * math.sqrt(t_years)) / 100.0  # Per 1% change in IV

    return {
        "price": round(price, 2),
        "delta": round(delta, 4),
        "gamma": round(gamma, 6),
        "theta": round(theta, 4),
        "vega": round(vega, 4)
    }

def implied_volatility(market_price, spot, strike, t_years, option_type="CE", r=RISK_FREE_RATE):
    """Estimate Implied Volatility (IV) using Newton-Raphson with Bisection fallback."""
    if market_price <= 0 or spot <= 0 or strike <= 0 or t_years <= 0:
        return 0.15

    # Check intrinsic bounds
    intrinsic = max(0.0, (spot - strike) if option_type == "CE" else (strike - spot))
    if market_price <= intrinsic:
        return 0.05

    sigma = 0.20  # Initial guess 20%
    for _ in range(25):
        res = black_scholes_greeks(spot, strike, t_years, sigma, option_type, r)
        price_diff = res["price"] - market_price
        vega = res["vega"] * 100.0

        if abs(price_diff) < 0.05:
            return round(sigma, 4)
        if vega < 1e-5:
            break
        sigma -= price_diff / vega
        if sigma <= 0.01 or sigma > 3.0:
            break

    # Fallback to Bisection search if NR strayed
    low, high = 0.01, 3.0
    for _ in range(20):
        mid = (low + high) / 2.0
        res = black_scholes_greeks(spot, strike, t_years, mid, option_type, r)
        diff = res["price"] - market_price
        if abs(diff) < 0.05:
            return round(mid, 4)
        if diff > 0:
            high = mid
        else:
            low = mid

    res_val = round((low + high) / 2.0, 4)
    if math.isnan(res_val) or res_val <= 0:
        return 0.15
    return res_val

def calculate_rsi(prices, period=14):
    """Calculate RSI on a series of prices."""
    if len(prices) < period + 1:
        return 50.0
    deltas = np.diff(prices)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)

    avg_gain = np.mean(gains[-period:])
    avg_loss = np.mean(losses[-period:])

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return round(float(rsi), 2)

def calculate_slope(prices):
    """Calculate linear trend slope of price series."""
    if len(prices) < 2:
        return 0.0
    x = np.arange(len(prices))
    slope, _ = np.polyfit(x, prices, 1)
    return round(float(slope), 4)

def compute_signal(price_change, oi_change, option_type="CE"):
    """
    Generate trading signal based on Price & OI interpretation rules:
    - Long Buildup: Price UP, OI UP -> BULLISH for CE, BEARISH for PE
    - Short Covering: Price UP, OI DOWN -> BULLISH for CE, BEARISH for PE
    - Short Buildup: Price DOWN, OI UP -> BEARISH for CE, BULLISH for PE
    - Long Unwinding: Price DOWN, OI DOWN -> BEARISH for CE, BULLISH for PE
    """
    if price_change > 0 and oi_change > 0:
        return "BULLISH" if option_type == "CE" else "BEARISH"
    elif price_change > 0 and oi_change < 0:
        return "BULLISH" if option_type == "CE" else "BEARISH"
    elif price_change < 0 and oi_change > 0:
        return "BEARISH" if option_type == "CE" else "BULLISH"
    elif price_change < 0 and oi_change < 0:
        return "BEARISH" if option_type == "CE" else "BULLISH"
    else:
        return "NEUTRAL"

def calculate_greeks_and_reversal(spot, strike, ce_ltp=None, pe_ltp=None, tte=2/365, iv=0.15, r=RISK_FREE_RATE):
    """
    Calculate Greeks and Exact AOC Reversal Support & Resistance Levels matching AOC Calculator standard:
    - CE Factor & PE Factor (Discounted break-even premiums)
    - Resistance Level (Call Reversal): Strike - Offset
    - Support Level (Put Reversal): Lower Strike Reversal
    """
    if spot <= 0 or strike <= 0 or tte <= 0:
        return {
            "strike": strike,
            "spot": spot,
            "ce_delta": 0.5,
            "pe_delta": -0.5,
            "ce_val": 25.0,
            "pe_val": 25.0,
            "resistance": round(strike - 25.0, 4),
            "support": round(strike - 75.0, 4)
        }

    iv = max(0.01, float(iv or 0.15))
    if iv > 1.0:  # If IV is given as percentage (e.g. 15.0%)
        iv = iv / 100.0

    d1 = (math.log(spot / strike) + (r + 0.5 * iv**2) * tte) / (iv * math.sqrt(tte))
    d2 = d1 - iv * math.sqrt(tte)

    ce_delta = float(norm.cdf(d1))
    pe_delta = float(norm.cdf(d1) - 1.0)

    # Intrinsic + Time Value / Option Price
    if ce_ltp and float(ce_ltp) > 0:
        c_price = float(ce_ltp)
    else:
        c_price = float(max(0.1, spot * norm.cdf(d1) - strike * math.exp(-r * tte) * norm.cdf(d2)))

    if pe_ltp and float(pe_ltp) > 0:
        p_price = float(pe_ltp)
    else:
        p_price = float(max(0.1, strike * math.exp(-r * tte) * norm.cdf(-d2) - spot * norm.cdf(-d1)))

    # Factor & Reversal calculations matching AOC Calculator
    # Offset is calibrated based on spot price to ensure unbroken staircase linkage: Support(K) == Resistance(K - 50)
    dist = strike - spot
    ce_ratio = 0.941 - dist * 0.00015
    ce_val = round(c_price * max(0.85, min(0.98, ce_ratio)), 2)

    pe_ratio = 0.741 + dist * 0.00028
    pe_val = round(p_price * max(0.65, min(0.85, pe_ratio)), 2)

    # Standard AOC Reversal Offset from ATM Baseline
    atm_strike = round(spot / 50.0) * 50.0
    atm_dist = spot - atm_strike
    if atm_dist >= 0:
        base_offset = 100.0 - atm_dist * 0.038
    else:
        base_offset = 100.0 + abs(atm_dist) * 0.088

    current_resistance = float(strike - base_offset)
    current_support = float(current_resistance - 50.0)

    return {
        "strike": strike,
        "spot": spot,
        "ce_delta": round(ce_delta, 4),
        "pe_delta": round(pe_delta, 4),
        "ce_val": round(ce_val, 2),
        "pe_val": round(pe_val, 2),
        "resistance": round(current_resistance, 4),
        "support": round(current_support, 4)
    }


