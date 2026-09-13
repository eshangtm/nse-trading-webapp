@echo off
title Multi-User Virtual Trading SaaS WebApp
echo ====================================================================
echo   Launching QuantGini Multi-User Virtual Trading SaaS Platform...
echo   (Admin Panel + User Demo Portals + Manual / Algo Trading)
echo ====================================================================

cd /d "%~dp0"

:: Check if server is already running on port 8080
netstat -ano | findstr /R /C:":8080 .*LISTENING" >nul
if errorlevel 1 (
    echo [INFO] Starting multi-user web server on port 8080...
    start "QuantGini Virtual Trading Server (Port 8080)" python server.py
    ping -n 4 127.0.0.1 >nul
)

echo [OK] Web server running. Opening Login Portal in browser...
start http://localhost:8080/login

echo ====================================================================
echo   Login Portal: http://localhost:8080/login
echo   Admin Panel : http://localhost:8080/admin
echo   Trading Desk: http://localhost:8080/trade
echo.
echo   Default Credentials:
echo     Admin : admin / Admin@123
echo     User 1: demo_trader1 / demo123 (Rs. 1,00,000 Margin)
echo     User 2: demo_trader2 / demo123 (Rs. 2,00,000 Margin)
echo ====================================================================
pause
