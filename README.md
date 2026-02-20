# EchoPilot — TTS Studio

A PyQt5 desktop application for text-to-speech synthesis, voice cloning, and audio editing.

## Quick start (Windows — run from source)

1. Install **Python 3.10+** from <https://www.python.org/downloads/>  
   (tick **"Add Python to PATH"** during installation)
2. Double-click **`setup.bat`** — installs all Python dependencies once
3. Double-click **`run.bat`** — launches the EchoPilot GUI

## Download a ZIP to test

1. Go to the **Actions** tab in this repository
2. Open the latest **Source ZIP** workflow run
3. Under **Artifacts**, download **echopilot_source** (a ZIP of all source files)
4. Extract the ZIP, then follow the Quick start steps above

A standalone Windows installer (PyInstaller + NSIS) is produced by the
**Windows Build and Release** workflow and published to **Releases** on push to `main`.

## Features

- Generate — 400+ neural TTS voices via Microsoft Edge TTS, with tone and mood controls
- Clone Voice — save custom voice profiles with reference audio, auto-detect gender/language
- Voice Bank — filter and browse all built-in and custom voices
- Edit & Save — trim audio, live-tweak tone/mood, export as WAV or MP3

## Requirements

See `requirements.txt`. Key packages: `PyQt5`, `edge-tts`, `pydub`, `librosa`, `langdetect`.
