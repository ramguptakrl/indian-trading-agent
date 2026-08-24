# Trade Brain — Windows Setup

This is the supported native Windows launch path for the Indian Trading Agent Trial / Trade Brain project.

## What you need once

Install:

- Windows 10 or 11
- Python 3.10+ (3.11 recommended)
- Node.js 20+
- Git or GitHub Desktop only if you want to pull repository updates

Kite credentials are **not** required to start the application. Without Kite, the existing labelled fallback/research market-data policy remains available.

## One-button start

From the repository folder, double-click:

```text
Start-TradeBrain.bat
```

On the first run it will automatically:

1. verify Python and Node versions;
2. create `venv` if it does not exist;
3. install the Trade Brain Python/runtime dependencies;
4. install frontend dependencies if needed;
5. verify ports 8000 and 3000 are free;
6. start the FastAPI backend;
7. start the Next.js frontend;
8. start the Zerodha Kite `MARKET_DATA_ONLY` WebSocket sidecar only when the required runtime fields are present in `.env`;
9. wait until backend and frontend are healthy;
10. open `http://localhost:3000` in the default browser.

Keep the launcher window open while Trade Brain is running. Press `Ctrl+C` in that window to stop the processes started by the launcher.

The launcher does **not** kill unrelated programs that happen to own the configured ports. It fails with the owning PID instead.

## Logs

Windows launcher logs are written locally under:

```text
.tradebrain\logs\
```

Important files:

```text
backend.out.log
backend.err.log
frontend.out.log
frontend.err.log
kite-live.out.log
kite-live.err.log
```

Local `*.log` files are ignored by Git.

## Useful launcher modes

PowerShell can also invoke the launcher directly:

```powershell
# Verify Python/Node prerequisites only
.\Start-TradeBrain.ps1 -CheckOnly

# Perform first-run dependency setup, then exit
.\Start-TradeBrain.ps1 -SetupOnly

# Start without opening a browser
.\Start-TradeBrain.ps1 -NoBrowser

# Use alternate ports
.\Start-TradeBrain.ps1 -BackendPort 8001 -FrontendPort 3001

# CI/end-to-end health smoke: start, verify backend + frontend, stop
.\Start-TradeBrain.ps1 -SmokeTest -NoBrowser
```

`Start-TradeBrain.bat` invokes PowerShell with a process-local execution-policy bypass so a normal double-click does not require changing the machine-wide PowerShell policy.

## Kite later

When valid Zerodha credentials are configured, the same launcher automatically detects:

```text
KITE_API_KEY
KITE_ACCESS_TOKEN
KITE_LIVE_SUBSCRIPTIONS
```

and starts the existing read-only live market-data sidecar. Kite remains `MARKET_DATA_ONLY`; the launcher does not enable broker order placement.

## Execution boundary

Trade Brain remains an advisory/research system:

```text
advisory_only = true
trade_authorization = false
order_execution_allowed = false
```

Buttons in the Actual Trades journal record trades that the human executed externally at the broker; they do not place broker orders.
