@echo off
REM EchoPilot - launch the app
REM Run setup.bat first if you haven't already.

python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found. Run setup.bat first.
    pause
    exit /b 1
)

cd /d "%~dp0"
python app.py
