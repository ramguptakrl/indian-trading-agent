from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from backend.tradebrain.ml_features import FeatureBundle
from backend.tradebrain.ml_meta_labeling import (
    SIGNAL_MEAN_REVERSION,
    SIGNAL_TREND_MOMENTUM,
    SIGNAL_VOLATILITY_BREAKOUT,
    meta_label_bundle,
    primary_signal_mask,
)


class MLMetaLabelingTests(unittest.TestCase):
    @staticmethod
    def _bundle(task: str = "BSE_INTRADAY_LONG", n: int = 180) -> FeatureBundle:
        dates = pd.date_range("2023-01-02 04:00:00Z", periods=n, freq="15min")
        frame = pd.DataFrame(
            {
                "ts_close": dates,
                "label_end": dates + pd.Timedelta(minutes=60),
                "label_net_positive": np.asarray([i % 2 for i in range(n)], dtype=int),
                "ema20_over_50_pct": np.full(n, 0.5 if task.endswith("LONG") else -0.5),
                "vwap_distance_pct": np.full(n, 0.4 if task.endswith("LONG") else -0.4),
                "relative_volume_20": np.full(n, 1.4),
                "dmi_spread": np.full(n, 10.0 if task.endswith("LONG") else -10.0),
                "adx_14": np.full(n, 25.0),
                "bollinger_position": np.full(n, 0.05 if task.endswith("LONG") else 0.95),
                "rsi_14": np.full(n, 25.0 if task.endswith("LONG") else 75.0),
                "volume_expansion": np.full(n, 0.8),
                "bollinger_bandwidth_pct": np.full(n, 1.0),
                "candle_range_pct": np.full(n, 0.5),
                "inside_bar": np.zeros(n),
                "return_1": np.full(n, 0.3 if task.endswith("LONG") else -0.3),
            }
        )
        features = tuple(
            name for name in frame.columns
            if name not in {"ts_close", "label_end", "label_net_positive"}
        )
        return FeatureBundle(
            frame=frame,
            feature_columns=features,
            metadata={"task": task},
        )

    def test_trend_primary_signal_is_independent_of_labels(self):
        bundle = self._bundle()
        first = primary_signal_mask(bundle, signal_family=SIGNAL_TREND_MOMENTUM)
        flipped = self._bundle()
        flipped.frame["label_net_positive"] = 1 - flipped.frame["label_net_positive"]
        second = primary_signal_mask(flipped, signal_family=SIGNAL_TREND_MOMENTUM)
        pd.testing.assert_series_equal(first, second)
        self.assertTrue(first.all())

    def test_mean_reversion_long_and_short_have_deterministic_direction(self):
        long_mask = primary_signal_mask(self._bundle("BSE_INTRADAY_LONG"), signal_family=SIGNAL_MEAN_REVERSION)
        short_mask = primary_signal_mask(self._bundle("BSE_INTRADAY_SHORT"), signal_family=SIGNAL_MEAN_REVERSION)
        self.assertTrue(long_mask.all())
        self.assertTrue(short_mask.all())

    def test_volatility_breakout_uses_only_prior_threshold_history(self):
        bundle = self._bundle(n=100)
        frame = bundle.frame
        # Build a long breakout at row 70: prior bar is compressed/inside, current bar expands.
        frame.loc[:, "inside_bar"] = 0.0
        frame.loc[:, "bollinger_bandwidth_pct"] = 2.0
        frame.loc[:, "candle_range_pct"] = 0.5
        frame.loc[69, "inside_bar"] = 1.0
        frame.loc[70, "candle_range_pct"] = 1.2
        frame.loc[70, "relative_volume_20"] = 1.5
        frame.loc[70, "return_1"] = 0.8
        before = primary_signal_mask(bundle, signal_family=SIGNAL_VOLATILITY_BREAKOUT)
        self.assertTrue(bool(before.iloc[70]))

        # Mutating future rows must not alter the historical signal at row 70.
        frame.loc[80:, "bollinger_bandwidth_pct"] = 99.0
        frame.loc[80:, "candle_range_pct"] = 99.0
        after = primary_signal_mask(bundle, signal_family=SIGNAL_VOLATILITY_BREAKOUT)
        self.assertEqual(bool(before.iloc[70]), bool(after.iloc[70]))

    def test_meta_bundle_reuses_existing_triple_barrier_target_as_secondary_filter(self):
        bundle = self._bundle(n=180)
        meta = meta_label_bundle(
            bundle,
            signal_family=SIGNAL_TREND_MOMENTUM,
            min_setups=100,
        )
        self.assertEqual(len(meta.frame), 180)
        self.assertEqual(meta.metadata["meta_target"], "label_net_positive")
        self.assertTrue(meta.metadata["existing_triple_barrier_labels_reused"])
        self.assertFalse(meta.metadata["primary_signal_used_labels"])
        self.assertFalse(meta.metadata["ml_decides_direction"])
        self.assertTrue(meta.metadata["ml_is_secondary_accept_reject_filter"])
        self.assertFalse(meta.metadata["trade_authorization"])
        self.assertFalse(meta.metadata["order_execution_allowed"])


if __name__ == "__main__":
    unittest.main()
