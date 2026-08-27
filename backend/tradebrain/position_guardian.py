"""Advisory-only guardian for manually reported open BSE trades.

The guardian never places/modifies/cancels broker orders. It keeps a human-reported
position under Trade Brain review until the journal is explicitly closed and ensures
hard intraday timing/data-integrity/corporate-action constraints outrank AI opinion.
A persisted Kite quote must also be fresh before it can drive live position interpretation.
"""

from __future__ import annotations

from datetime import datetime, time, timezone
from typing import Any
from zoneinfo import ZoneInfo

from backend.tradebrain.actual_trade_journal import list_actual_trades, mark_actual_trade
from backend.tradebrain.guardian_context import build_guardian_context
from backend.tradebrain.kite_stream import latest_kite_quote
from backend.tradebrain.market_guards import combined_market_guard

IST = ZoneInfo("Asia/Kolkata")
INTRADAY_HARD_EXIT = time(15, 15)
MAX_LIVE_QUOTE_AGE_SECONDS = 180
METHOD_VERSION = "BSE_POSITION_GUARDIAN_V3_FRESH_QUOTE"


def _dt(value: str | datetime) -> datetime:
    parsed = datetime.fromisoformat(value) if isinstance(value, str) else value
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _quote_freshness(
    quote: dict[str, Any], *, evaluated_at: str | datetime | None = None
) -> dict[str, Any]:
    """Fail closed unless the locally persisted Kite quote is recent and timestamped."""
    now = _dt(evaluated_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    raw_received = quote.get("received_at")
    if not raw_received:
        return {
            "status": "UNVERIFIED",
            "fresh": False,
            "quote_received_at": None,
            "quote_age_seconds": None,
            "max_quote_age_seconds": MAX_LIVE_QUOTE_AGE_SECONDS,
            "reason": "Persisted Kite quote has no received_at timestamp",
        }
    try:
        received = _dt(str(raw_received)).astimezone(timezone.utc)
    except (TypeError, ValueError):
        return {
            "status": "UNVERIFIED",
            "fresh": False,
            "quote_received_at": str(raw_received),
            "quote_age_seconds": None,
            "max_quote_age_seconds": MAX_LIVE_QUOTE_AGE_SECONDS,
            "reason": "Persisted Kite quote received_at timestamp is malformed",
        }
    age = (now - received).total_seconds()
    if age < -5:
        return {
            "status": "UNVERIFIED",
            "fresh": False,
            "quote_received_at": received.isoformat(),
            "quote_age_seconds": round(age, 3),
            "max_quote_age_seconds": MAX_LIVE_QUOTE_AGE_SECONDS,
            "reason": "Persisted Kite quote timestamp is unexpectedly in the future",
        }
    fresh = age <= MAX_LIVE_QUOTE_AGE_SECONDS
    return {
        "status": "FRESH" if fresh else "STALE",
        "fresh": fresh,
        "quote_received_at": received.isoformat(),
        "quote_age_seconds": round(max(age, 0.0), 3),
        "max_quote_age_seconds": MAX_LIVE_QUOTE_AGE_SECONDS,
        "reason": None if fresh else "Persisted Kite quote is older than the Guardian live-data freshness limit",
    }


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
    corporate_action_context: dict[str, Any] | None = None,
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
    action = corporate_action_context or {}

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

    if action.get("stock_split_ex_date"):
        return {
            "state": "CORPORATE_ACTION_POSITION_RECONCILIATION_REQUIRED",
            "priority": "CRITICAL",
            "reason": (
                "Known stock-split ex-date: raw quantity, entry, stop and target must be reconciled to the split-adjusted broker position before P&L or stop logic is trusted."
            ),
            "corporate_action_context": action,
            "current_price": current_price,
            "evaluated_at_ist": now.isoformat(),
            "trade_authorization": False,
            "order_execution_allowed": False,
        }

    if action.get("dividend_ex_date"):
        return {
            "state": "DIVIDEND_EX_DATE_ECONOMIC_REVIEW",
            "priority": "HIGH",
            "reason": (
                "Known dividend ex-date: the mechanical price adjustment and dividend entitlement must be included before interpreting the move as an ordinary stop/gap event."
            ),
            "corporate_action_context": action,
            "current_price": current_price,
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
            "reason": "Long position is adverse while a severe audited correction condition is active",
            "correction_state": correction,
            "current_price": current_price,
            "evaluated_at_ist": now.isoformat(),
            "trade_authorization": False,
            "order_execution_allowed": False,
        }

    return {
        "state": "HOLD",
        "priority": "NORMAL",
        "reason": "No hard exit, stop breach, confirmed halt, suspect data, corporate-action reconciliation issue, or high-impact local risk condition",
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
    event_risk: str | None = None,
    correction_state: str | None = None,
) -> dict[str, Any]:
    """Mark open BSE trades against fresh Kite data plus point-in-time local risk context."""
    open_trades = list_actual_trades(status="OPEN", limit=1000, db_path=db_path)
    partial = list_actual_trades(status="PARTIALLY_CLOSED", limit=1000, db_path=db_path)
    trades = [item for item in [*open_trades, *partial] if str(item.get("ticker") or "").upper() == "BSE"]
    context = build_guardian_context(evaluated_at=evaluated_at, db_path=db_path)
    resolved_event_risk = str(event_risk or context.get("event_risk") or "UNKNOWN").upper()
    resolved_correction = str(correction_state or context.get("correction_state") or "UNKNOWN").upper()
    action_context = context.get("corporate_action_context") or {}

    quote = latest_kite_quote("NSE", "BSE", db_path=db_path)
    if not quote:
        return {
            "method_version": METHOD_VERSION,
            "status": "NO_LIVE_BSE_QUOTE",
            "open_trades": len(trades),
            "positions": [],
            "reason": "No locally persisted Kite BSE quote is available",
            "guardian_context": context,
            "event_risk": resolved_event_risk,
            "correction_state": resolved_correction,
            "trade_authorization": False,
            "order_execution_allowed": False,
        }

    freshness = _quote_freshness(quote, evaluated_at=evaluated_at)
    if not freshness["fresh"]:
        return {
            "method_version": METHOD_VERSION,
            "status": "STALE_LIVE_BSE_QUOTE" if freshness["status"] == "STALE" else "LIVE_BSE_QUOTE_FRESHNESS_UNVERIFIED",
            "open_trades": len(trades),
            "positions": [],
            "reason": freshness["reason"],
            "quote_freshness": freshness,
            "guardian_context": context,
            "event_risk": resolved_event_risk,
            "correction_state": resolved_correction,
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
        if action_context.get("stock_split_ex_date"):
            mark = {
                "status": "SKIPPED_CORPORATE_ACTION_RECONCILIATION",
                "trade_id": str(trade["trade_id"]),
                "current_price": current,
                "reason": "Raw split-day mark would misstate quantity/cost basis before broker-position reconciliation.",
                "trade_authorization": False,
                "order_execution_allowed": False,
            }
        else:
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
            event_risk=resolved_event_risk,
            correction_state=resolved_correction,
            corporate_action_context=action_context,
        )
        positions.append({"trade": trade, "mark": mark, "risk": risk})

    return {
        "method_version": METHOD_VERSION,
        "status": "SUCCESS",
        "quote_received_at": quote.get("received_at"),
        "quote_freshness": freshness,
        "current_price": current,
        "market_guard": guard,
        "guardian_context": context,
        "open_trades": len(positions),
        "positions": positions,
        "event_risk": resolved_event_risk,
        "event_risk_source": "MANUAL_OVERRIDE" if event_risk is not None else "AUTO_LOCAL_EVENT_NEWS_MEMORY",
        "correction_state": resolved_correction,
        "correction_state_source": "MANUAL_OVERRIDE" if correction_state is not None else "AUTO_AUDITED_BSE_PLUS_NIFTY_CONTEXT",
        "event_news_auto_integration_complete": True,
        "audited_bse_correction_auto_integration_complete": context.get("correction_context_status") == "AUDITED_BSE_DAILY_CONTEXT",
        "broader_market_correction_auto_integration_complete": bool(context.get("broader_market_correction_auto_complete")),
        "trade_authorization": False,
        "order_execution_allowed": False,
    }
