from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from backend.tradebrain.identity import ExchangeListing
from backend.tradebrain.market_data_store import ensure_series, upsert_bars
from backend.tradebrain.ml_features import build_point_in_time_features
from backend.tradebrain.ml_labels import (
    TASK_INTRADAY_SHORT,
    TASK_SWING_LONG_MTF,
    build_labeled_dataset,
)
from backend.tradebrain.ml_validation import Chronology, chronological_split
from backend.tradebrain.store import upsert_listing

IST = timezone(timedelta(hours=5, minutes=30))


class MLDataSafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "tradebrain.db")
        os.environ["TRADEBRAIN_DATA_DIR"] = os.path.join(self.tmp.name, "data")
        upsert_listing(
            ExchangeListing(exchange="NSE", symbol="BSE", isin="INE118H01025"),
            listing_name="BSE Limited",
            security_name="BSE Limited",
            listing_status="ACTIVE",
            source_key="TEST_MASTER",
            source_timestamp="2026-01-01T00:00:00+00:00",
            db_path=self.db,
        )
        self.series = ensure_series(
            exchange="NSE",
            symbol="BSE",
            source_key="TEST_VENDOR",
            source_symbol="BSE.NS",
            base_interval="15m",
            db_path=self.db,
        )

    def tearDown(self):
        os.environ.pop("TRADEBRAIN_DATA_DIR", None)
        self.tmp.cleanup()

    def _intraday_bars(self, start_day: datetime, sessions: int, *, era="era:A", shock_after=None):
        rows = []
        idx = 0
        price = 100.0
        for day in range(sessions):
            base = start_day + timedelta(days=day)
            for block in range(24):
                opened = base.replace(hour=9, minute=15, second=0, microsecond=0) + timedelta(minutes=15 * block)
                drift = 0.08 + np.sin(idx / 7.0) * 0.03
                if shock_after is not None and idx >= shock_after:
                    drift += 4.0
                close = price + drift
                rows.append(
                    {
                        "ts_open": opened.astimezone(timezone.utc).isoformat(),
                        "ts_close": (opened + timedelta(minutes=15)).astimezone(timezone.utc).isoformat(),
                        "open": price,
                        "high": max(price, close) + 0.25,
                        "low": min(price, close) - 0.25,
                        "close": close,
                        "volume": 1000.0 + (idx % 10) * 25,
                        "source_timestamp": opened.astimezone(timezone.utc).isoformat(),
                        "is_final": True,
                        "quality_flags": [],
                        "era_id": era,
                    }
                )
                price = close
                idx += 1
        return rows

    def test_features_do_not_change_when_future_bars_are_appended(self):
        start = datetime(2026, 1, 1, tzinfo=IST)
        first = self._intraday_bars(start, 4)
        upsert_bars(self.series["series_id"], "15m", first, source_key="TEST_VENDOR", db_path=self.db)
        before = build_point_in_time_features(
            self.series["series_id"], interval="15m", as_of=first[-1]["ts_close"], db_path=self.db
        )
        anchor = before.frame.iloc[60]
        values = {key: anchor[key] for key in ("rsi_14", "macd", "atr_14", "ema_20", "relative_volume_20")}
        future = self._intraday_bars(start + timedelta(days=4), 2, shock_after=0)
        upsert_bars(self.series["series_id"], "15m", future, source_key="TEST_VENDOR", db_path=self.db)
        after = build_point_in_time_features(
            self.series["series_id"], interval="15m", as_of=future[-1]["ts_close"], db_path=self.db
        )
        same = after.frame.loc[after.frame["ts_open"] == anchor["ts_open"]].iloc[0]
        for key, expected in values.items():
            self.assertAlmostEqual(float(same[key]), float(expected), places=10)

    def test_dataset_hash_is_deterministic_for_same_cutoff(self):
        rows = self._intraday_bars(datetime(2026, 1, 1, tzinfo=IST), 4)
        upsert_bars(self.series["series_id"], "15m", rows, source_key="TEST_VENDOR", db_path=self.db)
        one = build_point_in_time_features(
            self.series["series_id"], interval="15m", as_of=rows[-1]["ts_close"], db_path=self.db
        )
        two = build_point_in_time_features(
            self.series["series_id"], interval="15m", as_of=rows[-1]["ts_close"], db_path=self.db
        )
        self.assertEqual(one.metadata["dataset_snapshot_hash"], two.metadata["dataset_snapshot_hash"])

    def test_rolling_features_reset_at_raw_price_era_boundary(self):
        start = datetime(2026, 1, 1, tzinfo=IST)
        first = self._intraday_bars(start, 3, era="era:A")
        second = self._intraday_bars(start + timedelta(days=3), 3, era="era:B")
        upsert_bars(self.series["series_id"], "15m", first + second, source_key="TEST_VENDOR", db_path=self.db)
        result = build_point_in_time_features(
            self.series["series_id"], interval="15m", as_of=second[-1]["ts_close"], db_path=self.db
        )
        first_b = result.frame.loc[result.frame["era_key"] == "era:B"].iloc[0]
        self.assertTrue(pd.isna(first_b["ema_50"]))
        self.assertEqual(first_b["missing__ema_50"], 1.0)

    def test_intraday_short_labels_never_cross_session_or_1510_entry_cutoff(self):
        rows = self._intraday_bars(datetime(2026, 1, 1, tzinfo=IST), 5)
        upsert_bars(self.series["series_id"], "15m", rows, source_key="TEST_VENDOR", db_path=self.db)
        dataset = build_labeled_dataset(
            self.series["series_id"], task=TASK_INTRADAY_SHORT, as_of=rows[-1]["ts_close"], db_path=self.db
        )
        self.assertGreater(len(dataset.frame), 0)
        for _, row in dataset.frame.iterrows():
            entry = pd.Timestamp(row["label_entry_time"]).tz_convert("Asia/Kolkata")
            end = pd.Timestamp(row["label_end"]).tz_convert("Asia/Kolkata")
            self.assertEqual(entry.date(), end.date())
            self.assertLess(entry.hour * 60 + entry.minute, 15 * 60 + 10)

    def test_swing_labels_include_mtf_cost_profile_and_funding(self):
        daily = []
        start = datetime(2025, 1, 1, 9, 15, tzinfo=IST)
        price = 100.0
        for idx in range(100):
            opened = start + timedelta(days=idx)
            close = price + (0.35 if idx % 5 else -0.15)
            daily.append(
                {
                    "ts_open": opened.astimezone(timezone.utc).isoformat(),
                    "ts_close": (opened + timedelta(hours=6, minutes=15)).astimezone(timezone.utc).isoformat(),
                    "open": price,
                    "high": max(price, close) + 1.0,
                    "low": min(price, close) - 0.6,
                    "close": close,
                    "volume": 100000.0 + idx * 100,
                    "source_timestamp": opened.astimezone(timezone.utc).isoformat(),
                    "is_final": True,
                    "quality_flags": [],
                    "era_id": "era:daily",
                }
            )
            price = close
        upsert_bars(self.series["series_id"], "1d", daily, source_key="TEST_VENDOR", db_path=self.db)
        dataset = build_labeled_dataset(
            self.series["series_id"], task=TASK_SWING_LONG_MTF, as_of=daily[-1]["ts_close"], db_path=self.db
        )
        self.assertGreater(len(dataset.frame), 0)
        sample = dataset.frame.iloc[0]
        self.assertTrue(bool(sample["label_mtf_profile"]))
        self.assertGreater(float(sample["label_mtf_funded_amount"]), 0.0)
        self.assertGreaterEqual(int(sample["label_mtf_interest_days"]), 0)
        self.assertTrue(bool(sample["label_cost_profile"]))

    def test_chronology_purges_outcome_that_crosses_next_boundary(self):
        frame = pd.DataFrame(
            {
                "ts_close": pd.to_datetime([
                    "2026-01-02T00:00:00Z", "2026-01-09T00:00:00Z", "2026-01-12T00:00:00Z",
                    "2026-01-22T00:00:00Z", "2026-02-02T00:00:00Z",
                ]),
                "label_end": pd.to_datetime([
                    "2026-01-03T00:00:00Z", "2026-01-12T00:00:00Z", "2026-01-13T00:00:00Z",
                    "2026-01-23T00:00:00Z", "2026-02-03T00:00:00Z",
                ]),
                "label_net_positive": [1, 1, 0, 1, 0],
                "label_net_return_pct": [0.2, 0.2, -0.1, 0.2, -0.1],
            }
        )
        chronology = Chronology(
            train_start="2026-01-01T00:00:00Z",
            train_end="2026-01-11T00:00:00Z",
            validation_start="2026-01-11T00:00:00Z",
            validation_end="2026-01-21T00:00:00Z",
            oos_start="2026-01-21T00:00:00Z",
            oos_end="2026-02-01T00:00:00Z",
            holdout_start="2026-02-01T00:00:00Z",
            holdout_end="2026-03-01T00:00:00Z",
            embargo_days=0,
        )
        split = chronological_split(frame, chronology=chronology)
        self.assertEqual(len(split["TRAIN"]), 1)
        self.assertEqual(len(split["VALIDATION"]), 1)
        self.assertEqual(len(split["OOS"]), 1)
        self.assertEqual(len(split["HOLDOUT"]), 1)


if __name__ == "__main__":
    unittest.main()
