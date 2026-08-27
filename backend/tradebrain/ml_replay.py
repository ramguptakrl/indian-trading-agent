"""Leakage-safe historical market replay for Trade Brain v0.14 ML.

This module is the machine-learning equivalent of TradingView candle replay. A replay
walks forward through historical BSE sessions and permits the model to use only evidence
and labels that would genuinely have existed at the historical decision time.

Important boundaries:
- intraday models are frozen for the entire market session;
- labels enter training only after ``label_end`` has actually matured;
- blind daily refitting is NOT the default and requires explicit research opt-in;
- news is disabled in the V1 feature replay, but a strict point-in-time news filter is
  provided for future challenger work;
- replay cannot promote models, change protected policy, or place broker orders.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import pandas as pd

from backend.tradebrain.ml_features import FeatureBundle
from backend.tradebrain.ml_models import (
    DEFAULT_RANDOM_STATE,
    MODEL_FAMILIES,
    ModelSpec,
    fit_model,
    predict_positive_probability,
)
from backend.tradebrain.ml_validation import trading_metrics

METHOD_VERSION = "BSE_ML_PREQUENTIAL_REPLAY_V1"
IST = "Asia/Kolkata"
INTRADAY_TASKS = {"BSE_INTRADAY_LONG", "BSE_INTRADAY_SHORT"}
SWING_TASK = "BSE_SWING_LONG_MTF"
SUPPORTED_TASKS = {*INTRADAY_TASKS, SWING_TASK}


@dataclass(frozen=True)
class ReplayModelSpec:
    task: str
    family: str
    params: dict[str, Any]
    feature_columns: tuple[str, ...]
    threshold: float
    random_state: int = DEFAULT_RANDOM_STATE

    def validate(self) -> None:
        if self.task not in SUPPORTED_TASKS:
            raise ValueError(f"Unsupported replay task: {self.task}")
        if self.family not in MODEL_FAMILIES:
            raise ValueError(f"Unsupported replay model family: {self.family}")
        if not self.feature_columns:
            raise ValueError("Replay model requires at least one feature")
        if not 0.0 < float(self.threshold) < 1.0:
            raise ValueError("Replay threshold must be in (0, 1)")

    def model_spec(self) -> ModelSpec:
        self.validate()
        return ModelSpec(self.family, dict(self.params))


@dataclass(frozen=True)
class ReplayConfig:
    start: str
    end: str
    min_train_rows: int = 100
    retrain_every_sessions: int = 0
    allow_daily_refit_research: bool = False
    news_enabled: bool = False

    def validate(self) -> None:
        start = _ts(self.start)
        end = _ts(self.end)
        if not start < end:
            raise ValueError("Replay start must be before replay end")
        if int(self.min_train_rows) < 20:
            raise ValueError("Replay requires at least 20 chronological training rows")
        if int(self.retrain_every_sessions) < 0:
            raise ValueError("retrain_every_sessions must be >= 0")
        if self.retrain_every_sessions == 1 and not self.allow_daily_refit_research:
            raise ValueError(
                "Blind daily refit is disabled by default; set allow_daily_refit_research=True only for an explicit research experiment"
            )
        if self.news_enabled:
            raise ValueError(
                "News is not attached to the V1 replay feature matrix. Use eligible_news_as_of() to build a separately audited challenger dataset."
            )


def _ts(value: str | pd.Timestamp) -> pd.Timestamp:
    parsed = pd.Timestamp(value)
    if parsed.tzinfo is None:
        return parsed.tz_localize("UTC")
    return parsed.tz_convert("UTC")


def matured_training_frame(frame: pd.DataFrame, *, decision_at: str | pd.Timestamp) -> pd.DataFrame:
    """Return only rows whose feature and outcome were knowable at ``decision_at``."""
    required = {"ts_close", "label_end", "label_net_positive"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"Replay frame missing maturity columns: {sorted(missing)}")
    cutoff = _ts(decision_at)
    feature_time = pd.to_datetime(frame["ts_close"], utc=True)
    label_end = pd.to_datetime(frame["label_end"], utc=True)
    mask = (feature_time < cutoff) & (label_end <= cutoff)
    return frame.loc[mask].copy().sort_values("ts_close", kind="stable").reset_index(drop=True)


def eligible_news_as_of(news: pd.DataFrame, *, decision_at: str | pd.Timestamp) -> pd.DataFrame:
    """Strictly filter historical news to what was provably public by the decision time.

    Required columns are ``published_at``, ``available_at`` and ``timestamp_verified``.
    Missing/unverified timestamps are excluded rather than inferred. Both timestamps must
    be at-or-before the historical decision time, which prevents later articles, edits or
    reposts from leaking into an earlier prediction.
    """
    required = {"published_at", "available_at", "timestamp_verified"}
    missing = required - set(news.columns)
    if missing:
        raise ValueError(f"Historical news missing point-in-time columns: {sorted(missing)}")
    cutoff = _ts(decision_at)
    published = pd.to_datetime(news["published_at"], utc=True, errors="coerce")
    available = pd.to_datetime(news["available_at"], utc=True, errors="coerce")
    verified = news["timestamp_verified"].fillna(False).astype(bool)
    mask = verified & published.notna() & available.notna() & (published <= cutoff) & (available <= cutoff)
    return news.loc[mask].copy().reset_index(drop=True)


def _stressed_frame(frame: pd.DataFrame, multiplier: float) -> pd.DataFrame:
    work = frame.copy()
    gross = pd.to_numeric(work["label_gross_return_pct"], errors="coerce").astype(float)
    net = pd.to_numeric(work["label_net_return_pct"], errors="coerce").astype(float)
    base_friction = gross - net
    work["label_net_return_pct"] = gross - base_friction * float(multiplier)
    return work


def _session_keys(frame: pd.DataFrame, task: str) -> pd.Series:
    if task in INTRADAY_TASKS:
        local = pd.to_datetime(frame["ts_open"], utc=True).dt.tz_convert(IST)
        return local.dt.date.astype(str)
    return pd.to_datetime(frame["ts_close"], utc=True).map(lambda value: value.isoformat())


def _session_decision_time(session: pd.DataFrame, task: str) -> pd.Timestamp:
    if task in INTRADAY_TASKS:
        return pd.to_datetime(session["ts_open"], utc=True).min()
    return pd.to_datetime(session["ts_close"], utc=True).max()


def _should_refit(*, model_exists: bool, session_index: int, every: int) -> bool:
    if not model_exists:
        return True
    if every <= 0:
        return False
    return session_index % every == 0


def prequential_replay(
    bundle: FeatureBundle,
    *,
    model_spec: ReplayModelSpec,
    config: ReplayConfig,
) -> dict[str, Any]:
    """Replay historical sessions with strict point-in-time training boundaries."""
    model_spec.validate()
    config.validate()
    task = str(bundle.metadata.get("task") or model_spec.task)
    if task != model_spec.task:
        raise ValueError("Replay bundle task does not match ReplayModelSpec task")
    if task not in SUPPORTED_TASKS:
        raise ValueError(f"Unsupported replay task: {task}")

    frame = bundle.frame.copy().sort_values("ts_close", kind="stable").reset_index(drop=True)
    required = {
        "ts_open", "ts_close", "label_end", "label_net_positive",
        "label_net_return_pct", "label_gross_return_pct",
    }
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"Replay dataset missing columns: {sorted(missing)}")
    missing_features = [name for name in model_spec.feature_columns if name not in frame.columns]
    if missing_features:
        raise ValueError(f"Replay dataset missing model features: {missing_features[:12]}")

    times = pd.to_datetime(frame["ts_close"], utc=True)
    replay_mask = (times >= _ts(config.start)) & (times < _ts(config.end))
    evaluation = frame.loc[replay_mask].copy()
    if evaluation.empty:
        return {
            "status": "INSUFFICIENT_REPLAY_DATA", "method_version": METHOD_VERSION,
            "task": task, "predictions": [], "model_fit_events": [], "news_used": False,
            "advisory_only": True, "trade_authorization": False, "order_execution_allowed": False,
        }

    evaluation["_replay_session"] = _session_keys(evaluation, task).to_numpy()
    fitted = None
    fit_events: list[dict[str, Any]] = []
    predictions: list[dict[str, Any]] = []
    evaluated_rows: list[pd.DataFrame] = []
    evaluated_probabilities: list[float] = []
    source_spec = model_spec.model_spec()

    for session_index, (session_key, session) in enumerate(evaluation.groupby("_replay_session", sort=True)):
        session = session.sort_values("ts_close", kind="stable")
        decision_at = _session_decision_time(session, task)
        if _should_refit(model_exists=fitted is not None, session_index=session_index, every=int(config.retrain_every_sessions)):
            training = matured_training_frame(frame, decision_at=decision_at)
            if len(training) < int(config.min_train_rows):
                continue
            classes = set(pd.to_numeric(training["label_net_positive"], errors="coerce").dropna().astype(int))
            if classes != {0, 1}:
                continue
            fitted = fit_model(training, feature_columns=model_spec.feature_columns, spec=source_spec, random_state=int(model_spec.random_state))
            max_label_end = pd.to_datetime(training["label_end"], utc=True).max()
            fit_events.append({
                "session": str(session_key), "fit_at": decision_at.isoformat(),
                "training_rows": int(len(training)), "training_max_label_end": max_label_end.isoformat(),
                "future_label_used": bool(max_label_end > decision_at),
            })

        if fitted is None:
            continue
        probabilities = predict_positive_probability(fitted, session, feature_columns=model_spec.feature_columns)
        for row_index, probability in zip(session.index.tolist(), probabilities.tolist()):
            row = evaluation.loc[[row_index]].drop(columns=["_replay_session"])
            source = row.iloc[0]
            predictions.append({
                "session": str(session_key), "decision_at": decision_at.isoformat(),
                "ts_close": pd.Timestamp(source["ts_close"]).isoformat(),
                "label_end": pd.Timestamp(source["label_end"]).isoformat(),
                "probability_net_positive": float(probability),
                "selected": bool(float(probability) >= float(model_spec.threshold)),
            })
            evaluated_rows.append(row)
            evaluated_probabilities.append(float(probability))

    if not evaluated_rows:
        return {
            "status": "INSUFFICIENT_TRAINING_HISTORY", "method_version": METHOD_VERSION,
            "task": task, "predictions": [], "model_fit_events": fit_events, "news_used": False,
            "advisory_only": True, "trade_authorization": False, "order_execution_allowed": False,
        }

    scored = pd.concat(evaluated_rows, ignore_index=True)
    probabilities = np.asarray(evaluated_probabilities, dtype=float)
    normal = trading_metrics(scored, probabilities, threshold=float(model_spec.threshold), slippage_bps=0.0, friction_multiplier=1.0)
    stress_15x = trading_metrics(_stressed_frame(scored, 1.5), probabilities, threshold=float(model_spec.threshold), slippage_bps=0.0, friction_multiplier=1.0)
    stress_20x = trading_metrics(_stressed_frame(scored, 2.0), probabilities, threshold=float(model_spec.threshold), slippage_bps=0.0, friction_multiplier=1.0)

    return {
        "status": "SUCCESS", "method_version": METHOD_VERSION, "task": task,
        "model_spec": asdict(model_spec), "replay_config": asdict(config),
        "rows_scored": int(len(scored)), "model_fit_events": fit_events, "predictions": predictions,
        "metrics": normal, "stress_15x": stress_15x, "stress_20x": stress_20x,
        "point_in_time_labels_only": True,
        "intraday_model_frozen_within_session": task in INTRADAY_TASKS,
        "blind_daily_refit_default": False, "news_used": False,
        "news_policy": "DISABLED_BY_DEFAULT_STRICT_AS_OF_FILTER_REQUIRED_FOR_CHALLENGER",
        "automatic_model_promotion": False, "automatic_policy_change": False,
        "advisory_only": True, "trade_authorization": False, "order_execution_allowed": False,
    }
