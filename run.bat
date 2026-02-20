@echo off
REM EchoPilot — launch the app
REM Run setup.bat first if you haven't already.

cd /d "%~dp0"

if exist "venv\Scripts\python.exe" (
    venv\Scripts\python.exe app.py
) else (
    python --version >nul 2>&1
    if errorlevel 1 (
        echo ERROR: Python not found and no venv\ present.
        echo Please run setup.bat first.
        pause
        exit /b 1
    )
    python app.py
)
