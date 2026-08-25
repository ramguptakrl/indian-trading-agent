"""Advisory-only guardian for manually reported open BSE trades.

The guardian never places/modifies/cancels broker orders. It keeps a human-reported
position under Trade Brain review until the journal is explicitly closed and ensures
hard intraday timing/data-integrity constraints outrank AI opinion.
"""

from __future__ import annotations

from datetime import datetime, time, timezone
from typing import Any
from zoneinfo import ZoneInfo

from backend.tradebrain.actual_trade_journal import list_actual_trades, mark_actual_trade
from backend.tradebrain.kite_stream import latest_kite_quote
from backend.tradebrain.market_guards import combined_market_guard

IST = ZoneInfo("Asia/Kolkata")
INTRADAY_HARD_EXIT = time(15, 15)
METHOD_VERSION = "BSE_POSITION_GUARDIAN_V1"


def _dt(value: str | datetime) -> datetime:
    parsed = datetime.fromisoformat(value) if isinstance(value, str) else value
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _is_adverse(direction: str, entry: float, current: float) -> bool:
    return current < entry if direction == "LONG" else current > entry


def assess_open_trade_risk(
    trade: dict[str, Any],
    *,
    current_price: float,
    evaluated_at: str | datetime | None = None,
    market_guard: dict[str, Any] | None = None,
    event_risk: str = "UNKNOWN",
    correction_state: str = "UNKNOWN",
) -> dict[str, Any]:
    if current_price <= 0:
        raise ValueError("current_price must be positive")
    now = _dt(evaluated_at or datetime.now(timezone.utc)).astimezone(IST)
    status = str(trade.get("status") or "").upper()
    if status == "CLOSED" or int(trade.get("open_quantity") or 0) <= 0:
        return {
            "state": "CLOSED",
            "priority": "NONE",
            "reason": "Journal position is closed",
            "trade_authorization": False,
            "order_execution_allowed": False,
        }

    mode = str(trade.get("mode") or "").upper()
    direction = str(trade.get("direction") or "").upper()
    entry = float(trade.get("avg_entry_price") or 0.0)
    stop = float(trade["stop_loss"]) if trade.get("stop_loss") is not None else None
    target = float(trade["take_profit"]) if trade.get("take_profit") is not None else None
    entry_at = _dt(str(trade["entry_timestamp"])).astimezone(IST)
    guard = market_guard or {}

    if mode == "INTRADAY":
        clock = now.time().replace(tzinfo=None)
        if now.date() > entry_at.date() or (now.date() == entry_at.date() and clock >= INTRADAY_HARD_EXIT):
            return {
                "state": "HARD_EXIT_REQUIRED_BY_INTRADAY_POLICY",
                "priority": "CRITICAL",
                "reason": "INTRADAY exposure must be flat by the Trade Brain 15:15 IST hard-exit boundary",
                "evaluated_at_ist": now.isoformat(),
                "trade_authorization": False,
                "order_execution_allowed": False,
            }

    halt_state = ((guard.get("market_halt") or {}).get("state") or "").upper()
    if halt_state == "MARKET_HALT_CONFIRMED":
        return {
            "state": "MARKET_HALTED_PRESERVE_AND_REASSESS",
            "priority": "CRITICAL",
            "reason": "Confirmed halt: preserve journal state and reassess immediately after reopening",
            "evaluated_at_ist": now.isoformat(),
            "trade_authorization": False,
            "order_execution_allowed": False,
        }

    if guard.get("data_confirmation_required"):
        return {
            "state": "DATA_CONFIRMATION_REQUIRED",
            "priority": "HIGH",
            "reason": "A suspicious/freak tick must be confirmed before changing the position thesis",
            "evaluated_at_ist": now.isoformat(),
            "trade_authorization": False,
            "order_execution_allowed": False,
        }

    stop_breached = (
        stop is not None
        and ((direction == "LONG" and current_price <= stop) or (direction == "SHORT" and current_price >= stop))
    )
    if stop_breached:
        return {
            "state": "EXIT_REVIEW_STOP_BREACHED",
            "priority": "CRITICAL",
            "reason": "Current accepted price breached the recorded stop-loss geometry",
            "stop_loss": stop,
            "current_price": current_price,
            "evaluated_at_ist": now.isoformat(),
            "trade_authorization": False,
            "order_execution_allowed": False,
        }

    target_reached = (
        target is not None
        and ((direction == "LONG" and current_price >= target) or (direction == "SHORT" and current_price <= target))
    )
    if target_reached:
        return {
            "state": "TARGET_REVIEW",
            "priority": "HIGH",
            "reason": "Current accepted price reached/passed the recorded primary target",
            "take_profit": target,
            "current_price": current_price,
            "evaluated_at_ist": now.isoformat(),
            "trade_authorization": False,
            "order_execution_allowed": False,
        }

    adverse = entry > 0 and _is_adverse(direction, entry, current_price)
    event = event_risk.upper()
    correction = correction_state.upper()
    if adverse and event in {"HIGH", "CRITICAL"}:
        return {
            "state": "EARLY_EXIT_REVIEW",
            "priority": "HIGH",
            "reason": "Position is adverse while a high-impact BSE event/news condition is active",
            "event_risk": event,
            "current_price": current_price,
            "evaluated_at_ist": now.isoformat(),
            "trade_authorization": False,
            "order_execution_allowed": False,
        }
    if adverse and correction in {"CRASH_RISK", "SEVERE_CORRECTION", "HIGH_VOL_TREND_DOWN"} and direction == "LONG":
        return {
            "state": "EARLY_EXIT_REVIEW",
            "priority": "HIGH",
            "reason": "Long position is adverse while a severe market-correction condition is active",
            "correction_state": correction,
            "current_price": current_price,
            "evaluated_at_ist": now.isoformat(),
            "trade_authorization": False,
            "order_execution_allowed": False,
        }

    return {
        "state": "HOLD",
        "priority": "NORMAL",
        "reason": "No hard exit, stop breach, confirmed halt, suspect data or supplied high-impact risk condition",
        "event_risk": event,
        "correction_state": correction,
        "current_price": current_price,
        "evaluated_at_ist": now.isoformat(),
        "trade_authorization": False,
        "order_execution_allowed": False,
    }


def position_guardian_snapshot(
    *,
    evaluated_at: str | datetime | None = None,
    db_path: str | None = None,
    event_risk: str = "UNKNOWN",
    correction_state: str = "UNKNOWN",
) -> dict[str, Any]:
    """Mark every open/partial BSE trade against the latest accepted Kite quote."""
    open_trades = list_actual_trades(status="OPEN", limit=1000, db_path=db_path)
    partial = list_actual_trades(status="PARTIALLY_CLOSED", limit=1000, db_path=db_path)
    trades = [item for item in [*open_trades, *partial] if str(item.get("ticker") or "").upper() == "BSE"]
    quote = latest_kite_quote("NSE", "BSE", db_path=db_path)
    if not quote:
        return {
            "method_version": METHOD_VERSION,
            "status": "NO_LIVE_BSE_QUOTE",
            "open_trades": len(trades),
            "positions": [],
            "reason": "No locally persisted Kite BSE quote is available",
            "trade_authorization": False,
            "order_execution_allowed": False,
        }

    current = float(quote["last_price"])
    depth = quote.get("depth") or []
    bids = [float(x["price"]) for x in depth if x.get("side") == "BUY" and float(x.get("price") or 0) > 0]
    asks = [float(x["price"]) for x in depth if x.get("side") == "SELL" and float(x.get("price") or 0) > 0]
    guard = combined_market_guard(
        last_price=current,
        best_bid=max(bids) if bids else None,
        best_ask=min(asks) if asks else None,
    )

    positions = []
    for trade in trades:
        mark = mark_actual_trade(
            trade_id=str(trade["trade_id"]),
            current_price=current,
            source=str(quote.get("source_key") or "ZERODHA_KITE_WEBSOCKET_MARKET_DATA_ONLY"),
            db_path=db_path,
        )
        risk = assess_open_trade_risk(
            trade,
            current_price=current,
            evaluated_at=evaluated_at,
            market_guard=guard,
            event_risk=event_risk,
            correction_state=correction_state,
        )
        positions.append({"trade": trade, "mark": mark, "risk": risk})

    return {
        "method_version": METHOD_VERSION,
        "status": "SUCCESS",
        "quote_received_at": quote.get("received_at"),
        "current_price": current,
        "market_guard": guard,
        "open_trades": len(positions),
        "positions": positions,
        "event_risk_input": event_risk,
        "correction_state_input": correction_state,
        "event_news_auto_integration_complete": False,
        "trade_authorization": False,
        "order_execution_allowed": False,
    }
