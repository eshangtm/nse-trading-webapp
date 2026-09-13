# ══════════════════════════════════════════════════════════════════
#  Shared Fyers logic — used by all 3 interfaces
# ══════════════════════════════════════════════════════════════════
import json, os, time, requests, threading
import pandas as pd
from datetime import datetime, timedelta, timezone
from fyers_apiv3 import fyersModel
try:
    import zstandard as zstd
    HAS_ZSTD = True
except ImportError:
    HAS_ZSTD = False

TOKEN_FILE = r"C:\nse_tool\fyers_token.json"
OUTPUT_DIR = r"C:\nse_tool\collected_data"
IST_OFFSET = timedelta(hours=5, minutes=30)

from settings_manager import get as _get_setting
def get_default_strike_index():
    default = _get_setting("strike_range_default", "ATM \u00b120")
    try:
        return ALL_STRIKE_OPTIONS.index(default)
    except (ValueError, AttributeError):
        return 3

SYMBOL_MASTER_URLS = {
    "MCX"    : "https://public.fyers.in/sym_details/MCX_COM.csv",
    "NSE_FO" : "https://public.fyers.in/sym_details/NSE_FO.csv",
    "NSE_CM" : "https://public.fyers.in/sym_details/NSE_CM.csv",
}

INDEX_SYMBOLS = {
    "NIFTY"     : "NSE:NIFTY50-INDEX",
    "BANKNIFTY" : "NSE:NIFTYBANK-INDEX",
    "FINNIFTY"  : "NSE:FINNIFTY-INDEX",
    "MIDCPNIFTY": "NSE:MIDCPNIFTY-INDEX",
    "SENSEX"    : "BSE:SENSEX-INDEX",
}

RESOLUTIONS = {"1 min":"1","5 min":"5","15 min":"15","1 hour":"60","Daily":"D"}

# ── Strike Range Presets ─────────────────────────────────────────
STRIKE_PRESET_LABELS = [
    "ATM ±5",  "ATM ±10", "ATM ±15", "ATM ±20",
    "ATM ±25", "ATM ±30", "ATM ±35", "ATM ±40",
    "ATM ±45", "ATM ±50",
]
FULL_CHAIN_LABEL = "Full Chain"
ALL_STRIKE_OPTIONS = STRIKE_PRESET_LABELS + [FULL_CHAIN_LABEL]
FULL_CHAIN_STRIKECOUNT = 100

def resolve_strikecount(label):
    if label == FULL_CHAIN_LABEL:
        return FULL_CHAIN_STRIKECOUNT
    try:
        return int(label.replace("ATM ±", "").replace("ATM ", "").strip())
    except (ValueError, AttributeError):
        return 20

def is_full_chain(label):
    return label == FULL_CHAIN_LABEL

def now_ist():
    return datetime.now(timezone.utc).replace(tzinfo=None) + IST_OFFSET

def load_fyers():
    if not os.path.exists(TOKEN_FILE):
        raise FileNotFoundError(f"Token nahi mila: {TOKEN_FILE}\nPehle 1_Login.bat chalao.")
    with open(TOKEN_FILE) as f:
        creds = json.load(f)
    return fyersModel.FyersModel(
        client_id=creds["client_id"],
        token=creds["access_token"],
        is_async=False, log_path=""
    )

def get_access_token():
    if not os.path.exists(TOKEN_FILE):
        return None
    with open(TOKEN_FILE) as f:
        creds = json.load(f)
    return creds.get("access_token")

_master_cache = {}
def get_master(key):
    if key in _master_cache:
        return _master_cache[key]
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    cache = os.path.join(OUTPUT_DIR, f"_cache_{key}.csv")
    stale = not os.path.exists(cache) or (time.time() - os.path.getmtime(cache)) > 6*3600
    if stale:
        try:
            r = requests.get(SYMBOL_MASTER_URLS[key], timeout=20)
            r.raise_for_status()
            with open(cache,"wb") as f: f.write(r.content)
        except Exception as e:
            print(f"⚠ Master download failed ({e})")
    if not os.path.exists(cache):
        return pd.DataFrame()
    df = pd.read_csv(cache, header=None, low_memory=False)
    _master_cache[key] = df
    return df

def search_master(key, keyword, filter_type=None, limit=50):
    df = get_master(key)
    if df.empty or df.shape[1] <= 9:
        return []
    desc_col, sym_col = 1, 9
    mask = (
        df[desc_col].astype(str).str.upper().str.contains(keyword.upper(), na=False) |
        df[sym_col].astype(str).str.upper().str.contains(keyword.upper(), na=False)
    )
    if filter_type:
        mask &= df[desc_col].astype(str).str.upper().str.contains(filter_type.upper(), na=False)
    return list(df[mask][[sym_col, desc_col]].drop_duplicates().head(limit).itertuples(index=False, name=None))

# ── API calls ──────────────────────────────────────────────────────
def api_quote(fyers, symbol):
    resp = fyers.quotes({"symbols": symbol})
    if resp.get("s") != "ok":
        return None, str(resp)
    d = resp.get("d", [])
    if not d or d[0].get("s") != "ok":
        return None, f"Symbol error: {d}"
    return d[0].get("v", {}), None

def api_history(fyers, symbol, resolution, date_from, date_to):
    resp = fyers.history(data={
        "symbol": symbol, "resolution": resolution,
        "date_format": "1", "range_from": date_from,
        "range_to": date_to, "cont_flag": "1"
    })
    if resp.get("s") != "ok":
        return None, str(resp)
    candles = resp.get("candles", [])
    if not candles:
        return None, "Koi data nahi mila."
    df = pd.DataFrame(candles, columns=["epoch","open","high","low","close","volume"])
    df["datetime_ist"] = pd.to_datetime(df["epoch"], unit="s") + IST_OFFSET
    return df[["epoch","datetime_ist","open","high","low","close","volume"]], None

def api_expiries(fyers, symbol):
    resp = fyers.optionchain(data={"symbol": symbol, "strikecount": "2", "timestamp": ""})
    if resp.get("s") != "ok":
        return [], str(resp)
    return resp.get("data", {}).get("expiryData", []), None

def api_option_chain(fyers, symbol, strikecount, expiry_epoch):
    resp = fyers.optionchain(data={
        "symbol": symbol,
        "strikecount": str(strikecount),
        "timestamp": str(expiry_epoch)
    })
    if resp.get("s") != "ok":
        return None, str(resp)
    chain = resp.get("data", {}).get("optionsChain", [])
    if not chain:
        return None, "Koi data nahi aaya."
    df = pd.DataFrame(chain)

    # Extract spot from underlying row (strike_price == -1, option_type == '')
    spot = None
    future = None
    if "strike_price" in df.columns:
        underlying = df[df["strike_price"] == -1]
        if not underlying.empty:
            spot   = float(underlying["ltp"].iloc[0])   if "ltp" in underlying.columns else None
            future = float(underlying["fp"].iloc[0])    if "fp"  in underlying.columns else None
            # Remove underlying info row, keep only options
            df = df[df["strike_price"] != -1].copy()

    # Rename Fyers columns to standard names used across all tools
    rename = {
        "oich":  "oi_change",
        "oichp": "oi_change_pct",
        "ltpch": "ltp_change",
        "ltpchp":"ltp_change_pct",
        "fpch":  "future_change",
        "fpchp": "future_change_pct",
    }
    df = df.rename(columns=rename)

    # Add spot/future columns to every row (for downstream tools)
    df["underlying_spot_price"] = spot
    df["future_price"]          = future

    # Note: Fyers option chain does NOT return Greeks (delta/gamma/theta/vega/iv)
    # Those columns will be absent — tools handle with .get() safely

    if spot is None:
        try:
            q_res, q_err = api_quote(fyers, symbol)
            if q_res and "lp" in q_res:
                spot = float(q_res["lp"])
        except Exception:
            pass

    # OI summary
    ce  = df[df["option_type"]=="CE"]["oi"].sum() if "option_type" in df.columns and "oi" in df.columns else 0
    pe  = df[df["option_type"]=="PE"]["oi"].sum() if "option_type" in df.columns and "oi" in df.columns else 0
    pcr = round(pe/ce, 3) if ce else None
    summary = {"total_call_oi": int(ce), "total_put_oi": int(pe), "pcr": pcr}
    return df, summary, spot

def save_df(df, symbol, suffix):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    sn = symbol.replace(":","_").replace("-","_")
    csv_path  = os.path.join(OUTPUT_DIR, f"{sn}_{suffix}_{stamp}.csv")
    xlsx_path = os.path.join(OUTPUT_DIR, f"{sn}_{suffix}_{stamp}.xlsx")
    df.to_csv(csv_path, index=False)
    df.to_excel(xlsx_path, index=False)
    return csv_path, xlsx_path


# ══════════════════════════════════════════════════════════════════
#  WebSocket + Live Buffer — shared across all tools
# ══════════════════════════════════════════════════════════════════

_ws_manager = None
_ws_lock = threading.Lock()

def get_live_buffer():
    from live_buffer import LiveTickBuffer
    global _ws_manager
    with _ws_lock:
        if _ws_manager is None:
            from ws_manager import WSManager
            _ws_manager = WSManager()
        return _ws_manager.buffer

def start_ws(access_token, symbols=None):
    from ws_manager import WSManager
    global _ws_manager
    with _ws_lock:
        if _ws_manager is None:
            _ws_manager = WSManager()
        if _ws_manager.get_status() != WSManager.STATUS_CONNECTED:
            _ws_manager.connect(access_token, symbols)
        elif symbols:
            _ws_manager.subscribe(symbols)
    return _ws_manager

def stop_ws():
    global _ws_manager
    with _ws_lock:
        if _ws_manager:
            _ws_manager.disconnect()
            _ws_manager = None

def get_ws_status():
    from ws_manager import WSManager
    global _ws_manager
    with _ws_lock:
        if _ws_manager is None:
            return WSManager.STATUS_DISCONNECTED
        return _ws_manager.get_status()

def ws_subscribe(symbols):
    global _ws_manager
    with _ws_lock:
        if _ws_manager:
            _ws_manager.subscribe(symbols)


# ══════════════════════════════════════════════════════════════════
#  Strike Filter Helpers (shared data layer)
# ══════════════════════════════════════════════════════════════════
_STRIKE_FILTER_KEY_PREFIX = "strike_filter|"

def strike_filter_key(symbol, expiry):
    return f"{_STRIKE_FILTER_KEY_PREFIX}{symbol}|{expiry}"

def strike_filter_enabled_strikes(symbol, expiry):
    return _get_setting(strike_filter_key(symbol, expiry), [])

def strike_filter_save_strikes(symbol, expiry, strikes):
    from settings_manager import save
    clean = []
    for s in strikes:
        try:
            clean.append(int(float(str(s))))
        except (ValueError, TypeError):
            clean.append(s)
    save({strike_filter_key(symbol, expiry): clean})
