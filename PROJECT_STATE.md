# Indian Trading Agent Trial / Trade Brain — Current Project State

Status date: **2026-08-25**  
Repository: `ramguptakrl/indian-trading-agent`  
Development branch: `tradebrain/reframe-foundation`  
Protected checkpoint: `checkpoint/tradebrain-bse-framework-2026-08-25`  
Checkpoint SHA: `5d8ff95c013a9091f576591dbbe9bae4439c099e`  
PR #1: OPEN / DRAFT / intentionally UNMERGED  
Current product version: **Trade Brain v0.13.0**

## Project identity

This is the Indian Trading Agent Trial → BSE-focused Trade Brain project.
Kronos-BSE is separate and must not be mixed into this repository.

## Current product doctrine

Trade Brain is an audited BSE Ltd (`NSE:BSE`) research/advisory system for a modeled
`RESIDENT_INDIAN` trader.

Active modes:

- `INTRADAY`: LONG or SHORT cash equity; same session; no fresh entry from 15:10 IST;
  intended flat by 15:15 IST.
- `SWING`: LONG-only, multi-day, **Zerodha MTF-funded**.

Important funding rule:

```text
SWING != a third "MTF mode"
SWING funding = MTF only
CNC_OWN_CASH = historical-readable compatibility label, not active SWING permission
```

Active SWING requires current MTF eligibility verification and a positive funded amount.
Net SWING scenarios combine resident equity transaction costs with the versioned Zerodha
MTF funding profile. An MTF holding/interest-days scenario must be explicit before a
fully costed SWING candidate can PASS; Trade Brain does not invent the holding duration.

Broker execution remains OFF:

```text
advisory_only = true
trade_authorization = false
order_execution_allowed = false
```

## AI / model framework

- Groq is the primary configured research/synthesis path.
- Gemini is the material-finding verifier/challenger when configured.
- Provider failover handles retryable quota/capacity errors.
- LLM output is evidence/candidate generation only.
- Deterministic calendar, market/risk, broker and funding rules outrank AI.

## Evidence / learning framework

Implemented foundation includes:

- BSE-only trade-target boundary;
- official identity/provenance and corporate-event memory;
- audited RAW_UNADJUSTED OHLCV;
- look-ahead-safe replay and strict outcomes;
- multi-timeframe / gap / structure / pattern research;
- Focus Instrument Lab;
- frozen challenger and walk-forward governance;
- human-approved soft parameter runtime;
- verified exchange-calendar/session controls;
- Crash Guard and abnormal-market guards;
- read-only Kite historical/REST/WebSocket market-data plane;
- final fail-closed advisory pipeline;
- actual manual trade journal;
- Windows launcher and browser UI.

Hard rules cannot self-learn.

## MTF economics

The repository contains a versioned Zerodha MTF profile verified on 2026-08-25 and a
combined SWING cost path that layers MTF funding charges on top of resident equity
transaction costs.

The base `equity_costs.py` engine remains a non-MTF transaction-cost component so
historical calculations are not silently rewritten.

The legacy Phase-6 paper ledger was designed around full-notional cash reservation.
The public API must not present that old own-cash SWING representation as active SWING.
MTF-aware paper/journal reconciliation is a deeper integration item, not permission to
fall back to CNC.

## Validation state

The original preserved framework checkpoint is unchanged at:

`5d8ff95c013a9091f576591dbbe9bae4439c099e`

The first post-checkpoint repair commit is:

`909d26eab10c2c4eb731889a0339a929921da4f3`
`fix(ci): align foundation tests with current Phase 6 APIs`

Foundation run #494 (`32887419390`) passed both:

- `unit-tests` ✅
- `frontend-contract` ✅

The unit job also passed the Phase 2/3/4/5/6/10 observational smokes and BSE evidence
baseline build/upload.

## Kite state

Kite remains `MARKET_DATA_ONLY`. Historical candles, quotes, WebSocket state and market
depth are supported. No place/modify/cancel order path exists.

Real authenticated Kite success is not claimed until real credentials are configured and
validated.

## What remains after the v0.13 MTF correction

1. Keep CI green after the MTF-only policy/API change.
2. Make the paper ledger and actual-trade journal explicitly MTF-aware rather than using
   legacy full-notional SWING accounting.
3. Continue deeper live BSE integration: market-state guards, material-change recompute,
   multi-timeframe runtime use and after-market study automation.
4. Authenticate/validate real Kite data when credentials are supplied.
5. Continue future-only prospective BSE evidence.
6. Do not merge PR #1 into `main` unless the owner explicitly asks.

## Do not reintroduce without explicit owner decision

- Kronos-BSE state/code
- active own-cash CNC SWING
- overnight cash-equity shorting
- automatic broker orders
- raw BUY/SELL/HOLD authority
- AI override of hard risk/session/broker/funding rules
- hidden leverage
- same-sample optimization presented as validation
