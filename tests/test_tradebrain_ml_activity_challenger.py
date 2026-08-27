from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd

from backend.tradebrain.ml_activity_bars import ACTIVITY_VOLUME
from backend.tradebrain.ml_activity_challenger import (
    ActivityLabelConfig,
    build_activity_labeled_dataset,
    load_activity_labeled_dataset,
    run_activity_challenger,
)
from backend.tradebrain.ml_features import FeatureBundle
from backend.tradebrain.ml_labels import TASK_INTRADAY_LONG, TASK_INTRADAY_SHORT

IST = timezone(timedelta(hours=5, minutes=30))


class MLActivityLabelTests(unittest.TestCase):
    @staticmethod
    def _minutes(
        *,
        count: int = 35,
        start_hour: int = 9,
        start_minute: int = 15,
        era: str = "era:A",
    ) -> list[dict]:
        start = datetime(2025, 1, 2, start_hour, start_minute, tzinfo=IST)
        rows: list[dict] = []
        for index in range(count):
            opened = start + timedelta(minutes=index)
            rows.append(
                {
                    "interval": "1m",
                    "ts_open": opened.astimezone(timezone.utc).isoformat(),
                    "ts_close": (opened + timedelta(minutes=1)).astimezone(timezone.utc).isoformat(),
                    "open": 100.0,
                    "high": 100.05,
                    "low": 99.95,
                    "close": 100.0,
                    "volume": 100.0,
                    "source_key": "KITE_HISTORICAL",
                    "source_timestamp": opened.astimezone(timezone.utc).isoformat(),
                    "is_final": True,
                    "is_derived": False,
                    "era_id": era,
                    "quality_flags": [],
                }
            )
        return rows

    def test_labels_enter_on_next_raw_minute_and_use_fixed_wall_clock_horizon(self):
        rows = self._minutes(count=35)
        bundle = build_activity_labeled_dataset(
            rows,
            task=TASK_INTRADAY_LONG,
            activity_kind=ACTIVITY_VOLUME,
            activity_target=100.0,
            label_config=ActivityLabelConfig(max_holding_minutes=3),
        )
        self.assertGreater(len(bundle.frame), 0)
        first = bundle.frame.iloc[0]
        self.assertEqual(first["label_entry_time"], first["ts_close"])
        self.assertLessEqual(int(first["label_holding_raw_1m_bars"]), 3)
        self.assertLessEqual(float(first["label_time_to_event_minutes"]), 3.0)
        self.assertEqual(bundle.metadata["label_future_path_source"], "AUDITED_RAW_1M_ONLY")
        self.assertEqual(
            bundle.metadata["label_horizon_type"],
            "FIXED_WALL_CLOCK_MINUTES_CAPPED_BY_INTRADAY_EXIT_BOUNDARY",
        )
        self.assertFalse(bundle.metadata["irregular_activity_bar_count_used_as_holding_horizon"])

    def test_same_raw_minute_stop_and_target_hit_is_excluded_as_ambiguous(self):
        rows = self._minutes(count=35)
        # Earliest labelable activity feature closes at 09:29 IST; its raw entry bar opens 09:29.
        rows[14]["high"] = 101.0
        rows[14]["low"] = 99.0
        bundle = build_activity_labeled_dataset(
            rows,
            task=TASK_INTRADAY_LONG,
            activity_kind=ACTIVITY_VOLUME,
            activity_target=100.0,
            label_config=ActivityLabelConfig(max_holding_minutes=3),
        )
        self.assertGreaterEqual(bundle.metadata["ambiguous_raw_1m_labels_excluded"], 1)
        self.assertTrue(bundle.metadata["same_raw_1m_stop_target_ambiguity_excluded"])

    def test_entry_cutoff_is_enforced_on_raw_minutes(self):
        rows = self._minutes(count=20, start_hour=14, start_minute=55)
        bundle = build_activity_labeled_dataset(
            rows,
            task=TASK_INTRADAY_SHORT,
            activity_kind=ACTIVITY_VOLUME,
            activity_target=100.0,
            label_config=ActivityLabelConfig(max_holding_minutes=10),
        )
        if not bundle.frame.empty:
            local_entry = pd.to_datetime(bundle.frame["label_entry_time"], utc=True).dt.tz_convert("Asia/Kolkata")
            entry_minutes = local_entry.dt.hour * 60 + local_entry.dt.minute
            self.assertTrue(bool((entry_minutes < 15 * 60 + 10).all()))
        self.assertGreater(bundle.metadata["unlabeled_feature_rows_excluded"], 0)

    def test_caller_target_is_predeclared_and_holdout_is_not_used_for_choice(self):
        bundle = build_activity_labeled_dataset(
            self._minutes(count=35),
            task=TASK_INTRADAY_LONG,
            activity_kind=ACTIVITY_VOLUME,
            activity_target=250.0,
        )
        self.assertEqual(bundle.metadata["activity_target"], 250.0)
        self.assertTrue(bundle.metadata["activity_target_must_be_predeclared"])
        self.assertFalse(bundle.metadata["activity_target_auto_calibrated"])
        self.assertFalse(bundle.metadata["holdout_used_for_activity_target_selection"])
        self.assertFalse(bundle.metadata["holdout_used_for_feature_selection"])
        self.assertFalse(bundle.metadata["holdout_used_for_architecture_selection"])
        self.assertEqual(
            bundle.metadata["historical_2026_holdout_status"],
            "CONSUMED_NOT_CLEAN_FINAL_PROOF",
        )
        self.assertTrue(bundle.metadata["prospective_shadow_required_for_clean_final_proof"])
        self.assertFalse(bundle.metadata["trade_authorization"])
        self.assertFalse(bundle.metadata["order_execution_allowed"])

    def test_loader_reads_only_native_1m_with_replay_cutoff(self):
        rows = self._minutes(count=35)
        cutoff = rows[-1]["ts_close"]
        with patch("backend.tradebrain.ml_activity_challenger.query_bars", return_value=rows) as query:
            bundle = load_activity_labeled_dataset(
                "series:bse",
                task=TASK_INTRADAY_LONG,
                activity_kind=ACTIVITY_VOLUME,
                activity_target=100.0,
                start="2025-01-01T00:00:00+00:00",
                end="2025-12-31T23:59:59+00:00",
                as_of=cutoff,
                limit=12345,
                db_path="audit.db",
            )
        query.assert_called_once_with(
            "series:bse",
            "1m",
            start="2025-01-01T00:00:00+00:00",
            end="2025-12-31T23:59:59+00:00",
            as_of=cutoff,
            limit=12345,
            db_path="audit.db",
        )
        self.assertEqual(bundle.metadata["series_id"], "series:bse")
        self.assertEqual(bundle.metadata["query_as_of"], cutoff)
        self.assertTrue(bundle.metadata["replay_cutoff_enforced_by_source_query"])


class MLActivityGovernanceTests(unittest.TestCase):
    @staticmethod
    def _bundle() -> FeatureBundle:
        frame = pd.DataFrame(
            {
                "ts_close": pd.to_datetime(["2025-01-02T04:00:00Z"]),
                "label_end": pd.to_datetime(["2025-01-02T04:03:00Z"]),
                "label_net_positive": [1],
                "label_net_return_pct": [0.1],
                "label_gross_return_pct": [0.2],
                "return_1": [0.1],
                "candle_range_pct": [0.2],
                "natr_14_pct": [0.3],
            }
        )
        return FeatureBundle(
            frame=frame,
            feature_columns=("return_1", "candle_range_pct", "natr_14_pct"),
            metadata={"task": TASK_INTRADAY_SHORT, "dataset_snapshot_hash": "snap"},
        )

    @staticmethod
    def _optimization() -> SimpleNamespace:
        winner = {
            "feature_set": "ALL",
            "family": "TREE",
            "threshold": 0.55,
            "params": {"depth": 4},
            "feature_schema_hash": "schema",
        }
        return SimpleNamespace(
            status="OOS_PASS",
            task=TASK_INTRADAY_SHORT,
            model=object(),
            feature_columns=("return_1", "candle_range_pct", "natr_14_pct"),
            winner=winner,
            trials=[dict(winner)],
            oos_metrics={"profit_factor": 1.4, "trades": 100},
            oos_stress_15x={"profit_factor": 1.2, "trades": 100},
            oos_stress_20x={"profit_factor": 1.1, "trades": 100},
            walk_forward=[],
            metadata={},
        )

    @staticmethod
    def _ledger(*, exhausted: bool, dsr_recorded: bool = False) -> dict:
        family = {
            "hypothesis_family_fingerprint": "activity-family",
            "hypothesis_family": {
                "task": TASK_INTRADAY_SHORT,
                "architecture": "ACTIVITY_BAR_VOLUME_1M_V1",
                "feature_set": "ALL",
                "family": "TREE",
            },
            "distinct_candidate_configurations": 50 if exhausted else 10,
            "best_validation_profit_factor": 1.4,
            "any_selected_candidate_passed_dsr": dsr_recorded,
            "budget_exhausted_without_dsr_pass": exhausted and not dsr_recorded,
            "new_parameter_search_allowed": not exhausted or dsr_recorded,
        }
        return {
            "distinct_candidate_configurations": 50 if exhausted else 10,
            "distinct_hypothesis_families": 1,
            "validation_trade_sharpes": [0.1, 0.2],
            "hypothesis_families": [family],
            "exhausted_hypothesis_families": [family] if exhausted and not dsr_recorded else [],
            "research_budget_exhausted": exhausted and not dsr_recorded,
            "selected_dsr_recorded": dsr_recorded,
        }

    @staticmethod
    def _serial(optimization) -> dict:
        return {
            "status": optimization.status,
            "task": optimization.task,
            "feature_columns": list(optimization.feature_columns),
            "winner": optimization.winner,
            "trials": optimization.trials,
            "oos_metrics": optimization.oos_metrics,
            "oos_stress_15x": optimization.oos_stress_15x,
            "oos_stress_20x": optimization.oos_stress_20x,
            "walk_forward": [],
            "metadata": optimization.metadata,
            "model_embedded": False,
        }

    def test_dead_activity_family_is_excluded_before_optimizer_search(self):
        exhausted = self._ledger(exhausted=True)
        optimization = self._optimization()
        with patch("backend.tradebrain.ml_activity_challenger.load_activity_labeled_dataset", return_value=self._bundle()), \
            patch("backend.tradebrain.ml_activity_challenger.research_ledger_summary", return_value=exhausted), \
            patch("backend.tradebrain.ml_activity_challenger.optimize_labeled_dataset", return_value=optimization) as optimize, \
            patch("backend.tradebrain.ml_activity_challenger.record_trials", return_value=exhausted), \
            patch("backend.tradebrain.ml_activity_challenger._selection_bias", return_value={"passed": False, "verdict": "NO_CLEARANCE", "dsr": {}, "pbo": {}}), \
            patch("backend.tradebrain.ml_activity_challenger.evaluate_research_kill_criteria", return_value={"candidate_killed": True, "hypothesis_family_killed": True, "verdict": "HALT_HYPOTHESIS_FAMILY"}), \
            patch("backend.tradebrain.ml_activity_challenger._bootstrap", return_value={"passed": False, "verdict": "NOT_RUN"}), \
            patch("backend.tradebrain.ml_activity_challenger.evaluate_historical_promotion", return_value={"passed": False, "verdict": "NOT_RUN"}), \
            patch("backend.tradebrain.ml_activity_challenger._cpcv", return_value={"passed": False, "verdict": "NOT_RUN"}), \
            patch("backend.tradebrain.ml_activity_challenger.serializable_result", side_effect=self._serial):
            result = run_activity_challenger(
                "series:bse",
                task=TASK_INTRADAY_SHORT,
                activity_kind=ACTIVITY_VOLUME,
                activity_target=1000.0,
            )
        config = optimize.call_args.kwargs["config"]
        self.assertEqual(config.excluded_hypothesis_families, (("ALL", "TREE"),))
        self.assertEqual(
            result["optimizer_excluded_hypothesis_families"],
            [{"feature_set": "ALL", "family": "TREE"}],
        )
        self.assertFalse(result["prospective_shadow_eligible"])

    def test_selected_dsr_is_recorded_before_kill_and_survivor_only_becomes_shadow_eligible(self):
        presearch = self._ledger(exhausted=False)
        after_trials = self._ledger(exhausted=True)
        refreshed = self._ledger(exhausted=False, dsr_recorded=True)
        optimization = self._optimization()
        multiple_testing = {
            "passed": True,
            "verdict": "MULTIPLE_TESTING_PASS",
            "dsr": {"passed": True, "verdict": "DSR_PASS", "deflated_sharpe_probability": 0.99},
            "pbo": {"passed": True, "verdict": "PBO_PASS"},
        }
        kill = {
            "candidate_killed": False,
            "hypothesis_family_killed": False,
            "verdict": "CONTINUE_RESEARCH",
        }
        with patch("backend.tradebrain.ml_activity_challenger.load_activity_labeled_dataset", return_value=self._bundle()), \
            patch("backend.tradebrain.ml_activity_challenger.research_ledger_summary", return_value=presearch), \
            patch("backend.tradebrain.ml_activity_challenger.optimize_labeled_dataset", return_value=optimization), \
            patch("backend.tradebrain.ml_activity_challenger.record_trials", return_value=after_trials), \
            patch("backend.tradebrain.ml_activity_challenger._selection_bias", return_value=multiple_testing), \
            patch("backend.tradebrain.ml_activity_challenger.record_selected_dsr", return_value=refreshed) as record_dsr, \
            patch("backend.tradebrain.ml_activity_challenger.evaluate_research_kill_criteria", return_value=kill) as kill_eval, \
            patch("backend.tradebrain.ml_activity_challenger._bootstrap", return_value={"passed": True, "verdict": "BOOTSTRAP_PASS"}), \
            patch("backend.tradebrain.ml_activity_challenger.evaluate_historical_promotion", return_value={"passed": True, "verdict": "HISTORICAL_PASS"}), \
            patch("backend.tradebrain.ml_activity_challenger._cpcv", return_value={"passed": True, "verdict": "CPCV_PASS"}), \
            patch("backend.tradebrain.ml_activity_challenger.serializable_result", side_effect=self._serial):
            result = run_activity_challenger(
                "series:bse",
                task=TASK_INTRADAY_SHORT,
                activity_kind=ACTIVITY_VOLUME,
                activity_target=1000.0,
            )
        record_dsr.assert_called_once()
        self.assertEqual(kill_eval.call_args.args[1], refreshed)
        self.assertTrue(result["prospective_shadow_eligible"])
        self.assertFalse(result["automatic_registration"])
        self.assertFalse(result["automatic_freeze"])
        self.assertFalse(result["automatic_promotion"])
        self.assertFalse(result["automatic_advisory_integration"])
        self.assertFalse(result["trade_authorization"])
        self.assertFalse(result["order_execution_allowed"])
        self.assertEqual(
            result["clean_final_proof_layer"],
            "FUTURE_PROSPECTIVE_SHADOW_SESSIONS",
        )

    def test_kill_clearance_blocks_shadow_eligibility_even_if_other_gates_pass(self):
        ledger = self._ledger(exhausted=False)
        optimization = self._optimization()
        multiple_testing = {
            "passed": True,
            "verdict": "PASS",
            "dsr": {"passed": True, "verdict": "DSR_PASS"},
            "pbo": {"passed": True, "verdict": "PBO_PASS"},
        }
        with tempfile.TemporaryDirectory() as tmp, \
            patch("backend.tradebrain.ml_activity_challenger.load_activity_labeled_dataset", return_value=self._bundle()), \
            patch("backend.tradebrain.ml_activity_challenger.research_ledger_summary", return_value=ledger), \
            patch("backend.tradebrain.ml_activity_challenger.optimize_labeled_dataset", return_value=optimization), \
            patch("backend.tradebrain.ml_activity_challenger.record_trials", return_value=ledger), \
            patch("backend.tradebrain.ml_activity_challenger._selection_bias", return_value=multiple_testing), \
            patch("backend.tradebrain.ml_activity_challenger.record_selected_dsr", return_value=ledger), \
            patch("backend.tradebrain.ml_activity_challenger.evaluate_research_kill_criteria", return_value={"candidate_killed": True, "hypothesis_family_killed": False, "verdict": "KILL_CANDIDATE"}), \
            patch("backend.tradebrain.ml_activity_challenger._bootstrap", return_value={"passed": True, "verdict": "PASS"}), \
            patch("backend.tradebrain.ml_activity_challenger.evaluate_historical_promotion", return_value={"passed": True, "verdict": "PASS"}), \
            patch("backend.tradebrain.ml_activity_challenger._cpcv", return_value={"passed": True, "verdict": "PASS"}), \
            patch("backend.tradebrain.ml_activity_challenger.serializable_result", side_effect=self._serial):
            result = run_activity_challenger(
                "series:bse",
                task=TASK_INTRADAY_SHORT,
                activity_kind=ACTIVITY_VOLUME,
                activity_target=1000.0,
                research_ledger_path=Path(tmp) / "ledger.json",
            )
        self.assertFalse(result["prospective_shadow_eligible"])
        self.assertEqual(result["historical_2026_holdout_status"], "CONSUMED_NOT_CLEAN_FINAL_PROOF")
        self.assertTrue(result["historical_oos_reused_after_research_hypothesis_change"])


if __name__ == "__main__":
    unittest.main()
