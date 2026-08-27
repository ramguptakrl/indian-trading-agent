"""Security-master persistence extensions for the additive Trade Brain store."""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from typing import Any

from backend.db import DB_PATH
from backend.tradebrain.identity import ExchangeListing, normalize_isin
from backend.tradebrain.store import ensure_tradebrain_schema


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


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def ensure_security_master_schema(db_path: str | None = None) -> None:
    """Apply non-destructive columns needed by official exchange masters."""
    ensure_tradebrain_schema(db_path)
    with _connect(db_path) as conn:
        _ensure_column(conn, "tb_exchange_listings", "exchange_security_id", "TEXT")
        _ensure_column(conn, "tb_exchange_listings", "series", "TEXT")
        _ensure_column(conn, "tb_exchange_listings", "group_name", "TEXT")
        _ensure_column(conn, "tb_exchange_listings", "industry", "TEXT")
        _ensure_column(conn, "tb_exchange_listings", "metadata_json", "TEXT")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_tb_exchange_listings_exchange_security_id "
            "ON tb_exchange_listings(exchange, exchange_security_id)"
        )


def _valid_isin(isin: str | None) -> str | None:
    value = normalize_isin(isin)
    return value if value and len(value) == 12 and value.startswith("IN") else None


def bulk_upsert_listings(
    rows: list[dict[str, Any]],
    *,
    source_key: str,
    source_timestamp: str,
    db_path: str | None = None,
) -> dict:
    """Upsert a parsed official master in one transaction.

    Existing rows absent from this payload are deliberately untouched. A missing row
    is not evidence of delisting/suspension.
    """
    ensure_security_master_schema(db_path)
    inserted = 0
    updated = 0
    canonical_created = 0

    with _connect(db_path) as conn:
        for item in rows:
            listing: ExchangeListing = item["listing"]
            exchange = listing.exchange
            symbol = listing.symbol.strip().upper()
            isin = _valid_isin(listing.isin)
            if not isin:
                continue

            issuer_id = listing.issuer_entity_id or f"issuer:isin:{isin}"
            display_name = item.get("listing_name") or item.get("security_name") or symbol

            listing_exists = conn.execute(
                "SELECT 1 FROM tb_exchange_listings WHERE exchange=? AND symbol=?",
                (exchange, symbol),
            ).fetchone()
            security_exists = conn.execute(
                "SELECT 1 FROM tb_canonical_securities WHERE isin=?",
                (isin,),
            ).fetchone()

            conn.execute(
                """
                INSERT INTO tb_issuer_entities(issuer_entity_id, display_name)
                VALUES (?, ?)
                ON CONFLICT(issuer_entity_id) DO UPDATE SET
                    display_name=COALESCE(excluded.display_name, tb_issuer_entities.display_name),
                    updated_at=datetime('now')
                """,
                (issuer_id, display_name),
            )
            conn.execute(
                """
                INSERT INTO tb_canonical_securities(isin, issuer_entity_id, security_name)
                VALUES (?, ?, ?)
                ON CONFLICT(isin) DO UPDATE SET
                    issuer_entity_id=excluded.issuer_entity_id,
                    security_name=COALESCE(excluded.security_name, tb_canonical_securities.security_name),
                    updated_at=datetime('now')
                """,
                (isin, issuer_id, item.get("security_name") or display_name),
            )
            conn.execute(
                """
                INSERT INTO tb_exchange_listings(
                    exchange, symbol, isin, issuer_entity_id, listing_name,
                    listing_status, source_key, source_timestamp,
                    exchange_security_id, series, group_name, industry, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(exchange, symbol) DO UPDATE SET
                    isin=excluded.isin,
                    issuer_entity_id=excluded.issuer_entity_id,
                    listing_name=COALESCE(excluded.listing_name, tb_exchange_listings.listing_name),
                    listing_status=excluded.listing_status,
                    source_key=excluded.source_key,
                    source_timestamp=excluded.source_timestamp,
                    exchange_security_id=COALESCE(excluded.exchange_security_id, tb_exchange_listings.exchange_security_id),
                    series=COALESCE(excluded.series, tb_exchange_listings.series),
                    group_name=COALESCE(excluded.group_name, tb_exchange_listings.group_name),
                    industry=COALESCE(excluded.industry, tb_exchange_listings.industry),
                    metadata_json=COALESCE(excluded.metadata_json, tb_exchange_listings.metadata_json),
                    updated_at=datetime('now')
                """,
                (
                    exchange,
                    symbol,
                    isin,
                    issuer_id,
                    display_name,
                    item.get("listing_status", "ACTIVE"),
                    source_key,
                    source_timestamp,
                    item.get("exchange_security_id"),
                    item.get("series"),
                    item.get("group_name"),
                    item.get("industry"),
                    json.dumps(item.get("metadata") or {}, ensure_ascii=False, default=str),
                ),
            )

            if listing_exists:
                updated += 1
            else:
                inserted += 1
            if not security_exists:
                canonical_created += 1

    return {
        "rows_inserted": inserted,
        "rows_updated": updated,
        "canonical_created": canonical_created,
    }


def security_master_stats(db_path: str | None = None) -> dict:
    ensure_security_master_schema(db_path)
    with _connect(db_path) as conn:
        canonical = conn.execute("SELECT COUNT(*) n FROM tb_canonical_securities").fetchone()["n"]
        listings = conn.execute("SELECT COUNT(*) n FROM tb_exchange_listings").fetchone()["n"]
        nse = conn.execute("SELECT COUNT(*) n FROM tb_exchange_listings WHERE exchange='NSE'").fetchone()["n"]
        bse = conn.execute("SELECT COUNT(*) n FROM tb_exchange_listings WHERE exchange='BSE'").fetchone()["n"]
        dual = conn.execute(
            """
            SELECT COUNT(*) n FROM (
                SELECT isin
                FROM tb_exchange_listings
                WHERE isin IS NOT NULL
                GROUP BY isin
                HAVING COUNT(DISTINCT exchange) >= 2
            )
            """
        ).fetchone()["n"]
        official = conn.execute(
            "SELECT COUNT(*) n FROM tb_sources WHERE source_type='SECURITY_MASTER' AND is_official=1"
        ).fetchone()["n"]
        artifacts = conn.execute(
            """
            SELECT COUNT(*) n
            FROM tb_raw_source_artifacts
            WHERE source_key IN ('NSE_EQUITY_SECURITY_MASTER', 'BSE_EQUITY_SECURITY_MASTER')
            """
        ).fetchone()["n"]
    return {
        "canonical_securities": canonical,
        "mapped_exchange_listings": listings,
        "nse_listings": nse,
        "bse_listings": bse,
        "nse_bse_isin_matches": dual,
        "official_security_master_sources": official,
        "raw_security_master_artifacts": artifacts,
    }


def get_identity_by_isin(isin: str, db_path: str | None = None) -> dict | None:
    ensure_security_master_schema(db_path)
    normalized = _valid_isin(isin)
    if not normalized:
        return None
    with _connect(db_path) as conn:
        security = conn.execute(
            """
            SELECT c.isin, c.security_name, c.issuer_entity_id, i.display_name issuer_name
            FROM tb_canonical_securities c
            LEFT JOIN tb_issuer_entities i ON i.issuer_entity_id=c.issuer_entity_id
            WHERE c.isin=?
            """,
            (normalized,),
        ).fetchone()
        if not security:
            return None
        listings = conn.execute(
            """
            SELECT exchange, symbol, listing_name, listing_status, exchange_security_id,
                   series, group_name, industry, source_key, source_timestamp, updated_at
            FROM tb_exchange_listings
            WHERE isin=?
            ORDER BY exchange, symbol
            """,
            (normalized,),
        ).fetchall()
    return {**dict(security), "listings": [dict(row) for row in listings]}


def get_exchange_listing(exchange: str, symbol: str, db_path: str | None = None) -> dict | None:
    ensure_security_master_schema(db_path)
    with _connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT exchange, symbol, isin, issuer_entity_id, listing_name, listing_status,
                   exchange_security_id, series, group_name, industry, source_key,
                   source_timestamp, metadata_json, updated_at
            FROM tb_exchange_listings
            WHERE exchange=? AND symbol=?
            """,
            (exchange.strip().upper(), symbol.strip().upper()),
        ).fetchone()
    if not row:
        return None
    result = dict(row)
    try:
        result["metadata"] = json.loads(result.pop("metadata_json") or "{}")
    except json.JSONDecodeError:
        result["metadata"] = {}
        result.pop("metadata_json", None)
    return result
