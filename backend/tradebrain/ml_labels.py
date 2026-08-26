"""Trade Brain v0.14 horizon-specific ML labels.

Labels are generated only after the feature timestamp, never span an intraday session
boundary, and use the versioned resident-equity / Zerodha-MTF cost engines. Ambiguous
same-bar stop/target ordering is excluded rather than guessed.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd

from backend.tradebrain.equity_costs import COST_PROFILE_KEY, calculate_equity_trade_costs
from backend.tradebrain.market_data_store import query_bars
from backend.tradebrain.ml_features import FeatureBundle, build_point_in_time_features
from backend.tradebrain.mtf_economics import PROFILE_KEY as MTF_PROFILE_KEY
from backend.tradebrain.swing_mtf import calculate_swing_mtf_trade_costs

METHOD_VERSION = "BSE_ML_LABELS_V1"
TASK_INTRADAY_LONG = "BSE_INTRADAY_LONG"
TASK_INTRADAY_SHORT = "BSE_INTRADAY_SHORT"
TASK_SWING_LONG_MTF = "BSE_SWING_LONG_MTF"
ML_TASKS = {TASK_INTRADAY_LONG, TASK_INTRADAY_SHORT, TASK_SWING_LONG_MTF}
IST = "Asia/Kolkata"


@dataclass(frozen=True)
class LabelSpec:
    task: str
    interval: str
    stop_atr: float
    target_atr: float
    max_holding_bars: int
    quantity: int = 100
    slippage_bps: float = 5.0
    mtf_funded_fraction: float = 0.80

    def validate(self) -> None:
        if self.task not in ML_TASKS:
            raise ValueError(f"Unsupported ML task: {self.task}")
        if self.stop_atr <= 0 or self.target_atr <= 0:
            raise ValueError("ATR stop/target multipliers must be positive")
        if self.max_holding_bars <= 0:
            raise ValueError("max_holding_bars must be positive")
        if self.quantity <= 0:
            raise ValueError("quantity must be positive")
        if self.slippage_bps < 0:
            raise ValueError("slippage_bps must be >= 0")
        if not 0.0 <= self.mtf_funded_fraction < 1.0:
            raise ValueError("mtf_funded_fraction must be in [0, 1)")


def default_label_spec(task: str) -> LabelSpec:
    if task == TASK_INTRADAY_LONG:
        return LabelSpec(task=task, interval="15m", stop_atr=1.0, target_atr=1.5, max_holding_bars=24)
    if task == TASK_INTRADAY_SHORT:
        return LabelSpec(task=task, interval="15m", stop_atr=1.0, target_atr=1.5, max_holding_bars=24)
    if task == TASK_SWING_LONG_MTF:
        return LabelSpec(task=task, interval="1d", stop_atr=1.25, target_atr=2.0, max_holding_bars=10)
    raise ValueError(f"Unsupported ML task: {task}")


def _bars_df(rows: list[dict[str, Any]]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows).sort_values("ts_open", kind="stable").reset_index(drop=True)
    df["ts_open"] = pd.to_datetime(df["ts_open"], utc=True)
    df["ts_close"] = pd.to_datetime(df["ts_close"], utc=True)
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = pd.to_numeric(df[col], errors="coerce").astype(float)
    df["era_id"] = df.get("era_id", pd.Series([None] * len(df), dtype="object"))
    df["era_key"] = df["era_id"].fillna("__UNASSIGNED_ERA__").astype(str)
    return df


def _same_session(left: pd.Timestamp, right: pd.Timestamp) -> bool:
    return left.tz_convert(IST).date() == right.tz_convert(IST).date()


def _local_minutes(ts: pd.Timestamp) -> int:
    value = ts.tz_convert(IST)
    return value.hour * 60 + value.minute


def _direction(task: str) -> str:
    return "SHORT" if task == TASK_INTRADAY_SHORT else "LONG"


def _thresholds(entry: float, atr: float, task: str, spec: LabelSpec) -> tuple[float, float]:
    if task == TASK_INTRADAY_SHORT:
        return entry + atr * spec.stop_atr, entry - atr * spec.target_atr
    return entry - atr * spec.stop_atr, entry + atr * spec.target_atr


def _hits(bar: pd.Series, *, direction: str, stop: float, target: float) -> tuple[bool, bool]:
    if direction == "LONG":
        return float(bar["low"]) <= stop, float(bar["high"]) >= target
    return float(bar["high"]) >= stop, float(bar["low"]) <= target


def _excursions(future: pd.DataFrame, *, direction: str, entry: float) -> tuple[float, float]:
    if future.empty or entry <= 0:
        return 0.0, 0.0
    if direction == "LONG":
        mae = max(0.0, (entry - float(future["low"].min())) / entry * 100.0)
        mfe = max(0.0, (float(future["high"].max()) - entry) / entry * 100.0)
    else:
        mae = max(0.0, (float(future["high"].max()) - entry) / entry * 100.0)
        mfe = max(0.0, (entry - float(future["low"].min())) / entry * 100.0)
    return mae, mfe


def _intraday_label(
    bars: pd.DataFrame,
    *,
    current_index: int,
    atr: float,
    spec: LabelSpec,
) -> dict[str, Any] | None:
    if current_index + 1 >= len(bars):
        return None
    current = bars.iloc[current_index]
    next_bar = bars.iloc[current_index + 1]
    if current["era_key"] != next_bar["era_key"]:
        return None
    if not _same_session(current["ts_close"], next_bar["ts_open"]):
        return None
    if _local_minutes(next_bar["ts_open"]) >= 15 * 60 + 10:
        return None

    session_mask = bars["ts_open"].map(lambda x: _same_session(next_bar["ts_open"], x))
    future = bars.iloc[current_index + 1 :].loc[session_mask.iloc[current_index + 1 :]].copy()
    future = future[future["ts_open"].map(_local_minutes) < 15 * 60 + 15]
    future = future.head(spec.max_holding_bars)
    if future.empty:
        return None
    future = future[future["era_key"] == current["era_key"]]
    if future.empty:
        return None

    direction = _direction(spec.task)
    entry = float(next_bar["open"])
    stop, target = _thresholds(entry, atr, spec.task, spec)
    outcome = "TIME_EXIT"
    exit_price = float(future.iloc[-1]["close"])
    exit_bar = future.iloc[-1]
    used_rows = []
    for _, bar in future.iterrows():
        hit_stop, hit_target = _hits(bar, direction=direction, stop=stop, target=target)
        used_rows.append(bar)
        if hit_stop and hit_target:
            return {
                "label_status": "AMBIGUOUS",
                "label_reason": "STOP_AND_TARGET_SAME_BAR_ORDER_UNKNOWN",
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
        quantity=spec.quantity,
        slippage_bps=spec.slippage_bps,
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
        "label_net_positive": int(float(costs["net_pnl"]) > 0.0),
        "label_net_pnl": float(costs["net_pnl"]),
        "label_net_return_pct": float(costs["net_return_on_entry_notional_pct"]),
        "label_gross_return_pct": gross_return_pct,
        "label_mae_pct": mae,
        "label_mfe_pct": mfe,
        "label_time_to_event_minutes": (exit_bar["ts_close"] - next_bar["ts_open"]).total_seconds() / 60.0,
        "label_holding_bars": len(observed),
        "label_cost_profile": COST_PROFILE_KEY,
        "label_mtf_profile": None,
        "label_mtf_interest_days": 0,
        "label_mtf_funded_amount": 0.0,
    }


def _swing_label(
    bars: pd.DataFrame,
    *,
    current_index: int,
    atr: float,
    spec: LabelSpec,
) -> dict[str, Any] | None:
    if current_index + 1 >= len(bars):
        return None
    current = bars.iloc[current_index]
    next_bar = bars.iloc[current_index + 1]
    if current["era_key"] != next_bar["era_key"]:
        return None
    future = bars.iloc[current_index + 1 : current_index + 1 + spec.max_holding_bars].copy()
    future = future[future["era_key"] == current["era_key"]]
    if future.empty:
        return None

    entry = float(next_bar["open"])
    stop, target = _thresholds(entry, atr, spec.task, spec)
    outcome = "TIME_EXIT"
    exit_price = float(future.iloc[-1]["close"])
    exit_bar = future.iloc[-1]
    used_rows = []
    for _, bar in future.iterrows():
        hit_stop, hit_target = _hits(bar, direction="LONG", stop=stop, target=target)
        used_rows.append(bar)
        if hit_stop and hit_target:
            return {
                "label_status": "AMBIGUOUS",
                "label_reason": "STOP_AND_TARGET_SAME_DAILY_BAR_ORDER_UNKNOWN",
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
    mae, mfe = _excursions(observed, direction="LONG", entry=entry)
    funded_amount = entry * spec.quantity * spec.mtf_funded_fraction
    entry_day = next_bar["ts_open"].tz_convert(IST).date()
    exit_day = exit_bar["ts_close"].tz_convert(IST).date()
    interest_days = max(0, (exit_day - entry_day).days)
    costs = calculate_swing_mtf_trade_costs(
        exchange="NSE",
        entry_price=entry,
        exit_price=exit_price,
        quantity=spec.quantity,
        funded_amount=funded_amount,
        interest_days=interest_days,
        slippage_bps=spec.slippage_bps,
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
        "label_net_positive": int(float(costs["net_pnl"]) > 0.0),
        "label_net_pnl": float(costs["net_pnl"]),
        "label_net_return_pct": float(costs["net_return_on_entry_notional_pct"]),
        "label_gross_return_pct": (exit_price / entry - 1.0) * 100.0,
        "label_mae_pct": mae,
        "label_mfe_pct": mfe,
        "label_time_to_event_minutes": (exit_bar["ts_close"] - next_bar["ts_open"]).total_seconds() / 60.0,
        "label_holding_bars": len(observed),
        "label_cost_profile": COST_PROFILE_KEY,
        "label_mtf_profile": MTF_PROFILE_KEY,
        "label_mtf_interest_days": interest_days,
        "label_mtf_funded_amount": funded_amount,
    }


def _dataset_hash(frame: pd.DataFrame, feature_columns: tuple[str, ...], spec: LabelSpec) -> str:
    label_cols = [
        "label_net_positive",
        "label_net_return_pct",
        "label_gross_return_pct",
        "label_mae_pct",
        "label_mfe_pct",
        "label_end",
        "label_reason",
    ]
    cols = ["ts_open", "ts_close", "era_key", *feature_columns, *label_cols]
    work = frame[cols].copy()
    for col in feature_columns:
        work[col] = pd.to_numeric(work[col], errors="coerce").round(10)
    canonical = {
        "feature_method": "BSE_ML_FEATURES_V1",
        "label_method": METHOD_VERSION,
        "label_spec": asdict(spec),
        "feature_columns": list(feature_columns),
        "rows": json.loads(work.to_json(orient="records", date_format="iso", date_unit="us")),
    }
    return hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":"), allow_nan=True).encode("utf-8")
    ).hexdigest()


def build_labeled_dataset(
    series_id: str,
    *,
    task: str,
    as_of: str | datetime | None = None,
    spec: LabelSpec | None = None,
    db_path: str | None = None,
) -> FeatureBundle:
    chosen = spec or default_label_spec(task)
    chosen.validate()
    if chosen.task != task:
        raise ValueError("LabelSpec task does not match requested task")

    features = build_point_in_time_features(
        series_id,
        interval=chosen.interval,
        as_of=as_of,
        db_path=db_path,
        include_mtf_context=chosen.interval != "1d",
    )
    frame = features.frame.copy()
    if frame.empty:
        metadata = dict(features.metadata)
        metadata.update(
            {
                "label_method_version": METHOD_VERSION,
                "task": task,
                "label_spec": asdict(chosen),
                "resolved_rows": 0,
                "ambiguous_rows": 0,
            }
        )
        return FeatureBundle(frame=frame, feature_columns=features.feature_columns, metadata=metadata)

    raw = query_bars(
        series_id,
        chosen.interval,
        as_of=features.metadata["as_of"],
        limit=500000,
        db_path=db_path,
    )
    bars = _bars_df(raw)
    by_open = {row["ts_open"]: idx for idx, row in bars.iterrows()}

    labels: list[dict[str, Any]] = []
    for _, row in frame.iterrows():
        idx = by_open.get(row["ts_open"])
        atr = float(row.get("atr_14") or np.nan)
        if idx is None or not np.isfinite(atr) or atr <= 0.0:
            labels.append({"label_status": "INSUFFICIENT_FEATURE_HISTORY", "label_reason": "ATR14_UNAVAILABLE"})
            continue
        if task in {TASK_INTRADAY_LONG, TASK_INTRADAY_SHORT}:
            result = _intraday_label(bars, current_index=idx, atr=atr, spec=chosen)
        else:
            result = _swing_label(bars, current_index=idx, atr=atr, spec=chosen)
        labels.append(result or {"label_status": "UNMATURED", "label_reason": "OUTCOME_WINDOW_NOT_AVAILABLE"})

    label_frame = pd.DataFrame(labels, index=frame.index)
    for col in label_frame.columns:
        frame[col] = label_frame[col]
    resolved = frame[frame["label_status"] == "RESOLVED"].copy().reset_index(drop=True)
    resolved["label_net_positive"] = pd.to_numeric(resolved["label_net_positive"], errors="coerce").astype(int)
    snapshot = (
        _dataset_hash(resolved, features.feature_columns, chosen)
        if not resolved.empty
        else hashlib.sha256(f"EMPTY|{task}|{asdict(chosen)}".encode("utf-8")).hexdigest()
    )

    metadata = dict(features.metadata)
    metadata.update(
        {
            "label_method_version": METHOD_VERSION,
            "task": task,
            "direction": _direction(task),
            "horizon": "SWING_MTF" if task == TASK_SWING_LONG_MTF else "INTRADAY",
            "label_spec": asdict(chosen),
            "resolved_rows": int((frame["label_status"] == "RESOLVED").sum()),
            "ambiguous_rows": int((frame["label_status"] == "AMBIGUOUS").sum()),
            "unmatured_rows": int((frame["label_status"] == "UNMATURED").sum()),
            "dataset_snapshot_hash": snapshot,
            "cost_profile_key": COST_PROFILE_KEY,
            "mtf_profile_key": MTF_PROFILE_KEY if task == TASK_SWING_LONG_MTF else None,
            "intraday_session_boundary_enforced": task != TASK_SWING_LONG_MTF,
            "intraday_no_fresh_entry_from_1510_ist": task != TASK_SWING_LONG_MTF,
            "intraday_hard_exit_by_1515_ist": task != TASK_SWING_LONG_MTF,
            "mtf_eligibility_inference_allowed": False,
            "mtf_eligibility_must_be_verified_at_advisory_time": task == TASK_SWING_LONG_MTF,
            "ambiguous_intrabar_order_excluded": True,
            "automatic_policy_change": False,
            "advisory_only": True,
            "trade_authorization": False,
            "order_execution_allowed": False,
        }
    )
    return FeatureBundle(frame=resolved, feature_columns=features.feature_columns, metadata=metadata)
