@echo off
REM One-click: rebuild venv, install deps, run the test suite.
REM Safe to delete after use.
cd /d "%~dp0"

echo === [1/3] Recreating venv ===
python -m venv venv --clear
if errorlevel 1 (
    echo FAILED to create venv. Make sure Python 3 is on PATH.
    pause
    exit /b 1
)

echo === [2/3] Installing dependencies ===
venv\Scripts\python.exe -m pip install --upgrade pip >nul
venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 (
    echo Full requirements failed ^(likely psycopg2-binary/supabase on Python 3.14^).
    echo Falling back to the minimal set needed for tests...
    venv\Scripts\python.exe -m pip install "Flask==2.3.3" Flask-WTF Werkzeug python-dotenv pytest qrcode Pillow
)
if errorlevel 1 (
    echo FAILED to install dependencies.
    pause
    exit /b 1
)

echo === [3/3] Running tests ===
venv\Scripts\python.exe -m pytest tests/ -q

echo.
echo Done. Exit code: %errorlevel%
pause
