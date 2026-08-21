"""Safe corporate-event identity re-resolution.

This is deliberately NOT fuzzy matching. It can only promote an unresolved event when:
1. its exact exchange+listing symbol now exists in the security master; or
2. its company name, after Unicode/case/whitespace normalization only, maps to exactly
   one listing name on that same exchange.

Punctuation, token similarity, edit distance, embeddings and LLM guesses are not used.
"""

from __future__ import annotations

import os
import sqlite3
import unicodedata
from collections import defaultdict
from contextlib import contextmanager
from typing import Any

from backend.db import DB_PATH
from backend.tradebrain.corporate_event_store import ensure_corporate_event_schema


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


def normalize_exact_name(value: str | None) -> str | None:
    if not value:
        return None
    text = unicodedata.normalize("NFKC", str(value))
    text = " ".join(text.split()).casefold().strip()
    return text or None


def resolve_unresolved_events_exactly(
    *, limit: int = 10000, db_path: str | None = None
) -> dict[str, Any]:
    ensure_corporate_event_schema(db_path)
    symbol_links = 0
    name_links = 0
    ambiguous_exact_names = 0
    still_unresolved = 0

    with _connect(db_path) as conn:
        events = conn.execute(
            """
            SELECT event_id, exchange, listing_symbol, company_name
            FROM tb_corporate_events
            WHERE identity_status!='RESOLVED'
            ORDER BY COALESCE(announced_at, received_at) DESC
            LIMIT ?
            """,
            (max(1, min(limit, 100000)),),
        ).fetchall()

        # First pass: exact listing identifiers. Useful when events arrived before a
        # security-master refresh populated the listing table.
        remaining: list[sqlite3.Row] = []
        for event in events:
            symbol = str(event["listing_symbol"] or "").strip().upper()
            exchange = str(event["exchange"] or "").strip().upper()
            if symbol and exchange in {"NSE", "BSE"}:
                listing = conn.execute(
                    """
                    SELECT symbol, isin, issuer_entity_id, listing_name
                    FROM tb_exchange_listings
                    WHERE exchange=? AND symbol=?
                    """,
                    (exchange, symbol),
                ).fetchone()
                if listing:
                    conn.execute(
                        """
                        UPDATE tb_corporate_events
                        SET isin=?, issuer_entity_id=?, company_name=COALESCE(company_name, ?),
                            identity_status='RESOLVED', identity_method='EXACT_EXCHANGE_LISTING',
                            updated_at=datetime('now')
                        WHERE event_id=?
                        """,
                        (listing["isin"], listing["issuer_entity_id"], listing["listing_name"], event["event_id"]),
                    )
                    symbol_links += 1
                    continue
            remaining.append(event)

        # Build exact normalized-name maps once per exchange. A normalized name that
        # maps to >1 listing is intentionally considered ambiguous and is never used.
        name_maps: dict[str, dict[str, list[sqlite3.Row]]] = {}
        for exchange in {str(row["exchange"] or "").upper() for row in remaining}:
            if exchange not in {"NSE", "BSE"}:
                continue
            grouped: dict[str, list[sqlite3.Row]] = defaultdict(list)
            for listing in conn.execute(
                """
                SELECT symbol, isin, issuer_entity_id, listing_name
                FROM tb_exchange_listings
                WHERE exchange=? AND listing_name IS NOT NULL AND listing_name!=''
                """,
                (exchange,),
            ).fetchall():
                key = normalize_exact_name(listing["listing_name"])
                if key:
                    grouped[key].append(listing)
            name_maps[exchange] = grouped

        for event in remaining:
            exchange = str(event["exchange"] or "").strip().upper()
            key = normalize_exact_name(event["company_name"])
            if not key or exchange not in name_maps:
                still_unresolved += 1
                continue
            matches = name_maps[exchange].get(key, [])
            if len(matches) != 1:
                if len(matches) > 1:
                    ambiguous_exact_names += 1
                still_unresolved += 1
                continue
            listing = matches[0]
            conn.execute(
                """
                UPDATE tb_corporate_events
                SET listing_symbol=?, isin=?, issuer_entity_id=?,
                    identity_status='RESOLVED', identity_method='EXACT_UNIQUE_LISTING_NAME',
                    updated_at=datetime('now')
                WHERE event_id=?
                """,
                (listing["symbol"], listing["isin"], listing["issuer_entity_id"], event["event_id"]),
            )
            name_links += 1

    return {
        "events_checked": len(events),
        "exact_symbol_links_added": symbol_links,
        "exact_unique_name_links_added": name_links,
        "ambiguous_exact_names_skipped": ambiguous_exact_names,
        "still_unresolved": still_unresolved,
        "fuzzy_matching_used": False,
    }
