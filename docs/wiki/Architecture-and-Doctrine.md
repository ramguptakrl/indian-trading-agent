# Architecture and Product Doctrine

## Canonical instrument

Trade Brain is intentionally single-instrument:

- Exchange symbol: `NSE:BSE`
- ISIN: `INE118H01025`
- Company: BSE Ltd

Any generic inherited multi-stock behavior is legacy compatibility, not product doctrine.

## Trading modes

### Intraday

- LONG and SHORT research/advisory are allowed.
- Same-session only.
- No fresh entry after 15:10 IST.
- Position must be flat before 15:15 IST.
- Overnight intraday short is forbidden.

### Swing

- LONG-only.
- Active funding doctrine: Zerodha MTF.
- MTF eligibility and costs must be modeled/verified.
- No F&O.

## Broker boundary

Kite is used for market data only.

Allowed:

- historical candles;
- live quotes;
- market-data backtest/replay inputs.

Forbidden:

- order placement;
- broker execution authority;
- inferring product doctrine from the credential account type.

Every advisory/research artifact must preserve:

```text
advisory_only = true
trade_authorization = false
order_execution_allowed = false
```

## Evidence hierarchy

Preferred decision evidence hierarchy:

1. 1D
2. derived 4H
3. 1H
4. 15m

Lower timeframes may support intraday structure but do not override higher-level hard risk/evidence gates.

Critical missing, stale, conflicting, or unverifiable evidence fails closed.

## Deterministic rules outrank ML

ML may provide advisory evidence but may not override:

- canonical BSE identity;
- point-in-time provenance;
- official exchange calendar/session rules;
- freak-tick and halt guards;
- MTF eligibility/funding rules;
- cost/interest accounting;
- hard risk gates;
- final advisory authorization boundary;
- broker execution prohibition.

## Market-data doctrine

### Primary / audited

Kite historical data is the intended audited finalized OHLCV source for ML research.

### Live

- Kite WebSocket live quote stream.
- Kite REST quote support.

### Fallback / research-only

Yahoo/yfinance may be used for clearly labeled fallback or descriptive research where appropriate, but must not silently substitute for an experiment that specifically claims audited Kite provenance.

## Schedule doctrine

### During market session

- advisory generation;
- live monitoring;
- data collection;
- lightweight state updates.

### After market

- study/replay;
- heavy research;
- supervised model training;
- challenger evaluation;
- drift review.

Heavy training should not run merely because the market is open.

## ML architecture

Conceptual pipeline:

```text
FULL AUDITED BSE HISTORY
        ↓
POINT-IN-TIME FEATURES + LABELS
        ↓
TASK-SPECIFIC LONG / SHORT / SWING DATASETS
        ↓
CONTROLLED ML OPTIMIZER
        ↓
CHRONOLOGICAL / PURGED VALIDATION
        ↓
COST + SLIPPAGE + REGIME STRESS
        ↓
MULTIPLE-TESTING CONTROLS
        ↓
BOOTSTRAP CONFIDENCE
        ↓
REGISTRY: CHALLENGER / HISTORICAL PASS
        ↓
HUMAN REVIEW
        ↓
SHADOW / PROSPECTIVE EVIDENCE
        ↓
OPTIONAL ADVISORY INPUT
```

There is no automatic champion promotion.

## Current supervised tasks

- `BSE_INTRADAY_LONG`
- `BSE_INTRADAY_SHORT`
- `BSE_SWING_LONG_MTF`

## Existing model families

- Logistic Regression
- Decision Tree
- Random Forest
- Extra Trees
- Histogram Gradient Boosting

These are estimator families. They are not equivalent to distinct trading hypotheses.

## Cost doctrine

Research conclusions must be net of modeled resident Indian equity costs appropriate to the active mode and, for swing, MTF financing/pledge effects where applicable.

Stress evaluation includes higher-friction scenarios. A candidate that only works under unrealistically cheap execution is not robust.

## Promotion philosophy

Historical success is only one stage. A candidate should require, at minimum:

- chronology integrity;
- validation selection discipline;
- OOS pass;
- stress survival;
- multiple-testing clearance;
- confidence-interval clearance;
- purged/CPCV robustness;
- registry integrity;
- human review;
- prospective/shadow evidence before meaningful advisory influence.

No backtest result grants broker authority.
