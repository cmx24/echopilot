@echo off
setlocal EnableDelayedExpansion
REM ============================================================
REM  EchoPilot Setup  —  fully automated
REM  Run once; re-run any time to repair or update.
REM ============================================================

echo ============================================================
echo  EchoPilot Setup
echo ============================================================
echo.

cd /d "%~dp0"

REM ── 1. Find the best Python to build the venv with ───────────
REM  We need Python 3.11 (or below) to include the voice-cloning
REM  library (chatterbox-tts requires numpy 1.24-1.25 which has
REM  no pre-built wheels for Python 3.12+).
REM  Strategy:
REM    a) If system Python < 3.12 → use it directly.
REM    b) If system Python >= 3.12 → look for py -3.11.
REM    c) If not found → install Python 3.11 via winget silently.
REM    d) If winget unavailable → fall back to system Python
REM       (app works; cloning unavailable).

REM VENV_PYEXE is the full command used to create and run the venv.
set VENV_PYEXE=
set PYVER=
set PYMINOR=0
set CLONING=0

REM Check system Python
python --version >nul 2>&1
if errorlevel 1 (
    echo No Python found on PATH. Trying winget to install Python 3.11...
    goto :TRY_WINGET_PY311
)

for /f "tokens=2 delims= " %%v in ('python --version 2^>^&1') do set PYVER=%%v
for /f "tokens=2 delims=." %%m in ("%PYVER%") do set PYMINOR=%%m
echo System Python: %PYVER%

if %PYMINOR% LSS 12 (
    echo Python %PYVER% supports voice cloning directly.
    set VENV_PYEXE=python
    set CLONING=1
    goto :BUILD_VENV
)

REM System Python >= 3.12 — look for 3.11 via py launcher
echo Python %PYVER% detected. Looking for Python 3.11 for voice cloning...
py -3.11 --version >nul 2>&1
if not errorlevel 1 (
    for /f "tokens=2 delims= " %%v in ('py -3.11 --version 2^>^&1') do echo Found py -3.11: %%v
    REM Resolve the actual Python 3.11 executable path so venv commands use a plain path
    for /f %%p in ('py -3.11 -c "import sys; print(sys.executable)"') do set VENV_PYEXE=%%p
    set CLONING=1
    goto :BUILD_VENV
)

REM Python 3.11 not installed — try winget
echo Python 3.11 not found. Attempting automatic install via winget...
:TRY_WINGET_PY311
winget --version >nul 2>&1
if errorlevel 1 (
    echo winget not available. Skipping automatic Python 3.11 install.
    goto :NO_PY311
)

winget install -e --id Python.Python.3.11 --silent --accept-package-agreements --accept-source-agreements
if errorlevel 1 (
    echo winget install did not succeed. Skipping automatic Python 3.11 install.
    goto :NO_PY311
)

REM Verify the py launcher can now see Python 3.11.
REM (The py launcher reads registry entries, so it detects the new install
REM  without needing to refresh PATH in the current shell.)
py -3.11 --version >nul 2>&1
if errorlevel 1 (
    echo Python 3.11 was installed but the py launcher cannot find it yet.
    echo Please close this window and re-run setup.bat.
    pause
    exit /b 1
)
for /f "tokens=2 delims= " %%v in ('py -3.11 --version 2^>^&1') do echo Installed: Python %%v
for /f %%p in ('py -3.11 -c "import sys; print(sys.executable)"') do set VENV_PYEXE=%%p
set CLONING=1
goto :BUILD_VENV

:NO_PY311
REM Fall back to system Python — no cloning, but app still works
if "%VENV_PYEXE%"=="" set VENV_PYEXE=python
echo.
echo ============================================================
echo  NOTE: Python 3.11 could not be found or installed.
echo  Voice cloning will NOT be available.
echo  EchoPilot will work with 400+ Microsoft Edge TTS voices.
echo ============================================================
echo.

REM ── 2. Create / refresh virtual environment ─────────────────
:BUILD_VENV
echo.
echo Setting up virtual environment in .\venv ...
"%VENV_PYEXE%" -m venv venv
if errorlevel 1 (
    echo ERROR: Failed to create virtual environment.
    pause
    exit /b 1
)

set VPIP=venv\Scripts\pip.exe

echo Upgrading pip...
"%VPIP%" install --upgrade pip

REM ── 3. Install core dependencies ────────────────────────────
echo.
echo Installing core dependencies...
"%VPIP%" install PyQt5 edge-tts pydub pyttsx3 librosa soundfile numpy scipy langdetect mutagen
if errorlevel 1 (
    echo ERROR: Core dependency install failed. Check your internet connection.
    pause
    exit /b 1
)

REM ── 4. Install voice-cloning libraries (if compatible Python) ─
if %CLONING%==1 (
    echo.
    echo Installing Chatterbox TTS ^(English voice cloning^)...
    echo NOTE: A ~400 MB model is downloaded from HuggingFace on first use.
    "%VPIP%" install chatterbox-tts
    if errorlevel 1 (
        echo WARNING: chatterbox-tts failed to install.
    ) else (
        echo Chatterbox TTS installed successfully.
    )

    echo.
    echo Installing Coqui XTTS v2 ^(multilingual voice cloning: pt-BR, fr, es, zh, ...^)...
    echo NOTE: A ~2 GB model is downloaded from HuggingFace on first use.
    "%VPIP%" install TTS
    if errorlevel 1 (
        echo WARNING: Coqui TTS failed to install.
        echo Multilingual cloning ^(pt-BR, fr, es, etc.^) will not be available.
        echo English cloning via Chatterbox will still work if it installed above.
    ) else (
        echo Coqui XTTS v2 installed successfully.
    )
)

echo.
echo ============================================================
echo  Setup complete!  Run run.bat to start EchoPilot.
echo ============================================================
pause
