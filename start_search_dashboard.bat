@echo off
title Upwork Lead Search Dashboard
echo =======================================================
echo   Starting Upwork Lead Search Web Dashboard...
echo =======================================================

cd /d "%~dp0\Script"

:: Start browser after 2 seconds in background
start "" cmd /c "timeout /t 2 /nobreak >nul && start http://localhost:5000"

:: Start Flask server
python app.py

pause
