<#
.SYNOPSIS
    Start the companysim dev servers on Windows. No Claude Code required.

.DESCRIPTION
    Loads .env, launches the FastAPI backend (8611) and the Vite frontend
    (5173) in their own windows, then waits until both genuinely serve and
    smoke-tests them.

    Both ports are hardcoded on the other side of the wire and cannot be
    changed independently: webapp/src/api/client.ts pins the API at 8611
    with no env override, and api/main.py pins CORS to localhost:5173.
    Change one without the other and you get a UI that renders perfectly
    and then fails every request.

.PARAMETER ApiOnly
    Start only the backend.

.PARAMETER WebOnly
    Start only the frontend.

.EXAMPLE
    .\scripts\start-dev.ps1
    .\scripts\start-dev.ps1 -ApiOnly
#>
[CmdletBinding()]
param(
    [switch]$ApiOnly,
    [switch]$WebOnly
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$startApi = -not $WebOnly
$startWeb = -not $ApiOnly

# --- .env ------------------------------------------------------------------
# Nothing in the app auto-loads this (no python-dotenv dependency), so the
# values have to be in the environment before uvicorn starts. Absent is
# fine: the app then runs with the LLM features off, which is not an error.
$envFile = Join-Path $root ".env"
if (Test-Path $envFile) {
    $loaded = 0
    Get-Content $envFile | ForEach-Object {
        if ($_ -match '^\s*[^#\s][^=]*=') {
            $name, $value = $_ -split '=', 2
            Set-Item -Path "Env:$($name.Trim())" -Value $value.Trim()
            $loaded++
        }
    }
    Write-Host "loaded $loaded variables from .env" -ForegroundColor DarkGray
} else {
    Write-Host ".env not found - LLM features will be off (not an error)" -ForegroundColor DarkGray
}

# --- prerequisites ---------------------------------------------------------
$python = Join-Path $root ".venv\Scripts\python.exe"
if ($startApi -and -not (Test-Path $python)) {
    Write-Host "No venv at .venv\Scripts\python.exe" -ForegroundColor Red
    Write-Host '  python -m venv .venv'
    Write-Host '  .venv\Scripts\activate'
    Write-Host '  pip install -e ".[dev,ml,viz,api,llm]"'
    exit 1
}
if ($startWeb -and -not (Test-Path (Join-Path $root "webapp\node_modules"))) {
    Write-Host "webapp\node_modules missing - run: cd webapp; npm install" -ForegroundColor Red
    exit 1
}

function Test-Port([int]$Port) {
    $c = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    return $null -ne $c
}

# --- launch ----------------------------------------------------------------
# Each server gets its own window so its log stays readable and Ctrl-C in
# that window stops just that server.
if ($startApi) {
    if (Test-Port 8611) {
        Write-Host "port 8611 already in use - skipping backend" -ForegroundColor Yellow
    } else {
        Write-Host "starting backend  -> http://localhost:8611"
        Start-Process powershell -ArgumentList @(
            "-NoExit", "-Command",
            "Set-Location '$root'; & '$python' -m uvicorn companysim.api.main:app --port 8611"
        )
    }
}
if ($startWeb) {
    if (Test-Port 5173) {
        Write-Host "port 5173 already in use - skipping frontend" -ForegroundColor Yellow
    } else {
        Write-Host "starting frontend -> http://localhost:5173"
        Start-Process powershell -ArgumentList @(
            "-NoExit", "-Command",
            "Set-Location '$root\webapp'; npm run dev"
        )
    }
}

# --- wait ------------------------------------------------------------------
# The backend runs `alembic upgrade head` from its lifespan hook, so the
# first start after a schema change takes noticeably longer than usual.
Write-Host "`nwaiting for readiness (up to 90s)..." -ForegroundColor DarkGray
$deadline = (Get-Date).AddSeconds(90)
$apiUp = -not $startApi
$webUp = -not $startWeb

while ((Get-Date) -lt $deadline -and -not ($apiUp -and $webUp)) {
    if (-not $apiUp) {
        try {
            $r = Invoke-WebRequest "http://localhost:8611/health" -UseBasicParsing -TimeoutSec 3
            if ($r.StatusCode -eq 200) { $apiUp = $true }
        } catch { }
    }
    if (-not $webUp) {
        try {
            $r = Invoke-WebRequest "http://localhost:5173/" -UseBasicParsing -TimeoutSec 3
            if ($r.StatusCode -eq 200) { $webUp = $true }
        } catch { }
    }
    if (-not ($apiUp -and $webUp)) { Start-Sleep -Milliseconds 700 }
}

# --- smoke -----------------------------------------------------------------
Write-Host "`n=== smoke ===" -ForegroundColor Cyan
$ok = $true

function Check([string]$Label, [string]$Url) {
    try {
        $r = Invoke-WebRequest $Url -UseBasicParsing -TimeoutSec 5
        Write-Host ("{0,-22} HTTP {1}" -f $Label, $r.StatusCode) -ForegroundColor Green
        return $true
    } catch {
        Write-Host ("{0,-22} FAILED" -f $Label) -ForegroundColor Red
        return $false
    }
}

if ($startApi) {
    if (-not (Check "GET /health" "http://localhost:8611/health"))          { $ok = $false }
    if (-not (Check "GET /orgs" "http://localhost:8611/orgs"))              { $ok = $false }
    if (-not (Check "GET /model/status" "http://localhost:8611/model/status")) { $ok = $false }
}
if ($startWeb) {
    if (-not (Check "GET /src/main.tsx" "http://localhost:5173/src/main.tsx")) { $ok = $false }
}

Write-Host ""
if ($ok) {
    if ($startApi) { Write-Host "API   http://localhost:8611      (Swagger UI: /docs)" }
    if ($startWeb) { Write-Host "WEB   http://localhost:5173" }
    Write-Host "stop  .\scripts\stop-dev.ps1"
    exit 0
} else {
    Write-Host "Something did not come up - check the server windows for the traceback." -ForegroundColor Red
    exit 1
}
