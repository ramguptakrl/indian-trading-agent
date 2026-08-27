"""Independent Gemini verification of material Groq BSE research findings.

The verifier checks a concise claim/evidence packet and returns a structured challenge.
It is not asked for hidden reasoning, cannot alter deterministic hard policy, and never
authorizes or executes a broker order. Capacity/quota failures degrade to an explicit
UNAVAILABLE state rather than blocking the primary research result.
"""

from __future__ import annotations

import json
import re
from typing import Any

from backend.tradebrain.llm_failover import get_material_verifier_config, is_retryable_llm_capacity_error

MATERIAL_RESEARCH_LABELS = {"LONG_CANDIDATE", "SHORT_CANDIDATE", "EXIT_CANDIDATE"}
MAX_EVIDENCE_CHARS_PER_SECTION = 2600
METHOD_VERSION = "GROQ_PRIMARY_GEMINI_VERIFIER_V1"


def _clip(value: Any, limit: int = MAX_EVIDENCE_CHARS_PER_SECTION) -> str:
    text = str(value or "").strip()
    return text if len(text) <= limit else text[:limit] + "…"


def _extract_json(text: str) -> dict[str, Any] | None:
    value = text.strip()
    if value.startswith("```"):
        value = re.sub(r"^```(?:json)?\s*", "", value, flags=re.IGNORECASE)
        value = re.sub(r"\s*```$", "", value)
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        start = value.find("{")
        end = value.rfind("}")
        if start >= 0 and end > start:
            try:
                parsed = json.loads(value[start : end + 1])
                return parsed if isinstance(parsed, dict) else None
            except json.JSONDecodeError:
                return None
    return None


def _normalize_verdict(value: Any) -> str:
    verdict = str(value or "").strip().upper()
    return verdict if verdict in {"SUPPORTS", "CONFLICTS", "UNCERTAIN"} else "UNCERTAIN"


def _safe_checks(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [_clip(item, 240) for item in value[:6] if str(item or "").strip()]


def verify_material_finding(
    *,
    research_label: str,
    final_trade_decision: str,
    market_report: str | None = None,
    news_report: str | None = None,
    fundamentals_report: str | None = None,
    config: dict[str, Any],
) -> dict[str, Any]:
    """Run one concise Gemini challenge only for material Groq findings."""
    label = str(research_label or "").upper()
    verifier = get_material_verifier_config(config)
    if label not in MATERIAL_RESEARCH_LABELS:
        return {
            "status": "SKIPPED_NOT_MATERIAL",
            "method_version": METHOD_VERSION,
            "research_label": label,
            "verdict": None,
            "trade_authorization": False,
            "order_execution_allowed": False,
        }
    if verifier is None:
        return {
            "status": "UNAVAILABLE_NOT_CONFIGURED",
            "method_version": METHOD_VERSION,
            "research_label": label,
            "verdict": None,
            "trade_authorization": False,
            "order_execution_allowed": False,
        }

    prompt = f"""You are an independent verification layer for BSE Ltd (NSE:BSE) research.
Do NOT produce chain-of-thought. Do NOT invent missing prices, news, or facts. Do NOT
place/authorize a trade. Check whether the PRIMARY FINDING is actually supported by the
SUPPLIED EVIDENCE and flag contradictions or missing evidence.

Return ONLY compact JSON with this exact shape:
{{
  "verdict": "SUPPORTS|CONFLICTS|UNCERTAIN",
  "checks": ["short factual check", "..."],
  "conflicts": ["short contradiction if any"],
  "missing_evidence": ["short missing item if any"]
}}

PRIMARY RESEARCH LABEL: {label}
PRIMARY FINDING:
{_clip(final_trade_decision, 4000)}

PRICE/STRUCTURE REPORT:
{_clip(market_report)}

BSE/INDIA NEWS CONTEXT:
{_clip(news_report)}

FUNDAMENTALS/EVENT CONTEXT:
{_clip(fundamentals_report)}
"""

    try:
        from tradingagents.llm_clients import create_llm_client

        llm = create_llm_client(
            provider=str(verifier["provider"]),
            model=str(verifier["model"]),
            max_retries=0,
            timeout=45,
        ).get_llm()
        response = llm.invoke(prompt)
        content = str(getattr(response, "content", response) or "")
        parsed = _extract_json(content)
        if parsed is None:
            return {
                "status": "UNPARSEABLE_VERIFIER_RESPONSE",
                "method_version": METHOD_VERSION,
                "provider": verifier["provider"],
                "model": verifier["model"],
                "research_label": label,
                "verdict": "UNCERTAIN",
                "checks": [],
                "conflicts": [],
                "missing_evidence": ["Verifier response was not valid structured JSON"],
                "trade_authorization": False,
                "order_execution_allowed": False,
            }
        return {
            "status": "SUCCESS",
            "method_version": METHOD_VERSION,
            "provider": verifier["provider"],
            "model": verifier["model"],
            "research_label": label,
            "verdict": _normalize_verdict(parsed.get("verdict")),
            "checks": _safe_checks(parsed.get("checks")),
            "conflicts": _safe_checks(parsed.get("conflicts")),
            "missing_evidence": _safe_checks(parsed.get("missing_evidence")),
            "verifier_can_override_hard_policy": False,
            "trade_authorization": False,
            "order_execution_allowed": False,
        }
    except Exception as exc:
        if is_retryable_llm_capacity_error(exc):
            state = "UNAVAILABLE_QUOTA_OR_RATE_LIMIT"
            message = "Gemini verification unavailable because its current quota/rate limit was reached."
        else:
            state = "UNAVAILABLE_ERROR"
            message = f"Gemini verification unavailable ({type(exc).__name__})."
        return {
            "status": state,
            "method_version": METHOD_VERSION,
            "provider": verifier["provider"],
            "model": verifier["model"],
            "research_label": label,
            "verdict": None,
            "message": message,
            "trade_authorization": False,
            "order_execution_allowed": False,
        }
