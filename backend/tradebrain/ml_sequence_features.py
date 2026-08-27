"""Causal sequence/context feature challenger for Trade Brain v0.14 ML.

This module extracts more information from real completed BSE candles without inventing new
market history. It adds compact lagged state and OHLC-derived volatility/efficiency proxies.
No Level-2/order-book information is claimed, and no neural sequence model is introduced.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from math import log
from typing import Any

import numpy as np
import pandas as pd

from backend.tradebrain.ml_features import FeatureBundle

METHOD_VERSION = "BSE_ML_SEQUENCE_CONTEXT_V1"
IST = "Asia/Kolkata"
INTRADAY_TASKS = {"BSE_INTRADAY_LONG", "BSE_INTRADAY_SHORT"}


@dataclass(frozen=True)
class SequenceFeatureConfig:
    lags: tuple[int, ...] = (1, 3, 5)
    efficiency_windows: tuple[int, ...] = (5, 10, 20)
    reset_lags_at_session_boundary: bool = True

    def validate(self) -> None:
        if not self.lags or any(int(x) < 1 for x in self.lags):
            raise ValueError("lags must contain positive integers")
        if not self.efficiency_windows or any(int(x) < 2 for x in self.efficiency_windows):
            raise ValueError("efficiency windows must be >= 2")


DEFAULT_SEQUENCE_CONFIG = SequenceFeatureConfig()
LAG_BASE_FEATURES = (
    "return_1",
    "natr_14_pct",
    "relative_volume_20",
    "vwap_distance_pct",
    "dmi_spread",
    "adx_14",
    "rsi_14",
    "macd_hist",
)


def _numeric(frame: pd.DataFrame, name: str) -> pd.Series:
    return pd.to_numeric(frame[name], errors="coerce").replace([np.inf, -np.inf], np.nan)


def _required_raw(frame: pd.DataFrame) -> None:
    required = {"ts_close", "open", "high", "low", "close"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"Sequence feature frame missing raw OHLC/time fields: {missing}")


def _session_key(frame: pd.DataFrame) -> pd.Series:
    local = pd.to_datetime(frame["ts_close"], utc=True).dt.tz_convert(IST)
    return local.dt.date.astype(str)


def _directional_efficiency(close: pd.Series, window: int) -> pd.Series:
    numerator = (close - close.shift(window)).abs()
    denominator = close.diff().abs().rolling(window, min_periods=window).sum()
    return numerator / denominator.replace(0.0, np.nan)


def sequence_context_bundle(
    bundle: FeatureBundle,
    *,
    config: SequenceFeatureConfig = DEFAULT_SEQUENCE_CONFIG,
) -> FeatureBundle:
    """Add causal lagged/context features to an existing point-in-time intraday bundle."""
    config.validate()
    task = str(bundle.metadata.get("task") or "")
    if task not in INTRADAY_TASKS:
        raise ValueError("Sequence context challenger currently supports intraday tasks only")
    frame = bundle.frame.copy().sort_values("ts_close", kind="stable").reset_index(drop=True)
    _required_raw(frame)

    high = _numeric(frame, "high")
    low = _numeric(frame, "low")
    open_ = _numeric(frame, "open")
    close = _numeric(frame, "close")
    positive = (high > 0.0) & (low > 0.0) & (open_ > 0.0) & (close > 0.0)

    log_hl = pd.Series(np.nan, index=frame.index, dtype=float)
    log_co = pd.Series(np.nan, index=frame.index, dtype=float)
    log_hl.loc[positive] = np.log(high.loc[positive] / low.loc[positive])
    log_co.loc[positive] = np.log(close.loc[positive] / open_.loc[positive])
    gk_var = 0.5 * log_hl.pow(2) - (2.0 * log(2.0) - 1.0) * log_co.pow(2)
    parkinson_var = log_hl.pow(2) / (4.0 * log(2.0))
    frame["garman_klass_vol_pct"] = np.sqrt(gk_var.clip(lower=0.0)) * 100.0
    frame["parkinson_vol_pct"] = np.sqrt(parkinson_var.clip(lower=0.0)) * 100.0

    candle_range = (high - low).replace(0.0, np.nan)
    frame["close_location_value"] = (2.0 * close - high - low) / candle_range

    if "vwap_distance_pct" in frame.columns and "natr_14_pct" in frame.columns:
        natr = _numeric(frame, "natr_14_pct").replace(0.0, np.nan)
        frame["vwap_distance_atr_units"] = _numeric(frame, "vwap_distance_pct") / natr
    if "candle_range_pct" in frame.columns and "natr_14_pct" in frame.columns:
        natr = _numeric(frame, "natr_14_pct").replace(0.0, np.nan)
        frame["range_atr_ratio"] = _numeric(frame, "candle_range_pct") / natr
        if "relative_volume_20" in frame.columns:
            frame["relative_volume_x_range_atr"] = _numeric(frame, "relative_volume_20") * frame["range_atr_ratio"]

    for window in config.efficiency_windows:
        frame[f"directional_efficiency_{int(window)}"] = _directional_efficiency(close, int(window))

    session = _session_key(frame)
    created_lags: list[str] = []
    for base in LAG_BASE_FEATURES:
        if base not in frame.columns:
            continue
        values = _numeric(frame, base)
        for lag in config.lags:
            name = f"lag{int(lag)}__{base}"
            if config.reset_lags_at_session_boundary:
                frame[name] = values.groupby(session, sort=False).shift(int(lag))
            else:
                frame[name] = values.shift(int(lag))
            created_lags.append(name)

    new_columns = [
        "garman_klass_vol_pct",
        "parkinson_vol_pct",
        "close_location_value",
        "vwap_distance_atr_units",
        "range_atr_ratio",
        "relative_volume_x_range_atr",
        *[f"directional_efficiency_{int(window)}" for window in config.efficiency_windows],
        *created_lags,
    ]
    new_columns = [name for name in new_columns if name in frame.columns]
    feature_columns = tuple(dict.fromkeys([*bundle.feature_columns, *new_columns]))

    metadata: dict[str, Any] = dict(bundle.metadata)
    metadata.update(
        {
            "sequence_context_method_version": METHOD_VERSION,
            "sequence_context_config": asdict(config),
            "sequence_context_added_features": new_columns,
            "sequence_context_feature_count": len(new_columns),
            "lags_reset_at_session_boundary": bool(config.reset_lags_at_session_boundary),
            "features_use_completed_current_and_prior_bars_only": True,
            "labels_used_to_construct_features": False,
            "future_bars_used": False,
            "level2_order_book_claimed": False,
            "neural_sequence_model_used": False,
            "synthetic_candles_created": False,
            "automatic_promotion": False,
            "advisory_only": True,
            "trade_authorization": False,
            "order_execution_allowed": False,
        }
    )
    return FeatureBundle(frame=frame, feature_columns=feature_columns, metadata=metadata)
