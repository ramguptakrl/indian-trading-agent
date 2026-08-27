from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from backend.tradebrain.ml_features import FeatureBundle
from backend.tradebrain.ml_intraday_features import compact_feature_columns, compact_intraday_bundle


class MLCompactIntradayFeatureTests(unittest.TestCase):
    @staticmethod
    def _bundle(task: str = "BSE_INTRADAY_LONG") -> FeatureBundle:
        rng = np.random.default_rng(20260827)
        n = 250
        base = rng.normal(size=n)
        frame = pd.DataFrame(
            {
                "mtf_alignment_score": rng.normal(size=n),
                "mtf_daily_trend": rng.normal(size=n),
                "mtf_4h_trend": rng.normal(size=n),
                "mtf_1h_trend": rng.normal(size=n),
                "relative_volume_20": rng.lognormal(mean=0.0, sigma=0.4, size=n),
                "natr_14_pct": rng.uniform(0.2, 4.0, size=n),
                "vwap_distance_pct": base,
                "opening_range_position": rng.uniform(0.0, 1.0, size=n),
                "distance_prev_high_pct": rng.normal(size=n),
                "distance_prev_low_pct": rng.normal(size=n),
                "gap_pct": rng.normal(scale=0.8, size=n),
                "adx_14": rng.uniform(5.0, 45.0, size=n),
                "dmi_spread": rng.normal(scale=15.0, size=n),
                "rsi_14": rng.uniform(10.0, 90.0, size=n),
                "macd_hist": rng.normal(scale=0.5, size=n),
                "label_net_positive": rng.integers(0, 2, size=n),
            }
        )
        return FeatureBundle(
            frame=frame,
            feature_columns=tuple(c for c in frame.columns if not c.startswith("label_")),
            metadata={"task": task},
        )

    def test_compact_challenger_caps_at_15_features_and_uses_no_labels(self):
        bundle = self._bundle()
        columns = compact_feature_columns(bundle)
        self.assertGreaterEqual(len(columns), 8)
        self.assertLessEqual(len(columns), 15)
        self.assertTrue(all(not name.startswith("label_") for name in columns))

    def test_highly_correlated_duplicate_is_pruned(self):
        bundle = self._bundle()
        bundle.frame.loc[:, "mtf_daily_trend"] = bundle.frame["mtf_alignment_score"] * 1.0
        columns = compact_feature_columns(bundle)
        self.assertIn("mtf_alignment_score", columns)
        self.assertNotIn("mtf_daily_trend", columns)

    def test_bundle_metadata_records_no_future_or_label_selection(self):
        compact = compact_intraday_bundle(self._bundle())
        self.assertFalse(compact.metadata["feature_selection_used_labels"])
        self.assertFalse(compact.metadata["feature_selection_used_future_outcomes"])
        self.assertFalse(compact.metadata["order_flow_imbalance_claimed"])
        self.assertFalse(compact.metadata["trade_authorization"])
        self.assertFalse(compact.metadata["order_execution_allowed"])

    def test_non_intraday_task_is_rejected(self):
        with self.assertRaises(ValueError):
            compact_intraday_bundle(self._bundle(task="BSE_SWING_LONG_MTF"))


if __name__ == "__main__":
    unittest.main()
