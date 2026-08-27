"""CPCV strategy-matrix Probability of Backtest Overfitting for Trade Brain v0.14 ML.

DSR penalizes all raw candidate configurations. PBO operates on one validation-selected
representative per broader hypothesis family (architecture + feature set + model family),
which avoids treating correlated parameter/threshold sweeps as independent strategies.

The PBO matrix is built only from TRAIN + VALIDATION discovery data. OOS and holdout are not
used to estimate researcher selection bias.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import pandas as pd

from backend.tradebrain.ml_cpcv import CPCVConfig, combinatorial_purged_folds
from backend.tradebrain.ml_features import FeatureBundle
from backend.tradebrain.ml_models import DEFAULT_RANDOM_STATE, ModelSpec, fit_model, predict_positive_probability
from backend.tradebrain.ml_multiple_testing import probability_backtest_overfitting
from backend.tradebrain.ml_optimizer import named_feature_sets
from backend.tradebrain.ml_validation import DEFAULT_CHRONOLOGY, Chronology, chronological_split, trading_metrics

METHOD_VERSION = "BSE_ML_PBO_V1"


@dataclass(frozen=True)
class PBOConfig:
    max_hypothesis_strategies: int = 40
    min_selected_trades: int = 10
    random_state: int = DEFAULT_RANDOM_STATE
    cpcv: CPCVConfig = CPCVConfig()

    def validate(self) -> None:
        if self.max_hypothesis_strategies < 3:
            raise ValueError("max_hypothesis_strategies must be >= 3")
        if self.min_selected_trades < 1:
            raise ValueError("min_selected_trades must be positive")
        self.cpcv.validate()


def _finite_score(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return float("-inf")
    return number if np.isfinite(number) else float("-inf")


def _hypothesis_key(trial: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(trial.get("variant") or trial.get("architecture") or "BASELINE"),
        str(trial.get("feature_set") or "UNKNOWN"),
        str(trial.get("family") or "UNKNOWN"),
    )


def hypothesis_representatives(trials: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Choose one representative per hypothesis family using validation evidence only."""
    chosen: dict[tuple[str, str, str], dict[str, Any]] = {}
    for trial in trials:
        if not isinstance(trial.get("validation"), dict):
            continue
        key = _hypothesis_key(trial)
        score = _finite_score(trial.get("robustness_score"))
        existing = chosen.get(key)
        if existing is None or score > _finite_score(existing.get("robustness_score")):
            chosen[key] = trial
    return [chosen[key] for key in sorted(chosen)]


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


def evaluate_pbo_from_optimizer(
    bundle: FeatureBundle,
    result: Any,
    *,
    chronology: Chronology = DEFAULT_CHRONOLOGY,
    config: PBOConfig = PBOConfig(),
) -> dict[str, Any]:
    """Build discovery-only CPCV IS/OOS matrices and estimate PBO."""
    config.validate()
    trials = list(getattr(result, "trials", None) or [])
    representatives = hypothesis_representatives(trials)
    if len(representatives) < 3:
        return {
            "method_version": METHOD_VERSION,
            "passed": False,
            "verdict": "PBO_INSUFFICIENT_HYPOTHESIS_FAMILIES",
            "hypothesis_strategies": len(representatives),
            "oos_used": False,
            "holdout_used": False,
            "automatic_promotion": False,
            "advisory_only": True,
            "trade_authorization": False,
            "order_execution_allowed": False,
        }
    if len(representatives) > config.max_hypothesis_strategies:
        return {
            "method_version": METHOD_VERSION,
            "passed": False,
            "verdict": "PBO_HYPOTHESIS_MATRIX_TOO_LARGE_REQUIRES_RESEARCH_REVIEW",
            "hypothesis_strategies": len(representatives),
            "maximum_hypothesis_strategies": config.max_hypothesis_strategies,
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
    feature_sets = named_feature_sets(bundle.feature_columns, deep_search=True)

    strategy_ids: list[str] = []
    resolved: list[tuple[dict[str, Any], tuple[str, ...], ModelSpec, float]] = []
    for index, trial in enumerate(representatives):
        feature_set = str(trial.get("feature_set") or "")
        columns = feature_sets.get(feature_set)
        if not columns:
            continue
        try:
            threshold = float(trial.get("threshold"))
            spec = ModelSpec(str(trial.get("family")), dict(trial.get("params") or {}))
            spec.validate()
        except Exception:
            continue
        strategy_id = f"H{index + 1}:{_hypothesis_key(trial)[1]}:{spec.family}"
        strategy_ids.append(strategy_id)
        resolved.append((trial, tuple(columns), spec, threshold))

    if len(resolved) < 3:
        return {
            "method_version": METHOD_VERSION,
            "passed": False,
            "verdict": "PBO_INSUFFICIENT_RESOLVABLE_STRATEGIES",
            "hypothesis_strategies": len(resolved),
            "oos_used": False,
            "holdout_used": False,
            "automatic_promotion": False,
            "advisory_only": True,
            "trade_authorization": False,
            "order_execution_allowed": False,
        }

    ins = np.full((len(folds), len(resolved)), np.nan, dtype=float)
    outs = np.full_like(ins, np.nan)
    errors: list[dict[str, Any]] = []
    for fold_index, fold in enumerate(folds):
        train = fold["train"]
        test = fold["test"]
        for strategy_index, (_, columns, spec, threshold) in enumerate(resolved):
            try:
                if set(pd.to_numeric(train["label_net_positive"], errors="coerce").dropna().astype(int).tolist()) != {0, 1}:
                    continue
                model = fit_model(
                    train,
                    feature_columns=columns,
                    spec=spec,
                    random_state=config.random_state,
                )
                train_prob = predict_positive_probability(model, train, feature_columns=columns)
                test_prob = predict_positive_probability(model, test, feature_columns=columns)
                ins[fold_index, strategy_index] = _strategy_score(
                    train, train_prob, threshold, config.min_selected_trades
                )
                outs[fold_index, strategy_index] = _strategy_score(
                    test, test_prob, threshold, config.min_selected_trades
                )
            except Exception as exc:
                errors.append({
                    "fold": fold_index + 1,
                    "strategy": strategy_ids[strategy_index],
                    "error": f"{type(exc).__name__}:{str(exc)[:180]}",
                })

    pbo = probability_backtest_overfitting(ins, outs, strategy_ids=strategy_ids)
    return {
        "method_version": METHOD_VERSION,
        **pbo,
        "verdict": pbo.get("verdict"),
        "config": asdict(config),
        "hypothesis_representatives": [
            {
                "strategy_id": strategy_ids[idx],
                "hypothesis": _hypothesis_key(item[0]),
                "params": dict(item[2].params),
                "threshold": item[3],
            }
            for idx, item in enumerate(resolved)
        ],
        "discovery_rows": int(len(discovery)),
        "cpcv_folds": len(folds),
        "evaluation_errors": errors,
        "selection_bias_data": ["TRAIN", "VALIDATION"],
        "oos_used": False,
        "holdout_used": False,
        "raw_parameter_trials_handled_by_dsr": True,
        "hypothesis_families_handled_by_pbo": True,
        "automatic_promotion": False,
        "advisory_only": True,
        "trade_authorization": False,
        "order_execution_allowed": False,
    }
