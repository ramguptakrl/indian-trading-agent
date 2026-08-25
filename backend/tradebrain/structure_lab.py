"""Research-only Fibonacci and volume-at-price proxy features for BSE Ltd.

Historical OHLCV candles do not reveal true trade-by-trade volume distribution. The
volume feature below therefore assigns each bar's volume to its typical price and is
explicitly labelled a proxy. It must not be presented as an exchange-native Volume
Profile. Fibonacci levels are deterministic geometry only, not standalone signals.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from backend.tradebrain.market_data_store import get_series, query_bars

METHOD_VERSION = "BSE_STRUCTURE_LAB_V1"
FIB_RATIOS = (0.236, 0.382, 0.5, 0.618, 0.786)


def _cutoff(value: str | datetime | None) -> str:
    if value is None:
        return datetime.now(timezone.utc).isoformat()
    if isinstance(value, str):
        return value
    dt = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def fibonacci_structure(bars: list[dict[str, Any]], *, lookback: int = 80) -> dict[str, Any]:
    window = bars[-max(10, int(lookback)) :]
    if len(window) < 10:
        return {"status": "INSUFFICIENT_DATA"}
    high = max(float(x["high"]) for x in window)
    low = min(float(x["low"]) for x in window)
    last = float(window[-1]["close"])
    if high <= low:
        return {"status": "INVALID_RANGE"}
    direction = "UPS WING" if last >= (high + low) / 2 else "DOWNSWING"
    span = high - low
    if direction == "UPS WING":
        levels = {str(ratio): high - span * ratio for ratio in FIB_RATIOS}
    else:
        levels = {str(ratio): low + span * ratio for ratio in FIB_RATIOS}
    return {
        "status": "OK",
        "lookback_bars": len(window),
        "swing_high": round(high, 4),
        "swing_low": round(low, 4),
        "last_close": round(last, 4),
        "orientation": direction.replace(" ", ""),
        "retracement_levels": {key: round(value, 4) for key, value in levels.items()},
        "standalone_signal": False,
    }


def volume_at_price_proxy(bars: list[dict[str, Any]], *, lookback: int = 160, bins: int = 24) -> dict[str, Any]:
    window = bars[-max(20, int(lookback)) :]
    if len(window) < 20:
        return {"status": "INSUFFICIENT_DATA"}
    prices = [(float(x["high"]) + float(x["low"]) + float(x["close"])) / 3.0 for x in window]
    low = min(prices)
    high = max(prices)
    if high <= low:
        return {"status": "INVALID_RANGE"}
    bins = max(8, min(int(bins), 80))
    width = (high - low) / bins
    volume = [0.0 for _ in range(bins)]
    for price, bar in zip(prices, window):
        idx = min(bins - 1, max(0, int((price - low) / width)))
        volume[idx] += max(0.0, float(bar.get("volume") or 0.0))
    total = sum(volume)
    if total <= 0:
        return {"status": "NO_VOLUME"}
    ranked = sorted(range(bins), key=lambda idx: volume[idx], reverse=True)

    def node(idx: int) -> dict[str, Any]:
        floor = low + idx * width
        ceiling = floor + width
        return {
            "bin_low": round(floor, 4),
            "bin_high": round(ceiling, 4),
            "mid": round((floor + ceiling) / 2.0, 4),
            "volume_share_pct": round(volume[idx] / total * 100.0, 3),
        }

    return {
        "status": "OK",
        "lookback_bars": len(window),
        "bins": bins,
        "high_volume_nodes_proxy": [node(idx) for idx in ranked[:5]],
        "low_volume_nodes_proxy": [node(idx) for idx in sorted(range(bins), key=lambda idx: volume[idx])[:5]],
        "method": "BAR_VOLUME_ASSIGNED_TO_TYPICAL_PRICE_BIN",
        "true_trade_level_volume_profile": False,
        "standalone_signal": False,
    }


def structure_lab_snapshot(
    series_id: str,
    *,
    as_of: str | datetime | None = None,
    db_path: str | None = None,
) -> dict[str, Any]:
    series = get_series(series_id, db_path=db_path)
    if series is None:
        raise ValueError(f"Unknown market series: {series_id}")
    cutoff = _cutoff(as_of)
    bars_15m = query_bars(series_id, "15m", as_of=cutoff, limit=500000, db_path=db_path)[-4000:]
    bars_60m = query_bars(series_id, "60m", as_of=cutoff, limit=500000, db_path=db_path)[-2000:]
    return {
        "method_version": METHOD_VERSION,
        "series_id": series_id,
        "as_of": cutoff,
        "fibonacci_1h": fibonacci_structure(bars_60m, lookback=80),
        "fibonacci_15m": fibonacci_structure(bars_15m, lookback=120),
        "volume_at_price_15m_proxy": volume_at_price_proxy(bars_15m, lookback=320, bins=28),
        "research_only": True,
        "eligible_for_direct_live_promotion": False,
        "required_next_step": "Test whether proximity/reaction features add out-of-sample value for BSE versus the simpler incumbent.",
        "trade_authorization": False,
        "order_execution_allowed": False,
    }
