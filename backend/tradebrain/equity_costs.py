"""Phase 6 resident-Indian equity transaction-cost component.

The trader/accounting profile is RESIDENT_INDIAN. A Kite/Zerodha credential may be
configured later as MARKET_DATA_ONLY even if that credential belongs to an NRI
account; credential account type never changes the resident policy/cost profile here.

This module intentionally contains no MTF funding cost. Active SWING funding permission
is defined by the Trade Brain product/policy layer and is Zerodha MTF-only; `swing_mtf.py`
combines this base transaction-cost component with the separately versioned MTF layer.
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from backend.tradebrain.trade_modes import to_active_mode

COST_PROFILE_KEY = "ZERODHA_RESIDENT_INDIVIDUAL_EQUITY_2026_08"
COST_PROFILE_VERIFIED_AT = "2026-08-21"

# Current resident-individual equity schedule verified from Zerodha's public charges
# and support pages on 2026-08-21. Keep this versioned; do not silently mutate old
# simulations when a broker/exchange changes fees.
COST_PROFILE: dict[str, Any] = {
    "profile_key": COST_PROFILE_KEY,
    "trader_profile": "RESIDENT_INDIAN",
    "broker_reference": "ZERODHA_RESIDENT_INDIVIDUAL",
    "verified_at": COST_PROFILE_VERIFIED_AT,
    "delivery_brokerage_pct": 0.0,
    "intraday_brokerage_pct": 0.03,
    "intraday_brokerage_cap_per_executed_order": 20.0,
    "stt_intraday_sell_pct": 0.025,
    "stt_delivery_buy_pct": 0.1,
    "stt_delivery_sell_pct": 0.1,
    "transaction_charge_pct": {"NSE": 0.00307, "BSE": 0.00375},
    "sebi_per_crore": 10.0,
    "ipft_equity_per_crore": 0.01,
    "gst_pct": 18.0,
    "stamp_intraday_buy_pct": 0.003,
    "stamp_delivery_buy_pct": 0.015,
    "dp_base_resident_default": 13.0,
    "dp_gst_pct": 18.0,
    "mtf_enabled": False,
    "funding_interest_pct": 0.0,
    "source_urls": [
        "https://zerodha.com/charges",
        "https://support.zerodha.com/category/account-opening/resident-individual/ri-charges/articles/what-is-the-brokerage-at-zerodha-for-equity",
        "https://support.zerodha.com/category/account-opening/resident-individual/ri-charges/articles/how-is-the-securities-transaction-tax-stt-calculated",
        "https://support.zerodha.com/category/account-opening/resident-individual/ri-charges/articles/what-do-dp-charges-mean",
    ],
}


def _d(value: float | int | str) -> Decimal:
    return Decimal(str(value))


def _money(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _nearest_rupee(value: Decimal) -> Decimal:
    return value.quantize(Decimal("1"), rounding=ROUND_HALF_UP)


def _pct(turnover: Decimal, pct: float) -> Decimal:
    return turnover * _d(pct) / Decimal("100")


def data_credential_boundary() -> dict[str, Any]:
    """Declare that credential identity is not trader identity."""
    return {
        "trader_profile": "RESIDENT_INDIAN",
        "kite_credential_role": "MARKET_DATA_ONLY",
        "kite_credential_may_belong_to_nri_account": True,
        "credential_account_type_affects_policy": False,
        "credential_account_type_affects_cost_profile": False,
        "order_api_enabled": False,
        "allowed_data_uses": ["LIVE_QUOTES", "HISTORICAL_CANDLES", "BACKTEST_INPUT"],
        "prohibited_uses": ["ORDER_PLACEMENT", "BROKER_RULE_INFERENCE_FROM_CREDENTIAL_TYPE"],
    }


def _transaction_pct(exchange: str, override: float | None) -> tuple[float, list[str]]:
    ex = exchange.upper()
    if ex not in {"NSE", "BSE"}:
        raise ValueError("exchange must be NSE or BSE")
    warnings: list[str] = []
    if override is not None:
        if override < 0:
            raise ValueError("transaction_charge_pct_override must be >= 0")
        return float(override), warnings
    if ex == "BSE":
        warnings.append(
            "BSE transaction charge can vary for special scrip groups; default 0.00375% is the standard equity rate. Supply an override when the verified group rate differs."
        )
    return float(COST_PROFILE["transaction_charge_pct"][ex]), warnings


def _fill_prices(direction: str, entry: float, exit_price: float, slippage_bps: float) -> tuple[Decimal, Decimal]:
    if entry <= 0 or exit_price <= 0:
        raise ValueError("entry_price and exit_price must be positive")
    if slippage_bps < 0:
        raise ValueError("slippage_bps must be >= 0")
    direction = direction.upper()
    if direction not in {"LONG", "SHORT"}:
        raise ValueError("direction must be LONG or SHORT")
    slip = _d(slippage_bps) / Decimal("10000")
    e = _d(entry)
    x = _d(exit_price)
    if direction == "LONG":
        return e * (Decimal("1") + slip), x * (Decimal("1") - slip)
    return e * (Decimal("1") - slip), x * (Decimal("1") + slip)


def _calculate_core(
    *,
    mode: str,
    exchange: str,
    direction: str,
    entry_price: float,
    exit_price: float,
    quantity: int,
    slippage_bps: float = 0.0,
    transaction_charge_pct_override: float | None = None,
    dp_base_rupees: float | None = None,
) -> dict[str, Any]:
    active_mode = to_active_mode(mode)
    direction = direction.upper()
    if quantity <= 0:
        raise ValueError("quantity must be positive")
    if active_mode == "SWING" and direction != "LONG":
        raise ValueError("SWING base transaction-cost leg is LONG delivery equity only")

    entry_fill, exit_fill = _fill_prices(direction, entry_price, exit_price, slippage_bps)
    qty = Decimal(quantity)
    if direction == "LONG":
        buy_turnover = entry_fill * qty
        sell_turnover = exit_fill * qty
        gross_pnl = (exit_fill - entry_fill) * qty
    else:
        sell_turnover = entry_fill * qty
        buy_turnover = exit_fill * qty
        gross_pnl = (entry_fill - exit_fill) * qty
    total_turnover = buy_turnover + sell_turnover

    txn_pct, warnings = _transaction_pct(exchange, transaction_charge_pct_override)

    if active_mode == "INTRADAY":
        brokerage_buy = min(_pct(buy_turnover, COST_PROFILE["intraday_brokerage_pct"]), _d(COST_PROFILE["intraday_brokerage_cap_per_executed_order"]))
        brokerage_sell = min(_pct(sell_turnover, COST_PROFILE["intraday_brokerage_pct"]), _d(COST_PROFILE["intraday_brokerage_cap_per_executed_order"]))
        stt_buy = Decimal("0")
        stt_sell = _nearest_rupee(_pct(sell_turnover, COST_PROFILE["stt_intraday_sell_pct"]))
        stamp = _pct(buy_turnover, COST_PROFILE["stamp_intraday_buy_pct"])
        dp = Decimal("0")
    else:
        brokerage_buy = Decimal("0")
        brokerage_sell = Decimal("0")
        stt_buy = _nearest_rupee(_pct(buy_turnover, COST_PROFILE["stt_delivery_buy_pct"]))
        stt_sell = _nearest_rupee(_pct(sell_turnover, COST_PROFILE["stt_delivery_sell_pct"]))
        stamp = _pct(buy_turnover, COST_PROFILE["stamp_delivery_buy_pct"])
        dp_base = _d(dp_base_rupees if dp_base_rupees is not None else COST_PROFILE["dp_base_resident_default"])
        if dp_base < 0:
            raise ValueError("dp_base_rupees must be >= 0")
        dp = dp_base * (Decimal("1") + _d(COST_PROFILE["dp_gst_pct"]) / Decimal("100"))

    brokerage = brokerage_buy + brokerage_sell
    transaction = _pct(total_turnover, txn_pct)
    sebi = total_turnover / Decimal("10000000") * _d(COST_PROFILE["sebi_per_crore"])
    ipft = total_turnover / Decimal("10000000") * _d(COST_PROFILE["ipft_equity_per_crore"])
    gst = (brokerage + transaction + sebi + ipft) * _d(COST_PROFILE["gst_pct"]) / Decimal("100")
    total_charges = brokerage + stt_buy + stt_sell + transaction + sebi + ipft + gst + stamp + dp
    net_pnl = gross_pnl - total_charges

    return {
        "profile_key": COST_PROFILE_KEY,
        "trader_profile": "RESIDENT_INDIAN",
        "mode": active_mode,
        "exchange": exchange.upper(),
        "direction": direction,
        "quantity": quantity,
        "raw_entry_price": round(float(entry_price), 6),
        "raw_exit_price": round(float(exit_price), 6),
        "entry_fill_price": round(float(entry_fill), 6),
        "exit_fill_price": round(float(exit_fill), 6),
        "slippage_bps_each_side": float(slippage_bps),
        "buy_turnover": _money(buy_turnover),
        "sell_turnover": _money(sell_turnover),
        "gross_pnl": _money(gross_pnl),
        "charges": {
            "brokerage": _money(brokerage),
            "stt_buy": _money(stt_buy),
            "stt_sell": _money(stt_sell),
            "transaction_charges": _money(transaction),
            "sebi_charges": _money(sebi),
            "ipft": _money(ipft),
            "gst": _money(gst),
            "stamp_duty": _money(stamp),
            "dp_charge": _money(dp),
            "financing_interest": 0.0,
            "mtf_pledge_unpledge": 0.0,
            "total": _money(total_charges),
        },
        "net_pnl": _money(net_pnl),
        "net_return_on_entry_notional_pct": round(float(net_pnl / (entry_fill * qty) * Decimal("100")), 6),
        "warnings": warnings,
        "mtf_used": False,
        "funded_amount": 0.0,
    }


def calculate_equity_trade_costs(**kwargs: Any) -> dict[str, Any]:
    """Calculate complete resident equity round-trip transaction costs and true net P&L."""
    result = _calculate_core(**kwargs)
    result["break_even_exit_price"] = solve_exit_price_for_net_profit(
        desired_net_profit=0.0,
        mode=result["mode"], exchange=result["exchange"], direction=result["direction"],
        entry_price=result["raw_entry_price"], quantity=result["quantity"],
        slippage_bps=result["slippage_bps_each_side"],
        transaction_charge_pct_override=kwargs.get("transaction_charge_pct_override"),
        dp_base_rupees=kwargs.get("dp_base_rupees"),
    )
    return result


def solve_exit_price_for_net_profit(
    *,
    desired_net_profit: float,
    mode: str,
    exchange: str,
    direction: str,
    entry_price: float,
    quantity: int,
    slippage_bps: float = 0.0,
    transaction_charge_pct_override: float | None = None,
    dp_base_rupees: float | None = None,
) -> float:
    """Binary-search the raw exit quote needed for a desired after-cost P&L."""
    if quantity <= 0 or entry_price <= 0:
        raise ValueError("entry_price and quantity must be positive")
    active_mode = to_active_mode(mode)
    direction = direction.upper()
    if active_mode == "SWING" and direction != "LONG":
        raise ValueError("SWING is LONG-only")

    def pnl_at(price: float) -> float:
        return float(_calculate_core(
            mode=active_mode, exchange=exchange, direction=direction,
            entry_price=entry_price, exit_price=price, quantity=quantity,
            slippage_bps=slippage_bps,
            transaction_charge_pct_override=transaction_charge_pct_override,
            dp_base_rupees=dp_base_rupees,
        )["net_pnl"])

    target = float(desired_net_profit)
    if direction == "LONG":
        lo, hi = entry_price * 0.5, entry_price * 1.5
        for _ in range(20):
            if pnl_at(hi) >= target:
                break
            hi *= 1.5
        for _ in range(70):
            mid = (lo + hi) / 2
            if pnl_at(mid) >= target:
                hi = mid
            else:
                lo = mid
        return round(hi, 4)

    lo, hi = max(0.01, entry_price * 0.01), entry_price * 1.5
    if pnl_at(lo) < target:
        raise ValueError("Desired SHORT net profit is not reachable before price approaches zero")
    for _ in range(70):
        mid = (lo + hi) / 2
        if pnl_at(mid) >= target:
            lo = mid
        else:
            hi = mid
    return round(lo, 4)


def cost_profile() -> dict[str, Any]:
    """Return base transaction-cost metadata without granting any funding permission."""
    return {
        **COST_PROFILE,
        "data_credential_boundary": data_credential_boundary(),
        "active_modes": ["INTRADAY", "SWING"],
        "component_scope": "BASE_RESIDENT_EQUITY_TRANSACTION_COSTS_ONLY",
        "swing_funding": "NOT_APPLICABLE_BASE_COMPONENT",
        "active_swing_funding_permission": "DEFINED_BY_TRADEBRAIN_POLICY_NOT_THIS_COMPONENT",
        "paper_intraday_buying_power": "CASH_NOTIONAL_CONSERVATIVE",
    }
