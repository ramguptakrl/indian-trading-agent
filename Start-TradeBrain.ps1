[CmdletBinding()]
param(
    [int]$BackendPort = 0,
    [int]$FrontendPort = 0,
    [switch]$NoBrowser,
    [switch]$SkipInstall,
    [switch]$SetupOnly,
    [switch]$CheckOnly,
    [switch]$SmokeTest
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version 2.0

$RootDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $RootDir

if ($BackendPort -le 0) {
    if ($env:BACKEND_PORT) { $BackendPort = [int]$env:BACKEND_PORT } else { $BackendPort = 8000 }
}
if ($FrontendPort -le 0) {
    if ($env:FRONTEND_PORT) { $FrontendPort = [int]$env:FRONTEND_PORT } else { $FrontendPort = 3000 }
}

if ($FrontendPort -notin @(3000, 3001)) {
    throw "FrontendPort must be 3000 or 3001 because those origins are explicitly allowed by the Trade Brain backend."
}

$BackendHealthUrl = "http://127.0.0.1:$BackendPort/api/health"
$FrontendHealthUrl = "http://127.0.0.1:$FrontendPort"
$FrontendUrl = "http://localhost:$FrontendPort"
$LogDir = Join-Path $RootDir ".tradebrain\logs"
$BackendOut = Join-Path $LogDir "backend.out.log"
$BackendErr = Join-Path $LogDir "backend.err.log"
$FrontendOut = Join-Path $LogDir "frontend.out.log"
$FrontendErr = Join-Path $LogDir "frontend.err.log"
$KiteOut = Join-Path $LogDir "kite-live.out.log"
$KiteErr = Join-Path $LogDir "kite-live.err.log"
$VenvPython = Join-Path $RootDir "venv\Scripts\python.exe"

function Write-Step([string]$Message) { Write-Host "[start] $Message" -ForegroundColor Cyan }
function Write-Ok([string]$Message)   { Write-Host "[ok]    $Message" -ForegroundColor Green }
function Write-Warn([string]$Message) { Write-Host "[warn]  $Message" -ForegroundColor Yellow }

function Get-SystemPython {
    # Prefer python.exe from PATH. This respects an explicitly configured
    # interpreter (including actions/setup-python and normal Windows PATH).
    $python = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($python) { return @{ File = $python.Source; Prefix = @() } }

    $py = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($py) { return @{ File = $py.Source; Prefix = @("-3") } }

    throw "Python 3.10+ was not found. Install Python from python.org and enable the Python launcher/PATH option."
}

function Invoke-SystemPython {
    param([hashtable]$Launcher, [string[]]$Arguments)
    & $Launcher.File @($Launcher.Prefix) @Arguments
    if ($LASTEXITCODE -ne 0) { throw "System Python command failed with exit code $LASTEXITCODE." }
}

function Assert-ToolVersions {
    $launcher = Get-SystemPython
    $pyVersion = (& $launcher.File @($launcher.Prefix) -c "import sys; print('.'.join(map(str, sys.version_info[:3])))").Trim()
    if ($LASTEXITCODE -ne 0) { throw "Unable to query Python version." }
    $pyParts = $pyVersion.Split('.')
    if ([int]$pyParts[0] -lt 3 -or ([int]$pyParts[0] -eq 3 -and [int]$pyParts[1] -lt 10)) {
        throw "Python $pyVersion is too old. Trade Brain requires Python 3.10+."
    }

    $node = Get-Command node.exe -ErrorAction SilentlyContinue
    if (-not $node) { throw "Node.js 20+ was not found. Install Node.js 20 LTS or newer." }
    $nodeVersion = (& $node.Source -p "process.versions.node").Trim()
    if ($LASTEXITCODE -ne 0) { throw "Unable to query Node.js version." }
    if ([int]($nodeVersion.Split('.')[0]) -lt 20) {
        throw "Node.js $nodeVersion is too old. Trade Brain requires Node.js 20+."
    }

    $npm = Get-Command npm.cmd -ErrorAction SilentlyContinue
    if (-not $npm) { $npm = Get-Command npm.exe -ErrorAction SilentlyContinue }
    if (-not $npm) { throw "npm was not found next to Node.js." }

    Write-Ok "Python $pyVersion"
    Write-Ok "Node.js $nodeVersion"
    return @{ Python = $launcher; Npm = $npm.Source }
}

function Install-IfNeeded {
    param([hashtable]$Tools)

    if (-not (Test-Path $VenvPython)) {
        Write-Step "Creating Python virtual environment..."
        Invoke-SystemPython -Launcher $Tools.Python -Arguments @("-m", "venv", "venv")
    }

    $runtimeReady = $false
    try {
        & $VenvPython -c "import fastapi, uvicorn, aiosqlite, numpy, feedparser, dotenv, langchain_core, tradingagents" 2>$null
        if ($LASTEXITCODE -eq 0) { $runtimeReady = $true }
    } catch { $runtimeReady = $false }

    if (-not $runtimeReady) {
        Write-Step "Installing Trade Brain Python dependencies..."
        & $VenvPython -m pip install --upgrade pip
        if ($LASTEXITCODE -ne 0) { throw "pip upgrade failed." }
        & $VenvPython -m pip install -e . fastapi uvicorn aiosqlite numpy feedparser
        if ($LASTEXITCODE -ne 0) { throw "Python dependency installation failed." }
    } else {
        Write-Ok "Python environment ready."
    }

    $nodeModules = Join-Path $RootDir "frontend\node_modules"
    if (-not (Test-Path $nodeModules)) {
        Write-Step "Installing frontend dependencies..."
        Push-Location (Join-Path $RootDir "frontend")
        try {
            if (Test-Path "package-lock.json") { & $Tools.Npm ci } else { & $Tools.Npm install }
            if ($LASTEXITCODE -ne 0) { throw "npm dependency installation failed." }
        } finally {
            Pop-Location
        }
    } else {
        Write-Ok "Frontend dependencies ready."
    }
}

function Assert-PortFree([int]$Port) {
    $pids = @()
    if (Get-Command Get-NetTCPConnection -ErrorAction SilentlyContinue) {
        $listeners = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
        $pids = @($listeners | Select-Object -ExpandProperty OwningProcess -Unique)
    } else {
        $matches = @(netstat -ano -p tcp | Select-String -Pattern (":$Port\s+.*LISTENING\s+(\d+)$"))
        foreach ($match in $matches) {
            if ($match.Matches.Count -gt 0) { $pids += [int]$match.Matches[0].Groups[1].Value }
        }
    }
    if ($pids.Count -gt 0) {
        throw "Port $Port is already in use by PID(s): $($pids -join ', '). Stop that process or choose another port."
    }
}

function Show-LogTail([string]$Path, [string]$Label) {
    if (Test-Path $Path) {
        Write-Warn "$Label last 30 lines:"
        Get-Content $Path -Tail 30 -ErrorAction SilentlyContinue
    }
}

function Wait-Healthy {
    param(
        [string]$Url,
        [string]$Label,
        [System.Diagnostics.Process]$Process,
        [string]$OutLog,
        [string]$ErrLog,
        [int]$TimeoutSeconds = 90
    )

    $watch = [System.Diagnostics.Stopwatch]::StartNew()
    $nextProgress = 5
    while ($watch.Elapsed.TotalSeconds -lt $TimeoutSeconds) {
        if ($Process.HasExited) {
            Show-LogTail -Path $OutLog -Label "$Label output"
            Show-LogTail -Path $ErrLog -Label "$Label errors"
            throw "$Label exited before becoming healthy (exit code $($Process.ExitCode))."
        }
        try {
            $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 400) {
                $watch.Stop()
                return
            }
        } catch { }

        if ($watch.Elapsed.TotalSeconds -ge $nextProgress) {
            Write-Step "$Label starting... ($([int]$watch.Elapsed.TotalSeconds)s)"
            $nextProgress += 5
        }
        Start-Sleep -Milliseconds 500
    }

    $watch.Stop()
    Show-LogTail -Path $OutLog -Label "$Label output"
    Show-LogTail -Path $ErrLog -Label "$Label errors"
    throw "$Label did not become healthy within $TimeoutSeconds seconds."
}

function Stop-ProcessTree {
    param([System.Diagnostics.Process]$Process)
    if (-not $Process) { return }
    try {
        if (-not $Process.HasExited) {
            & "$env:SystemRoot\System32\taskkill.exe" /PID $Process.Id /T /F *> $null
        }
    } catch { }
}

Write-Host ""
Write-Host "Trade Brain - Windows launcher" -ForegroundColor White
Write-Host "Advisory only | Broker order execution disabled" -ForegroundColor DarkGray
Write-Host ""

$tools = Assert-ToolVersions

if ($CheckOnly) {
    Write-Ok "Windows launcher preflight passed."
    exit 0
}

if ($SkipInstall) {
    if (-not (Test-Path $VenvPython)) { throw "-SkipInstall was used but venv\Scripts\python.exe does not exist." }
    if (-not (Test-Path (Join-Path $RootDir "frontend\node_modules"))) { throw "-SkipInstall was used but frontend\node_modules does not exist." }
} else {
    Install-IfNeeded -Tools $tools
}

if ($SetupOnly) {
    Write-Ok "Windows setup complete. Double-click Start-TradeBrain.bat to launch."
    exit 0
}

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
Assert-PortFree -Port $BackendPort
Assert-PortFree -Port $FrontendPort

$backendProcess = $null
$frontendProcess = $null
$kiteProcess = $null

try {
    Write-Step "Starting backend on port $BackendPort..."
    $backendProcess = Start-Process -FilePath $VenvPython `
        -ArgumentList @("-m", "uvicorn", "backend.app:app", "--host", "127.0.0.1", "--port", "$BackendPort") `
        -WorkingDirectory $RootDir `
        -RedirectStandardOutput $BackendOut `
        -RedirectStandardError $BackendErr `
        -PassThru

    $kiteReady = (& $VenvPython -c "from dotenv import dotenv_values; c=dotenv_values('.env'); ks=('KITE_API_KEY','KITE_ACCESS_TOKEN','KITE_LIVE_SUBSCRIPTIONS'); print('1' if all(str(c.get(k) or '').strip() for k in ks) else '0')").Trim()
    if ($LASTEXITCODE -ne 0) { $kiteReady = "0" }

    if ($kiteReady -eq "1") {
        Write-Step "Starting Kite MARKET_DATA_ONLY live stream..."
        $kiteProcess = Start-Process -FilePath $VenvPython `
            -ArgumentList @("scripts\tradebrain_kite_live_stream.py") `
            -WorkingDirectory $RootDir `
            -RedirectStandardOutput $KiteOut `
            -RedirectStandardError $KiteErr `
            -PassThru
    } else {
        Write-Step "Kite live stream not configured; labelled fallback policy remains available."
    }

    # Keep the browser client pointed at the same backend port chosen here.
    $env:NEXT_PUBLIC_API_URL = "http://localhost:$BackendPort"

    Write-Step "Starting frontend on port $FrontendPort..."
    $frontendProcess = Start-Process -FilePath $env:ComSpec `
        -ArgumentList @("/d", "/s", "/c", "npm run dev -- --port $FrontendPort") `
        -WorkingDirectory (Join-Path $RootDir "frontend") `
        -RedirectStandardOutput $FrontendOut `
        -RedirectStandardError $FrontendErr `
        -PassThru

    Wait-Healthy -Url $BackendHealthUrl -Label "Backend" -Process $backendProcess -OutLog $BackendOut -ErrLog $BackendErr
    Write-Ok "Backend ready at http://localhost:$BackendPort"
    Wait-Healthy -Url $FrontendHealthUrl -Label "Frontend" -Process $frontendProcess -OutLog $FrontendOut -ErrLog $FrontendErr
    Write-Ok "Frontend ready at $FrontendUrl"

    if ($kiteProcess) {
        Start-Sleep -Seconds 1
        if ($kiteProcess.HasExited) {
            Write-Warn "Kite stream exited; the app will continue without it."
            Show-LogTail -Path $KiteErr -Label "Kite errors"
            $kiteProcess = $null
        } else {
            Write-Ok "Kite MARKET_DATA_ONLY stream process running."
        }
    }

    if ($SmokeTest) {
        Write-Ok "Windows end-to-end smoke passed: backend + frontend became healthy."
        exit 0
    }

    if (-not $NoBrowser) {
        Write-Step "Opening Trade Brain in your browser..."
        Start-Process $FrontendUrl
    }

    Write-Host ""
    Write-Ok "Trade Brain is running."
    Write-Host "  Interface:       $FrontendUrl"
    Write-Host "  Backend output:  $BackendOut"
    Write-Host "  Backend errors:  $BackendErr"
    Write-Host "  Frontend output: $FrontendOut"
    Write-Host "  Frontend errors: $FrontendErr"
    if ($kiteProcess) { Write-Host "  Kite live output:$KiteOut" }
    Write-Host ""
    Write-Step "Keep this window open. Press Ctrl+C to stop Trade Brain."

    while ($true) {
        Start-Sleep -Seconds 2
        if ($backendProcess.HasExited) {
            Show-LogTail -Path $BackendErr -Label "Backend errors"
            throw "Backend exited unexpectedly."
        }
        if ($frontendProcess.HasExited) {
            Show-LogTail -Path $FrontendErr -Label "Frontend errors"
            throw "Frontend exited unexpectedly."
        }
        if ($kiteProcess -and $kiteProcess.HasExited) {
            Write-Warn "Kite stream stopped; Trade Brain remains advisory-only and continues through permitted fallback sources."
            Show-LogTail -Path $KiteErr -Label "Kite errors"
            $kiteProcess = $null
        }
    }
} finally {
    Write-Step "Stopping Trade Brain processes..."
    Stop-ProcessTree -Process $kiteProcess
    Stop-ProcessTree -Process $frontendProcess
    Stop-ProcessTree -Process $backendProcess
    Write-Ok "Stopped."
}
