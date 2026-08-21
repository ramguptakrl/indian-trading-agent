"""TradingAgents-compatible core OHLCV provider backed by Trade Brain.

This preserves the upstream `get_stock_data(symbol, start, end)` contract while making
Trade Brain's source policy authoritative: Kite historical data when credentials are
configured, otherwise explicitly-labelled Yahoo fallback.
"""

from __future__ import annotations

import csv
import io
from datetime import date, datetime
from zoneinfo import ZoneInfo

from backend.tradebrain.market_data_store import query_bars
from backend.tradebrain.market_source_policy import sync_preferred_history
from .config import get_config

IST = ZoneInfo("Asia/Kolkata")


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
    rows = query_bars(series_id, interval, limit=500000)

    selected = []
    for row in rows:
        opened = datetime.fromisoformat(row["ts_open"])
        if opened.tzinfo is None:
            opened = opened.replace(tzinfo=IST)
        day = opened.astimezone(IST).date()
        if start <= day < end:
            selected.append((day, row))
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
