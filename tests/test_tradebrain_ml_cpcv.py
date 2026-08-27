from __future__ import annotations

import math
import unittest

import pandas as pd

from backend.tradebrain.ml_cpcv import CPCVConfig, combinatorial_purged_folds, cpcv_plan_summary


class MLCPCVSafetyTests(unittest.TestCase):
    @staticmethod
    def _frame() -> pd.DataFrame:
        dates = pd.date_range("2022-01-03", periods=360, freq="B", tz="UTC")
        return pd.DataFrame(
            {
                "ts_close": dates,
                "label_end": dates + pd.to_timedelta([(i % 7) + 1 for i in range(len(dates))], unit="D"),
                "label_net_positive": [i % 2 for i in range(len(dates))],
                "label_net_return_pct": [0.2 if i % 2 else -0.1 for i in range(len(dates))],
            }
        )

    def test_plan_has_expected_combinatorial_count_when_all_folds_are_usable(self):
        config = CPCVConfig(n_groups=6, n_test_groups=2, embargo_days=1, min_train_rows=100, min_test_rows=20)
        summary = cpcv_plan_summary(self._frame(), config=config)
        self.assertEqual(summary["theoretical_combinations"], math.comb(6, 2))
        self.assertEqual(summary["usable_folds"], math.comb(6, 2))
        self.assertTrue(summary["causal_walk_forward_still_required"])
        self.assertTrue(summary["prequential_replay_still_required"])

    def test_every_fold_purges_target_overlap_and_post_test_embargo(self):
        config = CPCVConfig(n_groups=6, n_test_groups=2, embargo_days=2, min_train_rows=80, min_test_rows=20)
        folds = combinatorial_purged_folds(self._frame(), config=config)
        self.assertTrue(folds)
        for fold in folds:
            train = fold["train"].copy()
            feature = pd.to_datetime(train["ts_close"], utc=True)
            label_end = pd.to_datetime(train["label_end"], utc=True)
            for interval in fold["test_intervals"]:
                start = pd.Timestamp(interval["start"])
                end = pd.Timestamp(interval["label_end"])
                embargo_end = pd.Timestamp(interval["embargo_end"])
                overlap = (feature <= end) & (label_end >= start)
                embargo = (feature > end) & (feature <= embargo_end)
                self.assertFalse(overlap.any())
                self.assertFalse(embargo.any())
            self.assertFalse(fold["causal_replay_replacement"])
            self.assertFalse(fold["trade_authorization"])
            self.assertFalse(fold["order_execution_allowed"])

    def test_invalid_label_window_fails_closed(self):
        frame = self._frame()
        frame.loc[0, "label_end"] = frame.loc[0, "ts_close"] - pd.Timedelta(days=1)
        with self.assertRaises(ValueError):
            combinatorial_purged_folds(frame)


if __name__ == "__main__":
    unittest.main()
