# XTTS Local - Automated CI Build

This repository contains the source and CI configuration to produce a Windows distributable.

## How it works
- GitHub Actions runs on push to `main` and builds on a clean Windows VM.
- The workflow builds a PyInstaller `--onedir` artifact, packages an NSIS installer, and publishes a Release.
- Download the installer from the Releases page and run it.

## If you need changes
- Edit `src/xtts_local.py` with the real app code.
- Add runtime dependencies to `requirements.txt`.
- Push to `main` to trigger a new build.
