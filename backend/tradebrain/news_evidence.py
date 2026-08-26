"""Official-first, point-in-time news evidence for Trade Brain's BSE Ltd analyst.

Evidence order is intentional:
1. Official NSE/BSE corporate-event memory for BSE Ltd.
2. Official SEBI circular/press-release context relevant to exchanges/clearing/market structure.
3. Point-in-time archived Indian financial media (Moneycontrol, ET, Mint, Business Standard,
   NDTV Profit, etc.).
4. Yahoo/Alpha Vantage remain supplementary discovery tools in the LLM agent.

The pack is evidence only. It never authorizes or places an order.
"""

from __future__ import annotations

from datetime import datetime, time, timezone
from html.parser import HTMLParser
from typing import Any
from zoneinfo import ZoneInfo

import requests

from backend.tradebrain.corporate_event_store import list_events
from backend.tradebrain.corporate_events import collect_nse_corporate_events
from backend.tradebrain.news_archive import (
    archive_current_bse_context_news,
    query_news_known_by,
)
from backend.tradebrain.trade_date import normalize_trade_date

IST = ZoneInfo("Asia/Kolkata")
BSE_ISIN = "INE118H01025"
SEBI_CIRCULARS_URL = "https://www.sebi.gov.in/sebiweb/home/HomeAction.do?doListing=yes&sid=1&smid=0&ssid=7"
SEBI_PRESS_URL = "https://www.sebi.gov.in/sebiweb/home/HomeAction.do?doListing=yes&sid=6&smid=0&ssid=23"
METHOD_VERSION = "BSE_NEWS_EVIDENCE_OFFICIAL_FIRST_V1"

_SEBI_RELEVANCE_TERMS = (
    "stock exchange", "exchange", "clearing", "derivative", "securities market",
    "market infrastructure", "mii", "surveillance", "price band", "trading",
    "settlement", "broker", "investor protection", "index provider", "technology",
)


class _AnchorParser(HTMLParser):
    """Tiny dependency-free anchor extractor for official SEBI listing pages."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._href: str | None = None
        self._text: list[str] = []
        self.anchors: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a" or self._href is not None:
            return
        values = dict(attrs)
        self._href = str(values.get("href") or "")
        self._text = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a" and self._href is not None:
            text = " ".join(" ".join(self._text).split())
            self.anchors.append((text, self._href))
            self._href = None
            self._text = []


def _cutoff(trade_date: str) -> datetime:
    day = datetime.fromisoformat(normalize_trade_date(trade_date)).date()
    return datetime.combine(day, time(23, 59, 59), tzinfo=IST).astimezone(timezone.utc)


def _is_today_ist(trade_date: str) -> bool:
    return datetime.fromisoformat(normalize_trade_date(trade_date)).date() == datetime.now(IST).date()


def _clip(value: Any, limit: int = 220) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _official_bse_events(cutoff: datetime, *, limit: int = 8) -> list[dict[str, Any]]:
    rows = list_events(status=None, limit=500)
    selected: list[dict[str, Any]] = []
    for row in rows:
        isin = str(row.get("isin") or "").upper()
        exchange = str(row.get("exchange") or "").upper()
        symbol = str(row.get("listing_symbol") or "").upper()
        if not (isin == BSE_ISIN or (exchange == "NSE" and symbol == "BSE")):
            continue
        announced = row.get("announced_at") or row.get("received_at")
        try:
            observed = datetime.fromisoformat(str(announced).replace("Z", "+00:00"))
            if observed.tzinfo is None:
                observed = observed.replace(tzinfo=timezone.utc)
            if observed.astimezone(timezone.utc) > cutoff:
                continue
        except Exception:
            continue
        selected.append({
            "source_tier": "OFFICIAL_EXCHANGE",
            "source": str(row.get("source_key") or exchange or "OFFICIAL_EXCHANGE"),
            "date": str(announced),
            "title": _clip(row.get("subject") or row.get("company_name"), 260),
            "detail": _clip(row.get("details"), 260),
            "url": str(row.get("attachment_url") or row.get("source_url") or ""),
            "official_fact": True,
        })
        if len(selected) >= limit:
            break
    return selected


def _fetch_sebi_listing(url: str, *, timeout: int = 12, limit: int = 6) -> list[dict[str, Any]]:
    """Read a small official SEBI listing page; failure is non-fatal and explicitly absent."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) TradeBrain/0.13",
        "Accept-Language": "en-US,en;q=0.9",
    }
    response = requests.get(url, headers=headers, timeout=timeout)
    response.raise_for_status()
    parser = _AnchorParser()
    parser.feed(response.text)
    items: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for raw_title, raw_href in parser.anchors:
        title = _clip(raw_title, 260)
        href = str(raw_href or "").strip()
        if not title or not any(term in title.lower() for term in _SEBI_RELEVANCE_TERMS):
            continue
        if href.startswith("/"):
            href = "https://www.sebi.gov.in" + href
        key = (title.casefold(), href)
        if key in seen:
            continue
        seen.add(key)
        items.append({
            "source_tier": "OFFICIAL_REGULATOR",
            "source": "SEBI",
            "date": "CURRENT_OFFICIAL_LISTING",
            "title": title,
            "detail": "Official SEBI circular/press-release listing context; open the official item for exact publication details.",
            "url": href or url,
            "official_fact": True,
        })
        if len(items) >= limit:
            break
    return items


def _archived_media(cutoff: datetime, *, limit: int = 8) -> list[dict[str, Any]]:
    rows = query_news_known_by(cutoff, limit=100)
    priority = {"BSE_DIRECT": 0, "BSE_MARKET_CONTEXT": 1, "GENERAL_MARKET_CONTEXT": 2}
    # query_news_known_by is already newest-first; stable sorting by relevance preserves
    # newest-first order within each relevance tier.
    rows.sort(key=lambda row: priority.get(str(row.get("relevance") or ""), 9))
    output: list[dict[str, Any]] = []
    for row in rows[:limit]:
        output.append({
            "source_tier": "MEDIA_CONTEXT",
            "source": str(row.get("source") or "UNKNOWN_MEDIA"),
            "date": str(row.get("published_at_source") or row.get("first_seen_at") or ""),
            "title": _clip(row.get("title"), 260),
            "detail": _clip(row.get("summary"), 260),
            "url": str(row.get("url") or ""),
            "relevance": str(row.get("relevance") or ""),
            "official_fact": False,
            "known_by": str(row.get("first_seen_at") or ""),
        })
    return output


def build_bse_news_evidence(trade_date: str) -> dict[str, Any]:
    """Build a compact official-first pack known by the requested analysis date."""
    cutoff = _cutoff(trade_date)
    refresh_notes: list[str] = []

    if _is_today_ist(trade_date):
        try:
            collect_nse_corporate_events(timeout=12)
            refresh_notes.append("NSE_OFFICIAL_REFRESH_OK")
        except Exception as exc:
            refresh_notes.append(f"NSE_OFFICIAL_REFRESH_UNAVAILABLE:{type(exc).__name__}")
        try:
            archive_current_bse_context_news(max_per_source=3)
            refresh_notes.append("MEDIA_ARCHIVE_REFRESH_OK")
        except Exception as exc:
            refresh_notes.append(f"MEDIA_ARCHIVE_REFRESH_UNAVAILABLE:{type(exc).__name__}")

    official_events = _official_bse_events(cutoff)
    sebi_items: list[dict[str, Any]] = []
    if _is_today_ist(trade_date):
        for url in (SEBI_CIRCULARS_URL, SEBI_PRESS_URL):
            try:
                sebi_items.extend(_fetch_sebi_listing(url, limit=4))
            except Exception as exc:
                refresh_notes.append(f"SEBI_OFFICIAL_REFRESH_UNAVAILABLE:{type(exc).__name__}")
    media = _archived_media(cutoff)

    return {
        "method_version": METHOD_VERSION,
        "analysis_date": normalize_trade_date(trade_date),
        "as_of_utc": cutoff.isoformat(),
        "source_priority": [
            "OFFICIAL_NSE_BSE_DISCLOSURES",
            "OFFICIAL_SEBI_REGULATORY_CONTEXT",
            "ARCHIVED_MAJOR_INDIAN_FINANCIAL_MEDIA",
            "YAHOO_ALPHA_VANTAGE_SUPPLEMENTARY_DISCOVERY",
        ],
        "official_company_events": official_events,
        "official_sebi_context": sebi_items[:6],
        "media_context": media,
        "refresh_notes": refresh_notes,
        "high_confidence_media_claim_requires_official_confirmation": True,
        "historical_media_requires_first_seen_at_before_cutoff": True,
        "trade_authorization": False,
        "order_execution_allowed": False,
    }


def news_evidence_for_prompt(trade_date: str) -> str:
    pack = build_bse_news_evidence(trade_date)
    lines = [
        "TRADE BRAIN OFFICIAL-FIRST NEWS EVIDENCE (deterministic, point-in-time):",
        "Priority: NSE/BSE official disclosure > SEBI official > archived major media > Yahoo/Alpha Vantage discovery.",
        "Do not label a media-only claim HIGH confidence unless an official source confirms it.",
    ]
    for label, key in (
        ("OFFICIAL COMPANY/EXCHANGE", "official_company_events"),
        ("OFFICIAL SEBI", "official_sebi_context"),
        ("MEDIA CONTEXT", "media_context"),
    ):
        items = pack.get(key) or []
        lines.append(f"[{label}] {len(items)} item(s)")
        for item in items:
            source = _clip(item.get("source"), 80)
            date = _clip(item.get("date"), 80)
            title = _clip(item.get("title"), 180)
            detail = _clip(item.get("detail"), 180)
            lines.append(f"- {date} | {source} | {title}" + (f" | {detail}" if detail else ""))
    if pack.get("refresh_notes"):
        lines.append("Refresh notes: " + "; ".join(pack["refresh_notes"]))
    return "\n".join(lines)
