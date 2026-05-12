@echo off
REM Launch the web UI — tries .venv, then LOCALAPPDATA, then PATH.
setlocal
set ROOT=%~dp0

REM 1 — project .venv (skip if uvicorn isn't installed inside it)
set PY=%ROOT%.venv\Scripts\python.exe
if exist "%PY%" (
    "%PY%" -c "import uvicorn" >nul 2>&1 && goto :launch
    echo [webui] .venv found but missing uvicorn, skipping...
)

REM 2 — python.org per-user install (avoids WindowsApps 0-byte stub)
set PY=%LOCALAPPDATA%\Python\bin\python.exe
if exist "%PY%" goto :launch

REM 3 — whatever python is on PATH
where python >nul 2>&1
if not errorlevel 1 (
    set PY=python
    goto :launch
)

echo [webui] ERROR: no Python found. Install Python or create a .venv.
pause
exit /b 1

:launch
echo [webui] using %PY%
"%PY%" -m webui %*
echo [webui] Server exited with code %errorlevel%.
pause
