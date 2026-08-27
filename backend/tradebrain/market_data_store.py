"""Audited market-data persistence for Trade Brain Phase 3.

The store is source-aware and identity-aware. It keeps vendor/official provenance,
raw/unadjusted OHLCV, validation findings, derived bars, corporate-action markers,
comparable-price eras, and event price-effect results in additive `tb_*` tables.

Core rule: replay queries only expose bars whose `ts_close <= as_of`, so an
incomplete/future candle cannot leak into historical decisions.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterable

from backend.db import DB_PATH
from backend.tradebrain.corporate_event_store import ensure_corporate_event_schema
from backend.tradebrain.security_store import ensure_security_master_schema, get_exchange_listing


@contextmanager
def _connect(db_path: str | None = None):
    path = db_path or DB_PATH
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def ensure_market_data_schema(db_path: str | None = None) -> None:
    ensure_security_master_schema(db_path)
    ensure_corporate_event_schema(db_path)
    with _connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS tb_market_series (
                series_id TEXT PRIMARY KEY,
                exchange TEXT NOT NULL,
                symbol TEXT NOT NULL,
                isin TEXT,
                issuer_entity_id TEXT,
                source_key TEXT NOT NULL,
                source_symbol TEXT NOT NULL,
                price_mode TEXT NOT NULL DEFAULT 'RAW_UNADJUSTED',
                timezone TEXT NOT NULL DEFAULT 'Asia/Kolkata',
                currency TEXT,
                base_interval TEXT,
                first_bar_at TEXT,
                last_bar_at TEXT,
                last_sync_at TEXT,
                source_metadata_json TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now')),
                UNIQUE(exchange, symbol, source_key, price_mode)
            );

            CREATE INDEX IF NOT EXISTS idx_tb_market_series_identity
                ON tb_market_series(exchange, symbol, isin);

            CREATE TABLE IF NOT EXISTS tb_market_fetches (
                fetch_id TEXT PRIMARY KEY,
                series_id TEXT NOT NULL,
                source_key TEXT NOT NULL,
                interval TEXT NOT NULL,
                requested_start TEXT,
                requested_end TEXT,
                fetched_at TEXT NOT NULL,
                source_payload_sha256 TEXT,
                archive_path TEXT,
                snapshot_kind TEXT NOT NULL DEFAULT 'NORMALIZED_VENDOR_SNAPSHOT',
                rows_received INTEGER DEFAULT 0,
                status TEXT NOT NULL,
                notes TEXT,
                FOREIGN KEY (series_id) REFERENCES tb_market_series(series_id)
            );

            CREATE INDEX IF NOT EXISTS idx_tb_market_fetches_series
                ON tb_market_fetches(series_id, interval, fetched_at DESC);

            CREATE TABLE IF NOT EXISTS tb_ohlcv_bars (
                series_id TEXT NOT NULL,
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
                is_derived INTEGER NOT NULL DEFAULT 0,
                derived_from_interval TEXT,
                is_final INTEGER NOT NULL DEFAULT 1,
                era_id TEXT,
                quality_flags_json TEXT,
                PRIMARY KEY (series_id, interval, ts_open),
                FOREIGN KEY (series_id) REFERENCES tb_market_series(series_id)
            );

            CREATE INDEX IF NOT EXISTS idx_tb_ohlcv_replay
                ON tb_ohlcv_bars(series_id, interval, ts_close);

            CREATE TABLE IF NOT EXISTS tb_market_data_issues (
                issue_id TEXT PRIMARY KEY,
                series_id TEXT NOT NULL,
                interval TEXT NOT NULL,
                issue_type TEXT NOT NULL,
                severity TEXT NOT NULL,
                ts_start TEXT,
                ts_end TEXT,
                details_json TEXT,
                detected_at TEXT DEFAULT (datetime('now')),
                resolved_at TEXT,
                UNIQUE(series_id, interval, issue_type, ts_start, ts_end),
                FOREIGN KEY (series_id) REFERENCES tb_market_series(series_id)
            );

            CREATE TABLE IF NOT EXISTS tb_market_corporate_actions (
                action_id TEXT PRIMARY KEY,
                series_id TEXT NOT NULL,
                action_type TEXT NOT NULL,
                effective_at TEXT NOT NULL,
                value REAL,
                source_key TEXT NOT NULL,
                verification_status TEXT NOT NULL DEFAULT 'VENDOR_REPORTED',
                source_metadata_json TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                UNIQUE(series_id, action_type, effective_at, source_key),
                FOREIGN KEY (series_id) REFERENCES tb_market_series(series_id)
            );

            CREATE TABLE IF NOT EXISTS tb_price_eras (
                era_id TEXT PRIMARY KEY,
                series_id TEXT NOT NULL,
                starts_at TEXT,
                ends_at TEXT,
                boundary_reason TEXT NOT NULL,
                boundary_source TEXT NOT NULL,
                verification_status TEXT NOT NULL,
                adjustment_factor REAL,
                source_event_id TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (series_id) REFERENCES tb_market_series(series_id)
            );

            CREATE INDEX IF NOT EXISTS idx_tb_price_eras_series
                ON tb_price_eras(series_id, starts_at, ends_at);

            CREATE TABLE IF NOT EXISTS tb_event_price_effects (
                event_id TEXT NOT NULL,
                series_id TEXT NOT NULL,
                interval TEXT NOT NULL,
                horizon_sessions INTEGER NOT NULL,
                anchor_bar_open TEXT NOT NULL,
                anchor_price REAL NOT NULL,
                end_bar_close TEXT,
                end_price REAL,
                return_pct REAL,
                mae_pct REAL,
                mfe_pct REAL,
                bars_observed INTEGER NOT NULL,
                method TEXT NOT NULL,
                computed_at TEXT NOT NULL,
                PRIMARY KEY (event_id, series_id, interval, horizon_sessions),
                FOREIGN KEY (event_id) REFERENCES tb_corporate_events(event_id),
                FOREIGN KEY (series_id) REFERENCES tb_market_series(series_id)
            );
            """
        )


def _series_id(exchange: str, symbol: str, source_key: str, price_mode: str) -> str:
    seed = f"{exchange.upper()}|{symbol.upper()}|{source_key}|{price_mode}"
    return "series:" + hashlib.sha256(seed.encode("utf-8")).hexdigest()


def ensure_series(
    *,
    exchange: str,
    symbol: str,
    source_key: str,
    source_symbol: str,
    price_mode: str = "RAW_UNADJUSTED",
    timezone_name: str = "Asia/Kolkata",
    currency: str | None = "INR",
    base_interval: str | None = None,
    source_metadata: dict[str, Any] | None = None,
    db_path: str | None = None,
) -> dict[str, Any]:
    """Create/get a market series only for an identity known to Phase 1."""
    exchange = exchange.strip().upper()
    symbol = symbol.strip().upper()
    if exchange not in {"NSE", "BSE"}:
        raise ValueError("exchange must be NSE or BSE")
    listing = get_exchange_listing(exchange, symbol, db_path=db_path)
    if listing is None:
        raise ValueError(
            f"Unknown {exchange}:{symbol}; refresh Phase 1 security master before creating audited market data"
        )

    ensure_market_data_schema(db_path)
    sid = _series_id(exchange, symbol, source_key, price_mode)
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO tb_market_series(
                series_id, exchange, symbol, isin, issuer_entity_id, source_key,
                source_symbol, price_mode, timezone, currency, base_interval,
                source_metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(series_id) DO UPDATE SET
                isin=excluded.isin,
                issuer_entity_id=excluded.issuer_entity_id,
                source_symbol=excluded.source_symbol,
                timezone=excluded.timezone,
                currency=COALESCE(excluded.currency, tb_market_series.currency),
                base_interval=COALESCE(excluded.base_interval, tb_market_series.base_interval),
                source_metadata_json=COALESCE(excluded.source_metadata_json, tb_market_series.source_metadata_json),
                updated_at=datetime('now')
            """,
            (
                sid, exchange, symbol, listing.get("isin"), listing.get("issuer_entity_id"),
                source_key, source_symbol, price_mode, timezone_name, currency, base_interval,
                json.dumps(source_metadata or {}, sort_keys=True, ensure_ascii=False, default=str),
            ),
        )
    return get_series(sid, db_path=db_path) or {"series_id": sid}


def get_series(series_id: str, db_path: str | None = None) -> dict[str, Any] | None:
    ensure_market_data_schema(db_path)
    with _connect(db_path) as conn:
        row = conn.execute("SELECT * FROM tb_market_series WHERE series_id=?", (series_id,)).fetchone()
    if not row:
        return None
    result = dict(row)
    try:
        result["source_metadata"] = json.loads(result.pop("source_metadata_json") or "{}")
    except json.JSONDecodeError:
        result["source_metadata"] = {}
        result.pop("source_metadata_json", None)
    return result


def find_series(
    exchange: str,
    symbol: str,
    *,
    source_key: str | None = None,
    price_mode: str = "RAW_UNADJUSTED",
    db_path: str | None = None,
) -> dict[str, Any] | None:
    ensure_market_data_schema(db_path)
    clauses = ["exchange=?", "symbol=?", "price_mode=?"]
    args: list[Any] = [exchange.upper(), symbol.upper(), price_mode]
    if source_key:
        clauses.append("source_key=?")
        args.append(source_key)
    with _connect(db_path) as conn:
        row = conn.execute(
            f"SELECT * FROM tb_market_series WHERE {' AND '.join(clauses)} ORDER BY updated_at DESC LIMIT 1",
            args,
        ).fetchone()
    if not row:
        return None
    return get_series(row["series_id"], db_path=db_path)


def record_fetch(
    *,
    series_id: str,
    source_key: str,
    interval: str,
    requested_start: str | None,
    requested_end: str | None,
    fetched_at: str,
    source_payload_sha256: str | None,
    archive_path: str | None,
    rows_received: int,
    status: str,
    notes: str | None = None,
    db_path: str | None = None,
) -> str:
    ensure_market_data_schema(db_path)
    fetch_id = str(uuid.uuid4())
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO tb_market_fetches(
                fetch_id, series_id, source_key, interval, requested_start, requested_end,
                fetched_at, source_payload_sha256, archive_path, rows_received, status, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                fetch_id, series_id, source_key, interval, requested_start, requested_end,
                fetched_at, source_payload_sha256, archive_path, rows_received, status, notes,
            ),
        )
    return fetch_id


def upsert_bars(
    series_id: str,
    interval: str,
    bars: Iterable[dict[str, Any]],
    *,
    source_key: str,
    ingested_at: str | None = None,
    is_derived: bool = False,
    derived_from_interval: str | None = None,
    db_path: str | None = None,
) -> dict[str, int]:
    ensure_market_data_schema(db_path)
    ingested_at = ingested_at or datetime.now(timezone.utc).isoformat()
    inserted = updated = 0
    first_ts = last_ts = None
    with _connect(db_path) as conn:
        for bar in bars:
            existing = conn.execute(
                "SELECT 1 FROM tb_ohlcv_bars WHERE series_id=? AND interval=? AND ts_open=?",
                (series_id, interval, bar["ts_open"]),
            ).fetchone()
            conn.execute(
                """
                INSERT INTO tb_ohlcv_bars(
                    series_id, interval, ts_open, ts_close, open, high, low, close, volume,
                    source_key, source_timestamp, ingested_at, is_derived,
                    derived_from_interval, is_final, era_id, quality_flags_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(series_id, interval, ts_open) DO UPDATE SET
                    ts_close=excluded.ts_close,
                    open=excluded.open,
                    high=excluded.high,
                    low=excluded.low,
                    close=excluded.close,
                    volume=excluded.volume,
                    source_key=excluded.source_key,
                    source_timestamp=excluded.source_timestamp,
                    ingested_at=excluded.ingested_at,
                    is_derived=excluded.is_derived,
                    derived_from_interval=excluded.derived_from_interval,
                    is_final=excluded.is_final,
                    era_id=COALESCE(excluded.era_id, tb_ohlcv_bars.era_id),
                    quality_flags_json=excluded.quality_flags_json
                """,
                (
                    series_id, interval, bar["ts_open"], bar["ts_close"],
                    float(bar["open"]), float(bar["high"]), float(bar["low"]), float(bar["close"]),
                    float(bar.get("volume") or 0), source_key, bar.get("source_timestamp"), ingested_at,
                    int(is_derived), derived_from_interval, int(bool(bar.get("is_final", True))),
                    bar.get("era_id"), json.dumps(bar.get("quality_flags") or [], ensure_ascii=False),
                ),
            )
            if existing:
                updated += 1
            else:
                inserted += 1
            first_ts = bar["ts_open"] if first_ts is None or bar["ts_open"] < first_ts else first_ts
            last_ts = bar["ts_open"] if last_ts is None or bar["ts_open"] > last_ts else last_ts

        if first_ts or last_ts:
            conn.execute(
                """
                UPDATE tb_market_series
                SET first_bar_at=CASE
                        WHEN first_bar_at IS NULL OR ? < first_bar_at THEN ? ELSE first_bar_at END,
                    last_bar_at=CASE
                        WHEN last_bar_at IS NULL OR ? > last_bar_at THEN ? ELSE last_bar_at END,
                    last_sync_at=?,
                    base_interval=COALESCE(base_interval, ?),
                    updated_at=datetime('now')
                WHERE series_id=?
                """,
                (first_ts, first_ts, last_ts, last_ts, ingested_at, interval, series_id),
            )
    return {"bars_inserted": inserted, "bars_updated": updated}


def query_bars(
    series_id: str,
    interval: str,
    *,
    start: str | None = None,
    end: str | None = None,
    as_of: str | None = None,
    limit: int = 10000,
    db_path: str | None = None,
) -> list[dict[str, Any]]:
    """Return only completed bars at/before `as_of` to enforce replay no-lookahead."""
    ensure_market_data_schema(db_path)
    clauses = ["series_id=?", "interval=?"]
    args: list[Any] = [series_id, interval]
    if start:
        clauses.append("ts_open>=?")
        args.append(start)
    if end:
        clauses.append("ts_open<?")
        args.append(end)
    if as_of:
        clauses.append("ts_close<=?")
        args.append(as_of)
    clauses.append("is_final=1")
    args.append(max(1, min(limit, 500000)))
    with _connect(db_path) as conn:
        rows = conn.execute(
            f"SELECT * FROM tb_ohlcv_bars WHERE {' AND '.join(clauses)} ORDER BY ts_open LIMIT ?",
            args,
        ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        try:
            item["quality_flags"] = json.loads(item.pop("quality_flags_json") or "[]")
        except json.JSONDecodeError:
            item["quality_flags"] = ["MALFORMED_QUALITY_FLAGS"]
            item.pop("quality_flags_json", None)
        result.append(item)
    return result


def latest_bar_time(series_id: str, interval: str, db_path: str | None = None) -> str | None:
    ensure_market_data_schema(db_path)
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT MAX(ts_open) AS ts FROM tb_ohlcv_bars WHERE series_id=? AND interval=? AND is_final=1",
            (series_id, interval),
        ).fetchone()
    return row["ts"] if row and row["ts"] else None


def replace_issues(
    series_id: str,
    interval: str,
    issues: list[dict[str, Any]],
    *,
    db_path: str | None = None,
) -> int:
    ensure_market_data_schema(db_path)
    with _connect(db_path) as conn:
        conn.execute(
            "DELETE FROM tb_market_data_issues WHERE series_id=? AND interval=? AND resolved_at IS NULL",
            (series_id, interval),
        )
        for issue in issues:
            conn.execute(
                """
                INSERT OR IGNORE INTO tb_market_data_issues(
                    issue_id, series_id, interval, issue_type, severity, ts_start, ts_end, details_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()), series_id, interval, issue["issue_type"], issue.get("severity", "WARNING"),
                    issue.get("ts_start"), issue.get("ts_end"),
                    json.dumps(issue.get("details") or {}, ensure_ascii=False, sort_keys=True, default=str),
                ),
            )
    return len(issues)


def list_issues(
    series_id: str,
    *,
    interval: str | None = None,
    unresolved_only: bool = True,
    db_path: str | None = None,
) -> list[dict[str, Any]]:
    ensure_market_data_schema(db_path)
    clauses = ["series_id=?"]
    args: list[Any] = [series_id]
    if interval:
        clauses.append("interval=?")
        args.append(interval)
    if unresolved_only:
        clauses.append("resolved_at IS NULL")
    with _connect(db_path) as conn:
        rows = conn.execute(
            f"SELECT * FROM tb_market_data_issues WHERE {' AND '.join(clauses)} ORDER BY severity DESC, detected_at DESC",
            args,
        ).fetchall()
    out = []
    for row in rows:
        item = dict(row)
        try:
            item["details"] = json.loads(item.pop("details_json") or "{}")
        except json.JSONDecodeError:
            item["details"] = {}
            item.pop("details_json", None)
        out.append(item)
    return out


def upsert_corporate_actions(
    series_id: str,
    actions: Iterable[dict[str, Any]],
    *,
    source_key: str,
    verification_status: str = "VENDOR_REPORTED",
    db_path: str | None = None,
) -> int:
    ensure_market_data_schema(db_path)
    count = 0
    with _connect(db_path) as conn:
        for action in actions:
            action_type = str(action["action_type"]).upper()
            effective_at = str(action["effective_at"])
            aid = "action:" + hashlib.sha256(
                f"{series_id}|{action_type}|{effective_at}|{source_key}".encode("utf-8")
            ).hexdigest()
            conn.execute(
                """
                INSERT INTO tb_market_corporate_actions(
                    action_id, series_id, action_type, effective_at, value, source_key,
                    verification_status, source_metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(series_id, action_type, effective_at, source_key) DO UPDATE SET
                    value=excluded.value,
                    verification_status=excluded.verification_status,
                    source_metadata_json=excluded.source_metadata_json
                """,
                (
                    aid, series_id, action_type, effective_at, action.get("value"), source_key,
                    verification_status, json.dumps(action.get("metadata") or {}, ensure_ascii=False, default=str),
                ),
            )
            count += 1
    return count


def rebuild_vendor_split_eras(series_id: str, db_path: str | None = None) -> dict[str, Any]:
    """Create non-official comparable-price eras from vendor-reported split markers.

    These eras are barriers for raw-price comparison. They do not auto-adjust prices and
    remain `VENDOR_REPORTED`, not exchange-verified corporate-action truth.
    """
    ensure_market_data_schema(db_path)
    with _connect(db_path) as conn:
        actions = conn.execute(
            """
            SELECT effective_at, value, source_key, verification_status
            FROM tb_market_corporate_actions
            WHERE series_id=? AND action_type='SPLIT'
            ORDER BY effective_at
            """,
            (series_id,),
        ).fetchall()
        conn.execute(
            "DELETE FROM tb_price_eras WHERE series_id=? AND boundary_source='VENDOR_SPLIT_ACTION'",
            (series_id,),
        )
        boundaries = [dict(row) for row in actions]
        starts: list[str | None] = [None] + [b["effective_at"] for b in boundaries]
        ends: list[str | None] = [b["effective_at"] for b in boundaries] + [None]
        for idx, (start, end) in enumerate(zip(starts, ends)):
            boundary = boundaries[idx - 1] if idx > 0 else None
            era_id = "era:" + hashlib.sha256(
                f"{series_id}|vendor-split|{start}|{end}".encode("utf-8")
            ).hexdigest()
            conn.execute(
                """
                INSERT INTO tb_price_eras(
                    era_id, series_id, starts_at, ends_at, boundary_reason,
                    boundary_source, verification_status, adjustment_factor
                ) VALUES (?, ?, ?, ?, ?, 'VENDOR_SPLIT_ACTION', ?, ?)
                """,
                (
                    era_id, series_id, start, end,
                    "RAW_PRICE_COMPARABILITY_BOUNDARY" if boundary else "INITIAL_RAW_PRICE_ERA",
                    boundary["verification_status"] if boundary else "DERIVED_FROM_VENDOR_REPORTED_ACTIONS",
                    boundary["value"] if boundary else None,
                ),
            )
        eras = conn.execute(
            "SELECT * FROM tb_price_eras WHERE series_id=? AND boundary_source='VENDOR_SPLIT_ACTION' ORDER BY starts_at",
            (series_id,),
        ).fetchall()
    return {
        "series_id": series_id,
        "split_boundaries": len(boundaries),
        "eras_created": len(eras),
        "verification_status": "VENDOR_REPORTED_NOT_EXCHANGE_VERIFIED",
    }


def assign_price_eras(series_id: str, interval: str, db_path: str | None = None) -> int:
    ensure_market_data_schema(db_path)
    with _connect(db_path) as conn:
        eras = conn.execute(
            "SELECT era_id, starts_at, ends_at FROM tb_price_eras WHERE series_id=? ORDER BY starts_at",
            (series_id,),
        ).fetchall()
        updated = 0
        for era in eras:
            clauses = ["series_id=?", "interval=?"]
            args: list[Any] = [series_id, interval]
            if era["starts_at"]:
                clauses.append("ts_open>=?")
                args.append(era["starts_at"])
            if era["ends_at"]:
                clauses.append("ts_open<?")
                args.append(era["ends_at"])
            args.append(era["era_id"])
            cur = conn.execute(
                f"UPDATE tb_ohlcv_bars SET era_id=? WHERE {' AND '.join(clauses)}",
                [args[-1], *args[:-1]],
            )
            updated += cur.rowcount
    return updated


def store_event_price_effect(
    effect: dict[str, Any],
    *,
    db_path: str | None = None,
) -> None:
    ensure_market_data_schema(db_path)
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO tb_event_price_effects(
                event_id, series_id, interval, horizon_sessions, anchor_bar_open,
                anchor_price, end_bar_close, end_price, return_pct, mae_pct, mfe_pct,
                bars_observed, method, computed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(event_id, series_id, interval, horizon_sessions) DO UPDATE SET
                anchor_bar_open=excluded.anchor_bar_open,
                anchor_price=excluded.anchor_price,
                end_bar_close=excluded.end_bar_close,
                end_price=excluded.end_price,
                return_pct=excluded.return_pct,
                mae_pct=excluded.mae_pct,
                mfe_pct=excluded.mfe_pct,
                bars_observed=excluded.bars_observed,
                method=excluded.method,
                computed_at=excluded.computed_at
            """,
            (
                effect["event_id"], effect["series_id"], effect["interval"], effect["horizon_sessions"],
                effect["anchor_bar_open"], effect["anchor_price"], effect.get("end_bar_close"),
                effect.get("end_price"), effect.get("return_pct"), effect.get("mae_pct"),
                effect.get("mfe_pct"), effect["bars_observed"], effect["method"],
                effect.get("computed_at") or datetime.now(timezone.utc).isoformat(),
            ),
        )


def market_data_stats(db_path: str | None = None) -> dict[str, Any]:
    ensure_market_data_schema(db_path)
    with _connect(db_path) as conn:
        scalar = lambda sql, args=(): conn.execute(sql, args).fetchone()[0]
        by_interval = {
            row["interval"]: row["n"]
            for row in conn.execute("SELECT interval, COUNT(*) n FROM tb_ohlcv_bars GROUP BY interval")
        }
        by_source = {
            row["source_key"]: row["n"]
            for row in conn.execute("SELECT source_key, COUNT(*) n FROM tb_market_series GROUP BY source_key")
        }
        return {
            "series": scalar("SELECT COUNT(*) FROM tb_market_series"),
            "bars": scalar("SELECT COUNT(*) FROM tb_ohlcv_bars"),
            "derived_bars": scalar("SELECT COUNT(*) FROM tb_ohlcv_bars WHERE is_derived=1"),
            "fetches": scalar("SELECT COUNT(*) FROM tb_market_fetches"),
            "open_quality_issues": scalar("SELECT COUNT(*) FROM tb_market_data_issues WHERE resolved_at IS NULL"),
            "corporate_actions": scalar("SELECT COUNT(*) FROM tb_market_corporate_actions"),
            "price_eras": scalar("SELECT COUNT(*) FROM tb_price_eras"),
            "event_price_effects": scalar("SELECT COUNT(*) FROM tb_event_price_effects"),
            "bars_by_interval": by_interval,
            "series_by_source": by_source,
        }
