# Indian Trading Agent — Trade Brain Developer Guide

This repository is governed by the Trade Brain v0.12 architecture.
Read `AGENTS.md`, `TRADEBRAIN_REFRAME.md`, and `TRADEBRAIN_KITE_DATA.md` before changing trading/data logic.

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

The upstream agent price-data contract now routes through Trade Brain by default:

- core OHLCV -> Trade Brain market-source policy
- price-derived indicators -> same audited Trade Brain OHLCV source
- fundamentals/news -> their appropriate non-Kite vendors
- FII/DII/bulk/delivery data -> NSE-specific source layer

Do not bypass the Trade Brain source policy for new agent price/indicator code.

## Learning / calibration rules

- Hard rules are protected and never auto-optimized.
- Phase-5 challenger hypotheses/windows are frozen before evaluation.
- TRAIN is diagnostic only.
- Validation/walk-forward evidence controls readiness for human review.
- Soft runtime values change only after explicit human approval and activation.
- Expose the active soft parameter key/version/source in deterministic outputs.
- Prospective experiments may use only observations strictly after their freeze boundary.

Legacy recommender `success_probability` remains heuristic/non-learned/non-authorizing unless separately proven and promoted through the Trade Brain research process.

## Data and replay rules

- Preserve raw evidence and source provenance.
- Use SHA-256/content-addressed archives for official/reference artifacts where implemented.
- Keep source identity explicit: official exchange/reference vs non-official vendor.
- Historical replay must avoid future leakage (`ts_close <= as_of`, publication-time cutoffs).
- Do not silently overwrite raw traded prices with adjusted prices.
- Corporate-action comparability boundaries must stay explicit.
- NSE and BSE calendar evidence are exchange-aware; do not silently assume special-session equivalence.

### Price-source hierarchy

When Kite credentials are configured:

```text
Kite Historical REST -> audited finalized OHLCV -> replay/backtest/agents/indicators
Kite WebSocket        -> continuous latest live quote state
Kite REST Quote       -> on-demand live quote snapshot
```

If Kite is unavailable/not configured:

```text
Yahoo/yfinance -> explicitly labelled fallback/research source
```

Never silently call fallback data Kite data. Fundamentals/news may remain Yahoo/other vendors because Kite does not provide those data classes.

## Zerodha Kite

Trade Brain's Kite integration is `MARKET_DATA_ONLY`.
Allowed uses:

- instrument master
- REST quote snapshots
- historical candles
- WebSocket live market state
- replay/backtest input

Key implementation rules:

- `kite_data.py` handles REST instruments/quotes/historical candles.
- `kite_history_range.py` chunks long historical ranges and preserves per-chunk audit records.
- `kite_stream.py` parses the documented binary WebSocket market packets and stores latest live quote state.
- live WebSocket ticks are not finalized replay candles.
- text order postbacks on the WebSocket are ignored.
- `market_source_policy.py` selects Kite first when credentials exist and explicitly labels Yahoo fallback otherwise.
- `tradingagents/dataflows/tradebrain_market.py` feeds agent OHLCV and price-derived indicators from the same audited source.

The adapters must not expose place/modify/cancel-order methods.
A credential may belong to an NRI account, but credential account type must not change resident trader identity, resident cost profile or policy.

## Frontend / market-data contract

Deep Analysis must display research/advisory language rather than a guaranteed "Final Decision" or order instruction.
The frontend should preserve and render `tradebrain_advisory` metadata from the analysis WebSocket/API.

Current candidate UI vocabulary:

- LONG CANDIDATE
- SHORT CANDIDATE
- EXIT CANDIDATE
- WAIT
- NO TRADE

The ordinary market quote endpoint follows:

1. fresh persisted Kite WebSocket quote
2. Kite REST full quote
3. explicitly-labelled Yahoo fallback

Chart intervals supported by Trade Brain use the preferred historical policy; unsupported presentation helpers must identify their fallback source.

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
  market_data.py            Yahoo fallback market-data ingestion
  market_data_store.py      audited OHLCV store
  market_source_policy.py   Kite-primary / Yahoo-fallback source selection
  kite_data.py              read-only Kite REST adapter
  kite_history_range.py     audited chunked long-history Kite sync
  kite_stream.py            read-only Kite WebSocket latest-live-state plane
  replay.py                 look-ahead-safe replay
  focus_lab.py              instrument research
  challenger.py             walk-forward challenger logic
  challenger_store.py       frozen definitions/promotions
  soft_runtime.py           approved runtime soft preferences
  evidence_baseline.py      descriptive evidence packs
  prospective_gap.py        future-only BSE hypothesis collector
  equity_costs.py           resident equity economics
  paper_ledger.py           net-cost paper accounting
  advisory_pipeline.py      strict final candidate pipeline
  advisory_store.py         persisted advisory boundary

tradingagents/dataflows/
  tradebrain_market.py      upstream-agent OHLCV/indicator compatibility provider
```

Trade Brain routers are namespaced under `backend/routers/tradebrain*.py`.
The existing `/api/analysis` route remains UI-compatible but its signal is a research label and it persists Trade Brain advisory metadata.

## Validation expectations

Before declaring a change complete:

1. Compile changed Python integration modules.
2. Run `python -m unittest discover -s tests -p "test_tradebrain_*.py" -v`.
3. Validate `start.sh` syntax when launcher behavior changes.
4. If frontend contract/UI changed, run a production frontend build.
5. Keep observational live-source smokes non-authorizing and non-performance-claiming.
6. Reject malformed/blocked/unknown external responses rather than treating them as successful empty feeds.
7. Do not claim live Kite transport success until valid Kite credentials are configured and authenticated.

The GitHub workflow `.github/workflows/tradebrain-foundation.yml` enforces the current backend tests and frontend build contract.

## Setup

Python backend:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -e .
pip install fastapi uvicorn aiosqlite numpy feedparser
uvicorn backend.app:app --reload --port 8000
```

Frontend:

```bash
cd frontend
npm ci
npm run dev
```

Or use `./start.sh`. When `.env` contains `KITE_API_KEY`, `KITE_ACCESS_TOKEN`, and `KITE_LIVE_SUBSCRIPTIONS`, the launcher also starts the read-only Kite WebSocket sidecar. Without them, startup remains functional through the explicit fallback data path.

AI-powered Deep Analysis requires one supported LLM provider key.
Kite credentials are optional and only required if using Kite as the preferred market-data transport.

See `.env.example`, `README.md`, and `TRADEBRAIN_KITE_DATA.md` for current configuration.

## Canonical docs

- `AGENTS.md`
- `TRADEBRAIN_REFRAME.md`
- `TRADEBRAIN_PHASE4.md`
- `TRADEBRAIN_PHASE5.md`
- `TRADEBRAIN_PHASE6.md`
- `TRADEBRAIN_PHASE7_TO_10.md`
- `TRADEBRAIN_KITE_DATA.md`

Preserve useful upstream features, but when an upstream behavior conflicts with these boundaries, the Trade Brain boundary wins.
