"""Trade Brain analysis-date normalization helpers."""

from __future__ import annotations

from datetime import date, datetime


def normalize_trade_date(value: object) -> str:
    """Return YYYY-MM-DD from a date or ISO datetime string.

    The frontend/browser may serialize a date picker as an offset-aware midnight such as
    ``2026-08-26T00:00:00+05:30``. Downstream legacy data tools expect a plain market date.
    Normalize once at the API boundary so both shared research and horizon decisions see
    the same canonical India trading date.
    """
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()

    text = str(value or "").strip()
    if not text:
        raise ValueError("trade_date is required")

    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        pass

    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("trade_date must be YYYY-MM-DD or an ISO datetime") from exc
    return parsed.date().isoformat()
