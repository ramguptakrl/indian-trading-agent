"""Trade Brain active product-mode boundary.

Phase 6 simplifies the product to two resident-Indian equity modes only:
INTRADAY and SWING. Older DAY / SWING_POSITION values remain readable aliases so
Phases 0-5 historical rows do not need destructive migration.
"""

from __future__ import annotations

from typing import Literal

ActiveTradeMode = Literal["INTRADAY", "SWING"]
CompatibleTradeMode = Literal["INTRADAY", "SWING", "DAY", "SWING_POSITION"]

ACTIVE_TRADE_MODES = ("INTRADAY", "SWING")
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


def is_intraday(value: str) -> bool:
    return to_active_mode(value) == "INTRADAY"


def is_swing(value: str) -> bool:
    return to_active_mode(value) == "SWING"


def product_boundary() -> dict:
    return {
        "trader_profile": "RESIDENT_INDIAN",
        "active_trade_modes": list(ACTIVE_TRADE_MODES),
        "mtf_enabled": False,
        "funded_amount_modeled": False,
        "derivatives_enabled": False,
        "legacy_db_aliases": {"DAY": "INTRADAY", "SWING_POSITION": "SWING"},
    }
