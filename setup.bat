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

echo Python found. Installing core dependencies...
echo.

python -m pip install --upgrade pip
python -m pip install PyQt5 edge-tts pydub librosa soundfile numpy scipy langdetect mutagen

echo.

REM Coqui TTS (XTTS v2 voice cloning) only supports Python 3.9-3.11.
REM Detect version and install only when compatible.
for /f "tokens=2 delims= " %%v in ('python --version 2^>^&1') do set PYVER=%%v
for /f "tokens=2 delims=." %%m in ("%PYVER%") do set PYMINOR=%%m

if %PYMINOR% LSS 12 (
    echo Installing TTS (Coqui XTTS v2) for voice cloning...
    echo NOTE: The model (~2 GB) is downloaded on first use.
    echo.
    python -m pip install TTS
) else (
    echo NOTE: Coqui TTS (XTTS v2 voice cloning) requires Python 3.9-3.11.
    echo       You are running Python %PYVER%, so it will be skipped.
    echo       Voice generation will use Microsoft Edge TTS (400+ neural voices).
    echo       To enable voice cloning, install Python 3.11 and re-run setup.bat.
)

echo.
echo ============================================================
echo  Setup complete! Run "run.bat" to start EchoPilot.
echo ============================================================
pause
