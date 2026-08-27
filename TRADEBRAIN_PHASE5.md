# Trade Brain Phase 5 — Frozen Challenger / Walk-Forward Validation

Status: implemented in Trade Brain v0.6.0.

Phase 5 converts Phase-4 historical outcome evidence into an auditable challenger process. It deliberately does **not** perform unconstrained parameter search, rewrite hard rules, enable execution, or claim that historical performance predicts future returns.

## 1. V1 supported challenger family

Phase 5 V1 supports only two explicit soft parameters:

- `day_min_reward_risk`
- `swing_min_reward_risk`

These operate as historical candidate filters over Phase-4 replay outcomes. Unknown parameters are rejected instead of being silently treated as optimizable.

Protected safety/execution controls cannot enter the challenger pipeline, including examples such as:

- `advisory_only`
- `order_execution_enabled`
- `dry_run`
- `day_no_fresh_entry`
- `day_hard_exit`
- `swing_position_long_only`
- mandatory Entry/SL/TP geometry
- Severe Crash Guard fresh-LONG block
- broker/exchange permission

Prefixes such as `hard_rule.`, `execution.`, `broker.`, `safety.` and hard Crash Guard keys are also protected.

## 2. Experiment lifecycle

A Phase-5 experiment progresses through explicit states:

`DRAFT -> FROZEN -> READY_FOR_REVIEW | NEEDS_MORE_DATA | REJECTED -> PROMOTED (human approval only)`

A promoted experiment writes an audited soft-parameter registry version only. It does **not** mutate deterministic policy runtime or enable order execution.

## 3. Freeze before evaluation

Before any validation result is inspected, an experiment must contain:

- incumbent value
- challenger value
- written hypothesis
- quality/promotion thresholds
- market series and interval
- at least one TRAIN window
- at least one VALIDATION window
- at least one WALK_FORWARD window

All windows must be timezone-aware, satisfy `start < end`, and not overlap.

The canonical experiment definition and windows are SHA-256 hashed when frozen. Re-freezing or changing the definition through the Phase-5 API is not allowed.

## 4. Train vs out-of-sample behavior

TRAIN results are diagnostic only.

Promotion readiness is determined from frozen VALIDATION and WALK_FORWARD windows. A challenger can perform badly in TRAIN and still be READY_FOR_REVIEW if it passes the predeclared out-of-sample rules; conversely, strong TRAIN performance cannot rescue failed validation.

## 5. Window-end censorship

A candidate evaluated inside a window is not automatically usable by that window.

The outcome must also have been knowable by the frozen window end:

- TP_FIRST / SL_FIRST / AMBIGUOUS require their exit marker at or before window end.
- NEITHER / NOT_ENTERED require the observation horizon to have ended by window end.
- INSUFFICIENT_DATA is excluded.

This prevents a validation period from borrowing a future result from the next walk-forward period.

## 6. Quality gates

Each incumbent/challenger arm is checked independently against frozen thresholds including:

- minimum eligible sample
- minimum entered sample
- minimum clean TP/SL-resolved sample
- maximum ambiguity rate
- minimum coverage of the available window cohort

An arm with inadequate samples or no clean resolved performance metrics fails quality. A required out-of-sample quality failure produces `NEEDS_MORE_DATA`, not a forced winner.

## 7. Challenger comparison

For each frozen window Phase 5 records, at minimum:

- eligible count
- cohort coverage
- entered count
- clean resolved TP/SL count
- outcome distribution
- ambiguity rate
- TP rate among clean resolved outcomes
- mean/median realized R among clean resolved outcomes
- median MAE
- median MFE
- regime breakdown
- outcomes censored at the window boundary

The challenger must meet the predeclared mean-R improvement rule without exceeding the allowed TP-rate deterioration.

Validation and walk-forward win fractions are compared to frozen required fractions. A severe single-window mean-R drop can reject a challenger even if average behavior looks attractive.

## 8. Regime stability

Phase 5 also compares incumbent/challenger behavior by the audited instrument regime recorded with Phase-4 outcomes.

A regime is only assessed when both arms have the required resolved sample. A sufficiently sampled regime with a mean-R deterioration beyond the frozen tolerance makes the challenger unstable and rejects it.

## 9. Human-only promotion

`READY_FOR_REVIEW` is the strongest automatic evaluation state.

Promotion requires an explicit human `approved_by` and approval note. Promotion creates a version in `tb_soft_parameter_versions`, retires the prior active version for the same parameter/scope, and appends an immutable decision record.

The registry is intentionally **not** wired to silently rewrite the deterministic policy module in Phase 5. Applying a promoted value to runtime behavior should be a separate, reviewed integration decision.

## 10. Immutable audit trail

Phase-5 persistence uses additive `tb_*` tables:

- `tb_challenger_experiments`
- `tb_challenger_windows`
- `tb_challenger_window_results`
- `tb_challenger_decisions`
- `tb_soft_parameter_versions`

Every freeze, system evaluation decision, manual rejection and promotion is retained.

## 11. Phase-4 regime hardening

Phase 5 also fixes the long-history edge case identified after Phase 4.

The original Phase-4 classifier requested ascending daily history with `LIMIT 260`, which could select the oldest 260 rows in a long series. Runtime now installs `AUDITED_INSTRUMENT_REGIME_V2_RECENT_WINDOW`, which selects the **most recent completed 260 daily bars at or before the historical `as_of` timestamp** and then restores chronological order for calculation.

This keeps historical regime assignment aligned to the actual decision date rather than the beginning of the database.

## 12. API

Phase 5 adds endpoints under `/api/tradebrain` for:

- create challenger
- freeze challenger windows
- evaluate challenger
- retrieve experiment + windows + results + decisions
- explicit human promotion
- explicit rejection
- challenger statistics
- soft-parameter version history
- parameter-class inspection
- hardened audited regime lookup
- Phase-5 doctrine

## 13. Interpretation boundary

Phase 5 is a research validation framework. It does not establish that a historical edge will persist, does not authorize a trade, does not auto-enable a broker, and does not alter protected safety rules.

Automatic live order execution remains OFF.
