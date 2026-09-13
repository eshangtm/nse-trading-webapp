import sqlite3, os, json, hashlib
from datetime import datetime, timedelta
import pandas as pd

from settings_manager import get as _get_setting

DB_PATH = r"C:\nse_tool\research_data.db"

_db_ensured = False

SIGNAL_TABLE = """
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    symbol TEXT,
    expiry TEXT,
    spot_price REAL,
    strike REAL,
    option_type TEXT,
    direction TEXT NOT NULL,
    probability REAL,
    confidence REAL,
    reasons TEXT,
    price_at_signal REAL,
    price_after_15m REAL,
    price_after_30m REAL,
    price_after_60m REAL,
    val_time_15m TEXT,
    val_time_30m TEXT,
    val_time_60m TEXT,
    validated_15m TEXT,
    validated_30m TEXT,
    validated_60m TEXT,
    point_diff REAL,
    pct_move REAL,
    validation_reason TEXT,
    content_hash TEXT UNIQUE
)
"""

def _load_validation_tiers():
    return [
        (_get_setting("validation_15m_minutes", 15), round(_get_setting("validation_15m_threshold_pct", 0.3) / 100, 4)),
        (_get_setting("validation_30m_minutes", 30), round(_get_setting("validation_30m_threshold_pct", 0.5) / 100, 4)),
        (_get_setting("validation_60m_minutes", 60), round(_get_setting("validation_60m_threshold_pct", 0.7) / 100, 4)),
    ]

VALIDATION_TIERS = _load_validation_tiers()

def _get_conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def _hash(*parts):
    raw = "|".join(str(p) for p in parts if p is not None)
    return hashlib.md5(raw.encode()).hexdigest()

def ensure_table():
    global _db_ensured
    if _db_ensured:
        return
    conn = _get_conn()
    conn.execute(SIGNAL_TABLE)
    try:
        conn.execute("ALTER TABLE signals ADD COLUMN content_hash TEXT UNIQUE")
    except sqlite3.OperationalError:
        pass
    conn.commit()
    conn.close()

def _compute_max_pain(df):
    if df is None or df.empty or "strike_price" not in df.columns:
        return None
    strikes = sorted(df["strike_price"].dropna().unique())
    best_strike = None
    best_pain = float("inf")
    oi_by_strike = {}
    for s in strikes:
        ce_oi = df[(df["strike_price"] == s) & (df["option_type"] == "CE")]["oi"].sum()
        pe_oi = df[(df["strike_price"] == s) & (df["option_type"] == "PE")]["oi"].sum()
        oi_by_strike[s] = (ce_oi, pe_oi)
    for s in strikes:
        total_pain = 0.0
        for k, (ce_oi, pe_oi) in oi_by_strike.items():
            if k > s:
                total_pain += (k - s) * ce_oi
            elif k < s:
                total_pain += (s - k) * pe_oi
        if total_pain < best_pain:
            best_pain = total_pain
            best_strike = s
    return best_strike

def _compute_support_resistance(df):
    if df is None or df.empty:
        return None, None
    ce = df[df["option_type"] == "CE"]
    pe = df[df["option_type"] == "PE"]
    resistance = None
    support = None
    if not ce.empty and "oi" in ce.columns and ce["oi"].notna().any():
        resistance = float(ce.loc[ce["oi"].idxmax(), "strike_price"])
    if not pe.empty and "oi" in pe.columns and pe["oi"].notna().any():
        support = float(pe.loc[pe["oi"].idxmax(), "strike_price"])
    return support, resistance

def _reason_category(reason):
    if not reason:
        return "other"
    if reason.startswith("PCR"):
        return "pcr"
    if "Buildup" in reason:
        return "oi_buildup"
    if reason.startswith("Max Pain"):
        return "max_pain"
    if "Support" in reason or "Resistance" in reason:
        return "sr"
    return "other"

# ── Signal Mode configuration ──
SIGNAL_MODES = {
    "Fast": {
        "min_rules": 1,
        "min_weight": 0,
        "conflict_gap": 15,
        "cooldown_base_min": 30,
        "cooldown_same_cat_min": 60,
        "sideways_signal_count": 3,
    },
    "Balanced": {
        "min_rules": 1,
        "min_weight": 25,
        "conflict_gap": 20,
        "cooldown_base_min": 45,
        "cooldown_same_cat_min": 90,
        "sideways_signal_count": 2,
    },
    "High Conviction": {
        "min_rules": 2,
        "min_weight": 35,
        "conflict_gap": 25,
        "cooldown_base_min": 90,
        "cooldown_same_cat_min": 120,
        "sideways_signal_count": 3,
    },
}

def _get_mode_config():
    mode = _get_setting("signal_mode", "Fast")
    return SIGNAL_MODES.get(mode, SIGNAL_MODES["Fast"])

def generate_signals(df_snap, summary, symbol, expiry, spot_price=None,
                     prev_ce_oi=None, prev_pe_oi=None):
    ensure_table()
    if df_snap is None or df_snap.empty:
        return []
    now = datetime.now()
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")
    if spot_price is None and "underlying_spot_price" in df_snap.columns:
        sp = df_snap["underlying_spot_price"].dropna()
        if not sp.empty:
            spot_price = float(sp.iloc[0])
    pcr = summary.get("pcr")
    ce_oi = summary.get("total_call_oi", 0) or 0
    pe_oi = summary.get("total_put_oi", 0) or 0
    ce_oic = ((ce_oi - prev_ce_oi) / prev_ce_oi * 100) if prev_ce_oi and prev_ce_oi > 0 else None
    pe_oic = ((pe_oi - prev_pe_oi) / prev_pe_oi * 100) if prev_pe_oi and prev_pe_oi > 0 else None
    max_pain = _compute_max_pain(df_snap)
    support, resistance = _compute_support_resistance(df_snap)
    rules_fired = []
    reasons = []

    # Rule 1: PCR Oversold
    if pcr is not None and pcr < 0.7:
        rules_fired.append(("BUY", 15))
        reasons.append(f"PCR Oversold: {pcr:.3f}")

    # Rule 2: PCR Overbought
    if pcr is not None and pcr > 1.3:
        rules_fired.append(("SELL", 15))
        reasons.append(f"PCR Overbought: {pcr:.3f}")

    # Rule 3: Call Buildup
    if ce_oic is not None and ce_oic > 10 and ce_oi > pe_oi:
        rules_fired.append(("BUY", 20))
        reasons.append(f"Call Buildup: CE OI +{ce_oic:.1f}%")

    # Rule 4: Put Buildup
    if pe_oic is not None and pe_oic > 10 and pe_oi > ce_oi:
        rules_fired.append(("SELL", 20))
        reasons.append(f"Put Buildup: PE OI +{pe_oic:.1f}%")

    # Rule 5: Max Pain Bounce
    if max_pain and spot_price:
        mp_ratio = spot_price / max_pain
        if mp_ratio <= 0.995:
            rules_fired.append(("BUY", 15))
            reasons.append(f"Max Pain Bounce: Spot {spot_price:.1f} <= MP {max_pain:.1f}")

    # Rule 6: Max Pain Reject
    if max_pain and spot_price:
        mp_ratio = spot_price / max_pain
        if mp_ratio >= 1.005:
            rules_fired.append(("SELL", 15))
            reasons.append(f"Max Pain Reject: Spot {spot_price:.1f} >= MP {max_pain:.1f}")

    # Rule 7: Support Bounce
    if support and spot_price:
        sp_diff = abs(spot_price - support) / support
        if sp_diff <= 0.003:
            rules_fired.append(("BUY", 15))
            reasons.append(f"Support Bounce: Spot {spot_price:.1f} near Support {support:.1f}")

    # Rule 8: Resistance Reject
    if resistance and spot_price:
        rs_diff = abs(spot_price - resistance) / resistance
        if rs_diff <= 0.003:
            rules_fired.append(("SELL", 15))
            reasons.append(f"Resistance Reject: Spot {spot_price:.1f} near Resistance {resistance:.1f}")

    if not rules_fired:
        return []

    # Aggregate by direction
    buy_weight = sum(w for d, w in rules_fired if d == "BUY")
    sell_weight = sum(w for d, w in rules_fired if d == "SELL")
    buy_reasons = [r for i, r in enumerate(reasons) if rules_fired[i][0] == "BUY"]
    sell_reasons = [r for i, r in enumerate(reasons) if rules_fired[i][0] == "SELL"]

    # ── Mode-based conflict resolution ──
    config = _get_mode_config()
    gap = config["conflict_gap"]
    if buy_weight > 0 and sell_weight > 0:
        if buy_weight >= sell_weight + gap:
            sell_weight = 0
            sell_reasons = []
        elif sell_weight >= buy_weight + gap:
            buy_weight = 0
            buy_reasons = []
        else:
            buy_weight = 0
            sell_weight = 0
            buy_reasons = []
            sell_reasons = []

    signals_created = []
    conn = _get_conn()

    # ── Signal frequency check (from DB) ──
    recent_count = conn.execute(
        "SELECT COUNT(*) AS cnt FROM signals WHERE symbol=? AND created_at >= ?",
        (symbol, (now - timedelta(minutes=60)).strftime("%Y-%m-%d %H:%M:%S")),
    ).fetchone()
    signal_count_60m = recent_count["cnt"] if recent_count else 0

    for direction, weight, dir_reasons in [
        ("BUY", buy_weight, buy_reasons),
        ("SELL", sell_weight, sell_reasons),
    ]:
        if not dir_reasons:
            continue
        confidence = min(100, weight)
        probability = confidence
        dedup = _hash(now_str[:10], symbol, direction, dir_reasons[0][:40])
        existing = conn.execute(
            "SELECT id FROM signals WHERE content_hash=?",
            (dedup,),
        ).fetchone()
        if existing:
            continue

        # ── Mode: minimum distinct rules ──
        if len(dir_reasons) < config["min_rules"]:
            continue

        # ── Mode: minimum total weight ──
        if weight < config["min_weight"]:
            continue

        # ── Per-direction cooldown ──
        # Extended to at least 60 min when signal rate exceeds mode threshold.
        cooldown_min = config["cooldown_base_min"]
        if signal_count_60m >= config["sideways_signal_count"]:
            cooldown_min = max(cooldown_min, 60)
        cooldown_row = conn.execute(
            "SELECT id FROM signals WHERE symbol=? AND direction=? AND created_at >= ?",
            (symbol, direction,
             (now - timedelta(minutes=cooldown_min)).strftime("%Y-%m-%d %H:%M:%S")),
        ).fetchone()
        if cooldown_row:
            continue

        # ── Same-reason-category dedup ──
        # Prevents the same root cause (e.g. "PCR Oversold") from re-triggering
        # repeatedly within the mode's configured silence window.
        reason_cat = _reason_category(dir_reasons[0])
        if reason_cat != "other":
            similar = conn.execute(
                "SELECT reasons FROM signals WHERE symbol=? AND direction=? AND created_at >= ?"
                " ORDER BY created_at DESC LIMIT 1",
                (symbol, direction,
                 (now - timedelta(minutes=config["cooldown_same_cat_min"])).strftime("%Y-%m-%d %H:%M:%S")),
            ).fetchone()
            if similar:
                prev_reasons = json.loads(similar["reasons"])
                if prev_reasons and _reason_category(prev_reasons[0]) == reason_cat:
                    continue

        strike_for_signal = None
        opt_for_signal = "BOTH"
        if direction == "BUY" and support:
            strike_for_signal = support
            opt_for_signal = "PE"
        elif direction == "SELL" and resistance:
            strike_for_signal = resistance
            opt_for_signal = "CE"

        cur = conn.execute(
            """INSERT INTO signals
               (created_at, symbol, expiry, spot_price, strike, option_type,
                direction, probability, confidence, reasons, price_at_signal,
                content_hash)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (now_str, symbol, expiry, spot_price, strike_for_signal,
             opt_for_signal, direction, round(probability, 1),
             round(confidence, 1), json.dumps(dir_reasons), spot_price,
             dedup),
        )
        sig_id = cur.lastrowid
        signals_created.append({
            "id": sig_id,
            "created_at": now_str,
            "symbol": symbol,
            "direction": direction,
            "confidence": confidence,
            "reasons": dir_reasons,
            "price_at_signal": spot_price,
        })

    conn.commit()
    conn.close()
    return signals_created


def generate_signals_from_buffer(symbol, expiry, df_snap=None, summary=None):
    """Generate signals using latest live buffer + cached option chain.

    - Waits for first valid WS tick before producing any signal.
    - Reads spot price from live buffer (not DB / not stale chain).
    - Falls back to the provided *df_snap* or the last cached chain
      if no explicit chain data is given.
    - Delegates to the existing ``generate_signals()`` unchanged.
    """
    from common_fyers import get_live_buffer

    buf = get_live_buffer()

    if not buf.has_any_tick():
        return []

    if df_snap is None or summary is None:
        chain = buf.get_last_chain(symbol, expiry)
        if chain is None:
            return []
        df_snap = chain["df"]
        summary = chain["summary"]

    spot = buf.get_ltp(symbol)
    if spot is None:
        spot = summary.get("spot_price")
    if spot is None and df_snap is not None:
        sp = df_snap.get("underlying_spot_price")
        if sp is not None:
            try:
                spot = float(sp.iloc[0]) if hasattr(sp, "iloc") else float(sp)
            except (TypeError, ValueError):
                spot = None

    return generate_signals(
        df_snap, summary, symbol, expiry, spot_price=spot,
    )


def validate_pending_signals(current_price, symbol=None):
    ensure_table()
    now = datetime.now()
    conn = _get_conn()
    cutoff = (now - timedelta(minutes=61)).strftime("%Y-%m-%d %H:%M:%S")
    q = "SELECT * FROM signals WHERE created_at >= ?"
    params = [cutoff]
    if symbol:
        q += " AND symbol=?"
        params.append(symbol)
    q += " ORDER BY created_at ASC"
    rows = conn.execute(q, params).fetchall()
    validated = []
    for row in rows:
        sig_time = datetime.strptime(row["created_at"], "%Y-%m-%d %H:%M:%S")
        elapsed = (now - sig_time).total_seconds() / 60
        updated = False
        price_at_sig = row["price_at_signal"] or current_price
        direction = row["direction"]

        for tier_min, tier_thresh in VALIDATION_TIERS:
            col_min = f"validated_{tier_min}m"
            val_col = f"val_time_{tier_min}m"
            price_col = f"price_after_{tier_min}m"
            col_time = val_col
            if row[col_min] is not None:
                continue
            if elapsed < tier_min:
                continue
            price_diff = current_price - price_at_sig
            pct_move = (price_diff / price_at_sig * 100) if price_at_sig else 0
            if direction == "BUY":
                if pct_move >= tier_thresh * 100:
                    status = "Success"
                elif pct_move <= -tier_thresh * 100:
                    status = "Failed"
                else:
                    status = "Neutral"
            else:
                if pct_move <= -tier_thresh * 100:
                    status = "Success"
                elif pct_move >= tier_thresh * 100:
                    status = "Failed"
                else:
                    status = "Neutral"

            reason = (
                f"Price moved {price_diff:+.1f} pts ({pct_move:+.2f}%) "
                f"within {tier_min} min. {direction} {status}."
            )
            conn.execute(
                f"UPDATE signals SET {col_min}=?, {col_time}=?, {price_col}=?, "
                f"point_diff=?, pct_move=?, validation_reason=? WHERE id=?",
                (status, now.strftime("%Y-%m-%d %H:%M:%S"),
                 round(current_price, 2), round(price_diff, 1),
                 round(pct_move, 2), reason, row["id"]),
            )
            updated = True
            validated.append({
                "id": row["id"],
                "tier": tier_min,
                "status": status,
                "reason": reason,
            })
        if updated:
            conn.commit()
    conn.close()
    return validated

# ══════════════════════════════════════════════════════════════════
#  OI Signal Analysis Engine
#  Non-destructive addition: classifies OI + IV movement into
#  actionable signal tags consumed by the auto-trade loop.
# ══════════════════════════════════════════════════════════════════


def analyze_oi_signal(ce_oi_change, pe_oi_change, iv_change=None):
    """Classify OI + IV movement into an actionable signal tag.

    Parameters
    ----------
    ce_oi_change : float
        % change in total CE OI (positive = addition, negative = unwinding).
    pe_oi_change : float
        % change in total PE OI (positive = addition, negative = unwinding).
    iv_change : float or None
        % change in overall IV (optional, used for ROCKET_BLAST detection).

    Returns
    -------
    dict with keys:
        signal  — str tag: STRONG_BULLISH / BULLISH / BEARISH / ROCKET_BLAST / NEUTRAL
        reason  — human-readable explanation
        weight  — int 0-100 confidence weight for the auto-trade loop
    """
    ce_unwind = ce_oi_change < -5
    pe_add = pe_oi_change > 5
    pe_unwind = pe_oi_change < -5
    ce_add = ce_oi_change > 5
    high_iv = iv_change is not None and abs(iv_change) > 15

    # Tier 1: ROCKET_BLAST — high unwinding on both sides + IV expansion
    if high_iv and ce_unwind and pe_unwind:
        return {
            "signal": "ROCKET_BLAST",
            "reason": (
                f"CE unwinding {ce_oi_change:+.1f}%, PE unwinding "
                f"{pe_oi_change:+.1f}%, IV expansion {iv_change:+.1f}%"
            ),
            "weight": 90,
        }

    # Tier 2: STRONG_BULLISH — CE unwinding + PE addition
    if ce_unwind and pe_add:
        return {
            "signal": "STRONG_BULLISH",
            "reason": (
                f"CE unwinding {ce_oi_change:+.1f}% + "
                f"PE addition {pe_oi_change:+.1f}%"
            ),
            "weight": 80,
        }

    # Tier 3: BULLISH — PE addition dominates CE addition
    if pe_add and not ce_add and pe_oi_change > ce_oi_change:
        return {
            "signal": "BULLISH",
            "reason": (
                f"PE addition {pe_oi_change:+.1f}% > "
                f"CE change {ce_oi_change:+.1f}%"
            ),
            "weight": 60,
        }

    # Tier 4: BEARISH — PE unwinding + CE addition
    if pe_unwind and ce_add:
        return {
            "signal": "BEARISH",
            "reason": (
                f"PE unwinding {pe_oi_change:+.1f}% + "
                f"CE addition {ce_oi_change:+.1f}%"
            ),
            "weight": 75,
        }

    return {
        "signal": "NEUTRAL",
        "reason": (
            f"CE {ce_oi_change:+.1f}%, PE {pe_oi_change:+.1f}% "
            f"— no dominant signal"
        ),
        "weight": 0,
    }


def get_signal_history(symbol=None, direction=None, date_from=None, date_to=None,
                       validation_status=None, search=None, limit=200):
    ensure_table()
    conn = _get_conn()
    q = "SELECT * FROM signals WHERE 1=1"
    params = []
    if symbol:
        q += " AND symbol=?"
        params.append(symbol)
    if direction:
        q += " AND direction=?"
        params.append(direction)
    if date_from:
        q += " AND created_at >= ?"
        params.append(date_from)
    if date_to:
        q += " AND created_at <= ?"
        params.append(date_to)
    if search:
        q += " AND symbol LIKE ?"
        params.extend([f"%{search}%", f"%{search}%"])
    if validation_status == "Pending":
        q += " AND validated_15m IS NULL AND validated_30m IS NULL AND validated_60m IS NULL"
    elif validation_status:
        q += " AND (validated_15m=? OR validated_30m=? OR validated_60m=?)"
        params.extend([validation_status, validation_status, validation_status])
    q += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    rows = conn.execute(q, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ══════════════════════════════════════════════════════════════════
#  Signal Engine Debug Diagnostics
#  Returns structured reasons why signals are NOT being generated,
#  consumed by the Automation Panel UI for diagnostics.
# ══════════════════════════════════════════════════════════════════


def get_signal_debug_info(symbol, df_snap=None, summary=None,
                          prev_ce_oi=None, prev_pe_oi=None):
    """Return a list of (check_name, status, detail) tuples explaining
    why signals are or are not being generated.

    Status values:  ✅ Pass  |  ❌ Fail  |  ⚠️  N/A
    """
    from datetime import datetime

    checks = []
    ensure_table()
    now = datetime.now()
    conn = _get_conn()
    mode_cfg = _get_mode_config()

    if df_snap is None or df_snap.empty:
        checks.append(("Data Available", "❌ Fail", "No option chain data (df_snap is None/empty)"))
        conn.close()
        return checks
    checks.append(("Data Available", "✅ Pass", f"{len(df_snap)} rows in chain"))

    spot_price = summary.get("spot_price") if summary else None
    if spot_price is None and "underlying_spot_price" in df_snap.columns:
        sp = df_snap["underlying_spot_price"].dropna()
        if not sp.empty:
            spot_price = float(sp.iloc[0])

    pcr = summary.get("pcr") if summary else None
    ce_oi = summary.get("total_call_oi", 0) or 0 if summary else 0
    pe_oi = summary.get("total_put_oi", 0) or 0 if summary else 0
    ce_oic = ((ce_oi - prev_ce_oi) / prev_ce_oi * 100) if prev_ce_oi and prev_ce_oi > 0 else None
    pe_oic = ((pe_oi - prev_pe_oi) / prev_pe_oi * 100) if prev_pe_oi and prev_pe_oi > 0 else None
    max_pain = _compute_max_pain(df_snap)
    support, resistance = _compute_support_resistance(df_snap)

    # Rule checks
    rules_ok = []
    if pcr is not None and pcr < 0.7:
        rules_ok.append(("PCR Oversold: BUY", f"PCR={pcr:.3f} < 0.7"))
    if pcr is not None and pcr > 1.3:
        rules_ok.append(("PCR Overbought: SELL", f"PCR={pcr:.3f} > 1.3"))
    if ce_oic is not None and ce_oic > 10 and ce_oi > pe_oi:
        rules_ok.append(("Call Buildup: BUY", f"CE OI +{ce_oic:.1f}%, CE>PE"))
    if pe_oic is not None and pe_oic > 10 and pe_oi > ce_oi:
        rules_ok.append(("Put Buildup: SELL", f"PE OI +{pe_oic:.1f}%, PE>CE"))
    if max_pain and spot_price and spot_price / max_pain <= 0.995:
        rules_ok.append(("Max Pain Bounce: BUY", f"Spot {spot_price:.0f} <= 99.5% MP {max_pain:.0f}"))
    if max_pain and spot_price and spot_price / max_pain >= 1.005:
        rules_ok.append(("Max Pain Reject: SELL", f"Spot {spot_price:.0f} >= 100.5% MP {max_pain:.0f}"))
    if support and spot_price and abs(spot_price - support) / support <= 0.003:
        rules_ok.append(("Support Bounce: BUY", f"Spot {spot_price:.0f} near Support {support:.0f}"))
    if resistance and spot_price and abs(spot_price - resistance) / resistance <= 0.003:
        rules_ok.append(("Resistance Reject: SELL", f"Spot {spot_price:.0f} near Resistance {resistance:.0f}"))

    if not rules_ok:
        checks.append(("Rules Triggered", "❌ Fail", "No rules are currently firing"))
    else:
        checks.append(("Rules Triggered", "✅ Pass", f"{len(rules_ok)} rule(s) active"))

    # Mode config
    checks.append(("Signal Mode", "ℹ️", f"{_get_setting('signal_mode', 'Fast')} (min_rules={mode_cfg['min_rules']}, min_weight={mode_cfg['min_weight']}, conflict_gap={mode_cfg['conflict_gap']})"))

    # Signal count in last 60 min
    recent_count = conn.execute(
        "SELECT COUNT(*) AS cnt FROM signals WHERE symbol=? AND created_at >= ?",
        (symbol, (now - timedelta(minutes=60)).strftime("%Y-%m-%d %H:%M:%S")),
    ).fetchone()
    cnt_60 = recent_count["cnt"] if recent_count else 0
    checks.append(("Signals (60 min)", "ℹ️", f"{cnt_60} signals (sideways threshold={mode_cfg['sideways_signal_count']})"))

    # Per-direction cooldown check
    for direction in ("BUY", "SELL"):
        cooldown_min = mode_cfg["cooldown_base_min"]
        if cnt_60 >= mode_cfg["sideways_signal_count"]:
            cooldown_min = max(cooldown_min, 60)
        recent_dir = conn.execute(
            "SELECT id FROM signals WHERE symbol=? AND direction=? AND created_at >= ?",
            (symbol, direction, (now - timedelta(minutes=cooldown_min)).strftime("%Y-%m-%d %H:%M:%S")),
        ).fetchone()
        status = "❌ Blocked" if recent_dir else "✅ Available"
        checks.append((f"Cooldown ({direction})", status, f"{cooldown_min}min window"))

    conn.close()
    return checks


def get_trade_filter_debug_info(symbol, strike, option_type, entry_price):
    """Return list of (check_name, status, detail) for trade safety filters.

    Mirrors the logic in can_execute_trade() so the UI can show why a
    trade is blocked without actually executing it.
    """
    from paper_trader import (
        get_running_trades, get_trade_by_event,
        is_active_trade, is_hard_blocked,
    )
    from automation_panel import get_max_open_trades, MIN_ENTRY_PRICE

    checks = []

    # 1. Max open positions
    max_open = get_max_open_trades()
    running = get_running_trades()
    if len(running) >= max_open:
        checks.append(("Max Open Trades", "❌ Blocked", f"{len(running)} running >= {max_open} max"))
    else:
        checks.append(("Max Open Trades", "✅ Pass", f"{len(running)} running < {max_open} max"))

    # 2. Min price
    try:
        ep = float(entry_price)
        if ep < MIN_ENTRY_PRICE:
            checks.append(("Min Price Filter", "❌ Blocked", f"₹{ep:.2f} < ₹{MIN_ENTRY_PRICE}"))
        else:
            checks.append(("Min Price Filter", "✅ Pass", f"₹{ep:.2f} >= ₹{MIN_ENTRY_PRICE}"))
    except (ValueError, TypeError):
        checks.append(("Min Price Filter", "❌ Blocked", f"Invalid entry_price: {entry_price}"))

    # 3. DB duplicate
    existing = get_trade_by_event(symbol, float(strike), option_type)
    if existing:
        checks.append(("Duplicate (DB)", "❌ Blocked", f"Trade #{existing['id']} already running"))
    else:
        checks.append(("Duplicate (DB)", "✅ Pass", "No existing trade in DB"))

    # 4. In-memory guards
    if is_active_trade(symbol, float(strike), option_type):
        checks.append(("Duplicate (Memory)", "❌ Blocked", "Active-trade guard blocks"))
    else:
        checks.append(("Duplicate (Memory)", "✅ Pass", "Not in active-trade set"))

    if is_hard_blocked(symbol, float(strike), option_type):
        checks.append(("Hard Blocked", "❌ Blocked", "Already traded this session"))
    else:
        checks.append(("Hard Blocked", "✅ Pass", "Not hard-blocked"))

    return checks
