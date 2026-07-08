@echo off
cd /d "%~dp0"
if exist venv\Scripts\activate.bat (
    call venv\Scripts\activate.bat
) else (
    echo Virtual environment not found. Starting with system Python.
)
start http://127.0.0.1:5000
python app.py
pause
