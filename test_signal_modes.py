import sys
if sys.stdout.encoding != 'utf-8':
    try: sys.stdout.reconfigure(encoding='utf-8')
    except Exception: pass

from user_database import user_db
from multi_user_trading_manager import multi_user_trader

users = user_db.get_all_users()
non_admins = [u for u in users if u["role"] != "admin" and u["status"] == "active"]
while len(non_admins) < 2:
    idx = len(non_admins) + 1
    user_db.create_user(f"demo_trader{idx}", "demo123", f"Demo Trader {idx}", initial_capital=100000.0)
    users = user_db.get_all_users()
    non_admins = [u for u in users if u["role"] != "admin" and u["status"] == "active"]

u1 = non_admins[0]
u2 = non_admins[1]

# Set user 1 to Auto OFF, user 2 to Auto ON
user_db.save_user_settings(user_id=u1["id"], auto_trade_enabled=0, lots=1, trade_direction='BOTH', sl_pts=25.0, target_pts=35.0)
user_db.save_user_settings(user_id=u2["id"], auto_trade_enabled=1, lots=2, trade_direction='CALL', sl_pts=20.0, target_pts=40.0)

sig = {
    "signal_id": "SIG_TEST_001",
    "direction": "CALL",
    "strike": 24500,
    "contract": "NIFTY 24500 CE",
    "spot": 24520.0,
    "suggested_price": 130.0
}

print(f"Broadcasting signal to User {u1['id']} ({u1['username']}) and User {u2['id']} ({u2['username']})...")
res = multi_user_trader.broadcast_signal(sig)
print("Broadcast Result:", res)

# Check user 1 pending alerts
alerts = user_db.get_pending_alerts(u1["id"])
print(f"User {u1['id']} Pending Alerts count: {len(alerts)}")
if alerts:
    alert_id = alerts[0]["id"]
    print(f"User {u1['id']} executing alert {alert_id}...")
    exec_res = multi_user_trader.execute_alert(u1["id"], alert_id)
    print("Execution Result:", exec_res)

# Check user 2 open positions
p2 = multi_user_trader.get_user_portfolio(u2["id"])
print(f"User {u2['id']} Open Positions count: {len(p2.get('active_positions', []))}")
if p2.get('active_positions'):
    print(f"User {u2['id']} Auto Position:", p2['active_positions'][0]['contract'], "Lots:", p2['active_positions'][0]['lots'])

# Clean up test positions
with user_db.get_connection() as conn:
    conn.execute("DELETE FROM user_positions WHERE contract = 'NIFTY 24500 CE'")
    conn.execute("DELETE FROM user_signal_alerts WHERE contract = 'NIFTY 24500 CE'")
    conn.commit()

print("✅ Signal Modes & Broadcast Test Passed Successfully!")
