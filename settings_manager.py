import json, os, shutil, sys, time
from datetime import datetime
from log_utils import log_error


class _SafeEncoder(json.JSONEncoder):
    def default(self, o):
        try:
            if hasattr(o, 'item'):
                return o.item()
            return float(o)
        except (TypeError, ValueError):
            return str(o)

SETTINGS_PATH = r"C:\nse_tool\settings.json"

DEFAULTS = {
    "strike_range_default": "ATM \u00b120",
    "validation_15m_minutes": 15,
    "validation_15m_threshold_pct": 0.3,
    "validation_30m_minutes": 30,
    "validation_30m_threshold_pct": 0.5,
    "validation_60m_minutes": 60,
    "validation_60m_threshold_pct": 0.7,
    "notifications_enabled": True,
    "signal_retention_days": 30,
    "polling_interval_sec": 15,
    "auto_refresh_interval_sec": 30,
    "signal_mode": "Fast",
}

_cache = None
_save_errors = []


def _log(msg):
    print(f"[settings_manager] {msg}", file=sys.stderr)


def _atomic_save():
    global _cache, _save_errors
    if _cache is None:
        _cache = dict(DEFAULTS)

    tmp = SETTINGS_PATH + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_cache, f, indent=2, ensure_ascii=False, cls=_SafeEncoder)

        with open(tmp, "r", encoding="utf-8") as f:
            json.load(f)

        for attempt in range(3):
            try:
                os.replace(tmp, SETTINGS_PATH)
                return
            except OSError:
                if attempt < 2:
                    time.sleep(0.05)
    except Exception as e:
        err_id = log_error("settings_manager", "_atomic_save", e,
                           f"path={SETTINGS_PATH}")
        _log(f"Save failed | Error ID: {err_id} | {e}")
        _save_errors.append({
            "error_id": err_id,
            "message": f"Settings could not be saved ({type(e).__name__}). "
                       f"Changes will remain active until the application is closed.",
        })
    finally:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass


def pop_errors():
    global _save_errors
    out = list(_save_errors)
    _save_errors = []
    return out


def _backup_corrupted(path, error):
    try:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        bak = f"{path}.bak.{ts}"
        shutil.copy2(path, bak)
        _log(f"Corrupt settings backed up to: {bak}")
    except Exception as e:
        _log(f"Backup creation failed: {e}")


def load():
    global _cache
    if _cache is not None:
        return _cache

    if os.path.exists(SETTINGS_PATH):
        try:
            with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
                stored = json.load(f)
            _cache = {**DEFAULTS, **stored}
            return _cache
        except (json.JSONDecodeError, Exception) as e:
            err_id = log_error("settings_manager", "load", e,
                               f"path={SETTINGS_PATH}")
            _log(f"Corrupt settings.json | Error ID: {err_id} | {e}")
            _backup_corrupted(SETTINGS_PATH, e)

    _log("Using default settings")
    _cache = dict(DEFAULTS)
    _atomic_save()
    return _cache


def save(updates=None):
    global _cache
    if _cache is None:
        load()
    if updates:
        _cache.update(updates)
    _atomic_save()


def get(key, default=None):
    s = load()
    return s.get(key, default)


def set(key, value):
    save({key: value})
