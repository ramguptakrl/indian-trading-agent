"""Combined resident-equity + Zerodha MTF economics for active Trade Brain SWING.

The base resident equity engine remains versioned separately from Zerodha's incremental
MTF funding charges. This module combines both without enabling broker execution.
"""

from __future__ import annotations

from typing import Any

from backend.tradebrain.equity_costs import calculate_equity_trade_costs
from backend.tradebrain.mtf_economics import calculate_mtf_incremental_costs, mtf_rule_snapshot


def _core(
    *,
    exchange: str,
    entry_price: float,
    exit_price: float,
    quantity: int,
    funded_amount: float,
    interest_days: int,
    slippage_bps: float = 0.0,
    transaction_charge_pct_override: float | None = None,
    dp_base_rupees: float | None = None,
    purchase_date_count: int = 1,
    rms_squareoff_orders: int = 0,
) -> dict[str, Any]:
    if quantity <= 0:
        raise ValueError("quantity must be positive")
    if interest_days < 0:
        raise ValueError("interest_days must be >= 0")

    base = calculate_equity_trade_costs(
        mode="SWING",
        exchange=exchange,
        direction="LONG",
        entry_price=entry_price,
        exit_price=exit_price,
        quantity=quantity,
        slippage_bps=slippage_bps,
        transaction_charge_pct_override=transaction_charge_pct_override,
        dp_base_rupees=dp_base_rupees,
    )
    entry_value = float(base["buy_turnover"])
    exit_value = float(base["sell_turnover"])
    incremental = calculate_mtf_incremental_costs(
        entry_value=entry_value,
        exit_value=exit_value,
        funded_amount=float(funded_amount),
        interest_days=int(interest_days),
        purchase_date_count=purchase_date_count,
        rms_squareoff_orders=rms_squareoff_orders,
        include_unpledge=True,
    )

    charges = dict(base["charges"])
    mtf_costs = incremental["costs"]
    charges["financing_interest"] = float(mtf_costs["mtf_interest"])
    charges["mtf_buy_brokerage"] = float(mtf_costs["mtf_buy_brokerage"])
    charges["mtf_sell_brokerage"] = float(mtf_costs["mtf_sell_brokerage"])
    charges["gst_on_mtf_brokerage"] = float(mtf_costs["gst_on_mtf_brokerage"])
    charges["mtf_pledge"] = float(mtf_costs["pledge"])
    charges["mtf_unpledge"] = float(mtf_costs["unpledge"])
    charges["mtf_rms_squareoff_if_applicable"] = float(mtf_costs["rms_squareoff_if_applicable"])
    charges["mtf_incremental_total"] = float(mtf_costs["mtf_incremental_total"])
    total = round(float(base["charges"]["total"]) + float(mtf_costs["mtf_incremental_total"]), 2)
    charges["total"] = total
    gross = float(base["gross_pnl"])
    net = round(gross - total, 2)

    result = dict(base)
    result.update(
        {
            "charges": charges,
            "net_pnl": net,
            "net_return_on_entry_notional_pct": round(net / entry_value * 100.0, 6),
            "mtf_used": True,
            "funded_amount": round(float(funded_amount), 2),
            "user_cash_contribution": incremental["user_cash_contribution"],
            "mtf_interest_days": int(interest_days),
            "mtf_profile_key": incremental["profile_key"],
            "mtf_profile_verified_on": incremental["verified_on"],
            "base_equity_profile_key": base["profile_key"],
            "mtf_rules": mtf_rule_snapshot(),
            "advisory_only": True,
            "trade_authorization": False,
            "order_execution_allowed": False,
        }
    )
    return result


def calculate_swing_mtf_trade_costs(**kwargs: Any) -> dict[str, Any]:
    result = _core(**kwargs)
    result["break_even_exit_price"] = solve_swing_mtf_exit_price_for_net_profit(
        desired_net_profit=0.0,
        exchange=result["exchange"],
        entry_price=result["raw_entry_price"],
        quantity=result["quantity"],
        funded_amount=result["funded_amount"],
        interest_days=result["mtf_interest_days"],
        slippage_bps=result["slippage_bps_each_side"],
        transaction_charge_pct_override=kwargs.get("transaction_charge_pct_override"),
        dp_base_rupees=kwargs.get("dp_base_rupees"),
        purchase_date_count=kwargs.get("purchase_date_count", 1),
        rms_squareoff_orders=kwargs.get("rms_squareoff_orders", 0),
    )
    return result


def solve_swing_mtf_exit_price_for_net_profit(
    *,
    desired_net_profit: float,
    exchange: str,
    entry_price: float,
    quantity: int,
    funded_amount: float,
    interest_days: int,
    slippage_bps: float = 0.0,
    transaction_charge_pct_override: float | None = None,
    dp_base_rupees: float | None = None,
    purchase_date_count: int = 1,
    rms_squareoff_orders: int = 0,
) -> float:
    if entry_price <= 0 or quantity <= 0:
        raise ValueError("entry_price and quantity must be positive")

    def pnl_at(price: float) -> float:
        return float(
            _core(
                exchange=exchange,
                entry_price=entry_price,
                exit_price=price,
                quantity=quantity,
                funded_amount=funded_amount,
                interest_days=interest_days,
                slippage_bps=slippage_bps,
                transaction_charge_pct_override=transaction_charge_pct_override,
                dp_base_rupees=dp_base_rupees,
                purchase_date_count=purchase_date_count,
                rms_squareoff_orders=rms_squareoff_orders,
            )["net_pnl"]
        )

    target = float(desired_net_profit)
    lo, hi = max(0.01, entry_price * 0.5), entry_price * 1.5
    for _ in range(24):
        if pnl_at(hi) >= target:
            break
        hi *= 1.5
    else:
        raise ValueError("Could not bracket required MTF SWING exit price")

    for _ in range(70):
        mid = (lo + hi) / 2.0
        if pnl_at(mid) >= target:
            hi = mid
        else:
            lo = mid
    return round(hi, 4)
