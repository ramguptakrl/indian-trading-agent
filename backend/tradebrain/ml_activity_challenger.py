"""Governed audited-1m activity-bar challenger for Trade Brain v0.14.

The challenger is intentionally conservative:
- features are built from threshold-complete activity bars derived from audited native 1m OHLCV;
- activity targets are caller supplied/predeclared, never auto-calibrated here;
- each feature row is timestamped at the completed activity bar close;
- trade entry and future path are evaluated on the raw audited 1m series, not on a count of
  irregular activity bars;
- the maximum holding period is a fixed wall-clock horizon (default 360 minutes) capped by the
  intraday exit boundary;
- same-1m-bar stop/target ambiguity is rejected rather than guessed;
- the existing ledger/DSR/PBO/CPCV/bootstrap/friction/kill governance is reused;
- historical OOS is explicitly treated as reused research evidence and never as clean final
  proof for this newly designed architecture;
- no registry/champion/advisory integration or broker execution occurs here.

Historical 2026 holdout data may exist in the audited store, but it is never used for feature,
activity-target, model, threshold, or architecture selection. The configured chronology keeps
HOLDOUT outside optimizer prediction; future prospective shadow sessions remain the clean final
proof layer.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from backend.tradebrain.equity_costs import COST_PROFILE_KEY, calculate_equity_trade_costs
from backend.tradebrain.market_data_store import query_bars
from backend.tradebrain.ml_activity_bars import (
    ACTIVITY_KINDS,
    ARCHITECTURES,
    SOURCE_INTERVAL,
    build_activity_bars,
    completed_activity_bars,
)
from backend.tradebrain.ml_bootstrap_confidence import (
    bootstrap_promotion_verdict,
    selected_returns_from_probabilities,
    stationary_bootstrap_confidence,
)
from backend.tradebrain.ml_cpcv import evaluate_cpcv_candidate
from backend.tradebrain.ml_features import FeatureBundle
from backend.tradebrain.ml_kill_criteria import evaluate_research_kill_criteria
from backend.tradebrain.ml_labels import TASK_INTRADAY_LONG, TASK_INTRADAY_SHORT
from backend.tradebrain.ml_models import predict_positive_probability
from backend.tradebrain.ml_optimizer import OptimizerConfig, optimize_labeled_dataset, serializable_result
from backend.tradebrain.ml_pbo import evaluate_pbo_from_optimizer
from backend.tradebrain.ml_promotion import evaluate_historical_promotion
from backend.tradebrain.ml_research_ledger import (
    record_selected_dsr,
    record_trials,
    research_ledger_summary,
)
from backend.tradebrain.ml_selection_bias import evaluate_dsr_from_optimizer, multiple_testing_clearance
from backend.tradebrain.ml_validation import DEFAULT_CHRONOLOGY, Chronology, chronological_split

METHOD_VERSION = "BSE_ML_ACTIVITY_CHALLENGER_V1"
FEATURE_METHOD_VERSION = "BSE_ML_ACTIVITY_FEATURES_V1"
LABEL_METHOD_VERSION = "BSE_ML_ACTIVITY_LABELS_V1"
IST = ZoneInfo("Asia/Kolkata")
INTRADAY_TASKS = {TASK_INTRADAY_LONG, TASK_INTRADAY_SHORT}
SESSION_OPEN_MINUTE = 9 * 60 + 15
ENTRY_CUTOFF_MINUTE = 15 * 60 + 10
FUTURE_BAR_CUTOFF_MINUTE = 15 * 60 + 15
DEFAULT_RAW_QUERY_LIMIT = 1_500_000


@dataclass(frozen=True)
class ActivityLabelConfig:
    stop_atr: float = 1.0
    target_atr: float = 1.5
    max_holding_minutes: int = 360
    atr_period: int = 14
    quantity: int = 100
    slippage_bps: float = 5.0

    def validate(self) -> None:
        if self.stop_atr <= 0.0 or self.target_atr <= 0.0:
            raise ValueError("Activity stop/target ATR multipliers must be positive")
        if self.max_holding_minutes < 1:
            raise ValueError("Activity max_holding_minutes must be positive")
        if self.atr_period < 2:
            raise ValueError("Activity atr_period must be >= 2")
        if self.quantity < 1:
            raise ValueError("Activity quantity must be positive")
        if self.slippage_bps < 0.0:
            raise ValueError("Activity slippage_bps cannot be negative")


DEFAULT_LABEL_CONFIG = ActivityLabelConfig()


@dataclass(frozen=True)
class ActivityFeatureConfig:
    relative_window: int = 20
    efficiency_windows: tuple[int, ...] = (5, 10)

    def validate(self) -> None:
        if self.relative_window < 2:
            raise ValueError("Activity relative_window must be >= 2")
        if not self.efficiency_windows or any(int(value) < 2 for value in self.efficiency_windows):
            raise ValueError("Activity efficiency windows must all be >= 2")


DEFAULT_FEATURE_CONFIG = ActivityFeatureConfig()


def _wilder(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(alpha=1.0 / float(period), adjust=False, min_periods=period).mean()


def _true_range(frame: pd.DataFrame) -> pd.Series:
    previous_close = frame["close"].shift(1)
    return pd.concat(
        [
            (frame["high"] - frame["low"]).abs(),
            (frame["high"] - previous_close).abs(),
            (frame["low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)


def _directional_efficiency(close: pd.Series, window: int) -> pd.Series:
    numerator = (close - close.shift(window)).abs()
    denominator = close.diff().abs().rolling(window, min_periods=window).sum()
    return numerator / denominator.replace(0.0, np.nan)


def _raw_frame(rows: pd.DataFrame | Iterable[dict[str, Any]]) -> pd.DataFrame:
    frame = rows.copy() if isinstance(rows, pd.DataFrame) else pd.DataFrame(list(rows))
    required = {"ts_open", "ts_close", "open", "high", "low", "close", "volume"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"Activity challenger raw source is missing columns: {missing}")
    if frame.empty:
        return frame
    frame = frame.copy()
    frame["ts_open"] = pd.to_datetime(frame["ts_open"], utc=True, errors="raise")
    frame["ts_close"] = pd.to_datetime(frame["ts_close"], utc=True, errors="raise")
    frame = frame.sort_values("ts_open", kind="stable").reset_index(drop=True)
    for column in ("open", "high", "low", "close", "volume"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce").astype(float)
    frame["era_id"] = frame.get("era_id", pd.Series([None] * len(frame), dtype="object"))
    frame["era_key"] = frame["era_id"].fillna("__UNASSIGNED_ERA__").astype(str)
    local = frame["ts_open"].dt.tz_convert(IST)
    frame["session_date_ist"] = local.dt.date.astype(str)
    return frame


def _local_minute(timestamp: pd.Timestamp) -> int:
    local = timestamp.tz_convert(IST)
    return int(local.hour * 60 + local.minute)


def _same_session(left: pd.Timestamp, right: pd.Timestamp) -> bool:
    return left.tz_convert(IST).date() == right.tz_convert(IST).date()


def _direction(task: str) -> str:
    return "SHORT" if task == TASK_INTRADAY_SHORT else "LONG"


def _thresholds(entry: float, atr: float, task: str, config: ActivityLabelConfig) -> tuple[float, float]:
    if task == TASK_INTRADAY_SHORT:
        return entry + atr * config.stop_atr, entry - atr * config.target_atr
    return entry - atr * config.stop_atr, entry + atr * config.target_atr


def _hits(bar: pd.Series, *, direction: str, stop: float, target: float) -> tuple[bool, bool]:
    if direction == "LONG":
        return float(bar["low"]) <= stop, float(bar["high"]) >= target
    return float(bar["high"]) >= stop, float(bar["low"]) <= target


def _excursions(future: pd.DataFrame, *, direction: str, entry: float) -> tuple[float, float]:
    if future.empty or entry <= 0.0:
        return 0.0, 0.0
    if direction == "LONG":
        mae = max(0.0, (entry - float(future["low"].min())) / entry * 100.0)
        mfe = max(0.0, (float(future["high"].max()) - entry) / entry * 100.0)
    else:
        mae = max(0.0, (float(future["high"].max()) - entry) / entry * 100.0)
        mfe = max(0.0, (entry - float(future["low"].min())) / entry * 100.0)
    return mae, mfe


def _dataset_hash(frame: pd.DataFrame, metadata: dict[str, Any]) -> str:
    columns = [
        column
        for column in (
            "ts_close",
            "label_end",
            "label_net_positive",
            "label_net_return_pct",
            "activity_bar_id",
        )
        if column in frame.columns
    ]
    records = frame.loc[:, columns].copy() if columns else pd.DataFrame()
    for column in records.columns:
        if pd.api.types.is_datetime64_any_dtype(records[column]):
            records[column] = records[column].map(lambda value: pd.Timestamp(value).isoformat())
    payload = {
        "rows": records.to_dict(orient="records"),
        "metadata": metadata,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _feature_frame(
    completed: pd.DataFrame,
    *,
    label_config: ActivityLabelConfig,
    feature_config: ActivityFeatureConfig,
) -> tuple[pd.DataFrame, tuple[str, ...]]:
    frame = completed.copy().sort_values("ts_close", kind="stable").reset_index(drop=True)
    if frame.empty:
        return frame, ()
    frame["ts_open"] = pd.to_datetime(frame["ts_open"], utc=True)
    frame["ts_close"] = pd.to_datetime(frame["ts_close"], utc=True)
    frame["era_key"] = frame["era_id"].fillna("__UNASSIGNED_ERA__").astype(str)
    frame["return_1"] = frame["close"].pct_change() * 100.0
    candle_range = (frame["high"] - frame["low"]).replace(0.0, np.nan)
    frame["candle_range_pct"] = candle_range / frame["close"].replace(0.0, np.nan) * 100.0
    frame["candle_body_pct_range"] = (frame["close"] - frame["open"]) / candle_range
    frame["upper_wick_pct_range"] = (
        frame["high"] - np.maximum(frame["open"], frame["close"])
    ) / candle_range
    frame["lower_wick_pct_range"] = (
        np.minimum(frame["open"], frame["close"]) - frame["low"]
    ) / candle_range
    frame["activity_observed_pct_target"] = (
        frame["observed_activity"] / frame["activity_target"].replace(0.0, np.nan) * 100.0
    )
    frame["activity_overshoot_pct_target"] = (
        frame["activity_overshoot"] / frame["activity_target"].replace(0.0, np.nan) * 100.0
    )
    frame["activity_duration_minutes"] = (
        (frame["ts_close"] - frame["ts_open"]).dt.total_seconds() / 60.0
    )
    frame["activity_rate_per_minute"] = (
        frame["observed_activity"] / frame["activity_duration_minutes"].replace(0.0, np.nan)
    )
    frame["volume_per_minute"] = frame["volume"] / frame["activity_duration_minutes"].replace(0.0, np.nan)

    local_close = frame["ts_close"].dt.tz_convert(IST)
    close_minute = local_close.dt.hour * 60 + local_close.dt.minute
    frame["minutes_from_open"] = (close_minute - SESSION_OPEN_MINUTE).astype(float)
    frame["minutes_to_close"] = ((15 * 60 + 30) - close_minute).astype(float)
    frame["session_bar_index"] = frame.groupby("session_date_ist", sort=False).cumcount().astype(float)

    atr_values = pd.Series(np.nan, index=frame.index, dtype=float)
    relative_volume = pd.Series(np.nan, index=frame.index, dtype=float)
    duration_relative = pd.Series(np.nan, index=frame.index, dtype=float)
    rate_relative = pd.Series(np.nan, index=frame.index, dtype=float)
    efficiencies = {
        int(window): pd.Series(np.nan, index=frame.index, dtype=float)
        for window in feature_config.efficiency_windows
    }

    # ATR is reset only when raw-price era changes so overnight price gaps may remain visible;
    # session-normalized activity/duration statistics reset each day.
    for _, indices in frame.groupby("era_key", sort=False).groups.items():
        index = pd.Index(indices)
        group = frame.loc[index]
        atr_values.loc[index] = _wilder(_true_range(group), label_config.atr_period).to_numpy()

    for _, indices in frame.groupby("session_date_ist", sort=False).groups.items():
        index = pd.Index(indices)
        group = frame.loc[index]
        median_volume = group["volume"].rolling(feature_config.relative_window, min_periods=5).median()
        median_duration = group["activity_duration_minutes"].rolling(
            feature_config.relative_window, min_periods=5
        ).median()
        median_rate = group["activity_rate_per_minute"].rolling(
            feature_config.relative_window, min_periods=5
        ).median()
        relative_volume.loc[index] = (
            group["volume"] / median_volume.replace(0.0, np.nan)
        ).to_numpy()
        duration_relative.loc[index] = (
            group["activity_duration_minutes"] / median_duration.replace(0.0, np.nan)
        ).to_numpy()
        rate_relative.loc[index] = (
            group["activity_rate_per_minute"] / median_rate.replace(0.0, np.nan)
        ).to_numpy()
        for window in efficiencies:
            efficiencies[window].loc[index] = _directional_efficiency(group["close"], window).to_numpy()

    frame["atr_14"] = atr_values
    frame["natr_14_pct"] = frame["atr_14"] / frame["close"].replace(0.0, np.nan) * 100.0
    frame["relative_volume_20"] = relative_volume
    frame["duration_relative_20"] = duration_relative
    frame["activity_rate_relative_20"] = rate_relative
    for window, values in efficiencies.items():
        frame[f"directional_efficiency_{window}"] = values

    feature_columns = [
        "return_1",
        "candle_range_pct",
        "candle_body_pct_range",
        "upper_wick_pct_range",
        "lower_wick_pct_range",
        "activity_observed_pct_target",
        "activity_overshoot_pct_target",
        "source_minute_count",
        "activity_duration_minutes",
        "activity_rate_per_minute",
        "volume_per_minute",
        "minutes_from_open",
        "minutes_to_close",
        "session_bar_index",
        "atr_14",
        "natr_14_pct",
        "relative_volume_20",
        "duration_relative_20",
        "activity_rate_relative_20",
        *[f"directional_efficiency_{int(window)}" for window in feature_config.efficiency_windows],
    ]
    return frame, tuple(feature_columns)


def _label_feature_row(
    raw: pd.DataFrame,
    *,
    feature_row: pd.Series,
    task: str,
    config: ActivityLabelConfig,
) -> dict[str, Any] | None:
    feature_close = pd.Timestamp(feature_row["ts_close"])
    atr = float(feature_row["atr_14"])
    if not math.isfinite(atr) or atr <= 0.0:
        return None

    opens = raw["ts_open"]
    entry_index = int(opens.searchsorted(feature_close, side="left"))
    if entry_index >= len(raw):
        return None
    next_bar = raw.iloc[entry_index]
    if not _same_session(feature_close, next_bar["ts_open"]):
        return None
    feature_era = str(feature_row.get("era_key") or "__UNASSIGNED_ERA__")
    if str(next_bar["era_key"]) != feature_era:
        return None
    if _local_minute(next_bar["ts_open"]) >= ENTRY_CUTOFF_MINUTE:
        return None

    wall_clock_end = next_bar["ts_open"] + pd.Timedelta(minutes=config.max_holding_minutes)
    future = raw.iloc[entry_index:].copy()
    future = future.loc[
        future["ts_open"].map(lambda value: _same_session(next_bar["ts_open"], value))
    ]
    future = future.loc[future["era_key"] == feature_era]
    future = future.loc[future["ts_open"] < wall_clock_end]
    future = future.loc[future["ts_open"].map(_local_minute) < FUTURE_BAR_CUTOFF_MINUTE]
    if future.empty:
        return None

    direction = _direction(task)
    entry = float(next_bar["open"])
    stop, target = _thresholds(entry, atr, task, config)
    outcome = "TIME_EXIT"
    exit_price = float(future.iloc[-1]["close"])
    exit_bar = future.iloc[-1]
    used_rows: list[pd.Series] = []

    for _, bar in future.iterrows():
        hit_stop, hit_target = _hits(bar, direction=direction, stop=stop, target=target)
        used_rows.append(bar)
        if hit_stop and hit_target:
            return {
                "label_status": "AMBIGUOUS",
                "label_reason": "STOP_AND_TARGET_SAME_RAW_1M_BAR_ORDER_UNKNOWN",
                "label_end": bar["ts_close"],
            }
        if hit_stop:
            outcome = "STOP_FIRST"
            exit_price = stop
            exit_bar = bar
            break
        if hit_target:
            outcome = "TARGET_FIRST"
            exit_price = target
            exit_bar = bar
            break

    observed = pd.DataFrame(used_rows)
    mae, mfe = _excursions(observed, direction=direction, entry=entry)
    costs = calculate_equity_trade_costs(
        mode="INTRADAY",
        exchange="NSE",
        direction=direction,
        entry_price=entry,
        exit_price=exit_price,
        quantity=config.quantity,
        slippage_bps=config.slippage_bps,
    )
    gross_return_pct = (
        (exit_price / entry - 1.0) * 100.0
        if direction == "LONG"
        else (entry / exit_price - 1.0) * 100.0
    )
    return {
        "label_status": "RESOLVED",
        "label_reason": outcome,
        "label_entry_time": next_bar["ts_open"],
        "label_entry_price": entry,
        "label_exit_price": exit_price,
        "label_end": exit_bar["ts_close"],
        "label_stop_price": stop,
        "label_target_price": target,
        "label_atr_at_feature_close": atr,
        "label_net_positive": int(float(costs["net_pnl"]) > 0.0),
        "label_net_pnl": float(costs["net_pnl"]),
        "label_net_return_pct": float(costs["net_return_on_entry_notional_pct"]),
        "label_gross_return_pct": float(gross_return_pct),
        "label_mae_pct": float(mae),
        "label_mfe_pct": float(mfe),
        "label_time_to_event_minutes": (
            exit_bar["ts_close"] - next_bar["ts_open"]
        ).total_seconds() / 60.0,
        "label_holding_bars": int(len(observed)),
        "label_holding_raw_1m_bars": int(len(observed)),
        "label_cost_profile": COST_PROFILE_KEY,
        "label_mtf_profile": None,
        "label_mtf_interest_days": 0,
        "label_mtf_funded_amount": 0.0,
    }


def build_activity_labeled_dataset(
    raw_minutes: pd.DataFrame | Iterable[dict[str, Any]],
    *,
    task: str,
    activity_kind: str,
    activity_target: float,
    label_config: ActivityLabelConfig = DEFAULT_LABEL_CONFIG,
    feature_config: ActivityFeatureConfig = DEFAULT_FEATURE_CONFIG,
) -> FeatureBundle:
    """Build causal activity features and fixed-wall-clock raw-1m labels."""
    if task not in INTRADAY_TASKS:
        raise ValueError("Activity challenger currently supports BSE intraday long/short only")
    normalized_kind = str(activity_kind or "").strip().upper()
    if normalized_kind not in ACTIVITY_KINDS:
        raise ValueError(f"Unsupported activity kind: {activity_kind!r}")
    label_config.validate()
    feature_config.validate()

    activity = build_activity_bars(raw_minutes, kind=normalized_kind, target=activity_target)
    raw = _raw_frame(raw_minutes)
    completed = completed_activity_bars(activity)
    feature_frame, feature_columns = _feature_frame(
        completed,
        label_config=label_config,
        feature_config=feature_config,
    )

    resolved_rows: list[dict[str, Any]] = []
    ambiguous_count = 0
    unlabeled_count = 0
    for _, row in feature_frame.iterrows():
        label = _label_feature_row(raw, feature_row=row, task=task, config=label_config)
        if label is None:
            unlabeled_count += 1
            continue
        if label.get("label_status") != "RESOLVED":
            ambiguous_count += 1
            continue
        merged = row.to_dict()
        merged.update(label)
        resolved_rows.append(merged)

    labeled = pd.DataFrame(resolved_rows)
    if not labeled.empty:
        labeled["ts_close"] = pd.to_datetime(labeled["ts_close"], utc=True)
        labeled["label_end"] = pd.to_datetime(labeled["label_end"], utc=True)
        labeled = labeled.sort_values("ts_close", kind="stable").reset_index(drop=True)

    metadata: dict[str, Any] = {
        "method_version": METHOD_VERSION,
        "feature_method_version": FEATURE_METHOD_VERSION,
        "label_method_version": LABEL_METHOD_VERSION,
        "task": task,
        "architecture": ARCHITECTURES[normalized_kind],
        "activity_kind": normalized_kind,
        "activity_target": float(activity_target),
        "activity_bar_metadata": activity.metadata,
        "raw_source_interval": SOURCE_INTERVAL,
        "raw_source_rows": int(len(raw)),
        "completed_activity_bars": int(len(completed)),
        "resolved_label_rows": int(len(labeled)),
        "ambiguous_raw_1m_labels_excluded": int(ambiguous_count),
        "unlabeled_feature_rows_excluded": int(unlabeled_count),
        "feature_config": asdict(feature_config),
        "label_spec": asdict(label_config),
        "label_scale": "CAUSAL_ACTIVITY_BAR_WILDER_ATR",
        "label_entry_source": "NEXT_AUDITED_RAW_1M_OPEN_AT_OR_AFTER_FEATURE_CLOSE",
        "label_future_path_source": "AUDITED_RAW_1M_ONLY",
        "label_horizon_type": "FIXED_WALL_CLOCK_MINUTES_CAPPED_BY_INTRADAY_EXIT_BOUNDARY",
        "max_holding_minutes": int(label_config.max_holding_minutes),
        "same_raw_1m_stop_target_ambiguity_excluded": True,
        "irregular_activity_bar_count_used_as_holding_horizon": False,
        "activity_target_auto_calibrated": False,
        "activity_target_must_be_predeclared": True,
        "holdout_used_for_activity_target_selection": False,
        "holdout_used_for_feature_selection": False,
        "holdout_used_for_architecture_selection": False,
        "historical_2026_holdout_status": "CONSUMED_NOT_CLEAN_FINAL_PROOF",
        "historical_oos_reused_after_new_activity_architecture_design": True,
        "prospective_shadow_required_for_clean_final_proof": True,
        "tick_sequence_reconstructed": False,
        "intra_minute_sequence_claimed": False,
        "bid_ask_history_claimed": False,
        "spread_history_claimed": False,
        "queue_history_claimed": False,
        "level2_history_claimed": False,
        "automatic_registration": False,
        "automatic_promotion": False,
        "advisory_only": True,
        "trade_authorization": False,
        "order_execution_allowed": False,
    }
    metadata["dataset_snapshot_hash"] = _dataset_hash(labeled, metadata)
    return FeatureBundle(frame=labeled, feature_columns=feature_columns, metadata=metadata)


def load_activity_labeled_dataset(
    series_id: str,
    *,
    task: str,
    activity_kind: str,
    activity_target: float,
    start: str | None = None,
    end: str | None = None,
    as_of: str | None = None,
    limit: int = DEFAULT_RAW_QUERY_LIMIT,
    db_path: str | None = None,
    label_config: ActivityLabelConfig = DEFAULT_LABEL_CONFIG,
    feature_config: ActivityFeatureConfig = DEFAULT_FEATURE_CONFIG,
) -> FeatureBundle:
    rows = query_bars(
        series_id,
        SOURCE_INTERVAL,
        start=start,
        end=end,
        as_of=as_of,
        limit=limit,
        db_path=db_path,
    )
    bundle = build_activity_labeled_dataset(
        rows,
        task=task,
        activity_kind=activity_kind,
        activity_target=activity_target,
        label_config=label_config,
        feature_config=feature_config,
    )
    bundle.metadata.update(
        {
            "series_id": str(series_id),
            "query_start": start,
            "query_end": end,
            "query_as_of": as_of,
            "replay_cutoff_enforced_by_source_query": bool(as_of),
        }
    )
    return bundle


def _exhausted_families(ledger: dict[str, Any], architecture: str) -> tuple[tuple[str, str], ...]:
    blocked: set[tuple[str, str]] = set()
    for row in ledger.get("exhausted_hypothesis_families") or []:
        family = row.get("hypothesis_family") or {}
        if str(family.get("architecture") or "") != str(architecture):
            continue
        feature_set = str(family.get("feature_set") or "").strip()
        model_family = str(family.get("family") or "").strip()
        if feature_set and model_family:
            blocked.add((feature_set, model_family))
    return tuple(sorted(blocked))


def _selection_bias(bundle: FeatureBundle, optimization, ledger: dict[str, Any]) -> dict[str, Any]:
    if not optimization.winner:
        return multiple_testing_clearance(dsr=None, pbo=None)
    dsr = evaluate_dsr_from_optimizer(
        optimization,
        cumulative_candidate_count=int(ledger.get("distinct_candidate_configurations") or 0),
        cumulative_trial_sharpes=ledger.get("validation_trade_sharpes") or [],
    )
    if optimization.status == "OOS_PASS":
        try:
            pbo = evaluate_pbo_from_optimizer(bundle, optimization)
        except Exception as exc:
            pbo = {
                "passed": False,
                "verdict": "PBO_FAILED_SAFE",
                "error": f"{type(exc).__name__}:{str(exc)[:500]}",
                "oos_used": False,
                "holdout_used": False,
                "automatic_promotion": False,
                "advisory_only": True,
                "trade_authorization": False,
                "order_execution_allowed": False,
            }
    else:
        pbo = {
            "passed": False,
            "verdict": "PBO_NOT_RUN_NO_OOS_PASS",
            "oos_used": False,
            "holdout_used": False,
            "automatic_promotion": False,
            "advisory_only": True,
            "trade_authorization": False,
            "order_execution_allowed": False,
        }
    return multiple_testing_clearance(dsr=dsr, pbo=pbo)


def _bootstrap(bundle: FeatureBundle, optimization) -> dict[str, Any]:
    if optimization.status != "OOS_PASS" or not optimization.winner or optimization.model is None:
        return {
            "passed": False,
            "verdict": "BOOTSTRAP_NOT_RUN_NO_OOS_PASS",
            "advisory_only": True,
            "trade_authorization": False,
            "order_execution_allowed": False,
        }
    try:
        oos = chronological_split(bundle.frame, chronology=DEFAULT_CHRONOLOGY)["OOS"]
        probabilities = predict_positive_probability(
            optimization.model,
            oos,
            feature_columns=optimization.feature_columns,
        )
        returns = selected_returns_from_probabilities(
            oos,
            probabilities,
            threshold=float(optimization.winner.get("threshold")),
            friction_multiplier=2.0,
        )
        return bootstrap_promotion_verdict(stationary_bootstrap_confidence(returns))
    except Exception as exc:
        return {
            "passed": False,
            "verdict": "BOOTSTRAP_FAILED_SAFE",
            "error": f"{type(exc).__name__}:{str(exc)[:500]}",
            "advisory_only": True,
            "trade_authorization": False,
            "order_execution_allowed": False,
        }


def _cpcv(bundle: FeatureBundle, optimization, chronology: Chronology) -> dict[str, Any]:
    if optimization.status != "OOS_PASS" or not optimization.winner:
        return {
            "passed": False,
            "verdict": "CPCV_NOT_RUN_NO_OOS_PASS",
            "used_for_hyperparameter_selection": False,
            "automatic_promotion": False,
            "advisory_only": True,
            "trade_authorization": False,
            "order_execution_allowed": False,
        }
    try:
        cutoff = pd.Timestamp(chronology.holdout_start)
        pre_holdout = bundle.frame.loc[
            pd.to_datetime(bundle.frame["ts_close"], utc=True) < cutoff
        ].copy()
        return evaluate_cpcv_candidate(
            pre_holdout,
            feature_columns=optimization.feature_columns,
            family=str(optimization.winner.get("family")),
            params=dict(optimization.winner.get("params") or {}),
            threshold=float(optimization.winner.get("threshold")),
        )
    except Exception as exc:
        return {
            "passed": False,
            "verdict": "CPCV_FAILED_SAFE",
            "error": f"{type(exc).__name__}:{str(exc)[:500]}",
            "used_for_hyperparameter_selection": False,
            "automatic_promotion": False,
            "advisory_only": True,
            "trade_authorization": False,
            "order_execution_allowed": False,
        }


def run_activity_challenger(
    series_id: str,
    *,
    task: str,
    activity_kind: str,
    activity_target: float,
    start: str | None = None,
    end: str | None = None,
    as_of: str | None = None,
    chronology: Chronology = DEFAULT_CHRONOLOGY,
    optimizer_config: OptimizerConfig = OptimizerConfig(deep_search=True),
    label_config: ActivityLabelConfig = DEFAULT_LABEL_CONFIG,
    feature_config: ActivityFeatureConfig = DEFAULT_FEATURE_CONFIG,
    code_version: str = "LOCAL_UNSPECIFIED",
    research_ledger_path: str | Path | None = None,
    db_path: str | None = None,
) -> dict[str, Any]:
    """Run one predeclared activity architecture under the frozen statistical governance.

    A pass only makes the challenger eligible for *prospective shadow evidence*. This function
    deliberately does not register, freeze, promote, enable advisory weighting, or execute it.
    """
    normalized_kind = str(activity_kind or "").strip().upper()
    if normalized_kind not in ACTIVITY_KINDS:
        raise ValueError(f"Unsupported activity kind: {activity_kind!r}")
    architecture = ARCHITECTURES[normalized_kind]
    bundle = load_activity_labeled_dataset(
        series_id,
        task=task,
        activity_kind=normalized_kind,
        activity_target=activity_target,
        start=start,
        end=end,
        as_of=as_of,
        db_path=db_path,
        label_config=label_config,
        feature_config=feature_config,
    )

    presearch_ledger = research_ledger_summary(task=task, path=research_ledger_path)
    excluded = _exhausted_families(presearch_ledger, architecture)
    config = replace(optimizer_config, excluded_hypothesis_families=excluded)
    optimization = optimize_labeled_dataset(bundle, chronology=chronology, config=config)
    ledger = record_trials(
        task=task,
        trials=optimization.trials,
        dataset_snapshot_hash=bundle.metadata.get("dataset_snapshot_hash"),
        code_version=code_version,
        architecture=architecture,
        path=research_ledger_path,
    )
    multiple_testing = _selection_bias(bundle, optimization, ledger)
    if optimization.winner:
        dsr = dict(multiple_testing.get("dsr") or {})
        if dsr:
            ledger = record_selected_dsr(
                task=task,
                winner=optimization.winner,
                dsr_evidence=dsr,
                architecture=architecture,
                path=research_ledger_path,
            )
    kill = evaluate_research_kill_criteria(optimization, ledger, architecture=architecture)
    bootstrap = _bootstrap(bundle, optimization)
    promotion_quality = evaluate_historical_promotion(
        optimization,
        multiple_testing_evidence=multiple_testing,
        bootstrap_confidence=bootstrap,
    )
    cpcv = _cpcv(bundle, optimization, chronology)

    kill_clear = not bool(kill.get("candidate_killed")) and not bool(kill.get("hypothesis_family_killed"))
    prospective_shadow_eligible = bool(
        optimization.status == "OOS_PASS"
        and multiple_testing.get("passed")
        and bootstrap.get("passed")
        and promotion_quality.get("passed")
        and cpcv.get("passed")
        and kill_clear
    )
    return {
        "status": optimization.status,
        "method_version": METHOD_VERSION,
        "architecture": architecture,
        "activity_kind": normalized_kind,
        "activity_target": float(activity_target),
        "dataset_metadata": bundle.metadata,
        "optimization": serializable_result(optimization),
        "presearch_research_ledger": presearch_ledger,
        "optimizer_excluded_hypothesis_families": [
            {"feature_set": feature_set, "family": family} for feature_set, family in excluded
        ],
        "research_ledger": ledger,
        "multiple_testing_evidence": multiple_testing,
        "kill_criteria": kill,
        "bootstrap_confidence": bootstrap,
        "promotion_quality": promotion_quality,
        "cpcv_robustness": cpcv,
        "prospective_shadow_eligible": prospective_shadow_eligible,
        "historical_oos_reused_after_research_hypothesis_change": True,
        "historical_2026_holdout_status": "CONSUMED_NOT_CLEAN_FINAL_PROOF",
        "holdout_used_for_activity_target_selection": False,
        "holdout_used_for_architecture_selection": False,
        "clean_final_proof_layer": "FUTURE_PROSPECTIVE_SHADOW_SESSIONS",
        "automatic_registration": False,
        "automatic_freeze": False,
        "automatic_promotion": False,
        "automatic_advisory_integration": False,
        "advisory_only": True,
        "trade_authorization": False,
        "order_execution_allowed": False,
    }
