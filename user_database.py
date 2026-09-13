# ══════════════════════════════════════════════════════════════════
#  USER & PLATFORM DATABASE MANAGER (Multi-Tenant Virtual Trading)
#  SQLite Database with Persistent User Wallets & Trade Ledgers
# ══════════════════════════════════════════════════════════════════
import os
import sqlite3
import hashlib
import secrets
from datetime import datetime
from typing import Dict, List, Any, Optional

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)

DB_PATH = os.path.join(DATA_DIR, "trading_platform.db")

def hash_password(password: str, salt: str = None) -> tuple:
    """Secure password hashing with random salt using SHA-256."""
    if not salt:
        salt = secrets.token_hex(16)
    salted = f"{salt}:{password}".encode('utf-8')
    pwd_hash = hashlib.sha256(salted).hexdigest()
    return pwd_hash, salt

def verify_password(password: str, stored_hash: str, salt: str) -> bool:
    """Verify password against stored hash."""
    pwd_hash, _ = hash_password(password, salt)
    return secrets.compare_digest(pwd_hash, stored_hash)


class UserDatabase:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._init_db()
        self._seed_default_accounts()

    def get_connection(self):
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self.get_connection() as conn:
            # 1. Users table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    salt TEXT NOT NULL,
                    full_name TEXT NOT NULL,
                    email TEXT,
                    role TEXT NOT NULL DEFAULT 'user', -- 'admin' or 'user'
                    status TEXT NOT NULL DEFAULT 'active', -- 'active' or 'disabled'
                    initial_capital REAL NOT NULL DEFAULT 100000.0,
                    cash_balance REAL NOT NULL DEFAULT 100000.0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)

            # 2. User Active Positions table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS user_positions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trade_id TEXT UNIQUE NOT NULL,
                    user_id INTEGER NOT NULL,
                    timestamp TEXT NOT NULL,
                    direction TEXT NOT NULL, -- 'CALL' or 'PUT'
                    option_type TEXT NOT NULL, -- 'CE' or 'PE'
                    contract TEXT NOT NULL,
                    strike REAL NOT NULL,
                    lots INTEGER NOT NULL,
                    quantity INTEGER NOT NULL,
                    entry_spot REAL NOT NULL,
                    entry_price REAL NOT NULL,
                    current_ltp REAL NOT NULL,
                    stop_loss_price REAL NOT NULL,
                    initial_sl_price REAL NOT NULL,
                    target_price REAL NOT NULL,
                    peak_pts REAL NOT NULL DEFAULT 0.0,
                    trailed_to_cost INTEGER NOT NULL DEFAULT 0,
                    tsl_stage TEXT NOT NULL DEFAULT 'INITIAL',
                    live_pnl_rupees REAL NOT NULL DEFAULT 0.0,
                    live_pnl_pct REAL NOT NULL DEFAULT 0.0,
                    status TEXT NOT NULL DEFAULT 'OPEN',
                    FOREIGN KEY (user_id) REFERENCES users (id)
                );
            """)

            # 3. User Closed Trades Ledger
            conn.execute("""
                CREATE TABLE IF NOT EXISTS user_trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trade_id TEXT UNIQUE NOT NULL,
                    user_id INTEGER NOT NULL,
                    entry_timestamp TEXT NOT NULL,
                    exit_timestamp TEXT NOT NULL,
                    date TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    option_type TEXT NOT NULL,
                    contract TEXT NOT NULL,
                    strike REAL NOT NULL,
                    lots INTEGER NOT NULL,
                    quantity INTEGER NOT NULL,
                    entry_spot REAL NOT NULL,
                    entry_price REAL NOT NULL,
                    exit_spot REAL NOT NULL,
                    exit_price REAL NOT NULL,
                    exit_reason TEXT NOT NULL,
                    pnl_pts REAL NOT NULL,
                    gross_pnl REAL NOT NULL,
                    brokerage REAL NOT NULL,
                    net_pnl REAL NOT NULL,
                    pnl_pct REAL NOT NULL,
                    status TEXT NOT NULL DEFAULT 'CLOSED',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (id)
                );
            """)

            # 4. Sessions table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS user_sessions (
                    token TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (id)
                );
            """)

            # 5. User Auto-Trading & Preference Settings table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS user_settings (
                    user_id INTEGER PRIMARY KEY,
                    auto_trade_enabled INTEGER NOT NULL DEFAULT 0,
                    lots INTEGER NOT NULL DEFAULT 1,
                    trade_direction TEXT NOT NULL DEFAULT 'BOTH', -- 'BOTH', 'CALL', 'PUT'
                    sl_pts REAL NOT NULL DEFAULT 25.0,
                    target_pts REAL NOT NULL DEFAULT 35.0,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (id)
                );
            """)

            # 6. Interactive Signal Notifications / Alerts table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS user_signal_alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    signal_id TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    direction TEXT NOT NULL, -- 'CALL' or 'PUT'
                    option_type TEXT NOT NULL, -- 'CE' or 'PE'
                    strike REAL NOT NULL,
                    contract TEXT NOT NULL,
                    spot REAL NOT NULL,
                    suggested_price REAL NOT NULL,
                    target_price REAL NOT NULL,
                    sl_price REAL NOT NULL,
                    lots INTEGER NOT NULL DEFAULT 1,
                    status TEXT NOT NULL DEFAULT 'PENDING', -- 'PENDING', 'EXECUTED', 'CANCELLED', 'EXPIRED'
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (id)
                );
            """)
            conn.commit()

    def _seed_default_accounts(self):
        """Seed default admin and demo user accounts if database is empty."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM users")
            if cursor.fetchone()[0] == 0:
                # Seed Admin
                pwd_hash, salt = hash_password("Admin@123")
                cursor.execute("""
                    INSERT INTO users (username, password_hash, salt, full_name, email, role, status, initial_capital, cash_balance)
                    VALUES (?, ?, ?, ?, ?, 'admin', 'active', 1000000.0, 1000000.0)
                """, ("admin", pwd_hash, salt, "Master Administrator", "admin@nseplatform.local"))

                # Seed Demo User 1
                pwd_hash1, salt1 = hash_password("demo123")
                cursor.execute("""
                    INSERT INTO users (username, password_hash, salt, full_name, email, role, status, initial_capital, cash_balance)
                    VALUES (?, ?, ?, ?, ?, 'user', 'active', 100000.0, 100000.0)
                """, ("demo_trader1", pwd_hash1, salt1, "Demo Trader 1", "demo1@nseplatform.local"))

                # Seed Demo User 2
                pwd_hash2, salt2 = hash_password("demo123")
                cursor.execute("""
                    INSERT INTO users (username, password_hash, salt, full_name, email, role, status, initial_capital, cash_balance)
                    VALUES (?, ?, ?, ?, ?, 'user', 'active', 200000.0, 200000.0)
                """, ("demo_trader2", pwd_hash2, salt2, "Demo Trader 2", "demo2@nseplatform.local"))
                conn.commit()
                print("Default accounts successfully seeded: admin, demo_trader1, demo_trader2")

    # ══════════════════════════════════════════════════════════════════
    # USER CRUD OPERATIONS
    # ══════════════════════════════════════════════════════════════════
    def create_user(self, username: str, password: str, full_name: str, 
                    email: str = "", role: str = "user", initial_capital: float = 100000.0) -> Dict[str, Any]:
        username = username.strip().lower()
        if not username or not password:
            return {"status": "error", "message": "Username and password cannot be empty"}

        pwd_hash, salt = hash_password(password)
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO users (username, password_hash, salt, full_name, email, role, status, initial_capital, cash_balance)
                    VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?)
                """, (username, pwd_hash, salt, full_name, email, role, initial_capital, initial_capital))
                conn.commit()
                user_id = cursor.lastrowid
                return {
                    "status": "ok",
                    "message": f"User '{username}' successfully created",
                    "user": {"id": user_id, "username": username, "full_name": full_name, "role": role, "initial_capital": initial_capital}
                }
        except sqlite3.IntegrityError:
            return {"status": "error", "message": f"Username '{username}' already exists"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def authenticate(self, username: str, password: str) -> Optional[Dict[str, Any]]:
        username = username.strip().lower()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE username = ?", (username,))
            row = cursor.fetchone()
            if not row:
                return None
            if row["status"] != "active":
                return {"error": "ACCOUNT_DISABLED", "message": "Your account has been disabled by the Administrator"}
            if verify_password(password, row["password_hash"], row["salt"]):
                return dict(row)
            return None

    def create_session(self, user_id: int) -> str:
        token = secrets.token_hex(32)
        with self.get_connection() as conn:
            conn.execute("INSERT INTO user_sessions (token, user_id) VALUES (?, ?)", (token, user_id))
            conn.commit()
        return token

    def get_user_by_session(self, token: str) -> Optional[Dict[str, Any]]:
        if not token:
            return None
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT u.* FROM users u
                JOIN user_sessions s ON u.id = s.user_id
                WHERE s.token = ?
            """, (token,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def delete_session(self, token: str):
        with self.get_connection() as conn:
            conn.execute("DELETE FROM user_sessions WHERE token = ?", (token,))
            conn.commit()

    def get_all_users(self) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT u.id, u.username, u.full_name, u.email, u.role, u.status, 
                       u.initial_capital, u.cash_balance, u.created_at,
                       COUNT(DISTINCT p.id) as open_positions_count,
                       COUNT(DISTINCT t.id) as total_trades_count,
                       COALESCE(SUM(t.net_pnl), 0.0) as realized_pnl
                FROM users u
                LEFT JOIN user_positions p ON u.id = p.user_id AND p.status = 'OPEN'
                LEFT JOIN user_trades t ON u.id = t.user_id
                GROUP BY u.id
                ORDER BY u.id ASC
            """)
            return [dict(r) for r in cursor.fetchall()]

    def get_user_by_id(self, user_id: int) -> Optional[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def update_user_capital(self, user_id: int, new_capital: float) -> Dict[str, Any]:
        with self.get_connection() as conn:
            conn.execute("UPDATE users SET cash_balance = ?, initial_capital = ? WHERE id = ?", (new_capital, new_capital, user_id))
            conn.commit()
        return {"status": "ok", "message": f"Capital updated to ₹{new_capital:,.2f}"}

    def toggle_user_status(self, user_id: int) -> Dict[str, Any]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT status FROM users WHERE id = ?", (user_id,))
            row = cursor.fetchone()
            if not row:
                return {"status": "error", "message": "User not found"}
            new_status = "disabled" if row["status"] == "active" else "active"
            cursor.execute("UPDATE users SET status = ? WHERE id = ?", (new_status, user_id))
            conn.commit()
            return {"status": "ok", "new_status": new_status}

    def delete_user(self, user_id: int) -> Dict[str, Any]:
        with self.get_connection() as conn:
            conn.execute("DELETE FROM user_positions WHERE user_id = ?", (user_id,))
            conn.execute("DELETE FROM user_trades WHERE user_id = ?", (user_id,))
            conn.execute("DELETE FROM user_sessions WHERE user_id = ?", (user_id,))
            conn.execute("DELETE FROM user_settings WHERE user_id = ?", (user_id,))
            conn.execute("DELETE FROM user_signal_alerts WHERE user_id = ?", (user_id,))
            conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
            conn.commit()
        return {"status": "ok", "message": "User deleted successfully"}

    # ── User Preferences & Auto-Trading Settings ─────────────────────
    def get_user_settings(self, user_id: int) -> Dict[str, Any]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM user_settings WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()
            if row:
                return dict(row)
            # Default settings if none saved yet
            cursor.execute("""
                INSERT OR IGNORE INTO user_settings (user_id, auto_trade_enabled, lots, trade_direction, sl_pts, target_pts)
                VALUES (?, 0, 1, 'BOTH', 25.0, 35.0)
            """, (user_id,))
            conn.commit()
            return {
                "user_id": user_id,
                "auto_trade_enabled": 0,
                "lots": 1,
                "trade_direction": "BOTH",
                "sl_pts": 25.0,
                "target_pts": 35.0
            }

    def save_user_settings(self, user_id: int, auto_trade_enabled: int, lots: int, trade_direction: str, sl_pts: float, target_pts: float) -> Dict[str, Any]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO user_settings (user_id, auto_trade_enabled, lots, trade_direction, sl_pts, target_pts, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(user_id) DO UPDATE SET
                    auto_trade_enabled=excluded.auto_trade_enabled,
                    lots=excluded.lots,
                    trade_direction=excluded.trade_direction,
                    sl_pts=excluded.sl_pts,
                    target_pts=excluded.target_pts,
                    updated_at=CURRENT_TIMESTAMP
            """, (user_id, int(auto_trade_enabled), max(1, int(lots)), str(trade_direction).upper(), float(sl_pts), float(target_pts)))
            conn.commit()
        return {"status": "ok", "message": "Settings saved successfully"}

    # ── User Signal Notifications & Alerts ───────────────────────────
    def create_signal_alert(self, user_id: int, alert_data: Dict[str, Any]) -> int:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO user_signal_alerts (
                    user_id, signal_id, timestamp, direction, option_type, 
                    strike, contract, spot, suggested_price, target_price, sl_price, lots, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING')
            """, (
                user_id,
                alert_data["signal_id"],
                alert_data.get("timestamp", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
                alert_data["direction"],
                alert_data["option_type"],
                float(alert_data["strike"]),
                alert_data["contract"],
                float(alert_data.get("spot", 0.0)),
                float(alert_data.get("suggested_price", 0.0)),
                float(alert_data.get("target_price", 0.0)),
                float(alert_data.get("sl_price", 0.0)),
                int(alert_data.get("lots", 1))
            ))
            conn.commit()
            return cursor.lastrowid

    def get_pending_alerts(self, user_id: int) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM user_signal_alerts 
                WHERE user_id = ? AND status = 'PENDING'
                ORDER BY id DESC
            """, (user_id,))
            return [dict(r) for r in cursor.fetchall()]

    def update_alert_status(self, alert_id: int, user_id: int, status: str) -> bool:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE user_signal_alerts SET status = ?
                WHERE id = ? AND user_id = ?
            """, (status, alert_id, user_id))
            conn.commit()
            return cursor.rowcount > 0

    def get_alert_by_id(self, alert_id: int, user_id: int) -> Optional[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM user_signal_alerts WHERE id = ? AND user_id = ?", (alert_id, user_id))
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_user_trades_by_filter(self, user_id: int, date: Optional[str] = None, 
                                   date_from: Optional[str] = None, date_to: Optional[str] = None, 
                                   limit: int = 150) -> List[Dict[str, Any]]:
        """Fetch trades for a user with persistent date filters so history is never lost."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            query = "SELECT * FROM user_trades WHERE user_id = ?"
            params: List[Any] = [user_id]

            if date:
                query += " AND date = ?"
                params.append(date)
            elif date_from and date_to:
                query += " AND date BETWEEN ? AND ?"
                params.extend([date_from, date_to])
            elif date_from:
                query += " AND date >= ?"
                params.append(date_from)
            elif date_to:
                query += " AND date <= ?"
                params.append(date_to)

            query += " ORDER BY id DESC LIMIT ?"
            params.append(limit)

            cursor.execute(query, params)
            return [dict(r) for r in cursor.fetchall()]

    def get_user_alerts_history(self, user_id: int, date: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        """Fetch full signal alerts history for a user with persistent date filter."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if date:
                cursor.execute("""
                    SELECT * FROM user_signal_alerts 
                    WHERE user_id = ? AND timestamp LIKE ?
                    ORDER BY id DESC LIMIT ?
                """, (user_id, f"{date}%", limit))
            else:
                cursor.execute("""
                    SELECT * FROM user_signal_alerts 
                    WHERE user_id = ?
                    ORDER BY id DESC LIMIT ?
                """, (user_id, limit))
            return [dict(r) for r in cursor.fetchall()]

    def get_day_export_summary(self, date_str: str) -> Dict[str, Any]:
        """Export all trades, positions, and alerts across all users for a given day."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT t.*, u.username, u.full_name 
                FROM user_trades t
                JOIN users u ON t.user_id = u.id
                WHERE t.date = ?
                ORDER BY t.id ASC
            """, (date_str,))
            trades = [dict(r) for r in cursor.fetchall()]

            cursor.execute("""
                SELECT a.*, u.username 
                FROM user_signal_alerts a
                JOIN users u ON a.user_id = u.id
                WHERE a.timestamp LIKE ?
                ORDER BY a.id ASC
            """, (f"{date_str}%",))
            alerts = [dict(r) for r in cursor.fetchall()]

            return {
                "date": date_str,
                "exported_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "total_trades": len(trades),
                "total_alerts": len(alerts),
                "trades": trades,
                "alerts": alerts
            }

user_db = UserDatabase()
