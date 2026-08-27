# ML Research Plan

## Research objective

Find whether BSE Ltd contains a robust, repeatable net-of-cost edge for:

1. intraday LONG,
2. intraday SHORT,
3. swing LONG using MTF,

without contaminating holdout evidence or accepting a result merely because enough variants were tried.

## Frozen chronology

Default windows:

- TRAIN: 2017-01-01 → 2023-01-01
- VALIDATION: 2023-01-01 → 2025-01-01
- OOS: 2025-01-01 → 2026-01-01
- HOLDOUT: 2026-01-01 → 2026-08-22
- Embargo: 1 day

Feature timestamps and label-end timestamps must both respect split boundaries.

## Baseline supervised pipeline

The baseline optimizer searches controlled combinations of:

- model family;
- predeclared feature subset;
- model parameters;
- probability threshold.

Selection happens on discovery evidence, not holdout.

Existing estimator families:

- Logistic Regression
- Decision Tree
- Random Forest
- Extra Trees
- Histogram Gradient Boosting

## Mandatory anti-overfitting controls

### Persistent trial ledger

Every distinct research candidate must remain counted even if rejected and even if the process restarts later.

Repeated execution of the exact same candidate is deduplicated rather than counted as a new independent idea.

### Deflated Sharpe Ratio

DSR is used to penalize apparent Sharpe for the number/distribution of trials and non-normal return characteristics.

A raw attractive Sharpe is not enough if deflation indicates likely selection luck.

### Probability of Backtest Overfitting

PBO evaluates the selection process across purged/combinatorial folds. The candidate set must be fixed before each fold ranking; a strategy may not be preselected using the full discovery period and then presented as if fold selection were independent.

### Stationary-bootstrap confidence intervals

Promotion evidence should include 95% uncertainty under 2× friction.

Required direction of evidence:

- Profit Factor 95% lower bound > 1.0;
- expectancy 95% lower bound > 0;
- drawdown uncertainty remains within the approved risk ceiling.

Point estimates alone are insufficient.

### CPCV / purged robustness

Temporal overlap and label leakage must be removed around validation boundaries. Random K-fold validation is not acceptable for this project.

## Research kill criteria

### Per-hypothesis-family trial budget

The intended budget is 50 distinct configurations **inside one hypothesis family**.

If that family reaches the budget without a DSR-valid candidate, further parameter mining in the same family stops pending explicit research review.

A scientifically different predeclared hypothesis starts a separate family; the entire BSE task is not declared impossible because one hypothesis failed.

### Minimum Track Record Length

If the candidate's estimated Sharpe would require more than approximately five years of realistic trade frequency to establish the desired confidence, it is considered impractical for promotion research.

### Friction viability

If the candidate cannot reach Profit Factor > 1.0 at normal modeled friction, further complexity is not justified merely to rescue the backtest.

## Structural-break experiment

External hypothesis date: **15 May 2023**, based on the BSE equity-derivatives relaunch.

The date is predeclared from an external business event and must not move to maximize OOS performance.

Three research variants:

1. `FULL_HISTORY_CONTROL`
2. `PRE_2023_DOWNWEIGHTED`
3. `POST_2023_ONLY`

Purpose: test whether older market microstructure hurts modern predictive robustness while keeping full history available as a control/stress regime.

The experiment does **not** assume the business event is a proven causal statistical break.

## Meta-label research

Rather than asking ML to predict every candle, test whether ML works better as a secondary filter on deterministic structural setups.

### Hypothesis A — Trend / Momentum

Primary generator uses directional moving-average structure, VWAP location, DMI/ADX, and relative-volume confirmation.

### Hypothesis B — Mean Reversion

Primary generator uses Bollinger exhaustion, RSI extreme, VWAP displacement, and subdued/decaying volume.

### Hypothesis C — Volatility Breakout

Primary generator uses prior compression/inside-bar context, current range expansion, relative-volume confirmation, and deterministic direction.

For all three:

- primary signal existence must not use labels;
- primary signal direction is deterministic;
- ML is an accept/reject filter;
- changing primary thresholds is a new research candidate and spends statistical budget.

## Sequence/context research

Do not jump to neural sequence models on a single-stock dataset.

Current challenger remains tabular and causal:

- lag 1 / 3 / 5 contextual state;
- Garman–Klass volatility;
- Parkinson volatility;
- close-location value;
- VWAP displacement normalized by ATR;
- range/ATR interaction;
- relative-volume × range interaction;
- directional efficiency windows.

Only consider LSTM/Transformer-style sequence models if the project later demonstrates a sufficiently large set of independent/non-overlapping trade setups and the simpler models have been fairly exhausted.

## Alternative-bar research — planned, not complete

Planned challenger:

- construct volume bars and/or rupee-value/activity bars from audited 1-minute BSE OHLCV;
- preserve exact source-minute provenance;
- evaluate only as a separate hypothesis family;
- never claim reconstruction of true intra-minute trade ordering, spread bounce, queue position, or bid/ask path.

Synthetic bars derived from 1-minute OHLCV are approximations of aggregation, not recovered tick history.

## Synthetic augmentation policy

Do not manufacture independent-looking financial observations.

Potentially acceptable only as stress/research tooling:

- block bootstrap;
- volatility scaling.

Forbidden for ordinary training evidence:

- random candle shuffling;
- independent Open/Close perturbation;
- invented volume;
- arbitrary synthetic price paths presented as market history.

## Cross-asset context — planned cautiously

Potential contextual series:

- NIFTY 50;
- INDIA VIX;
- NIFTY Financial Services / appropriate broad financial-sector context.

These should be added only with point-in-time, auditable historical provenance. Arbitrary individual equities should not be added merely to increase feature count.

## Drift and retraining

Artifact baselines include discovery-period PSI distributions. Active model monitoring may use:

- feature-distribution drift;
- PSI;
- calibration/Brier deterioration;
- shadow performance deterioration.

An active frozen model should not be retrained simply because a calendar week passed. Drift may recommend a separate challenger; it does not mutate the active model in place.

## Promotion ladder

Research result → registered challenger → historical-pass evidence → human review → frozen/shadow stage → prospective evidence → possible advisory contribution.

No automatic champion promotion and no broker order authority.
