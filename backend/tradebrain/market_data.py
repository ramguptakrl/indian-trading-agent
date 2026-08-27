"""Phase 3 market-data ingestion, validation, and look-ahead-safe derivation.

Yahoo Finance via yfinance is the initial pluggable vendor because the upstream repo
already depends on it. It is explicitly NON-OFFICIAL. We archive a canonical
normalized vendor snapshot (not falsely labelled raw HTTP bytes), hash it, and keep
source/fetch metadata so another Indian market-data or broker adapter can be added
without changing the replay store.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from backend.tradebrain.market_data_store import (
    ensure_series,
    find_series,
    get_series,
    latest_bar_time,
    query_bars,
    rebuild_vendor_split_eras,
    record_fetch,
    replace_issues,
    upsert_bars,
    upsert_corporate_actions,
)
from backend.tradebrain.store import upsert_source

IST = ZoneInfo("Asia/Kolkata")
YAHOO_SOURCE_KEY = "YAHOO_FINANCE_VIA_YFINANCE"
YAHOO_BASE_URL = "https://finance.yahoo.com/"
SNAPSHOT_VERSION = "tradebrain-market-snapshot-v1"

INTERVAL_SECONDS = {
    "1m": 60,
    "2m": 120,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "60m": 3600,
    "1h": 3600,
    "90m": 5400,
}
DERIVABLE_INTERVALS = {"5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "2h": 7200, "4h": 14400}
SESSION_OPEN = time(9, 15)
SESSION_CLOSE = time(15, 30)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _data_root() -> Path:
    configured = os.getenv("TRADEBRAIN_DATA_DIR")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".tradingagents" / "tradebrain"


def yahoo_symbol(exchange: str, symbol: str) -> str:
    exchange = exchange.strip().upper()
    symbol = symbol.strip().upper()
    if symbol.endswith(".NS") or symbol.endswith(".BO"):
        return symbol
    if exchange == "NSE":
        return f"{symbol}.NS"
    if exchange == "BSE":
        return f"{symbol}.BO"
    raise ValueError("exchange must be NSE or BSE")


def _aware(value: Any) -> datetime:
    if hasattr(value, "to_pydatetime"):
        value = value.to_pydatetime()
    if not isinstance(value, datetime):
        raise TypeError(f"Unsupported market-data timestamp type: {type(value).__name__}")
    if value.tzinfo is None:
        value = value.replace(tzinfo=IST)
    return value


def _daily_times(value: datetime) -> tuple[datetime, datetime]:
    local = value.astimezone(IST)
    day = local.date()
    return (
        datetime.combine(day, SESSION_OPEN, tzinfo=IST).astimezone(timezone.utc),
        datetime.combine(day, SESSION_CLOSE, tzinfo=IST).astimezone(timezone.utc),
    )


def _bar_times(value: Any, interval: str) -> tuple[datetime, datetime]:
    dt = _aware(value)
    if interval == "1d":
        return _daily_times(dt)
    seconds = INTERVAL_SECONDS.get(interval)
    if seconds is None:
        raise ValueError(f"Unsupported direct vendor interval: {interval}")
    opened = dt.astimezone(timezone.utc)
    return opened, opened + timedelta(seconds=seconds)


def _finite_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def normalize_yfinance_frame(frame: Any, interval: str, *, fetched_at: datetime | None = None) -> tuple[list[dict], list[dict], list[dict]]:
    """Normalize a yfinance DataFrame without making adjusted-price assumptions."""
    fetched_at = fetched_at or _utc_now()
    bars_by_ts: dict[str, dict[str, Any]] = {}
    issues: list[dict] = []
    actions: list[dict] = []

    if frame is None or getattr(frame, "empty", True):
        return [], [], []

    for idx, row in frame.iterrows():
        try:
            opened, closed = _bar_times(idx, interval)
        except Exception as exc:
            issues.append({
                "issue_type": "TIMESTAMP_PARSE_ERROR", "severity": "ERROR",
                "details": {"timestamp": str(idx), "error": str(exc)},
            })
            continue

        o = _finite_number(row.get("Open"))
        h = _finite_number(row.get("High"))
        l = _finite_number(row.get("Low"))
        c = _finite_number(row.get("Close"))
        v = _finite_number(row.get("Volume"))
        ts_open = opened.isoformat()
        ts_close = closed.isoformat()

        if None in {o, h, l, c}:
            issues.append({
                "issue_type": "NON_NUMERIC_OHLC", "severity": "ERROR",
                "ts_start": ts_open, "ts_end": ts_close,
            })
            continue
        if h < max(o, c) or l > min(o, c) or h < l or min(o, h, l, c) <= 0:
            issues.append({
                "issue_type": "INVALID_OHLC_GEOMETRY", "severity": "ERROR",
                "ts_start": ts_open, "ts_end": ts_close,
                "details": {"open": o, "high": h, "low": l, "close": c},
            })
            continue
        if v is None or v < 0:
            issues.append({
                "issue_type": "INVALID_VOLUME", "severity": "WARNING",
                "ts_start": ts_open, "ts_end": ts_close, "details": {"volume": v},
            })
            v = 0.0

        if ts_open in bars_by_ts:
            issues.append({
                "issue_type": "DUPLICATE_TIMESTAMP_IN_FETCH", "severity": "ERROR",
                "ts_start": ts_open, "ts_end": ts_close,
            })

        bars_by_ts[ts_open] = {
            "ts_open": ts_open,
            "ts_close": ts_close,
            "open": o,
            "high": h,
            "low": l,
            "close": c,
            "volume": v or 0.0,
            "source_timestamp": ts_open,
            "is_final": closed <= fetched_at,
            "quality_flags": [],
        }

        dividend = _finite_number(row.get("Dividends")) or 0.0
        split = _finite_number(row.get("Stock Splits")) or 0.0
        if dividend:
            actions.append({
                "action_type": "DIVIDEND", "effective_at": ts_open, "value": dividend,
                "metadata": {"origin": "yfinance history(actions=True)"},
            })
        if split:
            actions.append({
                "action_type": "SPLIT", "effective_at": ts_open, "value": split,
                "metadata": {"origin": "yfinance history(actions=True)"},
            })

    bars = [bars_by_ts[key] for key in sorted(bars_by_ts)]
    return bars, issues, actions


def validate_bars(bars: list[dict[str, Any]], interval: str) -> list[dict[str, Any]]:
    """Validate geometry/session/intraday continuity without inventing holidays."""
    issues: list[dict[str, Any]] = []
    expected = INTERVAL_SECONDS.get(interval)
    previous: dict[str, Any] | None = None

    for bar in bars:
        opened = datetime.fromisoformat(bar["ts_open"])
        closed = datetime.fromisoformat(bar["ts_close"])
        local = opened.astimezone(IST)
        if interval != "1d" and not (SESSION_OPEN <= local.time() < SESSION_CLOSE):
            issues.append({
                "issue_type": "OUTSIDE_REGULAR_SESSION", "severity": "WARNING",
                "ts_start": bar["ts_open"], "ts_end": bar["ts_close"],
                "details": {"calendar_verified": False, "session": "09:15-15:30 Asia/Kolkata"},
            })
        if closed <= opened:
            issues.append({
                "issue_type": "NON_POSITIVE_BAR_DURATION", "severity": "ERROR",
                "ts_start": bar["ts_open"], "ts_end": bar["ts_close"],
            })
        if previous and expected:
            prev_open = datetime.fromisoformat(previous["ts_open"])
            prev_local = prev_open.astimezone(IST)
            if prev_local.date() == local.date():
                delta = int((opened - prev_open).total_seconds())
                if delta > expected:
                    missing = max(0, delta // expected - 1)
                    issues.append({
                        "issue_type": "INTRADAY_GAP", "severity": "WARNING",
                        "ts_start": previous["ts_close"], "ts_end": bar["ts_open"],
                        "details": {"expected_seconds": expected, "observed_seconds": delta, "estimated_missing_bars": missing},
                    })
                elif delta < expected:
                    issues.append({
                        "issue_type": "IRREGULAR_INTRADAY_SPACING", "severity": "WARNING",
                        "ts_start": previous["ts_open"], "ts_end": bar["ts_open"],
                        "details": {"expected_seconds": expected, "observed_seconds": delta},
                    })
        previous = bar

    return issues


def _canonical_snapshot(series: dict[str, Any], interval: str, bars: list[dict], actions: list[dict], fetched_at: datetime) -> tuple[bytes, str]:
    payload = {
        "snapshot_version": SNAPSHOT_VERSION,
        "source_key": YAHOO_SOURCE_KEY,
        "source_symbol": series["source_symbol"],
        "exchange": series["exchange"],
        "symbol": series["symbol"],
        "isin": series.get("isin"),
        "interval": interval,
        "price_mode": series["price_mode"],
        "fetched_at": fetched_at.isoformat(),
        "bars": bars,
        "actions": actions,
    }
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8")
    return encoded, hashlib.sha256(encoded).hexdigest()


def _archive_snapshot(series_id: str, interval: str, payload: bytes, digest: str) -> str:
    directory = _data_root() / "market_data" / "vendor_snapshots" / "yahoo"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{series_id.replace(':', '_')}_{interval}_{digest}.json"
    if not path.exists():
        path.write_bytes(payload)
    return str(path)


def sync_yahoo_history(
    *,
    exchange: str,
    symbol: str,
    interval: str = "1d",
    start: str | datetime | None = None,
    end: str | datetime | None = None,
    incremental: bool = True,
    overlap_bars: int = 2,
    db_path: str | None = None,
) -> dict[str, Any]:
    """Fetch raw/unadjusted yfinance history and persist an auditable snapshot."""
    if interval not in {*INTERVAL_SECONDS.keys(), "1d"}:
        raise ValueError(f"Unsupported Yahoo interval for Phase 3: {interval}")

    source_symbol = yahoo_symbol(exchange, symbol)
    series = ensure_series(
        exchange=exchange,
        symbol=symbol,
        source_key=YAHOO_SOURCE_KEY,
        source_symbol=source_symbol,
        price_mode="RAW_UNADJUSTED",
        base_interval=interval,
        source_metadata={"adapter": "yfinance", "official": False, "auto_adjust": False},
        db_path=db_path,
    )
    upsert_source(
        YAHOO_SOURCE_KEY,
        "Yahoo Finance via yfinance",
        source_type="MARKET_DATA_VENDOR",
        base_url=YAHOO_BASE_URL,
        is_official=False,
        db_path=db_path,
    )

    requested_start = start
    if incremental:
        latest = latest_bar_time(series["series_id"], interval, db_path=db_path)
        if latest:
            latest_dt = datetime.fromisoformat(latest)
            step = timedelta(seconds=INTERVAL_SECONDS.get(interval, 86400))
            candidate = latest_dt - step * max(1, overlap_bars)
            if requested_start is None:
                requested_start = candidate
            else:
                parsed = datetime.fromisoformat(requested_start) if isinstance(requested_start, str) else requested_start
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                if candidate > parsed:
                    requested_start = candidate

    if requested_start is None:
        # Conservative bootstrap; callers can explicitly request deeper history.
        days = 30 if interval != "1d" else 3650
        requested_start = _utc_now() - timedelta(days=days)
    if end is None:
        end = _utc_now() + timedelta(days=1)

    fetched_at = _utc_now()
    try:
        import yfinance as yf

        ticker = yf.Ticker(source_symbol)
        frame = ticker.history(
            start=requested_start,
            end=end,
            interval=interval,
            auto_adjust=False,
            actions=True,
        )
        bars, parse_issues, actions = normalize_yfinance_frame(frame, interval, fetched_at=fetched_at)
        validation_issues = validate_bars(bars, interval)
        issues = parse_issues + validation_issues
        snapshot, digest = _canonical_snapshot(series, interval, bars, actions, fetched_at)
        archive_path = _archive_snapshot(series["series_id"], interval, snapshot, digest)

        fetch_id = record_fetch(
            series_id=series["series_id"], source_key=YAHOO_SOURCE_KEY, interval=interval,
            requested_start=str(requested_start), requested_end=str(end), fetched_at=fetched_at.isoformat(),
            source_payload_sha256=digest, archive_path=archive_path, rows_received=len(bars),
            status="SUCCESS" if bars else "EMPTY", notes="Canonical normalized vendor snapshot; not raw Yahoo HTTP bytes",
            db_path=db_path,
        )
        writes = upsert_bars(
            series["series_id"], interval, bars, source_key=YAHOO_SOURCE_KEY,
            ingested_at=fetched_at.isoformat(), db_path=db_path,
        ) if bars else {"bars_inserted": 0, "bars_updated": 0}
        replace_issues(series["series_id"], interval, issues, db_path=db_path)
        action_count = upsert_corporate_actions(
            series["series_id"], actions, source_key=YAHOO_SOURCE_KEY,
            verification_status="VENDOR_REPORTED", db_path=db_path,
        ) if actions else 0
        era_result = rebuild_vendor_split_eras(series["series_id"], db_path=db_path)
        return {
            "status": "SUCCESS" if bars else "EMPTY",
            "series_id": series["series_id"],
            "fetch_id": fetch_id,
            "source_key": YAHOO_SOURCE_KEY,
            "source_official": False,
            "source_symbol": source_symbol,
            "price_mode": "RAW_UNADJUSTED",
            "interval": interval,
            "rows_received": len(bars),
            **writes,
            "quality_issues": len(issues),
            "corporate_actions": action_count,
            "vendor_split_eras": era_result,
            "snapshot_sha256": digest,
            "snapshot_kind": "NORMALIZED_VENDOR_SNAPSHOT",
            "archive_path": archive_path,
            "no_lookahead_contract": "Replay exposes only bars with ts_close <= as_of",
        }
    except Exception as exc:
        record_fetch(
            series_id=series["series_id"], source_key=YAHOO_SOURCE_KEY, interval=interval,
            requested_start=str(requested_start), requested_end=str(end), fetched_at=fetched_at.isoformat(),
            source_payload_sha256=None, archive_path=None, rows_received=0, status="FAILED",
            notes=f"{type(exc).__name__}: {exc}", db_path=db_path,
        )
        raise


def _bucket_intraday(dt_utc: datetime, target_seconds: int) -> tuple[datetime, datetime]:
    local = dt_utc.astimezone(IST)
    session_start = datetime.combine(local.date(), SESSION_OPEN, tzinfo=IST)
    delta = int((local - session_start).total_seconds())
    bucket_index = max(0, delta // target_seconds)
    opened = session_start + timedelta(seconds=bucket_index * target_seconds)
    closed = opened + timedelta(seconds=target_seconds)
    session_end = datetime.combine(local.date(), SESSION_CLOSE, tzinfo=IST)
    if closed > session_end:
        closed = session_end
    return opened.astimezone(timezone.utc), closed.astimezone(timezone.utc)


def derive_timeframe(
    series_id: str,
    *,
    source_interval: str,
    target_interval: str,
    as_of: str | None = None,
    db_path: str | None = None,
) -> dict[str, Any]:
    """Derive completed higher-timeframe candles without future source bars."""
    if target_interval not in {*DERIVABLE_INTERVALS.keys(), "1d", "1w"}:
        raise ValueError(f"Unsupported derived interval: {target_interval}")
    source = query_bars(series_id, source_interval, as_of=as_of, limit=500000, db_path=db_path)
    if not source:
        return {"series_id": series_id, "source_interval": source_interval, "target_interval": target_interval, "derived": 0}

    buckets: dict[str, dict[str, Any]] = {}
    for bar in source:
        opened = datetime.fromisoformat(bar["ts_open"])
        local = opened.astimezone(IST)
        if target_interval in DERIVABLE_INTERVALS:
            b_open, b_close = _bucket_intraday(opened, DERIVABLE_INTERVALS[target_interval])
        elif target_interval == "1d":
            b_open = datetime.combine(local.date(), SESSION_OPEN, tzinfo=IST).astimezone(timezone.utc)
            b_close = datetime.combine(local.date(), SESSION_CLOSE, tzinfo=IST).astimezone(timezone.utc)
        else:  # 1w, Monday-anchored Indian trading week
            monday = local.date() - timedelta(days=local.weekday())
            b_open = datetime.combine(monday, SESSION_OPEN, tzinfo=IST).astimezone(timezone.utc)
            friday = monday + timedelta(days=4)
            b_close = datetime.combine(friday, SESSION_CLOSE, tzinfo=IST).astimezone(timezone.utc)

        key = b_open.isoformat()
        item = buckets.get(key)
        if item is None:
            buckets[key] = {
                "ts_open": key,
                "ts_close": b_close.isoformat(),
                "open": bar["open"], "high": bar["high"], "low": bar["low"], "close": bar["close"],
                "volume": bar["volume"], "source_timestamp": bar["ts_close"], "is_final": True,
                "quality_flags": ["DERIVED_LOOKAHEAD_SAFE"],
            }
        else:
            item["high"] = max(item["high"], bar["high"])
            item["low"] = min(item["low"], bar["low"])
            item["close"] = bar["close"]
            item["volume"] += bar["volume"]
            item["source_timestamp"] = bar["ts_close"]

    cutoff = datetime.fromisoformat(as_of) if as_of else None
    derived = []
    for item in buckets.values():
        # A derived bar exists in replay only when its own bucket is complete.
        if cutoff and datetime.fromisoformat(item["ts_close"]) > cutoff:
            continue
        derived.append(item)
    derived.sort(key=lambda x: x["ts_open"])

    result = upsert_bars(
        series_id, target_interval, derived,
        source_key=f"DERIVED:{source_interval}",
        is_derived=True, derived_from_interval=source_interval, db_path=db_path,
    ) if derived else {"bars_inserted": 0, "bars_updated": 0}
    return {
        "series_id": series_id,
        "source_interval": source_interval,
        "target_interval": target_interval,
        "source_bars": len(source),
        "derived": len(derived),
        **result,
        "lookahead_safe": True,
        "partial_target_bar_excluded": bool(as_of),
    }


def derive_standard_timeframes(
    series_id: str,
    *,
    source_interval: str = "1m",
    as_of: str | None = None,
    db_path: str | None = None,
) -> dict[str, Any]:
    targets = ["5m", "15m", "30m", "1h", "2h", "4h", "1d", "1w"]
    return {
        "series_id": series_id,
        "source_interval": source_interval,
        "results": {
            target: derive_timeframe(
                series_id, source_interval=source_interval, target_interval=target,
                as_of=as_of, db_path=db_path,
            )
            for target in targets
            if target != source_interval
        },
    }
