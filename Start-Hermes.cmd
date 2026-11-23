@echo off
set "PATH=%LOCALAPPDATA%\hermes\bin;%USERPROFILE%\.local\bin;%PATH%"
set "TERM=xterm-256color"
cd /d L:\LocalCoder
ori hermes --model nvidia/nemotron-3-ultra-550b-a55b:free -- --cli --in L:\LocalCoder --skills localcoder-project,localcoder-continuity
if errorlevel 1 pause
