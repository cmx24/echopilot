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

REM Detect Python version for compatibility checks
for /f "tokens=2 delims= " %%v in ('python --version 2^>^&1') do set PYVER=%%v
for /f "tokens=2 delims=." %%m in ("%PYVER%") do set PYMINOR=%%m

echo Python %PYVER% found. Installing core dependencies...
echo.

python -m pip install --upgrade pip
python -m pip install PyQt5 edge-tts pydub librosa soundfile numpy scipy langdetect mutagen

echo.

REM Chatterbox TTS (voice cloning) requires Python 3.10-3.11.
REM numpy 1.24-1.25 (required by chatterbox) has no pre-built wheels for Python 3.12+,
REM so we skip the install entirely rather than letting pip fail with a long traceback.
if %PYMINOR% LSS 12 (
    echo Installing Chatterbox TTS (voice cloning^)...
    echo NOTE: ~400 MB model is downloaded from HuggingFace on first use.
    echo.
    python -m pip install chatterbox-tts
    if errorlevel 1 (
        echo.
        echo ============================================================
        echo  WARNING: chatterbox-tts failed to install.
        echo  Voice cloning will NOT be available.
        echo.
        echo  Try running manually:
        echo    pip install chatterbox-tts
        echo.
        echo  The app will still work with 400+ edge-tts neural voices.
        echo ============================================================
        echo.
        pause
    )
) else (
    echo ============================================================
    echo  NOTE: Chatterbox TTS voice cloning requires Python 3.10-3.11.
    echo  You are running Python %PYVER%.
    echo.
    echo  chatterbox-tts is SKIPPED ^(it cannot install on Python 3.12+^).
    echo.
    echo  To enable voice cloning, install Python 3.11:
    echo    https://www.python.org/downloads/release/python-3119/
    echo  Then create a virtual environment and run:
    echo    py -3.11 -m venv venv311
    echo    venv311\Scripts\activate
    echo    pip install PyQt5 edge-tts pydub librosa soundfile numpy scipy langdetect mutagen
    echo    pip install chatterbox-tts
    echo    python app.py
    echo.
    echo  The app works NOW with 400+ Microsoft Edge TTS neural voices.
    echo ============================================================
    echo.
)

REM Coqui TTS (XTTS v2 voice cloning) only supports Python 3.9-3.11.
if %PYMINOR% LSS 12 (
    echo Installing TTS (Coqui XTTS v2^) for voice cloning...
    echo NOTE: The model (~2 GB) is downloaded on first use.
    echo.
    python -m pip install TTS
) else (
    echo NOTE: Coqui TTS (XTTS v2^) also requires Python 3.9-3.11 — skipped on %PYVER%.
)

echo.
echo ============================================================
echo  Setup complete! Run "run.bat" to start EchoPilot.
echo ============================================================
pause
