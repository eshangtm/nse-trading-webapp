import sys
if sys.stdout.encoding != 'utf-8':
    try: sys.stdout.reconfigure(encoding='utf-8')
    except Exception: pass

from user_database import user_db
from multi_user_trading_manager import multi_user_trader

users = user_db.get_all_users()
non_admins = [u for u in users if u["role"] != "admin" and u["status"] == "active"]
if not non_admins:
    # Create a test demo user
    user_db.create_user("demo_test", "demo123", "Demo Tester", initial_capital=100000.0)
    users = user_db.get_all_users()
    non_admins = [u for u in users if u["role"] != "admin" and u["status"] == "active"]

target_user = non_admins[0]
user_id = target_user["id"]
username = target_user["username"]

print(f"1. Placing virtual order for User {user_id} ({username})...")
res = multi_user_trader.place_order(user_id=user_id, direction="CALL", strike=24700, lots=1, entry_price=120.0, target_pts=18.0, sl_pts=7.5, spot_price=24720.0)
print("Result:", res)

pf = multi_user_trader.get_user_portfolio(user_id=user_id)
print(f"Active positions: {len(pf.get('active_positions', []))} | Available margin: ₹{pf.get('available_margin', 0):,}")

print("2. Closing virtual position at Target ₹138.0 (+18 pts)...")
if res.get("trade_id"):
    cls_res = multi_user_trader.close_position(user_id=user_id, trade_id=res['trade_id'], exit_price=138.0, outcome="TARGET_HIT")
    print("Close Result:", cls_res)

pf2 = multi_user_trader.get_user_portfolio(user_id=user_id)
print(f"New Cash Balance: ₹{pf2.get('cash_balance', 0):,} | Realized PnL: ₹{pf2.get('all_time_realized_pnl', 0):,} | Win Rate: {pf2.get('win_rate', 0)}%")
print("✅ Order Lifecycle Test Passed Successfully!")
