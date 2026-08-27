from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from backend.tradebrain.ml_distribution_drift import build_psi_baseline, psi_feature_report
from backend.tradebrain.ml_research_ledger import ResearchBudget, record_trials, research_ledger_summary


class MLResearchGovernanceTests(unittest.TestCase):
    @staticmethod
    def _trial(feature_set: str, family: str, threshold: float, sharpe: float):
        return {
            "feature_set": feature_set,
            "feature_schema_hash": f"schema-{feature_set}",
            "family": family,
            "params": {"depth": 4},
            "threshold": threshold,
            "status": "REJECTED",
            "reason": "unit-test",
            "robustness_score": -0.25,
            "validation": {"trade_sharpe": sharpe},
        }

    def test_research_ledger_deduplicates_repeated_candidate_but_preserves_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ledger.json"
            trials = [
                self._trial("TREND", "TREE", 0.50, 0.10),
                self._trial("TREND", "TREE", 0.55, 0.12),
                self._trial("STRUCTURE", "LOGIT", 0.50, -0.02),
            ]
            first = record_trials(
                task="BSE_INTRADAY_LONG",
                trials=trials,
                dataset_snapshot_hash="snapshot-1",
                code_version="unit-test",
                architecture="BASELINE",
                path=path,
            )
            second = record_trials(
                task="BSE_INTRADAY_LONG",
                trials=trials,
                dataset_snapshot_hash="snapshot-1",
                code_version="unit-test",
                architecture="BASELINE",
                path=path,
            )
            self.assertEqual(first["distinct_candidate_configurations"], 3)
            self.assertEqual(second["distinct_candidate_configurations"], 3)
            self.assertEqual(first["newly_recorded_candidates"], 3)
            self.assertEqual(second["newly_recorded_candidates"], 0)
            self.assertEqual(second["distinct_hypothesis_families"], 2)
            self.assertEqual(len(second["validation_trade_sharpes"]), 3)

    def test_hypothesis_budget_is_separate_from_raw_candidate_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ledger.json"
            trials = []
            for idx in range(5):
                trials.append(self._trial(f"FEATURE_{idx}", f"FAMILY_{idx}", 0.50, 0.01 * idx))
                trials.append(self._trial(f"FEATURE_{idx}", f"FAMILY_{idx}", 0.55, 0.01 * idx + 0.001))
            record_trials(
                task="BSE_INTRADAY_SHORT",
                trials=trials,
                dataset_snapshot_hash="snapshot-2",
                code_version="unit-test",
                path=path,
            )
            summary = research_ledger_summary(
                task="BSE_INTRADAY_SHORT",
                path=path,
                budget=ResearchBudget(max_hypothesis_families=5),
            )
            self.assertEqual(summary["distinct_candidate_configurations"], 10)
            self.assertEqual(summary["distinct_hypothesis_families"], 5)
            self.assertTrue(summary["research_budget_exhausted"])
            self.assertFalse(summary["new_automatic_hypothesis_search_allowed"])

    def test_psi_uses_discovery_distribution_and_detects_large_shift(self):
        rng = np.random.default_rng(123)
        discovery = pd.DataFrame(
            {
                "natr_14_pct": rng.normal(2.0, 0.25, 1000),
                "relative_volume_20": rng.normal(1.0, 0.15, 1000),
                "vwap_distance_pct": rng.normal(0.0, 0.40, 1000),
            }
        )
        columns = tuple(discovery.columns)
        baseline = build_psi_baseline(discovery, columns)
        self.assertEqual(baseline["reference_period"], "TRAIN_PLUS_VALIDATION_ONLY")
        self.assertFalse(baseline["oos_used"])
        self.assertFalse(baseline["holdout_used"])

        stable = psi_feature_report(discovery.tail(100), baseline)
        self.assertIn(stable["status"], {"STABLE", "WATCH"})

        shifted = pd.DataFrame(
            {
                "natr_14_pct": rng.normal(5.0, 0.20, 100),
                "relative_volume_20": rng.normal(2.2, 0.10, 100),
                "vwap_distance_pct": rng.normal(3.0, 0.25, 100),
            }
        )
        alert = psi_feature_report(shifted, baseline)
        self.assertEqual(alert["status"], "DRIFT_ALERT")
        self.assertGreater(alert["features_alert"], 0)
        self.assertFalse(alert["trade_authorization"])
        self.assertFalse(alert["order_execution_allowed"])


if __name__ == "__main__":
    unittest.main()
