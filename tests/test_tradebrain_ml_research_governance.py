from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from backend.tradebrain.ml_distribution_drift import build_psi_baseline, psi_feature_report
from backend.tradebrain.ml_research_ledger import (
    ResearchBudget,
    record_selected_dsr,
    record_trials,
    research_ledger_summary,
)


class MLResearchGovernanceTests(unittest.TestCase):
    @staticmethod
    def _trial(
        feature_set: str,
        family: str,
        threshold: float,
        sharpe: float,
        *,
        profit_factor: float = 0.95,
    ):
        return {
            "feature_set": feature_set,
            "feature_schema_hash": f"schema-{feature_set}",
            "family": family,
            "params": {"depth": 4},
            "threshold": threshold,
            "status": "REJECTED",
            "reason": "unit-test",
            "robustness_score": -0.25,
            "validation": {
                "trade_sharpe": sharpe,
                "profit_factor": profit_factor,
                "mean_net_return_pct": -0.01,
                "trades": 40,
            },
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

    def test_budget_exhausts_one_family_not_the_whole_task(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ledger.json"
            trials = [
                self._trial("TREND", "TREE", 0.50 + idx * 0.01, 0.01 * idx)
                for idx in range(5)
            ]
            # A separate scientific family exists but has only one candidate.
            trials.append(self._trial("MEAN_REVERSION", "LOGIT", 0.50, 0.03))
            record_trials(
                task="BSE_INTRADAY_SHORT",
                trials=trials,
                dataset_snapshot_hash="snapshot-2",
                code_version="unit-test",
                architecture="BASELINE",
                path=path,
            )
            summary = research_ledger_summary(
                task="BSE_INTRADAY_SHORT",
                path=path,
                budget=ResearchBudget(max_candidates_per_hypothesis_family=5),
            )
            self.assertEqual(summary["distinct_candidate_configurations"], 6)
            self.assertEqual(summary["distinct_hypothesis_families"], 2)
            self.assertEqual(summary["exhausted_hypothesis_family_count"], 1)
            self.assertTrue(summary["research_budget_exhausted"])
            self.assertFalse(summary["new_parameter_search_in_exhausted_family_allowed"])
            self.assertTrue(summary["new_predeclared_hypothesis_family_allowed"])

    def test_dsr_pass_reopens_family_even_at_candidate_cap(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ledger.json"
            trials = [
                self._trial("TREND", "TREE", 0.50 + idx * 0.01, 0.05 + 0.01 * idx, profit_factor=1.2)
                for idx in range(5)
            ]
            record_trials(
                task="BSE_INTRADAY_LONG",
                trials=trials,
                dataset_snapshot_hash="snapshot-3",
                code_version="unit-test",
                architecture="BASELINE",
                path=path,
            )
            before = research_ledger_summary(
                task="BSE_INTRADAY_LONG",
                path=path,
                budget=ResearchBudget(max_candidates_per_hypothesis_family=5),
            )
            self.assertEqual(before["exhausted_hypothesis_family_count"], 1)
            record_selected_dsr(
                task="BSE_INTRADAY_LONG",
                winner=trials[-1],
                dsr_evidence={
                    "passed": True,
                    "verdict": "DSR_PASS",
                    "deflated_sharpe_probability": 0.98,
                    "method_version": "TEST_DSR",
                },
                architecture="BASELINE",
                path=path,
            )
            after = research_ledger_summary(
                task="BSE_INTRADAY_LONG",
                path=path,
                budget=ResearchBudget(max_candidates_per_hypothesis_family=5),
            )
            self.assertEqual(after["exhausted_hypothesis_family_count"], 0)
            self.assertTrue(after["hypothesis_families"][0]["any_selected_candidate_passed_dsr"])

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
