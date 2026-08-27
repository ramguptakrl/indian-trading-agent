"""CPCV strategy-matrix Probability of Backtest Overfitting for Trade Brain v0.14 ML.

PBO must test the selection process itself. Therefore each distinct validation-search
configuration (feature set + model specification + threshold) is a strategy column. We do not
first choose a representative using the whole discovery period, because that would leak
information from CPCV test blocks into the strategy set.

Model fits are cached per fold/specification, so multiple thresholds share one fitted model.
The PBO matrix is built only from TRAIN + VALIDATION discovery data. OOS and holdout are never
used to estimate researcher selection bias.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from typing import Any

import numpy as np
import pandas as pd

from backend.tradebrain.ml_cpcv import CPCVConfig, combinatorial_purged_folds
from backend.tradebrain.ml_features import FeatureBundle
from backend.tradebrain.ml_models import DEFAULT_RANDOM_STATE, ModelSpec, fit_model, predict_positive_probability
from backend.tradebrain.ml_multiple_testing import probability_backtest_overfitting
from backend.tradebrain.ml_optimizer import named_feature_sets
from backend.tradebrain.ml_validation import DEFAULT_CHRONOLOGY, Chronology, chronological_split, trading_metrics

METHOD_VERSION = "BSE_ML_PBO_V2"


@dataclass(frozen=True)
class PBOConfig:
    max_candidate_strategies: int = 400
    min_selected_trades: int = 10
    random_state: int = DEFAULT_RANDOM_STATE
    cpcv: CPCVConfig = CPCVConfig()

    def validate(self) -> None:
        if self.max_candidate_strategies < 3:
            raise ValueError("max_candidate_strategies must be >= 3")
        if self.min_selected_trades < 1:
            raise ValueError("min_selected_trades must be positive")
        self.cpcv.validate()


def _stressed_frame(frame: pd.DataFrame, multiplier: float) -> pd.DataFrame:
    work = frame.copy()
    gross = pd.to_numeric(work["label_gross_return_pct"], errors="coerce").astype(float)
    net = pd.to_numeric(work["label_net_return_pct"], errors="coerce").astype(float)
    friction = gross - net
    work["label_net_return_pct"] = gross - friction * float(multiplier)
    return work


def _strategy_score(frame: pd.DataFrame, probabilities: np.ndarray, threshold: float, min_trades: int) -> float:
    metrics = trading_metrics(
        _stressed_frame(frame, 2.0),
        probabilities,
        threshold=float(threshold),
        slippage_bps=0.0,
        friction_multiplier=1.0,
    )
    if int(metrics.get("trades") or 0) < int(min_trades):
        return float("nan")
    return float(metrics.get("mean_net_return_pct") or 0.0)


def _candidate_key(trial: dict[str, Any]) -> str:
    payload = {
        "feature_set": str(trial.get("feature_set") or ""),
        "family": str(trial.get("family") or ""),
        "params": dict(trial.get("params") or {}),
        "threshold": trial.get("threshold"),
        "feature_schema_hash": trial.get("feature_schema_hash"),
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _fit_key(feature_set: str, spec: ModelSpec) -> str:
    return json.dumps(
        {
            "feature_set": feature_set,
            "family": spec.family,
            "params": dict(spec.params),
        },
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _resolve_candidates(
    trials: list[dict[str, Any]],
    feature_sets: dict[str, tuple[str, ...]],
) -> list[dict[str, Any]]:
    """Resolve every distinct searchable configuration without using its validation rank."""
    resolved: list[dict[str, Any]] = []
    seen: set[str] = set()
    for trial in trials:
        if not isinstance(trial.get("validation"), dict):
            continue
        key = _candidate_key(trial)
        if key in seen:
            continue
        seen.add(key)
        feature_set = str(trial.get("feature_set") or "")
        columns = feature_sets.get(feature_set)
        if not columns:
            continue
        try:
            threshold = float(trial.get("threshold"))
            if not 0.0 < threshold < 1.0:
                continue
            spec = ModelSpec(str(trial.get("family")), dict(trial.get("params") or {}))
            spec.validate()
        except Exception:
            continue
        resolved.append(
            {
                "candidate_key": key,
                "feature_set": feature_set,
                "columns": tuple(columns),
                "spec": spec,
                "threshold": threshold,
                "fit_key": _fit_key(feature_set, spec),
            }
        )
    return resolved


def evaluate_pbo_from_optimizer(
    bundle: FeatureBundle,
    result: Any,
    *,
    chronology: Chronology = DEFAULT_CHRONOLOGY,
    config: PBOConfig = PBOConfig(),
) -> dict[str, Any]:
    """Build discovery-only purged IS/OOS matrices and estimate PBO for all candidates."""
    config.validate()
    trials = list(getattr(result, "trials", None) or [])
    feature_sets = named_feature_sets(bundle.feature_columns, deep_search=True)
    resolved = _resolve_candidates(trials, feature_sets)
    if len(resolved) < 3:
        return {
            "method_version": METHOD_VERSION,
            "passed": False,
            "verdict": "PBO_INSUFFICIENT_CANDIDATE_STRATEGIES",
            "candidate_strategies": len(resolved),
            "oos_used": False,
            "holdout_used": False,
            "automatic_promotion": False,
            "advisory_only": True,
            "trade_authorization": False,
            "order_execution_allowed": False,
        }
    if len(resolved) > config.max_candidate_strategies:
        return {
            "method_version": METHOD_VERSION,
            "passed": False,
            "verdict": "PBO_CANDIDATE_MATRIX_TOO_LARGE_REQUIRES_RESEARCH_REVIEW",
            "candidate_strategies": len(resolved),
            "maximum_candidate_strategies": config.max_candidate_strategies,
            "oos_used": False,
            "holdout_used": False,
            "automatic_promotion": False,
            "advisory_only": True,
            "trade_authorization": False,
            "order_execution_allowed": False,
        }

    split = chronological_split(bundle.frame, chronology=chronology)
    discovery = pd.concat([split["TRAIN"], split["VALIDATION"]], ignore_index=True)
    folds = combinatorial_purged_folds(discovery, config=config.cpcv)
    strategy_ids = [f"C{idx + 1:03d}" for idx in range(len(resolved))]
    ins = np.full((len(folds), len(resolved)), np.nan, dtype=float)
    outs = np.full_like(ins, np.nan)
    errors: list[dict[str, Any]] = []
    model_fit_count = 0

    for fold_index, fold in enumerate(folds):
        train = fold["train"]
        test = fold["test"]
        if set(pd.to_numeric(train["label_net_positive"], errors="coerce").dropna().astype(int).tolist()) != {0, 1}:
            continue
        prediction_cache: dict[str, tuple[np.ndarray, np.ndarray]] = {}
        failed_fit_keys: set[str] = set()
        for strategy_index, candidate in enumerate(resolved):
            fit_key = str(candidate["fit_key"])
            if fit_key in failed_fit_keys:
                continue
            if fit_key not in prediction_cache:
                try:
                    model = fit_model(
                        train,
                        feature_columns=candidate["columns"],
                        spec=candidate["spec"],
                        random_state=config.random_state,
                    )
                    train_prob = predict_positive_probability(
                        model, train, feature_columns=candidate["columns"]
                    )
                    test_prob = predict_positive_probability(
                        model, test, feature_columns=candidate["columns"]
                    )
                    prediction_cache[fit_key] = (train_prob, test_prob)
                    model_fit_count += 1
                except Exception as exc:
                    failed_fit_keys.add(fit_key)
                    errors.append({
                        "fold": fold_index + 1,
                        "fit_key": fit_key,
                        "error": f"{type(exc).__name__}:{str(exc)[:180]}",
                    })
                    continue
            train_prob, test_prob = prediction_cache[fit_key]
            threshold = float(candidate["threshold"])
            ins[fold_index, strategy_index] = _strategy_score(
                train, train_prob, threshold, config.min_selected_trades
            )
            outs[fold_index, strategy_index] = _strategy_score(
                test, test_prob, threshold, config.min_selected_trades
            )

    pbo = probability_backtest_overfitting(ins, outs, strategy_ids=strategy_ids)
    return {
        "method_version": METHOD_VERSION,
        **pbo,
        "verdict": pbo.get("verdict"),
        "config": asdict(config),
        "candidate_strategies": len(resolved),
        "distinct_model_fits_per_all_folds": model_fit_count,
        "candidates": [
            {
                "strategy_id": strategy_ids[idx],
                "feature_set": item["feature_set"],
                "family": item["spec"].family,
                "params": dict(item["spec"].params),
                "threshold": item["threshold"],
            }
            for idx, item in enumerate(resolved)
        ],
        "discovery_rows": int(len(discovery)),
        "cpcv_folds": len(folds),
        "evaluation_errors": errors,
        "selection_bias_data": ["TRAIN", "VALIDATION"],
        "oos_used": False,
        "holdout_used": False,
        "whole_discovery_period_not_used_to_preselect_pbo_strategies": True,
        "same_candidate_set_ranked_in_each_fold": True,
        "automatic_promotion": False,
        "advisory_only": True,
        "trade_authorization": False,
        "order_execution_allowed": False,
    }
