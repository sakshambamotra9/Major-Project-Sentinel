@echo off
color 0a
title Sentinel AI Backend Server Launcher
echo ===================================================
echo      STARTING SENTINEL AI BACKEND SERVER ONLY...
echo ===================================================
echo.
echo This script starts only the backend server (port 8000).
echo You can use the Admin Dashboard to register students or 
echo create exams while this backend runs in the background.
echo.
echo Press Ctrl+C at any time to stop the server.
echo.
cd /d "%~dp0backend"
python -m uvicorn main:app --host 127.0.0.1 --port 8000
pause
