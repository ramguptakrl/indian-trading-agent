# Current Status

_Last handoff status update:_

- **Toronto / Eastern Time:** 2026-08-26 21:26:54 EDT (UTC-04:00)
- **India Standard Time:** 2026-08-27 06:56:54 IST (UTC+05:30)
- **UTC:** 2026-08-27 01:26:54 UTC

For the exact cross-chat resume point, read [Session Handoff](Session-Handoff).

## Active development state

- Branch: `tradebrain/reframe-foundation`
- Branch head at handoff-capture start: `23a1ba16d21dac5dbb5d0aab530e850e543f9469`
- Latest research-code commit before Wiki-only handoff/documentation commits: `a33c6769e0e7fb664f0337e65260004c71414282`
- Pull request: PR #1 remains open/unmerged unless explicitly approved for merge.
- Last fully certified statistical-governance boundary: `5700f2e8282583ef7f9acb87a5641a4ccf23d379`
- That certified boundary passed the frontend contract, full Trade Brain unit suite, observational smoke phases, and evidence-baseline build/upload.
- Newer research modules and handoff/Wiki commits are **not** automatically green merely because that older boundary passed.

## Certified statistical-governance layer

Implemented and certified at the last green boundary:

- Persistent research-trial ledger.
- Exact-candidate deduplication across repeated research runs.
- Deflated Sharpe Ratio (DSR) using cumulative research history.
- Probability of Backtest Overfitting (PBO) using a fixed candidate set across purged folds.
- Stationary-bootstrap uncertainty estimates.
- 2× friction confidence gates for Profit Factor, expectancy, and drawdown uncertainty.
- CPCV/purged robustness evidence.
- PSI discovery baselines embedded with model artifacts.
- Live/replay PSI drift contribution.
- Registry fail-closed promotion requirements.
- No automatic freeze, shadow enablement, advisory integration, champion promotion, or execution.

## Newer research code — implemented, exact-head certification required

The following research layers were added after the last fully certified boundary and therefore must not be described as green until their newest exact head passes CI:

### Research kill governance

- Per-hypothesis-family candidate budget.
- Intended semantics: up to 50 distinct parameter/configuration candidates inside one hypothesis family before further parameter mining is halted when no DSR-valid edge has emerged.
- A killed hypothesis family does **not** kill the entire BSE task; a genuinely different, predeclared scientific hypothesis is a separate family.
- Minimum Track Record Length (MinTRL) logic was added to flag edges that would require impractically long live evidence.
- Baseline Profit Factor ≤ 1.0 is treated as evidence that friction may be insurmountable for the candidate.

### Structural-break challenger

Predeclared external hypothesis boundary: 15 May 2023, corresponding to the BSE equity-derivatives relaunch.

Three research arms:

1. `FULL_HISTORY_CONTROL`
2. `PRE_2023_DOWNWEIGHTED`
3. `POST_2023_ONLY`

The date is not optimized against OOS/holdout performance. Old data is retained as control/stress evidence rather than silently deleted.

### Meta-labeling challenger

Three deterministic primary hypothesis families:

1. Trend / momentum.
2. Mean reversion.
3. Volatility breakout.

The deterministic primary generator chooses the setup/direction. ML is a secondary accept/reject filter on the already-defined setup. Labels or future outcomes may not decide whether a primary signal existed.

### Causal sequence/context challenger

Tabular lagged features were added instead of jumping to LSTM/Transformer architectures:

- lag 1 / 3 / 5 state for selected returns, volatility, volume, VWAP, DMI/ADX, RSI and MACD context;
- session-boundary lag resets;
- Garman–Klass volatility;
- Parkinson volatility;
- close-location value;
- VWAP distance in ATR units;
- range/ATR ratio;
- relative-volume × range interaction;
- 5/10/20-bar directional efficiency.

No Level-2/order-book information is claimed and no synthetic candles are created by this module.

## Existing ML task set

1. `BSE_INTRADAY_LONG`
2. `BSE_INTRADAY_SHORT`
3. `BSE_SWING_LONG_MTF`

The existing supervised model families are conventional tabular estimators, not five trading strategies:

- Logistic Regression
- Decision Tree
- Random Forest
- Extra Trees
- Histogram Gradient Boosting

## Current empirical research verdict

There is **no approved champion**.

- Intraday Long: rejected under hardened evidence.
- Intraday Short: rejected under hardened evidence.
- Swing Long MTF: rejected for promotion after the stronger drawdown/friction/regime/CPCV checks.
- The 2026 historical holdout has already been opened once and is consumed. It is no longer an untouched selection resource.
- Future prospective market sessions are the cleanest new evidence.

## Chronology contract

Current default chronology:

- TRAIN: 2017-01-01 → 2023-01-01
- VALIDATION: 2023-01-01 → 2025-01-01
- OOS: 2025-01-01 → 2026-01-01
- HOLDOUT: 2026-01-01 → 2026-08-22
- Embargo: 1 day

Holdout is not an optimization resource.

## Valid optimizer research outcomes

- `OOS_PASS`
- `OOS_REJECTED`
- `NO_ROBUST_CANDIDATE`
- `INSUFFICIENT_DATA`
- `INSUFFICIENT_CHRONOLOGY`

`NO_ROBUST_CANDIDATE` is a legitimate research result, not a software failure.

## Immediate next action

**Run exact-head CI/test certification for the newest combined research modules before adding further model hypotheses.**

After that, continue from `Session-Handoff` / `Roadmap-and-Next-Steps`.

## Production/training claim boundary

The optimizer software and statistical safeguards can be complete while no production champion exists. Do not claim that a trained champion has been verified until a real audited local Kite dataset has been run through the current exact code and its run artifacts, trial counts, chronology, stress evidence, registry stage, and hashes have been inspected.

## Known whole-project caveats outside the ML core

Items that remain relevant before calling the entire application production-ready include:

- LLM runaway/billing guard integration into every paid provider path.
- Removal or isolation of stale generic multi-stock memory behavior.
- Remaining generic ticker/data-source escape paths.
- Generic Bull/Bear/Risk prompts that still need BSE-specific cleanup where applicable.
- News lookback/provenance hardening where undated/global data can contaminate replay.
- Stale documentation and UI/provider configuration mismatches.
- Scheduled dependency-refresh mutation risk.

These are separate from the ML optimizer’s statistical research status.
