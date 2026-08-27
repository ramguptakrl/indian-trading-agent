from __future__ import annotations

import unittest
from types import SimpleNamespace

from backend.tradebrain.ml_kill_criteria import (
    evaluate_research_kill_criteria,
    minimum_track_record_length,
)


class MLKillCriteriaTests(unittest.TestCase):
    @staticmethod
    def _result(*, pf: float = 1.5, stress_sharpe: float = 0.35, trades: int = 150):
        return SimpleNamespace(
            winner={
                "feature_set": "TREND",
                "family": "TREE",
            },
            oos_metrics={
                "profit_factor": pf,
                "trades": trades,
            },
            oos_stress_20x={
                "trade_sharpe": stress_sharpe,
                "return_skewness": 0.0,
                "return_kurtosis": 3.0,
            },
        )

    @staticmethod
    def _ledger(*, count: int = 8, exhausted: bool = False, dsr_pass: bool = False, best_pf: float = 1.2):
        return {
            "hypothesis_families": [
                {
                    "hypothesis_family_fingerprint": "family-1",
                    "hypothesis_family": {
                        "task": "BSE_INTRADAY_LONG",
                        "architecture": "BASELINE_OPTIMIZER",
                        "feature_set": "TREND",
                        "family": "TREE",
                    },
                    "distinct_candidate_configurations": count,
                    "best_validation_profit_factor": best_pf,
                    "any_selected_candidate_passed_dsr": dsr_pass,
                    "budget_exhausted_without_dsr_pass": exhausted,
                    "new_parameter_search_allowed": not exhausted,
                }
            ]
        }

    def test_minimum_track_record_increases_when_sharpe_is_weak(self):
        strong = minimum_track_record_length(
            sharpe=0.40,
            skewness=0.0,
            kurtosis=3.0,
        )
        weak = minimum_track_record_length(
            sharpe=0.08,
            skewness=0.0,
            kurtosis=3.0,
        )
        self.assertLess(strong["minimum_required_trades"], weak["minimum_required_trades"])

    def test_non_positive_post_friction_sharpe_is_statistically_unprovable(self):
        report = minimum_track_record_length(
            sharpe=0.0,
            skewness=0.0,
            kurtosis=3.0,
        )
        self.assertFalse(report["finite"])

    def test_family_cap_without_dsr_pass_halts_only_that_family(self):
        verdict = evaluate_research_kill_criteria(
            self._result(),
            self._ledger(count=50, exhausted=True, dsr_pass=False),
        )
        self.assertEqual(verdict["verdict"], "HALT_HYPOTHESIS_FAMILY")
        self.assertTrue(verdict["hypothesis_family_killed"])
        self.assertFalse(verdict["whole_task_declared_dead"])
        self.assertTrue(verdict["new_predeclared_hypothesis_family_allowed"])

    def test_baseline_pf_below_one_halts_current_candidate(self):
        verdict = evaluate_research_kill_criteria(
            self._result(pf=0.95, stress_sharpe=0.25),
            self._ledger(),
        )
        self.assertTrue(verdict["candidate_killed"])
        self.assertIn(
            "BASELINE_FRICTION_PROFIT_FACTOR_NOT_ABOVE_ONE",
            verdict["candidate_reasons"],
        )

    def test_minimum_track_record_over_five_years_halts_candidate(self):
        verdict = evaluate_research_kill_criteria(
            self._result(pf=1.2, stress_sharpe=0.03, trades=15),
            self._ledger(),
        )
        self.assertTrue(verdict["candidate_killed"])
        self.assertIn(
            "MINIMUM_TRACK_RECORD_EXCEEDS_FIVE_YEARS",
            verdict["candidate_reasons"],
        )
        self.assertGreater(verdict["estimated_years_required_for_95pct_confidence"], 5.0)

    def test_strong_candidate_under_open_family_can_continue(self):
        verdict = evaluate_research_kill_criteria(
            self._result(pf=1.6, stress_sharpe=0.45, trades=180),
            self._ledger(count=10, exhausted=False, best_pf=1.6),
        )
        self.assertEqual(verdict["verdict"], "CONTINUE_RESEARCH")
        self.assertFalse(verdict["candidate_killed"])
        self.assertFalse(verdict["hypothesis_family_killed"])
        self.assertFalse(verdict["trade_authorization"])
        self.assertFalse(verdict["order_execution_allowed"])


if __name__ == "__main__":
    unittest.main()
