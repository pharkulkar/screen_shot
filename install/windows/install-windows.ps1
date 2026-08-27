# =============================================================================
# install-windows.ps1
# Registers two hidden background tasks in Windows Task Scheduler:
#   1. SilentScreenshotDaemon  — global key listener, takes screenshots
#   2. SilentScreenshotServer  — Flask web gallery at http://localhost:5000
#
# Both start silently at login via VBScript wrappers (no console window).
#
# Usage (run as your normal user in PowerShell — NOT as Administrator):
#   Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
#   .\install-windows.ps1
#
# Requirements:
#   - Python 3.8+ on PATH
#   - pip install -r requirements.txt  (run in project root first)
# =============================================================================

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# ── Paths ──────────────────────────────────────────────────────────────────────
$ScriptDir     = Split-Path -Parent $MyInvocation.MyCommand.Definition
$InstallDir    = (Resolve-Path (Join-Path $ScriptDir "..\..")).Path
$LogDir        = Join-Path $InstallDir "logs"
$DaemonVbsSrc  = Join-Path $ScriptDir "run-daemon-hidden.vbs"
$ServerVbsSrc  = Join-Path $ScriptDir "run-server-hidden.vbs"
$DaemonVbsDst  = Join-Path $InstallDir "run-daemon-hidden.vbs"
$ServerVbsDst  = Join-Path $InstallDir "run-server-hidden.vbs"
$DaemonTask    = "SilentScreenshotDaemon"
$ServerTask    = "SilentScreenshotServer"

# ── Validate ───────────────────────────────────────────────────────────────────
$Python = (Get-Command python -ErrorAction SilentlyContinue)?.Source
if (-not $Python) {
    Write-Error "python not found on PATH. Install Python 3.8+ first."
    exit 1
}

# pythonw.exe sits beside python.exe — no console window.
$Pythonw = Join-Path (Split-Path $Python) "pythonw.exe"
if (-not (Test-Path $Pythonw)) {
    Write-Warning "pythonw.exe not found next to python.exe — falling back to python.exe (console may flash briefly)"
    $Pythonw = $Python
}

foreach ($mod in @("pynput", "flask", "PIL")) {
    $check = & $Python -c "import $mod" 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Python module '$mod' not found. Run:  pip install -r requirements.txt"
        exit 1
    }
}

foreach ($f in @("daemon.py", "server.py", "config.json")) {
    if (-not (Test-Path (Join-Path $InstallDir $f))) {
        Write-Error "$f not found in $InstallDir"
        exit 1
    }
}

# ── Prepare ────────────────────────────────────────────────────────────────────
New-Item -ItemType Directory -Path $LogDir -Force | Out-Null

# ── Write VBScripts with real paths substituted ────────────────────────────────
function Write-Vbs($src, $dst) {
    $content = (Get-Content $src -Raw) `
        -replace 'PYTHONW_EXE',  $Pythonw.Replace('\', '\\') `
        -replace 'INSTALL_DIR',  $InstallDir.Replace('\', '\\')
    Set-Content -Path $dst -Value $content -Encoding UTF8
    Write-Host "  Written: $dst"
}

Write-Host "Writing VBScript launchers..."
Write-Vbs $DaemonVbsSrc $DaemonVbsDst
Write-Vbs $ServerVbsSrc $ServerVbsDst

# ── Helper: register one scheduled task ───────────────────────────────────────
function Register-HiddenTask($taskName, $vbsPath) {
    $existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    if ($existing) {
        Write-Host "  Removing existing task '$taskName'..."
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    }

    $action    = New-ScheduledTaskAction `
                     -Execute "wscript.exe" `
                     -Argument "`"$vbsPath`"" `
                     -WorkingDirectory $InstallDir

    $trigger   = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME

    $settings  = New-ScheduledTaskSettingsSet `
                     -ExecutionTimeLimit  (New-TimeSpan -Hours 0) `
                     -RestartCount        5 `
                     -RestartInterval     (New-TimeSpan -Minutes 1) `
                     -MultipleInstances   IgnoreNew `
                     -StartWhenAvailable

    $principal = New-ScheduledTaskPrincipal `
                     -UserId    $env:USERNAME `
                     -LogonType Interactive `
                     -RunLevel  Limited

    Register-ScheduledTask `
        -TaskName  $taskName `
        -Action    $action `
        -Trigger   $trigger `
        -Settings  $settings `
        -Principal $principal `
        -Force | Out-Null

    Write-Host "  Registered: $taskName"
}

# ── Register tasks ─────────────────────────────────────────────────────────────
Write-Host "Registering scheduled tasks..."
Register-HiddenTask $DaemonTask $DaemonVbsDst
Register-HiddenTask $ServerTask $ServerVbsDst

# ── Start both immediately ─────────────────────────────────────────────────────
Write-Host "Starting tasks..."
Start-ScheduledTask -TaskName $DaemonTask
Start-Sleep -Seconds 2
Start-ScheduledTask -TaskName $ServerTask

Write-Host ""
Write-Host "OK  Installed and started."
Write-Host "    Daemon task : $DaemonTask"
Write-Host "    Server task : $ServerTask"
Write-Host "    Gallery     : http://localhost:5000"
Write-Host "    Log         : $LogDir\daemon.log"
Write-Host ""
Write-Host "NOTE: Windows Defender may flag the global keyboard hook."
Write-Host "Add an exclusion for this folder in Windows Security if needed."
