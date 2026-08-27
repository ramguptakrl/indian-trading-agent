# Trade Brain v0.14 — ML Self-Training & Optimization Checkpoint

Checkpoint date: 2026-08-26

This document freezes the agreed next-stage plan for Trade Brain after completion of the BSE-only v0.13 framework and local full-history market-data bootstrap. It is intentionally stored on a dedicated checkpoint branch so the current v0.13 recovery point remains untouched.

## Repository / safety state

- Repository: `ramguptakrl/indian-trading-agent`
- Active development branch at checkpoint creation: `tradebrain/reframe-foundation`
- Active branch SHA at checkpoint creation: `2652647a1b863999d354510ad53a84fc65e3ceb0`
- Existing v0.13 recovery checkpoint remains untouched:
  - branch: `checkpoint/tradebrain-bse-framework-2026-08-25`
  - SHA: `5d8ff95c013a9091f576591dbbe9bae4439c099e`
- New planning checkpoint branch: `checkpoint/tradebrain-ml-plan-2026-08-26`
- PR #1 must remain draft/open/unmerged unless explicitly requested otherwise.
- Product remains advisory-only. No broker order placement/modification/cancellation path may be introduced as part of ML research.

## Current product doctrine carried forward

Trade target is only BSE Ltd (`NSE:BSE`, ISIN `INE118H01025`).

Independent horizons:

1. `INTRADAY_LONG`
2. `INTRADAY_SHORT`
3. `SWING_LONG_MTF`

SWING is Zerodha MTF-funded only. No F&O. No horizon substitution.

Hard deterministic safety layers remain authoritative over any model output:

- BSE identity / product scope
- point-in-time data provenance
- official exchange calendar / trading-session state
- price-range / freak-tick / halt guards
- MTF eligibility and funding validation
- transaction costs / MTF interest
- hard risk and final advisory gates
- `advisory_only = true`
- `trade_authorization = false`
- `order_execution_allowed = false`

## Local market-data milestone completed before this checkpoint

On the Windows Trade Brain machine, the full available BSE Ltd history was successfully archived from the BSE listing era through the current date using Zerodha Kite market-data-only credentials.

Intervals successfully downloaded into the local audited market-data store:

- 1 minute
- 3 minute
- 5 minute
- 10 minute
- 15 minute
- 30 minute
- 60 minute
- daily

The full-history archive command completed with all intervals reporting success.

A subsequent forced after-market V2 study completed successfully with:

- `bootstrap: false` (the first bootstrap had already completed)
- `research_warnings: []`
- latest completed multi-timeframe alignment at that moment: `BEARISH_ALIGNED`
- pattern/FVG research counts recomputed from the expanded stored history
- no broker order authority

Latest user-reported full-history research snapshot after refresh included:

- `BEARISH_ENGULFING_BODY`: 3726
- `BULLISH_ENGULFING_BODY`: 3586
- `DOJI_SHAPE`: 26739
- `HAMMER_SHAPE`: 7133
- `INSIDE_BAR`: 4099
- `SHOOTING_STAR_SHAPE`: 6978
- bullish FVG: n=2345, 16-bar fill rate 52.708%, mean size 0.46375%
- bearish FVG: n=2540, 16-bar fill rate 51.063%, mean size 0.36646%

Official NSE calendar coverage for 2026 was also loaded and verified. Zerodha Kite REST quote and historical-candle access were validated with a fresh access token. Groq and Gemini provider tests were user-confirmed successful.

## What exists today vs what v0.14 must add

The current after-market study system is an evidence-learning loop, NOT ML training. It currently refreshes audited data, computes multi-timeframe indicators/features, explores opening gaps, candlestick/FVG patterns, Fibonacci / volume-at-price proxy structure, replays already-recorded plans, and updates prospective evidence.

Current learning boundary intentionally records:

- `llm_weights_modified: false`
- `hard_rules_modified: false`
- `soft_parameters_auto_promoted: false`
- `research_evidence_updated: true`
- `human_review_required_for_promotion: true`

Trade Brain v0.14 should add a dedicated quantitative ML / strategy-optimization subsystem without changing the LLM weights or allowing an LLM to rewrite protected trading rules.

# v0.14 target architecture

```text
FULL AUDITED BSE HISTORY
1m / 3m / 5m / 10m / 15m / 30m / 60m / 1D
                |
                v
POINT-IN-TIME FEATURE + LABEL ENGINE
                |
      +---------+----------+
      |                    |
      v                    v
INTRADAY MODELS       SWING MTF MODELS
 LONG / SHORT             LONG ONLY
      |                    |
      +---------+----------+
                v
        STRATEGY / ML OPTIMIZER
                |
                v
     WALK-FORWARD / PURGED OOS TESTS
                |
                v
      COST + SLIPPAGE + REGIME STRESS
                |
                v
       CHAMPION / CHALLENGER REGISTRY
                |
                v
           SHADOW MODE
                |
                v
      PROSPECTIVE LIVE EVIDENCE
                |
                v
       TRADE BRAIN ADVISORY INPUT
```

# Build plan

## Phase ML-1 — Reproducible point-in-time dataset builder

Create a deterministic dataset builder from the audited local market store.

Requirements:

- no future bars in any feature
- completed bars only
- preserve corporate-action price eras
- no accidental crossing of split-era raw prices
- official exchange-calendar awareness
- deterministic feature calculation from stored data
- dataset snapshot hash / code version / as-of cutoff persisted
- separate train/validation/OOS time ranges
- explicit missing-data flags rather than invented values

Initial features should include, where meaningful by horizon/timeframe:

- returns and log returns
- gap % / opening gap state
- opening range
- previous-day high/low/close distances
- EMA / SMA families
- RSI
- MACD family
- ADX / DMI
- ATR / normalized ATR
- VWAP distance / reclaim / rejection features
- Bollinger position / bandwidth
- Supertrend-style deterministic features
- stochastic
- CCI
- ROC / momentum
- OBV
- MFI
- Donchian / breakout distance
- relative volume / volume expansion
- candle body/wick/range features
- candlestick shape flags
- FVG features
- Fibonacci / local structure distance
- high-/low-volume-node proxy distances
- time-of-day / minutes-from-open / minutes-to-close
- day-of-week where justified
- 1D -> derived 4H -> 1H -> 15m alignment
- audited NIFTY context-only regime features

Do not add a feature just because it exists in a TA library. Every feature needs point-in-time semantics and a documented purpose.

## Phase ML-2 — Separate label engines by horizon

Do NOT create one generic BUY/SELL label.

Create independent target definitions for:

### INTRADAY_LONG

Predict whether a long setup reaches a positive net outcome within the same session before stop/exit constraints, after resident-equity transaction costs and configured slippage assumptions.

### INTRADAY_SHORT

Predict whether a cash-equity short setup reaches a positive net outcome in the same session only. No overnight short labels. Respect the no-fresh-entry / hard-exit windows.

### SWING_LONG_MTF

Predict whether a long Zerodha-MTF-funded position reaches a positive net outcome within its allowed holding horizon after:

- resident-equity transaction costs
- MTF brokerage
- pledge/unpledge costs where applicable
- funded amount
- MTF daily interest
- holding days
- configured slippage / execution friction

Labels should include more than one target where useful:

- probability net-positive
- expected net return
- maximum favorable excursion
- maximum adverse excursion
- time-to-target / time-to-stop
- regime / session metadata

## Phase ML-3 — Baseline model family

Start with strong, interpretable tabular models before deep learning.

Required baselines:

- logistic regression
- decision tree baseline
- random forest
- Extra Trees
- histogram gradient boosting

Then evaluate optional boosted-tree libraries if added deliberately (for example XGBoost / LightGBM) rather than introducing them blindly.

Each model should support calibrated probability outputs or a documented calibration layer.

## Phase ML-4 — Strategy / hyperparameter optimizer

Add a controlled optimizer (Optuna-style or equivalent) that can search:

- indicator periods
- feature subsets
- model hyperparameters
- probability thresholds
- entry gating thresholds
- stop / target geometry
- maximum holding horizon
- regime filters
- time-of-day filters

Optimization MUST be constrained by chronological validation. It must not optimize against the final holdout.

Record every trial, including rejected trials, so the system learns what failed rather than repeatedly rediscovering the same bad configuration.

## Phase ML-5 — Anti-overfitting / chronological validation

Core rule: never train and report on the same period.

Initial frozen chronology proposal:

- 2017-2022: discovery / training
- 2023-2024: validation
- 2025: out-of-sample test
- 2026 historical period up to the freeze boundary: untouched historical holdout
- post-freeze live days: prospective evidence only

In addition, implement expanding / rolling walk-forward evaluation.

For overlapping event labels, use purging / embargo logic where needed so training examples cannot leak outcome windows into validation examples.

No random K-fold cross-validation for time-dependent trading claims.

## Phase ML-6 — Trading-quality objective function

Do not optimize for classifier accuracy alone.

Primary ranking should incorporate:

- net expectancy after modeled costs
- profit factor
- maximum drawdown
- trade count / sample size
- stability by year
- stability by market regime
- win/loss asymmetry
- worst losing streak
- calibration quality
- return on deployed cash
- SWING MTF interest burden
- sensitivity to slippage / cost stress

Stress every candidate at multiple friction assumptions, such as:

- normal modeled costs/slippage
- 1.5x execution friction
- 2.0x execution friction

Reject candidates that collapse under modest friction or rely on a tiny number of trades.

## Phase ML-7 — Champion / challenger registry

Maintain separate champion models for:

- BSE_INTRADAY_LONG
- BSE_INTRADAY_SHORT
- BSE_SWING_LONG_MTF

Every model artifact must store:

- model ID
- horizon/direction
- training range
- validation range
- OOS range
- prospective range if any
- feature list + hash
- dataset snapshot hash
- code commit/version
- hyperparameters
- target definition version
- transaction-cost version
- MTF-cost version where applicable
- train/validation/OOS metrics
- stress-test metrics
- reason promoted / rejected

A new challenger must beat the incumbent across multiple chronological windows and robustness checks, not just aggregate P&L.

## Phase ML-8 — Shadow / prospective validation

No newly trained challenger should immediately influence final advisory at full weight.

Promotion ladder:

1. research candidate
2. historical walk-forward pass
3. frozen challenger
4. shadow inference during live sessions
5. prospective evidence accumulation
6. calibration / drift review
7. eligible for human-approved advisory integration

Even after promotion, deterministic safety gates outrank model output.

## Phase ML-9 — Self-training schedule

During market hours:

- inference only
- no heavy training
- no optimizer loops
- no protected-rule mutation

After market:

- refresh new audited bars
- mature labels whose outcome windows have completed
- score yesterday's predictions
- update calibration / drift metrics
- train lightweight challengers when scheduled

Periodic deeper research:

- run full strategy / hyperparameter competitions weekly or on a deliberately chosen cadence
- run heavier full-history re-evaluation less frequently
- trigger additional re-evaluation when drift thresholds are breached

## Phase ML-10 — ML evidence into Trade Brain agents

ML should produce structured evidence, for example:

```json
{
  "model_id": "BSE_INTRADAY_LONG_0042",
  "horizon": "INTRADAY",
  "direction": "LONG",
  "probability_net_positive": 0.73,
  "expected_net_return_pct": 0.64,
  "expected_adverse_excursion_pct": -0.27,
  "oos_profit_factor": 1.71,
  "regime": "TREND_UP_MODERATE_VOL",
  "calibration_status": "PASS",
  "model_status": "CHAMPION"
}
```

LLM agents may consume this as another evidence source. The LLM remains a research/synthesis layer; it does not become the ML trainer and does not get broker authority.

Final ordering stays conceptually:

```text
HALT / DATA INTEGRITY / PRICE RANGE / SESSION
        >
BROKER / MTF FUNDING PERMISSION
        >
HARD RISK
        >
ML + TECHNICAL + RESEARCH EVIDENCE
        >
LLM SYNTHESIS
        >
FINAL ADVISORY GATE
```

## Phase ML-11 — Drift monitoring

Track at minimum:

- feature drift
- probability calibration drift
- realized vs predicted expectancy
- win-rate drift
- regime-dependent degradation
- drawdown / loss-streak deviations

Drift may trigger challenger training or reduced model confidence, but it must not automatically weaken protected risk rules.

## Phase ML-12 — Tests / CI / operational safety

Add tests for:

- point-in-time feature leakage
- label leakage
- split-era safety
- session-boundary safety
- intraday no-overnight-short rule
- 15:10 no-fresh-entry / 15:15 hard-exit semantics
- SWING MTF cost inclusion
- deterministic dataset hashes
- chronological split correctness
- purging/embargo correctness
- reproducible model training with fixed seeds where supported
- artifact registry versioning
- champion/challenger promotion criteria
- fail-closed behavior if model artifact or feature schema is stale/incompatible
- no order API capability anywhere in ML code

CI should keep the existing Trade Brain foundation tests green and add dedicated `test_tradebrain_ml_*` coverage.

# Model choice philosophy

Do not start with LSTM / Transformer / reinforcement-learning trading agents.

Reason: one stock with roughly a decade of data can produce convincing but fragile deep-learning backtests. First establish a robust baseline with deterministic features + tree/boosting models + strict chronological OOS testing. Deep sequence models may be added only as challengers later, and only if they beat the simpler champion out of sample and under cost/slippage stress.

# Definition of "self-training" for this project

Self-training means:

- automatically ingest new audited BSE evidence
- mature new labels
- evaluate previous predictions against realized net outcomes
- train new challenger models
- optimize approved parameter spaces
- reject overfit / unstable candidates
- maintain a versioned champion/challenger registry
- monitor drift and calibration
- accumulate prospective live evidence

It does NOT mean:

- silently changing protected risk rules
- fine-tuning Groq/Gemini weights
- allowing an LLM to rewrite live trading policy
- promoting a model based only on in-sample P&L
- placing broker orders

# Immediate implementation order

1. Add ML dependencies deliberately and minimally.
2. Build the point-in-time feature engine.
3. Build horizon-specific net-outcome label engines.
4. Build leakage tests before any optimizer.
5. Build chronological / walk-forward evaluation harness.
6. Train simple baseline models.
7. Add model registry / artifact metadata.
8. Add optimizer and robustness scoring.
9. Add champion/challenger lifecycle.
10. Add after-market retraining supervisor integration.
11. Add shadow-mode inference to dual-horizon analysis.
12. Only after prospective evidence, consider human-approved promotion into advisory weighting.

# Checkpoint intent

This checkpoint exists so future work can resume from a precise agreed plan even if chat context is lost. The existing v0.13 framework checkpoint remains the recovery anchor. v0.14 ML work should proceed from the active Trade Brain branch without modifying or deleting the prior checkpoint.
