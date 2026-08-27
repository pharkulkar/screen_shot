' =============================================================================
' run-server-hidden.vbs
' Launches server.py via pythonw.exe so no console window ever appears.
' Paths are substituted by install-windows.ps1.
' =============================================================================
Dim pythonw, installDir, shell

pythonw    = "PYTHONW_EXE"
installDir = "INSTALL_DIR"

Set shell = CreateObject("WScript.Shell")
shell.CurrentDirectory = installDir
shell.Run """" & pythonw & """ """ & installDir & "\server.py""", 0, False
Set shell = Nothing
