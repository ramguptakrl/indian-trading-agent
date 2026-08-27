"""Trade Brain active product-mode and funding boundary.

Active product doctrine:
- INTRADAY: same-session cash-equity LONG/SHORT; no overnight short.
- SWING: LONG-only Zerodha MTF-funded multi-day equity.

Older DAY / SWING_POSITION mode labels and CNC_OWN_CASH funding labels remain readable
for historical audit/replay compatibility. Historical readability is not live permission.
"""

from __future__ import annotations

from typing import Literal

ActiveTradeMode = Literal["INTRADAY", "SWING"]
CompatibleTradeMode = Literal["INTRADAY", "SWING", "DAY", "SWING_POSITION"]
SwingFundingMode = Literal["CNC_OWN_CASH", "MTF"]

ACTIVE_TRADE_MODES = ("INTRADAY", "SWING")
ACTIVE_SWING_FUNDING_MODES = ("MTF",)
LEGACY_SWING_FUNDING_MODES = ("CNC_OWN_CASH",)
# Preserve the historical public ordering for compatibility while separately exposing
# ACTIVE_SWING_FUNDING_MODES as the permission-bearing list.
READABLE_SWING_FUNDING_MODES = LEGACY_SWING_FUNDING_MODES + ACTIVE_SWING_FUNDING_MODES

LEGACY_TO_ACTIVE = {
    "DAY": "INTRADAY",
    "SWING_POSITION": "SWING",
    "INTRADAY": "INTRADAY",
    "SWING": "SWING",
}
ACTIVE_TO_LEGACY = {
    "INTRADAY": "DAY",
    "SWING": "SWING_POSITION",
}


def to_active_mode(value: str) -> ActiveTradeMode:
    key = str(value).strip().upper()
    try:
        return LEGACY_TO_ACTIVE[key]  # type: ignore[return-value]
    except KeyError as exc:
        raise ValueError("Trade mode must be INTRADAY or SWING") from exc


def to_legacy_mode(value: str) -> Literal["DAY", "SWING_POSITION"]:
    active = to_active_mode(value)
    return ACTIVE_TO_LEGACY[active]  # type: ignore[return-value]


def to_swing_funding(value: str) -> SwingFundingMode:
    """Parse current and historical funding labels without granting live permission."""
    key = str(value).strip().upper()
    if key not in READABLE_SWING_FUNDING_MODES:
        raise ValueError("Swing funding must be MTF; CNC_OWN_CASH is historical compatibility only")
    return key  # type: ignore[return-value]


def is_active_swing_funding(value: str | None) -> bool:
    return bool(value) and str(value).strip().upper() == "MTF"


def is_intraday(value: str) -> bool:
    return to_active_mode(value) == "INTRADAY"


def is_swing(value: str) -> bool:
    return to_active_mode(value) == "SWING"


def product_boundary() -> dict:
    return {
        "trader_profile": "RESIDENT_INDIAN",
        "active_trade_modes": list(ACTIVE_TRADE_MODES),
        "swing_long_only": True,
        "swing_funding_modes": list(READABLE_SWING_FUNDING_MODES),
        "swing_funding_modes_semantics": "READABLE_COMPATIBILITY_LABELS",
        "active_swing_funding_modes": list(ACTIVE_SWING_FUNDING_MODES),
        "swing_funding_required": "MTF",
        "legacy_readable_swing_funding_labels": list(LEGACY_SWING_FUNDING_MODES),
        "cnc_own_cash_active_swing_allowed": False,
        "mtf_enabled_for_research_and_cost_modeling": True,
        "funded_amount_modeled": True,
        "mtf_eligibility_must_be_verified": True,
        "mtf_broker_order_execution_enabled": False,
        "derivatives_enabled": False,
        "intraday_short_overnight_allowed": False,
        "legacy_db_aliases": {"DAY": "INTRADAY", "SWING_POSITION": "SWING"},
    }
