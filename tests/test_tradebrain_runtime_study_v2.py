from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from backend.tradebrain.api_governor import ApiBudgetRule, ApiGovernor
import backend.tradebrain.multi_timeframe as mtf
import backend.tradebrain.pattern_lab as patterns
import backend.tradebrain.study_cycle_v2 as study_v2

IST = ZoneInfo("Asia/Kolkata")


def _bar(ts: datetime, price: float, *, minutes: int, volume: float = 1000.0, jump: float = 0.5):
    return {
        "ts_open": ts.astimezone(timezone.utc).isoformat(),
        "ts_close": (ts + timedelta(minutes=minutes)).astimezone(timezone.utc).isoformat(),
        "open": price,
        "high": price + jump,
        "low": max(0.01, price - jump),
        "close": price + 0.2,
        "volume": volume,
        "is_final": 1,
    }


def test_api_governor_paces_and_honors_retry_cooldown():
    clock = {"now": 0.0}
    sleeps = []

    def monotonic():
        return clock["now"]

    def sleep(seconds):
        sleeps.append(seconds)
        clock["now"] += seconds

    governor = ApiGovernor(
        {"x": ApiBudgetRule("x", min_interval_seconds=1.0, max_retries=2, base_backoff_seconds=2.0)},
        sleep_fn=sleep,
        monotonic_fn=monotonic,
        random_fn=lambda: 0.0,
    )
    governor.wait_for_slot("x")
    governor.wait_for_slot("x")
    assert sleeps and sleeps[-1] == 1.0
    governor.register_retry("x", attempt=0, headers={"Retry-After": "3"})
    governor.wait_for_slot("x")
    assert any(value >= 3.0 for value in sleeps)
    snap = governor.snapshot()
    assert snap["buckets"]["x"]["calls"] == 3
    assert snap["buckets"]["x"]["retries"] == 1
    assert snap["order_execution_allowed"] is False


def test_multi_timeframe_snapshot_builds_required_hierarchy(monkeypatch):
    start = datetime(2026, 5, 1, 9, 15, tzinfo=IST)
    daily = []
    for idx in range(80):
        ts = datetime(2026, 5, 1, 9, 15, tzinfo=IST) + timedelta(days=idx)
        daily.append(_bar(ts, 3000 + idx * 2, minutes=375, volume=100000 + idx * 100))
    hourly = []
    fifteen = []
    for day in range(30):
        base = start + timedelta(days=day)
        for hour in range(6):
            hourly.append(_bar(base + timedelta(hours=hour), 3100 + day * 2 + hour, minutes=60, volume=5000))
        for block in range(24):
            fifteen.append(_bar(base + timedelta(minutes=15 * block), 3100 + day * 2 + block * 0.1, minutes=15, volume=1000 + block))

    monkeypatch.setattr(mtf, "get_series", lambda *args, **kwargs: {"exchange": "NSE", "symbol": "BSE"})

    def fake_query(series_id, interval, **kwargs):
        return {"1d": daily, "60m": hourly, "15m": fifteen}[interval]

    monkeypatch.setattr(mtf, "query_bars", fake_query)
    result = mtf.multi_timeframe_snapshot("series:test", as_of=datetime(2026, 8, 25, 18, 0, tzinfo=IST))
    assert result["hierarchy"] == ["1D_TREND", "4H_STRUCTURE", "1H_SETUP", "15M_ENTRY_REFINEMENT"]
    assert result["frames"]["4h"]["status"] == "OK"
    assert result["4h_exchange_native"] is False
    assert result["opening_gap"]["status"] == "OK"
    assert result["trade_authorization"] is False


def test_pattern_lab_is_exploratory_only(monkeypatch):
    base = datetime(2026, 8, 25, 9, 15, tzinfo=IST)
    bars = []
    price = 100.0
    for idx in range(24):
        bar = _bar(base + timedelta(minutes=15 * idx), price + idx * 0.2, minutes=15, volume=1000 + idx)
        bars.append(bar)
    # Force one large three-candle bullish imbalance.
    bars[2]["low"] = bars[0]["high"] + 1.0
    bars[2]["open"] = bars[2]["low"] + 0.1
    bars[2]["close"] = bars[2]["low"] + 0.2
    bars[2]["high"] = bars[2]["low"] + 0.5

    monkeypatch.setattr(patterns, "get_series", lambda *args, **kwargs: {"exchange": "NSE", "symbol": "BSE"})
    monkeypatch.setattr(patterns, "query_bars", lambda *args, **kwargs: bars)
    result = patterns.pattern_lab_study("series:test", interval="15m")
    assert result["exploratory_only"] is True
    assert result["eligible_for_direct_live_promotion"] is False
    assert result["fair_value_gaps"]["BULLISH_FVG"]["n"] >= 1
    assert result["order_execution_allowed"] is False


def test_study_v2_adds_15m_and_60m_without_mutating_policy(monkeypatch, tmp_path):
    monkeypatch.setenv("KITE_API_KEY", "A" * 16)
    monkeypatch.setenv("KITE_ACCESS_TOKEN", "B" * 32)
    monkeypatch.setattr(study_v2, "get_operating_mode", lambda *args, **kwargs: {"mode": "POST_MARKET_STUDY"})
    monkeypatch.setattr(
        study_v2,
        "run_after_market_study",
        lambda **kwargs: {"status": "SUCCESS", "method_version": "AFTER_MARKET_STUDY_V1", "series_id": "series:test"},
    )

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def resolve_equity_instrument(self, exchange, symbol):
            return {"instrument_token": 123}

    monkeypatch.setattr(study_v2, "KiteDataOnlyClient", FakeClient)
    calls = []

    def fake_sync(**kwargs):
        calls.append(kwargs["interval"])
        internal = "15m" if kwargs["interval"] == "15minute" else "60m"
        return {
            "status": "SUCCESS",
            "series_id": "series:test",
            "interval": internal,
            "kite_interval": kwargs["interval"],
            "rows_received": 100,
            "bars_inserted": 90,
            "bars_updated": 10,
            "chunks": 2,
            "source_key": "ZERODHA_KITE_CONNECT_MARKET_DATA_ONLY",
            "credential_role": "MARKET_DATA_ONLY",
            "order_api_enabled": False,
        }

    monkeypatch.setattr(study_v2, "sync_kite_history_range", fake_sync)
    monkeypatch.setattr(study_v2, "multi_timeframe_snapshot", lambda *args, **kwargs: {"alignment": "BULLISH_LEAN"})
    monkeypatch.setattr(study_v2, "pattern_lab_study", lambda *args, **kwargs: {"exploratory_only": True})
    monkeypatch.setattr(study_v2, "audit_learning", lambda *args, **kwargs: str(tmp_path / "audit.txt"))

    result = study_v2.run_after_market_study_v2(
        now=datetime(2026, 8, 25, 18, 0, tzinfo=IST),
        state_path=tmp_path / "v2.json",
    )
    assert result["status"] == "SUCCESS"
    assert calls == ["15minute", "60minute"]
    assert result["learning_boundary"]["hard_rules_modified"] is False
    assert result["learning_boundary"]["soft_parameters_auto_promoted"] is False
    assert result["order_execution_allowed"] is False
