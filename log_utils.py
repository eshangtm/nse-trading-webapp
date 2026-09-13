import os
import traceback
from datetime import datetime, timedelta

_LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
_ERROR_LOG = os.path.join(_LOG_DIR, "error.log")
_MAX_LOG_SIZE = 5 * 1024 * 1024  # 5 MB
_MAX_ARCHIVE_DAYS = 30

_last_date = None
_counter = 0


def _ensure_log_dir():
    if not os.path.exists(_LOG_DIR):
        os.makedirs(_LOG_DIR, exist_ok=True)


def _rotate_logs():
    """Truncate error.log if over 5 MB; purge archives older than 30 days."""
    _ensure_log_dir()
    if os.path.exists(_ERROR_LOG) and os.path.getsize(_ERROR_LOG) > _MAX_LOG_SIZE:
        with open(_ERROR_LOG, "w", encoding="utf-8") as f:
            f.write(f"[ROTATED] {datetime.now().isoformat()} — log exceeded 5 MB, truncated\n")
    cutoff = datetime.now() - timedelta(days=_MAX_ARCHIVE_DAYS)
    for fname in os.listdir(_LOG_DIR):
        if fname.startswith("error_") and fname.endswith(".log"):
            fpath = os.path.join(_LOG_DIR, fname)
            try:
                mtime = datetime.fromtimestamp(os.path.getmtime(fpath))
                if mtime < cutoff:
                    os.remove(fpath)
            except Exception:
                pass


_rotate_logs()


def cleanup_fyers_logs():
    """Truncate large Fyers library logs at root (fyersRequests.log etc.) if over 10 MB."""
    _root = os.path.dirname(os.path.abspath(__file__))
    for fname in ["fyersRequests.log", "fyersApi.log", "fyersDataSocket.log"]:
        fpath = os.path.join(_root, fname)
        if os.path.exists(fpath) and os.path.getsize(fpath) > 10 * 1024 * 1024:
            try:
                with open(fpath, "w", encoding="utf-8") as f:
                    f.write(f"[ROTATED] {datetime.now().isoformat()} — log exceeded 10 MB, truncated\n")
            except Exception:
                pass


cleanup_fyers_logs()


def _next_id():
    global _last_date, _counter
    today = datetime.now().strftime("%Y%m%d")
    if _last_date != today:
        _last_date = today
        _counter = 0
    _counter += 1
    return f"ERR-{today}-{_counter:03d}"


def log_error(module, function, exception, context=""):
    error_id = _next_id()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    tb = "".join(traceback.format_exception(type(exception), exception, exception.__traceback__))
    exc_type = type(exception).__name__

    lines = [
        f"=== {error_id} ===",
        f"Timestamp : {now}",
        f"Module    : {module}",
        f"Function  : {function}",
        f"Context   : {context}",
        f"Exception : {exc_type}",
        "Traceback :",
        tb.rstrip(),
        "",
    ]
    text = "\n".join(lines)

    _ensure_log_dir()

    with open(_ERROR_LOG, "a", encoding="utf-8") as f:
        f.write(text)

    archive = os.path.join(_LOG_DIR, f"error_{datetime.now().strftime('%Y%m%d')}.log")
    with open(archive, "a", encoding="utf-8") as f:
        f.write(text)

    return error_id

def log_exc(module, function, context=""):
    import sys
    exc = sys.exc_info()[1]
    if exc is None:
        return None
    return log_error(module, function, exc, context)
