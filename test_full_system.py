import sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

from fastapi.testclient import TestClient
from server import app

# Use a single TestClient instance
client = TestClient(app)

print('--- 1. Testing Health & Public Pages ---')
assert client.get('/healthz').json()['status'] == 'ok'
assert client.get('/login').status_code == 200
print('[PASS] Health & Login page')

print('--- 2. Testing Admin Authentication & Controls ---')
admin_login = client.post('/api/auth/login', json={'username': 'admin', 'password': 'Admin@123'})
assert admin_login.status_code == 200, f'Admin login failed: {admin_login.text}'
assert client.get('/admin').status_code == 200
users_res = client.get('/api/admin/users').json()
assert users_res.get('status') == 'ok' and len(users_res.get('users', [])) > 0
assert client.get('/api/admin/live_positions').json().get('status') == 'ok'
assert client.get('/api/admin/fyers_status').json().get('status') == 'ok'
print(f'[PASS] Admin portal & management APIs ({len(users_res["users"])} users loaded)')

print('--- 3. Testing User Authentication & Trading Desk ---')
user_login = client.post('/api/auth/login', json={'username': 'somd', 'password': 'mypassword789'})
assert user_login.status_code == 200, f'User login failed: {user_login.text}'
assert client.get('/trade').status_code == 200
portfolio = client.get('/api/user/portfolio').json()
assert portfolio.get('status') == 'ok'
mdata = client.get('/api/user/market_data').json()
assert mdata.get('status') == 'ok' and 'spot_price' in mdata
analysis = client.get('/api/market/analysis').json()
assert analysis.get('status') == 'ok' and 'sentiment' in analysis
print(f'[PASS] User trading desk APIs (Spot: {mdata["spot_price"]}, Sentiment: {analysis["sentiment"]})')

print('--- 4. Testing Live Signal Desk & Wallet ---')
sig_status = client.get('/api/signals/status').json()
assert 'master_switch' in sig_status
wallet = client.get('/api/signals/wallet').json()
assert 'cash_balance' in wallet
trades = client.get('/api/signals/trades').json()
assert trades.get('status') == 'ok'
test_sig = client.post('/api/signals/test_trigger', json={'direction': 'CALL'}).json()
assert test_sig.get('status') == 'ok' and 'signal' in test_sig
print(f'[PASS] Live Signal Engine & Virtual Wallet (Active: {test_sig["signal"]["contract"]})')

print('--- 5. Testing Terminal & DuckDB Chart Feeds ---')
assert client.get('/terminal').status_code == 200
candles = client.get('/api/candles?symbol=SPOT&interval=60').json()
assert candles.get('status') == 'ok'
ts = client.get('/api/timestamps?date=2026-09-15').json()
assert ts.get('status') == 'ok'
aoc = client.get('/api/aoc_sr').json()
assert 'status' in aoc
tot = client.get('/api/tot_decision').json()
assert 'status' in tot
print('[PASS] Terminal charts, candles, AOC S/R, and TOT decision engines')

print('\n=============================================================')
print('  🎉 ALL 5 CORE SYSTEM INTEGRATION CHECKS PASSED WITH 100% SUCCESS!')
print('=============================================================')
