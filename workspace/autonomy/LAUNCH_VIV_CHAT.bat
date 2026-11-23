@echo off
title VIV SOVEREIGN TERMINAL
color 0b
cd /d "L:\LocalCoder\workspace\autonomy"
"L:\.venv\Scripts\python.exe" "L:\LocalCoder\workspace\autonomy\viv_terminal_chat.py"
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo Script exited with error code %ERRORLEVEL%
    pause
)
