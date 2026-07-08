@echo off
cd /d "%~dp0"
set "PY=python"
if exist "%~dp0venv\Scripts\python.exe" set "PY=%~dp0venv\Scripts\python.exe"
start "Classroom Server" cmd /k "%PY% public_server.py"
timeout /t 2 >nul
start "Serveo Tunnel" cmd /k "ssh -R 80:127.0.0.1:5000 serveo.net"
exit
