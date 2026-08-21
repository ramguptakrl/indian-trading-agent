import os
import tempfile
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from backend.tradebrain.challenger_store import activate_soft_parameter, ensure_challenger_schema
from backend.tradebrain.policy import TradePlan, evaluate_trade_plan
from backend.tradebrain.soft_runtime import effective_reward_risk_preference

IST = ZoneInfo("Asia/Kolkata")


class Phase7SoftRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp.name, "phase7.db")
        ensure_challenger_schema(self.db_path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_default_preference_is_used_without_promoted_version(self):
        result = effective_reward_risk_preference("INTRADAY", db_path=self.db_path)
        self.assertEqual(result["value"], 1.0)
        self.assertEqual(result["source"], "DEFAULT_SOFT_PREFERENCE")
        self.assertFalse(result["registry_applied"])

    def test_human_approved_active_version_becomes_runtime_soft_preference(self):
        activate_soft_parameter(
            parameter_key="day_min_reward_risk",
            parameter_scope="DAY",
            value=1.25,
            source_experiment_id=None,
            approved_by="phase7-test-human",
            approval_note="Explicit reviewed promotion for test",
            db_path=self.db_path,
        )
        result = effective_reward_risk_preference("INTRADAY", db_path=self.db_path)
        self.assertEqual(result["value"], 1.25)
        self.assertEqual(result["source"], "HUMAN_APPROVED_SOFT_REGISTRY")
        self.assertEqual(result["version"], 1)
        self.assertTrue(result["registry_applied"])
        self.assertFalse(result["hard_policy_mutated"])

    def test_policy_exposes_soft_registry_provenance_and_waits_below_it(self):
        activate_soft_parameter(
            parameter_key="day_min_reward_risk",
            parameter_scope="DAY",
            value=1.25,
            source_experiment_id=None,
            approved_by="phase7-test-human",
            approval_note="Explicit reviewed promotion for test",
            db_path=self.db_path,
        )
        plan = TradePlan(
            ticker="BSE", mode="INTRADAY", direction="LONG",
            entry=100.0, stop_loss=99.0, take_profit=101.1,
            evidence=["phase7:test"],
            evaluated_at_ist=datetime(2026, 8, 21, 12, 0, tzinfo=IST),
        )
        result = evaluate_trade_plan(plan, db_path=self.db_path)
        self.assertTrue(result.allowed_for_advisory)
        self.assertEqual(result.action, "WAIT")
        self.assertAlmostEqual(result.preferred_reward_risk, 1.25)
        self.assertEqual(result.preferred_reward_risk_source, "HUMAN_APPROVED_SOFT_REGISTRY")
        self.assertEqual(result.soft_parameter_version, 1)
        self.assertTrue(result.soft_parameter_registry_applied)

    def test_new_activation_retires_prior_version(self):
        first = activate_soft_parameter(
            parameter_key="swing_min_reward_risk", parameter_scope="SWING_POSITION",
            value=3.0, source_experiment_id=None, approved_by="human-a",
            approval_note="first", db_path=self.db_path,
        )
        second = activate_soft_parameter(
            parameter_key="swing_min_reward_risk", parameter_scope="SWING_POSITION",
            value=2.75, source_experiment_id=None, approved_by="human-b",
            approval_note="second", db_path=self.db_path,
        )
        result = effective_reward_risk_preference("SWING", db_path=self.db_path)
        self.assertEqual(first["version"], 1)
        self.assertEqual(second["version"], 2)
        self.assertEqual(result["version"], 2)
        self.assertEqual(result["value"], 2.75)


if __name__ == "__main__":
    unittest.main()
