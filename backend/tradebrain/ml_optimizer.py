"""Controlled chronological optimizer for Trade Brain v0.14 ML.

The optimizer chooses research candidates using TRAIN + VALIDATION only. OOS is evaluated
after the configuration is frozen. The configured historical holdout is never used for
hyperparameter selection. No result from this module can mutate protected policy or place
broker orders.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any, Iterable

import numpy as np
import pandas as pd

from backend.tradebrain.ml_features import FeatureBundle
from backend.tradebrain.ml_models import (
    DEFAULT_RANDOM_STATE,
    MODEL_FAMILIES,
    ModelSpec,
    default_model_specs,
    feature_importance,
    feature_schema_hash,
    fit_model,
    predict_positive_probability,
)
from backend.tradebrain.ml_validation import (
    DEFAULT_CHRONOLOGY,
    Chronology,
    chronological_split,
    expanding_walk_forward_windows,
    robustness_score,
    trading_metrics,
)

METHOD_VERSION = "BSE_ML_OPTIMIZER_V1"
DEFAULT_THRESHOLDS = (0.50, 0.55, 0.60, 0.65)


@dataclass(frozen=True)
class OptimizerConfig:
    thresholds: tuple[float, ...] = DEFAULT_THRESHOLDS
    min_validation_trades: int = 20
    min_oos_trades: int = 12
    random_state: int = DEFAULT_RANDOM_STATE
    deep_search: bool = False

    def validate(self) -> None:
        if not self.thresholds or any(not 0.0 < float(x) < 1.0 for x in self.thresholds):
            raise ValueError("Optimizer thresholds must be probabilities in (0,1)")
        if self.min_validation_trades < 1 or self.min_oos_trades < 1:
            raise ValueError("Minimum trade counts must be positive")


@dataclass
class OptimizationResult:
    status: str
    task: str
    model: Any | None
    feature_columns: tuple[str, ...]
    winner: dict[str, Any] | None
    trials: list[dict[str, Any]]
    oos_metrics: dict[str, Any] | None
    oos_stress_15x: dict[str, Any] | None
    oos_stress_20x: dict[str, Any] | None
    walk_forward: list[dict[str, Any]]
    metadata: dict[str, Any]


def _matches(name: str, tokens: tuple[str, ...]) -> bool:
    lowered = name.lower()
    return any(token in lowered for token in tokens)


def named_feature_sets(feature_columns: Iterable[str], *, deep_search: bool) -> dict[str, tuple[str, ...]]:
    columns = tuple(str(x) for x in feature_columns)
    if not columns:
        return {}
    missing = tuple(c for c in columns if c.startswith("missing__"))
    trend = tuple(
        c for c in columns
        if _matches(
            c,
            (
                "return_", "log_return", "ema_", "sma_", "macd", "adx", "plus_di",
                "minus_di", "dmi_", "roc_", "supertrend", "donchian",
            ),
        )
    )
    structure = tuple(
        c for c in columns
        if _matches(
            c,
            (
                "atr_", "natr_", "vwap", "opening_range", "gap_pct", "previous_day",
                "distance_prev", "bollinger", "stochastic", "cci_", "candle_", "wick",
                "inside_bar", "engulf", "doji", "fvg", "fib_", "local_range",
            ),
        )
    )
    volume_context = tuple(
        c for c in columns
        if _matches(
            c,
            (
                "volume", "obv", "mfi", "minutes_", "day_of_week", "nifty",
                "alignment", "regime", "mtf_",
            ),
        )
    )

    def merged(*groups: tuple[str, ...]) -> tuple[str, ...]:
        wanted = set()
        for group in groups:
            wanted.update(group)
        wanted.update(missing)
        return tuple(c for c in columns if c in wanted)

    sets: dict[str, tuple[str, ...]] = {
        "ALL": columns,
        "TREND_MOMENTUM": merged(trend),
        "STRUCTURE_VOLUME": merged(structure, volume_context),
    }
    if deep_search:
        sets.update(
            {
                "TREND_STRUCTURE": merged(trend, structure),
                "TREND_CONTEXT": merged(trend, volume_context),
                "STRUCTURE_ONLY": merged(structure),
                "VOLUME_CONTEXT": merged(volume_context),
            }
        )
    return {name: values for name, values in sets.items() if len(values) >= 3}


def _search_specs(deep: bool, specs: Iterable[ModelSpec] | None) -> tuple[ModelSpec, ...]:
    provided = tuple(specs or default_model_specs())
    if deep:
        return provided
    first_by_family: dict[str, ModelSpec] = {}
    for spec in provided:
        if spec.family not in MODEL_FAMILIES:
            raise ValueError(f"Unrecognized model family in optimizer: {spec.family}")
        first_by_family.setdefault(spec.family, spec)
    return tuple(first_by_family[name] for name in MODEL_FAMILIES if name in first_by_family)


def _stressed_frame(frame: pd.DataFrame, friction_multiplier: float) -> pd.DataFrame:
    """Scale all modeled friction, not gross market move, by the requested multiplier."""
    work = frame.copy()
    gross = pd.to_numeric(work["label_gross_return_pct"], errors="coerce").astype(float)
    net = pd.to_numeric(work["label_net_return_pct"], errors="coerce").astype(float)
    base_friction = gross - net
    work["label_net_return_pct"] = gross - base_friction * float(friction_multiplier)
    return work


def _metrics(frame: pd.DataFrame, probabilities: np.ndarray, threshold: float) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    normal = trading_metrics(frame, probabilities, threshold=threshold, slippage_bps=0.0, friction_multiplier=1.0)
    stress15 = trading_metrics(
        _stressed_frame(frame, 1.5),
        probabilities,
        threshold=threshold,
        slippage_bps=0.0,
        friction_multiplier=1.0,
    )
    stress20 = trading_metrics(
        _stressed_frame(frame, 2.0),
        probabilities,
        threshold=threshold,
        slippage_bps=0.0,
        friction_multiplier=1.0,
    )
    normal["cost_stress_method"] = "SCALE_IMPLIED_GROSS_MINUS_NET_FRICTION"
    stress15["cost_stress_method"] = "SCALE_IMPLIED_GROSS_MINUS_NET_FRICTION"
    stress20["cost_stress_method"] = "SCALE_IMPLIED_GROSS_MINUS_NET_FRICTION"
    return normal, stress15, stress20


def _passes_robustness(normal: dict[str, Any], stress15: dict[str, Any], stress20: dict[str, Any], *, min_trades: int) -> tuple[bool, str]:
    if int(normal["trades"]) < int(min_trades):
        return False, "INSUFFICIENT_SELECTED_TRADES"
    if float(normal["mean_net_return_pct"]) <= 0.0:
        return False, "NON_POSITIVE_EXPECTANCY"
    if float(stress15["mean_net_return_pct"]) <= 0.0:
        return False, "COLLAPSES_AT_1_5X_FRICTION"
    if float(stress20["mean_net_return_pct"]) <= 0.0:
        return False, "COLLAPSES_AT_2X_FRICTION"
    if float(normal["profit_factor"]) <= 1.0:
        return False, "PROFIT_FACTOR_NOT_ABOVE_ONE"
    return True, "PASS"


def _feature_baseline(frame: pd.DataFrame, columns: tuple[str, ...]) -> dict[str, dict[str, float | None]]:
    baseline: dict[str, dict[str, float | None]] = {}
    for column in columns:
        values = pd.to_numeric(frame[column], errors="coerce")
        finite = values.replace([np.inf, -np.inf], np.nan).dropna()
        if finite.empty:
            baseline[column] = {
                "mean": None, "std": None, "p05": None, "p50": None, "p95": None, "missing_pct": 100.0
            }
            continue
        baseline[column] = {
            "mean": float(finite.mean()),
            "std": float(finite.std(ddof=0)),
            "p05": float(finite.quantile(0.05)),
            "p50": float(finite.quantile(0.50)),
            "p95": float(finite.quantile(0.95)),
            "missing_pct": float((1.0 - len(finite) / max(1, len(values))) * 100.0),
        }
    return baseline


def _trial_id(task: str, feature_set: str, spec: ModelSpec, threshold: float) -> str:
    payload = {
        "task": task,
        "feature_set": feature_set,
        "family": spec.family,
        "params": spec.params,
        "threshold": float(threshold),
        "method": METHOD_VERSION,
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:12]
    return f"{task}:{digest}"


def _walk_forward_for_winner(
    frame: pd.DataFrame,
    *,
    feature_columns: tuple[str, ...],
    spec: ModelSpec,
    threshold: float,
    random_state: int,
) -> list[dict[str, Any]]:
    times = pd.to_datetime(frame["ts_close"], utc=True)
    if frame.empty:
        return []
    years = sorted(set(times.dt.year.tolist()))
    if len(years) < 2:
        return []
    first = max(years[1], 2018)
    last = min(max(years), 2025)
    rows: list[dict[str, Any]] = []
    for train, test, year in expanding_walk_forward_windows(
        frame,
        first_test_year=first,
        last_test_year=last,
        min_train_rows=100,
    ):
        boundary = pd.Timestamp(f"{year}-01-01T00:00:00Z")
        label_end = pd.to_datetime(train["label_end"], utc=True)
        train = train.loc[label_end < boundary].copy().reset_index(drop=True)
        if len(train) < 100 or len(test) < 10 or set(train["label_net_positive"].astype(int)) != {0, 1}:
            continue
        model = fit_model(
            train,
            feature_columns=feature_columns,
            spec=spec,
            random_state=random_state,
        )
        probabilities = predict_positive_probability(model, test, feature_columns=feature_columns)
        normal, stress15, stress20 = _metrics(test, probabilities, threshold)
        rows.append(
            {
                "year": year,
                "train_rows": int(len(train)),
                "test_rows": int(len(test)),
                "normal": normal,
                "stress_15x": stress15,
                "stress_20x": stress20,
                "advisory_only": True,
                "order_execution_allowed": False,
            }
        )
    return rows


def optimize_labeled_dataset(
    bundle: FeatureBundle,
    *,
    chronology: Chronology = DEFAULT_CHRONOLOGY,
    config: OptimizerConfig = OptimizerConfig(),
    model_specs: Iterable[ModelSpec] | None = None,
) -> OptimizationResult:
    """Search TRAIN/VALIDATION, freeze one config, then report OOS once.

    HOLDOUT rows are counted but never predicted here.
    """
    config.validate()
    frame = bundle.frame.copy()
    task = str(bundle.metadata.get("task") or "UNKNOWN")
    if frame.empty:
        return OptimizationResult(
            status="INSUFFICIENT_DATA",
            task=task,
            model=None,
            feature_columns=(),
            winner=None,
            trials=[],
            oos_metrics=None,
            oos_stress_15x=None,
            oos_stress_20x=None,
            walk_forward=[],
            metadata={"reason": "EMPTY_LABELED_DATASET", "holdout_evaluated": False},
        )
    split = chronological_split(frame, chronology=chronology)
    train = split["TRAIN"]
    validation = split["VALIDATION"]
    oos = split["OOS"]
    holdout = split.get("HOLDOUT", pd.DataFrame())
    if min(len(train), len(validation), len(oos)) == 0:
        return OptimizationResult(
            status="INSUFFICIENT_CHRONOLOGY",
            task=task,
            model=None,
            feature_columns=(),
            winner=None,
            trials=[],
            oos_metrics=None,
            oos_stress_15x=None,
            oos_stress_20x=None,
            walk_forward=[],
            metadata={
                "rows": {name: int(len(value)) for name, value in split.items()},
                "holdout_evaluated": False,
                "chronology_method": "BSE_ML_CHRONOLOGY_V1",
            },
        )

    feature_sets = named_feature_sets(bundle.feature_columns, deep_search=config.deep_search)
    specs = _search_specs(config.deep_search, model_specs)
    trials: list[dict[str, Any]] = []
    best: dict[str, Any] | None = None

    for feature_set_name, columns in feature_sets.items():
        for spec in specs:
            try:
                model = fit_model(
                    train,
                    feature_columns=columns,
                    spec=spec,
                    random_state=config.random_state,
                )
                probabilities = predict_positive_probability(model, validation, feature_columns=columns)
            except Exception as exc:
                trials.append(
                    {
                        "trial_id": _trial_id(task, feature_set_name, spec, config.thresholds[0]),
                        "feature_set": feature_set_name,
                        "feature_count": len(columns),
                        "family": spec.family,
                        "params": dict(spec.params),
                        "status": "REJECTED",
                        "reason": f"MODEL_FIT_FAILED:{type(exc).__name__}:{str(exc)[:180]}",
                    }
                )
                continue

            for threshold in config.thresholds:
                normal, stress15, stress20 = _metrics(validation, probabilities, float(threshold))
                passed, reason = _passes_robustness(
                    normal,
                    stress15,
                    stress20,
                    min_trades=config.min_validation_trades,
                )
                score = robustness_score(
                    normal,
                    stress15,
                    stress20,
                    min_trades=config.min_validation_trades,
                )
                trial = {
                    "trial_id": _trial_id(task, feature_set_name, spec, float(threshold)),
                    "feature_set": feature_set_name,
                    "feature_count": len(columns),
                    "feature_schema_hash": feature_schema_hash(columns),
                    "family": spec.family,
                    "params": dict(spec.params),
                    "threshold": float(threshold),
                    "validation": normal,
                    "stress_15x": stress15,
                    "stress_20x": stress20,
                    "robustness_score": None if not np.isfinite(score) else float(score),
                    "status": "PASS" if passed else "REJECTED",
                    "reason": reason,
                    "selection_period": "VALIDATION_ONLY",
                    "holdout_used": False,
                }
                trials.append(trial)
                if passed and (best is None or float(score) > float(best["robustness_score"])):
                    best = {
                        **trial,
                        "feature_columns": columns,
                        "model_spec": spec,
                    }

    if best is None:
        return OptimizationResult(
            status="NO_ROBUST_CANDIDATE",
            task=task,
            model=None,
            feature_columns=(),
            winner=None,
            trials=trials,
            oos_metrics=None,
            oos_stress_15x=None,
            oos_stress_20x=None,
            walk_forward=[],
            metadata={
                "rows": {name: int(len(value)) for name, value in split.items()},
                "holdout_evaluated": False,
                "chronology_method": "BSE_ML_CHRONOLOGY_V1",
                "reason": "NO_VALIDATION_CANDIDATE_SURVIVED_ROBUSTNESS",
            },
        )

    frozen_spec = best["model_spec"]
    frozen_columns = tuple(best["feature_columns"])
    threshold = float(best["threshold"])
    discovery_train = pd.concat([train, validation], ignore_index=True)
    frozen_model = fit_model(
        discovery_train,
        feature_columns=frozen_columns,
        spec=frozen_spec,
        random_state=config.random_state,
    )
    oos_probabilities = predict_positive_probability(frozen_model, oos, feature_columns=frozen_columns)
    oos_normal, oos_stress15, oos_stress20 = _metrics(oos, oos_probabilities, threshold)
    oos_pass, oos_reason = _passes_robustness(
        oos_normal,
        oos_stress15,
        oos_stress20,
        min_trades=config.min_oos_trades,
    )

    walk_forward = _walk_forward_for_winner(
        frame.loc[pd.to_datetime(frame["ts_close"], utc=True) < chronology.holdout_start].copy(),
        feature_columns=frozen_columns,
        spec=frozen_spec,
        threshold=threshold,
        random_state=config.random_state,
    )
    best = dict(best)
    best.pop("model_spec", None)
    best["feature_columns"] = list(frozen_columns)
    best.update(
        {
            "oos_pass": bool(oos_pass),
            "oos_reason": oos_reason,
            "feature_importance": feature_importance(frozen_model, frozen_columns)[:30],
        }
    )
    status = "OOS_PASS" if oos_pass else "OOS_REJECTED"
    metadata = {
        "method_version": METHOD_VERSION,
        "task": task,
        "dataset_snapshot_hash": bundle.metadata.get("dataset_snapshot_hash"),
        "feature_method_version": bundle.metadata.get("method_version"),
        "chronology_method": "BSE_ML_CHRONOLOGY_V1",
        "chronology": asdict(chronology),
        "rows": {name: int(len(value)) for name, value in split.items()},
        "holdout_rows": int(len(holdout)),
        "holdout_evaluated": False,
        "selection_period": "VALIDATION_ONLY",
        "oos_used_for_selection": False,
        "feature_baseline": _feature_baseline(discovery_train, frozen_columns),
        "advisory_only": True,
        "trade_authorization": False,
        "order_execution_allowed": False,
    }
    return OptimizationResult(
        status=status,
        task=task,
        model=frozen_model,
        feature_columns=frozen_columns,
        winner=best,
        trials=trials,
        oos_metrics=oos_normal,
        oos_stress_15x=oos_stress15,
        oos_stress_20x=oos_stress20,
        walk_forward=walk_forward,
        metadata=metadata,
    )
