# Trade Brain Reframe for `indian-trading-agent`

Status: foundation + Phase 1 security-master implementation

This file is the canonical architectural bridge between the existing Indian Trading Agent repository and the prior Trade Brain / BSE Engine work. It intentionally removes historical troubleshooting logs, retired L1/L2/L3 rescue-cycle details, local Windows paths, screenshots, and milestone-by-milestone chat continuity text. Those were useful during development but should not become product architecture.

## 1. Final product direction

The repository remains the application foundation. We do **not** replace its multi-agent pipeline, web UI, scanners, backtests, paper trading, calibration, market regime work, signal performance tracking, or memory system.

Trade Brain adds the missing control plane:

```text
OFFICIAL / REFERENCE DATA       MARKET DATA
NSE/BSE/SEBI/RBI/etc.           price/volume/timeframes
        |                              |
        +--------------+---------------+
                       |
          IDENTITY + PROVENANCE + MEMORY
                       |
          REPO RESEARCH / MULTI-AGENT LAYER
     scanner / news / fundamentals / debate / regime
                       |
          HISTORY + OUTCOME / REPLAY EVIDENCE
                       |
            MARKET STRUCTURE + RISK
                       |
                 CRASH GUARD
                       |
          DETERMINISTIC HARD-RULE ARBITER
                       |
             STRUCTURED TRADE PLAN
              DAY | SWING_POSITION
                       |
              ADVISORY GUIDANCE
```

LLMs are reasoning and orchestration tools. They are not the source of truth for market data, security identity, broker rules, or hard risk constraints.

## 2. What we keep from this repository

These are stronger or more mature than the corresponding old prototypes and should be reused rather than rebuilt:

- LangGraph multi-agent analyst / bull-bear / risk debate pipeline.
- FastAPI + Next.js application shell.
- scanner and unified recommender as **discovery tools**.
- support/resistance, pivots, cyclical tools, charts and news UI.
- paper trading and historical simulation.
- signal-performance feedback and conditional regime weights.
- confidence calibration / Brier-score concepts.
- market-regime classification.
- shadow trades / counterfactual tracking.
- memory persistence, pruning and decay.
- provider abstraction for multiple LLMs.
- existing `order_execution_enabled=False` safety stance.

The goal is to improve the meaning and governance of these outputs, not throw them away.

## 3. What Trade Brain changes

### 3.1 Heuristic score is not learned probability

The repository currently derives a `success_probability` from score magnitude and aligned-signal count. That number is useful for ranking but it is not automatically a learned probability for the current stock, setup family, regime, direction, timeframe, and exit geometry.

Compatibility rule:

- keep legacy response fields so the existing frontend does not break;
- label them `HEURISTIC_NOT_LEARNED`;
- treat them as soft evidence;
- graduate to a learned/calibrated probability only after plan-specific historical outcomes and out-of-sample validation exist.

### 3.2 Daily Verdict is context, not permission

GREEN / YELLOW / RED may summarize broad market conditions. It cannot authorize a trade.

A final plan still needs explicit entry / stop / target and must pass deterministic hard rules.

### 3.3 Security identity becomes ISIN-first

Never assume that a ticker or similar company name is a stable security identity.

Target model:

```text
Issuer / Company Entity
    -> Canonical Security (ISIN)
        -> NSE Listing
        -> BSE Listing
```

Automatic cross-exchange merge requires the same valid ISIN. Missing ISIN means "unresolved", not "safe to fuzzy merge". Missing from the latest exchange list does not prove delisting.

### 3.4 Provenance becomes first-class

Official/reference collectors should preserve where practical:

- source name;
- source URL;
- fetch timestamp;
- raw payload/archive path;
- SHA-256;
- normalization/parser version.

Raw payload is archived before normalization in the Phase 1 security-master collectors so an import can be reproduced or replayed.

### 3.5 Hard rules sit above AI

Current immutable/user-controlled policy:

- advisory-only; no automatic order execution;
- DAY plan needs explicit entry, TP and SL;
- DAY: no new entry from 15:10 IST;
- DAY must be flat before 15:15 IST;
- SWING/POSITION is LONG-only in the current equity/MTF architecture;
- verified broker/exchange restrictions outrank model output;
- Severe Crash Guard blocks fresh LONG exposure;
- a crash signal does not automatically create a SHORT;
- AI/backtesting may propose changes to soft parameters but may not silently rewrite hard rules.

### 3.6 Soft information is allowed to learn

Examples:

- support/resistance reliability;
- ATH behaviour;
- timeframe usefulness;
- regime importance;
- volume significance;
- Crash Guard threshold candidates;
- relative-market correlations;
- false-break probability;
- time-to-target;
- DAY reward/risk threshold;
- SWING target geometry;
- historical analogue feature weights.

Promotion flow:

1. Keep current model A.
2. Create challenger B.
3. Replay/backtest both without look-ahead.
4. Validate walk-forward / out-of-sample.
5. Report improvement and risk trade-offs.
6. Promote deliberately.
7. Never silently change a hard rule.

## 4. Two operating profiles

### INDIAN_MARKET_MASTER

Broad market intelligence across Indian equities:

- discover stocks;
- company/fundamental/news research;
- NSE/BSE/SEBI/RBI context;
- sector and macro context;
- events and filings;
- strategy exploration;
- market regime and breadth;
- portfolio/risk intelligence later.

This profile can use the repository's broad stock universes and scanners.

### FOCUS_INSTRUMENT_LAB

Deep learning for one chosen instrument, initially compatible with the BSE Ltd use case:

- richer historical storage;
- multi-timeframe reconstruction;
- corporate-action-aware comparable-price eras;
- adaptive ATH/support/resistance;
- historical analogues;
- plan-specific outcomes;
- Crash Guard calibration;
- level reliability;
- relative-market context;
- broker-cost economics.

Broad-market signal weights must not be assumed to transfer to the focus instrument. The instrument's own history decides.

## 5. Trade modes

### DAY

- LONG or SHORT.
- same-session only.
- explicit entry / TP / SL required.
- 15:10 IST onward: no fresh DAY entry.
- before 15:15 IST: must be flat.
- current 1:1 reward/risk is a **provisional starting floor**, not a learned optimum.
- multi-timeframe information can contribute, but no rigid "D1 must do X / M5 must do Y" dogma.

### SWING_POSITION

- overnight / multi-day LONG equity.
- MTF may later be used as a funding mechanism.
- the retired L1/L2/L3 averaging/rescue cycle is **not** revived.
- current ~1:3 reward/risk is a starting preference, not immutable truth.
- true net target must eventually include financing, brokerage, taxes, duties, DP/pledge costs, slippage and days held.

## 6. Market vs after-market brain schedule

The product should have an explicit operating state rather than one undifferentiated loop.

Typical states:

- `PRE_MARKET_RESEARCH`
- `LIVE_MARKET_RESEARCH`
- `LIVE_MARKET_RISK_ONLY` during the DAY exit window / hard exit period
- `POST_MARKET_STUDY`
- `STUDY_REPLAY` on non-market days

The current foundation uses weekday/clock logic only. A verified NSE/BSE trading calendar must later override holidays and special sessions.

## 7. Source-of-truth hierarchy

### Security identity

Official exchange/security-master data + ISIN mapping. Phase 1 now ingests official NSE/BSE equity masters into a persistent local identity model.

### Corporate events / regulation

Prefer official NSE/BSE/SEBI/RBI/company exchange filings. News/social sources may provide leads but not silently replace official facts.

### Market prices

A configured market-data provider with timestamps and quality checks. yfinance is useful for low-friction research and prototyping, but long-term Trade Brain history should have explicit auditability and provider metadata.

### Broker rules / costs

Verified broker documentation/API behaviour. Do not let an LLM invent margin, cost, product or execution rules.

### AI

Interpretation, synthesis, research planning, hypothesis generation, debate and explanation.

## 8. Implemented in this branch

- `backend/tradebrain/policy.py`
  - deterministic hard-rule arbiter;
  - DAY 15:10 / 15:15 rules;
  - mandatory TP/SL geometry;
  - SWING short block;
  - Severe Crash Guard LONG block;
  - broker-rule block;
  - advisory-only output;
  - provisional R:R warnings.

- `backend/tradebrain/schedule.py`
  - pre-market / live / exit-window / post-market / study modes.

- `backend/tradebrain/identity.py`
  - ISIN normalization;
  - no automatic cross-exchange merge without matching valid ISIN.

- `backend/tradebrain/provenance.py`
  - SHA-256 helpers and standard provenance record.

- `backend/tradebrain/store.py`
  - namespaced `tb_*` issuer/security/listing/source/raw-artifact/plan tables;
  - persistent plan evaluations and outcomes.

- `backend/tradebrain/security_store.py`
  - non-destructive metadata columns for official security masters;
  - one-transaction bulk upsert;
  - idempotency counters;
  - cross-exchange ISIN-match statistics;
  - exact listing and ISIN lookups;
  - missing-from-refresh does not imply delisted.

- `backend/tradebrain/security_master.py`
  - official NSE `EQUITY_L.csv` collector;
  - official BSE active-equity scrip-list collector;
  - browser-like transport/referer handling;
  - raw payload archive before parsing;
  - SHA-256 + parser-version provenance;
  - tolerant NSE CSV and BSE JSON parsing;
  - explicit invalid/missing-ISIN rejection sample;
  - safe ISIN-only cross-exchange identity.

- `backend/tradebrain/soft_evidence.py`
  - compatibility annotation for legacy score-derived probabilities;
  - Daily Verdict marked as soft context only.

- `backend/routers/tradebrain.py`
  - doctrine and operating-mode APIs;
  - deterministic plan validation/outcome APIs;
  - exact identity APIs;
  - NSE/BSE/all security-master refresh APIs;
  - security-master statistics API;
  - roadmap API.

- existing recommender and Daily Verdict endpoints remain backwards compatible but expose Trade Brain warnings/metadata.

### Phase 1 endpoints

```text
POST /api/tradebrain/security-master/nse
POST /api/tradebrain/security-master/bse
POST /api/tradebrain/security-master/refresh
GET  /api/tradebrain/security-master/stats
GET  /api/tradebrain/identity/isin/{isin}
GET  /api/tradebrain/identity/listing/{exchange}/{symbol}
```

The collector output reports received/valid/rejected rows, inserted/updated listings, newly created canonical securities, provenance/artifact identity and a rejected-row sample. Repeating the same master updates existing listings instead of duplicating them.

## 9. Implementation sequence

### Phase A — official security master + persisted identity

**STATUS: IMPLEMENTED IN CODE; LIVE EXCHANGE TRANSPORT STILL REQUIRES RUNTIME VALIDATION.**

Implemented:

- issuer entities created deterministically per verified ISIN;
- canonical securities by ISIN;
- NSE listings keyed by NSE symbol;
- BSE listings keyed by stable six-digit scrip code with BSE `scrip_id` preserved separately;
- NSE series/industry metadata and BSE group/industry metadata where supplied;
- raw source archive + SHA-256 + parser version;
- idempotent bulk upsert;
- explicit rejected-row sample for missing/invalid identity;
- exact ISIN/listing lookup APIs;
- cross-exchange match counts;
- safe rule that source absence does not prove delisting.

Not silently added:

- fuzzy issuer merging;
- automatic alias merging by similar company name;
- inferred delisting/suspension from absence;
- live broker identity substitution.

Verified CIN/LEI/company relationships and richer aliases/classifications can be added later without weakening the ISIN rule.

### Phase B — corporate events and document memory

- NSE/BSE announcements/filings;
- raw feed archive;
- exact event identity/upsert;
- event -> security/entity resolution;
- attachment download;
- SHA-256 / duplicate detection;
- local document text extraction;
- event importance and "what changed?" queue.

### Phase C — audited market-data history

- OHLCV persistence;
- provider/source/timestamp metadata;
- incremental sync;
- gap/duplicate checks;
- session-boundary checks;
- corporate-action-aware adjustment/comparable eras;
- derived 5m/15m/30m/1h/2h/4h/1d/1w data;
- look-ahead-safe replay API.

### Phase D — plan-specific outcome engine

Every structured setup should record:

- entry timestamp/price;
- mode and direction;
- TP / SL;
- context features at decision time;
- TP-first / SL-first / neither;
- MAE / MFE;
- time-to-event;
- R multiple;
- regime;
- source/evidence references.

This replaces vague "the signal won" learning with plan-specific evidence.

### Phase E — BSE Focus Instrument Lab

- adaptive structural levels;
- comparable ATH;
- Crash Guard replay;
- level reliability;
- multi-timeframe usefulness;
- historical analogue validation;
- normal-day false-positive testing;
- relative BSE-vs-market behaviour.

### Phase F — cost and funding economics

- own contribution;
- funded amount;
- days held;
- broker interest;
- brokerage/taxes/fees;
- true break-even;
- true net target.

Keep charges in a broker adapter/configuration layer and verify them rather than hardcoding assumptions forever.

### Phase G — controlled learning

- base/challenger model registry;
- versioned features and weights;
- walk-forward evaluation;
- calibration metrics;
- promotion audit trail;
- rollback.

### Phase H — broker boundary

- broker adapter interface;
- read-only account/market integration first;
- paper execution;
- rule validation;
- only then reconsider whether live execution is a desired product feature.

Until explicitly changed, automatic execution stays OFF.

## 10. What not to port from the old checkpoints

Do not carry forward as active product design:

- retired Probe/L1/L2/L3 rescue averaging;
- old cycle kill/recovery machinery;
- fixed +₹45 target as a current trading rule;
- one giant desktop `app.py` architecture;
- local machine paths and backup hashes as application doctrine;
- provisional thresholds described as learned truths;
- troubleshooting history that does not affect current architecture.

Historical data can remain archived for audit, but it must not silently control the new model.

## 11. Definition of a trustworthy final result

A final Trade Brain result should clearly separate:

1. **facts/evidence** — with source and time;
2. **heuristic/learned estimates** — labelled with validation status;
3. **AI interpretation** — narrative/reasoning, never source of truth;
4. **hard-rule status** — deterministic PASS / WAIT / BLOCK / HARD_EXIT;
5. **trade geometry** — entry / TP / SL / R:R;
6. **cost status** — gross vs net economics explicitly stated;
7. **execution boundary** — advisory only unless a later product decision changes it.

That separation is the main architectural principle of this reframe.
