# Trade Brain — BSE Ltd Project State

Status date: **2026-08-25**  
Repository: `ramguptakrl/indian-trading-agent`  
Development branch: `tradebrain/reframe-foundation`  
Protected checkpoint: `checkpoint/tradebrain-bse-framework-2026-08-25`  
Checkpoint SHA: `5d8ff95c013a9091f576591dbbe9bae4439c099e`  
PR #1: **OPEN / DRAFT / intentionally UNMERGED**  
Current product version: **Trade Brain v0.13.0**

## Runtime-ready checkpoint

Validated runtime commit:

`1b4866b9fc9f86100dd41f3d0aa8673c4241c5ca`

That exact runtime head passed:

- Trade Brain Foundation ✅
- Trade Brain Windows ✅
- Trade Brain Security ✅
- Trade Brain Dependency Refresh ✅
- 201 Trade Brain unit/regression tests ✅
- production Next.js frontend build ✅
- Windows PowerShell/BAT launcher validation ✅
- Windows clean first-run backend/frontend end-to-end health smoke ✅

A later validation-only commit, `caef3773a79575e385d91d2c01fd87cc82c0a5e5`, upgrades the Phase-6 smoke so it explicitly validates both INTRADAY resident-equity economics and active SWING Zerodha-MTF economics. It does not enable broker execution or change live trading policy.

## Project identity

This repository branch is **our Trade Brain / BSE software**, not the generic inherited ITA product.

Kronos-BSE is a separate project and must not be mixed into this branch unless explicitly requested.

Trade Brain is an audited BSE Ltd (`NSE:BSE`, ISIN `INE118H01025`) research/advisory system for a modeled `RESIDENT_INDIAN` trader.

```text
advisory_only = true
trade_authorization = false
order_execution_allowed = false
```

## Active horizons

### INTRADAY

- LONG or SHORT cash-equity research
- same-session only
- no fresh entry from 15:10 IST
- flat before 15:15 IST
- resident equity transaction costs included

### SWING

- LONG only
- active funding path: **Zerodha MTF only**
- current MTF eligibility must be verified
- funded amount must be explicit
- positive interest-day scenario is required for fully costed advice/replay
- `CNC_OWN_CASH` remains historical-readable compatibility only, not active SWING permission

No F&O is enabled.

## Decision architecture complete

One BSE analysis launches two independent horizons:

```text
INTRADAY graph
SWING · MTF graph
```

Each has its own task/progress/result. Neither may substitute for the other.

Both final decision layers consume the same audited deterministic hierarchy when available:

```text
1D dominant trend -> derived 4H structure -> 1H setup -> 15m entry refinement
```

Missing, stale or conflicting evidence remains explicit and fail-closed. The models are not allowed to invent missing timeframe values.

## BSE market-data / evidence plane complete

- Kite Connect is the preferred authenticated market-data source
- Kite role is `MARKET_DATA_ONLY`
- audited `RAW_UNADJUSTED` BSE OHLCV store
- completed-bar / as-of replay contract
- 1D / derived 4H / 1H / 15m hierarchy
- live Kite BSE quote plane
- source provenance retained
- Yahoo/yfinance remains explicitly labelled fallback/research data only where allowed

Real authenticated Kite success is not claimed until local credentials are supplied and tested.

## Broader-market context complete

BSE Ltd remains the only trade target.

NIFTY 50 is stored in a separate **context-only audited index store** because it is an index, not an ISIN-backed listed equity.

When Kite data is available:

```text
Kite NIFTY 50 daily history
-> completed audited context bars
-> broader-market correction context
```

If audited NIFTY context is unavailable, the broader-market state stays `UNKNOWN`. Trade Brain does not silently substitute unaudited web/yfinance data into a hard live risk gate. Missing optional NIFTY context also does not invalidate an otherwise successful BSE study cycle.

## Corporate-event / split safety complete

- official NSE/BSE corporate-event memory
- reviewed/archived official events remain permanent evidence; inbox status does not erase truth
- explicit split/dividend normalization
- ex-date/record-date/ratio values are never guessed
- official stock splits create raw-price comparability eras
- raw OHLC is never rewritten
- dividends are mechanical ex-date context, not structural split eras
- replay blocks raw-price comparisons that cross split eras
- regression coverage prevents a mechanical split reset from becoming a false stop-loss or false MTF loss

## MTF economics / replay complete

- resident equity transaction-cost component
- Zerodha MTF incremental brokerage/pledge/unpledge/interest model
- funded amount modeled explicitly
- user cash contribution modeled separately from total position value
- MTF break-even solver
- SWING MTF paper ledger
- strict SWING MTF replay
- replay refuses to guess interest days
- replay refuses unverified MTF eligibility
- replay blocks cross-split raw-price economics
- net P&L and return on user cash contribution available

Phase-6 smoke now validates both:

1. synthetic observed-history INTRADAY paper economics; and
2. explicit SWING MTF funded/interest economics.

No broker order API is used in either validation path.

## Position Guardian / actual trades complete

- manual actual BSE trade journal
- advisory linkage
- partial closes
- actual/estimated charge tracking
- MTF metadata for SWING
- live/open mark economics
- read-only Position Guardian
- Guardian visible directly on Actual Trades
- event/news risk
- BSE correction state
- audited NIFTY broader-market correction when available
- split/dividend reconciliation warnings
- stop/target review
- intraday hard-exit review

Guardian cannot place, modify or cancel broker orders.

## Learning / research boundary complete

- market-session advisory/monitoring mode
- after-market scheduled study mode
- audited replay
- pattern/structure research
- point-in-time news memory
- challenger/frozen-definition workflow
- human approval required for soft-parameter promotion
- hard rules cannot silently self-modify
- prospective evidence kept separate from hindsight exploration

`BSE_PROSPECTIVE_HYPOTHESIS_001` remains frozen for future-only evidence after `2026-08-21`.

No profitability or win-rate claim is implied by historical descriptive evidence.

## Active frontend surface

The BSE product exposes only:

- BSE Today
- BSE Analysis
- Analysis detail
- Price & Structure
- Analysis Outcomes
- BSE Evidence
- BSE Context / News
- Actual Trades
- Settings

Old generic ITA scanner/recommender/backtest/simulation/calibration/strategy/shadow-trade/memory-admin route entry points have been removed from this branch. A regression test locks the BSE-only route set.

Generic backend files may remain only as unmounted/reusable research infrastructure; they are not active trade-discovery routes.

## Windows readiness complete

- `Start-TradeBrain.ps1`
- `Start-TradeBrain.bat`
- `WINDOWS_SETUP.md`
- PowerShell launcher parse validated
- prerequisite preflight validated
- BAT wrapper validated
- clean first-run setup validated
- backend health validated
- frontend startup/health validated
- clean process shutdown validated

## What is actually left before real advisory use

The framework/integration build is no longer the blocker. Remaining work is local/runtime setup:

1. Configure local LLM credentials — Groq primary and Gemini verifier/fallback behavior as configured.
2. Configure the local Kite API key without committing secrets.
3. Complete the normal local Kite access-token/auth flow.
4. Launch `Start-TradeBrain.bat` on the Windows machine.
5. Confirm `/api/health` and the BSE frontend open locally.
6. Verify a real authenticated Kite BSE quote/history sync and optional NIFTY context sync.
7. Run the first real BSE dual-horizon advisory with broker order execution still OFF.

GitHub CI intentionally has no user broker credentials, so it cannot claim authenticated Kite success.

After those local checks, Trade Brain is ready for advisory use and continued prospective learning. Broker execution remains intentionally disabled unless a separate future owner decision explicitly changes that boundary.

## Do not reintroduce without explicit owner decision

- Kronos-BSE state/code
- active own-cash CNC SWING
- overnight cash-equity shorting
- automatic broker orders
- raw BUY/SELL/HOLD authority
- AI override of hard risk/session/broker/funding rules
- hidden leverage
- same-sample optimization presented as validation
