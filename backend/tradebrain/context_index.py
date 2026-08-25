"""Audited broader-market index context for Trade Brain.

BSE Ltd remains the only trade target. NIFTY 50 is stored separately as context-only
index evidence because it is not an ISIN-backed equity listing. The module is strictly
read-only with respect to Kite: historical market data may be collected, but no broker
account/order semantics are exposed.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from statistics import pstdev
from typing import Any

from backend.db import DB_PATH
from backend.tradebrain.kite_data import KITE_SOURCE_KEY, KiteDataOnlyClient, normalize_kite_candles
from backend.tradebrain.market_data import validate_bars

INDEX_KEY = "NSE:NIFTY_50"
EXCHANGE = "NSE"
SYMBOL = "NIFTY 50"
INTERVAL = "1d"
METHOD_VERSION = "AUDITED_NIFTY50_CONTEXT_V2_SEVERITY_ORDERED"


@contextmanager
def _connect(db_path: str | None = None):
    path = db_path or DB_PATH
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _data_root() -> Path:
    configured = os.getenv("TRADEBRAIN_DATA_DIR")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".tradingagents" / "tradebrain"


def ensure_context_index_schema(db_path: str | None = None) -> None:
    with _connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS tb_context_index_series (
                index_key TEXT PRIMARY KEY,
                exchange TEXT NOT NULL,
                symbol TEXT NOT NULL,
                source_key TEXT NOT NULL,
                instrument_token INTEGER,
                source_symbol TEXT NOT NULL,
                price_mode TEXT NOT NULL DEFAULT 'RAW_UNADJUSTED',
                timezone TEXT NOT NULL DEFAULT 'Asia/Kolkata',
                currency TEXT NOT NULL DEFAULT 'INR',
                last_sync_at TEXT,
                source_metadata_json TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS tb_context_index_bars (
                index_key TEXT NOT NULL,
                interval TEXT NOT NULL,
                ts_open TEXT NOT NULL,
                ts_close TEXT NOT NULL,
                open REAL NOT NULL,
                high REAL NOT NULL,
                low REAL NOT NULL,
                close REAL NOT NULL,
                volume REAL NOT NULL DEFAULT 0,
                source_key TEXT NOT NULL,
                source_timestamp TEXT,
                ingested_at TEXT NOT NULL,
                is_final INTEGER NOT NULL DEFAULT 1,
                quality_flags_json TEXT,
                PRIMARY KEY(index_key, interval, ts_open),
                FOREIGN KEY(index_key) REFERENCES tb_context_index_series(index_key)
            );

            CREATE INDEX IF NOT EXISTS idx_tb_context_index_replay
                ON tb_context_index_bars(index_key, interval, ts_close);

            CREATE TABLE IF NOT EXISTS tb_context_index_fetches (
                fetch_id TEXT PRIMARY KEY,
                index_key TEXT NOT NULL,
                interval TEXT NOT NULL,
                requested_start TEXT,
                requested_end TEXT,
                fetched_at TEXT NOT NULL,
                source_payload_sha256 TEXT,
                archive_path TEXT,
                rows_received INTEGER NOT NULL DEFAULT 0,
                quality_issues INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL,
                notes TEXT,
                FOREIGN KEY(index_key) REFERENCES tb_context_index_series(index_key)
            );
            """
        )


def resolve_nifty50_instrument(client: KiteDataOnlyClient) -> dict[str, Any]:
    """Resolve exactly one NIFTY 50 index token from Kite's read-only instrument dump."""
    rows = client.instruments(EXCHANGE)
    exact = [
        dict(row)
        for row in rows
        if str(row.get("tradingsymbol") or "").strip().upper() == SYMBOL
    ]
    if not exact:
        exact = [
            dict(row)
            for row in rows
            if str(row.get("name") or "").strip().upper() == SYMBOL
            and "IND" in str(row.get("segment") or row.get("instrument_type") or "").upper()
        ]
    if len(exact) != 1:
        raise ValueError(f"Expected exactly one Kite NIFTY 50 index instrument; found {len(exact)}")
    row = exact[0]
    try:
        row["instrument_token"] = int(row["instrument_token"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Kite NIFTY 50 index row has invalid instrument_token") from exc
    return row


def _archive(payload: bytes, digest: str) -> str:
    directory = _data_root() / "market_data" / "context_indexes" / "kite"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"nifty50_day_{digest}.json"
    if not path.exists():
        path.write_bytes(payload)
    return str(path)


def sync_kite_nifty50_daily(
    *,
    from_time: str | datetime,
    to_time: str | datetime,
    client: KiteDataOnlyClient | None = None,
    db_path: str | None = None,
) -> dict[str, Any]:
    """Persist finalized Kite NIFTY 50 daily candles into the context-only audited store."""
    data_client = client or KiteDataOnlyClient()
    instrument = resolve_nifty50_instrument(data_client)
    token = int(instrument["instrument_token"])
    fetched_at = datetime.now(timezone.utc)
    candles = data_client.historical(
        instrument_token=token,
        interval="day",
        from_time=from_time,
        to_time=to_time,
        continuous=False,
        oi=False,
    )
    bars, parse_issues = normalize_kite_candles(candles, "day", fetched_at=fetched_at)
    issues = parse_issues + validate_bars(bars, "1d")
    canonical = {
        "method_version": METHOD_VERSION,
        "index_key": INDEX_KEY,
        "exchange": EXCHANGE,
        "symbol": SYMBOL,
        "source_key": KITE_SOURCE_KEY,
        "instrument_token": token,
        "interval": INTERVAL,
        "price_mode": "RAW_UNADJUSTED",
        "credential_role": "MARKET_DATA_ONLY",
        "fetched_at": fetched_at.isoformat(),
        "bars": bars,
        "quality_issues": issues,
    }
    encoded = json.dumps(canonical, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()
    archive_path = _archive(encoded, digest)
    ensure_context_index_schema(db_path)
    now = fetched_at.isoformat()
    inserted = updated = 0
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO tb_context_index_series(
                index_key, exchange, symbol, source_key, instrument_token, source_symbol,
                source_metadata_json, created_at, updated_at, last_sync_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(index_key) DO UPDATE SET
                source_key=excluded.source_key,
                instrument_token=excluded.instrument_token,
                source_symbol=excluded.source_symbol,
                source_metadata_json=excluded.source_metadata_json,
                updated_at=excluded.updated_at,
                last_sync_at=excluded.last_sync_at
            """,
            (
                INDEX_KEY, EXCHANGE, SYMBOL, KITE_SOURCE_KEY, token, f"{EXCHANGE}:{SYMBOL}",
                json.dumps({"instrument": instrument, "credential_role": "MARKET_DATA_ONLY"}, sort_keys=True, default=str),
                now, now, now,
            ),
        )
        for bar in bars:
            existing = conn.execute(
                "SELECT 1 FROM tb_context_index_bars WHERE index_key=? AND interval=? AND ts_open=?",
                (INDEX_KEY, INTERVAL, bar["ts_open"]),
            ).fetchone()
            conn.execute(
                """
                INSERT INTO tb_context_index_bars(
                    index_key, interval, ts_open, ts_close, open, high, low, close, volume,
                    source_key, source_timestamp, ingested_at, is_final, quality_flags_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(index_key, interval, ts_open) DO UPDATE SET
                    ts_close=excluded.ts_close,
                    open=excluded.open,
                    high=excluded.high,
                    low=excluded.low,
                    close=excluded.close,
                    volume=excluded.volume,
                    source_key=excluded.source_key,
                    source_timestamp=excluded.source_timestamp,
                    ingested_at=excluded.ingested_at,
                    is_final=excluded.is_final,
                    quality_flags_json=excluded.quality_flags_json
                """,
                (
                    INDEX_KEY, INTERVAL, bar["ts_open"], bar["ts_close"], bar["open"], bar["high"],
                    bar["low"], bar["close"], bar.get("volume") or 0.0, KITE_SOURCE_KEY,
                    bar.get("source_timestamp"), now, int(bool(bar.get("is_final", True))),
                    json.dumps(bar.get("quality_flags") or [], sort_keys=True),
                ),
            )
            if existing:
                updated += 1
            else:
                inserted += 1
        conn.execute(
            """
            INSERT INTO tb_context_index_fetches(
                fetch_id, index_key, interval, requested_start, requested_end, fetched_at,
                source_payload_sha256, archive_path, rows_received, quality_issues, status, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()), INDEX_KEY, INTERVAL, str(from_time), str(to_time), now,
                digest, archive_path, len(bars), len(issues), "SUCCESS" if bars else "EMPTY",
                "Canonical normalized Kite NIFTY 50 context-only snapshot; no order/account semantics imported",
            ),
        )
    return {
        "status": "SUCCESS" if bars else "EMPTY",
        "method_version": METHOD_VERSION,
        "index_key": INDEX_KEY,
        "source_key": KITE_SOURCE_KEY,
        "source_symbol": f"{EXCHANGE}:{SYMBOL}",
        "instrument_token": token,
        "interval": INTERVAL,
        "rows_received": len(bars),
        "bars_inserted": inserted,
        "bars_updated": updated,
        "quality_issues": len(issues),
        "snapshot_sha256": digest,
        "archive_path": archive_path,
        "credential_role": "MARKET_DATA_ONLY",
        "context_only": True,
        "trade_target": False,
        "trade_authorization": False,
        "order_execution_allowed": False,
    }


def query_context_index_bars(
    *,
    as_of: str | datetime,
    limit: int = 260,
    db_path: str | None = None,
) -> list[dict[str, Any]]:
    ensure_context_index_schema(db_path)
    cutoff = datetime.fromisoformat(as_of) if isinstance(as_of, str) else as_of
    if cutoff.tzinfo is None:
        cutoff = cutoff.replace(tzinfo=timezone.utc)
    cutoff = cutoff.astimezone(timezone.utc).isoformat()
    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT * FROM tb_context_index_bars
            WHERE index_key=? AND interval=? AND ts_close<=? AND is_final=1
            ORDER BY ts_open DESC LIMIT ?
            """,
            (INDEX_KEY, INTERVAL, cutoff, max(1, min(int(limit), 5000))),
        ).fetchall()
    return [dict(row) for row in reversed(rows)]


def _annualized_vol(closes: list[float]) -> float:
    if len(closes) < 21:
        return 0.0
    returns = [(closes[i] / closes[i - 1]) - 1.0 for i in range(len(closes) - 20, len(closes))]
    return pstdev(returns) * math.sqrt(252) * 100.0 if len(returns) > 1 else 0.0


def nifty50_correction_context(
    *,
    as_of: str | datetime,
    db_path: str | None = None,
) -> dict[str, Any]:
    """Classify only completed locally audited NIFTY 50 daily bars; missing data stays UNKNOWN."""
    bars = query_context_index_bars(as_of=as_of, limit=260, db_path=db_path)
    if len(bars) < 50:
        return {
            "status": "INSUFFICIENT_AUDITED_NIFTY_CONTEXT",
            "correction_state": "UNKNOWN",
            "bars": len(bars),
            "required_bars": 50,
            "index_key": INDEX_KEY,
            "source_required": KITE_SOURCE_KEY,
            "hard_external_web_fetch_used": False,
            "trade_authorization": False,
            "order_execution_allowed": False,
        }

    closes = [float(bar["close"]) for bar in bars]
    close = closes[-1]
    sma20 = sum(closes[-20:]) / 20.0
    sma50 = sum(closes[-50:]) / 50.0
    vol20 = _annualized_vol(closes)
    baselines: list[float] = []
    start = max(50, len(closes) - 140)
    for end in range(start, len(closes) - 20, 5):
        sample = closes[: end + 1]
        value = _annualized_vol(sample)
        if value > 0:
            baselines.append(value)
    baseline = sum(baselines) / len(baselines) if baselines else vol20
    drawdown20 = (close / max(closes[-20:]) - 1.0) * 100.0

    # Severity ordering matters: a downtrend with an >=8% recent drawdown is classified
    # SEVERE even if realized volatility is also elevated. This keeps the state label
    # consistent with Guardian's correction-risk ordering.
    if close < sma20 < sma50 and drawdown20 <= -8.0:
        state = "SEVERE_CORRECTION"
        reason = "NIFTY 50 downtrend with at least 8% drawdown from its recent 20-session high"
    elif close < sma20 < sma50 and baseline > 0 and vol20 > baseline * 1.5:
        state = "HIGH_VOL_TREND_DOWN"
        reason = "NIFTY 50 close < SMA20 < SMA50 with elevated 20-session realized volatility"
    elif close < sma20 < sma50:
        state = "TREND_DOWN"
        reason = "NIFTY 50 close < SMA20 < SMA50"
    elif baseline > 0 and vol20 > baseline * 1.5:
        state = "HIGH_VOL"
        reason = "NIFTY 50 realized volatility is elevated relative to its local baseline"
    elif close > sma20 > sma50:
        state = "TREND_UP"
        reason = "NIFTY 50 close > SMA20 > SMA50"
    else:
        state = "RANGE"
        reason = "NIFTY 50 close/SMA20/SMA50 are not directionally aligned"

    return {
        "status": "AUDITED_NIFTY_DAILY_CONTEXT",
        "method_version": METHOD_VERSION,
        "index_key": INDEX_KEY,
        "source_key": KITE_SOURCE_KEY,
        "bars": len(bars),
        "as_of": str(as_of),
        "latest_completed_bar_close": bars[-1]["ts_close"],
        "close": round(close, 4),
        "sma20": round(sma20, 4),
        "sma50": round(sma50, 4),
        "annualized_vol_20_pct": round(vol20, 4),
        "vol_baseline_pct": round(baseline, 4),
        "drawdown_from_20_session_high_pct": round(drawdown20, 4),
        "correction_state": state,
        "reason": reason,
        "context_only": True,
        "trade_target": False,
        "hard_external_web_fetch_used": False,
        "trade_authorization": False,
        "order_execution_allowed": False,
    }