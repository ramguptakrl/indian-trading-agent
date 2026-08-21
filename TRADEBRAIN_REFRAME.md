# Trade Brain Reframe for `indian-trading-agent`

Status: **core framework Phases 0–10 implemented on the Trade Brain reframe branch**  
Current Trade Brain version: **0.11.0**

This is the canonical product architecture. Historical chat/checkpoint details are not product doctrine.

## 1. Product identity

Trade Brain is a **resident-Indian equity research, replay, validation and paper-accounting system** built on top of the existing Indian Trading Agent repository.

The upstream LangGraph research pipeline, FastAPI/Next.js shell, scanners, regime analysis, simulation, calibration, memory and UI remain useful. Trade Brain adds the evidence/control plane required to stop research output from becoming unverified trade permission.

LLMs are research/synthesis components. They are not the source of truth for security identity, exchange sessions, market prices, broker permission, costs, hard risk constraints or execution.

## 2. Active trade modes

Only two active user-facing modes exist.

### INTRADAY

- Resident cash-equity intraday.
- LONG or SHORT.
- Same cash-market session only.
- Explicit Entry / Stop-Loss / Take-Profit required.
- No fresh entry from **15:10 IST**.
- Must be flat before **15:15 IST**.
- Minimum R:R is a soft, versioned, challengeable preference.

### SWING

- Resident multi-day cash/delivery equity.
- LONG only.
- Own-cash funding only.
- Explicit Entry / Stop-Loss / Take-Profit required.
- Minimum R:R is a soft, versioned, challengeable preference.

There is **no MTF mode**, no funded-amount model, no pledge-financing logic and no financing-interest engine. Derivatives and overnight shorting are outside the active product.

Historical rows may contain compatibility labels only:

```text
DAY             -> INTRADAY
SWING_POSITION  -> SWING
```

## 3. Trader identity vs data credential identity

Modeled trader:

```text
RESIDENT_INDIAN
```

A Zerodha/Kite credential may belong to an NRI account and still be used strictly as:

```text
MARKET_DATA_ONLY
```

Allowed data uses:

- instrument master;
- live quotes;
- historical candles;
- replay/backtest inputs.

Credential account type must not import NRI restrictions, brokerage, PIS/Non-PIS rules, TDS/tax treatment or order permissions into resident policy/economics.

No Kite order route exists in the Trade Brain adapter.

## 4. Final architecture

```text
OFFICIAL / REFERENCE DATA                 MARKET DATA
NSE/BSE filings, identity, calendar        audited Yahoo + optional Kite data-only
              |                                      |
              +------------------+-------------------+
                                 |
                    IDENTITY + PROVENANCE + MEMORY
                                 |
                        MULTI-AGENT RESEARCH
                                 |
                      STRICT STRUCTURED PARSE
                                 |
                     AUDITED HISTORY / REPLAY
                                 |
                       STRICT OUTCOME ENGINE
                                 |
                      FOCUS INSTRUMENT LAB
                                 |
               FROZEN CHALLENGER / WALK-FORWARD
                                 |
                 HUMAN-APPROVED SOFT REGISTRY
                                 |
                  VERIFIED SESSION / CALENDAR
                                 |
                   EXPLICIT CRASH GUARD STATE
                                 |
                 EXPLICIT BROKER/RULE PERMISSION
                                 |
                 DETERMINISTIC HARD-RULE GATE
                                 |
                 RESIDENT EQUITY COST SCENARIOS
                                 |
                    INTRADAY / SWING ADVISORY
                                 |
                   NET-COST PAPER ACCOUNTING
                                 |
                 TRADE AUTHORIZATION = FALSE
                    ORDER EXECUTION = OFF
```

## 5. Source-of-truth hierarchy

### Security identity

Official exchange security masters with ISIN-first mapping:

```text
Issuer -> Canonical Security (ISIN) -> NSE/BSE Listing
```

No fuzzy cross-exchange merge.

### Corporate events

Prefer official exchange/regulator/company filings. News/social sources may provide leads but cannot silently replace official facts.

### Exchange calendar

Official exchange evidence. NSE cash holidays can be collected from the official holiday-master feed. BSE is not silently assumed to share NSE's calendar. Special sessions require verified timings before new-INTRADAY use.

### Market prices

Source/provider/timestamps/quality are retained. Yahoo/yfinance is explicitly NON-OFFICIAL. Kite Connect is a broker market-data vendor adapter with `MARKET_DATA_ONLY` semantics.

### Broker costs

Versioned, verified **resident individual** equity charge profiles. Data-credential account type does not choose the cost model.

### AI

Interpretation, hypothesis generation, synthesis, debate and explanation only.

## 6. Hard rules above AI and learning

Current protected boundaries include:

- advisory only;
- trade authorization false;
- order execution OFF;
- active modes only INTRADAY and SWING;
- explicit Entry / SL / TP geometry;
- INTRADAY no new entry from 15:10 IST;
- INTRADAY flat before 15:15 IST;
- SWING LONG cash/delivery only;
- MTF disabled;
- verified broker/exchange restriction outranks model opinion;
- Severe Crash Guard blocks fresh LONG exposure;
- crash/risk context does not automatically create a SHORT;
- final validation does not assume unknown Crash Guard or broker permission;
- raw agent BUY/SELL prose is not trade permission.

## 7. Soft learning governance

Current runtime-learnable examples include:

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

1. Define incumbent and challenger.
2. Freeze hypothesis + TRAIN / VALIDATION / WALK_FORWARD windows.
3. Replay without look-ahead.
4. Enforce sample/ambiguity/coverage gates.
5. Evaluate untouched out-of-sample evidence.
6. Reach READY_FOR_REVIEW / NEEDS_MORE_DATA / REJECTED.
7. Require explicit human approval.
8. Activate only a versioned soft-registry value.
9. Runtime uses the value with key/version/provenance exposed.
10. Missing/malformed/ambiguous registry state falls back to default.
11. Hard rules are never read from the soft registry.

## 8. Implemented phases

### Phase 0 — deterministic advisory boundary

Structured geometry, Crash Guard/broker gates, 15:10/15:15 hard clock and execution-disabled stance.

### Phase 1 — official security identity

Official NSE/BSE equity masters, raw archive/provenance, ISIN-first canonical identity and exact lookups.

### Phase 2 — corporate event/document memory

Official NSE announcement ingestion, fail-safe BSE parser, exact event identity, filing dedup/text extraction and persistent change-review queue.

### Phase 3 — audited market history/replay

Identity-bound RAW_UNADJUSTED OHLCV, source/fetch audit, validation, comparable-price eras, derived timeframes and completed-candle replay.

### Phase 4 — strict outcomes + Focus Instrument Lab

TP_FIRST / SL_FIRST / NEITHER / NOT_ENTERED / AMBIGUOUS / INSUFFICIENT_DATA, MAE/MFE/R/time-to-event, cohorts, levels, Crash Guard and event studies.

### Phase 5 — frozen challenger validation

SHA-256-frozen experiments, out-of-sample/walk-forward gates, future-result censoring, human-only soft promotion and regime-window hardening.

### Phase 6 — resident economics + paper ledger

INTRADAY/SWING active names, no MTF, resident versioned transaction costs, net target/break-even calculations and conservative full-notional paper accounts/positions.

### Phase 7 — reviewed soft runtime

Human-approved ACTIVE R:R versions can alter soft PASS/WAIT preference with provenance. Defaults remain fail-safe fallback. No hard policy mutation.

### Phase 8 — verified exchange calendar

Official NSE cash-calendar collector, persistent coverage, explicit holidays, special-session pending/override state and fail-closed scheduler option. BSE calendar evidence remains separate.

### Phase 9 — Kite market-data-only adapter

Instrument master, quotes and historical candles only. Historical data enters the same audited Phase-3 replay store. No order/place/modify/cancel methods.

### Phase 10 — fail-closed final advisory pipeline

The old LLM BUY/SELL signal extractor is removed. Safe research labels are:

- LONG_CANDIDATE
- SHORT_CANDIDATE
- EXIT_CANDIDATE
- WAIT
- NO_TRADE

The final pipeline parses only labelled fields and requires verified calendar, explicit Crash Guard, explicit broker/exchange permission and deterministic policy. When quantity exists, it attaches resident target/stop transaction-cost scenarios. Every result retains `trade_authorization=false` and `order_execution_allowed=false`.

Historical date-only analysis does not invent a decision timestamp; it remains historical research rather than a fake live gate.

## 9. Research profiles

### INDIAN_MARKET_MASTER

Broad Indian-equity discovery and macro/sector/news/event research.

### FOCUS_INSTRUMENT_LAB

Deep instrument-specific replay/learning, initially compatible with the BSE Ltd focus use case. Broad-market assumptions do not transfer automatically.

## 10. Definition of a trustworthy result

A Trade Brain result separates:

1. facts/evidence with source/time;
2. AI research candidate and parser status;
3. heuristic/learned estimates with validation/provenance;
4. verified exchange calendar/session state;
5. explicit Crash Guard and broker/rule state;
6. deterministic PASS / WAIT / BLOCK / HARD_EXIT;
7. Entry / TP / SL / gross R:R;
8. resident transaction-cost scenarios and net R:R when quantity is supplied;
9. trade mode INTRADAY or SWING only;
10. execution boundary: advisory/paper only, no order authorization.

## 11. Core-framework completion boundary

At v0.11.0 the planned control-plane framework is constructed. Remaining work is deployment/evidence/configuration rather than an implicit execution phase:

- refresh official security/event/calendar sources in the deployed runtime;
- load verified BSE calendar/special-session evidence as available;
- optionally configure Kite market-data credentials;
- accumulate real replay/paper/outcome samples;
- validate/promote soft challengers only when samples justify it;
- separately decide whether/when this draft PR should merge into `main`.

There is no automatic-order phase on the roadmap unless the product decision is explicitly changed later.
