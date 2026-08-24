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

Every final Trade Brain output is non-executing:

```text
advisory_only = true
trade_authorization = false
order_execution_allowed = false
```

Safe candidate labels:

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
        -> audited history / look-ahead-safe replay
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

## Implemented foundation

The repository contains the Trade Brain Phase 0–10 control/evidence plane, including:

- deterministic Entry/SL/TP and protected time/safety rules
- official security identity/provenance framework
- corporate-event/document memory
- audited RAW_UNADJUSTED OHLCV and quality checks
- comparable price eras and derived timeframes
- look-ahead-safe replay (`ts_close <= as_of`)
- strict replay outcomes without guessing intrabar order
- Focus Instrument Lab
- frozen challenger / walk-forward governance
- human-approved soft runtime only
- resident equity transaction-cost model
- conservative paper ledger
- verified exchange-calendar capability
- Crash Guard / regime evidence
- fail-closed final advisory pipeline
- browser frontend analysis/advisory contract
- actual manual trade journal

Hard rules are protected and must not self-optimize.

## Zerodha / Kite state

Kite code is already implemented as a **read-only `MARKET_DATA_ONLY` data plane**.

Implemented capabilities include:

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

Journal UI actions update local evidence only after the human acts externally at the broker. They never place orders.

## Windows deployment — COMPLETE AND CI-VALIDATED

Native Windows startup is part of the branch:

- `Start-TradeBrain.ps1` — native PowerShell launcher
- `Start-TradeBrain.bat` — double-click wrapper
- `WINDOWS_SETUP.md` — Windows setup/use documentation
- `.github/workflows/tradebrain-windows.yml` — clean-Windows end-to-end validation

The launcher checks Python/Node, creates the venv, installs dependencies, checks ports without killing unrelated processes, starts FastAPI and Next.js, optionally starts the existing Kite `MARKET_DATA_ONLY` sidecar when credentials exist, opens the browser, writes local logs and cleans up only the process trees it created.

### Validated Windows baseline

Trade Brain Windows run **#6** (`32682639112`) on runtime head `3c2af88cb59beaf3e367d51cd118b3210b65653f` completed SUCCESS, and the documentation-triggered **run #7** also completed SUCCESS.

Validated on clean Windows Server 2025 with Python 3.11.9 / Node.js 20.20.2:

- PowerShell parse: PASS
- prerequisite preflight: PASS
- BAT wrapper: PASS
- fresh venv: PASS
- Python dependency install: PASS
- frontend dependency install: PASS
- backend startup / `/api/health`: PASS
- frontend startup / health: PASS
- end-to-end Windows smoke: PASS
- cleanup: PASS

The supported UI is the Next.js browser interface opened by the Windows launcher. A packaged `.exe` is optional future packaging, not required for current Windows operation.

## Frontend production security — PATCHED AND GATED

A production-only npm audit was added instead of ignoring installation warnings.

The first production audit correctly FAILED and exposed high-severity advisories in the prior dependency tree, including the `next@16.2.3` line and affected transitive packages.

Remediation was then performed through a controlled CI job that was required to pass both the production audit and production build before writing the new lockfile.

Validated dependency refresh run **#2** (`32683166357`) completed SUCCESS and committed the validated package/lock refresh as branch head `0f87cea764cc2eb6f8c9324321ef9ec8baf9c0a7`.

Current key frontend versions:

```text
next = 16.3.2
eslint-config-next = 16.3.2
react = 19.2.4
react-dom = 19.2.4
```

The refresh job passed:

- locked dependency installation: PASS
- explicit patched Next.js upgrade: PASS
- compatible transitive `npm audit fix`: PASS
- `npm audit --omit=dev --audit-level=high`: PASS
- `npm run build`: PASS
- validated package.json/package-lock.json commit: PASS

Permanent guardrail:

- `.github/workflows/tradebrain-security.yml` independently audits production dependencies for high/critical vulnerabilities.
- `.github/workflows/tradebrain-dependency-refresh.yml` provides a controlled/manual refresh path and never commits a refresh unless the production audit and frontend build both pass.

## General validation baseline

Trade Brain Foundation run **#318** (`32682639110`) completed successfully on the pre-security-remediation runtime head and validated:

- frontend production contract/build
- Python integration compile
- Trade Brain tests
- Unix launcher syntax
- Phase 2/3/4/5/6/10 observational smokes
- BSE descriptive evidence rebuild/upload

The immediately preceding full checkpoint recorded **136 / 136 Trade Brain tests passing**.

The patched frontend dependency commit does not modify Trade Brain decision logic. Normal Foundation, Windows and Security workflows are rerun after the patched dependency head to independently reconfirm the deployment baseline.

## BSE evidence state

The BSE evidence baseline is deliberately descriptive/exploratory rather than a strategy-performance claim.

`BSE_PROSPECTIVE_HYPOTHESIS_001` was frozen for **future-only evidence after 2026-08-21**. Historical observations used to create it must not be backfilled as untouched validation.

The prospective collector, schema, tests and API are implemented. The hypothesis currently remains **NEEDS_MORE_DATA**, which is expected because untouched post-freeze market sessions must occur naturally before predefined evidence gates can be met.

## What is actually left

At this checkpoint there is no identified large missing non-Kite software subsystem. Remaining work is external or naturally ongoing:

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
- evaluate frozen benchmark/challenger rules only after sufficient untouched evidence exists

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

None of these may silently introduce broker order execution.

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
