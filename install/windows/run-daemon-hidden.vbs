' =============================================================================
' run-daemon-hidden.vbs
' Launches daemon.py via pythonw.exe so no console window ever appears.
' Paths are substituted by install-windows.ps1.
' =============================================================================
Dim pythonw, installDir, shell

pythonw    = "PYTHONW_EXE"
installDir = "INSTALL_DIR"

Set shell = CreateObject("WScript.Shell")
shell.CurrentDirectory = installDir
' WindowStyle 0 = completely hidden.  bWaitOnReturn = False = fire and forget.
shell.Run """" & pythonw & """ """ & installDir & "\daemon.py""", 0, False
Set shell = Nothing
