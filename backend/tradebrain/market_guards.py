"""Market/data integrity guards for BSE Ltd.

Hard facts (known exchange/broker limits, malformed prices, confirmed halts) outrank model
opinion. Heuristic warnings are explicitly labelled and may trigger review/fresh-data
requirements, never automatic broker execution.
"""

from __future__ import annotations

from typing import Any

METHOD_VERSION = "BSE_MARKET_GUARDS_V1"


def extract_kite_price_range(full_quote: dict[str, Any] | None) -> dict[str, Any]:
    """Extract broker-reported operating/circuit limits when present.

    Kite full quote payloads may expose lower_circuit_limit and upper_circuit_limit. We
    do not invent a fixed percentage when those values are absent because derivatives-
    eligible cash securities can operate under dynamic exchange ranges.
    """
    quote = full_quote or {}
    try:
        lower = float(quote.get("lower_circuit_limit"))
        upper = float(quote.get("upper_circuit_limit"))
    except (TypeError, ValueError):
        lower = upper = 0.0
    if lower > 0 and upper > lower:
        return {
            "status": "KNOWN",
            "lower_limit": lower,
            "upper_limit": upper,
            "source": "KITE_FULL_QUOTE_REPORTED_RANGE",
            "hardcoded_percentage_used": False,
        }
    return {
        "status": "UNKNOWN",
        "lower_limit": None,
        "upper_limit": None,
        "source": "UNAVAILABLE_IN_CURRENT_QUOTE",
        "hardcoded_percentage_used": False,
    }


def price_range_guard(
    last_price: float,
    *,
    lower_limit: float | None,
    upper_limit: float | None,
    near_fraction: float = 0.0025,
) -> dict[str, Any]:
    if last_price <= 0:
        return {"state": "INVALID_PRICE", "hard_block": True, "reason": "Non-positive market price"}
    if lower_limit is None or upper_limit is None or lower_limit <= 0 or upper_limit <= lower_limit:
        return {
            "state": "RANGE_UNKNOWN",
            "hard_block": False,
            "reason": "Operating/circuit range unavailable; do not infer a fixed percentage",
        }
    if last_price < lower_limit or last_price > upper_limit:
        return {
            "state": "OUTSIDE_REPORTED_RANGE",
            "hard_block": True,
            "reason": "Observed price is outside the broker-reported operating/circuit range",
        }
    lower_distance = (last_price - lower_limit) / last_price
    upper_distance = (upper_limit - last_price) / last_price
    if lower_distance <= near_fraction:
        state = "NEAR_LOWER_RANGE"
    elif upper_distance <= near_fraction:
        state = "NEAR_UPPER_RANGE"
    else:
        state = "INSIDE_RANGE"
    return {
        "state": state,
        "hard_block": False,
        "lower_limit": lower_limit,
        "upper_limit": upper_limit,
        "distance_to_lower_pct": round(lower_distance * 100.0, 4),
        "distance_to_upper_pct": round(upper_distance * 100.0, 4),
        "near_range_threshold_pct": round(near_fraction * 100.0, 4),
        "near_range_threshold_is_research_heuristic": True,
    }


def freak_tick_guard(
    *,
    last_price: float,
    previous_accepted_price: float | None = None,
    best_bid: float | None = None,
    best_ask: float | None = None,
    atr_reference: float | None = None,
    lower_limit: float | None = None,
    upper_limit: float | None = None,
) -> dict[str, Any]:
    """Flag suspicious prints; never auto-promote one isolated tick into a trade signal."""
    range_state = price_range_guard(
        last_price,
        lower_limit=lower_limit,
        upper_limit=upper_limit,
    )
    reasons: list[str] = []
    hard_block = bool(range_state.get("hard_block"))
    if hard_block:
        reasons.append(str(range_state.get("reason")))

    jump_abs = None
    jump_pct = None
    if previous_accepted_price is not None and previous_accepted_price > 0:
        jump_abs = abs(last_price - previous_accepted_price)
        jump_pct = jump_abs / previous_accepted_price * 100.0
        if atr_reference is not None and atr_reference > 0 and jump_abs >= 2.5 * atr_reference:
            reasons.append("Single-tick move is >=2.5x the supplied ATR reference")
        elif jump_pct >= 3.0:
            reasons.append("Single-tick move is >=3%; confirmation required")

    depth_dislocation_pct = None
    if best_bid is not None and best_ask is not None and best_bid > 0 and best_ask >= best_bid:
        if last_price < best_bid:
            depth_dislocation_pct = (best_bid - last_price) / best_bid * 100.0
        elif last_price > best_ask:
            depth_dislocation_pct = (last_price - best_ask) / best_ask * 100.0
        else:
            depth_dislocation_pct = 0.0
        if depth_dislocation_pct >= 1.0:
            reasons.append("Last price is materially dislocated from current best bid/ask")

    suspicious = bool(reasons)
    return {
        "state": "FREAK_TICK_SUSPECT" if suspicious else "NORMAL_TICK",
        "hard_block": hard_block,
        "requires_confirmation": suspicious,
        "reasons": reasons,
        "jump_pct": round(jump_pct, 4) if jump_pct is not None else None,
        "depth_dislocation_pct": round(depth_dislocation_pct, 4) if depth_dislocation_pct is not None else None,
        "heuristic_thresholds": {
            "atr_multiple": 2.5,
            "fallback_single_tick_jump_pct": 3.0,
            "depth_dislocation_pct": 1.0,
        },
        "heuristics_require_validation": True,
        "one_suspect_tick_can_change_live_policy": False,
        "order_execution_allowed": False,
    }


def market_halt_guard(
    *,
    halt_confirmed: bool = False,
    index_move_pct: float | None = None,
    official_state: str | None = None,
) -> dict[str, Any]:
    """Classify confirmed vs potential market-wide halt conditions.

    Threshold proximity alone is not treated as proof that trading is halted. A confirmed
    official/exchange state creates the hard block.
    """
    if halt_confirmed:
        return {
            "state": "MARKET_HALT_CONFIRMED",
            "hard_block_new_entries": True,
            "official_state": official_state,
            "reason": "Confirmed market halt; preserve state and reassess after reopening",
            "order_execution_allowed": False,
        }
    potential = abs(float(index_move_pct)) >= 10.0 if index_move_pct is not None else False
    return {
        "state": "POTENTIAL_MARKET_WIDE_CIRCUIT" if potential else "NO_CONFIRMED_HALT",
        "hard_block_new_entries": False,
        "index_move_pct": index_move_pct,
        "official_state": official_state,
        "requires_official_confirmation": potential,
        "order_execution_allowed": False,
    }


def combined_market_guard(
    *,
    last_price: float,
    lower_limit: float | None = None,
    upper_limit: float | None = None,
    previous_accepted_price: float | None = None,
    best_bid: float | None = None,
    best_ask: float | None = None,
    atr_reference: float | None = None,
    halt_confirmed: bool = False,
    index_move_pct: float | None = None,
    official_halt_state: str | None = None,
) -> dict[str, Any]:
    freak = freak_tick_guard(
        last_price=last_price,
        previous_accepted_price=previous_accepted_price,
        best_bid=best_bid,
        best_ask=best_ask,
        atr_reference=atr_reference,
        lower_limit=lower_limit,
        upper_limit=upper_limit,
    )
    halt = market_halt_guard(
        halt_confirmed=halt_confirmed,
        index_move_pct=index_move_pct,
        official_state=official_halt_state,
    )
    hard_block = bool(freak.get("hard_block")) or bool(halt.get("hard_block_new_entries"))
    return {
        "method_version": METHOD_VERSION,
        "freak_tick": freak,
        "market_halt": halt,
        "hard_block_new_entries": hard_block,
        "data_confirmation_required": bool(freak.get("requires_confirmation")),
        "trade_authorization": False,
        "order_execution_allowed": False,
    }
