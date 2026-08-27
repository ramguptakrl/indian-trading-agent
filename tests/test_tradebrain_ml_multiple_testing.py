from __future__ import annotations

import unittest

import numpy as np

from backend.tradebrain.ml_multiple_testing import (
    deflated_sharpe_ratio,
    expected_max_sharpe,
    probability_backtest_overfitting,
    probabilistic_sharpe_ratio,
    trade_sharpe,
)


class MLMultipleTestingTests(unittest.TestCase):
    def test_probabilistic_sharpe_rewards_persistent_positive_returns(self):
        returns = np.asarray([0.30, 0.20, 0.35, -0.05, 0.25, 0.18] * 12, dtype=float)
        report = probabilistic_sharpe_ratio(returns, benchmark_sharpe=0.0)
        self.assertGreater(report["sharpe"], 0.0)
        self.assertGreater(report["probability"], 0.95)
        self.assertEqual(report["observations"], len(returns))

    def test_expected_max_sharpe_rises_with_multiple_testing_burden(self):
        trial_sharpes = [-0.10, 0.00, 0.05, 0.08, 0.12, 0.15]
        small = expected_max_sharpe(trial_sharpes, effective_trials=6)
        large = expected_max_sharpe(trial_sharpes, effective_trials=200)
        self.assertGreater(
            large["expected_max_sharpe_under_null"],
            small["expected_max_sharpe_under_null"],
        )

    def test_dsr_can_reject_apparently_positive_but_weak_candidate_after_many_trials(self):
        rng = np.random.default_rng(1729)
        selected = rng.normal(loc=0.015, scale=0.20, size=60)
        trial_sharpes = rng.normal(loc=0.0, scale=0.12, size=80)
        report = deflated_sharpe_ratio(
            selected,
            trial_sharpes,
            effective_trials=500,
        )
        self.assertFalse(report["passed"])
        self.assertEqual(report["verdict"], "DSR_REJECTED")
        self.assertGreater(report["multiple_trial_null"]["effective_trials"], 80)

    def test_pbo_detects_in_sample_winner_that_fails_out_of_sample(self):
        # Strategy A is made to win every IS fold but is deliberately the worst OOS strategy.
        ins = np.asarray([
            [3.0, 2.0, 1.0],
            [3.1, 2.1, 1.1],
            [3.2, 2.2, 1.2],
            [3.3, 2.3, 1.3],
            [3.4, 2.4, 1.4],
            [3.5, 2.5, 1.5],
        ])
        outs = np.asarray([
            [0.1, 0.5, 0.7],
            [0.1, 0.6, 0.8],
            [0.2, 0.5, 0.9],
            [0.1, 0.7, 0.8],
            [0.2, 0.6, 0.7],
            [0.1, 0.5, 0.8],
        ])
        report = probability_backtest_overfitting(ins, outs, strategy_ids=["A", "B", "C"])
        self.assertGreater(report["pbo"], 0.50)
        self.assertFalse(report["passed"])
        self.assertTrue(all(row["best_is_strategy"] == "A" for row in report["rows"]))

    def test_pbo_accepts_stable_winner_matrix(self):
        ins = np.asarray([
            [3.0, 2.0, 1.0],
            [3.1, 2.1, 1.1],
            [3.2, 2.2, 1.2],
            [3.3, 2.3, 1.3],
            [3.4, 2.4, 1.4],
            [3.5, 2.5, 1.5],
        ])
        outs = np.asarray([
            [0.9, 0.5, 0.2],
            [1.0, 0.6, 0.3],
            [0.8, 0.5, 0.1],
            [0.9, 0.7, 0.2],
            [1.1, 0.6, 0.3],
            [0.9, 0.5, 0.2],
        ])
        report = probability_backtest_overfitting(ins, outs, strategy_ids=["A", "B", "C"])
        self.assertEqual(report["pbo"], 0.0)
        self.assertTrue(report["passed"])

    def test_trade_sharpe_is_unannualized_and_deterministic(self):
        values = [1.0, -0.5, 0.5, 1.5, -0.2]
        first = trade_sharpe(values)
        second = trade_sharpe(values)
        self.assertAlmostEqual(first, second, places=15)


if __name__ == "__main__":
    unittest.main()
