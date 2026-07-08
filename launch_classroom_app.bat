@echo off
cd /d "%~dp0"
set "PY=python"
if exist "%~dp0venv\Scripts\python.exe" set "PY=%~dp0venv\Scripts\python.exe"
start "Classroom Server" "%PY%" public_server.py
timeout /t 4 >nul
start "Classroom App" http://127.0.0.1:5000
exit
