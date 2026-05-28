@echo off
color 0b
title AI Proctoring App Launcher
echo ===================================================
echo      STARTING SENTINEL PROCTORING APP...
echo Initializing Desktop Application...
cd /d "c:\8th SEM\Major project"
python Run_App.py
if %errorlevel% neq 0 (
    echo.
    echo ===================================================
    echo Sentinel Application crashed with exit code %errorlevel%
    echo Please review the error messages above.
    echo ===================================================
    pause
)
