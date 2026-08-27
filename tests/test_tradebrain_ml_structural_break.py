from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from backend.tradebrain.ml_structural_break import (
    VARIANT_FULL_HISTORY,
    VARIANT_POST_BREAK_ONLY,
    VARIANT_PRE_BREAK_DOWNWEIGHTED,
    structural_distribution_report,
    structural_training_view,
)


class MLStructuralBreakTests(unittest.TestCase):
    @staticmethod
    def _frame():
        dates = pd.date_range("2022-01-03", "2024-12-30", freq="2D", tz="UTC")
        n = len(dates)
        values = np.linspace(0.0, 1.0, n)
        return pd.DataFrame(
            {
                "ts_close": dates,
                "label_net_positive": (values > 0.5).astype(int),
                "natr_14_pct": values,
                "relative_volume_20": 1.0 + values,
            }
        )

    def test_full_history_control_keeps_every_row_equal_weight(self):
        frame = self._frame()
        view, weights, meta = structural_training_view(frame, variant=VARIANT_FULL_HISTORY)
        self.assertEqual(len(view), len(frame))
        self.assertTrue(np.allclose(weights, 1.0))
        self.assertTrue(meta["full_history_control_required"])
        self.assertFalse(meta["old_history_deleted"])
        self.assertFalse(meta["labels_used_to_construct_view"])

    def test_pre_break_downweighting_is_fixed_and_label_agnostic(self):
        frame = self._frame()
        view, weights, meta = structural_training_view(frame, variant=VARIANT_PRE_BREAK_DOWNWEIGHTED)
        times = pd.to_datetime(view["ts_close"], utc=True)
        boundary = pd.Timestamp("2023-05-14T18:30:00Z")
        self.assertTrue(np.allclose(weights[(times < boundary).to_numpy()], 0.25))
        self.assertTrue(np.allclose(weights[(times >= boundary).to_numpy()], 1.0))
        flipped = frame.copy()
        flipped["label_net_positive"] = 1 - flipped["label_net_positive"]
        _, flipped_weights, _ = structural_training_view(flipped, variant=VARIANT_PRE_BREAK_DOWNWEIGHTED)
        np.testing.assert_array_equal(weights, flipped_weights)
        self.assertFalse(meta["boundary_selected_using_model_performance"])

    def test_post_break_only_uses_predeclared_date_not_labels(self):
        frame = self._frame()
        view, weights, meta = structural_training_view(frame, variant=VARIANT_POST_BREAK_ONLY)
        self.assertTrue((pd.to_datetime(view["ts_close"], utc=True) >= pd.Timestamp("2023-05-14T18:30:00Z")).all())
        self.assertTrue(np.allclose(weights, 1.0))
        self.assertEqual(meta["break_date_ist"], "2023-05-15")
        self.assertFalse(meta["oos_used_to_choose_boundary"])
        self.assertFalse(meta["holdout_used_to_choose_boundary"])

    def test_distribution_report_stops_before_oos_and_does_not_claim_causation(self):
        frame = self._frame()
        report = structural_distribution_report(
            frame,
            feature_columns=("natr_14_pct", "relative_volume_20"),
        )
        self.assertEqual(report["discovery_end"], "2025-01-01T00:00:00+00:00")
        self.assertFalse(report["oos_used"])
        self.assertFalse(report["holdout_used"])
        self.assertFalse(report["causal_break_claimed"])
        self.assertGreater(len(report["features"]), 0)
        self.assertFalse(report["trade_authorization"])
        self.assertFalse(report["order_execution_allowed"])


if __name__ == "__main__":
    unittest.main()
