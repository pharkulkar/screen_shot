@echo off
REM =============================================================================
REM run.bat — start both the daemon and the viewer server on Windows.
REM Double-click this file, or run it from a Command Prompt.
REM Both processes are started minimised; close this window to stop them.
REM =============================================================================

setlocal
cd /d "%~dp0"

where python >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: python not found on PATH. Install Python 3.8+ first.
    pause & exit /b 1
)

python -c "import pynput" >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: pynput not installed. Run:  pip install -r requirements.txt
    pause & exit /b 1
)

python -c "import flask" >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: flask not installed. Run:  pip install -r requirements.txt
    pause & exit /b 1
)

echo Starting screenshot daemon...
start "SilentScreenshotDaemon" /min pythonw daemon.py

timeout /t 2 /nobreak >nul

echo Starting screenshot viewer server...
start "SilentScreenshotServer" /min pythonw server.py

echo.
echo Both processes started.
echo Gallery: http://localhost:5000
echo Log:     %~dp0logs\daemon.log
echo.
echo Close this window to stop. (The background processes will keep running.)
echo To stop them, run:  taskkill /f /im pythonw.exe
pause
