"""Shared Trade Brain horizon rules with no agent/runtime dependencies.

This module is the single source of truth for model-facing INTRADAY/SWING
constraints. It is intentionally lightweight so policy contract tests do not
need to import the full LangChain agent package.
"""


def horizon_instruction(requested_trade_mode: str | None) -> str:
    mode = str(requested_trade_mode or "").strip().upper()
    if mode == "INTRADAY":
        return """**Dedicated horizon for this run: INTRADAY**
Evaluate INTRADAY independently. For any new candidate, `Trade Mode` MUST be INTRADAY.
Do not switch to SWING because the intraday setup is weak; use HOLD / WAIT or NO TRADE instead.
INTRADAY may be LONG or SHORT only with its own valid same-session setup.
No fresh INTRADAY entry is allowed from 15:10 IST and exposure must be flat before 15:15 IST."""
    if mode == "SWING":
        return """**Dedicated horizon for this run: SWING**
Evaluate SWING independently. For any new candidate, `Trade Mode` MUST be SWING and `Direction` MUST be LONG.
Do not switch to INTRADAY or SHORT because the swing setup is weak; use HOLD / WAIT or NO TRADE instead.
Active SWING funding is Zerodha MTF only. Never invent current MTF eligibility, funded amount, leverage, margin percentage, or holding/interest days.
If required MTF facts are unverified or missing, use HOLD / WAIT or NO TRADE rather than an own-cash/CNC substitute."""
    return """**Horizon selection for this legacy run**
INTRADAY and SWING are the only active horizons. Choose at most one new-candidate horizon from supplied evidence, or use HOLD / WAIT / NO TRADE. The BSE dual-horizon API runs them independently when both are required."""
