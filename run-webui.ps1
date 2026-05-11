# Launch the web UI using the project venv, not whatever python.exe is first on PATH.
$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Definition
$py = Join-Path $root ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $py)) {
    Write-Error "Project venv not found at $py. Create it with:`n  python -m venv .venv`n  .\.venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-local.txt -r requirements-webui.txt"
    exit 1
}

$webuiArgs = @("-m", "webui") + $args
Write-Host "[run-webui] launching $py -m webui $args" -ForegroundColor Cyan
& $py @webuiArgs
