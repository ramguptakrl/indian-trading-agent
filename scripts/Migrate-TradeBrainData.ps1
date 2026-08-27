[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
Set-StrictMode -Version 2.0

$RootDir = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$SourceRoot = Join-Path $env:USERPROFILE ".tradingagents"
$SourceDb = Join-Path $SourceRoot "trading_agent.db"
$SourceTradeBrain = Join-Path $SourceRoot "tradebrain"
$DestRoot = Join-Path $RootDir ".tradebrain"
$DestDb = Join-Path $DestRoot "trading_agent.db"
$EnvPath = Join-Path $RootDir ".env"
$VenvPython = Join-Path $RootDir "venv\Scripts\python.exe"
$Timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$BackupRoot = Join-Path $DestRoot "backups\pre-centralize-$Timestamp"

Write-Host "Trade Brain local-data migration" -ForegroundColor White
Write-Host "COPY FIRST: the old C-drive data will NOT be deleted." -ForegroundColor Yellow
Write-Host "Source: $SourceRoot"
Write-Host "Target: $DestRoot"
Write-Host ""

if (-not (Test-Path $SourceDb)) {
    throw "Source database not found: $SourceDb"
}
if (-not (Test-Path $EnvPath)) {
    throw "Local .env not found: $EnvPath"
}
if (-not (Test-Path $VenvPython)) {
    throw "Trade Brain venv Python not found: $VenvPython"
}

New-Item -ItemType Directory -Force -Path $DestRoot | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $DestRoot "models") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $DestRoot "ml_runs") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $DestRoot "backups") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $DestRoot "audit_txt") | Out-Null

if (Test-Path $DestDb) {
    New-Item -ItemType Directory -Force -Path $BackupRoot | Out-Null
    Copy-Item -LiteralPath $DestDb -Destination (Join-Path $BackupRoot "trading_agent.db") -Force
    Write-Host "[backup] Existing D-drive database copied to $BackupRoot" -ForegroundColor Cyan
}

# Use SQLite's backup API rather than a raw file copy so the destination is a
# transactionally consistent snapshot even if another process briefly has the source open.
$env:TB_MIGRATE_SOURCE_DB = $SourceDb
$env:TB_MIGRATE_DEST_DB = $DestDb
& $VenvPython -c "import os, sqlite3, pathlib; src=pathlib.Path(os.environ['TB_MIGRATE_SOURCE_DB']); dst=pathlib.Path(os.environ['TB_MIGRATE_DEST_DB']); dst.parent.mkdir(parents=True, exist_ok=True); a=sqlite3.connect(str(src)); b=sqlite3.connect(str(dst)); a.backup(b); b.close(); a.close(); print('SQLite backup complete:', dst)"
if ($LASTEXITCODE -ne 0) {
    throw "SQLite backup failed. The original C-drive database is unchanged."
}
Remove-Item Env:TB_MIGRATE_SOURCE_DB -ErrorAction SilentlyContinue
Remove-Item Env:TB_MIGRATE_DEST_DB -ErrorAction SilentlyContinue

if (Test-Path $SourceTradeBrain) {
    Get-ChildItem -LiteralPath $SourceTradeBrain -Force | ForEach-Object {
        Copy-Item -LiteralPath $_.FullName -Destination $DestRoot -Recurse -Force
    }
    Write-Host "[copy] Study state / audits / archived Trade Brain runtime data merged into D:." -ForegroundColor Green
} else {
    Write-Host "[warn] No legacy Trade Brain subfolder found at $SourceTradeBrain; database migration continues." -ForegroundColor Yellow
}

# Update exactly one local setting while preserving all API keys/secrets already in .env.
$desired = "TRADEBRAIN_DATA_DIR=$DestRoot"
$envText = [System.IO.File]::ReadAllText($EnvPath)
if ($envText -match '(?m)^TRADEBRAIN_DATA_DIR=.*$') {
    $envText = [System.Text.RegularExpressions.Regex]::Replace(
        $envText,
        '(?m)^TRADEBRAIN_DATA_DIR=.*$',
        [System.Text.RegularExpressions.MatchEvaluator]{ param($m) $desired }
    )
} else {
    if ($envText.Length -gt 0 -and -not $envText.EndsWith("`n")) { $envText += "`r`n" }
    $envText += "$desired`r`n"
}
[System.IO.File]::WriteAllText($EnvPath, $envText, (New-Object System.Text.UTF8Encoding($false)))
Write-Host "[env] TRADEBRAIN_DATA_DIR now points to $DestRoot" -ForegroundColor Green

# Verify that the freshly pulled code resolves the D-drive DB and that BSE candles exist.
# Pipe a literal Python program over stdin so PowerShell never parses SQL punctuation.
$VerificationPython = @'
from dotenv import load_dotenv
load_dotenv(".env", override=True)

import sqlite3
import backend.db as d

print("Resolved DB:", d.DB_PATH)
conn = sqlite3.connect(d.DB_PATH)
rows = conn.execute(
    "SELECT interval, COUNT(1) FROM tb_ohlcv_bars GROUP BY interval ORDER BY interval"
).fetchall()
print("OHLCV counts:", rows)
total = sum(row[1] for row in rows)
conn.close()
assert total > 0, "No OHLCV rows found in migrated database"
print("TOTAL OHLCV:", total)
'@

Push-Location $RootDir
try {
    $VerificationPython | & $VenvPython -
    if ($LASTEXITCODE -ne 0) {
        throw "Verification failed. Do NOT delete the C-drive source."
    }
} finally {
    Pop-Location
}

Write-Host ""
Write-Host "[PASS] Trade Brain runtime data is now copied and configured under:" -ForegroundColor Green
Write-Host "       $DestRoot"
Write-Host "[SAFE] Original source was NOT deleted:" -ForegroundColor Green
Write-Host "       $SourceRoot"
Write-Host "Keep the C-drive copy until we finish a normal Trade Brain launch verification." -ForegroundColor Yellow
