# Indian Trading Agent Trial / Trade Brain — Current Project State

Last canonical checkpoint: **2026-08-24**  
Repository: `ramguptakrl/indian-trading-agent`  
Development branch: `tradebrain/reframe-foundation`  
Pull request: **#1** — OPEN, DRAFT, intentionally UNMERGED  
Current product version: **Trade Brain v0.12.1**

## Project identity

This repository is the evolved **Indian Trading Agent Trial → BSE Engine / Trade Engine → Trade Brain** project.

**Kronos-BSE is a separate, unrelated project. Do not mix it into this repository.**

Similarity of instrument, broker, Python, backtesting, forecasting, or trading terminology is not permission to reuse another project's state. Cross-project reuse requires an explicit owner request.

For continuation questions, use this priority:

1. current code on `tradebrain/reframe-foundation`
2. this `PROJECT_STATE.md`
3. `AGENTS.md`
4. canonical `TRADEBRAIN_*.md` documents
5. current PR description and validated CI state
6. conversation memory only where it does not conflict with the above

## Product doctrine

Trade Brain is an audited Indian-equity research/advisory system focused initially on **BSE Ltd (`NSE:BSE`)**.

Modeled trader: `RESIDENT_INDIAN`.

Active modes:

- `INTRADAY`: LONG or SHORT cash-market equity; same-session only; no fresh entry from 15:10 IST; intended flat by 15:15 IST.
- `SWING`: LONG-only cash/delivery using own cash; may cross sessions.

Not active:

- MTF / funded delivery
- rescue-lot architecture
- F&O execution
- hidden leverage
- automatic broker order placement

Historical aliases may remain only for compatibility/audit purposes.

## Advisory / execution boundary

Every final Trade Brain output is non-executing:

```text
advisory_only = true
trade_authorization = false
order_execution_allowed = false
```

Safe current candidate labels:

- `LONG_CANDIDATE`
- `SHORT_CANDIDATE`
- `EXIT_CANDIDATE`
- `WAIT`
- `NO_TRADE`

AI/LLM output is research evidence and candidate generation, not final authority. Deterministic safety/data gates remain authoritative.

## Governing flow

```text
market data + provenance
        -> identity / corporate-event memory
        -> audited history / replay
        -> structure / regime / broader evidence
        -> multi-agent research
        -> strict candidate parser
        -> verified exchange calendar/session
        -> Crash Guard
        -> broker/exchange permission
        -> deterministic hard-rule gate
        -> approved soft preference
        -> resident transaction-cost scenario
        -> advisory only
        -> optional human-executed actual-trade journal
        -> future evidence / outcome learning
```

## Implemented Trade Brain foundation

The repository contains the Phase 0–10 control/evidence plane, including:

- deterministic Entry/SL/TP and protected time/safety rules
- official security identity/provenance framework
- corporate-event/document memory
- audited RAW_UNADJUSTED OHLCV storage and quality checks
- comparable price eras and derived timeframes
- look-ahead-safe replay (`ts_close <= as_of`)
- strict replay outcome states without guessing intrabar order
- Focus Instrument Lab
- frozen challenger / walk-forward governance
- human-approved soft runtime only
- resident equity transaction-cost model
- conservative paper ledger
- verified exchange-calendar capability
- Crash Guard / regime evidence
- fail-closed final advisory pipeline
- frontend analysis/advisory contract
- actual manual trade journal

Hard rules are protected and must not self-optimize.

## Zerodha / Kite state

Kite has already been implemented as a **read-only `MARKET_DATA_ONLY` data plane**.

Implemented code supports:

- exact instrument lookup
- historical REST candles
- audited/chunked long-range history sync
- REST LTP / OHLC / full quote
- WebSocket LTP / quote / full modes
- market depth in full mode
- persisted latest live quote state
- Kite-primary source policy
- explicitly labelled Yahoo/yfinance fallback/research source

There are no Trade Brain place/modify/cancel-order methods.

**Real Kite credentials have not yet been configured/authenticated, so authenticated historical/live success is not claimed.**

When credentials are supplied, remaining Kite work is operational validation, not architecture redesign.

## Actual manual trade journal

`ACTUAL_MANUAL_TRADE` is deliberately separate from hypothetical replay and paper/simulation evidence.

Implemented:

- advisory-linked and unlinked actual-trade records
- frozen advisory snapshot linkage
- preservation of advisory-vs-human direction mismatch
- actual entry fill, quantity, timestamp and optional broker reference
- `OPEN -> PARTIALLY_CLOSED -> CLOSED`
- separate partial-exit slices
- current quote marking
- estimated resident charges and net P&L
- actual-charge override support
- policy/time violation observations without erasing the real trade
- dedicated Actual Trades UI

UI actions update the journal only after the human acts externally at the broker. They never place an order.

## Windows deployment — COMPLETE AND CI-VALIDATED

Native Windows startup is now part of the branch.

Files:

- `Start-TradeBrain.ps1` — native PowerShell launcher
- `Start-TradeBrain.bat` — double-click wrapper
- `WINDOWS_SETUP.md` — Windows setup/use documentation
- `.github/workflows/tradebrain-windows.yml` — clean-Windows validation workflow

The Windows launcher now:

- checks Python 3.10+ and Node.js 20+
- respects an explicitly configured `python.exe` before the global `py` launcher
- creates `venv` on first run
- installs project/runtime Python dependencies when needed
- installs frontend dependencies when needed
- fails safely if required ports are already owned by another process
- starts FastAPI on local IPv4
- starts the Next.js interface
- uses IPv4 health probes to avoid Windows `localhost`/IPv6 ambiguity
- points the frontend at the selected backend port
- starts the Kite `MARKET_DATA_ONLY` sidecar only when required Kite runtime fields exist
- opens the browser in normal mode
- writes local logs under `.tradebrain\logs`
- stops only the process trees it created
- exposes `-CheckOnly`, `-SetupOnly`, `-NoBrowser`, and `-SmokeTest` modes

### Windows validation result

GitHub Actions **Trade Brain Windows run #6** (`32682639112`) on head `3c2af88cb59beaf3e367d51cd118b3210b65653f` completed **SUCCESS**.

Validated on a clean Windows Server 2025 runner with Python 3.11.9 and Node.js 20.20.2:

- PowerShell parser: PASS
- prerequisite preflight: PASS
- double-click BAT wrapper: PASS
- fresh Python virtual environment creation: PASS
- Python dependency installation: PASS
- frontend dependency installation: PASS
- backend startup: PASS
- `/api/health` reachable: PASS
- frontend startup: PASS
- frontend health reachable: PASS
- end-to-end Windows smoke: PASS
- cleanup: PASS

The smoke explicitly reported:

```text
Windows end-to-end smoke passed: backend + frontend became healthy.
```

This validates the browser-based Trade Brain interface on Windows through the native one-button launcher. It is not a packaged `.exe`; the supported UI remains the Next.js browser interface.

## General validation checkpoint

On the same runtime head, **Trade Brain Foundation run #318** (`32682639110`) completed successfully across its jobs.

Validated areas include:

- frontend production contract/build: PASS
- Python integration compile: PASS
- Trade Brain unit/integration suite: PASS
- Unix launcher syntax: PASS
- Phase 2 observational smoke: PASS / observational only
- Phase 3 observational smoke: PASS / observational only
- Phase 4 observational smoke: PASS / observational only
- Phase 5 observational smoke: PASS / observational only
- Phase 6 observational smoke: PASS / observational only
- Phase 10 observational smoke: PASS / observational only
- current BSE descriptive evidence rebuild/upload: PASS

The immediately preceding full checkpoint ran **136 / 136 Trade Brain tests successfully**; the Windows launcher changes did not change Trade Brain runtime logic and the same Foundation suite remains green.

## BSE evidence state

The BSE evidence baseline is deliberately descriptive/exploratory rather than a strategy-performance claim.

`BSE_PROSPECTIVE_HYPOTHESIS_001` was frozen for **future-only evidence after 2026-08-21**.

Historical observations used to create that hypothesis must not be backfilled as untouched validation.

The current evidence build still reports that the hypothesis **NEEDS_MORE_DATA**. This is expected: future market evidence must occur naturally and cannot be manufactured by code.

The prospective collector, schema, tests and API are already implemented. Remaining work here is accumulation of post-freeze BSE sessions and evaluation only after predefined sample/coverage gates are met.

## What is actually left

The architecture should not keep expanding with random features. At this checkpoint, the remaining work is external/ongoing rather than another large missing subsystem.

### 1. Authenticate and validate real Kite data when credentials are supplied

- configure API key/access token
- authenticate historical REST
- resolve the exact BSE instrument token
- pull audited Kite history
- compare Kite history with the labelled fallback baseline
- investigate material discrepancies
- validate read-only REST quotes
- validate read-only WebSocket
- verify live-state persistence and provenance

Do **not** add order endpoints.

### 2. Continue untouched prospective BSE evidence

- collect future post-freeze sessions
- never backfill pre-freeze observations into the prospective sample
- wait for predefined sample gates before performance claims
- evaluate frozen benchmark/challenger rules after sufficient evidence exists

### 3. Use the actual-trade journal when the human takes a trade

```text
Trade Brain advisory
    -> human executes externally
    -> I TOOK THIS TRADE
    -> record actual fill
    -> track / partial-close / close after external broker action
    -> compare real outcome with advisory/replay later
```

### Optional future work only if explicitly requested

- read-only broker reconciliation against the local journal
- additional hypotheses through the frozen-evidence protocol
- packaging the browser UI into a native `.exe` shell

None of these should silently introduce broker order execution.

## Repository / PR rule

Base branch: `main`  
Feature branch: `tradebrain/reframe-foundation`

PR #1 must remain:

- OPEN
- DRAFT
- UNMERGED

**Do not merge automatically.** Merge only when the project owner explicitly asks.

## Do not reintroduce without explicit owner decision

- Kronos-BSE code or state
- MTF / funded-delivery / rescue-lot logic
- automatic broker order placement
- raw BUY/SELL/HOLD final authority
- AI override of Crash Guard
- AI override of session timing
- AI override of broker restrictions
- fuzzy cross-exchange identity guessing
- same-sample optimization presented as validation
- automatic challenger promotion
- hidden leverage
