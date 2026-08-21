"""Compatibility annotations for heuristic outputs from the upstream application.

We preserve the original response fields so the existing UI keeps working, while
making it explicit to new consumers that a heuristic score is not a learned or
broker-authorized probability.
"""

from __future__ import annotations


def annotate_recommendation_payload(value):
    """Recursively label legacy `success_probability` values as heuristic evidence."""

    if isinstance(value, list):
        return [annotate_recommendation_payload(item) for item in value]
    if not isinstance(value, dict):
        return value

    result = {k: annotate_recommendation_payload(v) for k, v in value.items()}
    if "success_probability" in result:
        result.setdefault("heuristic_confidence_pct", result.get("success_probability"))
        result["probability_status"] = "HEURISTIC_NOT_LEARNED"
        result["probability_note"] = (
            "Legacy score-derived estimate. Treat as soft ranking evidence until validated on plan-specific, out-of-sample outcomes."
        )
        result["trade_authorization"] = False
    return result


def annotate_daily_verdict(result: dict) -> dict:
    """Mark the upstream daily verdict as context, not permission to trade."""

    output = dict(result)
    output["decision_scope"] = "SOFT_MARKET_CONTEXT"
    output["trade_authorization"] = False
    output["requires_tradebrain_gate"] = True
    output["tradebrain_note"] = (
        "GREEN/YELLOW/RED summarizes market context only. A structured trade still needs TP/SL geometry and the deterministic Trade Brain hard-rule gate."
    )
    return output
