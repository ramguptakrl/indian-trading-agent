# Indian Trading Agent — Trade Brain Developer Guide

This repository is governed by the Trade Brain v0.11 architecture.
Read `AGENTS.md` and `TRADEBRAIN_REFRAME.md` before changing trading logic.

## Core product boundary

- Modeled trader: `RESIDENT_INDIAN`.
- Active modes: `INTRADAY` and `SWING` only.
- `INTRADAY`: LONG/SHORT, same-session; no fresh entry from 15:10 IST; flat before 15:15 IST.
- `SWING`: LONG-only cash/delivery using own cash.
- MTF is removed.
- Automatic broker orders are disabled.
- AI is research/context only and cannot override hard rules.

Historical compatibility aliases:

- `DAY` → `INTRADAY`
- `SWING_POSITION` → `SWING`

Do not reintroduce these legacy names as new user-facing modes.

## Safe research labels

Current final research labels are:

- `LONG_CANDIDATE`
- `SHORT_CANDIDATE`
- `EXIT_CANDIDATE`
- `WAIT`
- `NO_TRADE`

Do not collapse final analysis back into raw `BUY`, `SELL`, `HOLD`, `OVERWEIGHT` or `UNDERWEIGHT` authorization.
Legacy modules may still emit such labels internally; treat them as heuristic evidence only.

## Final advisory pipeline

A live-use new-entry candidate must pass:

1. strict labelled Portfolio Manager parse
2. verified exchange calendar/session
3. explicit Crash Guard state
4. explicit broker/exchange permission
5. deterministic hard-rule policy gate
6. active human-approved/default soft R:R preference
7. resident transaction-cost scenario

Required unknown deterministic state must fail closed.

Every final result remains:

- `advisory_only=true`
- `trade_authorization=false`
- `order_execution_allowed=false`
- `order_endpoint_present=false`

## AI / agent rules

The upstream LangGraph pipeline remains useful for evidence generation, debate and candidate construction.
It is not the final authority.

Portfolio Manager output must be explicitly labelled and structured. Do not infer a trade from narrative prose.
`SELL / EXIT CANDIDATE` is reduction/exit context only; use an explicit `SHORT_CANDIDATE` for a fresh INTRADAY short candidate.

## Learning / calibration rules

- Hard rules are protected and never auto-optimized.
- Phase-5 challenger hypotheses/windows are frozen before evaluation.
- TRAIN is diagnostic only.
- Validation/walk-forward evidence controls readiness for human review.
- Soft runtime values change only after explicit human approval and activation.
- Expose the active soft parameter key/version/source in deterministic outputs.

Legacy recommender `success_probability` remains heuristic/non-learned/non-authorizing unless separately proven and promoted through the Trade Brain research process.

## Data and replay rules

- Preserve raw evidence and source provenance.
- Use SHA-256/content-addressed archives for official/reference artifacts where implemented.
- Keep source identity explicit: official exchange/reference vs non-official vendor.
- Historical replay must avoid future leakage (`ts_close <= as_of`, publication-time cutoffs).
- Do not silently overwrite raw traded prices with adjusted prices.
- Corporate-action comparability boundaries must stay explicit.
- NSE and BSE calendar evidence are exchange-aware; do not silently assume special-session equivalence.

## Zerodha Kite

Trade Brain's Kite integration is `MARKET_DATA_ONLY`.
Allowed uses:

- instrument master
- quotes
- historical candles
- replay/backtest input

The adapter must not expose place/modify/cancel-order methods.
A credential may belong to an NRI account, but credential account type must not change resident trader identity, resident cost profile or policy.

## Frontend contract

Deep Analysis must display research/advisory language rather than a guaranteed "Final Decision" or order instruction.
The frontend should preserve and render `tradebrain_advisory` metadata from the analysis WebSocket/API.

Current candidate UI vocabulary:

- LONG CANDIDATE
- SHORT CANDIDATE
- EXIT CANDIDATE
- WAIT
- NO TRADE

Historical upstream labels can remain visible in old records but should be treated as compatibility/non-authorizing labels.

## Repository layout

Important Trade Brain modules:

```text
backend/tradebrain/
  policy.py                 deterministic hard/soft gate
  schedule.py               operating/session mode
  exchange_calendar.py      verified calendar memory
  security_master.py        official security masters
  security_store.py         canonical/listing identity
  corporate_events.py       official event collectors
  corporate_event_store.py  event/document memory
  documents.py              filing ingestion/extraction
  market_data.py            market-data ingestion
  market_data_store.py      audited OHLCV store
  replay.py                 look-ahead-safe replay
  focus_lab.py              instrument research
  challenger.py             walk-forward challenger logic
  challenger_store.py       frozen definitions/promotions
  soft_runtime.py           approved runtime soft preferences
  equity_costs.py           resident equity economics
  paper_ledger.py           net-cost paper accounting
  kite_data.py              read-only Kite data adapter
  advisory_pipeline.py      strict final candidate pipeline
  advisory_store.py         persisted advisory boundary
```

Trade Brain routers are namespaced under `backend/routers/tradebrain*.py`.
The existing `/api/analysis` route remains UI-compatible but its signal is a research label and it persists Trade Brain advisory metadata.

## Validation expectations

Before declaring a change complete:

1. Compile changed Python integration modules.
2. Run `python -m unittest discover -s tests -p "test_tradebrain_*.py" -v`.
3. If frontend contract/UI changed, run a production frontend build.
4. Keep observational live-source smokes non-authorizing and non-performance-claiming.
5. Reject malformed/blocked/unknown external responses rather than treating them as successful empty feeds.

The GitHub workflow `.github/workflows/tradebrain-foundation.yml` enforces the current backend tests and frontend build contract.

## Setup

Python backend:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -e .
pip install fastapi uvicorn websockets aiosqlite numpy feedparser
uvicorn backend.app:app --reload --port 8000
```

Frontend:

```bash
cd frontend
npm ci
npm run dev
```

AI-powered Deep Analysis requires one supported LLM provider key.
Kite credentials are optional and only required if using Kite as a market-data transport.

See `.env.example` and `README.md` for current configuration.

## Canonical docs

- `AGENTS.md`
- `TRADEBRAIN_REFRAME.md`
- `TRADEBRAIN_PHASE4.md`
- `TRADEBRAIN_PHASE5.md`
- `TRADEBRAIN_PHASE6.md`
- `TRADEBRAIN_PHASE7_TO_10.md`

Preserve useful upstream features, but when an upstream behavior conflicts with these boundaries, the Trade Brain boundary wins.
