from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
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


class RuntimeStudyV2Tests(unittest.TestCase):
    def test_api_governor_paces_and_honors_retry_cooldown(self):
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
        self.assertTrue(sleeps)
        self.assertEqual(sleeps[-1], 1.0)
        governor.register_retry("x", attempt=0, headers={"Retry-After": "3"})
        governor.wait_for_slot("x")
        self.assertTrue(any(value >= 3.0 for value in sleeps))
        snap = governor.snapshot()
        self.assertEqual(snap["buckets"]["x"]["calls"], 3)
        self.assertEqual(snap["buckets"]["x"]["retries"], 1)
        self.assertFalse(snap["order_execution_allowed"])

    def test_multi_timeframe_snapshot_builds_required_hierarchy(self):
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

        def fake_query(series_id, interval, **kwargs):
            return {"1d": daily, "60m": hourly, "15m": fifteen}[interval]

        with patch.object(mtf, "get_series", return_value={"exchange": "NSE", "symbol": "BSE"}), \
             patch.object(mtf, "query_bars", side_effect=fake_query):
            result = mtf.multi_timeframe_snapshot("series:test", as_of=datetime(2026, 8, 25, 18, 0, tzinfo=IST))
        self.assertEqual(result["hierarchy"], ["1D_TREND", "4H_STRUCTURE", "1H_SETUP", "15M_ENTRY_REFINEMENT"])
        self.assertEqual(result["frames"]["4h"]["status"], "OK")
        self.assertFalse(result["4h_exchange_native"])
        self.assertEqual(result["opening_gap"]["status"], "OK")
        self.assertFalse(result["trade_authorization"])

    def test_pattern_lab_is_exploratory_only(self):
        base = datetime(2026, 8, 25, 9, 15, tzinfo=IST)
        bars = []
        for idx in range(24):
            bars.append(_bar(base + timedelta(minutes=15 * idx), 100 + idx * 0.2, minutes=15, volume=1000 + idx))
        bars[2]["low"] = bars[0]["high"] + 1.0
        bars[2]["open"] = bars[2]["low"] + 0.1
        bars[2]["close"] = bars[2]["low"] + 0.2
        bars[2]["high"] = bars[2]["low"] + 0.5

        with patch.object(patterns, "get_series", return_value={"exchange": "NSE", "symbol": "BSE"}), \
             patch.object(patterns, "query_bars", return_value=bars):
            result = patterns.pattern_lab_study("series:test", interval="15m")
        self.assertTrue(result["exploratory_only"])
        self.assertFalse(result["eligible_for_direct_live_promotion"])
        self.assertGreaterEqual(result["fair_value_gaps"]["BULLISH_FVG"]["n"], 1)
        self.assertFalse(result["order_execution_allowed"])

    def test_study_v2_adds_datasets_and_research_without_mutating_policy(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)

            class FakeClient:
                def __init__(self, *args, **kwargs):
                    pass

                def resolve_equity_instrument(self, exchange, symbol):
                    return {"instrument_token": 123}

            calls = []

            def fake_sync(**kwargs):
                calls.append(kwargs["interval"])
                internal = "15m" if kwargs["interval"] == "15minute" else "60m"
                return {
                    "status": "SUCCESS", "series_id": "series:test", "interval": internal,
                    "kite_interval": kwargs["interval"], "rows_received": 100,
                    "bars_inserted": 90, "bars_updated": 10, "chunks": 2,
                    "source_key": "ZERODHA_KITE_CONNECT_MARKET_DATA_ONLY",
                    "credential_role": "MARKET_DATA_ONLY", "order_api_enabled": False,
                }

            env = {"KITE_API_KEY": "A" * 16, "KITE_ACCESS_TOKEN": "B" * 32}
            with patch.dict(os.environ, env, clear=False), \
                 patch.object(study_v2, "get_operating_mode", return_value={"mode": "POST_MARKET_STUDY"}), \
                 patch.object(study_v2, "run_after_market_study", return_value={"status": "SUCCESS", "method_version": "AFTER_MARKET_STUDY_V1", "series_id": "series:test"}), \
                 patch.object(study_v2, "KiteDataOnlyClient", FakeClient), \
                 patch.object(study_v2, "sync_kite_history_range", side_effect=fake_sync), \
                 patch.object(study_v2, "multi_timeframe_snapshot", return_value={"alignment": "BULLISH_LEAN"}), \
                 patch.object(study_v2, "pattern_lab_study", return_value={"exploratory_only": True}), \
                 patch.object(study_v2, "structure_lab_snapshot", return_value={"research_only": True}), \
                 patch.object(study_v2, "archive_current_bse_context_news", return_value={"method_version": "TEST", "retroactive_sentiment_backfill_claimed": False}), \
                 patch.object(study_v2, "audit_learning", return_value=str(root / "audit.txt")):
                result = study_v2.run_after_market_study_v2(
                    now=datetime(2026, 8, 25, 18, 0, tzinfo=IST),
                    state_path=root / "v2.json",
                )

        self.assertEqual(result["status"], "SUCCESS")
        self.assertEqual(calls, ["15minute", "60minute"])
        self.assertFalse(result["learning_boundary"]["hard_rules_modified"])
        self.assertFalse(result["learning_boundary"]["soft_parameters_auto_promoted"])
        self.assertIn("structure_lab", result)
        self.assertIn("news_memory", result)
        self.assertFalse(result["order_execution_allowed"])


if __name__ == "__main__":
    unittest.main()
