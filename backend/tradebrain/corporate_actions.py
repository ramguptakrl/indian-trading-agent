"""Fail-closed normalization for BSE Ltd split/dividend corporate actions.

Corporate announcements are retained as the source of truth. This module derives only
explicit facts found in those announcements and never invents an ex-date, record date,
split ratio, or dividend amount. The normalized context is intended to prevent mechanical
corporate-action price moves from being treated as ordinary gaps or freak ticks.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timezone
from typing import Any, Iterable

METHOD_VERSION = "BSE_CORPORATE_ACTION_CONTEXT_V1"

_DATE_TOKEN = (
    r"(?:\d{1,2}[\-/]\d{1,2}[\-/]\d{2,4}|"
    r"\d{1,2}[\-/](?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*[\-/]\d{2,4}|"
    r"\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\s+\d{2,4}|"
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+\d{2,4})"
)
_DATE_FORMATS = (
    "%d-%m-%Y", "%d/%m/%Y", "%d-%m-%y", "%d/%m/%y",
    "%d-%b-%Y", "%d/%b/%Y", "%d-%B-%Y", "%d/%B/%Y",
    "%d %b %Y", "%d %B %Y", "%b %d %Y", "%b %d, %Y",
    "%B %d %Y", "%B %d, %Y",
)


def _text(event: dict[str, Any]) -> str:
    values = [event.get("subject"), event.get("details"), event.get("source_category"), event.get("subcategory")]
    raw = event.get("raw_payload")
    if raw is None and isinstance(event.get("raw_payload_json"), str):
        values.append(event.get("raw_payload_json"))
    elif raw is not None:
        values.append(str(raw))
    return " ".join(str(value or "") for value in values if value).strip()


def _parse_date_token(raw: str | None) -> str | None:
    if not raw:
        return None
    value = re.sub(r"\s+", " ", raw.replace("Sept", "Sep")).strip().rstrip(".,;")
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _as_utc(value: str | datetime | None) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value) if isinstance(value, str) else value
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _labelled_date(text: str, labels: tuple[str, ...]) -> str | None:
    for label in labels:
        match = re.search(
            rf"\b{label}\b\s*(?:is|shall\s+be|has\s+been\s+fixed\s+as|fixed\s+as|on|:|-)?\s*({_DATE_TOKEN})",
            text,
            flags=re.IGNORECASE,
        )
        if match:
            parsed = _parse_date_token(match.group(1))
            if parsed:
                return parsed
    return None


def _action_type(event: dict[str, Any], text: str) -> str | None:
    category = str(event.get("category") or "").upper()
    lowered = text.lower()
    if category == "DIVIDEND" or "dividend" in lowered:
        return "DIVIDEND"
    if category == "CORPORATE_ACTION" and any(token in lowered for token in ("stock split", "sub-division", "sub division")):
        return "STOCK_SPLIT"
    if any(token in lowered for token in ("stock split", "sub-division", "sub division")):
        return "STOCK_SPLIT"
    return None


def _dividend_amount(text: str) -> tuple[float | None, float | None]:
    absolute_patterns = (
        r"(?:₹|rs\.?|inr)\s*([0-9]+(?:\.[0-9]+)?)\s*(?:per\s+)?(?:equity\s+)?share",
        r"dividend\s+(?:of\s+)?(?:₹|rs\.?|inr)\s*([0-9]+(?:\.[0-9]+)?)",
    )
    for pattern in absolute_patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return float(match.group(1)), None
    pct = re.search(r"(?:dividend\s+(?:of\s+)?)?([0-9]+(?:\.[0-9]+)?)\s*%\s*(?:dividend)?", text, flags=re.IGNORECASE)
    return (None, float(pct.group(1))) if pct else (None, None)


def _split_terms(text: str) -> dict[str, Any]:
    face = re.search(
        r"face\s+value\s+(?:of\s+)?(?:₹|rs\.?|inr)?\s*([0-9]+(?:\.[0-9]+)?)"
        r".{0,160}?(?:into|to)\s+(?:equity\s+shares?.{0,80}?)?face\s+value\s+(?:of\s+)?(?:₹|rs\.?|inr)?\s*([0-9]+(?:\.[0-9]+)?)",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if face:
        old_face = float(face.group(1))
        new_face = float(face.group(2))
        if old_face > 0 and new_face > 0 and old_face > new_face:
            multiplier = old_face / new_face
            return {
                "old_face_value": old_face,
                "new_face_value": new_face,
                "share_multiplier": multiplier,
                "raw_price_adjustment_factor": new_face / old_face,
                "ratio_basis": "EXPLICIT_FACE_VALUE_CONVERSION",
            }

    into = re.search(
        r"(?:one|1)\s+(?:equity\s+)?share.{0,100}?(?:into|subdivided\s+into)\s+([0-9]+)\s+(?:equity\s+)?shares?",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if into:
        multiplier = int(into.group(1))
        if multiplier > 1:
            return {
                "old_face_value": None,
                "new_face_value": None,
                "share_multiplier": float(multiplier),
                "raw_price_adjustment_factor": 1.0 / float(multiplier),
                "ratio_basis": "EXPLICIT_ONE_SHARE_INTO_N",
            }

    return {
        "old_face_value": None,
        "new_face_value": None,
        "share_multiplier": None,
        "raw_price_adjustment_factor": None,
        "ratio_basis": "UNRESOLVED",
    }


def normalize_corporate_action(event: dict[str, Any]) -> dict[str, Any] | None:
    """Normalize an official event into explicit split/dividend facts when possible."""
    text = _text(event)
    action_type = _action_type(event, text)
    if action_type is None:
        return None

    ex_date = _labelled_date(text, (r"ex[ -]?date", r"ex[ -]?dividend\s+date", r"ex[ -]?split\s+date"))
    record_date = _labelled_date(text, (r"record\s+date",))
    payment_date = _labelled_date(text, (r"payment\s+date", r"dividend\s+payment\s+date"))
    known_at = event.get("fetched_at") or event.get("announced_at")

    result: dict[str, Any] = {
        "method_version": METHOD_VERSION,
        "event_id": event.get("event_id"),
        "action_type": action_type,
        "announced_at": event.get("announced_at"),
        "first_known_at": known_at,
        "ex_date": ex_date,
        "record_date": record_date,
        "payment_date": payment_date,
        "dates_are_explicit_only": True,
        "ex_date_inferred_from_record_date": False,
        "source_category": event.get("category"),
        "source_url": event.get("source_url"),
        "attachment_url": event.get("attachment_url"),
        "trade_authorization": False,
        "order_execution_allowed": False,
    }

    if action_type == "DIVIDEND":
        cash, pct = _dividend_amount(text)
        result.update({
            "cash_dividend_per_share": cash,
            "dividend_percent_stated": pct,
            "cash_amount_inferred_from_percent": False,
            "mechanical_gap_risk_on_ex_date": True,
            "raw_price_series_structural_break": False,
        })
    else:
        result.update(_split_terms(text))
        result.update({
            "mechanical_gap_risk_on_ex_date": True,
            "raw_price_series_structural_break": True,
        })
    return result


def corporate_action_context(
    events: Iterable[dict[str, Any]],
    *,
    session_date: str | date,
    known_by: str | datetime | None = None,
) -> dict[str, Any]:
    """Return point-in-time price-comparability context for one market date.

    Unknown/missing ex-dates never become guessed matches. For historical/replay use,
    `known_by` excludes announcements that were not yet observed by that cutoff.
    """
    day = date.fromisoformat(session_date) if isinstance(session_date, str) else session_date
    cutoff = _as_utc(known_by)
    normalized = [item for event in events if (item := normalize_corporate_action(event)) is not None]
    actions: list[dict[str, Any]] = []
    excluded_future_knowledge = 0
    excluded_unknown_knowledge_time = 0
    for item in normalized:
        if cutoff is None:
            actions.append(item)
            continue
        first_known = _as_utc(item.get("first_known_at"))
        if first_known is None:
            excluded_unknown_knowledge_time += 1
            continue
        if first_known <= cutoff:
            actions.append(item)
        else:
            excluded_future_knowledge += 1

    ex_actions = [item for item in actions if item.get("ex_date") == day.isoformat()]
    record_actions = [item for item in actions if item.get("record_date") == day.isoformat()]
    split = any(item["action_type"] == "STOCK_SPLIT" for item in ex_actions)
    dividend = any(item["action_type"] == "DIVIDEND" for item in ex_actions)
    return {
        "method_version": METHOD_VERSION,
        "session_date": day.isoformat(),
        "known_by": cutoff.isoformat() if cutoff else None,
        "actions": actions,
        "ex_date_actions": ex_actions,
        "record_date_actions": record_actions,
        "known_ex_date_event": bool(ex_actions),
        "stock_split_ex_date": split,
        "dividend_ex_date": dividend,
        "mechanical_gap_risk": bool(ex_actions),
        "raw_overnight_gap_comparable": not bool(ex_actions),
        "raw_price_series_structural_break": split,
        "requires_adjusted_or_event_aware_return_logic": bool(ex_actions),
        "future_knowledge_excluded": excluded_future_knowledge,
        "unknown_knowledge_time_excluded": excluded_unknown_knowledge_time,
        "unknown_ex_date_is_not_guessed": True,
        "trade_authorization": False,
        "order_execution_allowed": False,
    }


def corporate_action_context_from_store(
    *,
    session_date: str | date,
    known_by: str | datetime | None = None,
    db_path: str | None = None,
    limit: int = 500,
) -> dict[str, Any]:
    """Build BSE action context from the official event memory already in Trade Brain."""
    from backend.tradebrain.corporate_event_store import list_events

    events = list_events(limit=max(1, min(int(limit), 500)), db_path=db_path)
    return corporate_action_context(events, session_date=session_date, known_by=known_by)
