@echo off
REM =============================================================================
REM run.bat - start the InvisibleAI backend (and the optional C x4 screenshot
REM daemon) on Windows.
REM
REM   run.bat            start the backend server and the screenshot daemon
REM   run.bat nodaemon   start only the backend server
REM   run.bat stop       stop both
REM
REM Optional environment variables:
REM   BACKEND_PORT   server port (default 3000). The overlay and the daemon use
REM                  the same variable, so set it for them too if you change it.
REM   BIND_HOST      interface to listen on (default 127.0.0.1 = this PC only).
REM
REM Python: uses .venv\Scripts\python.exe when present, else python on PATH.
REM Output:  logs\server.log (backend)   logs\daemon.log (screenshot daemon)
REM
REM NOTE: keep this file saved with Windows (CRLF) line endings and plain ASCII.
REM =============================================================================
setlocal enableextensions
cd /d "%~dp0"

if not defined BACKEND_PORT set "BACKEND_PORT=3000"
if not defined BIND_HOST set "BIND_HOST=127.0.0.1"
if /i "%~1"=="stop" goto stop

REM ---- 1. Find Python (prefer the project venv) ------------------------------
set "PY=.venv\Scripts\python.exe"
set "PYW=.venv\Scripts\pythonw.exe"
if exist "%PY%" goto have_python
where python >nul 2>&1
if errorlevel 1 goto no_python
set "PY=python"
set "PYW=pythonw"
:have_python

REM ---- 2. Check the packages the app really needs ----------------------------
"%PY%" -c "import flask, flask_sock, pynput, openai, dotenv, PIL, mss, numpy, pypdf, docx" >nul 2>&1
if errorlevel 1 goto missing_deps

REM ---- 3. Friendly warning if there is no .env -------------------------------
if exist ".env" goto env_ok
echo WARNING: no .env file found, so AI features will not work.
echo          Run:  copy .env.example .env   then put your OPENAI_API_KEY in it.
echo.
:env_ok

if not exist logs mkdir logs

REM ---- 4. Backend server ------------------------------------------------------
call :port_listening
if not errorlevel 1 goto server_already
echo Starting backend on http://%BIND_HOST%:%BACKEND_PORT% ...
start "InvisibleAI Backend" /min cmd /c "%PY% server.py --host %BIND_HOST% --port %BACKEND_PORT% >> logs\server.log 2>&1"
goto server_started
:server_already
echo Backend is already running on port %BACKEND_PORT% - leaving it as it is.
:server_started

REM ---- 5. Screenshot daemon (C x4) -------------------------------------------
REM On Windows, daemon.py's own "already running" check can TERMINATE the process
REM whose id is stored in daemon.pid, so we never start it while that file points
REM at a live Python process, and we clear the file when it is stale.
if /i "%~1"=="nodaemon" goto wait_server
if not exist daemon.pid goto start_daemon
set "DPID="
set /p DPID=<daemon.pid
tasklist /FI "PID eq %DPID%" 2>nul | find /i "python" >nul
if errorlevel 1 goto stale_pid
echo Screenshot daemon is already running (PID %DPID%) - not starting another.
echo If that is wrong, delete daemon.pid and run this again.
goto wait_server
:stale_pid
echo Removing stale daemon.pid (process %DPID% is not a Python process).
del /q daemon.pid
:start_daemon
echo Starting screenshot daemon (press C four times quickly to capture) ...
start "InvisibleAI Daemon" /min %PYW% daemon.py

REM ---- 6. Wait until the backend answers (up to 40 seconds) ------------------
:wait_server
set /a TRIES=0
:wait_loop
call :port_listening
if not errorlevel 1 goto server_up
set /a TRIES+=1
if %TRIES% geq 40 goto server_slow
timeout /t 1 /nobreak >nul
goto wait_loop
:server_up
echo.
echo Backend is up:  http://%BIND_HOST%:%BACKEND_PORT%
goto summary
:server_slow
echo.
echo The backend is still starting, or failed to start. Check logs\server.log
:summary
echo Logs:  logs\server.log   logs\daemon.log
echo Now start the overlay in another window:  cd ..\overlay_app   then   npm start
echo Stop everything later with:  run.bat stop
echo.
pause
exit /b 0

REM ---- Error exits ------------------------------------------------------------
:no_python
echo ERROR: Python was not found. Install Python 3.12 from python.org and tick
echo        "Add python.exe to PATH", then in this folder run:
echo   py -3.12 -m venv .venv
echo   .venv\Scripts\activate
echo   pip install pynput==1.8.2 flask==3.0.3 flask-sock==0.7.0 mss==9.0.2 Pillow==11.3.0 numpy==1.26.4 openai==1.68.2 pypdf==5.1.0 python-docx==1.1.2 python-dotenv==1.0.1
pause
exit /b 1

:missing_deps
echo ERROR: some required Python packages are missing for %PY%. In this folder run:
echo   py -3.12 -m venv .venv
echo   .venv\Scripts\activate
echo   pip install pynput==1.8.2 flask==3.0.3 flask-sock==0.7.0 mss==9.0.2 Pillow==11.3.0 numpy==1.26.4 openai==1.68.2 pypdf==5.1.0 python-docx==1.1.2 python-dotenv==1.0.1
echo (Do not use requirements.txt: it still lists the large OCR packages that are switched off.)
pause
exit /b 1

REM ---- run.bat stop -----------------------------------------------------------
:stop
echo Stopping the InvisibleAI backend and screenshot daemon ...
if not exist daemon.pid goto stop_server
set "DPID="
set /p DPID=<daemon.pid
tasklist /FI "PID eq %DPID%" 2>nul | find /i "python" >nul
if errorlevel 1 goto stop_pid_file
taskkill /f /pid %DPID% >nul 2>&1
:stop_pid_file
del /q daemon.pid 2>nul
:stop_server
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":%BACKEND_PORT% .*LISTENING"') do taskkill /f /pid %%P >nul 2>&1
echo Done.
exit /b 0

REM ---- Subroutine: is something LISTENING on BACKEND_PORT? (errorlevel 0 = yes)
:port_listening
netstat -ano | findstr /R /C:":%BACKEND_PORT% .*LISTENING" >nul
exit /b %errorlevel%
