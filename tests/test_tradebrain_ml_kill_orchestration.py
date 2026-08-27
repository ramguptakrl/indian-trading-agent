from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd

from backend.tradebrain.ml_features import FeatureBundle
from backend.tradebrain.ml_labels import TASK_INTRADAY_SHORT
from backend.tradebrain.ml_optimizer import OptimizerConfig, optimize_labeled_dataset
from backend.tradebrain.ml_supervisor import run_ml_research_cycle


class MLOptimizerFamilyExclusionTests(unittest.TestCase):
    def test_exact_killed_family_pair_is_not_searched(self):
        bundle = FeatureBundle(
            frame=pd.DataFrame({"placeholder": [1.0]}),
            feature_columns=("a", "b", "c"),
            metadata={"task": "BSE_INTRADAY_LONG", "dataset_snapshot_hash": "snap"},
        )
        split = {
            "TRAIN": pd.DataFrame({"x": [1]}),
            "VALIDATION": pd.DataFrame({"x": [1]}),
            "OOS": pd.DataFrame({"x": [1]}),
            "HOLDOUT": pd.DataFrame({"x": [1]}),
        }
        with patch("backend.tradebrain.ml_optimizer.chronological_split", return_value=split), \
            patch(
                "backend.tradebrain.ml_optimizer.named_feature_sets",
                return_value={"TREND_MOMENTUM": ("a", "b", "c")},
            ), \
            patch(
                "backend.tradebrain.ml_optimizer._search_specs",
                return_value=(SimpleNamespace(family="TREE"),),
            ), \
            patch("backend.tradebrain.ml_optimizer.fit_model") as fit_model:
            result = optimize_labeled_dataset(
                bundle,
                config=OptimizerConfig(
                    excluded_hypothesis_families=(("TREND_MOMENTUM", "TREE"),),
                ),
            )
        fit_model.assert_not_called()
        self.assertEqual(result.status, "NO_ROBUST_CANDIDATE")
        self.assertEqual(result.trials, [])
        self.assertTrue(result.metadata["hypothesis_family_search_exclusions_applied"])
        self.assertEqual(
            result.metadata["excluded_hypothesis_families"],
            [{"feature_set": "TREND_MOMENTUM", "family": "TREE"}],
        )


class MLSupervisorKillOrchestrationTests(unittest.TestCase):
    @staticmethod
    def _bundle():
        return SimpleNamespace(
            frame=pd.DataFrame({"row": [1]}),
            metadata={"dataset_snapshot_hash": "snapshot-1"},
        )

    @staticmethod
    def _optimization(*, status: str = "OOS_PASS", winner: bool = True):
        selected = (
            {
                "feature_set": "TREND_MOMENTUM",
                "family": "TREE",
                "threshold": 0.55,
                "params": {"depth": 4},
                "feature_schema_hash": "schema-trend",
            }
            if winner
            else None
        )
        return SimpleNamespace(
            status=status,
            task=TASK_INTRADAY_SHORT,
            model=None,
            feature_columns=(),
            winner=selected,
            trials=[dict(selected)] if selected else [],
            oos_metrics={"profit_factor": 1.4, "trades": 120} if selected else None,
            oos_stress_15x=None,
            oos_stress_20x={
                "trade_sharpe": 0.4,
                "return_skewness": 0.0,
                "return_kurtosis": 3.0,
            }
            if selected
            else None,
            walk_forward=[],
            metadata={},
        )

    @staticmethod
    def _family_row(*, exhausted: bool):
        return {
            "hypothesis_family_fingerprint": "family-1",
            "hypothesis_family": {
                "task": TASK_INTRADAY_SHORT,
                "architecture": "BASELINE_OPTIMIZER",
                "feature_set": "TREND_MOMENTUM",
                "family": "TREE",
            },
            "distinct_candidate_configurations": 50 if exhausted else 49,
            "best_validation_profit_factor": 1.4,
            "any_selected_candidate_passed_dsr": not exhausted,
            "budget_exhausted_without_dsr_pass": exhausted,
            "new_parameter_search_allowed": not exhausted,
        }

    @classmethod
    def _ledger(cls, *, exhausted: bool, selected_dsr_recorded: bool = False):
        family = cls._family_row(exhausted=exhausted)
        return {
            "distinct_candidate_configurations": 50 if exhausted else 49,
            "distinct_hypothesis_families": 1,
            "validation_trade_sharpes": [0.1, 0.2],
            "hypothesis_families": [family],
            "exhausted_hypothesis_families": [family] if exhausted else [],
            "research_budget_exhausted": exhausted,
            "selected_dsr_recorded": selected_dsr_recorded,
        }

    @staticmethod
    def _serial(optimization):
        return {
            "status": optimization.status,
            "task": optimization.task,
            "feature_columns": [],
            "winner": optimization.winner,
            "trials": optimization.trials,
            "oos_metrics": optimization.oos_metrics,
            "oos_stress_15x": optimization.oos_stress_15x,
            "oos_stress_20x": optimization.oos_stress_20x,
            "walk_forward": [],
            "metadata": optimization.metadata,
            "model_embedded": False,
        }

    def test_preexisting_exhausted_family_is_passed_to_optimizer_as_exact_exclusion(self):
        optimization = self._optimization(status="NO_ROBUST_CANDIDATE", winner=False)
        exhausted = self._ledger(exhausted=True)
        with tempfile.TemporaryDirectory() as tmp, \
            patch("backend.tradebrain.ml_supervisor.get_operating_mode", return_value={"mode": "POST_MARKET_STUDY"}), \
            patch("backend.tradebrain.ml_supervisor.build_labeled_dataset", return_value=self._bundle()), \
            patch("backend.tradebrain.ml_supervisor.research_ledger_summary", return_value=exhausted), \
            patch("backend.tradebrain.ml_supervisor.optimize_labeled_dataset", return_value=optimization) as optimize, \
            patch("backend.tradebrain.ml_supervisor.record_trials", return_value=exhausted), \
            patch("backend.tradebrain.ml_supervisor._selection_bias_evidence", return_value={"passed": False, "verdict": "NO_WINNER"}), \
            patch("backend.tradebrain.ml_supervisor.evaluate_research_kill_criteria", return_value={"verdict": "CONTINUE_RESEARCH", "candidate_killed": False, "hypothesis_family_killed": False}), \
            patch("backend.tradebrain.ml_supervisor._bootstrap_evidence", return_value={"passed": False, "verdict": "NOT_RUN"}), \
            patch("backend.tradebrain.ml_supervisor.evaluate_historical_promotion", return_value={"passed": False, "verdict": "NOT_RUN", "failures": []}), \
            patch("backend.tradebrain.ml_supervisor._cpcv_evidence", return_value={"passed": False, "verdict": "NOT_RUN"}), \
            patch("backend.tradebrain.ml_supervisor.serializable_result", side_effect=self._serial), \
            patch("backend.tradebrain.ml_supervisor._write_result", return_value="artifact.json"), \
            patch("backend.tradebrain.ml_supervisor.registry_root", return_value=Path(tmp) / "registry"):
            result = run_ml_research_cycle(
                "series:test",
                tasks=(TASK_INTRADAY_SHORT,),
                force=True,
                state_path=Path(tmp) / "state.json",
                research_ledger_path=Path(tmp) / "ledger.json",
                registry_path=Path(tmp) / "registry",
            )
        config = optimize.call_args.kwargs["config"]
        self.assertEqual(
            config.excluded_hypothesis_families,
            (("TREND_MOMENTUM", "TREE"),),
        )
        self.assertEqual(
            result["tasks"][TASK_INTRADAY_SHORT]["optimizer_excluded_hypothesis_families"],
            [{"feature_set": "TREND_MOMENTUM", "family": "TREE"}],
        )
        self.assertFalse(result["trade_authorization"])
        self.assertFalse(result["order_execution_allowed"])

    def test_current_dsr_pass_refreshes_family_before_kill_evaluation(self):
        optimization = self._optimization()
        presearch = self._ledger(exhausted=False)
        at_cap_before_dsr = self._ledger(exhausted=True)
        refreshed = self._ledger(exhausted=False, selected_dsr_recorded=True)
        multiple_testing = {
            "passed": False,
            "verdict": "PBO_PENDING",
            "dsr": {
                "passed": True,
                "verdict": "DSR_PASS",
                "deflated_sharpe_probability": 0.98,
                "method_version": "TEST_DSR",
            },
            "pbo": {"passed": False, "verdict": "PBO_PENDING"},
        }
        continue_verdict = {
            "verdict": "CONTINUE_RESEARCH",
            "candidate_killed": False,
            "hypothesis_family_killed": False,
            "candidate_reasons": [],
            "hypothesis_family_reasons": [],
        }
        with tempfile.TemporaryDirectory() as tmp, \
            patch("backend.tradebrain.ml_supervisor.get_operating_mode", return_value={"mode": "POST_MARKET_STUDY"}), \
            patch("backend.tradebrain.ml_supervisor.build_labeled_dataset", return_value=self._bundle()), \
            patch("backend.tradebrain.ml_supervisor.research_ledger_summary", return_value=presearch), \
            patch("backend.tradebrain.ml_supervisor.optimize_labeled_dataset", return_value=optimization), \
            patch("backend.tradebrain.ml_supervisor.record_trials", return_value=at_cap_before_dsr), \
            patch("backend.tradebrain.ml_supervisor._psi_baseline", return_value={}), \
            patch("backend.tradebrain.ml_supervisor._selection_bias_evidence", return_value=multiple_testing), \
            patch("backend.tradebrain.ml_supervisor.record_selected_dsr", return_value=refreshed) as record_dsr, \
            patch("backend.tradebrain.ml_supervisor.evaluate_research_kill_criteria", return_value=continue_verdict) as kill_eval, \
            patch("backend.tradebrain.ml_supervisor._bootstrap_evidence", return_value={"passed": False, "verdict": "NOT_RUN"}), \
            patch("backend.tradebrain.ml_supervisor.evaluate_historical_promotion", return_value={"passed": False, "verdict": "NOT_RUN", "failures": []}), \
            patch("backend.tradebrain.ml_supervisor._cpcv_evidence", return_value={"passed": False, "verdict": "NOT_RUN"}), \
            patch("backend.tradebrain.ml_supervisor.serializable_result", side_effect=self._serial), \
            patch("backend.tradebrain.ml_supervisor.register_optimization", return_value={"model_id": "model-1", "stage": "RESEARCH", "historical_walk_forward_pass": False}) as register, \
            patch("backend.tradebrain.ml_supervisor._write_result", return_value="artifact.json"), \
            patch("backend.tradebrain.ml_supervisor.registry_root", return_value=Path(tmp) / "registry"):
            result = run_ml_research_cycle(
                "series:test",
                tasks=(TASK_INTRADAY_SHORT,),
                force=True,
                state_path=Path(tmp) / "state.json",
                research_ledger_path=Path(tmp) / "ledger.json",
                registry_path=Path(tmp) / "registry",
            )
        record_dsr.assert_called_once()
        self.assertEqual(kill_eval.call_args.args[1], refreshed)
        register.assert_called_once()
        task = result["tasks"][TASK_INTRADAY_SHORT]
        self.assertTrue(task["selected_dsr_recorded"])
        self.assertFalse(task["advancement_blocked_by_kill_criteria"])
        self.assertEqual(task["registered_model_id"], "model-1")

    def test_killed_candidate_cannot_enter_registry(self):
        optimization = self._optimization()
        open_ledger = self._ledger(exhausted=False)
        refreshed = self._ledger(exhausted=True, selected_dsr_recorded=True)
        multiple_testing = {
            "passed": False,
            "verdict": "MULTIPLE_TESTING_REJECTED",
            "dsr": {"passed": False, "verdict": "DSR_REJECTED", "method_version": "TEST_DSR"},
            "pbo": {"passed": False, "verdict": "PBO_REJECTED"},
        }
        killed = {
            "verdict": "HALT_HYPOTHESIS_FAMILY",
            "candidate_killed": True,
            "hypothesis_family_killed": True,
            "candidate_reasons": [],
            "hypothesis_family_reasons": ["HYPOTHESIS_FAMILY_50_CANDIDATE_BUDGET_EXHAUSTED_WITHOUT_DSR_PASS"],
        }
        with tempfile.TemporaryDirectory() as tmp, \
            patch("backend.tradebrain.ml_supervisor.get_operating_mode", return_value={"mode": "POST_MARKET_STUDY"}), \
            patch("backend.tradebrain.ml_supervisor.build_labeled_dataset", return_value=self._bundle()), \
            patch("backend.tradebrain.ml_supervisor.research_ledger_summary", return_value=open_ledger), \
            patch("backend.tradebrain.ml_supervisor.optimize_labeled_dataset", return_value=optimization), \
            patch("backend.tradebrain.ml_supervisor.record_trials", return_value=refreshed), \
            patch("backend.tradebrain.ml_supervisor._psi_baseline", return_value={}), \
            patch("backend.tradebrain.ml_supervisor._selection_bias_evidence", return_value=multiple_testing), \
            patch("backend.tradebrain.ml_supervisor.record_selected_dsr", return_value=refreshed), \
            patch("backend.tradebrain.ml_supervisor.evaluate_research_kill_criteria", return_value=killed), \
            patch("backend.tradebrain.ml_supervisor._bootstrap_evidence", return_value={"passed": False, "verdict": "NOT_RUN"}), \
            patch("backend.tradebrain.ml_supervisor.evaluate_historical_promotion", return_value={"passed": False, "verdict": "NOT_RUN", "failures": []}), \
            patch("backend.tradebrain.ml_supervisor._cpcv_evidence", return_value={"passed": False, "verdict": "NOT_RUN"}), \
            patch("backend.tradebrain.ml_supervisor.serializable_result", side_effect=self._serial), \
            patch("backend.tradebrain.ml_supervisor.register_optimization") as register, \
            patch("backend.tradebrain.ml_supervisor.mark_historical_pass") as historical, \
            patch("backend.tradebrain.ml_supervisor._write_result", return_value="artifact.json"), \
            patch("backend.tradebrain.ml_supervisor.registry_root", return_value=Path(tmp) / "registry"):
            result = run_ml_research_cycle(
                "series:test",
                tasks=(TASK_INTRADAY_SHORT,),
                force=True,
                state_path=Path(tmp) / "state.json",
                research_ledger_path=Path(tmp) / "ledger.json",
                registry_path=Path(tmp) / "registry",
            )
        register.assert_not_called()
        historical.assert_not_called()
        task = result["tasks"][TASK_INTRADAY_SHORT]
        self.assertEqual(task["kill_criteria_verdict"], "HALT_HYPOTHESIS_FAMILY")
        self.assertTrue(task["candidate_killed"])
        self.assertTrue(task["hypothesis_family_killed"])
        self.assertTrue(task["advancement_blocked_by_kill_criteria"])
        self.assertIsNone(task["registered_model_id"])
        self.assertFalse(result["trade_authorization"])
        self.assertFalse(result["order_execution_allowed"])


if __name__ == "__main__":
    unittest.main()
