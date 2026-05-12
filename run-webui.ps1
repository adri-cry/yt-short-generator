# Launch the web UI — tries .venv, then LOCALAPPDATA, then PATH.
$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Definition
$venvPy = Join-Path $root ".venv\Scripts\python.exe"
$localPy = Join-Path $env:LOCALAPPDATA "Python\bin\python.exe"
$pythonExe = $null

# 1 — project .venv (skip if uvicorn isn't installed)
if (Test-Path -LiteralPath $venvPy) {
    & $venvPy -c "import uvicorn" 2>$null
    if ($LASTEXITCODE -eq 0) {
        $pythonExe = $venvPy
    } else {
        Write-Host "[webui] .venv found but missing uvicorn, skipping..." -ForegroundColor Yellow
    }
}

# 2 — python.org per-user install (avoids WindowsApps 0-byte stub)
if (-not $pythonExe -and (Test-Path -LiteralPath $localPy)) {
    Write-Host "[webui] .venv not found, using LOCALAPPDATA Python..." -ForegroundColor Yellow
    $pythonExe = $localPy
}

# 3 — whatever python is on PATH (skip 0-byte stubs)
if (-not $pythonExe) {
    Write-Host "[webui] .venv not found, searching PATH..." -ForegroundColor Yellow
    $candidates = Get-Command python -ErrorAction SilentlyContinue
    foreach ($c in $candidates) {
        if ((Get-Item $c.Source).Length -gt 0) {
            $pythonExe = $c.Source
            break
        }
    }
    if (-not $pythonExe) {
        Write-Error "No real Python found. Install Python or create a .venv."
        exit 1
    }
}

$webuiArgs = @("-m", "webui") + $args
Write-Host "[webui] launching $pythonExe -m webui" -ForegroundColor Cyan
& $pythonExe @webuiArgs

if (-not $?) {
    Write-Host "[webui] Server exited with code $LASTEXITCODE" -ForegroundColor Red
}
Read-Host "Press Enter to exit"