import sys
if sys.stdout.encoding != 'utf-8':
    try: sys.stdout.reconfigure(encoding='utf-8')
    except Exception: pass

from multi_user_trading_manager import multi_user_trader

print("1. Placing virtual order for User 2 (demo_trader1)...")
res = multi_user_trader.place_order(user_id=2, direction="CALL", strike=24700, lots=1, entry_price=120.0, target_pts=18.0, sl_pts=7.5, spot_price=24720.0)
print("Result:", res)

pf = multi_user_trader.get_user_portfolio(user_id=2)
print(f"Active positions: {len(pf['active_positions'])} | Available margin: ₹{pf['available_margin']:,}")

print("2. Closing virtual position at Target ₹138.0 (+18 pts)...")
cls_res = multi_user_trader.close_position(user_id=2, trade_id=res['trade_id'], exit_price=138.0, outcome="TARGET_HIT")
print("Close Result:", cls_res)

pf2 = multi_user_trader.get_user_portfolio(user_id=2)
print(f"New Cash Balance: ₹{pf2['cash_balance']:,} | Realized PnL: ₹{pf2['all_time_realized_pnl']:,} | Win Rate: {pf2['win_rate']}%")
