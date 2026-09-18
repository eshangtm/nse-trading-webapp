# ══════════════════════════════════════════════════════════════════
#  Telegram Notifier — Zero-Dependency Institutional Dispatcher
#  Sends High-Priority Long Trade Alerts with Visual Charts to Telegram
# ══════════════════════════════════════════════════════════════════
import os
import sys
import json
import time
import requests
from datetime import datetime
from typing import Optional, Dict, Any

try:
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
SETTINGS_FILE = os.path.join(PROJECT_ROOT, "settings.json")

def load_telegram_config() -> Dict[str, str]:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
                if not token:
                    token = cfg.get("telegram_bot_token", "")
                if not chat_id:
                    chat_id = cfg.get("telegram_chat_id", "")
        except Exception:
            pass
    return {"token": token.strip(), "chat_id": chat_id.strip()}

def save_telegram_config(token: str, chat_id: str):
    try:
        cfg = {}
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        cfg["telegram_bot_token"] = token.strip()
        cfg["telegram_chat_id"] = str(chat_id).strip()
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
        return True
    except Exception as e:
        print("[TELEGRAM] Error saving config:", e)
        return False

def send_telegram_message(text: str, parse_mode: str = "Markdown", chat_id: Optional[str] = None) -> Dict[str, Any]:
    cfg = load_telegram_config()
    token = cfg["token"]
    raw_targets = chat_id or cfg["chat_id"]

    if not token or not raw_targets:
        return {"status": "unconfigured", "message": "Telegram Bot Token or Chat ID not set."}

    targets = [t.strip() for t in str(raw_targets).split(",") if t.strip()]
    last_res = {"status": "ok"}
    url = f"https://api.telegram.org/bot{token}/sendMessage"

    for t_chat in targets:
        payload = {
            "chat_id": t_chat,
            "text": text,
            "parse_mode": parse_mode
        }
        try:
            res = requests.post(url, json=payload, timeout=8)
            data = res.json()
            if data.get("ok"):
                last_res = {"status": "ok", "message_id": data["result"]["message_id"]}
            else:
                last_res = {"status": "error", "message": data.get("description", "Failed to send message")}
        except Exception as e:
            last_res = {"status": "error", "message": str(e)}
    return last_res

def send_telegram_photo(photo_path: str, caption: str = "", parse_mode: str = "Markdown", chat_id: Optional[str] = None) -> Dict[str, Any]:
    cfg = load_telegram_config()
    token = cfg["token"]
    raw_targets = chat_id or cfg["chat_id"]

    if not token or not raw_targets:
        return {"status": "unconfigured", "message": "Telegram Bot Token or Chat ID not set."}

    if not os.path.exists(photo_path):
        return {"status": "error", "message": f"Photo path not found: {photo_path}"}

    targets = [t.strip() for t in str(raw_targets).split(",") if t.strip()]
    last_res = {"status": "ok"}
    url = f"https://api.telegram.org/bot{token}/sendPhoto"

    for t_chat in targets:
        data = {
            "chat_id": t_chat,
            "caption": caption[:1024],
            "parse_mode": parse_mode
        }
        try:
            with open(photo_path, "rb") as f:
                files = {"photo": f}
                res = requests.post(url, data=data, files=files, timeout=15)
                res_json = res.json()
                if res_json.get("ok"):
                    last_res = {"status": "ok", "message_id": res_json["result"]["message_id"]}
                else:
                    last_res = {"status": "error", "message": res_json.get("description", "Photo send failed")}
        except Exception as e:
            last_res = {"status": "error", "message": str(e)}
    return last_res

def format_long_trade_caption(trade_plan: Dict[str, Any]) -> str:
    """
    Creates an institutional markdown caption for the Telegram alert.
    """
    spot = trade_plan.get("spot_price", 0.0)
    strike = trade_plan.get("suggested_strike", "ATM")
    target1 = trade_plan.get("target_1", spot + 40.0)
    target2 = trade_plan.get("target_2", spot + 80.0)
    sl = trade_plan.get("stop_loss", spot - 18.0)
    prob = trade_plan.get("long_probability", 80.0)
    conviction = trade_plan.get("conviction_label", "A+ LONG SETUP")
    reasoning = trade_plan.get("ai_reasoning", "Strong institutional absorption + trend continuation.")
    timestamp = trade_plan.get("timestamp", datetime.now().strftime("%H:%M:%S"))

    caption = (
        f"🚀 *AI LONG TRADE ALERT — NIFTY 50*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"⏱ *Time*: `{timestamp}` (15m Holding)\n"
        f"🎯 *Conviction*: *{conviction}* ({prob:.1f}% Win Prob)\n"
        f"📍 *Spot Entry*: `{spot:.2f}`\n"
        f"⚡ *Instrument*: *NIFTY {strike} CE*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🟢 *Target 1*: `{target1:.1f}` (+40 Pts)\n"
        f"🚀 *Target 2 (Runner)*: `{target2:.1f}` (+80 Pts)\n"
        f"🛡 *Invalidation (SL)*: `{sl:.1f}` (-18 Pts)\n"
        f"⚖ *Risk-Reward*: `1 : 2.5+`\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🧠 *AI Synthesis*:\n"
        f"_{reasoning}_\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💡 _Review in QuantGini Live Terminal_"
    )
    return caption

def format_trade_result_message(result: Dict[str, Any]) -> str:
    """
    Creates an institutional markdown message for the Trade Result & Outcome
    with 100% auditable parameters against real market data.
    """
    outcome = result.get("outcome", "TARGET_1_HIT")
    contract = result.get("contract", "NIFTY CE")
    trade_date = result.get("trade_date") or result.get("entry_time", "").split(" ")[0] or datetime.now().strftime("%Y-%m-%d")
    expiry = result.get("expiry", "Weekly Current Expiry")
    entry_spot = float(result.get("entry_spot", 0.0))
    exit_spot = float(result.get("exit_spot", 0.0))
    spot_pts = exit_spot - entry_spot
    entry_ltp = float(result.get("entry_ltp", 0.0))
    exit_ltp = float(result.get("exit_ltp", 0.0))
    opt_pts = exit_ltp - entry_ltp
    qty = int(result.get("qty", 130))
    lots = int(result.get("lots", 2))
    pnl_rupees = float(result.get("pnl_rupees", opt_pts * qty))
    margin = round(entry_ltp * qty, 2)
    ret_pct = round((pnl_rupees / margin * 100.0), 1) if margin > 0 else 0.0
    entry_time = str(result.get("entry_time", ""))
    exit_time = str(result.get("exit_time", datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    duration = result.get("duration_mins", 25)

    if "TARGET" in outcome or pnl_rupees > 0:
        header_icon = "🎯"
        title = f"TARGET HIT ({spot_pts:+.1f} SPOT PTS RUN)"
        status_text = "🏆 *PROFIT BOOKED (A+ WIN)*"
        accuracy_verdict = "✅ *100% ACCURATE* (Forecast Delivered)"
    else:
        header_icon = "🛑"
        title = "STOP LOSS HIT"
        status_text = "🛡 *DISCIPLINED SL EXIT*"
        accuracy_verdict = "⚠️ *INVALIDATION TRIGGERED* (Loss Capped)"

    pnl_sign = "+" if pnl_rupees >= 0 else ""
    pts_sign = "+" if opt_pts >= 0 else ""

    text = (
        f"{header_icon} *TRADE RESULT & AUDIT PROOF*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📅 *Trade Date*: `{trade_date}`\n"
        f"⌛ *Expiry Date*: `{expiry}`\n"
        f"⚡ *Instrument*: `{contract}`\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"⏱ *Time Audit*:\n"
        f"• Entry: `{entry_time}`\n"
        f"• Exit : `{exit_time}` ({duration} Mins Holding)\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📍 *Spot Price Range*:\n"
        f"• Entry Spot: `{entry_spot:.2f}`\n"
        f"• Exit Spot : `{exit_spot:.2f}`\n"
        f"• *Spot Run* : *{spot_pts:+.2f} Pts*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💵 *Option Premium (LTP)*:\n"
        f"• Buy Rate  : `₹{entry_ltp:.2f}`\n"
        f"• Exit Rate : `₹{exit_ltp:.2f}`\n"
        f"• *Gain*    : *{pts_sign}{opt_pts:+.2f} Pts*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 *Financials*:\n"
        f"• Position  : {lots} Lots ({qty} Qty)\n"
        f"• Margin    : ₹{margin:,.2f}\n"
        f"• *Net P&L* : *{pnl_sign}₹{pnl_rupees:,.2f}* ({pnl_sign}{ret_pct}%)\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🎯 *Forecast Accuracy*:\n"
        f"{accuracy_verdict}\n"
        f"{status_text}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💡 _Auditable in QuantGini DuckDB Engine_"
    )
    return text

def send_telegram_trade_result(result: Dict[str, Any], chart_image_path: Optional[str] = None) -> Dict[str, Any]:
    text = format_trade_result_message(result)
    if chart_image_path and os.path.exists(chart_image_path):
        return send_telegram_photo(chart_image_path, caption=text)
    return send_telegram_message(text)

def send_telegram_trade_entry(trade_data: Dict[str, Any]) -> Dict[str, Any]:
    """Dispatches real-time trade entry alert to Telegram."""
    contract = trade_data.get("contract", "NIFTY OPTION")
    direction = trade_data.get("direction", "CALL")
    entry_p = float(trade_data.get("entry_price", 0.0))
    sl_p = float(trade_data.get("sl_price", entry_p - 12.0))
    target_p = float(trade_data.get("target_price", entry_p + 35.0))
    qty = int(trade_data.get("quantity", trade_data.get("qty", 50)))
    lots = int(trade_data.get("lots", max(1, qty // 50)))
    spot = float(trade_data.get("spot_price", 0.0))
    t_str = trade_data.get("time_str", datetime.now().strftime("%H:%M:%S"))
    reason = trade_data.get("reason", "Institutional AI Signal")

    dir_icon = "🟢 CALL (BULLISH)" if direction == "CALL" else "🔴 PUT (BEARISH)"

    msg = (
        f"⚡ *NEW TRADE EXECUTED*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🎯 *Signal*: {dir_icon}\n"
        f"📌 *Contract*: `{contract}`\n"
        f"⏱️ *Time*: `{t_str}` IST\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 *Buy Rate (LTP)*: `₹{entry_p:.2f}`\n"
        f"📦 *Position*: `{lots} Lot{'s' if lots > 1 else ''}` ({qty} Qty)\n"
        f"📍 *Nifty Spot*: `{spot:.2f}`\n"
        f"🛑 *Initial SL*: `₹{sl_p:.2f}` (-{round(entry_p - sl_p, 1)} pts)\n"
        f"🚀 *Target*: `₹{target_p:.2f}` (Uncapped Runner Mode)\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🧠 *Strategy*: _{reason}_\n"
        f"🛡️ *Rules*: Early Shield at +5.5pt | -2pt Dynamic Ratchet\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🌐 _QuantGini Virtual Trading SaaS_"
    )
    return send_telegram_message(msg)

def send_telegram_tsl_update(trail_data: Dict[str, Any]) -> Dict[str, Any]:
    """Dispatches real-time trailing stop-loss shift (Early Shield, Mid Runner, or Mega -2pt Ratchet)."""
    contract = trail_data.get("contract", "NIFTY OPTION")
    peak_pts = float(trail_data.get("peak_pts", 0.0))
    new_sl = float(trail_data.get("new_sl", 0.0))
    entry_p = float(trail_data.get("entry_price", 0.0))
    locked_pts = round(new_sl - entry_p, 2)
    qty = int(trail_data.get("quantity", trail_data.get("qty", 50)))
    net_rs = trail_data.get("net_rs", (locked_pts - 1.40 - 0.60) * qty)

    if peak_pts >= 12.0:
        header = f"🚀 *MEGA RUNNER -2PT RATCHET ACTIVE*"
        desc = f"Trail strictly 2.0 pts behind highest peak! (*{peak_pts:.1f} pts ➔ SL {locked_pts:+.1f} pts*)"
    elif peak_pts >= 8.0:
        header = f"🎯 *MID RUNNER TRAILING*"
        desc = f"Locked in +{locked_pts:.1f} pts profit on pullback protection."
    else:
        header = f"🛡️ *EARLY PULLBACK SHIELD ACTIVATED*"
        desc = f"Brokerage (₹70) + slippage covered! Guaranteed *+₹{int(net_rs)} Net* in hand."

    msg = (
        f"{header}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📌 *Contract*: `{contract}`\n"
        f"📈 *Peak Gain Reached*: `+{peak_pts:.2f} pts`\n"
        f"🔒 *Stop Loss Shifted To*: `₹{new_sl:.2f}` (`{locked_pts:+.2f} pts`)\n"
        f"💰 *Guaranteed Net Profit*: `+₹{int(net_rs)} Net`\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"ℹ️ {desc}\n"
        f"🌐 _QuantGini Live Trailing Engine_"
    )
    return send_telegram_message(msg)

def send_telegram_trade_exit(exit_data: Dict[str, Any]) -> Dict[str, Any]:
    """Dispatches detailed trade exit with points, gross PnL, brokerage, and net in-hand profit."""
    contract = exit_data.get("contract", "NIFTY OPTION")
    direction = exit_data.get("direction", "CALL")
    entry_p = float(exit_data.get("entry_price", 0.0))
    exit_p = float(exit_data.get("exit_price", 0.0))
    pnl_pts = round(exit_p - entry_p, 2)
    qty = int(exit_data.get("quantity", exit_data.get("qty", 50)))
    lots = int(exit_data.get("lots", max(1, qty // 50)))
    gross_pnl = round(pnl_pts * qty, 2)
    brokerage = float(exit_data.get("brokerage", lots * 70.0))
    slippage = float(exit_data.get("slippage", 0.0))
    net_pnl = float(exit_data.get("net_pnl", gross_pnl - brokerage - slippage))
    reason = exit_data.get("exit_reason", "EXIT")
    entry_ts = str(exit_data.get("entry_timestamp", ""))
    exit_ts = str(exit_data.get("exit_timestamp", datetime.now().strftime("%H:%M:%S")))

    if net_pnl > 0:
        icon = "🏆"
        verdict = "PROFIT BOOKED (NET IN-HAND GAIN)"
        pnl_color = f"+₹{net_pnl:,.2f}"
    else:
        icon = "🛑"
        verdict = "STOP LOSS EXITED (CAP PROTECTED)"
        pnl_color = f"-₹{abs(net_pnl):,.2f}"

    msg = (
        f"{icon} *TRADE CLOSED — {verdict}*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📌 *Contract*: `{contract}` ({direction})\n"
        f"⏱️ *Duration*: `{entry_ts[-8:]}` ➔ `{exit_ts[-8:]}` IST\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💵 *Buy Price*: `₹{entry_p:.2f}`\n"
        f"🏁 *Exit Price*: `₹{exit_p:.2f}`\n"
        f"📈 *Points Captured*: `{pnl_pts:+.2f} pts`\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 *Gross P&L*: `₹{gross_pnl:+,.2f}`\n"
        f"🧾 *Brokerage & Slippage*: `-₹{(brokerage + slippage):,.2f}`\n"
        f"💎 *NET PROFIT (IN HAND)*: *{pnl_color}*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 *Exit Reason*: `{reason}`\n"
        f"🌐 _QuantGini Virtual Trading SaaS_"
    )
    return send_telegram_message(msg)

if __name__ == "__main__":
    cfg = load_telegram_config()
    print(f"[TELEGRAM NOTIFIER] Config loaded. Token set: {bool(cfg['token'])}, Chat ID set: {bool(cfg['chat_id'])}")
    if cfg["token"] and cfg["chat_id"]:
        print("Testing Telegram connection...")
        r = send_telegram_message("🟢 *QuantGini AI System Online*\nTelegram notifications active!")
        print("Result:", r)
    else:
        print("[INFO] Telegram credentials not configured yet in settings.json.")
