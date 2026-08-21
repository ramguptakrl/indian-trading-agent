# Indian Trading Agent — Trade Brain v0.12

> Advisory multi-agent research and deterministic control plane for Indian equities.

This repository is a reframed fork of `pradeepsiddappa/indian-trading-agent`, which itself builds on TauricResearch's TradingAgents framework. The upstream multi-agent research, scanner/UI components and data abstractions are preserved where useful, but final behavior is governed by the Trade Brain architecture.

**This project does not place broker orders.** It produces research candidates, validates them through deterministic safety/data rules, measures outcomes and supports paper/replay research.

## Active product boundary

Modeled trader: **RESIDENT_INDIAN**.

Active equity modes:

- **INTRADAY** — LONG or SHORT, same cash-market session only; no fresh entry from 15:10 IST; flat before 15:15 IST.
- **SWING** — multi-day LONG cash/delivery using the trader's own cash.

Not active:

- MTF / funded delivery
- F&O strategy execution
- automatic broker orders
- AI overriding hard safety rules

Historical internal aliases remain only for old audit/replay compatibility:

- `DAY` → `INTRADAY`
- `SWING_POSITION` → `SWING`

## Architecture

```text
OFFICIAL / REFERENCE DATA + MARKET DATA
        ↓
IDENTITY + PROVENANCE + CORPORATE MEMORY
        ↓
MULTI-AGENT RESEARCH / SCANNERS / EVIDENCE
        ↓
AUDITED HISTORY + LOOK-AHEAD-SAFE REPLAY
        ↓
OUTCOMES + FOCUS INSTRUMENT LAB
        ↓
CRASH GUARD + MARKET STRUCTURE + RISK
        ↓
DETERMINISTIC HARD-RULE GATE
        ↓
APPROVED / DEFAULT SOFT PREFERENCE
        ↓
RESIDENT TRANSACTION-COST SCENARIO
        ↓
ADVISORY CANDIDATE
```

The safe current research labels are:

- `LONG_CANDIDATE`
- `SHORT_CANDIDATE`
- `EXIT_CANDIDATE`
- `WAIT`
- `NO_TRADE`

A research label is **not** an order instruction.

## Trade Brain phases

### Phase 0 — deterministic advisory boundary
Explicit Entry/SL/TP geometry, INTRADAY time rules, SWING-long-only rule, Crash Guard block, broker/exchange restriction gate and execution-disabled output.

### Phase 1 — official security identity
Official NSE/BSE security-master ingestion, raw archives/hashes, ISIN-first canonical identity and exact exchange-listing mapping without fuzzy cross-exchange merging.

### Phase 2 — corporate-event/document memory
Official NSE announcement RSS, fail-safe BSE announcement parsing, repeat-safe event inbox, exact identity linkage, filing download/dedup/text extraction and a persistent `what changed?` queue.

### Phase 3 — audited historical market data + replay
Identity-bound RAW_UNADJUSTED OHLCV, source/fetch audit records, quality checks, comparable-price eras, derived timeframes and strict `ts_close <= as_of` replay.

### Phase 4 — strict outcomes + Focus Instrument Lab
Outcome states include `TP_FIRST`, `SL_FIRST`, `NEITHER`, `NOT_ENTERED`, `AMBIGUOUS` and `INSUFFICIENT_DATA`. Intrabar order is never guessed. The lab records MAE/MFE/R, regime/cohort behavior, level reliability, Crash Guard counterfactuals and event-price associations.

### Phase 5 — frozen challenger / walk-forward governance
Predeclared challenger hypotheses, frozen TRAIN/VALIDATION/WALK_FORWARD windows, future-result censoring, sample/coverage gates and explicit human approval before any soft parameter can become active.

### Phase 6 — resident equity economics + paper ledger
Versioned resident-individual equity charges, net P&L, after-cost break-even, net-target solver and a conservative full-notional paper ledger. MTF financing values are structurally zero/false.

### Phase 7 — approved soft runtime
Only ACTIVE human-approved soft R:R parameters can affect the PASS/WAIT preference. Hard rules cannot be changed by the soft registry.

### Phase 8 — verified exchange calendar
Official NSE cash-market holiday ingestion with source hashes/year coverage, fail-closed unknown calendar state and special-session timing verification. BSE calendar/special-session evidence is kept exchange-aware.

### Phase 9 / v0.12 data plane — Zerodha Kite MARKET_DATA_ONLY
Kite is now the **preferred price-data transport when credentials are configured**. The Trade Brain data plane supports:

- exact Kite instrument master resolution
- Kite Historical REST candles
- chunked long-range historical sync into the audited Phase-3 store
- Kite REST LTP/OHLC/full quote snapshots
- Kite WebSocket binary live-market packets
- persisted latest live quote state
- upstream TradingAgents core OHLCV and price-derived indicators routed through the same Trade Brain source policy
- user-facing Quote/Chart endpoints following the same source hierarchy

The Kite adapters expose **no place/modify/cancel-order methods**.

A Kite credential may belong to an NRI account; that credential type does not change the modeled `RESIDENT_INDIAN` trader, resident cost model or policy.

### Phase 10 — final fail-closed advisory pipeline
Explicit labelled candidate parsing → verified calendar → Crash Guard → broker/exchange permission → deterministic gate → soft preference → resident cost scenario.

Free-form bullish/bearish prose is never guessed into a trade. `SELL / EXIT CANDIDATE` is an exit/reduction context and cannot silently open a short.

## Market-data hierarchy

Price and price-derived indicator truth now follows this hierarchy:

```text
ZERODHA KITE (when configured)
  ├─ Historical REST -> audited finalized OHLCV -> replay/backtest/agents/indicators
  ├─ WebSocket       -> continuous latest live quote state
  └─ REST Quote      -> on-demand live quote snapshot
             ↓
        TRADE BRAIN
             ↓
       ADVISORY ONLY
```

If Kite is not configured or a permitted Kite data request fails:

```text
Yahoo/yfinance -> explicitly labelled FALLBACK / RESEARCH source
```

Important separation:

- **Live WebSocket ticks are not finalized replay candles.**
- Historical/replay candles come through audited historical ingestion.
- Fundamentals/news remain on appropriate non-Kite providers because Kite does not supply those data classes.
- NSE-specific FII/DII/bulk/delivery information remains in the NSE source layer.
- A fallback source is never silently relabelled as Kite or official exchange truth.

## Current execution boundary

Every final Trade Brain advisory remains structurally non-executing:

```text
advisory_only = true
trade_authorization = false
order_execution_allowed = false
order_endpoint_present = false
```

## Evidence stage

The first BSE Ltd evidence pack is descriptive/exploratory rather than a strategy-performance claim. The current audited vendor baseline includes long daily history plus recent hourly/five-minute history, explicit quality flags and price-comparability eras.

`BSE_PROSPECTIVE_HYPOTHESIS_001` is frozen for **future-only** validation after 2026-08-21. Historical observations used to generate the hypothesis cannot count toward validation.

See:

- `research/BSE_EVIDENCE_BASELINE_2026-08-21.md`
- `research/BSE_PROSPECTIVE_HYPOTHESIS_001.md`

## Data sources

Trade Brain distinguishes official/reference sources from vendor sources.

- NSE/BSE official security identity and corporate evidence are archived with provenance.
- Official NSE calendar data is used for verified cash-market holiday coverage.
- Zerodha Kite is the preferred market-price transport when credentials are configured.
- Yahoo/yfinance remains a **non-official fallback/research vendor** for price data and a separate provider for data classes such as fundamentals/news where used.

A vendor source is never relabelled as an exchange source of truth.

## API keys

You do **not** need a Kite API key to develop, run the deterministic framework, replay stored/vendor data or continue the evidence stage.

For AI-powered Deep Analysis/reflection, configure one supported LLM provider key (Anthropic/OpenAI/Google/etc.).

For Kite market data later:

```env
KITE_API_KEY=...
KITE_API_SECRET=...       # login/token-exchange flow only
KITE_ACCESS_TOKEN=...     # runtime market-data access
KITE_LIVE_SUBSCRIPTIONS=NSE:BSE
KITE_LIVE_MODE=quote      # ltp | quote | full
```

When those runtime fields are configured, `./start.sh` automatically starts the read-only Kite WebSocket sidecar. Without them, startup remains functional through the explicit fallback path.

Kite remains read-only inside Trade Brain.

See `.env.example` and `TRADEBRAIN_KITE_DATA.md`.

## Quick start

Prerequisites:

- Python 3.10+
- Node.js 20+
- an LLM API key only if you want AI-powered Deep Analysis

```bash
git clone https://github.com/ramguptakrl/indian-trading-agent.git
cd indian-trading-agent

python3 -m venv venv
source venv/bin/activate       # Windows: venv\Scripts\activate
pip install -e .
pip install fastapi uvicorn aiosqlite numpy feedparser

cd frontend
npm install
cd ..

./start.sh
```

Or run separately:

```bash
uvicorn backend.app:app --reload --port 8000
```

and:

```bash
cd frontend
npm run dev
```

Frontend: `http://localhost:3000`
Backend: `http://localhost:8000`

## Important APIs

Trade Brain APIs are namespaced under `/api/tradebrain/...` and include security-master identity, corporate events/documents, audited market data/replay, Focus Lab/outcomes, challenger governance, resident costs/paper ledger, calendar, Kite data-only transport and final advisory evaluation.

Kite/source APIs include:

- `GET /api/tradebrain/phase9/data/status`
- `POST /api/tradebrain/phase9/data/sync-preferred-history`
- `POST /api/tradebrain/phase9/kite/quote`
- `POST /api/tradebrain/phase9/kite/sync-history`
- `POST /api/tradebrain/phase9/kite/sync-history-range`
- `GET /api/tradebrain/phase9/kite/live/latest/{exchange}/{symbol}`

The legacy `/api/analysis` route is retained for upstream UI compatibility, but its `signal` field now carries a **non-authorizing research label** and the result includes the persisted Trade Brain advisory boundary.

## Frontend behavior

Deep Analysis displays the research label and deterministic Trade Brain status separately. It must not present a candidate as an executed or guaranteed trade.

The regular quote path prefers a fresh Kite WebSocket quote, then Kite REST quote, then an explicitly-labelled Yahoo fallback. Supported chart intervals use the preferred audited historical source policy.

Historical upstream `BUY/SELL/HOLD` values may still exist in old records or legacy research modules; those are compatibility/evidence labels, not Trade Brain authorization.

## Validation

The Trade Brain CI workflow runs:

- Python integration compile
- `start.sh` syntax validation when launcher behavior changes
- all `test_tradebrain_*.py` tests
- observational source/replay smokes
- BSE descriptive evidence artifact generation
- frontend production build for the Trade Brain analysis/history contract

The current credential-independent v0.12 data-plane tests cover Kite binary packet parsing, heartbeat/truncation handling, ignoring order postback text, latest-live-state persistence, conservative historical range chunking, Kite-primary/Yahoo-fallback selection, upstream agent price routing and same-source technical indicators.

**No live Kite success is claimed until valid Kite credentials are configured and authenticated.**

Live-source smokes are mechanics/transport checks only and are never strategy-performance claims.

## Canonical documentation

Read these before changing architecture:

- `AGENTS.md`
- `TRADEBRAIN_REFRAME.md`
- `TRADEBRAIN_PHASE4.md`
- `TRADEBRAIN_PHASE5.md`
- `TRADEBRAIN_PHASE6.md`
- `TRADEBRAIN_PHASE7_TO_10.md`
- `TRADEBRAIN_KITE_DATA.md`

## Attribution

This project preserves substantial architecture from:

- `pradeepsiddappa/indian-trading-agent`
- TauricResearch `TradingAgents`

See `LICENSE` and `NOTICE` for licensing/attribution details.

## Disclaimer

This software is for research and educational use. It is not financial advice and does not guarantee outcomes. Market trading involves risk of loss. Trade Brain intentionally separates AI research from deterministic controls and keeps automatic order execution disabled.
