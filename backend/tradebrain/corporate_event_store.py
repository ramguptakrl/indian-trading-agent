"""Persistent corporate-event/document memory for Trade Brain Phase 2.

This layer is intentionally additive (`tb_*` tables) and keeps official facts,
identity resolution, heuristic classification, document state, and research queue
status separate. Exact exchange listing / ISIN matches are allowed; fuzzy entity
merges are not performed here.
"""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from typing import Any

from backend.db import DB_PATH
from backend.tradebrain.security_store import ensure_security_master_schema

EVENT_STATUSES = {"NEW", "REVIEWED", "ARCHIVED", "IGNORED"}
QUEUE_STATUSES = {"PENDING", "IN_REVIEW", "DONE", "DISMISSED"}


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


def ensure_corporate_event_schema(db_path: str | None = None) -> None:
    ensure_security_master_schema(db_path)
    with _connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS tb_corporate_events (
                event_id TEXT PRIMARY KEY,
                source_key TEXT NOT NULL,
                exchange TEXT NOT NULL,
                source_event_id TEXT,
                event_fingerprint TEXT NOT NULL,
                listing_symbol TEXT,
                isin TEXT,
                issuer_entity_id TEXT,
                company_name TEXT,
                subject TEXT,
                details TEXT,
                category TEXT,
                subcategory TEXT,
                source_category TEXT,
                importance TEXT,
                importance_basis TEXT,
                classification_version TEXT,
                announced_at TEXT,
                source_url TEXT,
                attachment_url TEXT,
                raw_artifact_id TEXT,
                raw_item_sha256 TEXT,
                identity_status TEXT DEFAULT 'UNRESOLVED',
                identity_method TEXT,
                source_critical INTEGER DEFAULT 0,
                inbox_status TEXT DEFAULT 'NEW',
                received_at TEXT NOT NULL,
                raw_payload_json TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now')),
                UNIQUE(source_key, source_event_id)
            );

            CREATE INDEX IF NOT EXISTS idx_tb_events_announced
                ON tb_corporate_events(announced_at DESC);
            CREATE INDEX IF NOT EXISTS idx_tb_events_inbox
                ON tb_corporate_events(inbox_status, announced_at DESC);
            CREATE INDEX IF NOT EXISTS idx_tb_events_identity
                ON tb_corporate_events(exchange, listing_symbol, isin);
            CREATE INDEX IF NOT EXISTS idx_tb_events_issuer
                ON tb_corporate_events(issuer_entity_id, announced_at DESC);

            CREATE TABLE IF NOT EXISTS tb_documents (
                document_id TEXT PRIMARY KEY,
                sha256 TEXT NOT NULL UNIQUE,
                source_url TEXT,
                source_host TEXT,
                mime_type TEXT,
                file_extension TEXT,
                size_bytes INTEGER NOT NULL,
                local_path TEXT NOT NULL,
                fetched_at TEXT NOT NULL,
                extraction_status TEXT DEFAULT 'NOT_ATTEMPTED',
                extracted_text_path TEXT,
                extracted_text_sha256 TEXT,
                text_chars INTEGER,
                page_count INTEGER,
                metadata_json TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS tb_event_documents (
                event_id TEXT NOT NULL,
                document_id TEXT NOT NULL,
                role TEXT DEFAULT 'ATTACHMENT',
                source_url TEXT,
                linked_at TEXT DEFAULT (datetime('now')),
                PRIMARY KEY (event_id, document_id),
                FOREIGN KEY (event_id) REFERENCES tb_corporate_events(event_id),
                FOREIGN KEY (document_id) REFERENCES tb_documents(document_id)
            );

            CREATE TABLE IF NOT EXISTS tb_change_queue (
                queue_id TEXT PRIMARY KEY,
                event_id TEXT NOT NULL UNIQUE,
                priority TEXT NOT NULL,
                reason TEXT NOT NULL,
                status TEXT DEFAULT 'PENDING',
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (event_id) REFERENCES tb_corporate_events(event_id)
            );

            CREATE INDEX IF NOT EXISTS idx_tb_change_queue_status
                ON tb_change_queue(status, priority, created_at);
            """
        )


def _resolve_identity(conn: sqlite3.Connection, event: dict[str, Any]) -> dict[str, Any]:
    """Resolve only exact exchange-listing or exact ISIN identity."""
    exchange = str(event.get("exchange") or "").strip().upper()
    symbol = str(event.get("listing_symbol") or "").strip().upper() or None
    isin = str(event.get("isin") or "").strip().upper() or None

    row = None
    method = None
    if isin and len(isin) == 12:
        row = conn.execute(
            """
            SELECT c.isin, c.issuer_entity_id, c.security_name,
                   NULL AS exchange, NULL AS symbol, NULL AS listing_name
            FROM tb_canonical_securities c
            WHERE c.isin=?
            """,
            (isin,),
        ).fetchone()
        method = "EXACT_ISIN" if row else None

    if row is None and exchange in {"NSE", "BSE"} and symbol:
        row = conn.execute(
            """
            SELECT l.isin, l.issuer_entity_id, c.security_name,
                   l.exchange, l.symbol, l.listing_name
            FROM tb_exchange_listings l
            LEFT JOIN tb_canonical_securities c ON c.isin=l.isin
            WHERE l.exchange=? AND l.symbol=?
            """,
            (exchange, symbol),
        ).fetchone()
        method = "EXACT_EXCHANGE_LISTING" if row else None

    if row is None:
        return {
            "identity_status": "UNRESOLVED",
            "identity_method": None,
            "isin": isin,
            "issuer_entity_id": None,
            "listing_symbol": symbol,
        }

    return {
        "identity_status": "RESOLVED",
        "identity_method": method,
        "isin": row["isin"],
        "issuer_entity_id": row["issuer_entity_id"],
        "listing_symbol": symbol or row["symbol"],
        "company_name": event.get("company_name") or row["listing_name"] or row["security_name"],
    }


def bulk_upsert_events(
    events: list[dict[str, Any]],
    *,
    db_path: str | None = None,
) -> dict[str, int]:
    """Upsert normalized events in one transaction and populate research queue."""
    ensure_corporate_event_schema(db_path)
    inserted = updated = linked = unresolved = queued = 0

    with _connect(db_path) as conn:
        for event in events:
            identity = _resolve_identity(conn, event)
            existing = conn.execute(
                "SELECT inbox_status FROM tb_corporate_events WHERE event_id=?",
                (event["event_id"],),
            ).fetchone()

            conn.execute(
                """
                INSERT INTO tb_corporate_events(
                    event_id, source_key, exchange, source_event_id, event_fingerprint,
                    listing_symbol, isin, issuer_entity_id, company_name, subject, details,
                    category, subcategory, source_category, importance, importance_basis,
                    classification_version, announced_at, source_url, attachment_url,
                    raw_artifact_id, raw_item_sha256, identity_status, identity_method,
                    source_critical, inbox_status, received_at, raw_payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(event_id) DO UPDATE SET
                    source_event_id=COALESCE(excluded.source_event_id, tb_corporate_events.source_event_id),
                    event_fingerprint=excluded.event_fingerprint,
                    listing_symbol=COALESCE(excluded.listing_symbol, tb_corporate_events.listing_symbol),
                    isin=COALESCE(excluded.isin, tb_corporate_events.isin),
                    issuer_entity_id=COALESCE(excluded.issuer_entity_id, tb_corporate_events.issuer_entity_id),
                    company_name=COALESCE(excluded.company_name, tb_corporate_events.company_name),
                    subject=COALESCE(excluded.subject, tb_corporate_events.subject),
                    details=COALESCE(excluded.details, tb_corporate_events.details),
                    category=excluded.category,
                    subcategory=COALESCE(excluded.subcategory, tb_corporate_events.subcategory),
                    source_category=COALESCE(excluded.source_category, tb_corporate_events.source_category),
                    importance=excluded.importance,
                    importance_basis=excluded.importance_basis,
                    classification_version=excluded.classification_version,
                    announced_at=COALESCE(excluded.announced_at, tb_corporate_events.announced_at),
                    source_url=COALESCE(excluded.source_url, tb_corporate_events.source_url),
                    attachment_url=COALESCE(excluded.attachment_url, tb_corporate_events.attachment_url),
                    raw_artifact_id=COALESCE(excluded.raw_artifact_id, tb_corporate_events.raw_artifact_id),
                    raw_item_sha256=excluded.raw_item_sha256,
                    identity_status=excluded.identity_status,
                    identity_method=COALESCE(excluded.identity_method, tb_corporate_events.identity_method),
                    source_critical=MAX(tb_corporate_events.source_critical, excluded.source_critical),
                    received_at=excluded.received_at,
                    raw_payload_json=excluded.raw_payload_json,
                    updated_at=datetime('now')
                """,
                (
                    event["event_id"], event["source_key"], event["exchange"], event.get("source_event_id"),
                    event["event_fingerprint"], identity.get("listing_symbol"), identity.get("isin"),
                    identity.get("issuer_entity_id"), identity.get("company_name") or event.get("company_name"),
                    event.get("subject"), event.get("details"), event.get("category", "GENERAL"),
                    event.get("subcategory"), event.get("source_category"), event.get("importance", "LOW"),
                    event.get("importance_basis"), event.get("classification_version"), event.get("announced_at"),
                    event.get("source_url"), event.get("attachment_url"), event.get("raw_artifact_id"),
                    event.get("raw_item_sha256"), identity["identity_status"], identity.get("identity_method"),
                    int(bool(event.get("source_critical"))), existing["inbox_status"] if existing else "NEW",
                    event["received_at"], json.dumps(event.get("raw_payload") or {}, ensure_ascii=False, default=str),
                ),
            )

            if existing:
                updated += 1
            else:
                inserted += 1
            if identity["identity_status"] == "RESOLVED":
                linked += 1
            else:
                unresolved += 1

            if event.get("queue_for_change_review"):
                before = conn.execute("SELECT 1 FROM tb_change_queue WHERE event_id=?", (event["event_id"],)).fetchone()
                conn.execute(
                    """
                    INSERT INTO tb_change_queue(queue_id, event_id, priority, reason)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(event_id) DO UPDATE SET
                        priority=excluded.priority,
                        reason=excluded.reason,
                        updated_at=datetime('now')
                    """,
                    (
                        str(uuid.uuid4()), event["event_id"], event.get("queue_priority", "MEDIUM"),
                        event.get("queue_reason") or "Material corporate event requires change review",
                    ),
                )
                if before is None:
                    queued += 1

    return {
        "events_inserted": inserted,
        "events_updated": updated,
        "events_linked_to_entity": linked,
        "events_unresolved": unresolved,
        "change_queue_created": queued,
    }


def event_stats(db_path: str | None = None) -> dict[str, Any]:
    ensure_corporate_event_schema(db_path)
    with _connect(db_path) as conn:
        scalar = lambda sql, args=(): conn.execute(sql, args).fetchone()[0]
        by_exchange = {
            row["exchange"]: row["n"]
            for row in conn.execute("SELECT exchange, COUNT(*) n FROM tb_corporate_events GROUP BY exchange")
        }
        by_importance = {
            row["importance"]: row["n"]
            for row in conn.execute("SELECT importance, COUNT(*) n FROM tb_corporate_events GROUP BY importance")
        }
        return {
            "total_events": scalar("SELECT COUNT(*) FROM tb_corporate_events"),
            "new_events": scalar("SELECT COUNT(*) FROM tb_corporate_events WHERE inbox_status='NEW'"),
            "linked_events": scalar("SELECT COUNT(*) FROM tb_corporate_events WHERE identity_status='RESOLVED'"),
            "unresolved_events": scalar("SELECT COUNT(*) FROM tb_corporate_events WHERE identity_status!='RESOLVED'"),
            "events_with_attachment_url": scalar("SELECT COUNT(*) FROM tb_corporate_events WHERE attachment_url IS NOT NULL AND attachment_url!=''"),
            "documents": scalar("SELECT COUNT(*) FROM tb_documents"),
            "documents_with_text": scalar("SELECT COUNT(*) FROM tb_documents WHERE extraction_status='TEXT_EXTRACTED'"),
            "pending_change_reviews": scalar("SELECT COUNT(*) FROM tb_change_queue WHERE status='PENDING'"),
            "by_exchange": by_exchange,
            "by_importance": by_importance,
        }


def list_events(
    *,
    status: str | None = "NEW",
    exchange: str | None = None,
    limit: int = 50,
    offset: int = 0,
    db_path: str | None = None,
) -> list[dict[str, Any]]:
    ensure_corporate_event_schema(db_path)
    clauses: list[str] = []
    args: list[Any] = []
    if status:
        clauses.append("e.inbox_status=?")
        args.append(status.upper())
    if exchange:
        clauses.append("e.exchange=?")
        args.append(exchange.upper())
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    sql = f"""
        SELECT e.*,
               (SELECT COUNT(*) FROM tb_event_documents ed WHERE ed.event_id=e.event_id) AS document_count,
               (SELECT status FROM tb_change_queue q WHERE q.event_id=e.event_id) AS change_queue_status
        FROM tb_corporate_events e
        {where}
        ORDER BY COALESCE(e.announced_at, e.received_at) DESC
        LIMIT ? OFFSET ?
    """
    args.extend([max(1, min(limit, 500)), max(0, offset)])
    with _connect(db_path) as conn:
        rows = conn.execute(sql, args).fetchall()
    return [_decode_event_row(row) for row in rows]


def get_event(event_id: str, db_path: str | None = None) -> dict[str, Any] | None:
    ensure_corporate_event_schema(db_path)
    with _connect(db_path) as conn:
        row = conn.execute("SELECT * FROM tb_corporate_events WHERE event_id=?", (event_id,)).fetchone()
        if not row:
            return None
        docs = conn.execute(
            """
            SELECT d.*, ed.role, ed.source_url AS event_document_source_url
            FROM tb_event_documents ed
            JOIN tb_documents d ON d.document_id=ed.document_id
            WHERE ed.event_id=?
            ORDER BY ed.linked_at
            """,
            (event_id,),
        ).fetchall()
        queue = conn.execute("SELECT * FROM tb_change_queue WHERE event_id=?", (event_id,)).fetchone()
    result = _decode_event_row(row)
    result["documents"] = [_decode_document_row(r) for r in docs]
    result["change_queue"] = dict(queue) if queue else None
    return result


def set_event_status(event_id: str, status: str, db_path: str | None = None) -> None:
    value = status.upper()
    if value not in EVENT_STATUSES:
        raise ValueError(f"Unsupported event status: {status}")
    ensure_corporate_event_schema(db_path)
    with _connect(db_path) as conn:
        cur = conn.execute(
            "UPDATE tb_corporate_events SET inbox_status=?, updated_at=datetime('now') WHERE event_id=?",
            (value, event_id),
        )
        if cur.rowcount == 0:
            raise ValueError(f"Unknown event_id: {event_id}")


def list_change_queue(
    *, status: str | None = "PENDING", limit: int = 100, db_path: str | None = None
) -> list[dict[str, Any]]:
    ensure_corporate_event_schema(db_path)
    args: list[Any] = []
    where = ""
    if status:
        where = "WHERE q.status=?"
        args.append(status.upper())
    args.append(max(1, min(limit, 500)))
    with _connect(db_path) as conn:
        rows = conn.execute(
            f"""
            SELECT q.*, e.exchange, e.listing_symbol, e.isin, e.issuer_entity_id,
                   e.company_name, e.subject, e.details, e.category, e.importance,
                   e.announced_at, e.attachment_url
            FROM tb_change_queue q
            JOIN tb_corporate_events e ON e.event_id=q.event_id
            {where}
            ORDER BY CASE q.priority WHEN 'HIGH' THEN 0 WHEN 'MEDIUM' THEN 1 ELSE 2 END,
                     COALESCE(e.announced_at, e.received_at) DESC
            LIMIT ?
            """,
            args,
        ).fetchall()
    return [dict(row) for row in rows]


def set_change_queue_status(queue_id: str, status: str, db_path: str | None = None) -> None:
    value = status.upper()
    if value not in QUEUE_STATUSES:
        raise ValueError(f"Unsupported queue status: {status}")
    ensure_corporate_event_schema(db_path)
    with _connect(db_path) as conn:
        cur = conn.execute(
            "UPDATE tb_change_queue SET status=?, updated_at=datetime('now') WHERE queue_id=?",
            (value, queue_id),
        )
        if cur.rowcount == 0:
            raise ValueError(f"Unknown queue_id: {queue_id}")


def get_event_attachment(event_id: str, db_path: str | None = None) -> dict[str, Any] | None:
    ensure_corporate_event_schema(db_path)
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT event_id, exchange, source_key, attachment_url FROM tb_corporate_events WHERE event_id=?",
            (event_id,),
        ).fetchone()
    return dict(row) if row else None


def upsert_document(
    *,
    sha256: str,
    source_url: str,
    source_host: str,
    mime_type: str | None,
    file_extension: str,
    size_bytes: int,
    local_path: str,
    fetched_at: str,
    extraction_status: str,
    extracted_text_path: str | None,
    extracted_text_sha256: str | None,
    text_chars: int | None,
    page_count: int | None,
    metadata: dict[str, Any] | None = None,
    db_path: str | None = None,
) -> str:
    ensure_corporate_event_schema(db_path)
    document_id = f"doc:{sha256}"
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO tb_documents(
                document_id, sha256, source_url, source_host, mime_type, file_extension,
                size_bytes, local_path, fetched_at, extraction_status, extracted_text_path,
                extracted_text_sha256, text_chars, page_count, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(sha256) DO UPDATE SET
                source_url=COALESCE(tb_documents.source_url, excluded.source_url),
                source_host=COALESCE(tb_documents.source_host, excluded.source_host),
                mime_type=COALESCE(tb_documents.mime_type, excluded.mime_type),
                extraction_status=CASE
                    WHEN tb_documents.extraction_status='TEXT_EXTRACTED' THEN tb_documents.extraction_status
                    ELSE excluded.extraction_status END,
                extracted_text_path=COALESCE(tb_documents.extracted_text_path, excluded.extracted_text_path),
                extracted_text_sha256=COALESCE(tb_documents.extracted_text_sha256, excluded.extracted_text_sha256),
                text_chars=COALESCE(tb_documents.text_chars, excluded.text_chars),
                page_count=COALESCE(tb_documents.page_count, excluded.page_count),
                metadata_json=COALESCE(tb_documents.metadata_json, excluded.metadata_json),
                updated_at=datetime('now')
            """,
            (
                document_id, sha256, source_url, source_host, mime_type, file_extension,
                size_bytes, local_path, fetched_at, extraction_status, extracted_text_path,
                extracted_text_sha256, text_chars, page_count,
                json.dumps(metadata or {}, ensure_ascii=False, default=str),
            ),
        )
    return document_id


def link_event_document(
    event_id: str, document_id: str, source_url: str, *, db_path: str | None = None
) -> None:
    ensure_corporate_event_schema(db_path)
    with _connect(db_path) as conn:
        event_exists = conn.execute("SELECT 1 FROM tb_corporate_events WHERE event_id=?", (event_id,)).fetchone()
        if not event_exists:
            raise ValueError(f"Unknown event_id: {event_id}")
        conn.execute(
            """
            INSERT INTO tb_event_documents(event_id, document_id, source_url)
            VALUES (?, ?, ?)
            ON CONFLICT(event_id, document_id) DO NOTHING
            """,
            (event_id, document_id, source_url),
        )


def get_document(document_id: str, db_path: str | None = None) -> dict[str, Any] | None:
    ensure_corporate_event_schema(db_path)
    with _connect(db_path) as conn:
        row = conn.execute("SELECT * FROM tb_documents WHERE document_id=?", (document_id,)).fetchone()
        if not row:
            return None
        events = conn.execute(
            "SELECT event_id, role, source_url, linked_at FROM tb_event_documents WHERE document_id=?",
            (document_id,),
        ).fetchall()
    result = _decode_document_row(row)
    result["events"] = [dict(r) for r in events]
    return result


def latest_raw_artifact(source_key: str, db_path: str | None = None) -> dict[str, Any] | None:
    ensure_corporate_event_schema(db_path)
    with _connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT artifact_id, source_key, source_url, fetched_at, sha256, raw_archive_path, parser_version
            FROM tb_raw_source_artifacts
            WHERE source_key=?
            ORDER BY fetched_at DESC
            LIMIT 1
            """,
            (source_key,),
        ).fetchone()
    return dict(row) if row else None


def _decode_event_row(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    try:
        result["raw_payload"] = json.loads(result.pop("raw_payload_json") or "{}")
    except json.JSONDecodeError:
        result["raw_payload"] = {}
        result.pop("raw_payload_json", None)
    return result


def _decode_document_row(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    try:
        result["metadata"] = json.loads(result.pop("metadata_json") or "{}")
    except json.JSONDecodeError:
        result["metadata"] = {}
        result.pop("metadata_json", None)
    return result
