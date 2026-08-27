# =============================================================================
# uninstall-windows.ps1
# Stops and removes both scheduled tasks and the generated VBScript launchers.
# =============================================================================

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ScriptDir  = Split-Path -Parent $MyInvocation.MyCommand.Definition
$InstallDir = (Resolve-Path (Join-Path $ScriptDir "..\..")).Path

foreach ($taskName in @("SilentScreenshotDaemon", "SilentScreenshotServer")) {
    $task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    if ($task) {
        if ($task.State -eq 'Running') {
            Stop-ScheduledTask -TaskName $taskName
            Write-Host "Stopped: $taskName"
        }
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
        Write-Host "Removed task: $taskName"
    } else {
        Write-Host "Task not found: $taskName"
    }
}

foreach ($vbs in @("run-daemon-hidden.vbs", "run-server-hidden.vbs")) {
    $path = Join-Path $InstallDir $vbs
    if (Test-Path $path) {
        Remove-Item $path -Force
        Write-Host "Removed: $path"
    }
}

# Kill any running python processes for this project
Get-Process python, pythonw -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like "*daemon.py*" -or $_.CommandLine -like "*server.py*" } |
    ForEach-Object { $_.Kill(); Write-Host "Killed PID $($_.Id)" }

Write-Host ""
Write-Host "OK  Uninstalled."
