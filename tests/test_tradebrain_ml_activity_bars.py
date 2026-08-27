from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pandas as pd

from backend.tradebrain.ml_activity_bars import (
    ACTIVITY_RUPEE_CLOSE_NOTIONAL,
    ACTIVITY_VOLUME,
    build_activity_bars,
    completed_activity_bars,
    load_activity_bars,
)

IST = timezone(timedelta(hours=5, minutes=30))


class MLActivityBarTests(unittest.TestCase):
    @staticmethod
    def _minutes(day: int, volumes: list[float], closes: list[float] | None = None):
        closes = closes or [100.0 + idx for idx in range(len(volumes))]
        start = datetime(2025, 1, day, 9, 15, tzinfo=IST)
        rows = []
        for idx, (volume, close) in enumerate(zip(volumes, closes)):
            opened = start + timedelta(minutes=idx)
            open_price = float(close) - 0.25
            rows.append(
                {
                    "interval": "1m",
                    "ts_open": opened.astimezone(timezone.utc).isoformat(),
                    "ts_close": (opened + timedelta(minutes=1)).astimezone(timezone.utc).isoformat(),
                    "open": open_price,
                    "high": float(close) + 0.50,
                    "low": open_price - 0.50,
                    "close": float(close),
                    "volume": float(volume),
                    "source_key": "KITE_HISTORICAL",
                    "source_timestamp": opened.astimezone(timezone.utc).isoformat(),
                    "is_final": True,
                    "is_derived": False,
                    "era_id": "era:A",
                    "quality_flags": [],
                }
            )
        return rows

    def test_volume_bar_keeps_minute_atomic_and_records_overshoot(self):
        source = self._minutes(2, [100.0, 100.0, 100.0, 50.0])
        bundle = build_activity_bars(source, kind=ACTIVITY_VOLUME, target=250.0)

        self.assertEqual(len(bundle.bars), 2)
        first = bundle.bars.iloc[0]
        trailing = bundle.bars.iloc[1]
        self.assertTrue(bool(first["threshold_reached"]))
        self.assertEqual(int(first["source_minute_count"]), 3)
        self.assertAlmostEqual(float(first["observed_activity"]), 300.0)
        self.assertAlmostEqual(float(first["activity_overshoot"]), 50.0)
        self.assertFalse(bool(trailing["threshold_reached"]))
        self.assertEqual(trailing["partial_reason"], "SESSION_END")
        self.assertAlmostEqual(float(trailing["observed_activity"]), 50.0)

        self.assertEqual(len(bundle.lineage), len(source))
        self.assertFalse(bundle.lineage["source_ts_open"].duplicated().any())
        self.assertEqual(
            bundle.lineage.groupby("activity_bar_id").size().sort_values().tolist(),
            [1, 3],
        )
        self.assertTrue(bundle.metadata["source_minute_is_atomic"])
        self.assertFalse(bundle.metadata["source_minute_splitting_allowed"])
        self.assertFalse(bundle.metadata["threshold_overshoot_carried_into_next_bar"])

    def test_rupee_activity_is_close_times_volume_proxy_not_turnover_claim(self):
        source = self._minutes(2, [10.0, 10.0], closes=[10.0, 20.0])
        bundle = build_activity_bars(
            source,
            kind=ACTIVITY_RUPEE_CLOSE_NOTIONAL,
            target=250.0,
        )
        self.assertEqual(len(bundle.bars), 1)
        bar = bundle.bars.iloc[0]
        self.assertTrue(bool(bar["threshold_reached"]))
        self.assertAlmostEqual(float(bar["observed_activity"]), 300.0)
        self.assertAlmostEqual(float(bar["activity_overshoot"]), 50.0)
        self.assertEqual(bundle.metadata["rupee_activity_definition"], "CLOSE_X_VOLUME_NOTIONAL_PROXY")
        self.assertFalse(bundle.metadata["exact_exchange_turnover_claimed"])

    def test_accumulator_resets_between_ist_sessions(self):
        source = self._minutes(2, [100.0, 100.0]) + self._minutes(3, [100.0, 100.0, 100.0])
        bundle = build_activity_bars(source, kind=ACTIVITY_VOLUME, target=250.0)
        self.assertEqual(len(bundle.bars), 2)
        first = bundle.bars.iloc[0]
        second = bundle.bars.iloc[1]
        self.assertFalse(bool(first["threshold_reached"]))
        self.assertEqual(first["partial_reason"], "SESSION_END")
        self.assertAlmostEqual(float(first["observed_activity"]), 200.0)
        self.assertTrue(bool(second["threshold_reached"]))
        self.assertAlmostEqual(float(second["observed_activity"]), 300.0)
        self.assertNotEqual(first["session_date_ist"], second["session_date_ist"])
        self.assertFalse(bundle.metadata["cross_session_aggregation_allowed"])

    def test_trailing_partial_is_preserved_but_completed_view_excludes_it(self):
        source = self._minutes(2, [150.0, 150.0, 20.0])
        bundle = build_activity_bars(source, kind=ACTIVITY_VOLUME, target=250.0)
        completed = completed_activity_bars(bundle)
        self.assertEqual(len(bundle.bars), 2)
        self.assertEqual(len(completed), 1)
        self.assertEqual(len(bundle.lineage), 3)
        self.assertEqual(bundle.metadata["partial_bars"], 1)
        self.assertTrue(bundle.metadata["trailing_partial_bar_emitted"])

    def test_same_source_and_fixed_target_are_deterministic(self):
        source = self._minutes(2, [100.0, 200.0, 300.0, 50.0])
        one = build_activity_bars(source, kind=ACTIVITY_VOLUME, target=250.0)
        two = build_activity_bars(source, kind=ACTIVITY_VOLUME, target=250.0)
        pd.testing.assert_frame_equal(one.bars, two.bars)
        pd.testing.assert_frame_equal(one.lineage, two.lineage)
        self.assertEqual(one.metadata["source_snapshot_sha256"], two.metadata["source_snapshot_sha256"])
        self.assertFalse(one.metadata["automatic_threshold_calibration"])
        self.assertFalse(one.metadata["holdout_used_for_threshold_selection"])

    def test_truth_metadata_forbids_microstructure_claims_and_execution(self):
        bundle = build_activity_bars(self._minutes(2, [100.0]), kind=ACTIVITY_VOLUME, target=250.0)
        for key in (
            "tick_sequence_reconstructed",
            "intra_minute_sequence_claimed",
            "bid_ask_history_claimed",
            "spread_history_claimed",
            "queue_history_claimed",
            "level2_history_claimed",
            "trade_authorization",
            "order_execution_allowed",
        ):
            self.assertFalse(bundle.metadata[key])
        self.assertTrue(bundle.metadata["research_only"])
        self.assertEqual(bundle.metadata["hypothesis_family_namespace"], "ACTIVITY_BAR")

    def test_rejects_non_native_nonfinal_or_discontinuous_minute_input(self):
        derived = self._minutes(2, [100.0])
        derived[0]["is_derived"] = True
        with self.assertRaisesRegex(ValueError, "native audited 1m"):
            build_activity_bars(derived, kind=ACTIVITY_VOLUME, target=100.0)

        nonfinal = self._minutes(2, [100.0])
        nonfinal[0]["is_final"] = False
        with self.assertRaisesRegex(ValueError, "completed/final"):
            build_activity_bars(nonfinal, kind=ACTIVITY_VOLUME, target=100.0)

        gap = self._minutes(2, [100.0, 100.0, 100.0])
        gap.pop(1)
        with self.assertRaisesRegex(ValueError, "continuity gap"):
            build_activity_bars(gap, kind=ACTIVITY_VOLUME, target=100.0)

    def test_rejects_duplicate_minute_bad_target_and_missing_ohlcv(self):
        duplicate = self._minutes(2, [100.0, 100.0])
        duplicate[1]["ts_open"] = duplicate[0]["ts_open"]
        duplicate[1]["ts_close"] = duplicate[0]["ts_close"]
        with self.assertRaisesRegex(ValueError, "duplicate"):
            build_activity_bars(duplicate, kind=ACTIVITY_VOLUME, target=100.0)

        with self.assertRaisesRegex(ValueError, "finite positive"):
            build_activity_bars(self._minutes(2, [100.0]), kind=ACTIVITY_VOLUME, target=0.0)

        missing = self._minutes(2, [100.0])
        del missing[0]["high"]
        with self.assertRaisesRegex(ValueError, "missing required"):
            build_activity_bars(missing, kind=ACTIVITY_VOLUME, target=100.0)

    def test_era_boundary_never_aggregates_incomparable_raw_price_rows(self):
        source = self._minutes(2, [100.0, 100.0, 100.0])
        source[2]["era_id"] = "era:B"
        bundle = build_activity_bars(source, kind=ACTIVITY_VOLUME, target=250.0)
        self.assertEqual(len(bundle.bars), 2)
        self.assertEqual(bundle.bars.iloc[0]["partial_reason"], "ERA_BOUNDARY")
        self.assertEqual(bundle.bars.iloc[0]["era_id"], "era:A")
        self.assertEqual(bundle.bars.iloc[1]["era_id"], "era:B")

    def test_loader_queries_exact_1m_with_replay_cutoff(self):
        rows = self._minutes(2, [100.0, 200.0])
        cutoff = rows[-1]["ts_close"]
        with patch("backend.tradebrain.ml_activity_bars.query_bars", return_value=rows) as query:
            bundle = load_activity_bars(
                "series:bse",
                kind=ACTIVITY_VOLUME,
                target=250.0,
                start="2025-01-02T03:45:00+00:00",
                end="2025-01-03T03:45:00+00:00",
                as_of=cutoff,
                db_path="test.db",
            )
        query.assert_called_once_with(
            "series:bse",
            "1m",
            start="2025-01-02T03:45:00+00:00",
            end="2025-01-03T03:45:00+00:00",
            as_of=cutoff,
            limit=500000,
            db_path="test.db",
        )
        self.assertEqual(bundle.metadata["series_id"], "series:bse")
        self.assertEqual(bundle.metadata["query_as_of"], cutoff)
        self.assertTrue(bundle.metadata["replay_cutoff_enforced_by_source_query"])


if __name__ == "__main__":
    unittest.main()
