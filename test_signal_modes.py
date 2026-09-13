import sys
sys.stdout.reconfigure(encoding='utf-8')
from user_database import user_db
from multi_user_trading_manager import multi_user_trader

# Set user 2 to Auto OFF, user 3 to Auto ON
user_db.save_user_settings(user_id=2, auto_trade_enabled=0, lots=1, trade_direction='BOTH', sl_pts=25.0, target_pts=35.0)
user_db.save_user_settings(user_id=3, auto_trade_enabled=1, lots=2, trade_direction='CALL', sl_pts=20.0, target_pts=40.0)

sig = {
    "signal_id": "SIG_TEST_001",
    "direction": "CALL",
    "strike": 24500,
    "contract": "NIFTY 24500 CE",
    "spot": 24520.0,
    "suggested_price": 130.0
}

print("Broadcasting signal...")
res = multi_user_trader.broadcast_signal(sig)
print("Broadcast Result:", res)

# Check user 2 pending alerts
alerts = user_db.get_pending_alerts(2)
print(f"User 2 Pending Alerts count: {len(alerts)}")
if alerts:
    alert_id = alerts[0]["id"]
    print(f"User 2 executing alert {alert_id}...")
    exec_res = multi_user_trader.execute_alert(2, alert_id)
    print("Execution Result:", exec_res)

# Check user 3 open positions
p3 = multi_user_trader.get_user_portfolio(3)
print(f"User 3 Open Positions count: {len(p3['active_positions'])}")
if p3['active_positions']:
    print("User 3 Auto Position:", p3['active_positions'][0]['contract'], "Lots:", p3['active_positions'][0]['lots'])

# Clean up test positions
with user_db.get_connection() as conn:
    conn.execute("DELETE FROM user_positions WHERE contract = 'NIFTY 24500 CE'")
    conn.execute("DELETE FROM user_signal_alerts WHERE contract = 'NIFTY 24500 CE'")
    conn.commit()
print("Test completed and cleaned successfully!")
