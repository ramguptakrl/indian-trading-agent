"""Validation-only intraday challenger tournament for Trade Brain v0.14 ML.

The tournament compares the existing full-feature baseline with two deliberately isolated
challengers: a compact unweighted feature set and the same compact schema with friction /
temporal-uniqueness sample weighting.  Every configuration is selected using TRAIN +
VALIDATION only. Exactly one globally frozen configuration is then evaluated on the configured
OOS period. HOLDOUT is never predicted here.

This is research evidence. Reusing the historical OOS after a new research hypothesis has
been designed is recorded explicitly; prospective shadow evidence remains the clean final
proof layer.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import pandas as pd

from backend.tradebrain.ml_features import FeatureBundle
from backend.tradebrain.ml_intraday_features import compact_intraday_bundle
from backend.tradebrain.ml_models import (
    DEFAULT_RANDOM_STATE,
    ModelSpec,
    default_model_specs,
    feature_importance,
    feature_schema_hash,
    fit_model,
    predict_positive_probability,
)
from backend.tradebrain.ml_optimizer import DEFAULT_THRESHOLDS, named_feature_sets
from backend.tradebrain.ml_validation import (
    DEFAULT_CHRONOLOGY,
    Chronology,
    chronological_split,
    robustness_score,
    trading_metrics,
)
from backend.tradebrain.ml_weighting import fit_friction_weighted_model

METHOD_VERSION = "BSE_ML_INTRADAY_TOURNAMENT_V1"
VARIANT_FULL = "FULL_UNWEIGHTED"
VARIANT_COMPACT = "COMPACT_UNWEIGHTED"
VARIANT_COMPACT_WEIGHTED = "COMPACT_FRICTION_UNIQUENESS_WEIGHTED"
VARIANTS = (VARIANT_FULL, VARIANT_COMPACT, VARIANT_COMPACT_WEIGHTED)


@dataclass(frozen=True)
class ChallengerTournamentConfig:
    thresholds: tuple[float, ...] = DEFAULT_THRESHOLDS
    min_validation_trades: int = 20
    min_oos_trades: int = 12
    deep_search: bool = True
    random_state: int = DEFAULT_RANDOM_STATE

    def validate(self) -> None:
        if not self.thresholds or any(not 0.0 < float(x) < 1.0 for x in self.thresholds):
            raise ValueError("Tournament thresholds must be probabilities in (0,1)")
        if self.min_validation_trades < 1 or self.min_oos_trades < 1:
            raise ValueError("Tournament trade minimums must be positive")


def _stressed_frame(frame: pd.DataFrame, friction_multiplier: float) -> pd.DataFrame:
    work = frame.copy()
    gross = pd.to_numeric(work["label_gross_return_pct"], errors="coerce").astype(float)
    net = pd.to_numeric(work["label_net_return_pct"], errors="coerce").astype(float)
    base_friction = gross - net
    work["label_net_return_pct"] = gross - base_friction * float(friction_multiplier)
    return work


def _metrics(
    frame: pd.DataFrame,
    probabilities: np.ndarray,
    threshold: float,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    normal = trading_metrics(
        frame,
        probabilities,
        threshold=threshold,
        slippage_bps=0.0,
        friction_multiplier=1.0,
    )
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
    return normal, stress15, stress20


def _passes(
    normal: dict[str, Any],
    stress15: dict[str, Any],
    stress20: dict[str, Any],
    *,
    min_trades: int,
) -> tuple[bool, str]:
    if int(normal.get("trades") or 0) < int(min_trades):
        return False, "INSUFFICIENT_SELECTED_TRADES"
    if float(normal.get("mean_net_return_pct") or 0.0) <= 0.0:
        return False, "NON_POSITIVE_EXPECTANCY"
    if float(stress15.get("mean_net_return_pct") or 0.0) <= 0.0:
        return False, "COLLAPSES_AT_1_5X_FRICTION"
    if float(stress20.get("mean_net_return_pct") or 0.0) <= 0.0:
        return False, "COLLAPSES_AT_2X_FRICTION"
    if float(normal.get("profit_factor") or 0.0) <= 1.0:
        return False, "PROFIT_FACTOR_NOT_ABOVE_ONE"
    return True, "PASS"


def _specs(deep: bool) -> tuple[ModelSpec, ...]:
    specs = default_model_specs()
    if deep:
        return specs
    first: dict[str, ModelSpec] = {}
    for spec in specs:
        first.setdefault(spec.family, spec)
    return tuple(first.values())


def _fit(
    frame: pd.DataFrame,
    *,
    columns: tuple[str, ...],
    spec: ModelSpec,
    variant: str,
    random_state: int,
):
    if variant == VARIANT_COMPACT_WEIGHTED:
        model, weighting_metadata = fit_friction_weighted_model(
            frame,
            feature_columns=columns,
            spec=spec,
            random_state=random_state,
        )
        return model, weighting_metadata
    model = fit_model(
        frame,
        feature_columns=columns,
        spec=spec,
        random_state=random_state,
    )
    return model, None


def _full_feature_sets(bundle: FeatureBundle, *, deep: bool) -> dict[str, tuple[str, ...]]:
    return named_feature_sets(bundle.feature_columns, deep_search=deep)


def _feature_baseline(frame: pd.DataFrame, columns: tuple[str, ...]) -> dict[str, dict[str, float | None]]:
    baseline: dict[str, dict[str, float | None]] = {}
    for column in columns:
        values = pd.to_numeric(frame[column], errors="coerce").replace([np.inf, -np.inf], np.nan)
        finite = values.dropna()
        if finite.empty:
            baseline[column] = {
                "mean": None,
                "std": None,
                "p05": None,
                "p50": None,
                "p95": None,
                "missing_pct": 100.0,
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


def run_intraday_challenger_tournament(
    bundle: FeatureBundle,
    *,
    chronology: Chronology = DEFAULT_CHRONOLOGY,
    config: ChallengerTournamentConfig = ChallengerTournamentConfig(),
) -> dict[str, Any]:
    """Choose one intraday research configuration on validation, then evaluate OOS once."""

    config.validate()
    task = str(bundle.metadata.get("task") or "")
    if task not in {"BSE_INTRADAY_LONG", "BSE_INTRADAY_SHORT"}:
        raise ValueError("Intraday challenger tournament only supports BSE intraday tasks")

    split = chronological_split(bundle.frame, chronology=chronology)
    train = split["TRAIN"]
    validation = split["VALIDATION"]
    oos = split["OOS"]
    holdout = split.get("HOLDOUT", pd.DataFrame())
    if min(len(train), len(validation), len(oos)) == 0:
        return {
            "status": "INSUFFICIENT_CHRONOLOGY",
            "task": task,
            "rows": {name: int(len(value)) for name, value in split.items()},
            "holdout_evaluated": False,
            "trade_authorization": False,
            "order_execution_allowed": False,
        }

    compact = compact_intraday_bundle(bundle)
    compact_columns = tuple(compact.feature_columns)
    variant_sets: dict[str, dict[str, tuple[str, ...]]] = {
        VARIANT_FULL: _full_feature_sets(bundle, deep=config.deep_search),
        VARIANT_COMPACT: {"COMPACT_CORE": compact_columns},
        VARIANT_COMPACT_WEIGHTED: {"COMPACT_CORE": compact_columns},
    }

    trials: list[dict[str, Any]] = []
    best: dict[str, Any] | None = None
    specs = _specs(config.deep_search)

    for variant in VARIANTS:
        for feature_set_name, columns in variant_sets[variant].items():
            for spec in specs:
                try:
                    model, weighting_metadata = _fit(
                        train,
                        columns=columns,
                        spec=spec,
                        variant=variant,
                        random_state=config.random_state,
                    )
                    probabilities = predict_positive_probability(
                        model,
                        validation,
                        feature_columns=columns,
                    )
                except Exception as exc:
                    trials.append(
                        {
                            "variant": variant,
                            "feature_set": feature_set_name,
                            "family": spec.family,
                            "params": dict(spec.params),
                            "status": "REJECTED",
                            "reason": f"MODEL_FIT_FAILED:{type(exc).__name__}:{str(exc)[:180]}",
                            "selection_period": "VALIDATION_ONLY",
                            "oos_used": False,
                            "holdout_used": False,
                        }
                    )
                    continue

                for threshold in config.thresholds:
                    normal, stress15, stress20 = _metrics(validation, probabilities, float(threshold))
                    passed, reason = _passes(
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
                        "variant": variant,
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
                        "weighting": weighting_metadata,
                        "status": "PASS" if passed else "REJECTED",
                        "reason": reason,
                        "selection_period": "VALIDATION_ONLY",
                        "oos_used": False,
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
        return {
            "status": "NO_ROBUST_VALIDATION_CHALLENGER",
            "task": task,
            "trials": trials,
            "winner": None,
            "rows": {name: int(len(value)) for name, value in split.items()},
            "holdout_evaluated": False,
            "oos_configurations_evaluated": 0,
            "prospective_shadow_required_for_clean_final_proof": True,
            "advisory_only": True,
            "trade_authorization": False,
            "order_execution_allowed": False,
        }

    spec = best.pop("model_spec")
    columns = tuple(best["feature_columns"])
    variant = str(best["variant"])
    threshold = float(best["threshold"])
    discovery = pd.concat([train, validation], ignore_index=True)
    frozen_model, frozen_weighting = _fit(
        discovery,
        columns=columns,
        spec=spec,
        variant=variant,
        random_state=config.random_state,
    )
    oos_probabilities = predict_positive_probability(
        frozen_model,
        oos,
        feature_columns=columns,
    )
    oos_normal, oos_stress15, oos_stress20 = _metrics(oos, oos_probabilities, threshold)
    oos_pass, oos_reason = _passes(
        oos_normal,
        oos_stress15,
        oos_stress20,
        min_trades=config.min_oos_trades,
    )

    winner = dict(best)
    winner["feature_columns"] = list(columns)
    winner["training_weighting"] = frozen_weighting
    winner["feature_importance"] = feature_importance(frozen_model, columns)[:30]
    winner["oos_pass"] = bool(oos_pass)
    winner["oos_reason"] = oos_reason

    return {
        "status": "OOS_PASS" if oos_pass else "OOS_REJECTED",
        "method_version": METHOD_VERSION,
        "task": task,
        "winner": winner,
        "model": frozen_model,
        "feature_columns": columns,
        "trials": trials,
        "oos_metrics": oos_normal,
        "oos_stress_15x": oos_stress15,
        "oos_stress_20x": oos_stress20,
        "feature_baseline": _feature_baseline(discovery, columns),
        "chronology": asdict(chronology),
        "rows": {name: int(len(value)) for name, value in split.items()},
        "holdout_rows_unseen": int(len(holdout)),
        "holdout_evaluated": False,
        "global_variant_selection_period": "VALIDATION_ONLY",
        "oos_configurations_evaluated": 1,
        "oos_used_for_variant_selection": False,
        "historical_oos_reused_after_research_hypothesis_change": True,
        "prospective_shadow_required_for_clean_final_proof": True,
        "automatic_registration": False,
        "automatic_promotion": False,
        "advisory_only": True,
        "trade_authorization": False,
        "order_execution_allowed": False,
    }
