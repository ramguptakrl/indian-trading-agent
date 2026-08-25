# Trade Brain — BSE Ltd Project State

Status date: **2026-08-25**  
Repository: `ramguptakrl/indian-trading-agent`  
Development branch: `tradebrain/reframe-foundation`  
Protected checkpoint: `checkpoint/tradebrain-bse-framework-2026-08-25`  
Original checkpoint SHA: `5d8ff95c013a9091f576591dbbe9bae4439c099e`  
PR #1: **OPEN / DRAFT / intentionally UNMERGED**  
Current product version: **Trade Brain v0.13.0**

## Second full code/logic audit — 2026-08-25

The branch was re-audited after the earlier green checkpoint instead of relying on CI alone.
That audit found and fixed real issues:

1. direct Phase-10 live advisory could be called with a non-BSE ticker;
2. Foundation used `unittest discover`, which silently skipped pytest-style Trade Brain modules;
3. active agent config still contained historical dynamic CNC/MTF SWING labels;
4. base resident cost metadata still described own-cash SWING even though active policy was MTF-only;
5. Position Guardian could use an old persisted Kite quote after a feed disconnect;
6. NIFTY correction severity ordering could label a severe drawdown as merely high-vol downtrend;
7. corporate-action date normalization accidentally changed `September` into `Sepember`, losing an explicitly stated record date;
8. README/runtime/Phase-6/Actual-Trades documentation lagged the implemented v0.13 behavior.

All of those findings were corrected without enabling broker execution.

## Current regression validation

Foundation run **#665** (`32900437853`) on code commit
`f4f8d7b8beaba5317c9a37b69a7214f1f1f17b98` passed:

- **243 tests passed**;
- **5 subtests passed**;
- Python integration compile ✅;
- launcher syntax validation ✅;
- production frontend contract/build ✅;
- Phase 2 corporate-event/document smoke ✅ observational;
- Phase 3 market-data/replay smoke ✅ observational;
- Phase 4 strict outcome/Focus Lab smoke ✅ observational;
- Phase 5 challenger smoke ✅ observational;
- Phase 6 INTRADAY + SWING MTF economics smoke ✅ observational;
- Phase 10 calendar/final-advisory smoke ✅ observational;
- descriptive BSE evidence baseline rebuilt/uploaded ✅.

The regression runner is now **pytest over every `tests/test_tradebrain_*.py` module**. This executes
both `unittest.TestCase` suites and pytest-style top-level tests; the old 201-test count was
incomplete and must not be used as the current coverage claim.

Security and Dependency Refresh also passed on the same code line. Windows validation is
tracked separately and must be green on the final runtime code before local handoff is called complete.

A passing software suite supports tested code/contract correctness. It is not a profitability claim.

## Product identity

This branch is **our BSE Trade Brain software**, not the generic inherited ITA product.
Kronos-BSE is a separate project and must not be mixed into this branch unless explicitly requested.

Only trade target:

```text
BSE Ltd
NSE:BSE
ISIN INE118H01025
```

Modeled trader: `RESIDENT_INDIAN`.

Every final advisory remains non-executing:

```text
advisory_only = true
trade_authorization = false
order_execution_allowed = false
```

No Trade Brain place/modify/cancel broker-order method is active.

## Active horizons

### INTRADAY

- LONG or SHORT cash equity;
- same-session only;
- no fresh entry from 15:10 IST;
- flat before 15:15 IST;
- explicit Entry / Stop-Loss / Primary Target;
- resident equity transaction costs included.

### SWING

- LONG only;
- multi-day;
- active funding path is **Zerodha MTF only**;
- MTF is funding, not a third mode;
- current MTF eligibility must be verified;
- funded amount must be explicit and valid;
- positive MTF interest-days scenario is required before fully costed advice/replay can PASS;
- historical `CNC_OWN_CASH` remains readable compatibility only and cannot grant active permission.

No F&O and no overnight cash-equity shorting are active.

## Decision architecture

A BSE analysis launches two independent horizons:

```text
INTRADAY graph
SWING · MTF graph
```

Neither may substitute for the other.

Audited evidence hierarchy when available:

```text
1D dominant trend -> derived 4H structure -> 1H setup -> 15m entry refinement
```

Missing, stale or conflicting evidence stays explicit and fail-closed. Models cannot invent missing values.

The shared live-advisory layer now enforces BSE/NSE scope before market/policy evaluation, so a
direct Phase-10 caller cannot turn another stock into a Trade Brain target.

## AI/model framework

- Groq primary research/synthesis when configured: `openai/gpt-oss-20b`;
- Gemini material-finding verifier/challenger when configured: `gemini-3.6-flash`;
- retryable quota/capacity failover between configured providers;
- AI provides research evidence/candidates only;
- calendar, source provenance, market risk, broker/funding permission and deterministic hard rules outrank AI.

## Data/provenance plane

Kite role: **`MARKET_DATA_ONLY`**.

Supported:

- exact instrument lookup;
- historical REST candles;
- audited range sync;
- REST quote/LTP/OHLC;
- WebSocket LTP/quote/full state;
- market depth in full mode;
- persisted latest quote state.

No order mutation API is exposed.

Yahoo/yfinance remains explicitly labelled fallback/research data only where source policy permits it.
It is not silently treated as official/Kite data.

## Corporate-action safety

- official corporate-event memory is permanent regardless of inbox REVIEWED/ARCHIVED status;
- stock splits and dividends are normalized only from explicit evidence;
- record/ex/payment dates are parsed when explicitly stated;
- `Sept` abbreviation normalization no longer corrupts full `September`;
- ex-date is never guessed from record date;
- split ratio is never guessed;
- raw OHLC is never rewritten;
- stock splits create raw-price comparability boundaries;
- dividends create ex-date economic context, not split-style eras;
- replay/Guardian avoid false loss/stop interpretation across a split reset.

## Costs / MTF economics

The resident base equity cost module is explicitly a **transaction-cost component**, not a funding-permission source.

Active SWING economics layer:

```text
resident equity transaction costs
+ Zerodha MTF incremental brokerage/pledge/unpledge/interest
= active SWING MTF net economics
```

Implemented:

- funded amount and user cash contribution separated;
- MTF break-even solver;
- explicit interest days;
- MTF-aware target/stop scenarios;
- MTF paper ledger;
- strict MTF replay;
- MTF-aware actual-trade estimates/partial closes;
- no hidden leverage assumption;
- no guessed eligibility/holding days.

Current Zerodha rates/rules used by the versioned 2026-08-25 profile were rechecked against Zerodha's public documentation during this audit.

## Position Guardian / Actual Trades

Actual Trades remains manual evidence of what the human executed externally.

Position Guardian is read-only and now requires a **fresh timestamped persisted Kite BSE quote** before it may interpret live stop/target/HOLD risk.

- no quote -> fail closed;
- malformed/missing quote timestamp -> fail closed;
- quote older than the configured freshness limit -> `STALE_LIVE_BSE_QUOTE` and no live position interpretation;
- corporate-action reconciliation outranks raw stop/P&L interpretation;
- INTRADAY 15:15 exit rule outranks setup opinion;
- confirmed halt/freak-tick/data-integrity state outranks setup opinion;
- audited BSE and optional audited NIFTY correction context may increase review severity.

Guardian cannot place, modify or cancel orders.

## Broader-market context

BSE remains the only trade target.

NIFTY 50 is a separate audited **context-only** index store populated from Kite when authenticated.
Only completed bars at/before the as-of cutoff are used.

Severity ordering now preserves `SEVERE_CORRECTION` when an audited downtrend also has at least an 8% recent 20-session drawdown, even if volatility is elevated.

If sufficient audited NIFTY history is unavailable, state remains `UNKNOWN`; no unaudited web signal is substituted into a hard live gate.

## Learning/research boundary

- market session: advisory/monitoring;
- after market: audited refresh/replay/research/study;
- no hard-rule autonomous mutation;
- patterns remain exploratory until frozen chronological validation;
- challenger promotion requires explicit human approval;
- future-only prospective evidence remains separate from hindsight exploration.

`BSE_PROSPECTIVE_HYPOTHESIS_001` remains frozen for sessions strictly after **2026-08-21**.
Current `NEEDS_MORE_DATA` status is expected until untouched future evidence accumulates.

## Active browser surface

Only the BSE product routes are intended to remain visible:

- BSE Today;
- BSE Analysis;
- Analysis detail;
- Price & Structure;
- Analysis Outcomes;
- BSE Evidence;
- BSE Context / News;
- Actual Trades;
- Settings.

The generic ITA scanner/recommender/backtest/simulation/calibration/strategy/shadow-trade/memory-admin pages were removed from the active frontend surface.

## What remains before real advisory use

The framework/code integration is not the current blocker. Remaining work is operational/local:

1. confirm the final Windows CI smoke on the audited runtime line;
2. configure local Groq and Gemini keys;
3. configure local Kite API credentials without committing secrets;
4. complete local Kite access-token authentication;
5. launch `Start-TradeBrain.bat` on the Windows machine;
6. verify backend/frontend health locally;
7. verify real authenticated BSE historical/quote/WebSocket data and optional NIFTY context;
8. run the first real BSE dual-horizon advisory with execution still OFF;
9. continue untouched prospective evidence collection.

GitHub CI intentionally has no private broker/LLM credentials, so it cannot claim authenticated local success.

## Do not reintroduce without explicit owner decision

- Kronos-BSE state/code;
- generic multi-stock trade targeting;
- active own-cash CNC SWING;
- overnight cash-equity shorting;
- automatic broker orders;
- raw BUY/SELL/HOLD authority;
- AI override of hard risk/session/broker/funding rules;
- hidden leverage;
- same-sample optimization presented as validation.
