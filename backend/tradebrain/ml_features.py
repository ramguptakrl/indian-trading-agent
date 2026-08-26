"""Trade Brain v0.14 point-in-time feature engine for BSE Ltd.

The feature engine reads only completed bars from the audited Trade Brain store. Features
are calculated in chronological order, reset at raw-price era boundaries, and never use
future bars. The output is research evidence only and has no broker authority.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd

from backend.tradebrain.market_data_store import get_series, query_bars

METHOD_VERSION = "BSE_ML_FEATURES_V1"
IST = "Asia/Kolkata"
FEATURE_INTERVALS = {"1m", "3m", "5m", "10m", "15m", "30m", "60m", "1d"}


@dataclass(frozen=True)
class FeatureBundle:
    frame: pd.DataFrame
    feature_columns: tuple[str, ...]
    metadata: dict[str, Any]


def _utc_iso(value: str | datetime | None) -> str:
    if value is None:
        return datetime.now(timezone.utc).isoformat()
    parsed = datetime.fromisoformat(value) if isinstance(value, str) else value
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def _bars_frame(rows: list[dict[str, Any]]) -> pd.DataFrame:
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


def _wilder(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(alpha=1.0 / float(period), adjust=False, min_periods=period).mean()


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = _wilder(gain, period)
    avg_loss = _wilder(loss, period)
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    out = 100.0 - 100.0 / (1.0 + rs)
    flat = (avg_gain.fillna(0.0) == 0.0) & (avg_loss.fillna(0.0) == 0.0)
    out = out.mask(flat, 50.0)
    out = out.mask((avg_loss == 0.0) & (avg_gain > 0.0), 100.0)
    return out


def _true_range(df: pd.DataFrame) -> pd.Series:
    prev_close = df["close"].shift(1)
    values = pd.concat(
        [
            (df["high"] - df["low"]).abs(),
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    )
    return values.max(axis=1)


def _adx_features(df: pd.DataFrame, period: int = 14) -> tuple[pd.Series, pd.Series, pd.Series]:
    up = df["high"].diff()
    down = -df["low"].diff()
    plus_dm = pd.Series(np.where((up > down) & (up > 0), up, 0.0), index=df.index)
    minus_dm = pd.Series(np.where((down > up) & (down > 0), down, 0.0), index=df.index)
    atr = _wilder(_true_range(df), period)
    plus_di = 100.0 * _wilder(plus_dm, period) / atr.replace(0.0, np.nan)
    minus_di = 100.0 * _wilder(minus_dm, period) / atr.replace(0.0, np.nan)
    dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0.0, np.nan)
    adx = _wilder(dx, period)
    return adx, plus_di, minus_di


def _mean_deviation(values: np.ndarray) -> float:
    if len(values) == 0:
        return float("nan")
    mean = float(np.mean(values))
    return float(np.mean(np.abs(values - mean)))


def _session_features(df: pd.DataFrame) -> pd.DataFrame:
    local = df["ts_open"].dt.tz_convert(IST)
    out = pd.DataFrame(index=df.index)
    out["session_date"] = local.dt.date.astype(str)
    minutes = local.dt.hour * 60 + local.dt.minute
    out["minutes_from_open"] = (minutes - (9 * 60 + 15)).astype(float)
    out["minutes_to_close"] = ((15 * 60 + 30) - minutes).astype(float)
    out["day_of_week"] = local.dt.dayofweek.astype(float)

    typical = (df["high"] + df["low"] + df["close"]) / 3.0
    pv = typical * df["volume"]
    session_group = out["session_date"]
    cumulative_volume = df["volume"].groupby(session_group).cumsum()
    cumulative_pv = pv.groupby(session_group).cumsum()
    session_vwap = cumulative_pv / cumulative_volume.replace(0.0, np.nan)
    out["vwap_distance_pct"] = (df["close"] / session_vwap - 1.0) * 100.0
    out["vwap_reclaim"] = ((df["close"] > session_vwap) & (df["open"] <= session_vwap)).astype(float)
    out["vwap_rejection"] = ((df["close"] < session_vwap) & (df["open"] >= session_vwap)).astype(float)

    elapsed_close = (
        df["ts_close"].dt.tz_convert(IST).dt.hour * 60
        + df["ts_close"].dt.tz_convert(IST).dt.minute
    ) - (9 * 60 + 15)
    first_30 = elapsed_close <= 30
    opening_high = df["high"].where(first_30).groupby(session_group).cummax()
    opening_low = df["low"].where(first_30).groupby(session_group).cummin()
    out["opening_range_high"] = opening_high.groupby(session_group).ffill()
    out["opening_range_low"] = opening_low.groupby(session_group).ffill()
    out["opening_range_position"] = (
        (df["close"] - out["opening_range_low"])
        / (out["opening_range_high"] - out["opening_range_low"]).replace(0.0, np.nan)
    )

    daily = (
        df.assign(session_date=session_group)
        .groupby("session_date", sort=True)
        .agg(
            day_open=("open", "first"),
            day_high=("high", "max"),
            day_low=("low", "min"),
            day_close=("close", "last"),
        )
    )
    previous = daily.shift(1).rename(
        columns={
            "day_high": "previous_day_high",
            "day_low": "previous_day_low",
            "day_close": "previous_day_close",
            "day_open": "previous_day_open",
        }
    )
    for col in previous.columns:
        out[col] = session_group.map(previous[col])
    out["gap_pct"] = (df["open"] / out["previous_day_close"] - 1.0) * 100.0
    out["distance_prev_high_pct"] = (df["close"] / out["previous_day_high"] - 1.0) * 100.0
    out["distance_prev_low_pct"] = (df["close"] / out["previous_day_low"] - 1.0) * 100.0
    out["distance_prev_close_pct"] = (df["close"] / out["previous_day_close"] - 1.0) * 100.0
    return out


def _feature_group(df: pd.DataFrame, interval: str) -> pd.DataFrame:
    out = df.copy()
    close = out["close"]
    high = out["high"]
    low = out["low"]
    volume = out["volume"]

    out["return_1"] = close.pct_change(1) * 100.0
    out["return_3"] = close.pct_change(3) * 100.0
    out["return_6"] = close.pct_change(6) * 100.0
    out["log_return_1"] = np.log(close / close.shift(1))

    for period in (5, 10, 20, 50):
        out[f"ema_{period}"] = close.ewm(span=period, adjust=False, min_periods=period).mean()
    for period in (5, 20, 50):
        out[f"sma_{period}"] = close.rolling(period, min_periods=period).mean()
    out["ema20_distance_pct"] = (close / out["ema_20"] - 1.0) * 100.0
    out["ema50_distance_pct"] = (close / out["ema_50"] - 1.0) * 100.0
    out["ema20_over_50_pct"] = (out["ema_20"] / out["ema_50"] - 1.0) * 100.0
    out["rsi_14"] = _rsi(close, 14)

    ema12 = close.ewm(span=12, adjust=False, min_periods=12).mean()
    ema26 = close.ewm(span=26, adjust=False, min_periods=26).mean()
    out["macd"] = ema12 - ema26
    out["macd_signal"] = out["macd"].ewm(span=9, adjust=False, min_periods=9).mean()
    out["macd_hist"] = out["macd"] - out["macd_signal"]

    tr = _true_range(out)
    out["atr_14"] = _wilder(tr, 14)
    out["natr_14_pct"] = out["atr_14"] / close * 100.0
    adx, plus_di, minus_di = _adx_features(out, 14)
    out["adx_14"] = adx
    out["plus_di_14"] = plus_di
    out["minus_di_14"] = minus_di
    out["dmi_spread"] = plus_di - minus_di

    mid = close.rolling(20, min_periods=20).mean()
    std = close.rolling(20, min_periods=20).std(ddof=0)
    upper = mid + 2.0 * std
    lower = mid - 2.0 * std
    out["bollinger_position"] = (close - lower) / (upper - lower).replace(0.0, np.nan)
    out["bollinger_bandwidth_pct"] = (upper - lower) / mid.replace(0.0, np.nan) * 100.0

    low14 = low.rolling(14, min_periods=14).min()
    high14 = high.rolling(14, min_periods=14).max()
    out["stochastic_k_14"] = (close - low14) / (high14 - low14).replace(0.0, np.nan) * 100.0

    typical = (high + low + close) / 3.0
    tp_mean = typical.rolling(20, min_periods=20).mean()
    mean_dev = typical.rolling(20, min_periods=20).apply(_mean_deviation, raw=True)
    out["cci_20"] = (typical - tp_mean) / (0.015 * mean_dev.replace(0.0, np.nan))
    out["roc_10_pct"] = close.pct_change(10) * 100.0

    sign = np.sign(close.diff()).fillna(0.0)
    out["obv"] = (sign * volume).cumsum()
    out["obv_change_5"] = out["obv"].diff(5)
    median_volume = volume.rolling(20, min_periods=5).median()
    out["relative_volume_20"] = volume / median_volume.replace(0.0, np.nan)
    out["volume_expansion"] = volume / volume.rolling(5, min_periods=5).mean().replace(0.0, np.nan)

    money_flow = typical * volume
    direction = typical.diff()
    positive = money_flow.where(direction > 0, 0.0).rolling(14, min_periods=14).sum()
    negative = money_flow.where(direction < 0, 0.0).rolling(14, min_periods=14).sum()
    ratio = positive / negative.replace(0.0, np.nan)
    out["mfi_14"] = 100.0 - 100.0 / (1.0 + ratio)

    prior_high20 = high.shift(1).rolling(20, min_periods=20).max()
    prior_low20 = low.shift(1).rolling(20, min_periods=20).min()
    out["donchian_high_distance_pct"] = (close / prior_high20 - 1.0) * 100.0
    out["donchian_low_distance_pct"] = (close / prior_low20 - 1.0) * 100.0

    candle_range = (high - low).replace(0.0, np.nan)
    body = close - out["open"]
    out["candle_body_pct_range"] = body / candle_range
    out["upper_wick_pct_range"] = (high - np.maximum(out["open"], close)) / candle_range
    out["lower_wick_pct_range"] = (np.minimum(out["open"], close) - low) / candle_range
    out["candle_range_pct"] = candle_range / close * 100.0
    out["inside_bar"] = ((high < high.shift(1)) & (low > low.shift(1))).astype(float)
    out["bullish_engulfing_body"] = (
        (close > out["open"])
        & (close.shift(1) < out["open"].shift(1))
        & (out["open"] <= close.shift(1))
        & (close >= out["open"].shift(1))
    ).astype(float)
    out["bearish_engulfing_body"] = (
        (close < out["open"])
        & (close.shift(1) > out["open"].shift(1))
        & (out["open"] >= close.shift(1))
        & (close <= out["open"].shift(1))
    ).astype(float)
    out["doji_shape"] = (body.abs() <= candle_range * 0.1).astype(float)

    bullish_fvg = low > high.shift(2)
    bearish_fvg = high < low.shift(2)
    out["bullish_fvg"] = bullish_fvg.astype(float)
    out["bearish_fvg"] = bearish_fvg.astype(float)
    out["fvg_size_pct"] = np.where(
        bullish_fvg,
        (low - high.shift(2)) / close * 100.0,
        np.where(bearish_fvg, (low.shift(2) - high) / close * 100.0, 0.0),
    )

    range_high = high.shift(1).rolling(20, min_periods=20).max()
    range_low = low.shift(1).rolling(20, min_periods=20).min()
    width = (range_high - range_low).replace(0.0, np.nan)
    out["local_range_position"] = (close - range_low) / width
    out["fib_382_distance_pct"] = (close / (range_low + width * 0.382) - 1.0) * 100.0
    out["fib_500_distance_pct"] = (close / (range_low + width * 0.500) - 1.0) * 100.0
    out["fib_618_distance_pct"] = (close / (range_low + width * 0.618) - 1.0) * 100.0

    rolling_pv = (close * volume).rolling(20, min_periods=5).sum()
    rolling_vol = volume.rolling(20, min_periods=5).sum()
    node_proxy = rolling_pv / rolling_vol.replace(0.0, np.nan)
    out["volume_node_proxy_distance_pct"] = (close / node_proxy - 1.0) * 100.0

    basic_upper = (high + low) / 2.0 + 3.0 * out["atr_14"]
    basic_lower = (high + low) / 2.0 - 3.0 * out["atr_14"]
    out["supertrend_style_bias"] = np.where(
        close > basic_upper.shift(1),
        1.0,
        np.where(close < basic_lower.shift(1), -1.0, 0.0),
    )

    if interval != "1d":
        session = _session_features(out)
        for col in session.columns:
            out[col] = session[col]
    else:
        local = out["ts_open"].dt.tz_convert(IST)
        out["session_date"] = local.dt.date.astype(str)
        out["day_of_week"] = local.dt.dayofweek.astype(float)

    out["regime"] = np.where(
        out["natr_14_pct"] > out["natr_14_pct"].rolling(60, min_periods=20).median() * 1.5,
        "HIGH_VOL",
        np.where(
            (close > out["ema_20"]) & (out["ema_20"] > out["ema_50"]) & (out["adx_14"] >= 20),
            "TREND_UP",
            np.where(
                (close < out["ema_20"]) & (out["ema_20"] < out["ema_50"]) & (out["adx_14"] >= 20),
                "TREND_DOWN",
                "RANGE",
            ),
        ),
    )
    return out


def _trend_context(rows: list[dict[str, Any]], label: str) -> pd.DataFrame:
    df = _bars_frame(rows)
    if df.empty:
        return pd.DataFrame(columns=["context_time", label])
    parts = []
    for _, group in df.groupby("era_key", sort=False):
        work = group.copy()
        ema20 = work["close"].ewm(span=20, adjust=False, min_periods=20).mean()
        ema50 = work["close"].ewm(span=50, adjust=False, min_periods=50).mean()
        score = np.where(
            (work["close"] > ema20) & (ema20 > ema50),
            1.0,
            np.where((work["close"] < ema20) & (ema20 < ema50), -1.0, 0.0),
        )
        parts.append(pd.DataFrame({"context_time": work["ts_close"], label: score}, index=work.index))
    return pd.concat(parts).sort_values("context_time").reset_index(drop=True)


def _derived_4h_context(hourly_rows: list[dict[str, Any]]) -> pd.DataFrame:
    df = _bars_frame(hourly_rows)
    if df.empty:
        return pd.DataFrame(columns=["context_time", "mtf_4h_trend"])
    local_date = df["ts_open"].dt.tz_convert(IST).dt.date.astype(str)
    records: list[dict[str, Any]] = []
    for _, day in df.groupby(local_date, sort=True):
        for idx in range(3, len(day)):
            window = day.iloc[idx - 3 : idx + 1]
            records.append(
                {
                    "ts_open": window.iloc[0]["ts_open"],
                    "ts_close": window.iloc[-1]["ts_close"],
                    "open": float(window.iloc[0]["open"]),
                    "high": float(window["high"].max()),
                    "low": float(window["low"].min()),
                    "close": float(window.iloc[-1]["close"]),
                    "volume": float(window["volume"].sum()),
                    "era_id": window.iloc[-1].get("era_id"),
                }
            )
    return _trend_context(records, "mtf_4h_trend")


def _attach_mtf_context(
    frame: pd.DataFrame,
    *,
    series_id: str,
    as_of: str,
    db_path: str | None,
) -> pd.DataFrame:
    if frame.empty:
        return frame
    out = frame.sort_values("ts_close").copy()
    daily = query_bars(series_id, "1d", as_of=as_of, limit=500000, db_path=db_path)
    hourly = query_bars(series_id, "60m", as_of=as_of, limit=500000, db_path=db_path)
    contexts = [
        _trend_context(daily, "mtf_daily_trend"),
        _trend_context(hourly, "mtf_1h_trend"),
        _derived_4h_context(hourly),
    ]
    for context in contexts:
        label_cols = [c for c in context.columns if c != "context_time"]
        if context.empty:
            for col in label_cols:
                out[col] = np.nan
            continue
        out = pd.merge_asof(
            out.sort_values("ts_close"),
            context.sort_values("context_time"),
            left_on="ts_close",
            right_on="context_time",
            direction="backward",
            allow_exact_matches=True,
        ).drop(columns=["context_time"])
    for col in ("mtf_daily_trend", "mtf_4h_trend", "mtf_1h_trend"):
        if col not in out:
            out[col] = np.nan
    out["mtf_alignment_score"] = out[
        ["mtf_daily_trend", "mtf_4h_trend", "mtf_1h_trend"]
    ].sum(axis=1, min_count=1)
    return out


def _feature_columns(frame: pd.DataFrame) -> tuple[str, ...]:
    excluded = {
        "series_id",
        "interval",
        "ts_open",
        "ts_close",
        "era_id",
        "era_key",
        "session_date",
        "regime",
        "source_key",
        "source_timestamp",
        "ingested_at",
        "quality_flags",
        "is_final",
        "is_derived",
        "derived_from_interval",
        "open",
        "high",
        "low",
        "close",
        "volume",
    }
    columns = []
    for col in frame.columns:
        if col in excluded or col.startswith("label_"):
            continue
        if pd.api.types.is_numeric_dtype(frame[col]):
            columns.append(col)
    return tuple(columns)


def _snapshot_hash(
    frame: pd.DataFrame,
    feature_columns: tuple[str, ...],
    *,
    interval: str,
    as_of: str,
) -> str:
    cols = ["ts_open", "ts_close", "era_key", *feature_columns]
    work = frame[cols].copy()
    for col in feature_columns:
        work[col] = pd.to_numeric(work[col], errors="coerce").round(10)
    canonical = {
        "method_version": METHOD_VERSION,
        "interval": interval,
        "as_of": as_of,
        "feature_columns": list(feature_columns),
        "rows": json.loads(work.to_json(orient="records", date_format="iso", date_unit="us")),
    }
    return hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":"), allow_nan=True).encode("utf-8")
    ).hexdigest()


def build_point_in_time_features(
    series_id: str,
    *,
    interval: str,
    as_of: str | datetime | None = None,
    db_path: str | None = None,
    include_mtf_context: bool = True,
) -> FeatureBundle:
    """Build deterministic completed-bar features for the NSE:BSE series."""
    if interval not in FEATURE_INTERVALS:
        raise ValueError(f"Unsupported ML interval: {interval}")
    series = get_series(series_id, db_path=db_path)
    if series is None:
        raise ValueError(f"Unknown market series: {series_id}")
    if str(series.get("exchange") or "").upper() != "NSE" or str(series.get("symbol") or "").upper() != "BSE":
        raise ValueError("Trade Brain ML features are restricted to NSE:BSE")
    cutoff = _utc_iso(as_of)
    rows = query_bars(series_id, interval, as_of=cutoff, limit=500000, db_path=db_path)
    base = _bars_frame(rows)
    if base.empty:
        return FeatureBundle(
            frame=base,
            feature_columns=tuple(),
            metadata={
                "method_version": METHOD_VERSION,
                "series_id": series_id,
                "interval": interval,
                "as_of": cutoff,
                "rows": 0,
                "dataset_snapshot_hash": hashlib.sha256(b"EMPTY").hexdigest(),
                "point_in_time": True,
                "automatic_policy_change": False,
                "trade_authorization": False,
                "order_execution_allowed": False,
            },
        )

    pieces = []
    for _, group in base.groupby("era_key", sort=False):
        pieces.append(_feature_group(group.copy(), interval))
    frame = pd.concat(pieces).sort_values("ts_open", kind="stable").reset_index(drop=True)
    if include_mtf_context and interval != "1d":
        frame = _attach_mtf_context(frame, series_id=series_id, as_of=cutoff, db_path=db_path)

    numeric_before_flags = _feature_columns(frame)
    for col in numeric_before_flags:
        if frame[col].isna().any():
            frame[f"missing__{col}"] = frame[col].isna().astype(float)

    features = _feature_columns(frame)
    snapshot = _snapshot_hash(frame, features, interval=interval, as_of=cutoff)
    metadata = {
        "method_version": METHOD_VERSION,
        "series_id": series_id,
        "exchange": "NSE",
        "symbol": "BSE",
        "interval": interval,
        "as_of": cutoff,
        "rows": len(frame),
        "feature_count": len(features),
        "feature_columns": list(features),
        "dataset_snapshot_hash": snapshot,
        "point_in_time": True,
        "completed_bars_only": True,
        "raw_price_era_reset": True,
        "missing_values_invented": False,
        "missing_flags_emitted": True,
        "mtf_context": include_mtf_context and interval != "1d",
        "nifty_context_status": "NOT_YET_ATTACHED_TO_V1_DATASET",
        "automatic_policy_change": False,
        "advisory_only": True,
        "trade_authorization": False,
        "order_execution_allowed": False,
    }
    frame.insert(0, "series_id", series_id)
    frame.insert(1, "interval", interval)
    return FeatureBundle(frame=frame, feature_columns=features, metadata=metadata)
