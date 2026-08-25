"""Live Phase-10 safety wrapper around the deterministic advisory pipeline.

Only this wrapper should be used by API paths that may return an advisory PASS. It makes
market halt, broker-reported price range, and freak-tick/data-confirmation state outrank
technical/LLM setup. Unknown critical price-range state fails closed.
"""

from __future__ import annotations

from typing import Any

from backend.tradebrain.advisory_pipeline import evaluate_final_advisory
from backend.tradebrain.market_guards import combined_market_guard

METHOD_VERSION = "BSE_LIVE_GUARDED_ADVISORY_V1"


def _blocked(
    *,
    ticker: str,
    exchange: str,
    status: str,
    reason: str,
    market_guard: dict[str, Any],
) -> dict[str, Any]:
    return {
        "tradebrain_version": "0.13.0",
        "live_guard_version": METHOD_VERSION,
        "ticker": ticker.strip().upper(),
        "exchange": exchange.strip().upper(),
        "final_status": status,
        "reason": reason,
        "market_guard": market_guard,
        "gate": None,
        "costs": {"status": "NOT_COMPUTED_MARKET_GUARD_BLOCK"},
        "advisory_only": True,
        "trade_authorization": False,
        "order_execution_allowed": False,
        "order_endpoint_present": False,
    }


def evaluate_live_guarded_advisory(
    *,
    ticker: str,
    exchange: str,
    final_trade_decision: str,
    last_price: float | None,
    lower_limit: float | None,
    upper_limit: float | None,
    previous_accepted_price: float | None = None,
    best_bid: float | None = None,
    best_ask: float | None = None,
    atr_reference: float | None = None,
    halt_confirmed: bool = False,
    index_move_pct: float | None = None,
    official_halt_state: str | None = None,
    **advisory_kwargs: Any,
) -> dict[str, Any]:
    """Apply live market/data guards before deterministic advisory evaluation."""
    if last_price is None or last_price <= 0:
        guard = {
            "method_version": "BSE_MARKET_GUARDS_V1",
            "state": "LIVE_PRICE_UNVERIFIED",
            "hard_block_new_entries": True,
            "trade_authorization": False,
            "order_execution_allowed": False,
        }
        return _blocked(
            ticker=ticker,
            exchange=exchange,
            status="BLOCK_LIVE_PRICE_UNVERIFIED",
            reason="A positive accepted live BSE price is required before a live advisory can pass.",
            market_guard=guard,
        )

    guard = combined_market_guard(
        last_price=float(last_price),
        lower_limit=lower_limit,
        upper_limit=upper_limit,
        previous_accepted_price=previous_accepted_price,
        best_bid=best_bid,
        best_ask=best_ask,
        atr_reference=atr_reference,
        halt_confirmed=halt_confirmed,
        index_move_pct=index_move_pct,
        official_halt_state=official_halt_state,
    )

    range_state = ((guard.get("freak_tick") or {}).get("state") or "").upper()
    # The nested price-range state is not exposed directly by V1 freak_tick_guard, so
    # explicit missing range inputs are checked here. Do not infer a fixed circuit %.
    if lower_limit is None or upper_limit is None or lower_limit <= 0 or upper_limit <= lower_limit:
        return _blocked(
            ticker=ticker,
            exchange=exchange,
            status="BLOCK_PRICE_RANGE_UNVERIFIED",
            reason="Broker/exchange operating price range is unavailable; Trade Brain will not invent a fixed circuit percentage.",
            market_guard=guard,
        )

    halt_state = ((guard.get("market_halt") or {}).get("state") or "").upper()
    if halt_state == "MARKET_HALT_CONFIRMED":
        return _blocked(
            ticker=ticker,
            exchange=exchange,
            status="BLOCK_MARKET_HALT_CONFIRMED",
            reason="A confirmed market halt outranks all setup/LLM evidence.",
            market_guard=guard,
        )
    if halt_state == "POTENTIAL_MARKET_WIDE_CIRCUIT":
        return _blocked(
            ticker=ticker,
            exchange=exchange,
            status="BLOCK_HALT_CONFIRMATION_REQUIRED",
            reason="Index movement is in market-wide circuit territory and requires official confirmation before new advice.",
            market_guard=guard,
        )
    if guard.get("hard_block_new_entries"):
        return _blocked(
            ticker=ticker,
            exchange=exchange,
            status="BLOCK_MARKET_GUARD",
            reason="A hard market/data-integrity guard blocks new advisory entries.",
            market_guard=guard,
        )
    if guard.get("data_confirmation_required"):
        return _blocked(
            ticker=ticker,
            exchange=exchange,
            status="BLOCK_DATA_CONFIRMATION_REQUIRED",
            reason="A suspicious/freak tick must be confirmed before a new advisory can pass.",
            market_guard=guard,
        )

    result = evaluate_final_advisory(
        ticker=ticker,
        exchange=exchange,
        final_trade_decision=final_trade_decision,
        **advisory_kwargs,
    )
    result["live_guard_version"] = METHOD_VERSION
    result["market_guard"] = guard
    result["market_guard_checked_before_advisory"] = True
    result["market_guard_priority"] = "HALT > PRICE_RANGE > DATA_QUALITY > POLICY > LLM"
    return result
