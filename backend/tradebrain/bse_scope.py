"""Canonical BSE Ltd product scope for Trade Brain.

The original ITA remains available on the repository's ``main`` branch. The Trade Brain
branch is deliberately single-instrument: BSE Ltd listed on NSE as ``NSE:BSE``.
Broader instruments may be consumed as contextual evidence, but they may never become a
trade target through this module.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BSEProductScope:
    company_name: str = "BSE Ltd"
    ticker: str = "BSE"
    exchange: str = "NSE"
    kite_symbol: str = "NSE:BSE"
    isin: str = "INE118H01025"
    market_timezone: str = "Asia/Kolkata"
    tradable_instruments: tuple[str, ...] = ("NSE:BSE",)
    active_modes: tuple[str, ...] = ("INTRADAY", "SWING")


BSE_SCOPE = BSEProductScope()

# Inputs accepted only as user/interface aliases for the same canonical security.
_BSE_ALIASES = {
    "BSE",
    "NSE:BSE",
    "BSE.NS",
    "BSE LTD",
    "BSE LIMITED",
}


def is_bse_trade_target(value: str | None) -> bool:
    """Return True only when ``value`` denotes the canonical BSE Ltd trade target."""
    if value is None:
        return False
    normalized = " ".join(str(value).strip().upper().split())
    return normalized in _BSE_ALIASES


def require_bse_trade_target(value: str | None) -> str:
    """Validate a requested trade target and return canonical ticker ``BSE``.

    Context instruments such as NIFTY/BANKNIFTY are deliberately not accepted here.
    They belong to the evidence/context plane, never the tradable-target plane.
    """
    if not is_bse_trade_target(value):
        supplied = str(value or "").strip() or "(empty)"
        raise ValueError(
            f"Trade Brain is BSE Ltd-only on this branch. Requested target {supplied!r} "
            f"is not allowed; canonical target is {BSE_SCOPE.kite_symbol}."
        )
    return BSE_SCOPE.ticker


def public_scope() -> dict[str, object]:
    """Return non-secret product-scope metadata suitable for health/UI endpoints."""
    return {
        "product": "TRADE_BRAIN_BSE",
        "company_name": BSE_SCOPE.company_name,
        "ticker": BSE_SCOPE.ticker,
        "exchange": BSE_SCOPE.exchange,
        "kite_symbol": BSE_SCOPE.kite_symbol,
        "isin": BSE_SCOPE.isin,
        "market_timezone": BSE_SCOPE.market_timezone,
        "tradable_instruments": list(BSE_SCOPE.tradable_instruments),
        "active_modes": list(BSE_SCOPE.active_modes),
        "broader_market_role": "CONTEXT_ONLY",
        "advisory_only": True,
        "order_execution_allowed": False,
    }
