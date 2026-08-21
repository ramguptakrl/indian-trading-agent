"""TradingAgents-compatible OHLCV/indicator provider backed by Trade Brain.

This preserves upstream tool contracts while making Trade Brain's price-source policy
authoritative: Kite historical data when credentials are configured, otherwise an
explicitly-labelled Yahoo fallback. Price-derived technical indicators are calculated
from the same audited daily OHLCV rather than silently fetching a second price source.
"""

from __future__ import annotations

import csv
import io
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
from stockstats import wrap

from backend.tradebrain.market_data_store import query_bars
from backend.tradebrain.market_source_policy import sync_preferred_history
from .config import get_config

IST = ZoneInfo("Asia/Kolkata")
SUPPORTED_INDICATORS = {
    "close_10_ema", "close_50_sma", "close_200_sma",
    "macd", "macds", "macdh", "rsi",
    "boll", "boll_ub", "boll_lb", "atr", "vwma", "mfi",
}


def _identity(symbol: str) -> tuple[str, str]:
    value = symbol.strip().upper()
    if ":" in value:
        exchange, ticker = value.split(":", 1)
        if exchange not in {"NSE", "BSE"} or not ticker:
            raise ValueError(f"Unsupported Indian market symbol: {symbol}")
        return exchange, ticker
    if value.endswith(".NS"):
        return "NSE", value[:-3]
    if value.endswith(".BO"):
        return "BSE", value[:-3]
    exchange = str(get_config().get("default_exchange") or "NSE").upper()
    if exchange not in {"NSE", "BSE"}:
        exchange = "NSE"
    return exchange, value


def _day(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def _rows_for_range(series_id: str, interval: str, start: date, end: date) -> list[tuple[date, dict]]:
    rows = query_bars(series_id, interval, limit=500000)
    selected: list[tuple[date, dict]] = []
    for row in rows:
        opened = datetime.fromisoformat(row["ts_open"])
        if opened.tzinfo is None:
            opened = opened.replace(tzinfo=IST)
        day = opened.astimezone(IST).date()
        if start <= day < end:
            selected.append((day, row))
    return selected


def get_tradebrain_stock_data(symbol: str, start_date: str, end_date: str) -> str:
    """Return CSV OHLCV in the shape expected by the upstream analyst tools."""
    start = _day(start_date)
    end = _day(end_date)
    if end <= start:
        raise ValueError("end_date must be after start_date")
    exchange, ticker = _identity(symbol)
    result = sync_preferred_history(
        exchange=exchange,
        symbol=ticker,
        interval="1d",
        from_time=f"{start_date}T00:00:00+05:30",
        to_time=f"{end_date}T23:59:59+05:30",
        allow_yahoo_fallback=True,
    )
    series_id = result.get("series_id")
    interval = result.get("interval") or "1d"
    if not series_id:
        return f"No data found for symbol '{symbol}' between {start_date} and {end_date}"
    selected = _rows_for_range(series_id, interval, start, end)
    if not selected:
        return f"No data found for symbol '{symbol}' between {start_date} and {end_date}"

    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["Date", "Open", "High", "Low", "Close", "Volume"])
    for day, row in selected:
        writer.writerow([
            day.isoformat(),
            round(float(row["open"]), 2),
            round(float(row["high"]), 2),
            round(float(row["low"]), 2),
            round(float(row["close"]), 2),
            int(float(row.get("volume") or 0)),
        ])

    source = result.get("source_key")
    fallback = bool(result.get("fallback_used"))
    header = (
        f"# Stock data for {exchange}:{ticker} from {start_date} to {end_date}\n"
        f"# Total records: {len(selected)}\n"
        f"# Trade Brain source: {source}\n"
        f"# Yahoo fallback used: {str(fallback).lower()}\n"
        f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
    )
    return header + out.getvalue()


def get_tradebrain_indicator(symbol: str, indicator: str, curr_date: str, look_back_days: int) -> str:
    """Calculate a stockstats indicator from the same audited daily price source."""
    if indicator not in SUPPORTED_INDICATORS:
        raise ValueError(f"Indicator {indicator} is not supported by Trade Brain")
    if look_back_days <= 0:
        raise ValueError("look_back_days must be positive")
    current = _day(curr_date)
    history_start = current - timedelta(days=max(420, look_back_days + 60))
    history_end = current + timedelta(days=1)
    exchange, ticker = _identity(symbol)
    result = sync_preferred_history(
        exchange=exchange,
        symbol=ticker,
        interval="1d",
        from_time=f"{history_start.isoformat()}T00:00:00+05:30",
        to_time=f"{history_end.isoformat()}T23:59:59+05:30",
        allow_yahoo_fallback=True,
    )
    series_id = result.get("series_id")
    interval = result.get("interval") or "1d"
    if not series_id:
        return f"No data available to calculate {indicator} for {symbol}"
    selected = _rows_for_range(series_id, interval, history_start, history_end)
    if not selected:
        return f"No data available to calculate {indicator} for {symbol}"

    records = [
        {
            "date": day.isoformat(),
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "volume": float(row.get("volume") or 0),
        }
        for day, row in selected
    ]
    frame = wrap(pd.DataFrame(records))
    values = frame[indicator].tolist()
    by_day: dict[str, str] = {}
    for idx, record in enumerate(records):
        value = values[idx]
        by_day[record["date"]] = "N/A" if pd.isna(value) else str(value)

    window_start = current - timedelta(days=look_back_days)
    lines = []
    cursor = current
    while cursor >= window_start:
        key = cursor.isoformat()
        lines.append(f"{key}: {by_day.get(key, 'N/A: Not a completed trading day')}")
        cursor -= timedelta(days=1)

    source = result.get("source_key")
    fallback = bool(result.get("fallback_used"))
    return (
        f"## {indicator} values from {window_start.isoformat()} to {curr_date}:\n\n"
        + "\n".join(lines)
        + "\n\n"
        + f"Calculated from Trade Brain audited daily OHLCV. Source: {source}. "
        + f"Yahoo fallback used: {str(fallback).lower()}."
    )
