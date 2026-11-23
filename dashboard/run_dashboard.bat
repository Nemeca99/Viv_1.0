@echo off
title Nox Forge - Master Neural Control Panel
cd /d "L:\LocalCoder"
echo Starting Viv learner and Nox Forge Master Neural Dashboard on port 8501...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "L:\LocalCoder\dashboard\run_dashboard_with_learner.ps1"
pause
