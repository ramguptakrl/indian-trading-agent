# Trade Brain v0.13 — BSE Ltd Decision Support

Trade Brain is a **BSE Ltd-only** (`NSE:BSE`, ISIN `INE118H01025`) research, replay, validation and advisory system for a modeled `RESIDENT_INDIAN` trader.

It retains useful multi-agent research infrastructure from the inherited repository, but the active product is governed by Trade Brain's audited deterministic control plane.

**Trade Brain does not place broker orders.**

```text
advisory_only = true
trade_authorization = false
order_execution_allowed = false
```

## Active product boundary

### INTRADAY

- LONG or SHORT cash equity
- same-session only
- no fresh entry from 15:10 IST
- flat before 15:15 IST
- explicit Entry / Stop-Loss / Primary Target required

### SWING

- LONG only
- multi-day
- **Zerodha MTF-funded only** in the active product
- current MTF eligibility must be verified
- funded amount must be explicit
- positive interest-days scenario required before fully costed advice/replay can PASS
- historical `CNC_OWN_CASH` labels may remain readable, but cannot grant active SWING permission

MTF is a funding dimension of SWING, not a third trade mode. F&O and overnight cash-equity shorting are outside the active product.

## Decision architecture

A BSE analysis launches two independent research horizons:

```text
INTRADAY graph
SWING · MTF graph
```

Neither horizon substitutes for the other. Both consume the audited hierarchy when available:

```text
1D dominant trend -> derived 4H structure -> 1H setup -> 15m entry refinement
```

Missing, stale or conflicting evidence is explicit and fail-closed. Models are not allowed to invent missing timeframe values.

## AI framework

Normal Trade Brain configuration:

- **Groq** primary research/synthesis — `openai/gpt-oss-20b`
- **Google Gemini** material-finding verifier/challenger — `gemini-3.6-flash`
- retryable quota/capacity failover between configured providers

LLM output is research evidence/candidate generation only. Exchange calendar, data provenance, broker/funding permission, cost logic and hard risk rules outrank AI opinion.

## Market-data hierarchy

When configured, Zerodha Kite is the preferred **MARKET_DATA_ONLY** transport:

```text
Kite Historical REST -> audited finalized BSE OHLCV
Kite WebSocket        -> fresh live BSE quote state
Kite REST Quote       -> on-demand quote snapshot
```

Kite adapters expose no place/modify/cancel-order methods.

Yahoo/yfinance may be used only as an explicitly labelled fallback/research source where the source policy permits it. It is never silently relabelled as Kite or official exchange truth.

## Evidence and safety plane

Implemented Trade Brain capabilities include:

- BSE-only scope enforcement at request and live-advisory boundaries
- official security identity/provenance
- permanent corporate-event/document memory
- reviewed/archived official events remain evidence
- explicit split/dividend normalization without guessed dates/ratios
- raw-price comparability eras across stock splits; raw OHLC is never rewritten
- audited RAW_UNADJUSTED OHLCV
- look-ahead-safe replay
- strict TP/SL ambiguity handling
- multi-timeframe, gap, structure, volume and pattern research
- Focus Instrument Lab
- frozen challenger / walk-forward validation
- human-approved soft runtime only
- verified exchange-calendar/session controls
- Crash Guard and abnormal-market guards
- resident equity transaction costs
- Zerodha MTF incremental funding costs
- combined SWING MTF target/stop/break-even economics
- funding-aware MTF paper ledger
- actual manual trade journal with MTF-aware SWING accounting and partial exits
- read-only Position Guardian on Actual Trades
- separate audited NIFTY 50 context-only store
- after-market study cycle
- BSE-only browser UI
- Windows one-button launcher

Hard rules cannot self-learn. Research may propose evidence; promotion requires chronological validation and explicit human approval.

## Corporate-action safety

Trade Brain stores official corporate-event evidence independently from inbox workflow status.

- stock splits create raw-price comparability boundaries
- dividends are ex-date economic context, not split-style structural eras
- explicit record/ex/payment dates are parsed when stated
- an ex-date is never guessed from a record date
- replay and Guardian avoid interpreting mechanical split resets as ordinary losses/stops

## Broader-market context

BSE Ltd remains the only trade target.

NIFTY 50 is stored separately as **context-only audited index evidence**. When authenticated Kite data is available, completed NIFTY daily bars can contribute broader-market correction context. If audited NIFTY context is missing, its state stays `UNKNOWN`; Trade Brain does not substitute unaudited web data into a hard live risk gate.

## Actual Trades / Position Guardian

The Actual Trades journal records what the human actually did externally at the broker. It does not execute trades.

For active SWING records, MTF eligibility/funded amount/interest-day information is explicit and MTF financing is included in estimates when required.

Position Guardian uses the manually logged position plus **fresh persisted Kite BSE quote data** and local event/corporate-action/correction context. A missing, malformed or stale live quote fails closed rather than driving stop/target/HOLD interpretation.

## After-market study

The operating design separates market-session advisory work from post-market study/replay. The after-market study cycle can refresh audited BSE datasets, multi-timeframe evidence, pattern/structure research, news memory and optional audited NIFTY context. It cannot silently mutate hard rules or create broker authority.

## Validation

GitHub Actions validates:

- Python integration compilation
- the complete `tests/test_tradebrain_*.py` suite with **pytest** (including `unittest.TestCase` and pytest-style modules)
- observational Phase 2/3/4/5/6/10 smokes after the regression suite passes
- production Next.js build
- frontend production dependency security audit
- Windows PowerShell/BAT syntax, prerequisites and clean first-run backend/frontend health smoke

A green software test suite supports tested code/contract correctness. It does **not** prove market edge or future profitability.

## Local setup

Use the Windows launcher for the intended operator path:

```text
Start-TradeBrain.bat
```

AI-powered analysis requires the chosen provider keys locally. Authenticated Kite market data requires local Kite credentials/access token. Never commit real credentials.

See:

- `PROJECT_STATE.md`
- `TRADEBRAIN_REFRAME.md`
- `TRADEBRAIN_RUNTIME_REQUIREMENTS.md`
- `TRADEBRAIN_KITE_DATA.md`
- `TRADEBRAIN_ACTUAL_TRADES.md`
- `TRADEBRAIN_PHASE6.md`
- `WINDOWS_SETUP.md`

## Evidence boundary

`BSE_PROSPECTIVE_HYPOTHESIS_001` is frozen for future-only validation after **2026-08-21**. Historical observations used to generate the hypothesis cannot be backfilled as untouched validation evidence.

PR #1 intentionally remains **OPEN, DRAFT and UNMERGED**. Do not merge into `main` unless the owner explicitly requests it.
