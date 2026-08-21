"""Trade Brain operating schedule with verified exchange-calendar awareness."""

from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

from backend.tradebrain.exchange_calendar import session_for_date

IST = ZoneInfo("Asia/Kolkata")
MARKET_OPEN = time(9, 15)
INTRADAY_EXIT_WINDOW = time(15, 10)
INTRADAY_HARD_EXIT = time(15, 15)
MARKET_CLOSE = time(15, 30)
# Legacy names retained for older callers/tests.
DAY_EXIT_WINDOW = INTRADAY_EXIT_WINDOW
DAY_HARD_EXIT = INTRADAY_HARD_EXIT


def _clock_mode(now: datetime, *, session_open: time, session_close: time) -> tuple[str, str]:
    clock = now.timetz().replace(tzinfo=None)
    # The user's hard INTRADAY safety clocks remain 15:10 / 15:15. A special
    # session outside those hours is research-only until hard policy is explicitly changed.
    if clock < session_open:
        return "PRE_MARKET_RESEARCH", "PRE_MARKET"
    if clock < INTRADAY_EXIT_WINDOW and clock < session_close:
        return "LIVE_MARKET_RESEARCH", "NORMAL"
    if clock < INTRADAY_HARD_EXIT and clock < session_close:
        return "LIVE_MARKET_RISK_ONLY", "EXIT_WINDOW"
    if clock < session_close:
        return "LIVE_MARKET_RISK_ONLY", "HARD_EXIT"
    return "POST_MARKET_STUDY", "CLOSED"


def get_operating_mode(
    now: datetime | None = None,
    *,
    exchange: str = "NSE",
    db_path: str | None = None,
    require_verified_calendar: bool = False,
) -> dict:
    """Return research/risk operating state for the current exchange session.

    If official calendar coverage has been loaded, holidays and verified special
    sessions override weekday assumptions. For backward compatibility, callers may
    still use weekday fallback when calendar coverage is unavailable. Safety-critical
    orchestration can set ``require_verified_calendar=True`` to fail closed instead.
    """

    if now is None:
        now = datetime.now(IST)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=IST)
    else:
        now = now.astimezone(IST)

    calendar = session_for_date(now, exchange=exchange, db_path=db_path)
    calendar_verified = bool(calendar.get("calendar_verified"))

    if calendar_verified:
        if not calendar.get("is_trading_session"):
            if calendar.get("session_type") == "SPECIAL_PENDING":
                mode = "STUDY_REPLAY"
                trade_state = "SPECIAL_SESSION_PENDING_TIMES"
            else:
                mode = "STUDY_REPLAY"
                trade_state = "CLOSED"
            return {
                "mode": mode,
                "day_trade_state": trade_state,
                "intraday_trade_state": trade_state,
                "now_ist": now.isoformat(),
                "exchange": exchange.upper(),
                "market_hours_reference": None,
                "day_no_fresh_entry_from": "15:10 IST",
                "day_hard_exit": "15:15 IST",
                "calendar_verified": True,
                "calendar": calendar,
                "note": "Official exchange calendar marks this date non-regular or closed.",
            }

        open_value = calendar.get("open_time") or "09:15"
        close_value = calendar.get("close_time") or "15:30"
        session_open = time.fromisoformat(open_value)
        session_close = time.fromisoformat(close_value)
        mode, trade_state = _clock_mode(now, session_open=session_open, session_close=session_close)
        special = calendar.get("session_type") == "SPECIAL_OPEN"
        hard_rule_compatible = not special or (
            session_open < INTRADAY_HARD_EXIT and session_close <= INTRADAY_HARD_EXIT
        )
        if special and not hard_rule_compatible and mode == "LIVE_MARKET_RESEARCH":
            # Do not let a special-session clock bypass immutable INTRADAY hard times.
            mode = "LIVE_MARKET_RISK_ONLY"
            trade_state = "SPECIAL_SESSION_RESEARCH_ONLY"
        return {
            "mode": mode,
            "day_trade_state": trade_state,
            "intraday_trade_state": trade_state,
            "now_ist": now.isoformat(),
            "exchange": exchange.upper(),
            "market_hours_reference": f"{open_value}-{close_value} IST",
            "day_no_fresh_entry_from": "15:10 IST",
            "day_hard_exit": "15:15 IST",
            "calendar_verified": True,
            "calendar": calendar,
            "special_session_hard_rule_compatible": hard_rule_compatible,
            "note": "Official exchange calendar/session data applied.",
        }

    if require_verified_calendar:
        return {
            "mode": "STUDY_REPLAY",
            "day_trade_state": "CALENDAR_UNVERIFIED",
            "intraday_trade_state": "CALENDAR_UNVERIFIED",
            "now_ist": now.isoformat(),
            "exchange": exchange.upper(),
            "market_hours_reference": None,
            "day_no_fresh_entry_from": "15:10 IST",
            "day_hard_exit": "15:15 IST",
            "calendar_verified": False,
            "calendar": calendar,
            "note": "Fail-closed: verified exchange calendar coverage is required.",
        }

    # Backward-compatible research-only fallback. This is never labelled verified.
    weekday = now.weekday() < 5
    if not weekday:
        mode, trade_state = "STUDY_REPLAY", "CLOSED"
    else:
        mode, trade_state = _clock_mode(now, session_open=MARKET_OPEN, session_close=MARKET_CLOSE)
    return {
        "mode": mode,
        "day_trade_state": trade_state,
        "intraday_trade_state": trade_state,
        "now_ist": now.isoformat(),
        "exchange": exchange.upper(),
        "market_hours_reference": "09:15-15:30 IST",
        "day_no_fresh_entry_from": "15:10 IST",
        "day_hard_exit": "15:15 IST",
        "calendar_verified": False,
        "calendar": calendar,
        "note": "Weekday fallback only; official calendar coverage is not loaded for this exchange/year.",
    }
