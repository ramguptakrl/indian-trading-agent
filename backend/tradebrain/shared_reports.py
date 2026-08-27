"""Lightweight helpers for assembling one immutable shared BSE research pack.

These helpers deliberately have no LangGraph/LangChain imports so report-retention rules can
be tested independently of the heavy agent runtime.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

REPORT_BY_ANALYST = {
    "market": "market_report",
    "social": "sentiment_report",
    "news": "news_report",
    "fundamentals": "fundamentals_report",
}
SHARED_REPORT_FIELDS = tuple(REPORT_BY_ANALYST.values())


def merge_shared_report_snapshot(
    observed: dict[str, str],
    state: Mapping[str, Any] | None,
    *,
    on_report: Callable[[str, str], None] | None = None,
) -> dict[str, str]:
    """Retain every non-empty analyst report observed anywhere in a graph stream.

    LangGraph stream chunks must not be assumed to repeat every field from earlier chunks.
    A later message-clear/tool chunk therefore cannot erase a report already produced by an
    analyst. New non-empty content for the same report field replaces the older value.
    """
    if not state:
        return observed

    for field in SHARED_REPORT_FIELDS:
        value = state.get(field)
        if value is None:
            continue
        text = str(value).strip()
        if not text or text == observed.get(field):
            continue
        observed[field] = text
        if on_report is not None:
            on_report(field, text)
    return observed


def missing_required_reports(
    selected_analysts: Sequence[str],
    reports: Mapping[str, str],
) -> list[str]:
    """Return required report fields that genuinely have no retained non-empty content."""
    missing: list[str] = []
    for analyst in selected_analysts:
        field = REPORT_BY_ANALYST.get(str(analyst).strip().lower())
        if field and not str(reports.get(field) or "").strip():
            missing.append(field)
    return missing


def analyst_for_report(field: str) -> str | None:
    """Map a report field back to the analyst that owns it."""
    for analyst, report_field in REPORT_BY_ANALYST.items():
        if report_field == field:
            return analyst
    return None
