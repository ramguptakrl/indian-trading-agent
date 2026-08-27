# Trade Brain — BSE Ltd Product Conversion Audit

Status: **conversion complete through Trade Brain v0.13.0**  
Canonical branch: `tradebrain/reframe-foundation`  
Control/baseline branch: `main` (original inherited ITA; keep untouched)  
Only tradable target: **BSE Ltd (`NSE:BSE`, ISIN `INE118H01025`)**

## Product decision

Trade Brain is no longer a generic multi-stock Indian trading application on this branch.
It is a BSE Ltd decision-support, evidence, replay and validation system.

Broader Indian/global market information is context only. It cannot become an independent
trade target through the active product surface.

Every final result remains non-executing:

```text
advisory_only = true
trade_authorization = false
order_execution_allowed = false
```

## Canonical decision question

For BSE Ltd only:

- what is the current INTRADAY posture?
- what is the current SWING · Zerodha-MTF posture?
- what Entry / Stop-Loss / Primary Target geometry exists?
- what evidence supports or blocks the candidate?
- are the data, exchange session, market risk and broker/funding state sufficiently verified?

If valid geometry/evidence does not exist, the correct result is WAIT/BLOCK rather than an
invented price or forced trade.

## Canonical active modes

### INTRADAY

- LONG or SHORT cash equity;
- same session only;
- no fresh entry from 15:10 IST;
- flat before 15:15 IST.

### SWING

- LONG only;
- multi-day;
- active funding is **Zerodha MTF only**;
- verified MTF eligibility required;
- funded amount explicit;
- explicit interest-days scenario required for complete net-cost evaluation.

MTF is funding, not a third trade mode. Historical CNC labels may remain readable only for
compatibility/audit.

## Canonical AI roles

- **OpenAI paid API** is the normal development/production reasoning path when configured.
- Recommended OpenAI routing is `gpt-5.6-luna` for high-volume/quick work and `gpt-5.6-terra` for deeper synthesis.
- **Gemini** remains the independent material-finding verifier/challenger and retryable-capacity fallback when configured.
- **Groq** may remain configured as an optional alternate provider; it is no longer required as the primary development path.
- AI never grants broker, session, risk or funding permission.

## Conversion status — completed

### BSE-only scope

Completed:

- fixed BSE instrument contract;
- request-model BSE validation;
- dual-horizon BSE analysis;
- shared live-advisory BSE/NSE scope lock;
- no generic ticker search in active BSE Analysis;
- BSE-only frontend route contract.

### Generic ITA product surfaces

Disconnected/removed from the active frontend:

- Top Picks;
- generic Market Scan;
- watchlist/discovery pages;
- generic AI backtest/simulation pages;
- verdict/calibration pages;
- shadow-trade page;
- strategy catalog entry points;
- memory-admin trading navigation.

The active browser surface is:

- BSE Today;
- BSE Analysis;
- Analysis detail;
- Price & Structure;
- Analysis Outcomes;
- BSE Evidence;
- BSE Context / News;
- Actual Trades;
- Settings.

Generic backend files may remain only where unmounted or deliberately reused as underlying
research infrastructure. They are not active multi-stock trade-discovery routes.

## Canonical evidence/data plane

Retained and converted capabilities include:

- official identity/security-master handling;
- provenance;
- permanent corporate-event/document memory;
- audited RAW_UNADJUSTED OHLCV;
- explicit stock-split price eras;
- dividend ex-date economic context;
- point-in-time replay;
- multi-timeframe structure/regime/gap/volume research;
- Focus Instrument Lab;
- frozen challenger/walk-forward governance;
- prospective evidence;
- verified exchange calendar;
- Crash Guard / market guards;
- Kite read-only historical/quote/WebSocket data;
- context-only audited NIFTY 50 store;
- after-market study cycle.

## Canonical market-data hierarchy

When locally authenticated:

```text
Kite Historical REST -> audited finalized BSE history
Kite WebSocket        -> fresh persisted live BSE quote/depth state
Kite REST Quote       -> on-demand market-data snapshot
```

Yahoo/yfinance is explicitly labelled fallback/research data only where permitted. It is
not silently upgraded to official/Kite evidence.

No Kite place/modify/cancel-order method exists.

## Corporate-action hardening

Completed:

- REVIEWED/ARCHIVED inbox state no longer removes official truth from risk/replay readers;
- explicit record/ex/payment dates are normalized when stated;
- an ex-date is never inferred from a record date;
- full month names such as `September` are preserved during date normalization;
- split ratios are explicit-only;
- stock splits create raw-price comparability boundaries without rewriting OHLC;
- replay and Guardian avoid treating a mechanical split reset as an ordinary loss/stop;
- dividends remain economic context rather than structural split eras.

## Costs / SWING MTF conversion

Completed:

- resident base equity transaction-cost component;
- separate versioned Zerodha MTF incremental funding component;
- combined SWING MTF target/stop/break-even economics;
- explicit funded amount / user contribution separation;
- explicit interest-day handling;
- funding-aware MTF paper ledger;
- strict MTF replay;
- MTF-aware Actual Trades estimates and partial closes.

The base cost component no longer claims own-cash SWING funding permission. Active funding
permission comes from Trade Brain policy and is MTF-only.

## Actual Trades / Guardian conversion

Completed:

- actual human fill journal remains separate from replay/paper evidence;
- advisory linkage and mismatch preservation;
- partial closes;
- MTF metadata/economics for active SWING;
- read-only Guardian surfaced on Actual Trades;
- local event/news/corporate-action/correction context;
- audited NIFTY correction context when available;
- fresh-quote requirement before live stop/target/HOLD interpretation;
- stale/malformed/missing live quote fails closed.

## Validation conversion

Foundation now runs:

```text
python -m pytest -q tests/test_tradebrain_*.py
```

This executes both `unittest.TestCase` and pytest-style Trade Brain modules. The old
`unittest discover` runner silently skipped several pytest-style files and is no longer the
canonical regression gate.

Second full audit validation on 2026-08-25 passed **243 tests + 5 subtests** before the
observational Phase 2/3/4/5/6/10 smokes.

## Benchmark boundary vs original ITA

The original baseline remains on `main`. Do not back-port Trade Brain logic there before a
controlled benchmark.

Any future comparison must use identical BSE dates/information cutoffs and harmonized
outcome definitions. A raw ITA BUY/SELL string is not equivalent to a Trade Brain
fail-closed structured advisory.

Useful benchmark dimensions include:

- analysis completion/failure rate;
- structured-level completeness;
- directional/outcome accuracy under one frozen scoring rule;
- net-of-cost performance under identical valid execution assumptions;
- max adverse excursion/drawdown;
- abstention quality;
- provenance/look-ahead violations;
- hard-rule/session violations;
- latency and provider cost/resilience.

## v0.14 ML extension boundary

The v0.13 BSE conversion is complete. v0.14 ML/self-training is an additive research subsystem, not a reopening of the product boundary.

The canonical frozen implementation specification is `TRADEBRAIN_ML_SELF_TRAINING_PLAN.md`, restored from `checkpoint/tradebrain-ml-plan-2026-08-26`.

ML may learn feature/model weights, probability thresholds and approved research parameters only through chronological validation, challenger governance and human-approved promotion. It may never weaken BSE scope, session, provenance, broker/MTF funding, halt, risk, advisory-only or no-order-execution rules.

## Remaining operational validation

Before real advisory use:

1. configure/test the local paid OpenAI key and confirm Luna/Terra routing;
2. keep Gemini configured as verifier/fallback and Groq only as an optional alternate;
3. authenticate local paid Kite market data;
4. launch the Windows software;
5. verify real BSE history/quote/WebSocket and optional NIFTY context locally;
6. run the first real dual-horizon advisory with execution OFF;
7. continue untouched prospective evidence collection and v0.14 ML shadow validation.

PR #1 remains **OPEN / DRAFT / UNMERGED** until the owner explicitly asks otherwise.
