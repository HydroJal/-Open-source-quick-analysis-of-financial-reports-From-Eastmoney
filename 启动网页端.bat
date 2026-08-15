@echo off
title Financial Report Quick Analysis
cd /d "%~dp0"

echo ============================================
echo   Financial Report Quick Analysis
echo   Starting server, browser opens in 3s...
echo   (Press Ctrl+C to stop)
echo ============================================

start "" /min cmd /c "timeout /t 3 /nobreak >nul & start http://127.0.0.1:5000"

py app.py

pause
