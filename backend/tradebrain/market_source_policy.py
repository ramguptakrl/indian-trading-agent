"""Trade Brain market-data source preference and safe fallback policy.

Kite is the preferred transport when credentials are configured. Yahoo/yfinance remains
an explicit fallback/research vendor. Source selection is surfaced in every result so
fallback data is never silently relabelled as Kite.
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any

from backend.tradebrain.kite_data import KITE_SOURCE_KEY
from backend.tradebrain.kite_history_range import sync_kite_history_range
from backend.tradebrain.market_data import YAHOO_SOURCE_KEY, sync_yahoo_history

KITE_INTERVALS = {
    "1m": "minute",
    "3m": "3minute",
    "5m": "5minute",
    "10m": "10minute",
    "15m": "15minute",
    "30m": "30minute",
    "60m": "60minute",
    "1h": "60minute",
    "1d": "day",
}
YAHOO_INTERVALS = {
    "1m": "1m",
    "5m": "5m",
    "15m": "15m",
    "30m": "30m",
    "60m": "60m",
    "1h": "1h",
    "1d": "1d",
}


def kite_credentials_ready() -> bool:
    return bool((os.getenv("KITE_API_KEY") or "").strip() and (os.getenv("KITE_ACCESS_TOKEN") or "").strip())


def market_source_status() -> dict[str, Any]:
    ready = kite_credentials_ready()
    return {
        "preferred_historical_source": KITE_SOURCE_KEY if ready else YAHOO_SOURCE_KEY,
        "preferred_live_source": "ZERODHA_KITE_WEBSOCKET_MARKET_DATA_ONLY" if ready else "YAHOO_RESEARCH_FALLBACK",
        "kite_credentials_ready": ready,
        "kite_role": "MARKET_DATA_ONLY",
        "yahoo_role": "FALLBACK_AND_RESEARCH",
        "automatic_order_execution": False,
        "fallback_is_always_labelled": True,
        "historical_long_ranges_are_chunked": True,
    }


def sync_preferred_history(
    *,
    exchange: str,
    symbol: str,
    interval: str,
    from_time: str | datetime,
    to_time: str | datetime,
    allow_yahoo_fallback: bool = True,
    db_path: str | None = None,
) -> dict[str, Any]:
    """Sync history using Kite when configured, otherwise explicit Yahoo fallback."""
    normalized = interval.strip().lower()
    if normalized not in KITE_INTERVALS and normalized not in YAHOO_INTERVALS:
        raise ValueError(f"Unsupported preferred-history interval: {interval}")

    if kite_credentials_ready():
        if normalized not in KITE_INTERVALS:
            raise ValueError(f"Interval {interval} is not supported by the Kite adapter")
        try:
            result = sync_kite_history_range(
                exchange=exchange,
                symbol=symbol,
                interval=KITE_INTERVALS[normalized],
                from_time=from_time,
                to_time=to_time,
                db_path=db_path,
            )
            return {
                **result,
                "selected_by": "PREFERRED_SOURCE_POLICY",
                "primary_source_attempted": KITE_SOURCE_KEY,
                "fallback_used": False,
            }
        except Exception as exc:
            if not allow_yahoo_fallback:
                raise
            fallback_reason = f"{type(exc).__name__}: {exc}"
    else:
        fallback_reason = "KITE_CREDENTIALS_NOT_CONFIGURED"

    if normalized not in YAHOO_INTERVALS:
        raise RuntimeError(
            f"Kite unavailable and interval {interval} has no Yahoo fallback; reason={fallback_reason}"
        )
    result = sync_yahoo_history(
        exchange=exchange,
        symbol=symbol,
        interval=YAHOO_INTERVALS[normalized],
        start=from_time,
        end=to_time,
        incremental=False,
        db_path=db_path,
    )
    return {
        **result,
        "selected_by": "PREFERRED_SOURCE_POLICY",
        "primary_source_attempted": KITE_SOURCE_KEY,
        "fallback_used": True,
        "fallback_source": YAHOO_SOURCE_KEY,
        "fallback_reason": fallback_reason,
    }
