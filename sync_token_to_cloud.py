#!/usr/bin/env python3
# ══════════════════════════════════════════════════════════════════
#  Sync Local Fyers Token to Cloud WebApp (Render.com)
#  Ensures online webapp stays connected to live market ticks
# ══════════════════════════════════════════════════════════════════
import os
import sys
import json
import time

try:
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

CLOUD_PUSH_URL = "https://nse-trading-webapp.onrender.com/api/sync/push_fyers_token"
CLOUD_HEALTH_URL = "https://nse-trading-webapp.onrender.com/healthz"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(BASE_DIR)

TOKEN_CANDIDATES = [
    os.path.join(BASE_DIR, "fyers_token.json"),
    r"C:\nse_tool\fyers_token.json",
    os.path.join(PARENT_DIR, "fyers_token.json"),
]

def find_active_token():
    """Find the freshest valid fyers_token.json file on this PC."""
    freshest_path = None
    freshest_mtime = 0
    freshest_data = None

    for path in TOKEN_CANDIDATES:
        if os.path.exists(path):
            try:
                mtime = os.path.getmtime(path)
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if data.get("access_token"):
                    if mtime > freshest_mtime or freshest_data is None:
                        freshest_mtime = mtime
                        freshest_path = path
                        freshest_data = data
            except Exception:
                continue

    return freshest_path, freshest_data


def sync_token_to_cloud(silent=False, max_retries=3):
    """Robustly sync local Fyers token to the Render Cloud WebApp."""
    token_path, token_data = find_active_token()

    if not token_data:
        if not silent:
            print("❌ Koi valid Fyers access token nahi mila!")
            print("   Pehle '1_Login.bat' chala kar Fyers me login karein.")
        return False

    client_id = token_data.get("client_id", "2YMMMGEFE5-100")
    access_token = token_data.get("access_token")

    if not silent:
        print(f"[*] Found local token: {token_path}")
        print(f"[*] Target Cloud WebApp: {CLOUD_PUSH_URL}")
        print("[*] Connecting and syncing token with Cloud server...")

    # Try requests first, fallback to urllib
    try:
        import requests
        has_requests = True
    except ImportError:
        has_requests = False

    payload = json.dumps({"client_id": client_id, "access_token": access_token}).encode("utf-8")
    headers = {"Content-Type": "application/json"}

    timeouts = [15, 25, 45]  # Render cold start can take 30+ seconds

    for attempt in range(1, max_retries + 1):
        timeout = timeouts[min(attempt - 1, len(timeouts) - 1)]
        try:
            if not silent and attempt > 1:
                print(f"[*] Retrying sync (attempt {attempt}/{max_retries}, timeout {timeout}s)...")

            if has_requests:
                resp = requests.post(CLOUD_PUSH_URL, data=payload, headers=headers, timeout=timeout)
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("status") == "ok":
                        if not silent:
                            print("=" * 70)
                            print("✅ SUCCESS: Fyers Live Token Cloud WebApp par sync ho gaya!")
                            print("🌐 Online WebApp: https://nse-trading-webapp.onrender.com")
                            print("=" * 70)
                        return True
            else:
                import urllib.request
                req = urllib.request.Request(CLOUD_PUSH_URL, data=payload, headers=headers)
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    if resp.status == 200:
                        body = json.loads(resp.read().decode("utf-8"))
                        if body.get("status") == "ok":
                            if not silent:
                                print("=" * 70)
                                print("✅ SUCCESS: Fyers Live Token Cloud WebApp par sync ho gaya!")
                                print("🌐 Online WebApp: https://nse-trading-webapp.onrender.com")
                                print("=" * 70)
                            return True

        except Exception as e:
            if attempt < max_retries:
                time.sleep(3)
            else:
                if not silent:
                    print(f"⚠️ Cloud sync attempt {attempt} failed: {e}")
                    print("ℹ️ Tip: Check internet connection or make sure Cloud WebApp is up.")

    return False


if __name__ == "__main__":
    silent_mode = "--silent" in sys.argv
    success = sync_token_to_cloud(silent=silent_mode)
    if not silent_mode:
        if not success:
            sys.exit(1)
        sys.exit(0)
