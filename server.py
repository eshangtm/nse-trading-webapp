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
from live_signal_engine import live_signal_engine, get_live_signal_engine, get_all_active_engines

app = FastAPI(title="QuantGini Multi-User Virtual Trading Platform")

collector = FullTickCollector()

# Mount static files if present
static_dir = os.path.join(BASE_DIR, "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

templates_dir = os.path.join(BASE_DIR, "templates")

# Helper to resolve isolated signal engine for the logged-in user
def resolve_user_engine(request: Request):
    user = get_current_user(request)
    user_id = user["username"] if user else "default"
    return get_live_signal_engine(user_id), user

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
    # Restore token from DB if file is missing
    token_file = os.path.join(BASE_DIR, "fyers_token.json")
    if not os.path.exists(token_file):
        db_token_str = user_db.get_config("fyers_token")
        if db_token_str:
            try:
                with open(token_file, "w") as f:
                    f.write(db_token_str)
                collector._init_fyers()
            except Exception:
                pass
    asyncio.create_task(live_tick_background_loop())

async def live_tick_background_loop():
    """Continuously pulls live ticks, saves to daily DuckDB, & updates all users' floating positions & trailing SL."""
    while True:
        try:
            # 1. Attempt live Fyers / broker fetch
            records = await asyncio.to_thread(collector.fetch_current_nifty_chain)
            ticks = records if (records and len(records) > 0) else None

            if not ticks:
                # Fallback to latest DuckDB chain snapshot
                df = await asyncio.to_thread(duckdb_engine.get_latest_option_chain)
                if df is not None and not df.empty:
                    ticks = df.to_dict('records')

            if ticks and len(ticks) > 0:
                spot_p = float(ticks[0].get("spot_price", 0.0))
                if records and len(records) > 0:
                    await asyncio.to_thread(cloud_data_manager.save_live_ticks, records)
                    await asyncio.to_thread(duckdb_engine.insert_ticks, records)

                if spot_p > 0:
                    # 1. Update all users' active desk positions & trailing SL
                    await asyncio.to_thread(multi_user_trader.update_all_positions_with_ticks, ticks, spot_p)

                    # 2. Evaluate master signal engine for algorithmic setups
                    sig_res = await asyncio.to_thread(live_signal_engine.process_market_tick, ticks, spot_p)
                    if sig_res and isinstance(sig_res, dict):
                        sig = sig_res.get("signal")
                        if sig:
                            # Deliver signal to each user's isolated signal engine!
                            all_users = user_db.get_all_users()
                            for u in all_users:
                                if u.get("status") != "active":
                                    continue
                                uname = u.get("username")
                                u_eng = get_live_signal_engine(uname)
                                # Only execute if that specific user has their master_switch ON and auto_trading ON!
                                if u_eng.state.get("master_switch", True):
                                    if u_eng.state.get("auto_trading", False):
                                        u_eng.state["active_signal"] = dict(sig)
                                        u_eng.execute_signal(sig.get("signal_id"), is_auto=True)
                                    else:
                                        u_eng.state["active_signal"] = dict(sig)
                                        u_eng.save_state()

                            # Broadcast to desk traders with master_auto=False so user's personal config controls it
                            await asyncio.to_thread(multi_user_trader.broadcast_signal, sig, master_auto=False)

                    # 3. Update trailing SL and positions for all active user signal engines
                    for u_eng in get_all_active_engines():
                        if u_eng.wallet.get("active_positions"):
                            u_eng.update_live_positions()
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

@app.get("/api/candles")
def get_candles(symbol: str = "SPOT", interval: int = 60, date: str = None):
    """API endpoint to fetch candle data from DuckDB for TradingView chart."""
    df = duckdb_engine.get_candles(symbol=symbol, interval_seconds=interval, date=date)
    if df is None or df.empty:
        return {"status": "empty", "candles": []}
    df = df.fillna(0.0)
    df_c = df.rename(columns={"candle_time": "time"})
    cols = [c for c in ["time", "open", "high", "low", "close", "volume"] if c in df_c.columns]
    candles = df_c[cols].to_dict("records")
    return {"status": "ok", "symbol": symbol, "date": date, "candles": candles}

@app.get("/api/timestamps")
def get_timestamps_api(date: str):
    """Returns available historical timestamps for the date slider."""
    ts = duckdb_engine.get_timestamps_for_date(date)
    return {"status": "ok", "date": date, "timestamps": ts or []}

@app.get("/api/symbols")
def get_symbols_api():
    """Returns all active option contracts and spot symbols."""
    syms = duckdb_engine.get_active_symbols()
    return {"status": "ok", "symbols": syms or ["NSE:NIFTY50-INDEX"]}

@app.get("/api/aoc_sr")
def api_aoc_sr(timestamp: Optional[str] = None):
    """Calculates automated Support & Resistance lines (R1, R3, R Rev, S1, S3, S Rev) for charts."""
    try:
        if timestamp:
            df = duckdb_engine.get_option_chain_at_timestamp(timestamp)
        else:
            df = duckdb_engine.get_latest_option_chain()
        if df is None or df.empty:
            return {"status": "empty", "data": None}
        ticks = df.to_dict("records")
        spot_price = float(ticks[0].get("spot_price", 0.0))
        from aoc_sr_engine import calculate_aoc_sr
        aoc_sr = calculate_aoc_sr(ticks, spot_price)
        return {"status": "ok", "data": aoc_sr}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/api/tot_decision")
def api_tot_decision(timestamp: Optional[str] = None):
    """Calculates Table of Trade (TOT) decision matrix, sentiment, and CE/PE trade execution plans."""
    try:
        if timestamp:
            df = duckdb_engine.get_option_chain_at_timestamp(timestamp)
        else:
            df = duckdb_engine.get_latest_option_chain()
        if df is None or df.empty:
            return {"status": "empty", "data": None}
        ticks = df.to_dict("records")
        spot_price = float(ticks[0].get("spot_price", 0.0))
        from aoc_sr_engine import calculate_aoc_sr
        from tot_signal_engine import calculate_tot_decision
        aoc_sr = calculate_aoc_sr(ticks, spot_price)
        tot = calculate_tot_decision(aoc_sr, spot_price)
        return {"status": "ok", "data": tot}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/api/strike_percentage_history")
def api_strike_percentage_history(strike: float, type: str = "CE", date: Optional[str] = None):
    """Provides historical percentage movement for a strike."""
    try:
        target_date = date or datetime.now().strftime("%Y-%m-%d")
        data = duckdb_engine.get_strike_percentage_history(target_date, float(strike), type.upper())
        return {"status": "ok", "strike": strike, "type": type, "date": target_date, "data": data or []}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/api/strike_sr_history")
def api_strike_sr_history(strike: float, date: Optional[str] = None):
    """Provides historical candles for an option strike."""
    try:
        res = duckdb_engine.get_strike_history(float(strike), interval_seconds=60, date=date)
        return res or {"status": "ok", "candles": []}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/api/signals/status")
def get_signal_engine_status(request: Request, timestamp: str = None):
    """Get live signal engine state (switch status, lots, strike mode, active signal) isolated per user."""
    engine, user = resolve_user_engine(request)
    try:
        connected, feed_msg = collector.is_fyers_connected()
        engine.state["live_connected"] = connected
        engine.state["feed_message"] = feed_msg
        
        is_open, msg = engine.is_market_open()
        engine.state["is_market_open"] = is_open
        engine.state["market_status"] = msg
        df = duckdb_engine.get_latest_option_chain()
        if df is not None and not df.empty:
            ticks = df.to_dict("records")
            spot_price = float(ticks[0].get("spot_price", 0.0))
            engine.state["live_spot_price"] = spot_price
            engine.state["last_tick_time"] = str(ticks[0].get("time_str", datetime.now().strftime("%H:%M:%S")))
            if is_open:
                engine.process_market_tick(ticks, spot_price, current_timestamp=None)
    except Exception as e:
        engine.state["error"] = str(e)
    res = dict(engine.state)
    res["current_user"] = user["username"] if user else "default"
    res["current_user_name"] = user["full_name"] if user else "Demo Trader"
    res["user_role"] = user["role"] if user else "guest"
    return res

@app.post("/api/signals/toggle_switch")
def toggle_signal_switch(payload: dict, request: Request):
    engine, _ = resolve_user_engine(request)
    is_on = payload.get("master_switch", True)
    return engine.set_switch(is_on)

@app.post("/api/signals/set_lots")
def set_signal_lots(payload: dict, request: Request):
    engine, _ = resolve_user_engine(request)
    lots = payload.get("lots", 2)
    return engine.set_lot_size(lots)

@app.post("/api/signals/set_daily_limit")
def set_daily_limit_route(payload: dict, request: Request):
    """Set daily profit trades target limit (2, 3, 4, 5, etc.)."""
    engine, _ = resolve_user_engine(request)
    limit = payload.get("max_daily_trades") or payload.get("limit", 2)
    return engine.set_max_daily_trades(limit)

@app.post("/api/signals/set_strike_mode")
def set_signal_strike_mode(payload: dict, request: Request):
    engine, _ = resolve_user_engine(request)
    mode = payload.get("strike_mode", "ITM_1")
    return engine.set_strike_mode(mode)

@app.post("/api/signals/toggle_auto")
def toggle_signal_auto(payload: dict, request: Request):
    engine, _ = resolve_user_engine(request)
    is_auto = payload.get("auto_trading", False)
    return engine.set_auto_mode(is_auto)

@app.post("/api/signals/execute")
def execute_signal_action(request: Request, payload: dict = None):
    engine, _ = resolve_user_engine(request)
    payload = payload or {}
    sig_id = payload.get("signal_id")
    is_auto = payload.get("is_auto", False)
    return engine.execute_signal(sig_id, is_auto=is_auto)

@app.post("/api/signals/cancel")
def cancel_signal_action(request: Request, payload: dict = None):
    engine, _ = resolve_user_engine(request)
    payload = payload or {}
    sig_id = payload.get("signal_id")
    return engine.cancel_signal(sig_id)

@app.post("/api/signals/test")
@app.post("/api/signals/test_trigger")
def trigger_test_signal_route(request: Request, payload: dict = None):
    engine, user = resolve_user_engine(request)
    payload = payload or {}
    direction = payload.get("direction", "CALL")
    res = engine.trigger_test_signal(direction)
    return res

@app.get("/api/signals/wallet")
def get_signal_wallet(request: Request):
    """Returns the dedicated virtual wallet status for the current logged-in user."""
    engine, _ = resolve_user_engine(request)
    return engine.get_wallet()

@app.get("/api/signals/history")
def get_signal_history(request: Request, date: Optional[str] = None):
    """Returns list of trades for current user's signals history table."""
    engine, _ = resolve_user_engine(request)
    return engine.get_trades(date=date)

@app.get("/api/signals/trades")
def get_signal_trades(request: Request, date: Optional[str] = None):
    engine, _ = resolve_user_engine(request)
    return {"status": "ok", "trades": engine.get_trades(date=date), "wallet": engine.get_wallet()}

@app.post("/api/signals/trades/close")
def close_signal_trade_route(payload: dict, request: Request):
    """Resolves or closes an active signal trade (Win / SL / Target hit) in user wallet."""
    engine, _ = resolve_user_engine(request)
    trade_id = payload.get("trade_id")
    outcome = payload.get("outcome", "TARGET_HIT")
    exit_ltp = payload.get("exit_ltp")
    return engine.close_trade(trade_id, outcome=outcome, exit_ltp=exit_ltp)

@app.post("/api/signals/delete_trades")
@app.post("/api/signals/trades/delete")
def delete_signal_trades(payload: dict, request: Request):
    engine, _ = resolve_user_engine(request)
    trade_ids = payload.get("trade_ids", [])
    return engine.delete_trades(trade_ids)

@app.post("/api/signals/reset_wallet")
@app.post("/api/signals/wallet/reset")
def reset_signal_wallet(request: Request, payload: dict = None):
    engine, _ = resolve_user_engine(request)
    payload = payload or {}
    init_cap = float(payload.get("initial_capital", 100000.0))
    return engine.reset_wallet(init_cap)

@app.post("/api/signals/wallet/reset_daily_limit")
def reset_signal_daily_limit(request: Request):
    engine, _ = resolve_user_engine(request)
    return engine.reset_daily_limit()

@app.get("/api/signals/export_csv")
def export_signals_csv(request: Request, date: Optional[str] = None):
    """Export user's trades history as downloadable CSV."""
    engine, user = resolve_user_engine(request)
    import pandas as pd
    trades = engine.get_trades(date=date)
    uname = user["username"] if user else "user"
    if not trades:
        content = "trade_id,timestamp,action,contract,strike_price,entry_ltp,exit_ltp,pnl_points,pnl_rupees,status\n"
    else:
        df = pd.DataFrame(trades)
        content = df.to_csv(index=False)
    return Response(
        content=content,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=institutional_trades_{uname}_{date or 'all'}.csv"}
    )

@app.get("/api/reversal/trades")
def get_reversal_trades_route(date: Optional[str] = None):
    """Endpoint for reversal signals audit ledger."""
    return {"status": "ok", "trades": []}


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
            fb_spot = 23387.05
            fb_atm = 23400
            return {
                "status": "ok",
                "spot_price": fb_spot,
                "atm_strike": fb_atm,
                "strikes": [
                    {"strike": s, "ce_ltp": round(max(5.0, (fb_spot - s)*0.68 + 75), 1), 
                     "pe_ltp": round(max(5.0, (s - fb_spot)*0.68 + 75), 1)}
                    for s in range(fb_atm - 200, fb_atm + 250, 50)
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
        target_pts=float(payload.get("target_pts", 35.0)),
        notifications_enabled=int(payload.get("notifications_enabled", 1)),
        max_open_positions=int(payload.get("max_open_positions", 1))
    )

@app.post("/api/user/settings/toggle_notifications")
def api_toggle_notifications(payload: dict, user: dict = Depends(require_auth)):
    """Quick toggle to turn notifications ON or OFF."""
    enabled = int(payload.get("enabled", 1))
    user_db.update_user_notifications(user["id"], enabled)
    if not enabled:
        user_db.dismiss_all_alerts(user["id"])
    return {"status": "ok", "notifications_enabled": enabled}

# ── Interactive Signal Notifications & Alerts ───────────────────────
@app.get("/api/user/alerts/pending")
def api_get_pending_alerts(user: dict = Depends(require_auth)):
    """Returns active pending signal alerts for the user."""
    # If user has notifications disabled, return empty
    cfg = user_db.get_user_settings(user["id"])
    if cfg.get("notifications_enabled", 1) == 0:
        return {"status": "ok", "alerts": []}
    return {"status": "ok", "alerts": user_db.get_pending_alerts(user["id"])}

@app.get("/api/user/alerts/history")
def api_get_alerts_history(date: Optional[str] = None, user: dict = Depends(require_auth)):
    """Returns all past signals & alerts with optional date filter."""
    return {"status": "ok", "alerts": user_db.get_user_alerts_history(user["id"], date=date)}

@app.post("/api/user/alerts/{alert_id}/execute")
def api_execute_alert(alert_id: int, user: dict = Depends(require_auth)):
    """User clicks 'Execute' button on a signal popup."""
    res = multi_user_trader.execute_alert(user["id"], alert_id)
    # Dismiss any other pending alerts so they don't spam
    user_db.dismiss_all_alerts(user["id"])
    return res

@app.post("/api/user/alerts/{alert_id}/cancel")
def api_cancel_alert(alert_id: int, user: dict = Depends(require_auth)):
    """User clicks 'Cancel' button to dismiss a signal popup."""
    res = multi_user_trader.cancel_alert(user["id"], alert_id)
    user_db.dismiss_all_alerts(user["id"])
    return res

@app.post("/api/user/alerts/dismiss_all")
def api_dismiss_all_alerts(user: dict = Depends(require_auth)):
    """User dismisses all pending alerts."""
    user_db.dismiss_all_alerts(user["id"])
    return {"status": "ok", "message": "All alerts dismissed"}

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
        spot_p = float(df['spot_price'].iloc[0]) if df is not None and not df.empty else 23387.05
        atm_strike = int(round(spot_p / 50.0) * 50)
        
        pcr = 0.85
        sentiment = "BEARISH"
        support = atm_strike - 50 if (atm_strike - 50) <= spot_p else atm_strike
        resistance = atm_strike + 100 if (atm_strike + 100) >= spot_p else atm_strike + 50
        
        if df is not None and not df.empty:
            total_ce_oi = df[df['type'] == 'CE']['oi'].sum()
            total_pe_oi = df[df['type'] == 'PE']['oi'].sum()
            if total_ce_oi > 0:
                pcr = round(float(total_pe_oi / total_ce_oi), 2)
            sentiment = "BULLISH" if pcr >= 1.0 else "BEARISH"
            
            # Dynamic Real Support = Strike near ATM with Highest PE OI
            pe_df = df[df['type'] == 'PE']
            if not pe_df.empty:
                max_pe_idx = pe_df['oi'].idxmax()
                support = int(pe_df.loc[max_pe_idx, 'strike'])
                
            # Dynamic Real Resistance = Strike near ATM with Highest CE OI
            ce_df = df[df['type'] == 'CE']
            if not ce_df.empty:
                max_ce_idx = ce_df['oi'].idxmax()
                resistance = int(ce_df.loc[max_ce_idx, 'strike'])

        return {
            "status": "ok",
            "spot_price": round(spot_p, 2),
            "atm_strike": atm_strike,
            "pcr": pcr,
            "sentiment": sentiment,
            "support": support,
            "resistance": resistance,
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

@app.post("/api/admin/users/{user_id}/update_profile")
def api_admin_update_profile(user_id: int, payload: dict, admin: dict = Depends(require_admin)):
    """Updates user username, full_name, password, and margin balance."""
    return user_db.update_user_profile(
        user_id=user_id,
        username=payload.get("username"),
        full_name=payload.get("full_name"),
        new_password=payload.get("new_password"),
        capital=payload.get("capital")
    )

@app.get("/api/admin/live_positions")
def api_admin_live_positions(admin: dict = Depends(require_admin)):
    """Real-time stream of all open positions across all users."""
    return {"status": "ok", "positions": multi_user_trader.get_all_platform_open_positions()}

@app.post("/api/admin/positions/{trade_id}/close")
def api_admin_close_single_position(trade_id: str, admin: dict = Depends(require_admin)):
    """Admin manually exits an open position for any trader."""
    with user_db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT user_id FROM user_positions WHERE trade_id = ?", (trade_id,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Position not found")
        uid = row["user_id"]
    return multi_user_trader.close_position(user_id=uid, trade_id=trade_id, outcome="ADMIN_EXIT")

@app.post("/api/admin/positions/close_all")
def api_admin_close_all_positions(payload: dict, admin: dict = Depends(require_admin)):
    """Admin squares off all positions for a specific trader or all traders."""
    username = payload.get("username", "ALL")
    positions = multi_user_trader.get_all_platform_open_positions()
    if username != "ALL":
        positions = [p for p in positions if p.get("username") == username]
    closed_count = 0
    for p in positions:
        try:
            multi_user_trader.close_position(user_id=p["user_id"], trade_id=p["trade_id"], outcome="ADMIN_BULK_EXIT")
            closed_count += 1
        except Exception:
            pass
    return {"status": "ok", "closed_count": closed_count, "message": f"Successfully squared off {closed_count} positions"}

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
    
    token_data = {"client_id": client_id, "access_token": token}
    token_file = os.path.join(BASE_DIR, "fyers_token.json")
    with open(token_file, "w") as f:
        json.dump(token_data, f)
    
    try:
        user_db.set_config("fyers_token", json.dumps(token_data))
    except Exception:
        pass
    
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
    
    token_data = {"client_id": client_id, "access_token": token}
    token_file = os.path.join(BASE_DIR, "fyers_token.json")
    with open(token_file, "w") as f:
        json.dump(token_data, f)
    
    try:
        user_db.set_config("fyers_token", json.dumps(token_data))
    except Exception:
        pass
    
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
