"""Trade Brain operating schedule.

Market hours are for research mode switching only. Exchange holidays and exceptional
sessions should ultimately come from verified exchange calendar data, not hardcoded
assumptions in this module.
"""

from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
MARKET_OPEN = time(9, 15)
DAY_EXIT_WINDOW = time(15, 10)
DAY_HARD_EXIT = time(15, 15)
MARKET_CLOSE = time(15, 30)


def get_operating_mode(now: datetime | None = None) -> dict:
    """Return the intended brain mode for the current IST clock.

    This is deliberately a scheduler hint, not proof the exchange is open. A future
    official trading-calendar adapter must override weekends/holidays/special sessions.
    """

    if now is None:
        now = datetime.now(IST)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=IST)
    else:
        now = now.astimezone(IST)

    weekday = now.weekday() < 5
    clock = now.timetz().replace(tzinfo=None)

    if not weekday:
        mode = "STUDY_REPLAY"
        day_trade_state = "CLOSED"
    elif clock < MARKET_OPEN:
        mode = "PRE_MARKET_RESEARCH"
        day_trade_state = "PRE_MARKET"
    elif clock < DAY_EXIT_WINDOW:
        mode = "LIVE_MARKET_RESEARCH"
        day_trade_state = "NORMAL"
    elif clock < DAY_HARD_EXIT:
        mode = "LIVE_MARKET_RISK_ONLY"
        day_trade_state = "EXIT_WINDOW"
    elif clock < MARKET_CLOSE:
        mode = "LIVE_MARKET_RISK_ONLY"
        day_trade_state = "HARD_EXIT"
    else:
        mode = "POST_MARKET_STUDY"
        day_trade_state = "CLOSED"

    return {
        "mode": mode,
        "day_trade_state": day_trade_state,
        "now_ist": now.isoformat(),
        "market_hours_reference": "09:15-15:30 IST",
        "day_no_fresh_entry_from": "15:10 IST",
        "day_hard_exit": "15:15 IST",
        "calendar_verified": False,
        "note": "Official exchange calendar data must override this weekday clock when available.",
    }
