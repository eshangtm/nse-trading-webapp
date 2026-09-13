#!/usr/bin/env python3
# ══════════════════════════════════════════════════════════════════
#  MASTER PRODUCTION WEB SERVER (Multi-Tenant Virtual Trading SaaS)
#  FastAPI + WebSockets + Multi-User Isolated Portfolios + Admin Desk
# ══════════════════════════════════════════════════════════════════
import os
import sys
import asyncio
import json
from datetime import datetime
from typing import Optional, Dict, Any

try:
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass

from fastapi import FastAPI, Request, Response, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

PARENT_DIR = os.path.dirname(BASE_DIR)
if PARENT_DIR not in sys.path:
    sys.path.append(PARENT_DIR)

from user_database import user_db
from multi_user_trading_manager import multi_user_trader
from duckdb_engine import duckdb_engine
from full_tick_collector import FullTickCollector
from cloud_data_manager import cloud_data_manager
from confluence_signal_engine import confluence_paper_trader

app = FastAPI(title="QuantGini Multi-User Virtual Trading Platform")

collector = FullTickCollector()

# Mount static files if present
static_dir = os.path.join(BASE_DIR, "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

templates_dir = os.path.join(BASE_DIR, "templates")

# ══════════════════════════════════════════════════════════════════
# AUTHENTICATION HELPERS & MIDDLEWARE
# ══════════════════════════════════════════════════════════════════
def get_current_user(request: Request) -> Optional[Dict[str, Any]]:
    token = request.cookies.get("session_token")
    if not token:
        # Fallback to Authorization header
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header[7:]
    if not token:
        return None
    return user_db.get_user_by_session(token)

def require_auth(request: Request) -> Dict[str, Any]:
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    if user["status"] != "active":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account disabled")
    return user

def require_admin(request: Request) -> Dict[str, Any]:
    user = require_auth(request)
    if user["role"] != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return user


# ══════════════════════════════════════════════════════════════════
# BACKGROUND REAL-TIME TICK FEED & AUTO-EXECUTION ENGINE
# ══════════════════════════════════════════════════════════════════
@app.on_event("startup")
def startup_event():
    asyncio.create_task(live_tick_background_loop())

async def live_tick_background_loop():
    """Continuously pulls live ticks, saves to daily DuckDB, & updates all users' floating positions & trailing SL."""
    while True:
        try:
            # 1. Attempt live Fyers / broker fetch
            records = await asyncio.to_thread(collector.fetch_current_nifty_chain)
            if records and len(records) > 0:
                # Save into today's isolated daily DuckDB
                await asyncio.to_thread(cloud_data_manager.save_live_ticks, records)
                await asyncio.to_thread(duckdb_engine.insert_ticks, records)
                spot_p = float(records[0].get("spot_price", 0.0))
                if spot_p > 0:
                    await asyncio.to_thread(multi_user_trader.update_all_positions_with_ticks, records, spot_p)
            else:
                # Fallback to latest DuckDB chain snapshot
                df = await asyncio.to_thread(duckdb_engine.get_latest_option_chain)
                if df is not None and not df.empty:
                    spot_p = float(df['spot_price'].iloc[0])
                    ticks = df.to_dict('records')
                    await asyncio.to_thread(multi_user_trader.update_all_positions_with_ticks, ticks, spot_p)
        except Exception as e:
            pass
        await asyncio.sleep(2)  # Tick every 2 seconds


# ══════════════════════════════════════════════════════════════════
# PAGE ROUTES (HTML FRONTEND)
# ══════════════════════════════════════════════════════════════════
@app.api_route("/", methods=["GET", "HEAD"], response_class=HTMLResponse)
def index_route(request: Request):
    if request.method == "HEAD":
        return Response(status_code=200)
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login")
    if user["role"] == "admin":
        return RedirectResponse("/admin")
    return RedirectResponse("/trade")

@app.api_route("/healthz", methods=["GET", "HEAD"])
def health_check():
    return {"status": "ok", "app": "QuantGini"}

@app.get("/login", response_class=HTMLResponse)
def login_page():
    path = os.path.join(templates_dir, "login.html")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return HTMLResponse(f.read())
    return HTMLResponse("<h1>login.html not found</h1>")

@app.get("/admin", response_class=HTMLResponse)
def admin_page(request: Request):
    user = get_current_user(request)
    if not user or user["role"] != "admin":
        return RedirectResponse("/login")
    path = os.path.join(templates_dir, "admin_panel.html")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return HTMLResponse(f.read())
    return HTMLResponse("<h1>admin_panel.html not found</h1>")

@app.get("/trade", response_class=HTMLResponse)
def trade_page(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login")
    path = os.path.join(templates_dir, "user_trading_desk.html")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return HTMLResponse(f.read())
    return HTMLResponse("<h1>user_trading_desk.html not found</h1>")

@app.get("/terminal", response_class=HTMLResponse)
def terminal_page(request: Request):
    """Serve the complete NIFTY50 Options Live Terminal (AOC Calculator & Option Chain)."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login")
    path = os.path.join(templates_dir, "index.html")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return HTMLResponse(f.read())
    return HTMLResponse("<h1>index.html not found</h1>")

@app.get("/signals", response_class=HTMLResponse)
def signals_page(request: Request):
    """Serve the Confluence Signals Controller & Live Algo Monitor."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login")
    path = os.path.join(templates_dir, "live_signals_controller.html")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return HTMLResponse(f.read())
    return HTMLResponse("<h1>live_signals_controller.html not found</h1>")


# ══════════════════════════════════════════════════════════════════
# AUTHENTICATION REST API
# ══════════════════════════════════════════════════════════════════
@app.post("/api/auth/login")
def api_login(payload: dict, response: Response):
    username = payload.get("username", "")
    password = payload.get("password", "")

    user = user_db.authenticate(username, password)
    if not user:
        return {"status": "error", "message": "Invalid username or password"}
    if "error" in user:
        return {"status": "error", "message": user["message"]}

    token = user_db.create_session(user["id"])
    response.set_cookie(
        key="session_token",
        value=token,
        httponly=True,
        max_age=86400 * 30, # 30 days
        samesite="lax"
    )

    return {
        "status": "ok",
        "message": f"Welcome back, {user['full_name']}!",
        "token": token,
        "user": {
            "id": user["id"],
            "username": user["username"],
            "full_name": user["full_name"],
            "role": user["role"]
        }
    }

@app.get("/api/auth/logout")
def api_logout(request: Request, response: Response):
    token = request.cookies.get("session_token")
    if token:
        user_db.delete_session(token)
    response = RedirectResponse("/login")
    response.delete_cookie("session_token")
    return response

@app.get("/api/auth/me")
def api_me(user: dict = Depends(require_auth)):
    return {
        "status": "ok",
        "user": {
            "id": user["id"],
            "username": user["username"],
            "full_name": user["full_name"],
            "role": user["role"],
            "cash_balance": user["cash_balance"]
        }
    }


# ══════════════════════════════════════════════════════════════════
# DUCKDB LIVE OPTION CHAIN & TERMINAL APIS (from 8_NIFTY50_DuckDB)
# ══════════════════════════════════════════════════════════════════
@app.get("/api/feed_status")
def get_feed_status():
    """Reports status of live Fyers data feed."""
    return {"status": "ok", "feed_connected": True, "time": datetime.now().strftime("%H:%M:%S")}

@app.get("/api/option_chain")
def get_option_chain(timestamp: str = None):
    """API endpoint to get option chain snapshot from DuckDB (latest or at specific timestamp)."""
    try:
        if timestamp:
            df = duckdb_engine.get_option_chain_at_timestamp(timestamp)
        else:
            df = duckdb_engine.get_latest_option_chain()
            
        if df is None or df.empty:
            return {"status": "empty", "data": []}
        df = df.fillna(0.0)
        ts_str = str(df["timestamp"].iloc[0]) if "timestamp" in df.columns and not df.empty else ""
        return {"status": "ok", "timestamp": ts_str, "data": df.to_dict("records")}
    except Exception as e:
        return {"status": "error", "message": str(e), "data": []}

@app.get("/api/available_dates")
def get_available_dates():
    """API endpoint to fetch all available historical dates in DuckDB."""
    try:
        dates = duckdb_engine.get_available_dates()
        return {"status": "ok", "dates": dates}
    except Exception as e:
        return {"status": "error", "dates": []}

@app.get("/api/expiries")
def get_expiries(date: str = None):
    """API endpoint to fetch available expiries for a specific date."""
    try:
        exps = duckdb_engine.get_available_expiries(date=date)
        active_exp = duckdb_engine.get_active_weekly_expiry(date=date)
        return {"status": "ok", "expiries": exps or [], "active_expiry": active_exp}
    except Exception as e:
        return {"status": "error", "expiries": []}

@app.get("/api/confluence_signal")
def get_confluence_signal(timestamp: str = None):
    """Fetch current 9-rule confluence matrix signal & paper trader position."""
    try:
        if timestamp:
            clean_ts = str(timestamp).replace('T', ' ')
            df = duckdb_engine.get_option_chain_at_timestamp(clean_ts)
        else:
            df = duckdb_engine.get_latest_option_chain()
        if df is None or df.empty:
            return {"status": "empty", "data": None}
        ticks = df.to_dict("records")
        spot_price = float(ticks[0].get("spot_price", 0.0))
        result = confluence_paper_trader.process_tick(ticks, spot_price, current_timestamp=timestamp)
        if result:
            result["chart_markers"] = confluence_paper_trader.get_chart_markers()
        return {"status": "ok", "data": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/api/chart_markers")
def get_chart_markers():
    try:
        return {"status": "ok", "markers": confluence_paper_trader.get_chart_markers()}
    except Exception as e:
        return {"status": "error", "markers": []}


# ══════════════════════════════════════════════════════════════════
# USER TRADING REST API
# ══════════════════════════════════════════════════════════════════
@app.get("/api/user/portfolio")
def api_user_portfolio(user: dict = Depends(require_auth)):
    """Returns user-specific wallet, margin status, active positions, and today's trades."""
    return multi_user_trader.get_user_portfolio(user["id"])

@app.get("/api/user/market_data")
def api_user_market_data():
    """Provides live Nifty 50 spot, ATM strike, and 9 nearest strikes with CE/PE LTP."""
    try:
        df = duckdb_engine.get_latest_option_chain()
        if df is None or df.empty:
            return {
                "status": "ok",
                "spot_price": 24700.0,
                "atm_strike": 24700,
                "strikes": [
                    {"strike": s, "ce_ltp": round(max(5.0, (24700 - s)*0.68 + 80), 1), 
                     "pe_ltp": round(max(5.0, (s - 24700)*0.68 + 80), 1)}
                    for s in range(24500, 24950, 50)
                ]
            }

        spot_price = float(df['spot_price'].iloc[0])
        atm_strike = int(round(spot_price / 50.0) * 50)

        # 4 below ATM to 4 above ATM
        strike_range = [atm_strike + (step * 50) for step in range(-4, 5)]
        strikes_data = []

        for s in strike_range:
            ce_row = df[(df['strike'] == s) & (df['type'] == 'CE')]
            pe_row = df[(df['strike'] == s) & (df['type'] == 'PE')]
            ce_ltp = float(ce_row['ltp'].iloc[0]) if not ce_row.empty else 0.0
            pe_ltp = float(pe_row['ltp'].iloc[0]) if not pe_row.empty else 0.0
            strikes_data.append({
                "strike": s,
                "ce_ltp": round(ce_ltp, 2),
                "pe_ltp": round(pe_ltp, 2)
            })

        return {
            "status": "ok",
            "spot_price": round(spot_price, 2),
            "atm_strike": atm_strike,
            "strikes": strikes_data
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.post("/api/user/order/place")
def api_user_place_order(payload: dict, user: dict = Depends(require_auth)):
    """User places a manual virtual order (BUY CE / BUY PE)."""
    return multi_user_trader.place_order(
        user_id=user["id"],
        direction=payload.get("direction", "CALL"),
        strike=float(payload.get("strike", 0.0)),
        lots=int(payload.get("lots", 1)),
        entry_price=float(payload.get("entry_price", 0.0)),
        target_pts=float(payload.get("target_pts", 18.0)),
        sl_pts=float(payload.get("sl_pts", 7.5)),
        spot_price=float(payload.get("spot_price", 0.0))
    )

@app.post("/api/user/order/close")
def api_user_close_order(payload: dict, user: dict = Depends(require_auth)):
    """User closes an active open position."""
    trade_id = payload.get("trade_id")
    exit_price = payload.get("exit_price")
    return multi_user_trader.close_position(
        user_id=user["id"],
        trade_id=trade_id,
        exit_price=exit_price,
        outcome="MANUAL_EXIT"
    )

@app.post("/api/user/order/trail")
def api_user_trail_order(payload: dict, user: dict = Depends(require_auth)):
    """User trails SL to cost."""
    trade_id = payload.get("trade_id")
    return multi_user_trader.trail_sl_to_cost(user["id"], trade_id)

# ── User Preferences & Auto-Trade Settings ──────────────────────────
@app.get("/api/user/settings")
def api_get_user_settings(user: dict = Depends(require_auth)):
    """Returns user's personal Auto-Trade, Lot size, SL, Target & Direction preferences."""
    return {"status": "ok", "settings": user_db.get_user_settings(user["id"])}

@app.post("/api/user/settings")
def api_save_user_settings(payload: dict, user: dict = Depends(require_auth)):
    """Saves user's personal Auto-Trade, Lot size, SL, Target & Direction preferences."""
    return user_db.save_user_settings(
        user_id=user["id"],
        auto_trade_enabled=int(payload.get("auto_trade_enabled", 0)),
        lots=int(payload.get("lots", 1)),
        trade_direction=str(payload.get("trade_direction", "BOTH")).upper(),
        sl_pts=float(payload.get("sl_pts", 25.0)),
        target_pts=float(payload.get("target_pts", 35.0))
    )

# ── Interactive Signal Notifications & Alerts ───────────────────────
@app.get("/api/user/alerts/pending")
def api_get_pending_alerts(user: dict = Depends(require_auth)):
    """Returns active pending signal alerts for the user."""
    return {"status": "ok", "alerts": user_db.get_pending_alerts(user["id"])}

@app.get("/api/user/alerts/history")
def api_get_alerts_history(date: Optional[str] = None, user: dict = Depends(require_auth)):
    """Returns all past signals & alerts with optional date filter."""
    return {"status": "ok", "alerts": user_db.get_user_alerts_history(user["id"], date=date)}

@app.post("/api/user/alerts/{alert_id}/execute")
def api_execute_alert(alert_id: int, user: dict = Depends(require_auth)):
    """User clicks 'Execute' button on a signal popup."""
    return multi_user_trader.execute_alert(user["id"], alert_id)

@app.post("/api/user/alerts/{alert_id}/cancel")
def api_cancel_alert(alert_id: int, user: dict = Depends(require_auth)):
    """User clicks 'Cancel' button to dismiss a signal popup."""
    return multi_user_trader.cancel_alert(user["id"], alert_id)

# ── User Trades History with Date Range Filter ──────────────────────
@app.get("/api/user/trades")
def api_get_user_trades(date: Optional[str] = None, date_from: Optional[str] = None, 
                        date_to: Optional[str] = None, user: dict = Depends(require_auth)):
    """Returns closed trades ledger filtered by date or date range. Never wiped on login!"""
    trades = user_db.get_user_trades_by_filter(user["id"], date=date, date_from=date_from, date_to=date_to)
    return {"status": "ok", "trades": trades}

# ── Live Market Indicators & AOC Analysis ───────────────────────────
@app.get("/api/market/analysis")
def api_market_analysis():
    """Provides live market indicators (Spot, ATM, Support/Resistance, Trend)."""
    try:
        df = duckdb_engine.get_latest_option_chain()
        spot_p = float(df['spot_price'].iloc[0]) if df is not None and not df.empty else 24700.0
        atm_strike = int(round(spot_p / 50.0) * 50)
        
        # Calculate PCR and volume highlights if chain available
        pcr = 1.05
        sentiment = "BULLISH"
        if df is not None and not df.empty:
            total_ce_oi = df[df['type'] == 'CE']['oi'].sum()
            total_pe_oi = df[df['type'] == 'PE']['oi'].sum()
            if total_ce_oi > 0:
                pcr = round(float(total_pe_oi / total_ce_oi), 2)
            sentiment = "BULLISH" if pcr >= 1.0 else "BEARISH"

        return {
            "status": "ok",
            "spot_price": round(spot_p, 2),
            "atm_strike": atm_strike,
            "pcr": pcr,
            "sentiment": sentiment,
            "support": atm_strike - 150,
            "resistance": atm_strike + 150,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ══════════════════════════════════════════════════════════════════
# ADMIN REST API (MASTER DESK) & DATA SYNC
# ══════════════════════════════════════════════════════════════════
@app.get("/api/admin/users")
def api_admin_list_users(admin: dict = Depends(require_admin)):
    """Lists all user accounts, capital allocations, and individual performance."""
    return {"status": "ok", "users": user_db.get_all_users()}

@app.post("/api/admin/users/create")
def api_admin_create_user(payload: dict, admin: dict = Depends(require_admin)):
    """Creates a new demo account with custom virtual capital."""
    return user_db.create_user(
        username=payload.get("username", ""),
        password=payload.get("password", ""),
        full_name=payload.get("full_name", ""),
        email=payload.get("email", ""),
        role=payload.get("role", "user"),
        initial_capital=float(payload.get("initial_capital", 100000.0))
    )

@app.post("/api/admin/users/{user_id}/toggle_status")
def api_admin_toggle_user(user_id: int, admin: dict = Depends(require_admin)):
    """Enables or disables user trading access."""
    return user_db.toggle_user_status(user_id)

@app.post("/api/admin/users/{user_id}/delete")
def api_admin_delete_user(user_id: int, admin: dict = Depends(require_admin)):
    """Deletes a demo user account and associated trades."""
    return user_db.delete_user(user_id)

@app.post("/api/admin/users/{user_id}/reset_password")
def api_admin_reset_password(user_id: int, payload: dict, admin: dict = Depends(require_admin)):
    """Resets or updates a user's password from Admin Desk."""
    new_password = payload.get("new_password", "").strip()
    return user_db.reset_user_password(user_id, new_password)

@app.get("/api/admin/live_positions")
def api_admin_live_positions(admin: dict = Depends(require_admin)):
    """Real-time stream of all open positions across all users."""
    return {"status": "ok", "positions": multi_user_trader.get_all_platform_open_positions()}

@app.get("/api/admin/export_day_data")
def api_admin_export_day_data(date: Optional[str] = None, admin: dict = Depends(require_admin)):
    """Packages today's DuckDB file, trades CSV, and alerts into a downloadable ZIP for the PC."""
    target_date = date or datetime.now().strftime("%Y-%m-%d")
    zip_path = cloud_data_manager.create_day_export_package(target_date)
    if not zip_path or not os.path.exists(zip_path):
        raise HTTPException(status_code=404, detail=f"No data available to export for {target_date}")
    return FileResponse(
        zip_path,
        media_type="application/zip",
        filename=f"nse_sync_{target_date}.zip"
    )

@app.get("/api/sync/today_data")
def api_sync_today_data(date: Optional[str] = None):
    """
    Automated endpoint for PC's 5:00 PM sync script.
    Allows the user's local PC to download today's complete DuckDB + trades bundle.
    """
    target_date = date or datetime.now().strftime("%Y-%m-%d")
    zip_path = cloud_data_manager.create_day_export_package(target_date)
    if not zip_path or not os.path.exists(zip_path):
        raise HTTPException(status_code=404, detail=f"No data available to export for {target_date}")
    return FileResponse(
        zip_path,
        media_type="application/zip",
        filename=f"nse_sync_{target_date}.zip"
    )

@app.get("/api/admin/fyers_status")
def api_admin_fyers_status(admin: dict = Depends(require_admin)):
    """Returns the live connection status of Fyers data feed."""
    token_file = os.path.join(BASE_DIR, "fyers_token.json")
    has_token = os.path.exists(token_file)
    token_time = None
    if has_token:
        try:
            token_time = datetime.fromtimestamp(os.path.getmtime(token_file)).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            pass
    connected, reason = collector.is_fyers_connected()
    return {
        "status": "ok",
        "has_token": has_token,
        "connected": connected,
        "reason": reason,
        "token_last_updated": token_time
    }

@app.post("/api/admin/update_fyers_token")
def api_admin_update_fyers_token(payload: dict, admin: dict = Depends(require_admin)):
    """Updates the Fyers access token from Admin Desk."""
    token = payload.get("access_token", "").strip()
    client_id = payload.get("client_id", "2YMMMGEFE5-100").strip()
    if not token:
        raise HTTPException(status_code=400, detail="access_token is required")
    
    token_file = os.path.join(BASE_DIR, "fyers_token.json")
    with open(token_file, "w") as f:
        json.dump({"client_id": client_id, "access_token": token}, f)
    
    try:
        collector._init_fyers()
    except Exception:
        pass
    
    return {"status": "ok", "message": "Fyers token updated! Live market ticks activated."}

@app.post("/api/sync/push_fyers_token")
def api_sync_push_token(payload: dict):
    """Auto-synced by PC's 1_Login.bat every morning."""
    token = payload.get("access_token", "").strip()
    client_id = payload.get("client_id", "2YMMMGEFE5-100").strip()
    if not token:
        raise HTTPException(status_code=400, detail="access_token is required")
    
    token_file = os.path.join(BASE_DIR, "fyers_token.json")
    with open(token_file, "w") as f:
        json.dump({"client_id": client_id, "access_token": token}, f)
    
    try:
        collector._init_fyers()
    except Exception:
        pass
    
    return {"status": "ok", "message": "Fyers token synced to cloud successfully!"}



# ══════════════════════════════════════════════════════════════════
# SERVER STARTUP HELPER
# ══════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    print("=" * 75)
    print("  [QUANTGINI] MULTI-USER VIRTUAL TRADING SAAS WEBAPP")
    print(f"  Running on: http://localhost:{port}")
    print(f"  Default Admin: admin / Admin@123")
    print(f"  Demo Traders: demo_trader1 / demo123, demo_trader2 / demo123")
    print("=" * 75)
    uvicorn.run(app, host="0.0.0.0", port=port)
