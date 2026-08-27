"""Trade Brain Phase 5: frozen challenger / walk-forward validation.

V1 deliberately supports a narrow, auditable challenger family: minimum reward:risk
filters for DAY and SWING_POSITION candidates that already have Phase-4 hypothetical
replay outcomes. It does not search parameter space, mutate hard policy, or look at a
validation window before the challenger and windows are frozen.
"""

from __future__ import annotations

import hashlib
import json
import math
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from statistics import mean, median
from typing import Any

from backend.tradebrain.challenger_store import (
    activate_soft_parameter,
    append_decision,
    challenger_stats,
    create_experiment_record,
    get_experiment,
    list_decisions,
    list_soft_parameter_versions,
    list_window_results,
    list_windows,
    save_window_result,
    set_experiment_status,
    set_frozen_definition,
)
from backend.tradebrain.focus_lab_store import list_replay_outcomes
from backend.tradebrain.market_data_store import get_series

METHOD_VERSION = "FROZEN_WALK_FORWARD_V1"

SUPPORTED_SOFT_PARAMETERS: dict[str, str] = {
    "day_min_reward_risk": "DAY",
    "swing_min_reward_risk": "SWING_POSITION",
}

# These names/prefixes are intentionally rejected even if a caller tries to label
# them as a challenger. Phase 5 is not allowed to optimize the safety boundary.
PROTECTED_EXACT = {
    "advisory_only",
    "order_execution_enabled",
    "dry_run",
    "day_no_fresh_entry",
    "day_hard_exit",
    "swing_position_long_only",
    "mandatory_entry_sl_tp",
    "severe_crash_guard_block_long",
    "broker_allows_trade",
}
PROTECTED_PREFIXES = (
    "hard_rule.",
    "execution.",
    "broker.",
    "safety.",
    "crash_guard_hard_",
)

DEFAULT_THRESHOLDS: dict[str, Any] = {
    "min_eligible": 30,
    "min_entered": 20,
    "min_resolved": 15,
    "max_ambiguity_pct": 15.0,
    "min_coverage_pct": 25.0,
    "min_mean_r_improvement": 0.05,
    "max_tp_rate_drop_pp": 3.0,
    "required_validation_win_fraction": 1.0,
    "required_walk_forward_win_fraction": 0.60,
    "max_single_window_mean_r_drop": 0.25,
    "min_regime_resolved": 10,
    "max_regime_mean_r_drop": 0.25,
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_dt(value: str | datetime) -> datetime:
    dt = datetime.fromisoformat(value) if isinstance(value, str) else value
    if dt.tzinfo is None:
        raise ValueError("Phase-5 windows must use timezone-aware ISO timestamps")
    return dt.astimezone(timezone.utc)


def _json_hash(value: Any) -> str:
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def parameter_class(parameter_key: str) -> str:
    key = parameter_key.strip().lower()
    if key in PROTECTED_EXACT or any(key.startswith(prefix) for prefix in PROTECTED_PREFIXES):
        return "PROTECTED_HARD_RULE"
    if key in SUPPORTED_SOFT_PARAMETERS:
        return "SOFT_CALIBRATABLE"
    return "UNSUPPORTED"


def _normalize_thresholds(overrides: dict[str, Any] | None) -> dict[str, Any]:
    values = dict(DEFAULT_THRESHOLDS)
    if overrides:
        unknown = sorted(set(overrides) - set(values))
        if unknown:
            raise ValueError(f"Unknown Phase-5 threshold(s): {', '.join(unknown)}")
        values.update(overrides)
    integer_keys = {"min_eligible", "min_entered", "min_resolved", "min_regime_resolved"}
    for key in integer_keys:
        values[key] = int(values[key])
        if values[key] < 0:
            raise ValueError(f"{key} must be >= 0")
    percent_keys = {
        "max_ambiguity_pct", "min_coverage_pct", "max_tp_rate_drop_pp",
    }
    for key in percent_keys:
        values[key] = float(values[key])
        if values[key] < 0 or values[key] > 100:
            raise ValueError(f"{key} must be between 0 and 100")
    fraction_keys = {"required_validation_win_fraction", "required_walk_forward_win_fraction"}
    for key in fraction_keys:
        values[key] = float(values[key])
        if values[key] < 0 or values[key] > 1:
            raise ValueError(f"{key} must be between 0 and 1")
    for key in ("min_mean_r_improvement", "max_single_window_mean_r_drop", "max_regime_mean_r_drop"):
        values[key] = float(values[key])
        if values[key] < 0:
            raise ValueError(f"{key} must be >= 0")
    return values


def create_challenger(
    *,
    name: str,
    series_id: str,
    interval: str,
    parameter_key: str,
    incumbent_value: float,
    challenger_value: float,
    hypothesis: str,
    thresholds: dict[str, Any] | None = None,
    created_by: str = "HUMAN_REQUEST",
    db_path: str | None = None,
) -> dict[str, Any]:
    if get_series(series_id, db_path=db_path) is None:
        raise ValueError(f"Unknown market series: {series_id}")
    key = parameter_key.strip().lower()
    klass = parameter_class(key)
    if klass == "PROTECTED_HARD_RULE":
        raise ValueError(f"{key} is a protected hard rule and cannot enter automatic challenger promotion")
    if klass != "SOFT_CALIBRATABLE":
        raise ValueError(
            f"Unsupported Phase-5 parameter: {key}. V1 supports: {', '.join(sorted(SUPPORTED_SOFT_PARAMETERS))}"
        )
    incumbent = float(incumbent_value)
    challenger = float(challenger_value)
    if not math.isfinite(incumbent) or not math.isfinite(challenger) or incumbent <= 0 or challenger <= 0:
        raise ValueError("Reward:risk challenger values must be positive finite numbers")
    if incumbent == challenger:
        raise ValueError("Challenger value must differ from incumbent value")
    if not name.strip() or not hypothesis.strip():
        raise ValueError("name and hypothesis are required before an experiment can be created")
    return create_experiment_record(
        name=name.strip(), series_id=series_id, interval=interval,
        parameter_key=key, parameter_scope=SUPPORTED_SOFT_PARAMETERS[key],
        parameter_class=klass, incumbent_value=incumbent, challenger_value=challenger,
        hypothesis=hypothesis.strip(), thresholds=_normalize_thresholds(thresholds),
        method_version=METHOD_VERSION, created_by=created_by, db_path=db_path,
    )


def _validate_windows(windows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not windows:
        raise ValueError("At least TRAIN, VALIDATION and WALK_FORWARD windows are required")
    normalized: list[dict[str, Any]] = []
    role_counts: dict[str, int] = defaultdict(int)
    for item in windows:
        role = str(item.get("role") or "").upper()
        if role not in {"TRAIN", "VALIDATION", "WALK_FORWARD"}:
            raise ValueError("Window role must be TRAIN, VALIDATION or WALK_FORWARD")
        starts = _parse_dt(item["starts_at"])
        ends = _parse_dt(item["ends_at"])
        if starts >= ends:
            raise ValueError("Every Phase-5 window must satisfy starts_at < ends_at")
        role_counts[role] += 1
        ordinal = int(item.get("ordinal") or role_counts[role])
        normalized.append({
            "window_id": str(uuid.uuid4()),
            "role": role,
            "ordinal": ordinal,
            "starts_at": starts.isoformat(),
            "ends_at": ends.isoformat(),
        })
    for role in ("TRAIN", "VALIDATION", "WALK_FORWARD"):
        if role_counts[role] < 1:
            raise ValueError(f"At least one {role} window is required before freezing")
    normalized.sort(key=lambda row: (row["starts_at"], row["ends_at"], row["role"], row["ordinal"]))
    for prev, curr in zip(normalized, normalized[1:]):
        if _parse_dt(curr["starts_at"]) < _parse_dt(prev["ends_at"]):
            raise ValueError("Phase-5 windows may not overlap; use explicit non-overlapping evaluation periods")
    keys = [(row["role"], row["ordinal"]) for row in normalized]
    if len(keys) != len(set(keys)):
        raise ValueError("Window ordinal must be unique within each role")
    return normalized


def freeze_challenger(
    experiment_id: str,
    *,
    windows: list[dict[str, Any]],
    db_path: str | None = None,
) -> dict[str, Any]:
    experiment = get_experiment(experiment_id, db_path=db_path)
    if not experiment:
        raise ValueError(f"Unknown experiment_id: {experiment_id}")
    if experiment["status"] != "DRAFT":
        raise ValueError("Experiment definition is immutable after it has been frozen")
    normalized = _validate_windows(windows)
    frozen_definition = {
        "experiment_id": experiment_id,
        "series_id": experiment["series_id"],
        "interval": experiment["interval"],
        "parameter_key": experiment["parameter_key"],
        "parameter_scope": experiment["parameter_scope"],
        "incumbent_value": experiment["incumbent_value"],
        "challenger_value": experiment["challenger_value"],
        "hypothesis": experiment["hypothesis"],
        "thresholds": experiment["thresholds"],
        "method_version": experiment["method_version"],
        "windows": [{k: row[k] for k in ("role", "ordinal", "starts_at", "ends_at")} for row in normalized],
    }
    definition_sha256 = _json_hash(frozen_definition)
    frozen_at = _now()
    set_frozen_definition(
        experiment_id, windows=normalized, definition_sha256=definition_sha256,
        frozen_at=frozen_at, db_path=db_path,
    )
    append_decision(
        experiment_id, decision="FROZEN", actor="SYSTEM",
        rationale={
            "definition_sha256": definition_sha256,
            "rule": "Challenger values and windows are frozen before any validation/walk-forward result is evaluated",
        },
        db_path=db_path,
    )
    return experiment_report(experiment_id, db_path=db_path)


def _known_by_window_end(row: dict[str, Any], end: datetime) -> bool:
    outcome = row.get("outcome")
    if outcome in {"TP_FIRST", "SL_FIRST", "AMBIGUOUS"}:
        marker = row.get("exit_timestamp")
    elif outcome in {"NEITHER", "NOT_ENTERED"}:
        marker = row.get("observation_end")
    else:
        return False
    if not marker:
        return False
    return _parse_dt(marker) <= end


def _window_pool(
    rows: list[dict[str, Any]],
    *,
    starts_at: str,
    ends_at: str,
    mode: str,
) -> tuple[list[dict[str, Any]], int]:
    start = _parse_dt(starts_at)
    end = _parse_dt(ends_at)
    evaluated = [
        row for row in rows
        if row.get("mode") == mode
        and start <= _parse_dt(row.get("evaluated_at_ist") or row["evaluated_at"]) < end
    ]
    known = [row for row in evaluated if _known_by_window_end(row, end)]
    return known, len(evaluated) - len(known)


def _summary(rows: list[dict[str, Any]], *, pool_n: int) -> dict[str, Any]:
    counts: dict[str, int] = defaultdict(int)
    for row in rows:
        counts[str(row.get("outcome") or "UNKNOWN")] += 1
    entered = [row for row in rows if row.get("outcome") not in {"NOT_ENTERED", "INSUFFICIENT_DATA"}]
    resolved = [row for row in entered if row.get("outcome") in {"TP_FIRST", "SL_FIRST"}]
    r_values = [float(row["r_multiple"]) for row in resolved if row.get("r_multiple") is not None]
    maes = [float(row["mae_pct"]) for row in entered if row.get("mae_pct") is not None]
    mfes = [float(row["mfe_pct"]) for row in entered if row.get("mfe_pct") is not None]
    ambiguity = sum(row.get("outcome") == "AMBIGUOUS" for row in entered)
    by_regime: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_regime[str(row.get("regime") or "UNKNOWN")].append(row)
    return {
        "pool_n": pool_n,
        "eligible_n": len(rows),
        "coverage_pct": round(len(rows) / pool_n * 100, 3) if pool_n else None,
        "entered_n": len(entered),
        "resolved_n": len(resolved),
        "outcomes": dict(sorted(counts.items())),
        "ambiguity_rate_entered_pct": round(ambiguity / len(entered) * 100, 3) if entered else None,
        "tp_rate_resolved_pct": round(sum(row.get("outcome") == "TP_FIRST" for row in resolved) / len(resolved) * 100, 3) if resolved else None,
        "mean_r_resolved": round(mean(r_values), 6) if r_values else None,
        "median_r_resolved": round(median(r_values), 6) if r_values else None,
        "median_mae_pct": round(median(maes), 6) if maes else None,
        "median_mfe_pct": round(median(mfes), 6) if mfes else None,
        "by_regime": {
            regime: _simple_regime_summary(items)
            for regime, items in sorted(by_regime.items())
        },
    }


def _simple_regime_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    resolved = [row for row in rows if row.get("outcome") in {"TP_FIRST", "SL_FIRST"}]
    r_values = [float(row["r_multiple"]) for row in resolved if row.get("r_multiple") is not None]
    return {
        "n": len(rows),
        "resolved_n": len(resolved),
        "tp_rate_resolved_pct": round(sum(row.get("outcome") == "TP_FIRST" for row in resolved) / len(resolved) * 100, 3) if resolved else None,
        "mean_r_resolved": round(mean(r_values), 6) if r_values else None,
    }


def _quality(metrics: dict[str, Any], thresholds: dict[str, Any]) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if metrics["eligible_n"] < thresholds["min_eligible"]:
        reasons.append(f"eligible_n {metrics['eligible_n']} < {thresholds['min_eligible']}")
    if metrics["entered_n"] < thresholds["min_entered"]:
        reasons.append(f"entered_n {metrics['entered_n']} < {thresholds['min_entered']}")
    if metrics["resolved_n"] < thresholds["min_resolved"]:
        reasons.append(f"resolved_n {metrics['resolved_n']} < {thresholds['min_resolved']}")
    ambiguity = metrics.get("ambiguity_rate_entered_pct")
    if ambiguity is not None and ambiguity > thresholds["max_ambiguity_pct"]:
        reasons.append(f"ambiguity {ambiguity:.3f}% > {thresholds['max_ambiguity_pct']:.3f}%")
    coverage = metrics.get("coverage_pct")
    if coverage is None or coverage < thresholds["min_coverage_pct"]:
        reasons.append(f"coverage {coverage if coverage is not None else 'NA'} < {thresholds['min_coverage_pct']:.3f}%")
    if metrics.get("mean_r_resolved") is None or metrics.get("tp_rate_resolved_pct") is None:
        reasons.append("resolved performance metrics unavailable")
    return (not reasons), reasons


def _compare_arms(
    incumbent: dict[str, Any], challenger: dict[str, Any], thresholds: dict[str, Any]
) -> dict[str, Any]:
    if incumbent.get("mean_r_resolved") is None or challenger.get("mean_r_resolved") is None:
        return {"win": False, "status": "INSUFFICIENT_METRICS"}
    delta_r = challenger["mean_r_resolved"] - incumbent["mean_r_resolved"]
    incumbent_tp = incumbent.get("tp_rate_resolved_pct")
    challenger_tp = challenger.get("tp_rate_resolved_pct")
    delta_tp = None if incumbent_tp is None or challenger_tp is None else challenger_tp - incumbent_tp
    win = (
        delta_r >= thresholds["min_mean_r_improvement"]
        and delta_tp is not None
        and delta_tp >= -thresholds["max_tp_rate_drop_pp"]
    )
    return {
        "win": win,
        "status": "CHALLENGER_WIN" if win else "INCUMBENT_OR_TIE",
        "mean_r_delta": round(delta_r, 6),
        "tp_rate_delta_pp": round(delta_tp, 6) if delta_tp is not None else None,
    }


def _regime_stability(
    window_pairs: list[tuple[dict[str, Any], dict[str, Any]]], thresholds: dict[str, Any]
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    unstable: list[str] = []
    regimes = sorted({
        regime
        for incumbent, challenger in window_pairs
        for regime in set(incumbent.get("by_regime", {})) | set(challenger.get("by_regime", {}))
    })
    for regime in regimes:
        inc_n = sum(pair[0].get("by_regime", {}).get(regime, {}).get("resolved_n", 0) for pair in window_pairs)
        ch_n = sum(pair[1].get("by_regime", {}).get(regime, {}).get("resolved_n", 0) for pair in window_pairs)
        if min(inc_n, ch_n) < thresholds["min_regime_resolved"]:
            rows.append({"regime": regime, "assessed": False, "incumbent_resolved": inc_n, "challenger_resolved": ch_n})
            continue
        inc_weighted = []
        ch_weighted = []
        for incumbent, challenger in window_pairs:
            inc = incumbent.get("by_regime", {}).get(regime)
            ch = challenger.get("by_regime", {}).get(regime)
            if inc and inc.get("mean_r_resolved") is not None:
                inc_weighted.extend([inc["mean_r_resolved"]] * int(inc.get("resolved_n") or 0))
            if ch and ch.get("mean_r_resolved") is not None:
                ch_weighted.extend([ch["mean_r_resolved"]] * int(ch.get("resolved_n") or 0))
        inc_mean = mean(inc_weighted) if inc_weighted else None
        ch_mean = mean(ch_weighted) if ch_weighted else None
        delta = None if inc_mean is None or ch_mean is None else ch_mean - inc_mean
        is_unstable = delta is not None and delta < -thresholds["max_regime_mean_r_drop"]
        if is_unstable:
            unstable.append(regime)
        rows.append({
            "regime": regime,
            "assessed": delta is not None,
            "incumbent_resolved": inc_n,
            "challenger_resolved": ch_n,
            "mean_r_delta": round(delta, 6) if delta is not None else None,
            "unstable": is_unstable,
        })
    return {
        "stable": not unstable,
        "unstable_regimes": unstable,
        "regimes": rows,
        "minimum_resolved_per_arm": thresholds["min_regime_resolved"],
    }


def evaluate_challenger(experiment_id: str, *, db_path: str | None = None) -> dict[str, Any]:
    experiment = get_experiment(experiment_id, db_path=db_path)
    if not experiment:
        raise ValueError(f"Unknown experiment_id: {experiment_id}")
    if experiment["status"] != "FROZEN":
        raise ValueError("Only a FROZEN experiment can be evaluated; freeze windows before seeing results")
    if experiment["parameter_class"] != "SOFT_CALIBRATABLE":
        raise ValueError("Protected or unsupported parameters cannot be evaluated for promotion")

    windows = list_windows(experiment_id, db_path=db_path)
    rows = list_replay_outcomes(
        series_id=experiment["series_id"], interval=experiment["interval"],
        limit=100000, db_path=db_path,
    )
    thresholds = experiment["thresholds"]
    mode = experiment["parameter_scope"]
    computed_at = _now()
    comparisons: list[dict[str, Any]] = []
    non_training_pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []

    for window in windows:
        pool, censored = _window_pool(
            rows, starts_at=window["starts_at"], ends_at=window["ends_at"], mode=mode,
        )
        incumbent_rows = [
            row for row in pool
            if row.get("reward_risk") is not None and float(row["reward_risk"]) >= float(experiment["incumbent_value"])
        ]
        challenger_rows = [
            row for row in pool
            if row.get("reward_risk") is not None and float(row["reward_risk"]) >= float(experiment["challenger_value"])
        ]
        incumbent_metrics = _summary(incumbent_rows, pool_n=len(pool))
        challenger_metrics = _summary(challenger_rows, pool_n=len(pool))
        incumbent_metrics["outcomes_censored_at_window_end"] = censored
        challenger_metrics["outcomes_censored_at_window_end"] = censored
        incumbent_quality, incumbent_reasons = _quality(incumbent_metrics, thresholds)
        challenger_quality, challenger_reasons = _quality(challenger_metrics, thresholds)
        save_window_result(
            experiment_id=experiment_id, window_id=window["window_id"], arm="INCUMBENT",
            metrics=incumbent_metrics, quality_pass=incumbent_quality,
            quality_reasons=incumbent_reasons, computed_at=computed_at, db_path=db_path,
        )
        save_window_result(
            experiment_id=experiment_id, window_id=window["window_id"], arm="CHALLENGER",
            metrics=challenger_metrics, quality_pass=challenger_quality,
            quality_reasons=challenger_reasons, computed_at=computed_at, db_path=db_path,
        )
        comparison = _compare_arms(incumbent_metrics, challenger_metrics, thresholds)
        comparison.update({
            "window_id": window["window_id"], "role": window["role"], "ordinal": window["ordinal"],
            "starts_at": window["starts_at"], "ends_at": window["ends_at"],
            "incumbent_quality_pass": incumbent_quality,
            "challenger_quality_pass": challenger_quality,
            "quality_pass": incumbent_quality and challenger_quality,
            "censored_outcomes": censored,
        })
        comparisons.append(comparison)
        if window["role"] != "TRAIN":
            non_training_pairs.append((incumbent_metrics, challenger_metrics))

    required = [row for row in comparisons if row["role"] in {"VALIDATION", "WALK_FORWARD"}]
    quality_failed = [row for row in required if not row["quality_pass"]]
    validation = [row for row in required if row["role"] == "VALIDATION"]
    walk_forward = [row for row in required if row["role"] == "WALK_FORWARD"]
    validation_win_fraction = sum(row.get("win", False) for row in validation) / len(validation) if validation else 0.0
    walk_forward_win_fraction = sum(row.get("win", False) for row in walk_forward) / len(walk_forward) if walk_forward else 0.0
    worst_delta = min((row.get("mean_r_delta") for row in required if row.get("mean_r_delta") is not None), default=None)
    regime_stability = _regime_stability(non_training_pairs, thresholds)

    if quality_failed:
        status = "NEEDS_MORE_DATA"
        reason = "One or more validation/walk-forward windows failed frozen sample/ambiguity/coverage quality gates"
    elif worst_delta is not None and worst_delta < -thresholds["max_single_window_mean_r_drop"]:
        status = "REJECTED"
        reason = "Challenger suffered a disallowed out-of-sample mean-R drop in at least one required window"
    elif not regime_stability["stable"]:
        status = "REJECTED"
        reason = "Challenger was unstable in at least one sufficiently sampled regime"
    elif (
        validation_win_fraction >= thresholds["required_validation_win_fraction"]
        and walk_forward_win_fraction >= thresholds["required_walk_forward_win_fraction"]
    ):
        status = "READY_FOR_REVIEW"
        reason = "Frozen validation and walk-forward gates passed; explicit human approval is still required for promotion"
    else:
        status = "REJECTED"
        reason = "Challenger did not win the required fraction of frozen out-of-sample windows"

    set_experiment_status(experiment_id, status, evaluated_at=computed_at, db_path=db_path)
    append_decision(
        experiment_id, decision=status, actor="SYSTEM",
        rationale={
            "reason": reason,
            "validation_win_fraction": round(validation_win_fraction, 6),
            "walk_forward_win_fraction": round(walk_forward_win_fraction, 6),
            "quality_failed_windows": [row["window_id"] for row in quality_failed],
            "worst_mean_r_delta": worst_delta,
            "regime_stability": regime_stability,
            "automatic_promotion": False,
        },
        db_path=db_path,
    )
    return {
        "experiment": get_experiment(experiment_id, db_path=db_path),
        "decision": status,
        "reason": reason,
        "validation_win_fraction": round(validation_win_fraction, 6),
        "walk_forward_win_fraction": round(walk_forward_win_fraction, 6),
        "worst_mean_r_delta": worst_delta,
        "regime_stability": regime_stability,
        "comparisons": comparisons,
        "automatic_promotion": False,
        "promotion_requires_explicit_human_approval": True,
        "performance_boundary": "Historical hypothetical replay validation is not a promise of future trading performance",
    }


def promote_challenger(
    experiment_id: str,
    *,
    approved_by: str,
    approval_note: str,
    db_path: str | None = None,
) -> dict[str, Any]:
    experiment = get_experiment(experiment_id, db_path=db_path)
    if not experiment:
        raise ValueError(f"Unknown experiment_id: {experiment_id}")
    if experiment["parameter_class"] != "SOFT_CALIBRATABLE":
        raise ValueError("Only a soft calibratable parameter can be promoted")
    if experiment["status"] != "READY_FOR_REVIEW":
        raise ValueError("Experiment must pass frozen validation and be READY_FOR_REVIEW before promotion")
    if len(approved_by.strip()) < 2 or len(approval_note.strip()) < 5:
        raise ValueError("Explicit approved_by and a meaningful approval_note are required")
    version = activate_soft_parameter(
        parameter_key=experiment["parameter_key"], parameter_scope=experiment["parameter_scope"],
        value=experiment["challenger_value"], source_experiment_id=experiment_id,
        approved_by=approved_by.strip(), approval_note=approval_note.strip(), db_path=db_path,
    )
    set_experiment_status(experiment_id, "PROMOTED", db_path=db_path)
    append_decision(
        experiment_id, decision="PROMOTED", actor=approved_by.strip(),
        rationale={
            "approval_note": approval_note.strip(),
            "soft_parameter_version": version["version"],
            "runtime_policy_mutated": False,
            "execution_enabled": False,
            "rule": "Promotion writes the audited soft-parameter registry only; it does not alter protected policy or enable execution",
        },
        db_path=db_path,
    )
    return {
        "experiment": get_experiment(experiment_id, db_path=db_path),
        "soft_parameter_version": version,
        "runtime_policy_mutated": False,
        "execution_enabled": False,
    }


def reject_challenger(
    experiment_id: str,
    *,
    rejected_by: str,
    rejection_note: str,
    db_path: str | None = None,
) -> dict[str, Any]:
    experiment = get_experiment(experiment_id, db_path=db_path)
    if not experiment:
        raise ValueError(f"Unknown experiment_id: {experiment_id}")
    if experiment["status"] in {"PROMOTED", "REJECTED"}:
        raise ValueError(f"Experiment is already terminal: {experiment['status']}")
    if len(rejected_by.strip()) < 2 or len(rejection_note.strip()) < 5:
        raise ValueError("Explicit rejected_by and a meaningful rejection_note are required")
    set_experiment_status(experiment_id, "REJECTED", db_path=db_path)
    append_decision(
        experiment_id, decision="REJECTED", actor=rejected_by.strip(),
        rationale={"reason": rejection_note.strip(), "manual": True}, db_path=db_path,
    )
    return experiment_report(experiment_id, db_path=db_path)


def experiment_report(experiment_id: str, *, db_path: str | None = None) -> dict[str, Any]:
    experiment = get_experiment(experiment_id, db_path=db_path)
    if not experiment:
        raise ValueError(f"Unknown experiment_id: {experiment_id}")
    return {
        "experiment": experiment,
        "windows": list_windows(experiment_id, db_path=db_path),
        "window_results": list_window_results(experiment_id, db_path=db_path),
        "decisions": list_decisions(experiment_id, db_path=db_path),
        "definition_frozen": bool(experiment.get("definition_sha256")),
        "hard_policy_mutation_allowed": False,
        "automatic_promotion_allowed": False,
    }


def phase5_stats(*, db_path: str | None = None) -> dict[str, Any]:
    return {
        **challenger_stats(db_path=db_path),
        "supported_soft_parameters": sorted(SUPPORTED_SOFT_PARAMETERS),
        "protected_parameter_examples": sorted(PROTECTED_EXACT),
        "active_soft_parameters": list_soft_parameter_versions(active_only=True, db_path=db_path),
        "method_version": METHOD_VERSION,
    }
