from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from backend.tradebrain.ml_features import FeatureBundle
from backend.tradebrain.ml_sequence_features import sequence_context_bundle


class MLSequenceFeatureTests(unittest.TestCase):
    @staticmethod
    def _bundle() -> FeatureBundle:
        first = pd.date_range("2024-01-02 03:45:00Z", periods=20, freq="15min")
        second = pd.date_range("2024-01-03 03:45:00Z", periods=20, freq="15min")
        dates = first.append(second)
        n = len(dates)
        close = 100.0 + np.arange(n, dtype=float) * 0.2
        open_ = close - 0.05
        high = close + 0.25
        low = close - 0.30
        frame = pd.DataFrame(
            {
                "ts_close": dates,
                "label_net_positive": np.asarray([i % 2 for i in range(n)], dtype=int),
                "open": open_,
                "high": high,
                "low": low,
                "close": close,
                "return_1": pd.Series(close).pct_change().fillna(0.0).to_numpy() * 100.0,
                "natr_14_pct": np.full(n, 1.5),
                "relative_volume_20": np.linspace(0.8, 1.5, n),
                "vwap_distance_pct": np.linspace(-0.5, 0.5, n),
                "dmi_spread": np.linspace(-5.0, 5.0, n),
                "adx_14": np.full(n, 24.0),
                "rsi_14": np.linspace(35.0, 65.0, n),
                "macd_hist": np.linspace(-0.2, 0.2, n),
                "candle_range_pct": (high - low) / close * 100.0,
            }
        )
        features = tuple(
            name for name in frame.columns
            if name not in {"ts_close", "label_net_positive", "open", "high", "low", "close"}
        )
        return FeatureBundle(frame=frame, feature_columns=features, metadata={"task": "BSE_INTRADAY_LONG"})

    def test_ohlc_proxy_features_are_finite_and_do_not_claim_level2(self):
        enhanced = sequence_context_bundle(self._bundle())
        for name in (
            "garman_klass_vol_pct",
            "parkinson_vol_pct",
            "close_location_value",
            "vwap_distance_atr_units",
            "range_atr_ratio",
            "relative_volume_x_range_atr",
        ):
            self.assertIn(name, enhanced.feature_columns)
            self.assertGreater(pd.to_numeric(enhanced.frame[name], errors="coerce").notna().sum(), 0)
        self.assertFalse(enhanced.metadata["level2_order_book_claimed"])
        self.assertFalse(enhanced.metadata["synthetic_candles_created"])
        self.assertFalse(enhanced.metadata["neural_sequence_model_used"])

    def test_intraday_lags_reset_at_session_boundary(self):
        enhanced = sequence_context_bundle(self._bundle())
        times = pd.to_datetime(enhanced.frame["ts_close"], utc=True).dt.tz_convert("Asia/Kolkata")
        session = times.dt.date.astype(str)
        first_rows = enhanced.frame.groupby(session, sort=False).head(1).index
        self.assertTrue(enhanced.frame.loc[first_rows, "lag1__return_1"].isna().all())
        second_rows = enhanced.frame.groupby(session, sort=False).nth(1).index
        self.assertTrue(enhanced.frame.loc[second_rows, "lag1__return_1"].notna().all())

    def test_future_mutation_cannot_change_past_sequence_features(self):
        bundle = self._bundle()
        before = sequence_context_bundle(bundle)
        cutoff = 15
        historical = before.frame.loc[:cutoff, [
            "garman_klass_vol_pct",
            "parkinson_vol_pct",
            "directional_efficiency_5",
            "lag3__relative_volume_20",
        ]].copy()

        mutated = self._bundle()
        mutated.frame.loc[cutoff + 5 :, "close"] *= 4.0
        mutated.frame.loc[cutoff + 5 :, "high"] *= 4.0
        mutated.frame.loc[cutoff + 5 :, "low"] *= 4.0
        after = sequence_context_bundle(mutated)
        pd.testing.assert_frame_equal(
            historical,
            after.frame.loc[:cutoff, historical.columns],
            check_exact=False,
            rtol=1e-12,
            atol=1e-12,
        )

    def test_flipping_labels_does_not_change_features(self):
        first_bundle = self._bundle()
        first = sequence_context_bundle(first_bundle)
        second_bundle = self._bundle()
        second_bundle.frame["label_net_positive"] = 1 - second_bundle.frame["label_net_positive"]
        second = sequence_context_bundle(second_bundle)
        columns = list(first.metadata["sequence_context_added_features"])
        pd.testing.assert_frame_equal(first.frame[columns], second.frame[columns])
        self.assertFalse(first.metadata["labels_used_to_construct_features"])
        self.assertFalse(first.metadata["future_bars_used"])
        self.assertFalse(first.metadata["trade_authorization"])
        self.assertFalse(first.metadata["order_execution_allowed"])


if __name__ == "__main__":
    unittest.main()
