from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from backend.tradebrain.ml_challenger_tournament import (
    ChallengerTournamentConfig,
    VARIANTS,
    run_intraday_challenger_tournament,
)
from backend.tradebrain.ml_features import FeatureBundle


class MLIntradayChallengerTournamentTests(unittest.TestCase):
    @staticmethod
    def _bundle(task: str = "BSE_INTRADAY_LONG") -> FeatureBundle:
        rng = np.random.default_rng(20260827)
        dates = pd.date_range("2017-01-02", "2026-08-20", freq="2D", tz="UTC")
        n = len(dates)
        signal = rng.normal(size=n)
        context = rng.normal(size=n)
        latent = 1.4 * signal + 0.6 * context + rng.normal(scale=0.45, size=n)
        y = (latent > 0.0).astype(int)
        gross = np.where(y == 1, 0.90, -0.55)
        net = gross - 0.06
        frame = pd.DataFrame(
            {
                "ts_open": dates - pd.Timedelta(minutes=15),
                "ts_close": dates,
                "label_end": dates + pd.Timedelta(hours=2),
                "label_net_positive": y,
                "label_gross_return_pct": gross,
                "label_net_return_pct": net,
                "return_1": signal,
                "macd_hist": context,
                "mtf_alignment_score": signal + 0.1 * rng.normal(size=n),
                "mtf_daily_trend": rng.normal(size=n),
                "mtf_4h_trend": rng.normal(size=n),
                "mtf_1h_trend": rng.normal(size=n),
                "relative_volume_20": 1.0 + np.abs(context),
                "natr_14_pct": rng.uniform(0.2, 3.0, size=n),
                "vwap_distance_pct": signal * 0.7 + rng.normal(scale=0.4, size=n),
                "opening_range_position": rng.uniform(0.0, 1.0, size=n),
                "distance_prev_high_pct": rng.normal(size=n),
                "distance_prev_low_pct": rng.normal(size=n),
                "gap_pct": rng.normal(scale=0.7, size=n),
                "adx_14": rng.uniform(5.0, 45.0, size=n),
                "dmi_spread": context * 10.0 + rng.normal(size=n),
                "rsi_14": rng.uniform(10.0, 90.0, size=n),
            }
        )
        features = tuple(
            c
            for c in frame.columns
            if c not in {
                "ts_open",
                "ts_close",
                "label_end",
                "label_net_positive",
                "label_gross_return_pct",
                "label_net_return_pct",
            }
        )
        return FeatureBundle(
            frame=frame,
            feature_columns=features,
            metadata={"task": task, "dataset_snapshot_hash": "tournament-synthetic"},
        )

    def test_tournament_selects_globally_on_validation_and_opens_only_one_oos_configuration(self):
        result = run_intraday_challenger_tournament(
            self._bundle(),
            config=ChallengerTournamentConfig(
                thresholds=(0.50,),
                min_validation_trades=20,
                min_oos_trades=10,
                deep_search=False,
                random_state=1729,
            ),
        )
        self.assertIn(result["status"], {"OOS_PASS", "OOS_REJECTED"})
        self.assertIn(result["winner"]["variant"], VARIANTS)
        self.assertEqual(result["global_variant_selection_period"], "VALIDATION_ONLY")
        self.assertEqual(result["oos_configurations_evaluated"], 1)
        self.assertFalse(result["oos_used_for_variant_selection"])
        self.assertFalse(result["holdout_evaluated"])
        self.assertGreater(result["holdout_rows_unseen"], 0)
        self.assertTrue(result["prospective_shadow_required_for_clean_final_proof"])
        self.assertFalse(result["automatic_registration"])
        self.assertFalse(result["automatic_promotion"])
        self.assertFalse(result["trade_authorization"])
        self.assertFalse(result["order_execution_allowed"])

    def test_every_search_trial_is_validation_only(self):
        result = run_intraday_challenger_tournament(
            self._bundle(task="BSE_INTRADAY_SHORT"),
            config=ChallengerTournamentConfig(
                thresholds=(0.50,),
                min_validation_trades=20,
                min_oos_trades=10,
                deep_search=False,
            ),
        )
        self.assertTrue(result["trials"])
        for trial in result["trials"]:
            self.assertEqual(trial["selection_period"], "VALIDATION_ONLY")
            self.assertFalse(trial["oos_used"])
            self.assertFalse(trial["holdout_used"])

    def test_swing_task_cannot_enter_intraday_tournament(self):
        with self.assertRaises(ValueError):
            run_intraday_challenger_tournament(self._bundle(task="BSE_SWING_LONG_MTF"))


if __name__ == "__main__":
    unittest.main()
