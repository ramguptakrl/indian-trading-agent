from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from backend.tradebrain.ml_adaptive_cycle import run_adaptive_ml_cycle
from backend.tradebrain.ml_features import FeatureBundle
from backend.tradebrain.ml_registry import STAGE_SHADOW


class MLAdaptiveCycleTests(unittest.TestCase):
    @staticmethod
    def _bundle(task: str) -> FeatureBundle:
        frame = pd.DataFrame(
            {
                "ts_close": pd.to_datetime(["2026-08-26T10:00:00Z"]),
                "label_end": pd.to_datetime(["2026-08-26T11:00:00Z"]),
                "label_net_positive": [1],
                "label_net_return_pct": [0.2],
                "label_gross_return_pct": [0.3],
                "return_1": [0.1],
            }
        )
        return FeatureBundle(frame=frame, feature_columns=("return_1",), metadata={"task": task})

    @staticmethod
    def _active(task: str = "BSE_SWING_LONG_MTF"):
        return {
            task: {
                "model_id": f"{task}_ACTIVE1234",
                "task": task,
                "stage": STAGE_SHADOW,
            }
        }

    def test_stable_active_model_is_not_calendar_retrained(self):
        task = "BSE_SWING_LONG_MTF"
        with tempfile.TemporaryDirectory() as tmp, \
            patch("backend.tradebrain.ml_adaptive_cycle.get_operating_mode", return_value={"mode": "POST_MARKET_STUDY"}), \
            patch("backend.tradebrain.ml_adaptive_cycle.latest_active_models", return_value=self._active(task)), \
            patch("backend.tradebrain.ml_adaptive_cycle.build_labeled_dataset", return_value=self._bundle(task)), \
            patch("backend.tradebrain.ml_adaptive_cycle.model_drift_report", return_value={"feature_drift": {"status": "STABLE"}, "shadow_performance": {"status": "STABLE"}}), \
            patch("backend.tradebrain.ml_adaptive_cycle.retraining_recommendation", return_value={"research_retrain_recommended": False, "verdict": "KEEP_FROZEN_MODEL_NO_RETRAIN"}), \
            patch("backend.tradebrain.ml_adaptive_cycle.run_ml_research_cycle") as research:
            result = run_adaptive_ml_cycle(
                "series:test",
                now=datetime.fromisoformat("2026-08-26T18:00:00+05:30"),
                tasks=(task,),
                state_path=Path(tmp) / "state.json",
            )
            self.assertEqual(result["status"], "STABLE_ACTIVE_MODELS_NO_RETRAIN")
            self.assertFalse(result["active_model_mutated"])
            self.assertFalse(result["task_decisions"][task]["calendar_cadence_can_retrain_active_model"])
            research.assert_not_called()

    def test_drift_alert_triggers_separate_after_market_research(self):
        task = "BSE_SWING_LONG_MTF"
        with tempfile.TemporaryDirectory() as tmp, \
            patch("backend.tradebrain.ml_adaptive_cycle.get_operating_mode", return_value={"mode": "POST_MARKET_STUDY"}), \
            patch("backend.tradebrain.ml_adaptive_cycle.latest_active_models", return_value=self._active(task)), \
            patch("backend.tradebrain.ml_adaptive_cycle.build_labeled_dataset", return_value=self._bundle(task)), \
            patch("backend.tradebrain.ml_adaptive_cycle.model_drift_report", return_value={"feature_drift": {"status": "DRIFT_ALERT"}, "shadow_performance": {"status": "STABLE"}}), \
            patch("backend.tradebrain.ml_adaptive_cycle.retraining_recommendation", return_value={"research_retrain_recommended": True, "verdict": "RESEARCH_RETRAIN_RECOMMENDED"}), \
            patch("backend.tradebrain.ml_adaptive_cycle.run_ml_research_cycle", return_value={"status": "SUCCESS"}) as research:
            result = run_adaptive_ml_cycle(
                "series:test",
                now=datetime.fromisoformat("2026-08-26T18:00:00+05:30"),
                tasks=(task,),
                state_path=Path(tmp) / "state.json",
            )
            self.assertEqual(result["status"], "RESEARCH_RETRAIN_TRIGGERED")
            self.assertEqual(result["drift_triggered_tasks"], [task])
            kwargs = research.call_args.kwargs
            self.assertTrue(kwargs["force"])
            self.assertEqual(kwargs["tasks"], (task,))
            self.assertFalse(result["active_model_mutated"])
            self.assertFalse(result["automatic_promotion"])

    def test_task_without_active_model_uses_bounded_discovery_cadence(self):
        task = "BSE_INTRADAY_LONG"
        with tempfile.TemporaryDirectory() as tmp, \
            patch("backend.tradebrain.ml_adaptive_cycle.get_operating_mode", return_value={"mode": "POST_MARKET_STUDY"}), \
            patch("backend.tradebrain.ml_adaptive_cycle.latest_active_models", return_value={}), \
            patch("backend.tradebrain.ml_adaptive_cycle.run_ml_research_cycle", return_value={"status": "SKIPPED_CADENCE"}) as research:
            result = run_adaptive_ml_cycle(
                "series:test",
                now=datetime.fromisoformat("2026-08-26T18:00:00+05:30"),
                tasks=(task,),
                cadence_days=7,
                state_path=Path(tmp) / "state.json",
            )
            self.assertEqual(result["discovery_tasks"], [task])
            kwargs = research.call_args.kwargs
            self.assertFalse(kwargs["force"])
            self.assertEqual(kwargs["cadence_days"], 7)
            self.assertTrue(result["task_decisions"][task]["calendar_cadence_allowed_for_discovery"])

    def test_market_session_never_starts_heavy_training(self):
        task = "BSE_INTRADAY_LONG"
        with patch("backend.tradebrain.ml_adaptive_cycle.get_operating_mode", return_value={"mode": "MARKET_SESSION"}), \
            patch("backend.tradebrain.ml_adaptive_cycle.run_ml_research_cycle") as research:
            result = run_adaptive_ml_cycle(
                "series:test",
                now=datetime.fromisoformat("2026-08-26T11:00:00+05:30"),
                tasks=(task,),
            )
            self.assertEqual(result["status"], "SKIPPED_NOT_TRAINING_TIME")
            self.assertFalse(result["heavy_training_during_market"])
            research.assert_not_called()


if __name__ == "__main__":
    unittest.main()
