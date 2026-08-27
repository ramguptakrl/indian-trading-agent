from __future__ import annotations

import unittest

import numpy as np

from backend.tradebrain.ml_bootstrap_confidence import (
    BootstrapConfig,
    bootstrap_promotion_verdict,
    stationary_bootstrap_confidence,
    stationary_bootstrap_indices,
)


class MLBootstrapConfidenceTests(unittest.TestCase):
    def test_stationary_bootstrap_indices_are_reproducible_and_valid(self):
        first = stationary_bootstrap_indices(
            25,
            n_resamples=20,
            mean_block_length=5.0,
            random_state=1729,
        )
        second = stationary_bootstrap_indices(
            25,
            n_resamples=20,
            mean_block_length=5.0,
            random_state=1729,
        )
        np.testing.assert_array_equal(first, second)
        self.assertEqual(first.shape, (20, 25))
        self.assertTrue(np.all(first >= 0))
        self.assertTrue(np.all(first < 25))

    def test_strong_dependent_trade_sequence_clears_confidence_gate(self):
        # Contiguous five-trade blocks deliberately repeat to preserve dependence structure.
        returns = np.asarray(([0.35, 0.28, 0.31, 0.22, -0.08] * 32), dtype=float)
        report = stationary_bootstrap_confidence(
            returns,
            config=BootstrapConfig(
                n_resamples=700,
                mean_block_length=6.0,
                confidence_level=0.95,
                min_trades=100,
                random_state=99,
            ),
        )
        verdict = bootstrap_promotion_verdict(report)
        self.assertEqual(report["status"], "OK")
        self.assertTrue(verdict["passed"])
        self.assertGreater(verdict["checks"]["profit_factor_95_lower"], 1.0)
        self.assertGreater(verdict["checks"]["expectancy_95_lower_pct"], 0.0)
        self.assertLessEqual(verdict["checks"]["max_drawdown_95_upper_pct"], 25.0)
        self.assertFalse(verdict["trade_authorization"])
        self.assertFalse(verdict["order_execution_allowed"])

    def test_weak_edge_is_rejected_by_uncertainty_even_if_point_mean_is_positive(self):
        rng = np.random.default_rng(7)
        returns = rng.normal(loc=0.006, scale=0.22, size=160)
        report = stationary_bootstrap_confidence(
            returns,
            config=BootstrapConfig(
                n_resamples=700,
                mean_block_length=8.0,
                confidence_level=0.95,
                min_trades=100,
                random_state=7,
            ),
        )
        verdict = bootstrap_promotion_verdict(report)
        self.assertFalse(verdict["passed"])
        self.assertTrue(
            "BOOTSTRAP_95_PF_LOWER_NOT_ABOVE_1" in verdict["failures"]
            or "BOOTSTRAP_95_EXPECTANCY_LOWER_NOT_POSITIVE" in verdict["failures"]
        )

    def test_insufficient_trades_fail_closed(self):
        report = stationary_bootstrap_confidence(
            [0.2] * 99,
            config=BootstrapConfig(n_resamples=500, min_trades=100),
        )
        verdict = bootstrap_promotion_verdict(report)
        self.assertEqual(report["status"], "INSUFFICIENT_TRADES")
        self.assertFalse(verdict["passed"])
        self.assertIn("BOOTSTRAP_CONFIDENCE_NOT_AVAILABLE", verdict["failures"])


if __name__ == "__main__":
    unittest.main()
