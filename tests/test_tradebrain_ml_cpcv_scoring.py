from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from backend.tradebrain.ml_cpcv import CPCVConfig, evaluate_cpcv_candidate
from backend.tradebrain.ml_models import MODEL_DECISION_TREE


class MLCPCVScoringTests(unittest.TestCase):
    @staticmethod
    def _frame(*, learnable: bool) -> pd.DataFrame:
        rng = np.random.default_rng(20260827)
        dates = pd.date_range("2020-01-02", periods=720, freq="B", tz="UTC")
        signal = rng.normal(size=len(dates))
        noise = rng.normal(size=len(dates))
        if learnable:
            y = (signal + 0.1 * noise > 0.0).astype(int)
        else:
            y = rng.integers(0, 2, size=len(dates))
        gross = np.where(y == 1, 0.80, -0.55)
        net = gross - 0.05
        return pd.DataFrame(
            {
                "ts_close": dates,
                "label_end": dates + pd.Timedelta(days=3),
                "label_net_positive": y,
                "label_gross_return_pct": gross,
                "label_net_return_pct": net,
                "return_1": signal,
                "relative_volume_20": noise,
            }
        )

    def test_frozen_learnable_candidate_can_pass_cpcv(self):
        verdict = evaluate_cpcv_candidate(
            self._frame(learnable=True),
            feature_columns=("return_1", "relative_volume_20"),
            family=MODEL_DECISION_TREE,
            params={"max_depth": 4, "min_samples_leaf": 8},
            threshold=0.55,
            config=CPCVConfig(n_groups=6, n_test_groups=2, embargo_days=2),
        )
        self.assertTrue(verdict["passed"])
        self.assertGreaterEqual(verdict["pass_fraction"], 0.80)
        self.assertEqual(verdict["catastrophic_folds"], 0)
        self.assertFalse(verdict["used_for_hyperparameter_selection"])
        self.assertTrue(verdict["causal_walk_forward_still_required"])
        self.assertTrue(verdict["prequential_replay_still_required"])

    def test_random_candidate_is_rejected(self):
        verdict = evaluate_cpcv_candidate(
            self._frame(learnable=False),
            feature_columns=("return_1", "relative_volume_20"),
            family=MODEL_DECISION_TREE,
            params={"max_depth": 4, "min_samples_leaf": 8},
            threshold=0.55,
            config=CPCVConfig(n_groups=6, n_test_groups=2, embargo_days=2),
        )
        self.assertFalse(verdict["passed"])
        self.assertFalse(verdict["automatic_promotion"])
        self.assertFalse(verdict["trade_authorization"])
        self.assertFalse(verdict["order_execution_allowed"])


if __name__ == "__main__":
    unittest.main()
