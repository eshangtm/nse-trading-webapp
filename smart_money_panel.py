import streamlit as st
import pandas as pd
from signal_engine import _compute_max_pain, _compute_support_resistance, get_signal_history
from research_db import get_oi_snapshots
from common_fyers import get_live_buffer


def render_smart_money_panel(
    symbol, expiry, chain_df, summary, spot_price,
    enabled_strikes, available_strikes, prev_oi,
    prev_ce_oi, prev_pe_oi,
):
    st.markdown("### 🧠 Smart Money Dashboard")

    if chain_df is None or chain_df.empty:
        st.info("Start the live monitor or fetch once to load data.")
        return

    # ── Compute all metrics ──
    oi_score, oi_reasons = _compute_oi_flow_score(chain_df, prev_oi, spot_price)
    mf_score, mf_reasons = _compute_money_flow_score(chain_df, prev_oi)
    ms_score, ms_reasons = _compute_market_structure_score(chain_df, summary, spot_price)
    sig_score, sig_reasons = _compute_signal_score(symbol)

    reasons = oi_reasons + mf_reasons + ms_reasons + sig_reasons

    final_score = max(0, min(100,
        oi_score * 0.30 +
        mf_score * 0.20 +
        ms_score * 0.25 +
        sig_score * 0.25
    ))

    # ── Smart Money Score Header ──
    _render_score_header(final_score, chain_df, summary, spot_price)

    # ── Three-panel layout ──
    c1, c2, c3 = st.columns(3)
    with c1:
        _render_oi_flow_panel(chain_df, prev_oi, spot_price)
    with c2:
        _render_money_flow_panel(chain_df, prev_oi)
    with c3:
        _render_market_structure_panel(chain_df, summary, spot_price)

    # ── Reasons Panel ──
    _render_reasons_panel(reasons, final_score)

    # ── Strike-level OI Buildup Table ──
    _render_oi_buildup_table(chain_df, prev_oi, spot_price, enabled_strikes, available_strikes)


# ══════════════════════════════════════════════════════════════════
#  SCORE COMPUTATION FUNCTIONS
# ══════════════════════════════════════════════════════════════════


def _compute_oi_flow_score(chain_df, prev_oi, spot_price):
    if chain_df is None or chain_df.empty or not prev_oi:
        return 50, []

    bullish_oi = 0.0
    bearish_oi = 0.0
    reasons = []
    details = []

    for _, row in chain_df.iterrows():
        strike = row.get("strike_price")
        opt = row.get("option_type")
        key = f"{strike}_{opt}"
        if key not in prev_oi:
            continue
        oi_now = row.get("oi", 0) or 0
        oi_prev = prev_oi[key].get("oi", 0) or 0
        if oi_prev == 0:
            continue
        chg = oi_now - oi_prev
        pct = (chg / oi_prev) * 100
        if abs(pct) < 1:
            continue

        if opt == "CE":
            if pct < 0:
                bullish_oi += abs(pct)
                details.append(("CE Short Covering", strike, pct))
            else:
                bearish_oi += abs(pct)
                details.append(("CE Build-up", strike, pct))
        else:
            if pct > 0:
                bullish_oi += abs(pct)
                details.append(("PE Build-up", strike, pct))
            else:
                bearish_oi += abs(pct)
                details.append(("PE Unwinding", strike, pct))

    total = bullish_oi + bearish_oi
    if total == 0:
        return 50, ["OI Flow: Neutral — no significant change"]

    net_pct = (bullish_oi - bearish_oi) / total
    score = 50 + net_pct * 50
    score = max(0, min(100, score))

    if bullish_oi > bearish_oi * 1.1:
        reasons.append(f"OI Flow: Bullish bias ({bullish_oi:.0f}% flow vs {bearish_oi:.0f}% bearish)")
    elif bearish_oi > bullish_oi * 1.1:
        reasons.append(f"OI Flow: Bearish bias ({bearish_oi:.0f}% flow vs {bullish_oi:.0f}% bullish)")
    else:
        reasons.append(f"OI Flow: Balanced ({bullish_oi:.0f}% bull / {bearish_oi:.0f}% bear)")

    top = sorted([d for d in details if abs(d[2]) > 3], key=lambda x: -abs(x[2]))[:3]
    for label, strike, pct in top:
        dir_str = "↑" if pct > 0 else "↓"
        reasons.append(f"{label} at {int(strike)} {dir_str} {abs(pct):.1f}%")

    return round(score), reasons


def _compute_money_flow_score(chain_df, prev_oi):
    if chain_df is None or chain_df.empty or not prev_oi:
        return 50, []

    bull_money = 0.0
    bear_money = 0.0

    for _, row in chain_df.iterrows():
        strike = row.get("strike_price")
        opt = row.get("option_type")
        key = f"{strike}_{opt}"
        if key not in prev_oi:
            continue
        oi_now = row.get("oi", 0) or 0
        oi_prev = prev_oi[key].get("oi", 0) or 0
        ltp = row.get("ltp", 0) or 0
        if oi_prev == 0:
            continue
        chg = oi_now - oi_prev
        money = abs(chg) * ltp
        if money == 0:
            continue

        if opt == "CE":
            if chg < 0:
                bull_money += money
            else:
                bear_money += money
        else:
            if chg > 0:
                bull_money += money
            else:
                bear_money += money

    total = bull_money + bear_money
    if total == 0:
        return 50, ["Money Flow: Neutral — no significant flow"]

    bull_pct = (bull_money / total) * 100
    bear_pct = (bear_money / total) * 100
    net = ((bull_money - bear_money) / total) * 100
    score = 50 + net / 2
    score = max(0, min(100, score))

    if net > 5:
        reasons.append(f"Money Flow: Bullish +{net:.0f}% net ({bull_pct:.0f}% / {bear_pct:.0f}%)")
    elif net < -5:
        reasons.append(f"Money Flow: Bearish {net:.0f}% net ({bull_pct:.0f}% / {bear_pct:.0f}%)")
    else:
        reasons.append(f"Money Flow: Neutral ({bull_pct:.0f}% / {bear_pct:.0f}%)")

    return round(score), reasons


def _compute_market_structure_score(chain_df, summary, spot_price):
    reasons = []
    points = 50

    support, resistance = _compute_support_resistance(chain_df)
    max_pain = _compute_max_pain(chain_df)

    # PCR
    pcr = summary.get("pcr") if summary else None
    if pcr is not None:
        if pcr > 1.3:
            points += 20
            reasons.append(f"PCR Overbought: {pcr:.2f} — bearish extreme")
        elif pcr > 1.1:
            points += 10
            reasons.append(f"PCR Bullish: {pcr:.2f} — bullish leaning")
        elif pcr < 0.7:
            points -= 20
            reasons.append(f"PCR Oversold: {pcr:.2f} — bullish extreme")
        elif pcr < 0.9:
            points -= 10
            reasons.append(f"PCR Bearish: {pcr:.2f} — bearish leaning")
        else:
            reasons.append(f"PCR Neutral: {pcr:.2f}")

    # Spot vs Support
    if spot_price and support:
        dist = ((spot_price - support) / support) * 100
        if 0 <= dist < 1:
            points += 15
            reasons.append(f"Spot at support: {int(spot_price)} ≈ {int(support)} (+{dist:.2f}%)")
        elif dist >= 1:
            points += 10
            reasons.append(f"Spot above support: {int(spot_price)} > {int(support)}")
        elif dist < 0:
            points -= 15
            reasons.append(f"Spot below support: {int(spot_price)} < {int(support)} (⚠)")

    # Spot vs Resistance
    if spot_price and resistance:
        dist = ((resistance - spot_price) / spot_price) * 100
        if 0 <= dist < 1:
            points += 15
            reasons.append(f"Spot testing resistance: {int(spot_price)} ≈ {int(resistance)}")
        elif dist >= 1:
            points += 5
            reasons.append(f"Room to resistance: {int(spot_price)} → {int(resistance)} (gap {dist:.1f}%)")
        elif dist < 0:
            points -= 10
            reasons.append(f"Spot above resistance: {int(spot_price)} > {int(resistance)} (⚠)")

    # Spot vs Max Pain
    if spot_price and max_pain:
        if spot_price > max_pain:
            points += 10
            reasons.append(f"Spot above Max Pain: {int(spot_price)} > {int(max_pain)} — bullish")
        elif spot_price < max_pain:
            points -= 5
            reasons.append(f"Spot below Max Pain: {int(spot_price)} < {int(max_pain)} — bearish")
        else:
            reasons.append(f"Spot at Max Pain: {int(spot_price)}")

    score = max(0, min(100, points))
    return score, reasons


def _compute_signal_score(symbol):
    reasons = []
    try:
        recent = get_signal_history(symbol=symbol, limit=10)
    except Exception:
        return 50, ["Signals: No data"]

    if not recent:
        return 50, ["Signals: No recent signals"]

    bullish = 0
    bearish = 0
    total_conf = 0

    for s in recent:
        conf = s.get("confidence", 50) or 50
        total_conf += conf
        if s.get("direction") == "BUY":
            bullish += conf
        elif s.get("direction") == "SELL":
            bearish += conf

    if total_conf == 0:
        return 50, ["Signals: No confidence data"]

    net = (bullish - bearish) / total_conf
    score = 50 + net * 50
    score = max(0, min(100, score))

    bullish_count = sum(1 for s in recent if s.get("direction") == "BUY")
    bearish_count = sum(1 for s in recent if s.get("direction") == "SELL")

    if bullish_count > bearish_count * 2:
        reasons.append(f"Signals: {bullish_count}B / {bearish_count}S — strong bullish")
    elif bearish_count > bullish_count * 2:
        reasons.append(f"Signals: {bullish_count}B / {bearish_count}S — strong bearish")
    elif bullish_count > bearish_count:
        reasons.append(f"Signals: {bullish_count}B / {bearish_count}S — leaning bullish")
    elif bearish_count > bullish_count:
        reasons.append(f"Signals: {bullish_count}B / {bearish_count}S — leaning bearish")
    else:
        reasons.append(f"Signals: {bullish_count}B / {bearish_count}S — balanced")

    return round(score), reasons


# ══════════════════════════════════════════════════════════════════
#  RENDER FUNCTIONS
# ══════════════════════════════════════════════════════════════════


def _render_score_header(final_score, chain_df, summary, spot_price):
    if final_score >= 80:
        emoji, label, color = "🟢", "Strong Bullish", "#3fb950"
    elif final_score >= 60:
        emoji, label, color = "🔵", "Bullish", "#58a6ff"
    elif final_score >= 40:
        emoji, label, color = "🟡", "Neutral", "#d29922"
    elif final_score >= 20:
        emoji, label, color = "🟠", "Bearish", "#f0883e"
    else:
        emoji, label, color = "🔴", "Strong Bearish", "#f85149"

    pcr = summary.get("pcr", "—") if summary else "—"
    ce_oi = summary.get("total_call_oi", "—") if summary else "—"
    pe_oi = summary.get("total_put_oi", "—") if summary else "—"

    st.markdown(f"""
    <div style="background:{color}22; border:1px solid {color}; border-radius:12px; padding:20px; margin-bottom:16px;">
        <div style="display:flex; align-items:center; gap:20px;">
            <div style="font-size:3rem;">{emoji}</div>
            <div>
                <div style="font-size:2rem; font-weight:700; color:{color};">{final_score}/100</div>
                <div style="font-size:1.2rem; color:{color};">{label}</div>
            </div>
            <div style="margin-left:auto; display:flex; gap:24px; font-size:0.9rem;">
                <div><b>CE OI</b><br>{ce_oi:,}</div>
                <div><b>PE OI</b><br>{pe_oi:,}</div>
                <div><b>PCR</b><br>{pcr}</div>
                <div><b>Spot</b><br>{int(spot_price) if spot_price else "—"}</div>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)


def _render_oi_flow_panel(chain_df, prev_oi, spot_price):
    st.markdown("**📊 OI Flow**")
    if chain_df is None or chain_df.empty or not prev_oi:
        st.caption("No data")
        return

    ce_build = pe_build = ce_unwind = pe_unwind = 0
    ce_build_vol = pe_build_vol = ce_unwind_vol = pe_unwind_vol = 0

    for _, row in chain_df.iterrows():
        strike = row.get("strike_price")
        opt = row.get("option_type")
        key = f"{strike}_{opt}"
        if key not in prev_oi:
            continue
        oi_now = row.get("oi", 0) or 0
        oi_prev = prev_oi[key].get("oi", 0) or 0
        ltp = row.get("ltp", 0) or 0
        if oi_prev == 0:
            continue
        chg = oi_now - oi_prev
        pct = (chg / oi_prev) * 100
        if abs(pct) < 1:
            continue
        money = abs(chg) * ltp

        if opt == "CE":
            if chg > 0:
                ce_build += 1
                ce_build_vol += money
            else:
                ce_unwind += 1
                ce_unwind_vol += money
        else:
            if chg > 0:
                pe_build += 1
                pe_build_vol += money
            else:
                pe_unwind += 1
                pe_unwind_vol += money

    rows = [
        ("CE Build-up", ce_build, ce_build_vol, "🔴", ce_build_vol - ce_unwind_vol),
        ("CE Unwinding", ce_unwind, ce_unwind_vol, "🟢", 0),
        ("PE Build-up", pe_build, pe_build_vol, "🟢", pe_build_vol - pe_unwind_vol),
        ("PE Unwinding", pe_unwind, pe_unwind_vol, "🔴", 0),
    ]

    for label, count, vol, icon, _ in rows:
        vol_str = f"₹{vol:,.0f}" if vol else ""
        arrow = "▲" if vol > 0 else ("▼" if vol < 0 else "—")
        st.markdown(f"{icon} **{label}:** {count} strikes {arrow} {vol_str}")

    net = (pe_build_vol + ce_unwind_vol) - (ce_build_vol + pe_unwind_vol)
    net_str = f"+₹{net:,.0f}" if net >= 0 else f"-₹{abs(net):,.0f}"
    st.markdown(f"**Net OI Flow:** {net_str}")


def _render_money_flow_panel(chain_df, prev_oi):
    st.markdown("**💰 Money Flow**")
    if chain_df is None or chain_df.empty or not prev_oi:
        st.caption("No data")
        return

    bull_money = bear_money = 0.0

    for _, row in chain_df.iterrows():
        strike = row.get("strike_price")
        opt = row.get("option_type")
        key = f"{strike}_{opt}"
        if key not in prev_oi:
            continue
        oi_now = row.get("oi", 0) or 0
        oi_prev = prev_oi[key].get("oi", 0) or 0
        ltp = row.get("ltp", 0) or 0
        if oi_prev == 0:
            continue
        chg = oi_now - oi_prev
        money = abs(chg) * ltp

        if opt == "CE":
            if chg < 0:
                bull_money += money
            else:
                bear_money += money
        else:
            if chg > 0:
                bull_money += money
            else:
                bear_money += money

    total = bull_money + bear_money
    if total == 0:
        st.caption("No significant money flow")
        return

    bull_pct = (bull_money / total) * 100
    bear_pct = (bear_money / total) * 100
    neutral_pct = 0.0
    net = ((bull_money - bear_money) / total) * 100

    st.markdown(f"""
    <div style="margin:8px 0;">
        <div style="display:flex; justify-content:space-between;">
            <span style="color:#3fb950;">🟢 Bullish</span>
            <span>{bull_pct:.0f}%</span>
        </div>
        <div style="background:#21262d; height:8px; border-radius:4px;">
            <div style="background:#3fb950; width:{bull_pct:.0f}%; height:8px; border-radius:4px;"></div>
        </div>
    </div>
    <div style="margin:8px 0;">
        <div style="display:flex; justify-content:space-between;">
            <span style="color:#f85149;">🔴 Bearish</span>
            <span>{bear_pct:.0f}%</span>
        </div>
        <div style="background:#21262d; height:8px; border-radius:4px;">
            <div style="background:#f85149; width:{bear_pct:.0f}%; height:8px; border-radius:4px;"></div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    net_label = "Bullish" if net > 0 else "Bearish" if net < 0 else "Neutral"
    st.markdown(f"**Net Money Flow:** {net_label} ({net:+.0f}%)")


def _render_market_structure_panel(chain_df, summary, spot_price):
    st.markdown("**📐 Market Structure**")

    if chain_df is None or chain_df.empty:
        st.caption("No data")
        return

    support, resistance = _compute_support_resistance(chain_df)
    max_pain = _compute_max_pain(chain_df)
    pcr = summary.get("pcr") if summary else None

    cols = [
        ("Support", f"{int(support)}" if support else "—"),
        ("Resistance", f"{int(resistance)}" if resistance else "—"),
        ("Max Pain", f"{int(max_pain)}" if max_pain else "—"),
        ("PCR", f"{pcr:.2f}" if pcr else "—"),
    ]

    for label, val in cols:
        st.markdown(f"**{label}:** `{val}`")

    # Trend strength from recent snapshots
    try:
        snaps = get_oi_snapshots(symbol=None, expiry=None, limit=20)
        if len(snaps) >= 2:
            latest = snaps[-1].get("pcr", 0) if "pcr" in snaps[-1] else 0
            prev_pcr = sum(s.get("pcr", 0) for s in snaps[-5:]) / 5 if snaps[-5:] else 0
            # PCR trend not directly in snapshots, compute from OI levels
            ce_oi_hist = [s.get("oi", 0) for s in snaps[-10:] if s.get("option_type") == "CE"]
            pe_oi_hist = [s.get("oi", 0) for s in snaps[-10:] if s.get("option_type") == "PE"]
    except Exception:
        pass

    # Spot relative position
    if spot_price and support and resistance and max_pain:
        range_size = resistance - support
        if range_size > 0:
            pos = ((spot_price - support) / range_size) * 100
            pos_label = "Lower" if pos < 33 else "Middle" if pos < 66 else "Upper"
            st.markdown(f"**Zone:** {pos_label} ({pos:.0f}%)")
        mp_dist = ((spot_price - max_pain) / max_pain) * 100
        mp_icon = "🟢" if mp_dist > 0 else "🔴" if mp_dist < 0 else "⚪"
        st.markdown(f"**Spot vs MP:** {mp_icon} {mp_dist:+.2f}%")


def _render_reasons_panel(reasons, final_score):
    st.markdown("### 💡 Reasons")

    if not reasons:
        st.caption("No reasons available yet.")
        return

    for r in reasons:
        st.markdown(f"✔ {r}")

    st.markdown(f"**Score: {final_score}/100**")


def _render_oi_buildup_table(chain_df, prev_oi, spot_price, enabled_strikes, available_strikes):
    st.markdown("### 📋 Strike-level OI Buildup/Unwind")

    if chain_df is None or chain_df.empty or not prev_oi:
        st.caption("No data")
        return

    # Filter by enabled strikes only
    strikes_in_scope = set(enabled_strikes) if enabled_strikes else set(available_strikes)
    if not strikes_in_scope:
        strikes_in_scope = set(chain_df["strike_price"].unique())

    # Option type filter (from existing strike filter)
    _eot = st.session_state.get("_strike_filter_ot", {"CALL": True, "PUT": True})
    show_ce = _eot.get("CALL", True)
    show_pe = _eot.get("PUT", True)

    rows = []
    for _, row in chain_df.iterrows():
        strike = row.get("strike_price")
        opt = row.get("option_type")
        if strike not in strikes_in_scope:
            continue
        if opt == "CE" and not show_ce:
            continue
        if opt == "PE" and not show_pe:
            continue

        key = f"{strike}_{opt}"
        oi_now = row.get("oi", 0) or 0
        ltp = row.get("ltp", 0) or 0
        oi_change = row.get("oi_change", 0) or 0
        ce_oi_chg = pe_oi_chg = None
        signal = action = ""

        if key in prev_oi:
            oi_prev = prev_oi[key].get("oi", 0) or 0
            if oi_prev > 0:
                pct = ((oi_now - oi_prev) / oi_prev) * 100
                if opt == "CE":
                    ce_oi_chg = round(pct, 1)
                else:
                    pe_oi_chg = round(pct, 1)

        if ce_oi_chg is not None and pe_oi_chg is not None:
            if ce_oi_chg > 3 and pe_oi_chg < -3:
                signal = "🔴 Bearish"
                action = "CE Build / PE Unwind"
            elif ce_oi_chg < -3 and pe_oi_chg > 3:
                signal = "🟢 Bullish"
                action = "CE Unwind / PE Build"
            elif ce_oi_chg > 3:
                signal = "🟠 Weak Bearish"
                action = "CE Build-up"
            elif pe_oi_chg > 3:
                signal = "🟢 Weak Bullish"
                action = "PE Build-up"
            else:
                signal = "⚪ Neutral"
                action = "No significant move"

        rows.append({
            "strike": int(strike),
            "type": opt,
            "oi": int(oi_now),
            "ltp": round(ltp, 2),
            "ce_chg": ce_oi_chg,
            "pe_chg": pe_oi_chg,
            "signal": signal,
            "action": action,
        })

    if not rows:
        st.caption("No strike data with OI changes")
        return

    df_display = pd.DataFrame(rows)

    # Sort by strike
    df_display = df_display.sort_values("strike", ascending=False)

    # Display as columns
    ce_df = df_display[df_display["type"] == "CE"][["strike", "oi", "ltp", "ce_chg", "signal", "action"]]
    pe_df = df_display[df_display["type"] == "PE"][["strike", "oi", "ltp", "pe_chg", "signal", "action"]]

    ce_col, pe_col = st.columns(2)
    with ce_col:
        st.markdown("**CALLS**")
        if not ce_df.empty:
            ce_df = ce_df.rename(columns={"ce_chg": "OI Δ%"})
            st.dataframe(ce_df, use_container_width=True, height=300,
                         column_config={"strike": st.column_config.NumberColumn("Strike", format="%d"),
                                        "oi": st.column_config.NumberColumn("OI", format="%d"),
                                        "ltp": st.column_config.NumberColumn("LTP", format="%.2f"),
                                        "OI Δ%": st.column_config.NumberColumn("OI Δ%", format="%+.1f"),
                                        "signal": "Signal",
                                        "action": "Action"})
        else:
            st.caption("No CALL data")

    with pe_col:
        st.markdown("**PUTS**")
        if not pe_df.empty:
            pe_df = pe_df.rename(columns={"pe_chg": "OI Δ%"})
            st.dataframe(pe_df, use_container_width=True, height=300,
                         column_config={"strike": st.column_config.NumberColumn("Strike", format="%d"),
                                        "oi": st.column_config.NumberColumn("OI", format="%d"),
                                        "ltp": st.column_config.NumberColumn("LTP", format="%.2f"),
                                        "OI Δ%": st.column_config.NumberColumn("OI Δ%", format="%+.1f"),
                                        "signal": "Signal",
                                        "action": "Action"})
        else:
            st.caption("No PUT data")
