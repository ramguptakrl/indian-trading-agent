"""Persistent Trade Brain schema layered onto the repository's existing SQLite DB.

The upstream database remains untouched. Trade Brain owns `tb_*` tables so future
upstream merges are less likely to conflict with this fork's architecture.
"""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone

from backend.db import DB_PATH
from backend.tradebrain.identity import ExchangeListing, normalize_isin
from backend.tradebrain.policy import GateResult, TradePlan


@contextmanager
def _connect(db_path: str | None = None):
    path = db_path or DB_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def ensure_tradebrain_schema(db_path: str | None = None) -> None:
    with _connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS tb_sources (
                source_key TEXT PRIMARY KEY,
                source_name TEXT NOT NULL,
                source_type TEXT,
                base_url TEXT,
                is_official INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS tb_issuer_entities (
                issuer_entity_id TEXT PRIMARY KEY,
                display_name TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS tb_canonical_securities (
                isin TEXT PRIMARY KEY,
                issuer_entity_id TEXT NOT NULL,
                security_name TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (issuer_entity_id) REFERENCES tb_issuer_entities(issuer_entity_id)
            );

            CREATE TABLE IF NOT EXISTS tb_exchange_listings (
                exchange TEXT NOT NULL,
                symbol TEXT NOT NULL,
                isin TEXT,
                issuer_entity_id TEXT,
                listing_name TEXT,
                listing_status TEXT DEFAULT 'UNKNOWN',
                source_key TEXT,
                source_timestamp TEXT,
                updated_at TEXT DEFAULT (datetime('now')),
                PRIMARY KEY (exchange, symbol),
                FOREIGN KEY (isin) REFERENCES tb_canonical_securities(isin),
                FOREIGN KEY (issuer_entity_id) REFERENCES tb_issuer_entities(issuer_entity_id)
            );

            CREATE INDEX IF NOT EXISTS idx_tb_exchange_listings_isin
                ON tb_exchange_listings(isin);

            CREATE TABLE IF NOT EXISTS tb_raw_source_artifacts (
                artifact_id TEXT PRIMARY KEY,
                source_key TEXT NOT NULL,
                source_url TEXT,
                fetched_at TEXT NOT NULL,
                sha256 TEXT NOT NULL,
                raw_archive_path TEXT,
                parser_version TEXT,
                UNIQUE(source_key, sha256)
            );

            CREATE TABLE IF NOT EXISTS tb_trade_plan_evaluations (
                plan_id TEXT PRIMARY KEY,
                ticker TEXT NOT NULL,
                exchange TEXT NOT NULL,
                mode TEXT NOT NULL,
                direction TEXT NOT NULL,
                entry REAL NOT NULL,
                stop_loss REAL NOT NULL,
                take_profit REAL NOT NULL,
                quantity INTEGER,
                crash_guard TEXT,
                broker_allows_trade INTEGER NOT NULL,
                reward_risk REAL,
                gate_action TEXT NOT NULL,
                allowed_for_advisory INTEGER NOT NULL,
                hard_rule_failures TEXT,
                warnings TEXT,
                evidence TEXT,
                evaluated_at_ist TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS tb_trade_plan_outcomes (
                plan_id TEXT PRIMARY KEY,
                outcome TEXT NOT NULL,
                exit_price REAL,
                exit_timestamp TEXT,
                mae_pct REAL,
                mfe_pct REAL,
                r_multiple REAL,
                time_to_event_minutes REAL,
                notes TEXT,
                updated_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (plan_id) REFERENCES tb_trade_plan_evaluations(plan_id)
            );
            """
        )


def upsert_source(
    source_key: str,
    source_name: str,
    *,
    source_type: str | None = None,
    base_url: str | None = None,
    is_official: bool = False,
    db_path: str | None = None,
) -> None:
    ensure_tradebrain_schema(db_path)
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO tb_sources(source_key, source_name, source_type, base_url, is_official)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(source_key) DO UPDATE SET
                source_name=excluded.source_name,
                source_type=excluded.source_type,
                base_url=excluded.base_url,
                is_official=excluded.is_official,
                updated_at=datetime('now')
            """,
            (source_key, source_name, source_type, base_url, int(is_official)),
        )


def upsert_listing(
    listing: ExchangeListing,
    *,
    listing_name: str | None = None,
    security_name: str | None = None,
    listing_status: str = "UNKNOWN",
    source_key: str | None = None,
    source_timestamp: str | None = None,
    db_path: str | None = None,
) -> dict:
    """Persist one exchange listing without fuzzy issuer merging.

    With a valid ISIN, the initial safe model creates one deterministic issuer entity
    per security unless a verified issuer id was supplied. This can later be merged by
    verified CIN/LEI relationships, never by similar names alone.
    """

    ensure_tradebrain_schema(db_path)
    exchange = listing.exchange
    symbol = listing.symbol.strip().upper()
    isin = normalize_isin(listing.isin)
    valid_isin = bool(isin and len(isin) == 12)
    issuer_id = listing.issuer_entity_id

    if issuer_id is None and valid_isin:
        issuer_id = f"issuer:isin:{isin}"

    with _connect(db_path) as conn:
        if issuer_id:
            conn.execute(
                """
                INSERT INTO tb_issuer_entities(issuer_entity_id, display_name)
                VALUES (?, ?)
                ON CONFLICT(issuer_entity_id) DO UPDATE SET
                    display_name=COALESCE(excluded.display_name, tb_issuer_entities.display_name),
                    updated_at=datetime('now')
                """,
                (issuer_id, listing_name or security_name),
            )

        if valid_isin and issuer_id:
            conn.execute(
                """
                INSERT INTO tb_canonical_securities(isin, issuer_entity_id, security_name)
                VALUES (?, ?, ?)
                ON CONFLICT(isin) DO UPDATE SET
                    issuer_entity_id=excluded.issuer_entity_id,
                    security_name=COALESCE(excluded.security_name, tb_canonical_securities.security_name),
                    updated_at=datetime('now')
                """,
                (isin, issuer_id, security_name or listing_name),
            )

        conn.execute(
            """
            INSERT INTO tb_exchange_listings(
                exchange, symbol, isin, issuer_entity_id, listing_name,
                listing_status, source_key, source_timestamp
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(exchange, symbol) DO UPDATE SET
                isin=excluded.isin,
                issuer_entity_id=excluded.issuer_entity_id,
                listing_name=COALESCE(excluded.listing_name, tb_exchange_listings.listing_name),
                listing_status=excluded.listing_status,
                source_key=excluded.source_key,
                source_timestamp=excluded.source_timestamp,
                updated_at=datetime('now')
            """,
            (
                exchange,
                symbol,
                isin if valid_isin else None,
                issuer_id,
                listing_name,
                listing_status,
                source_key,
                source_timestamp,
            ),
        )

    return {
        "exchange": exchange,
        "symbol": symbol,
        "isin": isin if valid_isin else None,
        "issuer_entity_id": issuer_id,
        "identity_verified_for_merge": valid_isin,
    }


def record_raw_artifact(
    *,
    source_key: str,
    source_url: str | None,
    fetched_at: str,
    sha256: str,
    raw_archive_path: str | None = None,
    parser_version: str | None = None,
    db_path: str | None = None,
) -> str:
    ensure_tradebrain_schema(db_path)
    artifact_id = str(uuid.uuid4())
    with _connect(db_path) as conn:
        existing = conn.execute(
            "SELECT artifact_id FROM tb_raw_source_artifacts WHERE source_key=? AND sha256=?",
            (source_key, sha256),
        ).fetchone()
        if existing:
            return str(existing["artifact_id"])
        conn.execute(
            """
            INSERT INTO tb_raw_source_artifacts(
                artifact_id, source_key, source_url, fetched_at, sha256,
                raw_archive_path, parser_version
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                artifact_id,
                source_key,
                source_url,
                fetched_at,
                sha256,
                raw_archive_path,
                parser_version,
            ),
        )
    return artifact_id


def record_plan_evaluation(
    plan: TradePlan,
    result: GateResult,
    *,
    plan_id: str | None = None,
    db_path: str | None = None,
) -> str:
    ensure_tradebrain_schema(db_path)
    plan_id = plan_id or str(uuid.uuid4())
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO tb_trade_plan_evaluations(
                plan_id, ticker, exchange, mode, direction, entry, stop_loss,
                take_profit, quantity, crash_guard, broker_allows_trade,
                reward_risk, gate_action, allowed_for_advisory, hard_rule_failures,
                warnings, evidence, evaluated_at_ist
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                plan_id,
                plan.ticker,
                plan.exchange,
                plan.mode,
                plan.direction,
                plan.entry,
                plan.stop_loss,
                plan.take_profit,
                plan.quantity,
                plan.crash_guard,
                int(plan.broker_allows_trade),
                result.reward_risk,
                result.action,
                int(result.allowed_for_advisory),
                json.dumps(result.hard_rule_failures),
                json.dumps(result.warnings),
                json.dumps(plan.evidence),
                result.evaluated_at_ist,
            ),
        )
    return plan_id


def record_plan_outcome(
    plan_id: str,
    *,
    outcome: str,
    exit_price: float | None = None,
    exit_timestamp: str | None = None,
    mae_pct: float | None = None,
    mfe_pct: float | None = None,
    r_multiple: float | None = None,
    time_to_event_minutes: float | None = None,
    notes: str | None = None,
    db_path: str | None = None,
) -> None:
    ensure_tradebrain_schema(db_path)
    with _connect(db_path) as conn:
        exists = conn.execute(
            "SELECT 1 FROM tb_trade_plan_evaluations WHERE plan_id=?",
            (plan_id,),
        ).fetchone()
        if not exists:
            raise ValueError(f"Unknown plan_id: {plan_id}")
        conn.execute(
            """
            INSERT INTO tb_trade_plan_outcomes(
                plan_id, outcome, exit_price, exit_timestamp, mae_pct, mfe_pct,
                r_multiple, time_to_event_minutes, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(plan_id) DO UPDATE SET
                outcome=excluded.outcome,
                exit_price=excluded.exit_price,
                exit_timestamp=excluded.exit_timestamp,
                mae_pct=excluded.mae_pct,
                mfe_pct=excluded.mfe_pct,
                r_multiple=excluded.r_multiple,
                time_to_event_minutes=excluded.time_to_event_minutes,
                notes=excluded.notes,
                updated_at=datetime('now')
            """,
            (
                plan_id,
                outcome,
                exit_price,
                exit_timestamp,
                mae_pct,
                mfe_pct,
                r_multiple,
                time_to_event_minutes,
                notes,
            ),
        )


def store_stats(db_path: str | None = None) -> dict:
    ensure_tradebrain_schema(db_path)
    tables = [
        "tb_sources",
        "tb_issuer_entities",
        "tb_canonical_securities",
        "tb_exchange_listings",
        "tb_raw_source_artifacts",
        "tb_trade_plan_evaluations",
        "tb_trade_plan_outcomes",
    ]
    with _connect(db_path) as conn:
        return {
            table: conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
            for table in tables
        }
