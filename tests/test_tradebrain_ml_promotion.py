from __future__ import annotations

import unittest
from types import SimpleNamespace

from backend.tradebrain.ml_promotion import evaluate_historical_promotion


class MLPromotionQualityTests(unittest.TestCase):
    @staticmethod
    def _result(**overrides):
        normal = {
            "trades": 140,
            "max_drawdown_pct": 12.0,
            "mean_net_return_pct": 0.30,
            "profit_factor": 1.75,
            "regime_expectancy_pct": {
                "HIGH_VOL": 0.22,
                "TREND_UP": 0.35,
                "TREND_DOWN": 0.12,
                "RANGE": 0.18,
            },
        }
        stress20 = {
            "trades": 140,
            "max_drawdown_pct": 18.0,
            "mean_net_return_pct": 0.14,
            "profit_factor": 1.42,
        }
        walk_forward = [
            {
                "year": "2023",
                "normal": {"trades": 60},
                "stress_20x": {"mean_net_return_pct": 0.11, "profit_factor": 1.36},
            },
            {
                "year": "2024",
                "normal": {"trades": 70},
                "stress_20x": {"mean_net_return_pct": 0.09, "profit_factor": 1.33},
            },
        ]
        payload = {
            "status": "OOS_PASS",
            "oos_metrics": normal,
            "oos_stress_20x": stress20,
            "walk_forward": walk_forward,
        }
        payload.update(overrides)
        return SimpleNamespace(**payload)

    def test_strong_candidate_passes_hardened_gate(self):
        verdict = evaluate_historical_promotion(self._result())
        self.assertTrue(verdict["passed"])
        self.assertEqual(verdict["verdict"], "PROMOTION_QUALITY_PASS")
        self.assertFalse(verdict["automatic_promotion"])
        self.assertTrue(verdict["human_review_still_required"])
        self.assertFalse(verdict["trade_authorization"])
        self.assertFalse(verdict["order_execution_allowed"])
        self.assertFalse(verdict["holdout_used_for_threshold_tuning"])

    def test_swing_like_62_8_pct_drawdown_is_rejected(self):
        result = self._result()
        result.oos_metrics = dict(result.oos_metrics, max_drawdown_pct=62.8)
        verdict = evaluate_historical_promotion(result)
        self.assertFalse(verdict["passed"])
        self.assertIn("OOS_DRAWDOWN_ABOVE_25_PCT", verdict["failures"])

    def test_2x_profit_factor_below_1_30_is_rejected(self):
        result = self._result()
        result.oos_stress_20x = dict(result.oos_stress_20x, profit_factor=1.29)
        verdict = evaluate_historical_promotion(result)
        self.assertFalse(verdict["passed"])
        self.assertIn("OOS_2X_PROFIT_FACTOR_BELOW_1_30", verdict["failures"])

    def test_fewer_than_100_oos_trades_is_rejected(self):
        result = self._result()
        result.oos_metrics = dict(result.oos_metrics, trades=99)
        verdict = evaluate_historical_promotion(result)
        self.assertFalse(verdict["passed"])
        self.assertIn("OOS_SAMPLE_COUNT_BELOW_100", verdict["failures"])

    def test_any_observed_negative_regime_is_rejected(self):
        result = self._result()
        regimes = dict(result.oos_metrics["regime_expectancy_pct"])
        regimes["RANGE"] = -0.01
        result.oos_metrics = dict(result.oos_metrics, regime_expectancy_pct=regimes)
        verdict = evaluate_historical_promotion(result)
        self.assertFalse(verdict["passed"])
        self.assertIn("NON_POSITIVE_EXPECTANCY_IN_OBSERVED_REGIME", verdict["failures"])
        self.assertIn("RANGE", verdict["checks"]["non_positive_regimes"])

    def test_missing_regime_evidence_fails_closed(self):
        result = self._result()
        result.oos_metrics = dict(result.oos_metrics, regime_expectancy_pct={})
        verdict = evaluate_historical_promotion(result)
        self.assertFalse(verdict["passed"])
        self.assertIn("REGIME_EVIDENCE_MISSING", verdict["failures"])

    def test_weak_walk_forward_block_is_rejected(self):
        result = self._result()
        result.walk_forward = [
            result.walk_forward[0],
            {
                "year": "2024",
                "normal": {"trades": 70},
                "stress_20x": {"mean_net_return_pct": 0.03, "profit_factor": 1.18},
            },
        ]
        verdict = evaluate_historical_promotion(result)
        self.assertFalse(verdict["passed"])
        self.assertIn("WALK_FORWARD_BLOCK_FAILS_2X_FRICTION_GATE", verdict["failures"])
        self.assertIn("2024", verdict["checks"]["weak_walk_forward_blocks"])

    def test_non_oos_pass_cannot_be_promoted(self):
        verdict = evaluate_historical_promotion(self._result(status="OOS_REJECTED"))
        self.assertFalse(verdict["passed"])
        self.assertIn("OPTIMIZER_DID_NOT_PASS_OOS", verdict["failures"])


if __name__ == "__main__":
    unittest.main()
