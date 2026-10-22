Unicode True
RequestExecutionLevel user
Name "ReadDraw"
OutFile "..\release\ReadDraw-Setup-v${APP_VERSION}.exe"
InstallDir "$LOCALAPPDATA\Programs\ReadDraw"
InstallDirRegKey HKCU "Software\ReadDraw" "InstallDir"
Icon "..\assets\ReadDraw.ico"
UninstallIcon "..\assets\ReadDraw.ico"
ShowInstDetails show
ShowUninstDetails show

Page directory
Page instfiles
UninstPage uninstConfirm
UninstPage instfiles

Section "ReadDraw"
  SetOutPath "$INSTDIR"
  File /oname=ReadDraw.exe "${EXE_PATH}"
  WriteRegStr HKCU "Software\ReadDraw" "InstallDir" "$INSTDIR"
  WriteUninstaller "$INSTDIR\Uninstall.exe"
  CreateDirectory "$SMPROGRAMS\ReadDraw"
  CreateShortCut "$DESKTOP\ReadDraw.lnk" "$INSTDIR\ReadDraw.exe"
  CreateShortCut "$SMPROGRAMS\ReadDraw\ReadDraw.lnk" "$INSTDIR\ReadDraw.exe"
  CreateShortCut "$SMPROGRAMS\ReadDraw\卸载 ReadDraw.lnk" "$INSTDIR\Uninstall.exe"
SectionEnd

Section "Uninstall"
  Delete "$DESKTOP\ReadDraw.lnk"
  Delete "$SMPROGRAMS\ReadDraw\ReadDraw.lnk"
  Delete "$SMPROGRAMS\ReadDraw\卸载 ReadDraw.lnk"
  RMDir "$SMPROGRAMS\ReadDraw"
  Delete "$INSTDIR\ReadDraw.exe"
  Delete "$INSTDIR\drop_helper.exe"
  Delete "$INSTDIR\drop_hook.dll"
  Delete "$INSTDIR\Uninstall.exe"
  RMDir "$INSTDIR"
  DeleteRegKey HKCU "Software\ReadDraw"
SectionEnd
