# ══════════════════════════════════════════════════════════════════
#  CLOUD DATA MANAGER (Daily DuckDB Storage & Cloud-to-PC Sync)
#  Records daily live streaming ticks into per-day DuckDB files,
#  and provides packaging for 1-Click "Send to PC" & 5:00 PM auto-sync
# ══════════════════════════════════════════════════════════════════
import os
import csv
import json
import zipfile
import duckdb
from datetime import datetime
from typing import Dict, List, Any, Optional

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)

from user_database import user_db

class CloudDataManager:
    def __init__(self, data_dir: str = DATA_DIR):
        self.data_dir = data_dir

    def get_day_duckdb_path(self, date_str: str) -> str:
        """Returns the DuckDB file path for a specific trading date."""
        return os.path.join(self.data_dir, f"ticks_{date_str}.duckdb")

    def save_live_ticks(self, records: List[Dict[str, Any]]) -> None:
        """Saves incoming live market ticks into today's isolated DuckDB database."""
        if not records:
            return
        today_str = datetime.now().strftime("%Y-%m-%d")
        db_path = self.get_day_duckdb_path(today_str)

        try:
            conn = duckdb.connect(db_path)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS ticks (
                    timestamp TIMESTAMP,
                    symbol VARCHAR,
                    strike DOUBLE,
                    type VARCHAR,
                    ltp DOUBLE,
                    oi BIGINT,
                    volume BIGINT,
                    iv DOUBLE,
                    spot_price DOUBLE,
                    dte DOUBLE,
                    bid_price DOUBLE,
                    ask_price DOUBLE,
                    bid_qty INTEGER,
                    ask_qty INTEGER
                )
            """)

            # Prepare rows
            rows = []
            for r in records:
                # Format timestamp
                ts = r.get("timestamp") or datetime.now()
                if isinstance(ts, str):
                    try:
                        ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    except Exception:
                        ts = datetime.now()

                rows.append((
                    ts,
                    str(r.get("symbol", "")),
                    float(r.get("strike", 0.0)),
                    str(r.get("type", "")),
                    float(r.get("ltp", 0.0)),
                    int(r.get("oi", 0) or 0),
                    int(r.get("volume", 0) or 0),
                    float(r.get("iv", 0.0) or 0.0),
                    float(r.get("spot_price", 0.0) or 0.0),
                    float(r.get("dte", 0.0) or 0.0),
                    float(r.get("bid_price", 0.0) or 0.0),
                    float(r.get("ask_price", 0.0) or 0.0),
                    int(r.get("bid_qty", 0) or 0),
                    int(r.get("ask_qty", 0) or 0)
                ))

            if rows:
                conn.executemany("INSERT INTO ticks VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
            conn.close()
        except Exception as e:
            print(f"[CloudDataManager] Error saving live ticks to {db_path}: {e}")

    def create_day_export_package(self, date_str: str) -> Optional[str]:
        """
        Packages today's DuckDB file, trades CSV, and alerts JSON into a zip
        file for 'Send to PC' / 5:00 PM transfer.
        """
        zip_filename = f"nse_sync_{date_str}.zip"
        zip_path = os.path.join(self.data_dir, zip_filename)

        duckdb_file = self.get_day_duckdb_path(date_str)
        day_summary = user_db.get_day_export_summary(date_str)

        # Temporary CSV path
        csv_path = os.path.join(self.data_dir, f"trades_{date_str}.csv")
        alerts_path = os.path.join(self.data_dir, f"alerts_{date_str}.json")

        # 1. Write Trades CSV
        trades = day_summary.get("trades", [])
        if trades:
            fieldnames = list(trades[0].keys())
            with open(csv_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(trades)
        else:
            with open(csv_path, "w", newline="", encoding="utf-8") as f:
                f.write("No trades recorded for this date.\n")

        # 2. Write Alerts JSON
        with open(alerts_path, "w", encoding="utf-8") as f:
            json.dump(day_summary.get("alerts", []), f, indent=2)

        # 3. Create ZIP archive
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            if os.path.exists(duckdb_file):
                zf.write(duckdb_file, arcname=f"ticks_{date_str}.duckdb")
            if os.path.exists(csv_path):
                zf.write(csv_path, arcname=f"trades_{date_str}.csv")
            if os.path.exists(alerts_path):
                zf.write(alerts_path, arcname=f"alerts_{date_str}.json")

        # Clean temp files
        for p in (csv_path, alerts_path):
            if os.path.exists(p):
                try:
                    os.remove(p)
                except Exception:
                    pass

        return zip_path if os.path.exists(zip_path) else None

cloud_data_manager = CloudDataManager()
