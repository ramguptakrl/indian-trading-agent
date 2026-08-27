from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from backend.tradebrain.ml_models import ModelSpec, MODEL_DECISION_TREE
from backend.tradebrain.ml_weighting import (
    fit_friction_weighted_model,
    friction_aware_sample_weights,
    temporal_uniqueness_weights,
)


class MLWeightingTests(unittest.TestCase):
    @staticmethod
    def _frame() -> pd.DataFrame:
        dates = pd.date_range("2024-01-02", periods=80, freq="B", tz="UTC")
        gross = np.where(np.arange(len(dates)) % 2 == 0, 0.8, -0.5)
        net = gross - 0.08
        return pd.DataFrame(
            {
                "ts_close": dates,
                "label_end": dates + pd.to_timedelta((np.arange(len(dates)) % 5) + 1, unit="D"),
                "label_net_positive": (net > 0).astype(int),
                "label_gross_return_pct": gross,
                "label_net_return_pct": net,
                "return_1": np.sin(np.arange(len(dates)) / 5.0),
                "relative_volume_20": 1.0 + (np.arange(len(dates)) % 7) / 10.0,
            }
        )

    def test_uniqueness_downweights_overlapping_windows(self):
        frame = self._frame()
        weights = temporal_uniqueness_weights(frame)
        self.assertEqual(len(weights), len(frame))
        self.assertTrue((weights > 0).all())
        self.assertLess(float(weights.min()), 1.0)

    def test_friction_weights_are_finite_positive_and_normalized(self):
        weights, metadata = friction_aware_sample_weights(self._frame())
        self.assertTrue(np.isfinite(weights).all())
        self.assertTrue((weights > 0).all())
        self.assertAlmostEqual(float(weights.mean()), 1.0, places=12)
        self.assertTrue(metadata["uses_matured_outcomes_only"])
        self.assertFalse(metadata["future_features_used"])
        self.assertFalse(metadata["trade_authorization"])
        self.assertFalse(metadata["order_execution_allowed"])

    def test_near_zero_net_outcome_gets_less_economic_weight(self):
        frame = self._frame().iloc[:20].copy()
        frame.loc[0, "label_gross_return_pct"] = 0.08
        frame.loc[0, "label_net_return_pct"] = 0.001
        frame.loc[1, "label_gross_return_pct"] = 0.80
        frame.loc[1, "label_net_return_pct"] = 0.72
        weights, _ = friction_aware_sample_weights(frame)
        self.assertLess(float(weights[0]), float(weights[1]))

    def test_weighted_decision_tree_fits_without_execution_authority(self):
        frame = self._frame()
        model, metadata = fit_friction_weighted_model(
            frame,
            feature_columns=("return_1", "relative_volume_20"),
            spec=ModelSpec(MODEL_DECISION_TREE, {"max_depth": 4, "min_samples_leaf": 5}),
        )
        self.assertIsNotNone(model)
        self.assertEqual(metadata["method_version"], "BSE_ML_SAMPLE_WEIGHTING_V1")
        self.assertFalse(metadata["trade_authorization"])
        self.assertFalse(metadata["order_execution_allowed"])


if __name__ == "__main__":
    unittest.main()
