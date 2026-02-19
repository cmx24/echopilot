; build/installer.nsi
!define APPNAME "XTTS Local"
!define VERSION "1.0.0"
!define INSTALLDIR "$LOCALAPPDATA\Programs\XTTS Local"

OutFile "xtts_local_installer.exe"
InstallDir "${INSTALLDIR}"
RequestExecutionLevel user

Section "Install"
  SetOutPath "$INSTDIR"
  File /r "dist\xtts_local\*.*"
  CreateDirectory "$SMPROGRAMS\XTTS Local"
  CreateShortCut "$SMPROGRAMS\XTTS Local\XTTS Local.lnk" "$INSTDIR\xtts_local.exe"
  WriteUninstaller "$INSTDIR\uninstall.exe"
SectionEnd

Section "Uninstall"
  Delete "$INSTDIR\xtts_local.exe"
  Delete "$SMPROGRAMS\XTTS Local\XTTS Local.lnk"
  RMDir /r "$INSTDIR"
  Delete "$INSTDIR\uninstall.exe"
SectionEnd
