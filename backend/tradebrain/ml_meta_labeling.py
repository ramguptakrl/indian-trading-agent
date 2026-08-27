"""Deterministic primary-signal generators for Trade Brain v0.14 meta-label research.

Meta-labeling narrows the ML question from "predict every BSE candle" to "should this already
identified structural setup be accepted after costs?" Direction remains deterministic and
point-in-time. ML only predicts whether the primary setup's existing triple-barrier label is
net positive.

Three mutually different hypotheses are predeclared here. Their thresholds are not tuned on
OOS or holdout. Any later threshold change is a new research candidate and must be charged to
the persistent research ledger.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import pandas as pd

from backend.tradebrain.ml_features import FeatureBundle

METHOD_VERSION = "BSE_ML_META_LABEL_V1"
SIGNAL_TREND_MOMENTUM = "META_TREND_MOMENTUM"
SIGNAL_MEAN_REVERSION = "META_MEAN_REVERSION"
SIGNAL_VOLATILITY_BREAKOUT = "META_VOLATILITY_BREAKOUT"
PRIMARY_SIGNAL_FAMILIES = (
    SIGNAL_TREND_MOMENTUM,
    SIGNAL_MEAN_REVERSION,
    SIGNAL_VOLATILITY_BREAKOUT,
)
INTRADAY_TASKS = {"BSE_INTRADAY_LONG", "BSE_INTRADAY_SHORT"}


@dataclass(frozen=True)
class MetaSignalConfig:
    trend_min_relative_volume: float = 1.10
    trend_min_adx: float = 18.0
    mean_reversion_long_bollinger_position: float = 0.10
    mean_reversion_short_bollinger_position: float = 0.90
    mean_reversion_long_rsi: float = 30.0
    mean_reversion_short_rsi: float = 70.0
    mean_reversion_max_volume_expansion: float = 1.00
    breakout_min_relative_volume: float = 1.20
    breakout_range_expansion_multiple: float = 1.50
    breakout_lookback: int = 50
    breakout_min_periods: int = 20
    breakout_compression_quantile: float = 0.25

    def validate(self) -> None:
        if self.trend_min_relative_volume <= 0.0 or self.breakout_min_relative_volume <= 0.0:
            raise ValueError("relative-volume thresholds must be positive")
        if self.trend_min_adx < 0.0:
            raise ValueError("ADX threshold must be non-negative")
        if not 0.0 <= self.mean_reversion_long_bollinger_position < self.mean_reversion_short_bollinger_position <= 1.0:
            raise ValueError("Bollinger position thresholds are invalid")
        if not 0.0 <= self.mean_reversion_long_rsi < self.mean_reversion_short_rsi <= 100.0:
            raise ValueError("RSI thresholds are invalid")
        if self.mean_reversion_max_volume_expansion <= 0.0:
            raise ValueError("volume expansion threshold must be positive")
        if self.breakout_range_expansion_multiple <= 1.0:
            raise ValueError("breakout range expansion multiple must be > 1")
        if self.breakout_lookback < self.breakout_min_periods or self.breakout_min_periods < 5:
            raise ValueError("breakout lookback/min periods are invalid")
        if not 0.0 < self.breakout_compression_quantile < 0.5:
            raise ValueError("compression quantile must be in (0,0.5)")


DEFAULT_META_SIGNAL_CONFIG = MetaSignalConfig()


def _require(frame: pd.DataFrame, columns: tuple[str, ...]) -> None:
    missing = [name for name in columns if name not in frame.columns]
    if missing:
        raise ValueError(f"Meta-label primary signal missing point-in-time features: {missing}")


def _numeric(frame: pd.DataFrame, name: str) -> pd.Series:
    return pd.to_numeric(frame[name], errors="coerce").replace([np.inf, -np.inf], np.nan)


def _trend_mask(frame: pd.DataFrame, *, side: str, config: MetaSignalConfig) -> pd.Series:
    columns = ("ema20_over_50_pct", "vwap_distance_pct", "relative_volume_20", "dmi_spread", "adx_14")
    _require(frame, columns)
    ema = _numeric(frame, "ema20_over_50_pct")
    vwap = _numeric(frame, "vwap_distance_pct")
    rvol = _numeric(frame, "relative_volume_20")
    dmi = _numeric(frame, "dmi_spread")
    adx = _numeric(frame, "adx_14")
    common = (rvol >= config.trend_min_relative_volume) & (adx >= config.trend_min_adx)
    if side == "LONG":
        return common & (ema > 0.0) & (vwap > 0.0) & (dmi > 0.0)
    return common & (ema < 0.0) & (vwap < 0.0) & (dmi < 0.0)


def _mean_reversion_mask(frame: pd.DataFrame, *, side: str, config: MetaSignalConfig) -> pd.Series:
    columns = ("bollinger_position", "rsi_14", "vwap_distance_pct", "volume_expansion")
    _require(frame, columns)
    boll = _numeric(frame, "bollinger_position")
    rsi = _numeric(frame, "rsi_14")
    vwap = _numeric(frame, "vwap_distance_pct")
    volume = _numeric(frame, "volume_expansion")
    decaying = volume <= config.mean_reversion_max_volume_expansion
    if side == "LONG":
        return (
            decaying
            & (boll <= config.mean_reversion_long_bollinger_position)
            & (rsi <= config.mean_reversion_long_rsi)
            & (vwap < 0.0)
        )
    return (
        decaying
        & (boll >= config.mean_reversion_short_bollinger_position)
        & (rsi >= config.mean_reversion_short_rsi)
        & (vwap > 0.0)
    )


def _volatility_breakout_mask(frame: pd.DataFrame, *, side: str, config: MetaSignalConfig) -> pd.Series:
    columns = (
        "bollinger_bandwidth_pct",
        "candle_range_pct",
        "inside_bar",
        "relative_volume_20",
        "return_1",
    )
    _require(frame, columns)
    bandwidth = _numeric(frame, "bollinger_bandwidth_pct")
    candle_range = _numeric(frame, "candle_range_pct")
    inside = _numeric(frame, "inside_bar")
    rvol = _numeric(frame, "relative_volume_20")
    ret = _numeric(frame, "return_1")

    # Every threshold below is formed from bars strictly before the current feature timestamp.
    prior_bandwidth = bandwidth.shift(1)
    prior_compression_cutoff = bandwidth.shift(1).rolling(
        config.breakout_lookback,
        min_periods=config.breakout_min_periods,
    ).quantile(config.breakout_compression_quantile)
    prior_range_median = candle_range.shift(1).rolling(
        config.breakout_lookback,
        min_periods=config.breakout_min_periods,
    ).median()
    prior_compressed = (
        (prior_bandwidth <= prior_compression_cutoff)
        | (inside.shift(1) >= 1.0)
    )
    expansion = candle_range >= prior_range_median * config.breakout_range_expansion_multiple
    activity = rvol >= config.breakout_min_relative_volume
    if side == "LONG":
        return prior_compressed & expansion & activity & (ret > 0.0)
    return prior_compressed & expansion & activity & (ret < 0.0)


def primary_signal_mask(
    bundle: FeatureBundle,
    *,
    signal_family: str,
    config: MetaSignalConfig = DEFAULT_META_SIGNAL_CONFIG,
) -> pd.Series:
    """Return a point-in-time primary-signal mask without consulting labels."""
    config.validate()
    task = str(bundle.metadata.get("task") or "")
    if task not in INTRADAY_TASKS:
        raise ValueError("Meta-label primary signals currently support only intraday tasks")
    if signal_family not in PRIMARY_SIGNAL_FAMILIES:
        raise ValueError(f"Unsupported meta-label signal family: {signal_family}")
    side = "SHORT" if task == "BSE_INTRADAY_SHORT" else "LONG"
    frame = bundle.frame
    if signal_family == SIGNAL_TREND_MOMENTUM:
        mask = _trend_mask(frame, side=side, config=config)
    elif signal_family == SIGNAL_MEAN_REVERSION:
        mask = _mean_reversion_mask(frame, side=side, config=config)
    else:
        mask = _volatility_breakout_mask(frame, side=side, config=config)
    return mask.fillna(False).astype(bool)


def meta_label_bundle(
    bundle: FeatureBundle,
    *,
    signal_family: str,
    config: MetaSignalConfig = DEFAULT_META_SIGNAL_CONFIG,
    min_setups: int = 100,
) -> FeatureBundle:
    """Filter an existing triple-barrier dataset to deterministic primary setups.

    Existing `label_net_positive` becomes the secondary ML target: did the primary setup make
    money after the modeled costs? No label is used to decide whether the primary setup exists.
    """
    if min_setups < 20:
        raise ValueError("min_setups must be >= 20")
    mask = primary_signal_mask(bundle, signal_family=signal_family, config=config)
    selected = bundle.frame.loc[mask].copy().reset_index(drop=True)
    if len(selected) < int(min_setups):
        raise ValueError(
            f"Insufficient deterministic meta-label setups for {signal_family}: {len(selected)} < {min_setups}"
        )
    metadata: dict[str, Any] = dict(bundle.metadata)
    metadata.update(
        {
            "meta_label_method_version": METHOD_VERSION,
            "meta_signal_family": signal_family,
            "meta_signal_config": asdict(config),
            "meta_primary_side": "SHORT" if str(bundle.metadata.get("task")) == "BSE_INTRADAY_SHORT" else "LONG",
            "meta_target": "label_net_positive",
            "input_labeled_rows": int(len(bundle.frame)),
            "primary_signal_setups": int(len(selected)),
            "primary_signal_coverage_pct": float(len(selected) / max(1, len(bundle.frame)) * 100.0),
            "primary_signal_used_labels": False,
            "primary_signal_used_future_outcomes": False,
            "primary_signal_thresholds_tuned_on_oos": False,
            "primary_signal_thresholds_tuned_on_holdout": False,
            "existing_triple_barrier_labels_reused": True,
            "ml_decides_direction": False,
            "ml_is_secondary_accept_reject_filter": True,
            "automatic_promotion": False,
            "advisory_only": True,
            "trade_authorization": False,
            "order_execution_allowed": False,
        }
    )
    return FeatureBundle(
        frame=selected,
        feature_columns=tuple(bundle.feature_columns),
        metadata=metadata,
    )
