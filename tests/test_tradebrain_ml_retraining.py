from __future__ import annotations

import unittest

from backend.tradebrain.ml_retraining import retraining_recommendation


class MLRetrainingTriggerTests(unittest.TestCase):
    def test_stable_model_stays_frozen(self):
        verdict = retraining_recommendation(
            feature_drift={"status": "STABLE"},
            shadow_performance={"status": "STABLE", "alerts": []},
            operating_mode="POST_MARKET_STUDY",
        )
        self.assertEqual(verdict["verdict"], "KEEP_FROZEN_MODEL_NO_RETRAIN")
        self.assertFalse(verdict["research_retrain_recommended"])
        self.assertFalse(verdict["current_model_mutated"])

    def test_feature_drift_recommends_research_retrain_after_market(self):
        verdict = retraining_recommendation(
            feature_drift={"status": "DRIFT_ALERT"},
            shadow_performance={"status": "STABLE", "alerts": []},
            operating_mode="POST_MARKET_STUDY",
        )
        self.assertTrue(verdict["research_retrain_recommended"])
        self.assertIn("FEATURE_DRIFT_ALERT", verdict["hard_trigger_reasons"])

    def test_calibration_drift_recommends_research_retrain(self):
        verdict = retraining_recommendation(
            feature_drift={"status": "STABLE"},
            shadow_performance={"status": "DRIFT_ALERT", "alerts": ["CALIBRATION_DRIFT"]},
            operating_mode="POST_MARKET_STUDY",
        )
        self.assertTrue(verdict["research_retrain_recommended"])
        self.assertIn("CALIBRATION_DRIFT", verdict["hard_trigger_reasons"])

    def test_market_hours_defer_retraining_even_on_drift(self):
        verdict = retraining_recommendation(
            feature_drift={"status": "DRIFT_ALERT"},
            shadow_performance={"status": "DRIFT_ALERT", "alerts": ["EXPECTANCY_DEGRADATION"]},
            operating_mode="MARKET_SESSION",
        )
        self.assertEqual(verdict["verdict"], "DEFER_RETRAIN_UNTIL_AFTER_MARKET")
        self.assertTrue(verdict["trigger_detected"])
        self.assertFalse(verdict["research_retrain_recommended"])
        self.assertFalse(verdict["trade_authorization"])
        self.assertFalse(verdict["order_execution_allowed"])

    def test_single_watch_does_not_retrain(self):
        verdict = retraining_recommendation(
            feature_drift={"status": "WATCH"},
            shadow_performance={"status": "STABLE", "alerts": []},
            operating_mode="POST_MARKET_STUDY",
            consecutive_watch_sessions=1,
        )
        self.assertFalse(verdict["research_retrain_recommended"])

    def test_persistent_watch_can_trigger_after_market_research(self):
        verdict = retraining_recommendation(
            feature_drift={"status": "WATCH"},
            shadow_performance={"status": "WATCH", "alerts": []},
            operating_mode="POST_MARKET_STUDY",
            consecutive_watch_sessions=5,
        )
        self.assertTrue(verdict["research_retrain_recommended"])
        self.assertIn("PERSISTENT_DRIFT_WATCH", verdict["hard_trigger_reasons"])


if __name__ == "__main__":
    unittest.main()
