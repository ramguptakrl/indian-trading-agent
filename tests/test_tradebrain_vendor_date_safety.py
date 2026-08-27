from __future__ import annotations

import pandas as pd

from tradingagents.dataflows import y_finance


ISO_IST = "2026-08-26T00:00:00+05:30"


def test_yahoo_price_fallback_accepts_offset_aware_iso_tool_dates(monkeypatch):
    calls = {}

    class FakeTicker:
        def history(self, *, start, end):
            calls["start"] = start
            calls["end"] = end
            return pd.DataFrame(
                {"Open": [100.0], "High": [102.0], "Low": [99.0], "Close": [101.0], "Volume": [1000]},
                index=pd.DatetimeIndex(["2026-08-25"]),
            )

    monkeypatch.setattr(y_finance.yf, "Ticker", lambda _symbol: FakeTicker())
    monkeypatch.setattr(y_finance, "yf_retry", lambda func: func())

    result = y_finance.get_YFin_data_online(
        "BSE.NS",
        "2026-08-25T00:00:00+05:30",
        "2026-08-26T00:00:00+05:30",
    )

    assert calls == {"start": "2026-08-25", "end": "2026-08-26"}
    assert "Stock data for BSE.NS from 2026-08-25 to 2026-08-26" in result


def test_yahoo_indicator_fallback_accepts_offset_aware_iso_tool_date(monkeypatch):
    monkeypatch.setattr(
        y_finance,
        "_get_stock_stats_bulk",
        lambda _symbol, _indicator, curr_date: {curr_date: "55.0"},
    )

    result = y_finance.get_stock_stats_indicators_window(
        "BSE.NS", "rsi", ISO_IST, 1
    )

    assert "to 2026-08-26" in result
    assert "2026-08-26: 55.0" in result


def test_historical_fundamental_snapshot_fails_closed_before_vendor_call(monkeypatch):
    called = False

    def should_not_call(_symbol):
        nonlocal called
        called = True
        raise AssertionError("historical snapshot must not call current ticker.info")

    monkeypatch.setattr(y_finance.yf, "Ticker", should_not_call)

    result = y_finance.get_fundamentals("BSE.NS", "2025-08-26T00:00:00+05:30")

    assert called is False
    assert "Point-in-time fundamental safety" in result
    assert "intentionally NOT returned" in result
    assert "dated balance-sheet, cash-flow and income-statement" in result


def test_statement_cutoff_accepts_offset_aware_iso_date(monkeypatch):
    statement = pd.DataFrame(
        {
            pd.Timestamp("2026-06-30"): [10.0],
            pd.Timestamp("2026-09-30"): [20.0],
        },
        index=["Revenue"],
    )

    class FakeTicker:
        quarterly_income_stmt = statement

    monkeypatch.setattr(y_finance.yf, "Ticker", lambda _symbol: FakeTicker())
    monkeypatch.setattr(y_finance, "yf_retry", lambda func: func())

    result = y_finance.get_income_statement("BSE.NS", "quarterly", ISO_IST)

    assert "Statement cutoff: 2026-08-26" in result
    assert "2026-06-30" in result
    assert "2026-09-30" not in result
