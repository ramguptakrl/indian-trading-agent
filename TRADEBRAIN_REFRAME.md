# Trade Brain Reframe for `indian-trading-agent`

Status: **Phases 0-6 implemented on the Trade Brain reframe branch**  
Current Trade Brain version: **0.7.0**

This is the canonical product architecture. Historical chat/checkpoint details are not product doctrine.

## 1. Product identity

Trade Brain is a **resident-Indian equity research and paper-accounting system** built on top of the existing Indian Trading Agent repository.

The repository's LangGraph research pipeline, FastAPI/Next.js shell, scanners, market-regime work, simulation, calibration, memory and UI remain useful. Trade Brain adds identity, provenance, official-event memory, audited replay, deterministic safety, outcome learning, walk-forward governance and net-cost paper accounting.

LLMs are evidence synthesis/reasoning tools. They are not the source of truth for prices, identity, exchange/broker rules, charges or trade permission.

## 2. Only two active trade modes

### INTRADAY

- Resident cash-equity intraday.
- LONG or SHORT.
- Same cash-market session only.
- Explicit Entry / Stop-Loss / Take-Profit required.
- No fresh entry from **15:10 IST**.
- Must be flat before **15:15 IST**.
- Provisional R:R starting floor is ~1:1 and remains a soft, challengeable parameter.

### SWING

- Resident multi-day cash/delivery equity.
- LONG only in the active architecture.
- Funded with the trader's **own cash**.
- Explicit Entry / Stop-Loss / Take-Profit required.
- Provisional R:R starting preference is ~1:3 and remains a soft, challengeable parameter.

There is **no MTF mode**, no funded-amount model, no pledge-financing logic and no financing-interest engine. Derivatives and overnight shorting are outside the active product.

Historical Phases 0-5 rows used `DAY` and `SWING_POSITION`. Those values remain internal compatibility aliases only:

```text
DAY             -> INTRADAY
SWING_POSITION  -> SWING
```

New user-facing Phase-6 APIs and paper-ledger records use only `INTRADAY` and `SWING`.

## 3. Trader identity is separate from data-credential identity

The modeled trader is:

```text
RESIDENT_INDIAN
```

A Zerodha/Kite credential may later be configured to provide:

- live quotes;
- WebSocket ticks;
- historical candles;
- backtest/replay inputs.

That credential may belong to an NRI account. **This does not make the modeled trader NRI.**

A data-only credential must never import into policy/economics:

- NRI trading restrictions;
- NRI brokerage rates;
- NRI TDS/tax treatment;
- PIS/Non-PIS rules;
- NRI order permissions.

The active boundary is:

```text
KITE / BROKER CREDENTIAL
        |
        +--> MARKET DATA ONLY
             live / historical / backtest

RESIDENT TRADER PROFILE
        |
        +--> INTRADAY / SWING policy
        +--> resident equity cost profile
        +--> paper accounting

ORDER API = OFF
```

## 4. Architecture

```text
OFFICIAL / REFERENCE DATA          MARKET DATA
NSE / BSE / regulators             audited vendor / future Kite data-only adapter
          |                                  |
          +----------------+-----------------+
                           |
             IDENTITY + PROVENANCE + MEMORY
                           |
              MULTI-AGENT RESEARCH LAYER
                           |
                 AUDITED HISTORY / REPLAY
                           |
                  STRICT OUTCOME ENGINE
                           |
                FOCUS INSTRUMENT LAB
                           |
          FROZEN CHALLENGER / WALK-FORWARD
                           |
            MARKET STRUCTURE + CRASH GUARD
                           |
             DETERMINISTIC HARD-RULE GATE
                           |
              RESIDENT EQUITY COST ENGINE
                           |
           STRUCTURED INTRADAY / SWING PLAN
                           |
              NET-COST PAPER ACCOUNTING
                           |
                   ADVISORY GUIDANCE
```

Automatic order execution remains OFF.

## 5. Source-of-truth rules

### Security identity

Official exchange security masters with ISIN-first mapping.

```text
Issuer -> Canonical Security (ISIN) -> NSE/BSE Listing
```

No fuzzy cross-exchange merge.

### Corporate events

Prefer official NSE/BSE/regulator/company exchange filings. News/social sources may provide leads but cannot silently replace official facts.

### Market prices

Every persisted source must retain source/provider, timestamps and quality metadata. Yahoo/yfinance is currently a NON-OFFICIAL first adapter. A future Kite adapter can be added as data transport without changing trader identity.

### Broker costs

Use versioned, verified **resident individual** equity charge profiles. Never derive costs from the account type of a data-only credential.

### AI

Interpretation, hypothesis generation, synthesis, debate and explanation only.

## 6. Hard rules above AI

Current hard/user-controlled boundaries include:

- advisory only;
- order execution OFF;
- only INTRADAY and SWING active;
- explicit Entry / SL / TP required;
- INTRADAY no new entry from 15:10 IST;
- INTRADAY flat before 15:15 IST;
- SWING LONG cash/delivery only;
- MTF disabled;
- verified broker/exchange restrictions outrank model opinion;
- Severe Crash Guard blocks fresh LONG exposure;
- a crash signal does not automatically create a SHORT.

Phase-5 learning may challenge soft parameters but cannot silently rewrite these hard boundaries.

## 7. Soft information may learn

Examples:

- INTRADAY minimum R:R;
- SWING minimum R:R;
- level reliability;
- timeframe usefulness;
- regime importance;
- volume significance;
- event-category relevance;
- false-break behaviour;
- time-to-target;
- historical analogue weights.

Promotion flow:

1. Keep incumbent A.
2. Define challenger B.
3. Freeze hypothesis + TRAIN / VALIDATION / WALK_FORWARD windows.
4. Replay without look-ahead.
5. Enforce sample/ambiguity/coverage gates.
6. Evaluate untouched out-of-sample results.
7. Reach READY_FOR_REVIEW / NEEDS_MORE_DATA / REJECTED.
8. Require explicit human approval for soft promotion.
9. Never silently rewrite hard policy.

## 8. Implemented phases

### Phase 0 — deterministic advisory boundary

- Entry/SL/TP geometry.
- 15:10/15:15 intraday clock rules.
- Crash Guard and broker restriction gates.
- Advisory-only/no-order boundary.

### Phase 1 — official security identity

- Official NSE/BSE equity masters.
- Raw archive + SHA-256/parser provenance.
- ISIN-first canonical identity.
- Repeat-safe exact listing lookups.

### Phase 2 — corporate event/document memory

- NSE official corporate-announcement RSS.
- BSE announcement parser with fail-safe schema rejection.
- Exact event/security resolution.
- Filing download/dedup/text extraction.
- Persistent `what changed?` review queue.

### Phase 3 — audited historical market data + replay

- Identity-bound raw/unadjusted OHLCV.
- Source/fetch audit records.
- Validation/gap checks.
- Corporate-action comparability eras.
- 09:15-anchored derived timeframes.
- Strict completed-candle `as_of` replay.

### Phase 4 — strict outcomes + Focus Instrument Lab

- TP_FIRST / SL_FIRST / NEITHER / NOT_ENTERED / AMBIGUOUS / INSUFFICIENT_DATA.
- No intrabar order guessing.
- MAE/MFE/R/time-to-event.
- Regime/cohort/Crash Guard/level/event studies.

### Phase 5 — frozen challenger / walk-forward validation

- Frozen, SHA-256 fingerprinted experiment definitions.
- TRAIN diagnostic only.
- VALIDATION/WALK_FORWARD promotion gates.
- Future-result censoring.
- Human-only soft promotion registry.
- Regime recent-window hardening.

### Phase 6 — resident equity economics + paper ledger

- Active modes renamed to INTRADAY / SWING.
- Legacy DAY / SWING_POSITION preserved only for historical replay compatibility.
- Trader profile fixed to RESIDENT_INDIAN.
- Broker/Kite credential role separated as MARKET_DATA_ONLY.
- MTF/funded amount/financing disabled.
- Versioned resident equity cost engine.
- Brokerage, STT, exchange transaction charges, SEBI fee, IPFT, GST, stamp duty and SWING DP charges.
- Configurable adverse slippage.
- True net P&L and after-cost break-even/target solver.
- Trade Brain paper accounts and paper positions.
- Conservative full-notional virtual buying power; no hidden leverage assumption.
- INTRADAY same-session/15:15 violation tracking.
- SWING LONG own-cash accounting.
- Order execution remains OFF.

## 9. Two research profiles

### INDIAN_MARKET_MASTER

Broad Indian-equity intelligence for discovery, macro/sector/news/event context and research candidate generation.

### FOCUS_INSTRUMENT_LAB

Deep instrument-specific replay and learning, initially compatible with the BSE Ltd focus use case. Broad-market weights are not assumed to transfer; the instrument's own audited history must earn them.

## 10. Definition of a trustworthy final result

A Trade Brain result should separate:

1. **facts/evidence** with source/time;
2. **heuristic or learned estimates** with validation status;
3. **AI interpretation** as interpretation only;
4. **hard-rule status** as deterministic PASS / WAIT / BLOCK / HARD_EXIT;
5. **trade geometry** Entry / TP / SL / R:R;
6. **cost economics** gross vs resident net-after-cost;
7. **trade mode** INTRADAY or SWING only;
8. **execution boundary** advisory/paper only unless a future explicit product decision changes it.

That separation is the core product doctrine.
