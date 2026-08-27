# BSE ML Hardening Evidence — 2026-08-27

## Scope

This note records empirical ML hardening evidence from the audited Zerodha Kite BSE Ltd
historical database supplied for Trade Brain research. It is a research checkpoint, not a
trading recommendation and not a broker authorization.

The experiment preserved the v0.14 task separation:

- `BSE_INTRADAY_LONG`
- `BSE_INTRADAY_SHORT`
- `BSE_SWING_LONG_MTF`

All experiments remained advisory/research only. No broker order path was enabled.

## Evidence hygiene

- Point-in-time features and matured labels were used.
- New compact/weighted intraday variants competed against the prior full-feature control on
  VALIDATION first.
- Only a validation winner was allowed a new OOS evaluation.
- The 2026 historical holdout had already been inspected in an earlier research step and is
  therefore treated as **consumed evidence**, not an untouched tuning set.
- The experiments in this note did **not** use 2026 to select or tune configurations.
- Future prospective shadow sessions remain the clean final proof layer.

## Audited data used

The uploaded Kite SQLite archive contained the canonical BSE Ltd market-data series with
approximately 1.55 million finalized candles across the supported intervals. Relevant inputs
for these tests included:

- 15-minute: 58,927 raw feature bars before label-resolution filtering
- Daily: full 2017–2026 BSE history used by the swing label engine

The label engine continued to exclude ambiguous same-bar target/stop outcomes rather than
inventing intrabar ordering.

---

## Intraday Long — compact + friction/uniqueness challenger

### Prior full-feature validation control

- Family: Extra Trees
- Threshold: 0.55
- Validation selected trades: 90
- Validation mean net return: 0.46099%
- Validation profit factor: 1.9403
- Validation 2×-friction mean net return: 0.27451%
- Validation 2×-friction profit factor: 1.4912
- Validation robustness score: 0.48497
- Prior 2025 OOS result: rejected

### New validation winner

Compact point-in-time feature schema after correlation pruning:

- `mtf_alignment_score`
- `mtf_daily_trend`
- `mtf_1h_trend`
- `relative_volume_20`
- `natr_14_pct`
- `vwap_distance_pct`
- `opening_range_position`
- `distance_prev_high_pct`
- `distance_prev_low_pct`
- `gap_pct`
- `adx_14`
- `dmi_spread`
- `rsi_14`
- `macd_hist`

`mtf_4h_trend` was removed by the correlation-pruning rule in this realized dataset. No
historical order-flow imbalance was invented because the audited archive is OHLCV rather than
historical level-2/order-book data.

Winning research variant:

- Variant: compact + friction/temporal-uniqueness sample weighting
- Family: Histogram Gradient Boosting
- Hyperparameters: learning_rate=0.05, max_iter=140, max_leaf_nodes=15,
  l2_regularization=1.0
- Threshold: 0.65
- Validation selected trades: 20
- Validation mean net return: 0.70371%
- Validation profit factor: 2.1196
- Validation 2×-friction mean net return: 0.52617%
- Validation 2×-friction profit factor: 1.7543
- Validation robustness score: 0.62905

The compact weighted challenger therefore beat the old full-feature control on validation and
was allowed the single new OOS opening.

### Frozen 2025 OOS verdict

- OOS selected trades: **23**
- OOS mean net return: 0.13251%
- OOS profit factor: 1.2890
- OOS max drawdown: 4.13%
- OOS 2×-friction mean net return: **-0.02950%**
- OOS 2×-friction profit factor: **0.9441**
- OOS 2× high-vol expectancy: -0.22221%
- OOS 2× trend-up expectancy: -0.09550%

**Verdict: REJECT.**

The new weighting hypothesis improved validation but did not survive 2025 cost stress. It also
falls far short of the hardened >=100 OOS-trade promotion threshold.

---

## Intraday Short — compact challengers

The same compact schema was tested with both:

1. compact unweighted training, and
2. compact friction/temporal-uniqueness weighted training.

Neither produced a validation candidate that survived the existing minimum expectancy,
profit-factor, and 1.5×/2× friction robustness tests.

No new OOS configuration was opened for Intraday Short.

**Verdict: REJECT / NO ROBUST VALIDATION CANDIDATE.**

This is evidence against the current label/model hypothesis; it is not proof that BSE can
never have an intraday-short edge.

---

## Swing Long MTF — hardened gate

Existing frozen research configuration:

- Feature family: structure-only search winner
- Model: Decision Tree
- max_depth=7
- min_samples_leaf=12
- Threshold: 0.65

2025 OOS evidence from the prior run:

- OOS selected trades: 136
- OOS mean net return: 0.62172%
- OOS profit factor: **1.2274**
- OOS max drawdown: **62.80%**
- OOS 2×-friction mean net return: 0.08541%
- OOS 2×-friction profit factor: **1.0283**
- OOS 2×-friction max drawdown: **71.16%**
- OOS RANGE expectancy: -1.25955%
- OOS 2× RANGE expectancy: -1.77973%

Under the hardened promotion gate this candidate fails at least:

- max OOS drawdown <=25%
- OOS 2× profit factor >=1.30
- positive expectancy in every observed regime

The >=100 OOS trade-count rule is satisfied, but that is not enough.

**Hardened promotion verdict: REJECT.**

### Purged / embargoed CPCV diagnostic

The exact frozen Swing configuration was then evaluated on pre-2026 history using the new
secondary CPCV robustness standard:

- groups: 6
- held-out groups per fold: 2
- theoretical/usable folds: 15 / 15
- label-window overlap purging: enabled
- post-test embargo: enabled
- fixed family/params/features/threshold: yes
- CPCV used for hyperparameter selection: no
- per-fold strict rule: >=20 selected trades, positive expectancy at 2× friction, PF >=1.30

Observed result:

- strict passing folds: **1 / 15**
- strict pass fraction: **6.67%**
- catastrophic folds: **14 / 15**

The required standard is >=80% strict-pass folds with zero catastrophic folds.

**CPCV verdict: REJECT.**

CPCV remains secondary evidence because combinatorial folds may train on later historical
blocks relative to a held-out block. Causal walk-forward and prequential historical replay
remain mandatory for claims about what the model could have known at the time.

---

## Current model decision

As of this research checkpoint:

| Task | Current verdict | Promotion status |
| --- | --- | --- |
| Intraday Long | Compact weighted challenger failed frozen OOS | Reject |
| Intraday Short | No compact validation candidate | Reject |
| Swing Long MTF | Hard gate + CPCV fail | Reject |

There is **no justified ML champion** from these three task configurations.

The correct behavior is to keep Trade Brain fail-closed rather than weaken thresholds to force
a winner.

## Next research boundary

Further work may explore new frozen hypotheses, but it must not tune against the consumed 2026
historical evidence. Candidate changes should be selected on historical research/validation,
then subjected to the same cost, CPCV, causal replay, and promotion gates. Any model that
survives historical review must still complete at least 30 continuous verified live-shadow
market sessions with the exact same artifact and zero retunes before integration eligibility.

Broker execution remains disabled throughout.
