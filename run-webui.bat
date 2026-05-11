@echo off
REM Launch the web UI using the project venv.
setlocal
set ROOT=%~dp0
set PY=%ROOT%.venv\Scripts\python.exe
if not exist "%PY%" (
    echo Project venv not found at %PY%.
    echo Create it first:
    echo   python -m venv .venv
    echo   .venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-local.txt -r requirements-webui.txt
    exit /b 1
)
"%PY%" -m webui %*
