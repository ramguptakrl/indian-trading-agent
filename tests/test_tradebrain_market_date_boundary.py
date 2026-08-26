from datetime import date

from tradingagents.dataflows.tradebrain_market import _day


def test_market_tool_accepts_plain_trade_date():
    assert _day("2026-08-26") == date(2026, 8, 26)


def test_market_tool_accepts_offset_aware_midnight_from_agent():
    assert _day("2026-08-26T00:00:00+05:30") == date(2026, 8, 26)


def test_market_tool_accepts_utc_iso_datetime():
    assert _day("2026-08-26T00:00:00Z") == date(2026, 8, 26)
