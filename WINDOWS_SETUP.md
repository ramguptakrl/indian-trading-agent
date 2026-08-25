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

## Secure Kite setup on this PC

Do **not** paste your API secret or access token into chat, source code, a GitHub issue, or a committed file.

First make sure the Windows environment is installed:

```powershell
.\Start-TradeBrain.ps1 -SetupOnly
```

Then run the local auth helper using the project virtual environment:

```powershell
.\venv\Scripts\python.exe scripts\tradebrain_kite_auth.py
```

The helper will:

1. ask for the API key if it is not already in local `.env`;
2. ask for the API secret using a hidden prompt (the helper does **not** save the secret);
3. open Zerodha's documented Kite Connect login page;
4. ask you to paste the short-lived `request_token` value returned in the redirect URL;
5. exchange it locally for the session `access_token`;
6. validate the session with a **read-only `NSE:BSE` LTP request**;
7. save only `KITE_API_KEY`, `KITE_ACCESS_TOKEN` and `KITE_LIVE_SUBSCRIPTIONS` into the repository-local `.env`;
8. write a credential-redacted success record to the Trade Brain TXT audit trail.

`.env` is already excluded by `.gitignore` and must remain local/private.

After a successful session setup, start normally:

```text
Start-TradeBrain.bat
```

Kite remains `MARKET_DATA_ONLY`. The auth helper contains no place/modify/cancel-order path.

## Human-readable Trade Brain audit TXT

Runtime audit records are append-only daily text files. Default location:

```text
%USERPROFILE%\.tradingagents\tradebrain\audit_txt\tradebrain-audit-YYYY-MM-DD.txt
```

The audit contains readable structured records for:

- final advisory inputs and strict parsed candidate fields;
- deterministic gate outcome and concise rationale summary;
- Entry / Stop-Loss / Take-Profit geometry when present;
- evidence-baseline / learning updates;
- prospective-hypothesis checks and interpretation;
- Kite read-only session validation;
- explicit advisory/execution boundaries and provenance.

Credential-like fields are automatically redacted. Hidden model chain-of-thought is **not** persisted; the file stores concise rationale/evidence summaries instead.

A custom private audit folder can be set in local `.env`:

```text
TRADEBRAIN_AUDIT_DIR=C:\private\TradeBrainAudit
```

GitHub regression runs also publish a `tradebrain-test-audit-txt` artifact containing the raw unittest text output plus `tradebrain-test-interpretation.txt`, which explains what a PASS/FAIL means without claiming trading profitability.

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

## Kite runtime fields

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
