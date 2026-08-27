"""Chunk long Kite historical ranges within documented per-request limits."""

from __future__ import annotations

import time as time_module
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from backend.tradebrain.kite_data import KiteDataOnlyClient, sync_kite_history

IST = ZoneInfo("Asia/Kolkata")

# Conservative windows kept below the published/forum candle caps so inclusive
# endpoints and timezone boundaries do not turn a nominally-valid request invalid.
CONSERVATIVE_CHUNK_DAYS = {
    "minute": 55,
    "3minute": 90,
    "5minute": 90,
    "10minute": 90,
    "15minute": 180,
    "30minute": 180,
    "60minute": 360,
    "day": 1800,
}


def _aware(value: str | datetime) -> datetime:
    dt = datetime.fromisoformat(value) if isinstance(value, str) else value
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=IST)
    return dt.astimezone(IST)


def planned_kite_chunks(interval: str, from_time: str | datetime, to_time: str | datetime) -> list[tuple[datetime, datetime]]:
    if interval not in CONSERVATIVE_CHUNK_DAYS:
        raise ValueError(f"Unsupported Kite historical interval: {interval}")
    start = _aware(from_time)
    finish = _aware(to_time)
    if finish <= start:
        raise ValueError("to_time must be after from_time")
    span = timedelta(days=CONSERVATIVE_CHUNK_DAYS[interval])
    chunks: list[tuple[datetime, datetime]] = []
    cursor = start
    while cursor < finish:
        end = min(cursor + span, finish)
        chunks.append((cursor, end))
        cursor = end
    return chunks


def sync_kite_history_range(
    *,
    exchange: str,
    symbol: str,
    interval: str,
    from_time: str | datetime,
    to_time: str | datetime,
    api_key: str | None = None,
    access_token: str | None = None,
    instrument_token: int | None = None,
    client: KiteDataOnlyClient | None = None,
    rate_limit_sleep_seconds: float | None = None,
    db_path: str | None = None,
) -> dict[str, Any]:
    """Sync a long range through repeated audited Kite historical requests.

    Real Kite REST calls are paced/retried inside KiteDataOnlyClient, so this range
    wrapper must not double-throttle them. Tests/special callers may still provide an
    explicit inter-chunk sleep; `0` disables it for mocked/no-network calls.
    """
    if rate_limit_sleep_seconds is not None and rate_limit_sleep_seconds < 0:
        raise ValueError("rate_limit_sleep_seconds must be >= 0")
    data_client = client or KiteDataOnlyClient(api_key, access_token)
    if instrument_token is None:
        instrument = data_client.resolve_equity_instrument(exchange, symbol)
        instrument_token = int(instrument["instrument_token"])
    chunks = planned_kite_chunks(interval, from_time, to_time)

    results: list[dict[str, Any]] = []
    for idx, (start, end) in enumerate(chunks):
        if idx > 0 and rate_limit_sleep_seconds:
            time_module.sleep(rate_limit_sleep_seconds)
        result = sync_kite_history(
            exchange=exchange,
            symbol=symbol,
            interval=interval,
            from_time=start,
            to_time=end,
            instrument_token=int(instrument_token),
            client=data_client,
            db_path=db_path,
        )
        results.append(result)

    first = results[0] if results else {}
    return {
        "status": "SUCCESS" if all(item.get("status") in {"SUCCESS", "EMPTY"} for item in results) else "PARTIAL",
        "source_key": "ZERODHA_KITE_CONNECT_MARKET_DATA_ONLY",
        "series_id": first.get("series_id"),
        "interval": first.get("interval"),
        "price_mode": first.get("price_mode", "RAW_UNADJUSTED"),
        "credential_role": "MARKET_DATA_ONLY",
        "order_api_enabled": False,
        "exchange": exchange.upper(),
        "symbol": symbol.upper(),
        "kite_interval": interval,
        "instrument_token": int(instrument_token),
        "range_start": _aware(from_time).isoformat(),
        "range_end": _aware(to_time).isoformat(),
        "chunk_days": CONSERVATIVE_CHUNK_DAYS[interval],
        "chunks": len(results),
        "rows_received": sum(int(item.get("rows_received") or 0) for item in results),
        "bars_inserted": sum(int(item.get("bars_inserted") or 0) for item in results),
        "bars_updated": sum(int(item.get("bars_updated") or 0) for item in results),
        "quality_issues_reported_across_chunks": sum(int(item.get("quality_issues") or 0) for item in results),
        "fetch_ids": [item.get("fetch_id") for item in results],
        "chunk_results": results,
        "range_is_single_opaque_vendor_request": False,
        "api_governor": "KITE_CLIENT_INTERNAL_V1" if rate_limit_sleep_seconds is None else "KITE_CLIENT_INTERNAL_PLUS_EXPLICIT_INTER_CHUNK_PACING",
    }
