@echo off
REM EchoPilot - first-time setup
REM Run this once to install all Python dependencies.

echo ============================================================
echo  EchoPilot Setup
echo ============================================================
echo.

REM Check that Python is on PATH
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found on PATH.
    echo Please install Python 3.10+ from https://www.python.org/downloads/
    echo Make sure to tick "Add Python to PATH" during installation.
    pause
    exit /b 1
)

echo Python found. Installing dependencies...
echo.

python -m pip install --upgrade pip
python -m pip install PyQt5 edge-tts pydub librosa soundfile numpy scipy langdetect mutagen

echo.
echo ============================================================
echo  Setup complete! Run "run.bat" to start EchoPilot.
echo ============================================================
pause
