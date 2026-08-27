"""Point-in-time news/context archive for BSE research.

Live RSS/yfinance articles are useful only from the moment Trade Brain actually observed
them. This store records `first_seen_at` and therefore prevents future backtests from
pretending today's web/news fetch was available in the past. Official exchange corporate
events remain a separate, stronger evidence source.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterable

from backend.db import DB_PATH

METHOD_VERSION = "BSE_POINT_IN_TIME_NEWS_ARCHIVE_V1"

BSE_KEYWORDS = (
    "bse ltd",
    "bse limited",
    "bombay stock exchange",
    "nse:bse",
)
CONTEXT_KEYWORDS = (
    "sebi",
    "stock exchange",
    "capital market",
    "nifty",
    "sensex",
    "fii",
    "dii",
    "rbi",
)


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


def ensure_news_archive_schema(db_path: str | None = None) -> None:
    with _connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS tb_news_archive (
                article_id TEXT PRIMARY KEY,
                source TEXT,
                source_type TEXT,
                title TEXT NOT NULL,
                summary TEXT,
                url TEXT,
                published_at_source TEXT,
                query_context TEXT,
                relevance TEXT NOT NULL,
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                observation_count INTEGER NOT NULL DEFAULT 1,
                raw_json TEXT NOT NULL,
                method_version TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_tb_news_archive_first_seen
                ON tb_news_archive(first_seen_at, relevance);
            CREATE INDEX IF NOT EXISTS idx_tb_news_archive_relevance
                ON tb_news_archive(relevance, first_seen_at DESC);
            """
        )


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split())


def _article_id(article: dict[str, Any]) -> str:
    stable = "|".join([
        _clean(article.get("source")).lower(),
        _clean(article.get("url")).lower(),
        _clean(article.get("title")).lower(),
    ])
    return "news:" + hashlib.sha256(stable.encode("utf-8")).hexdigest()


def classify_relevance(article: dict[str, Any]) -> str:
    text = f"{_clean(article.get('title'))} {_clean(article.get('summary'))}".lower()
    if any(keyword in text for keyword in BSE_KEYWORDS):
        return "BSE_DIRECT"
    if any(keyword in text for keyword in CONTEXT_KEYWORDS):
        return "BSE_MARKET_CONTEXT"
    return "GENERAL_MARKET_CONTEXT"


def archive_articles(
    articles: Iterable[dict[str, Any]],
    *,
    query_context: str,
    observed_at: datetime | None = None,
    db_path: str | None = None,
) -> dict[str, Any]:
    now = observed_at or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    seen_at = now.astimezone(timezone.utc).isoformat()
    ensure_news_archive_schema(db_path)
    inserted = 0
    updated = 0
    by_relevance: dict[str, int] = {}

    with _connect(db_path) as conn:
        for raw in articles:
            title = _clean(raw.get("title"))
            if not title:
                continue
            article = dict(raw)
            aid = _article_id(article)
            relevance = classify_relevance(article)
            by_relevance[relevance] = by_relevance.get(relevance, 0) + 1
            existing = conn.execute(
                "SELECT article_id FROM tb_news_archive WHERE article_id=?", (aid,)
            ).fetchone()
            payload = json.dumps(article, sort_keys=True, ensure_ascii=False, default=str)
            if existing:
                conn.execute(
                    """
                    UPDATE tb_news_archive SET
                        source=?, source_type=?, title=?, summary=?, url=?,
                        published_at_source=?, query_context=?, relevance=?,
                        last_seen_at=?, observation_count=observation_count+1,
                        raw_json=?, method_version=?
                    WHERE article_id=?
                    """,
                    (
                        _clean(article.get("source")) or None,
                        _clean(article.get("source_type")) or None,
                        title,
                        _clean(article.get("summary")) or None,
                        _clean(article.get("url")) or None,
                        _clean(article.get("published_at")) or None,
                        query_context,
                        relevance,
                        seen_at,
                        payload,
                        METHOD_VERSION,
                        aid,
                    ),
                )
                updated += 1
            else:
                conn.execute(
                    """
                    INSERT INTO tb_news_archive(
                        article_id, source, source_type, title, summary, url,
                        published_at_source, query_context, relevance,
                        first_seen_at, last_seen_at, observation_count, raw_json, method_version
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,1,?,?)
                    """,
                    (
                        aid,
                        _clean(article.get("source")) or None,
                        _clean(article.get("source_type")) or None,
                        title,
                        _clean(article.get("summary")) or None,
                        _clean(article.get("url")) or None,
                        _clean(article.get("published_at")) or None,
                        query_context,
                        relevance,
                        seen_at,
                        seen_at,
                        payload,
                        METHOD_VERSION,
                    ),
                )
                inserted += 1

    return {
        "method_version": METHOD_VERSION,
        "observed_at": seen_at,
        "inserted": inserted,
        "updated": updated,
        "seen": inserted + updated,
        "by_relevance": dict(sorted(by_relevance.items())),
        "historical_eligibility_boundary": "first_seen_at <= analysis_as_of",
        "published_at_source_is_not_assumed_timezone_aware": True,
        "retroactive_pre_first_seen_use_allowed": False,
        "trade_authorization": False,
        "order_execution_allowed": False,
    }


def archive_current_bse_context_news(
    *,
    max_per_source: int = 4,
    observed_at: datetime | None = None,
    db_path: str | None = None,
) -> dict[str, Any]:
    """Fetch once and archive BSE-specific + broader Indian market context news."""
    from backend.news_sources import fetch_all_news, fetch_ticker_news

    bse_articles = fetch_ticker_news("BSE", max_items=20)
    market_articles = fetch_all_news(max_per_source=max_per_source)
    direct = archive_articles(
        bse_articles,
        query_context="BSE_TICKER_NEWS",
        observed_at=observed_at,
        db_path=db_path,
    )
    context = archive_articles(
        market_articles,
        query_context="INDIA_MARKET_CONTEXT",
        observed_at=observed_at,
        db_path=db_path,
    )
    return {
        "method_version": METHOD_VERSION,
        "bse_ticker_fetch": direct,
        "india_context_fetch": context,
        "official_exchange_events_are_separate_stronger_source": True,
        "retroactive_sentiment_backfill_claimed": False,
        "trade_authorization": False,
        "order_execution_allowed": False,
    }


def query_news_known_by(
    as_of: str | datetime,
    *,
    relevance: str | None = None,
    limit: int = 500,
    db_path: str | None = None,
) -> list[dict[str, Any]]:
    """Return only articles Trade Brain had actually observed by `as_of`."""
    if isinstance(as_of, str):
        cutoff = datetime.fromisoformat(as_of)
    else:
        cutoff = as_of
    if cutoff.tzinfo is None:
        cutoff = cutoff.replace(tzinfo=timezone.utc)
    cutoff_iso = cutoff.astimezone(timezone.utc).isoformat()
    ensure_news_archive_schema(db_path)
    clauses = ["first_seen_at <= ?"]
    args: list[Any] = [cutoff_iso]
    if relevance:
        clauses.append("relevance = ?")
        args.append(relevance.upper())
    n = max(1, min(int(limit), 5000))
    with _connect(db_path) as conn:
        rows = conn.execute(
            f"""
            SELECT article_id, source, source_type, title, summary, url,
                   published_at_source, query_context, relevance,
                   first_seen_at, last_seen_at, observation_count, method_version
            FROM tb_news_archive
            WHERE {' AND '.join(clauses)}
            ORDER BY first_seen_at DESC
            LIMIT ?
            """,
            (*args, n),
        ).fetchall()
    return [dict(row) for row in rows]
