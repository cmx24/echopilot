; build/installer.nsi - minimal NSIS script
Name "XTTS Local"
OutFile "xtts_local_installer.exe"
InstallDir "$PROGRAMFILES\XTTS Local"
RequestExecutionLevel user
Section "Install"
  SetOutPath "$INSTDIR"
  File /r "dist\xtts_local\*"
SectionEnd
