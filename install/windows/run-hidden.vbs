' =============================================================================
' run-hidden.vbs
' Launches silent-screenshot-daemon via wscript.exe so no console window
' ever appears.  Task Scheduler calls this VBScript; it in turn calls node.
'
' Arguments are substituted by install-windows.ps1:
'   NODE_EXE   - absolute path to node.exe
'   INSTALL_DIR - absolute path to the project root
'
' Usage (via Task Scheduler — do not run manually):
'   wscript.exe "C:\path\to\run-hidden.vbs"
' =============================================================================

Dim nodeExe, installDir, indexJs, shell

nodeExe    = "NODE_EXE"
installDir = "INSTALL_DIR"
indexJs    = installDir & "\index.js"

Set shell = CreateObject("WScript.Shell")

' WindowStyle 0 = hidden window.  bWaitOnReturn = False = fire and forget.
shell.Run """" & nodeExe & """ """ & indexJs & """", 0, False

Set shell = Nothing
