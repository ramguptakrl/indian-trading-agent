"""Zerodha Kite Connect adapter restricted to market-data transport only.

The modeled trader remains RESIDENT_INDIAN even if the credential used here belongs
to an NRI account. This module deliberately exposes no order, position, margin or
portfolio mutation methods. It may retrieve instrument masters, quotes and historical
candles, then persist historical candles into the audited Phase-3 store.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import os
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import requests

from backend.tradebrain.api_governor import KITE_API_GOVERNOR, kite_bucket_for_path
from backend.tradebrain.market_data import validate_bars
from backend.tradebrain.market_data_store import (
    ensure_series,
    record_fetch,
    replace_issues,
    upsert_bars,
)
from backend.tradebrain.store import upsert_source

IST = ZoneInfo("Asia/Kolkata")
KITE_SOURCE_KEY = "ZERODHA_KITE_CONNECT_MARKET_DATA_ONLY"
KITE_BASE_URL = "https://api.kite.trade"
KITE_DOCS_URL = "https://kite.trade/docs/connect/v3/"
SNAPSHOT_VERSION = "tradebrain-kite-market-snapshot-v1"
SESSION_OPEN = time(9, 15)
SESSION_CLOSE = time(15, 30)

KITE_TO_INTERNAL_INTERVAL = {
    "minute": "1m",
    "3minute": "3m",
    "5minute": "5m",
    "10minute": "10m",
    "15minute": "15m",
    "30minute": "30m",
    "60minute": "60m",
    "day": "1d",
}
INTERVAL_SECONDS = {
    "minute": 60,
    "3minute": 180,
    "5minute": 300,
    "10minute": 600,
    "15minute": 900,
    "30minute": 1800,
    "60minute": 3600,
}


def kite_data_boundary() -> dict[str, Any]:
    return {
        "trader_profile": "RESIDENT_INDIAN",
        "credential_account_type_may_be_nri": True,
        "credential_role": "MARKET_DATA_ONLY",
        "allowed": ["INSTRUMENT_MASTER", "LIVE_QUOTES", "HISTORICAL_CANDLES", "BACKTEST_INPUT"],
        "prohibited": ["ORDER_PLACEMENT", "ORDER_MODIFICATION", "ORDER_CANCELLATION", "POSITION_MUTATION", "MARGIN_INFERENCE"],
        "order_api_enabled": False,
        "credential_account_type_affects_policy": False,
        "credential_account_type_affects_cost_profile": False,
        "rest_governor": "KITE_READ_ONLY_PROCESS_LOCAL_V1",
    }


def _data_root() -> Path:
    configured = os.getenv("TRADEBRAIN_DATA_DIR")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".tradingagents" / "tradebrain"


class KiteDataOnlyClient:
    """Small REST client intentionally limited to read-only market-data endpoints."""

    def __init__(
        self,
        api_key: str | None = None,
        access_token: str | None = None,
        *,
        session: requests.Session | None = None,
        timeout: float = 20.0,
    ) -> None:
        self.api_key = (api_key or os.getenv("KITE_API_KEY") or "").strip()
        self.access_token = (access_token or os.getenv("KITE_ACCESS_TOKEN") or "").strip()
        if not self.api_key or not self.access_token:
            raise ValueError("Kite market-data access requires api_key and access_token")
        self.session = session or requests.Session()
        self.timeout = timeout

    @property
    def boundary(self) -> dict[str, Any]:
        return kite_data_boundary()

    def _headers(self) -> dict[str, str]:
        return {
            "X-Kite-Version": "3",
            "Authorization": f"token {self.api_key}:{self.access_token}",
            "Accept": "application/json,text/csv,*/*",
            "User-Agent": "TradeBrain/market-data-only",
        }

    def _get(self, path: str, *, params: Any = None, expect_json: bool = True) -> Any:
        """Govern every Kite REST read and retry only transient/capacity failures."""
        bucket = kite_bucket_for_path(path)
        rule = KITE_API_GOVERNOR.rule(bucket)
        response = None
        for attempt in range(rule.max_retries + 1):
            KITE_API_GOVERNOR.wait_for_slot(bucket)
            response = self.session.get(
                f"{KITE_BASE_URL}{path}", headers=self._headers(), params=params, timeout=self.timeout
            )
            status = int(getattr(response, "status_code", 200) or 200)
            if status not in {429, 502, 503, 504} or attempt >= rule.max_retries:
                break
            KITE_API_GOVERNOR.register_retry(
                bucket,
                attempt=attempt,
                headers=getattr(response, "headers", None),
            )
        if response is None:  # pragma: no cover - defensive guard
            raise RuntimeError("Kite REST request produced no response")
        response.raise_for_status()
        if not expect_json:
            return response.text
        payload = response.json()
        if not isinstance(payload, dict) or payload.get("status") != "success":
            raise ValueError(f"Unexpected Kite market-data response for {path}")
        return payload.get("data")

    def instruments(self, exchange: str | None = None) -> list[dict[str, str]]:
        ex = exchange.strip().upper() if exchange else None
        if ex and ex not in {"NSE", "BSE"}:
            raise ValueError("Kite equity data adapter supports NSE or BSE")
        path = f"/instruments/{ex}" if ex else "/instruments"
        text = self._get(path, expect_json=False)
        rows = list(csv.DictReader(io.StringIO(text)))
        return rows

    def resolve_equity_instrument(self, exchange: str, symbol: str) -> dict[str, Any]:
        ex = exchange.strip().upper()
        sym = symbol.strip().upper()
        matches = [
            row for row in self.instruments(ex)
            if str(row.get("exchange") or "").upper() == ex
            and str(row.get("tradingsymbol") or "").upper() == sym
            and str(row.get("instrument_type") or "").upper() == "EQ"
        ]
        if len(matches) != 1:
            raise ValueError(f"Expected exactly one Kite EQ instrument for {ex}:{sym}; found {len(matches)}")
        row = dict(matches[0])
        try:
            row["instrument_token"] = int(row["instrument_token"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Kite instrument row has invalid instrument_token") from exc
        return row

    def quote(self, instruments: list[str], *, kind: str = "full") -> dict[str, Any]:
        if not instruments:
            raise ValueError("At least one exchange:tradingsymbol is required")
        normalized = [str(item).strip().upper() for item in instruments]
        if any(":" not in item for item in normalized):
            raise ValueError("Quotes require exact exchange:tradingsymbol identifiers")
        kind = kind.lower()
        path_limit = {
            "full": ("/quote", 500),
            "ohlc": ("/quote/ohlc", 1000),
            "ltp": ("/quote/ltp", 1000),
        }
        if kind not in path_limit:
            raise ValueError("kind must be full, ohlc or ltp")
        path, limit = path_limit[kind]
        if len(normalized) > limit:
            raise ValueError(f"Kite {kind} quote request exceeds documented limit {limit}")
        data = self._get(path, params=[("i", item) for item in normalized])
        if not isinstance(data, dict):
            raise ValueError("Kite quote data must be an object")
        return data

    def historical(
        self,
        *,
        instrument_token: int,
        interval: str,
        from_time: str | datetime,
        to_time: str | datetime,
        continuous: bool = False,
        oi: bool = False,
    ) -> list[list[Any]]:
        interval = interval.strip().lower()
        if interval not in KITE_TO_INTERNAL_INTERVAL:
            raise ValueError(f"Unsupported Kite historical interval: {interval}")
        token = int(instrument_token)
        params = {
            "from": _kite_time(from_time),
            "to": _kite_time(to_time),
            "continuous": 1 if continuous else 0,
            "oi": 1 if oi else 0,
        }
        data = self._get(f"/instruments/historical/{token}/{interval}", params=params)
        candles = data.get("candles") if isinstance(data, dict) else None
        if not isinstance(candles, list):
            raise ValueError("Kite historical response is missing candles")
        return candles


def _kite_time(value: str | datetime) -> str:
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value)
    else:
        parsed = value
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=IST)
    return parsed.astimezone(IST).strftime("%Y-%m-%d %H:%M:%S")


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def normalize_kite_candles(
    candles: list[list[Any]], interval: str, *, fetched_at: datetime | None = None
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    fetched_at = fetched_at or datetime.now(timezone.utc)
    internal = KITE_TO_INTERNAL_INTERVAL.get(interval)
    if internal is None:
        raise ValueError(f"Unsupported Kite interval: {interval}")
    bars: dict[str, dict[str, Any]] = {}
    issues: list[dict[str, Any]] = []
    for raw in candles:
        if not isinstance(raw, list) or len(raw) < 6:
            issues.append({"issue_type": "MALFORMED_KITE_CANDLE", "severity": "ERROR", "details": {"row": raw}})
            continue
        try:
            opened = datetime.fromisoformat(str(raw[0]))
        except ValueError:
            try:
                opened = datetime.strptime(str(raw[0]), "%Y-%m-%dT%H:%M:%S%z")
            except ValueError:
                issues.append({"issue_type": "TIMESTAMP_PARSE_ERROR", "severity": "ERROR", "details": {"timestamp": str(raw[0])}})
                continue
        if opened.tzinfo is None:
            opened = opened.replace(tzinfo=IST)
        opened_utc = opened.astimezone(timezone.utc)
        if interval == "day":
            local_day = opened.astimezone(IST).date()
            opened_utc = datetime.combine(local_day, SESSION_OPEN, tzinfo=IST).astimezone(timezone.utc)
            closed_utc = datetime.combine(local_day, SESSION_CLOSE, tzinfo=IST).astimezone(timezone.utc)
        else:
            closed_utc = opened_utc + timedelta(seconds=INTERVAL_SECONDS[interval])
        o, h, l, c, v = (_finite(raw[i]) for i in range(1, 6))
        if None in {o, h, l, c}:
            issues.append({"issue_type": "NON_NUMERIC_OHLC", "severity": "ERROR", "ts_start": opened_utc.isoformat()})
            continue
        if h < max(o, c) or l > min(o, c) or h < l or min(o, h, l, c) <= 0:
            issues.append({"issue_type": "INVALID_OHLC_GEOMETRY", "severity": "ERROR", "ts_start": opened_utc.isoformat()})
            continue
        if v is None or v < 0:
            issues.append({"issue_type": "INVALID_VOLUME", "severity": "WARNING", "ts_start": opened_utc.isoformat()})
            v = 0.0
        key = opened_utc.isoformat()
        if key in bars:
            issues.append({"issue_type": "DUPLICATE_TIMESTAMP_IN_FETCH", "severity": "ERROR", "ts_start": key})
        bars[key] = {
            "ts_open": key,
            "ts_close": closed_utc.isoformat(),
            "open": o,
            "high": h,
            "low": l,
            "close": c,
            "volume": v or 0.0,
            "source_timestamp": str(raw[0]),
            "is_final": closed_utc <= fetched_at,
            "quality_flags": ["KITE_MARKET_DATA_ONLY"],
        }
    output = [bars[key] for key in sorted(bars)]
    return output, issues


def _archive_snapshot(payload: bytes, digest: str) -> str:
    directory = _data_root() / "market_data" / "vendor_snapshots" / "kite"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"kite_{digest}.json"
    if not path.exists():
        path.write_bytes(payload)
    return str(path)


def sync_kite_history(
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
    db_path: str | None = None,
) -> dict[str, Any]:
    """Persist Kite historical equity candles into the same audited replay store."""

    ex = exchange.strip().upper()
    sym = symbol.strip().upper()
    if ex not in {"NSE", "BSE"}:
        raise ValueError("exchange must be NSE or BSE")
    if interval not in KITE_TO_INTERNAL_INTERVAL:
        raise ValueError(f"Unsupported Kite interval: {interval}")
    data_client = client or KiteDataOnlyClient(api_key, access_token)
    instrument = None
    if instrument_token is None:
        instrument = data_client.resolve_equity_instrument(ex, sym)
        instrument_token = int(instrument["instrument_token"])

    internal_interval = KITE_TO_INTERNAL_INTERVAL[interval]
    source_symbol = f"{ex}:{sym}"
    series = ensure_series(
        exchange=ex,
        symbol=sym,
        source_key=KITE_SOURCE_KEY,
        source_symbol=source_symbol,
        price_mode="RAW_UNADJUSTED",
        base_interval=internal_interval,
        source_metadata={
            "adapter": "Kite Connect REST",
            "official": False,
            "credential_role": "MARKET_DATA_ONLY",
            "credential_account_type_affects_policy": False,
            "instrument_token": int(instrument_token),
        },
        db_path=db_path,
    )
    upsert_source(
        KITE_SOURCE_KEY,
        "Zerodha Kite Connect market data only",
        source_type="BROKER_MARKET_DATA_VENDOR",
        base_url=KITE_BASE_URL,
        is_official=False,
        db_path=db_path,
    )

    fetched_at = datetime.now(timezone.utc)
    try:
        candles = data_client.historical(
            instrument_token=int(instrument_token), interval=interval,
            from_time=from_time, to_time=to_time, continuous=False, oi=False,
        )
        bars, parse_issues = normalize_kite_candles(candles, interval, fetched_at=fetched_at)
        issues = parse_issues + validate_bars(bars, internal_interval)
        snapshot_obj = {
            "snapshot_version": SNAPSHOT_VERSION,
            "source_key": KITE_SOURCE_KEY,
            "source_symbol": source_symbol,
            "instrument_token": int(instrument_token),
            "exchange": ex,
            "symbol": sym,
            "interval": internal_interval,
            "kite_interval": interval,
            "price_mode": "RAW_UNADJUSTED",
            "fetched_at": fetched_at.isoformat(),
            "credential_role": "MARKET_DATA_ONLY",
            "bars": bars,
        }
        encoded = json.dumps(snapshot_obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        digest = hashlib.sha256(encoded).hexdigest()
        archive_path = _archive_snapshot(encoded, digest)
        fetch_id = record_fetch(
            series_id=series["series_id"], source_key=KITE_SOURCE_KEY, interval=internal_interval,
            requested_start=_kite_time(from_time), requested_end=_kite_time(to_time),
            fetched_at=fetched_at.isoformat(), source_payload_sha256=digest,
            archive_path=archive_path, rows_received=len(bars), status="SUCCESS" if bars else "EMPTY",
            notes="Canonical normalized Kite market-data-only snapshot; no order/account semantics imported",
            db_path=db_path,
        )
        writes = upsert_bars(
            series["series_id"], internal_interval, bars, source_key=KITE_SOURCE_KEY,
            ingested_at=fetched_at.isoformat(), db_path=db_path,
        ) if bars else {"bars_inserted": 0, "bars_updated": 0}
        replace_issues(series["series_id"], internal_interval, issues, db_path=db_path)
        return {
            "status": "SUCCESS" if bars else "EMPTY",
            "series_id": series["series_id"],
            "fetch_id": fetch_id,
            "source_key": KITE_SOURCE_KEY,
            "source_official": False,
            "source_symbol": source_symbol,
            "instrument_token": int(instrument_token),
            "instrument": instrument,
            "price_mode": "RAW_UNADJUSTED",
            "interval": internal_interval,
            "kite_interval": interval,
            "rows_received": len(bars),
            **writes,
            "quality_issues": len(issues),
            "snapshot_sha256": digest,
            "archive_path": archive_path,
            "credential_role": "MARKET_DATA_ONLY",
            "order_api_enabled": False,
            "trader_profile": "RESIDENT_INDIAN",
            "no_lookahead_contract": "Replay exposes only bars with ts_close <= as_of",
        }
    except Exception as exc:
        record_fetch(
            series_id=series["series_id"], source_key=KITE_SOURCE_KEY, interval=internal_interval,
            requested_start=_kite_time(from_time), requested_end=_kite_time(to_time),
            fetched_at=fetched_at.isoformat(), source_payload_sha256=None, archive_path=None,
            rows_received=0, status="FAILED", notes=f"{type(exc).__name__}: {exc}", db_path=db_path,
        )
        raise
