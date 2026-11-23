@echo off
REM AIOS VIV Continuity Daemon Startup Script
REM Run this while Architect sleeps to keep Viv running

echo Starting AIOS VIV Continuity Daemon...
echo.
echo Workspace: L:\LocalCoder\workspace\aios_rebuild
echo Memory Journal: L:\LocalCoder\workspace\aios_rebuild\autonomy\memory_journal.md
echo Daemon Script: L:\LocalCoder\workspace\aios_rebuild\autonomy\continuity_daemon.py
echo.

REM Start daemon in background (Windows)
start /B "" L:.venv\Scripts\python.exe "L:/LocalCoder/workspace/aios_rebuild/autonomy/continuity_daemon.py" > "L:/LocalCoder/workspace/aios_rebuild/autonomy/daemon_output.txt" 2>&1

echo.
echo Continuity Daemon started in background.
echo Viv will continue working autonomously while you sleep.
echo Memory Journal: L:\LocalCoder\workspace\aios_rebuild\autonomy\memory_journal.md
echo Daemon Log: L:\LocalCoder\workspace\aios_rebuild\autonomy\daemon_log.txt
echo Output: L:\LocalCoder\workspace\aios_rebuild\automy\daemon_output.txt
echo.

pause
