# Indian Trading Agent Trial / Trade Brain — Current Project State

Last canonical checkpoint: **2026-08-23**  
Repository: `ramguptakrl/indian-trading-agent`  
Development branch: `tradebrain/reframe-foundation`  
Pull request: **#1** (draft, intentionally unmerged)  
Current product version: **Trade Brain v0.12.1**

## Project identity

This repository is the **Indian Trading Agent Trial / Trade Brain / BSE Engine** project.

**Kronos-BSE is a separate, unrelated project. Do not mix it into this repository.**

Similarity of instrument, broker, language, backtesting, forecasting, or trading terminology is not permission to reuse Kronos-BSE project state. Cross-project reuse requires an explicit owner request.

For project-continuation questions, use this priority:

1. current repository code on `tradebrain/reframe-foundation`
2. `PROJECT_STATE.md`
3. `AGENTS.md`
4. canonical `TRADEBRAIN_*.md` documents
5. current PR description / validated CI state
6. conversation memory only where it does not conflict with the above

## What we are building

Trade Brain is an audited Indian-equity research/advisory system focused initially on **BSE Ltd (`NSE:BSE`)**.

Its intended flow is:

```text
market data + source provenance
        -> market structure / events / broader context
        -> historical evidence / replay
        -> multi-agent research
        -> strict candidate parser
        -> exchange calendar/session validation
        -> Crash Guard
        -> broker/exchange permission
        -> deterministic hard-rule gate
        -> approved soft preference
        -> resident transaction-cost scenario
        -> advisory
        -> optional human-executed manual trade journal
        -> actual outcomes / future evidence
```

AI/LLM output is research evidence and a candidate generator, **not final authority**.

## Active product doctrine

Modeled trader: `RESIDENT_INDIAN`

Active modes:

- `INTRADAY`: LONG or SHORT cash-market equity, same-session only; no fresh entry from 15:10 IST; intended flat by 15:15 IST.
- `SWING`: LONG-only cash/delivery using own cash; may cross sessions.

Not active:

- MTF / margin-funded delivery
- rescue-lot architecture
- F&O execution
- hidden leverage
- automatic broker orders

Historical aliases may remain internally for compatibility, but current user-facing modes are `INTRADAY` and `SWING`.

## Advisory / execution boundary

Every Trade Brain final advisory remains non-executing:

```text
advisory_only = true
trade_authorization = false
order_execution_allowed = false
```

Safe candidate/advisory labels:

- `LONG_CANDIDATE`
- `SHORT_CANDIDATE`
- `EXIT_CANDIDATE`
- `WAIT`
- `NO_TRADE`

Do not reintroduce raw BUY/SELL/HOLD as broker authority.

`I TOOK THIS TRADE`, `Partial Close`, and `Close Trade` update the local actual-trade journal only after the human acts externally at the broker.

## Zerodha / Kite state

Kite has been implemented as a **read-only market-data plane**.

Implemented capabilities include:

- instrument lookup
- historical REST candles
- conservative audited range chunking
- REST LTP / OHLC / full quote
- WebSocket live state in LTP / quote / full modes
- market depth in full mode
- persisted latest live quote state
- Kite-primary price-source hierarchy
- labelled Yahoo/yfinance fallback

Kite remains `MARKET_DATA_ONLY`.

There are no Trade Brain place/modify/cancel-order methods.

**Credentials have not yet been configured and authenticated live/historical Kite success has not been claimed.**

When credentials arrive, the next Kite work is operational validation, not redesign.

## Actual manual trade journal

`ACTUAL_MANUAL_TRADE` is a separate evidence class from replay and paper/simulation.

Implemented:

- advisory-linked and unlinked actual trade records
- exact advisory snapshot preservation
- mismatch preservation when human direction differs from advisory
- actual entry fill, quantity, timestamp and optional broker reference
- `OPEN -> PARTIALLY_CLOSED -> CLOSED`
- separate partial exit slices
- current quote marking
- estimated resident charges and open/realized net P&L
- actual charge override support
- timing/policy violation recording without erasing reality
- dedicated Actual Trades UI

Future broker reconciliation, if added, must be read-only unless the owner explicitly changes the product boundary.

## BSE evidence state

The first BSE Ltd baseline was deliberately descriptive/exploratory rather than a strategy-performance claim.

Baseline coverage recorded at the v0.12.1 checkpoint:

- 2,361 completed daily bars, roughly Feb-2017 through Aug-2026
- 3,280 one-hour bars
- 2,847 five-minute bars
- 39 recent sessions observed
- 25 strict full regular sessions in the cited baseline

`BSE_PROSPECTIVE_HYPOTHESIS_001` is frozen for future-only evidence after 2026-08-21. Historical data used to generate the hypothesis must not be backfilled as untouched validation.

## Current validation checkpoint

Latest full validation referenced before this project-state guardrail update: GitHub Actions run **#310** on head `c06157e9915af9549d51abc151bd11be2782ebee`.

Validated at that checkpoint:

- Python integration compile: PASS
- `start.sh` syntax: PASS
- **136 / 136 Trade Brain tests: PASS**
- Phase 2 observational smoke: PASS / safe
- Phase 3 observational smoke: PASS
- Phase 4 observational smoke: PASS
- Phase 5 observational smoke: PASS
- Phase 6 observational smoke: PASS
- Phase 10 observational smoke: PASS
- BSE descriptive evidence artifact rebuild: PASS
- artifact upload: PASS
- Next.js production frontend build: PASS

Do not claim the new documentation-only commits changed runtime validation; rerun CI when runtime/code behavior changes.

## Current repository / PR state

Base branch: `main`

Feature branch: `tradebrain/reframe-foundation`

PR #1 title at the v0.12.1 checkpoint:

`Trade Brain v0.12.1: Kite-primary data + actual advisory trade journal`

The PR is intentionally:

- OPEN
- DRAFT
- UNMERGED

**Do not merge automatically.** Merge only when the project owner explicitly asks.

## What should happen next

The architecture should not keep expanding with random phases. The useful next work is evidence/deployment oriented.

### 1. Authenticate Kite when credentials are provided

- configure API key/token
- authenticate historical REST
- resolve exact BSE instrument token
- pull audited Kite history
- compare Kite history against the labelled Yahoo baseline
- investigate meaningful discrepancies
- validate read-only WebSocket
- verify live quote persistence and source provenance

Do **not** add order endpoints.

### 2. Continue prospective BSE evidence

- collect future post-freeze sessions
- do not backfill pre-freeze observations into `BSE_PROSPECTIVE_HYPOTHESIS_001`
- wait for predefined sample gates before making performance claims

### 3. Add hypotheses only through frozen evidence protocol

Potential research topics already identified include:

- first-hour breakout vs fade
- prior-day high/low reactions
- time-of-day entry windows
- regime-conditioned gap behavior
- audited support/resistance reaction reliability
- INTRADAY vs SWING setup behavior

Each hypothesis should define benchmark/challenger, freeze parameters first, use untouched validation, and include resident costs.

### 4. Use the actual-trade journal

When the human actually takes an advisory externally:

1. execute manually at broker
2. record `I TOOK THIS TRADE`
3. store actual fill
4. track current state
5. exit externally at broker
6. record partial/full close
7. compare actual outcome with advisory/replay later

### 5. Optional future read-only broker reconciliation

May verify positions/tradebook against the journal.

If implemented:

- read-only only
- no place/modify/cancel
- journal remains explicit evidence record

## Do not reintroduce without explicit owner decision

- Kronos-BSE code or project state
- MTF as an active Trade Brain mode
- funded-delivery / rescue-lot logic
- automatic broker order placement
- raw BUY/SELL/HOLD final authority
- AI override of Crash Guard
- AI override of session timing
- AI override of broker restrictions
- fuzzy cross-exchange identity guessing
- same-sample optimization presented as validation
- automatic challenger promotion
- hidden leverage
- NRI policy imported merely because Kite credentials belong to an NRI account

## Required reading before major changes

- `PROJECT_STATE.md`
- `AGENTS.md`
- `TRADEBRAIN_REFRAME.md`
- `TRADEBRAIN_PHASE4.md`
- `TRADEBRAIN_PHASE5.md`
- `TRADEBRAIN_PHASE6.md`
- `TRADEBRAIN_PHASE7_TO_10.md`
- `TRADEBRAIN_KITE_DATA.md`
- `TRADEBRAIN_ACTUAL_TRADES.md`
- relevant files under `research/`

If a future coding agent or assistant cannot reconcile its memory with these documents, it should stop relying on memory and anchor to the repository.
