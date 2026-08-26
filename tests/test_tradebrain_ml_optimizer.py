from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from backend.tradebrain.ml_features import FeatureBundle
from backend.tradebrain.ml_models import MODEL_FAMILIES, default_model_specs
from backend.tradebrain.ml_optimizer import OptimizerConfig, optimize_labeled_dataset
from backend.tradebrain.ml_registry import (
    STAGE_FROZEN,
    STAGE_HISTORICAL_PASS,
    STAGE_RESEARCH,
    STAGE_SHADOW,
    enable_shadow,
    freeze_challenger,
    load_model,
    mark_historical_pass,
    register_optimization,
)
from backend.tradebrain.ml_shadow import shadow_infer


class MLOptimizerSafetyTests(unittest.TestCase):
    @staticmethod
    def _bundle() -> FeatureBundle:
        rng = np.random.default_rng(12345)
        dates = pd.date_range("2017-01-02", "2026-08-20", freq="2D", tz="UTC")
        n = len(dates)
        trend = rng.normal(size=n)
        momentum = rng.normal(size=n)
        volume = rng.normal(size=n)
        latent = 1.3 * trend - 0.8 * momentum + 0.35 * volume + rng.normal(scale=0.65, size=n)
        labels = (latent > 0.0).astype(int)
        gross = np.where(labels == 1, 0.85, -0.52) + rng.normal(scale=0.06, size=n)
        net = gross - 0.08
        frame = pd.DataFrame(
            {
                "ts_open": dates - pd.Timedelta(minutes=15),
                "ts_close": dates,
                "label_end": dates + pd.Timedelta(hours=2),
                "label_net_positive": labels,
                "label_net_return_pct": net,
                "label_gross_return_pct": gross,
                "return_1": trend,
                "macd_hist": momentum,
                "relative_volume_20": volume,
            }
        )
        return FeatureBundle(
            frame=frame,
            feature_columns=("return_1", "macd_hist", "relative_volume_20"),
            metadata={
                "task": "BSE_INTRADAY_LONG",
                "dataset_snapshot_hash": "synthetic-dataset-v1",
                "method_version": "BSE_ML_FEATURES_V1",
                "label_method_version": "BSE_ML_LABELS_V1",
                "label_spec": {"slippage_bps": 5.0},
                "cost_profile_key": "TEST_COST_PROFILE",
                "mtf_profile_key": None,
            },
        )

    def _optimize(self):
        return optimize_labeled_dataset(
            self._bundle(),
            config=OptimizerConfig(
                thresholds=(0.50, 0.55),
                min_validation_trades=20,
                min_oos_trades=10,
                random_state=1729,
                deep_search=False,
            ),
        )

    def test_required_five_baseline_model_families_are_present(self):
        families = {spec.family for spec in default_model_specs()}
        self.assertEqual(families, set(MODEL_FAMILIES))
        self.assertEqual(len(MODEL_FAMILIES), 5)

    def test_optimizer_uses_validation_for_selection_and_keeps_holdout_unseen(self):
        result = self._optimize()
        self.assertEqual(result.status, "OOS_PASS")
        self.assertTrue(result.trials)
        self.assertTrue(all(trial.get("holdout_used") is False for trial in result.trials if "holdout_used" in trial))
        self.assertFalse(result.metadata["holdout_evaluated"])
        self.assertFalse(result.metadata["oos_used_for_hyperparameter_selection"])
        self.assertGreater(result.metadata["holdout_rows_unseen"], 0)
        self.assertGreater(result.oos_metrics["trades"], 0)
        self.assertGreater(result.oos_stress_15x["mean_net_return_pct"], 0.0)
        self.assertGreater(result.oos_stress_20x["mean_net_return_pct"], 0.0)

    def test_optimizer_is_reproducible_with_fixed_seed(self):
        first = self._optimize()
        second = self._optimize()
        self.assertEqual(first.status, second.status)
        self.assertEqual(first.winner["family"], second.winner["family"])
        self.assertEqual(first.winner["params"], second.winner["params"])
        self.assertEqual(first.winner["threshold"], second.winner["threshold"])
        self.assertAlmostEqual(
            first.oos_metrics["mean_net_return_pct"],
            second.oos_metrics["mean_net_return_pct"],
            places=12,
        )

    def test_registry_blocks_self_promotion_and_shadow_remains_non_executing(self):
        result = self._optimize()
        with tempfile.TemporaryDirectory() as tmp:
            metadata = register_optimization(result, code_version="unit-test", root=tmp)
            self.assertEqual(metadata["stage"], STAGE_RESEARCH)
            self.assertFalse(metadata["advisory_weight_enabled"])
            self.assertFalse(metadata["order_execution_allowed"])

            with self.assertRaises(ValueError):
                freeze_challenger(
                    metadata["model_id"],
                    reason="skip required historical stage",
                    human_approved=True,
                    root=tmp,
                )

            historical = mark_historical_pass(metadata["model_id"], root=tmp)
            self.assertEqual(historical["stage"], STAGE_HISTORICAL_PASS)
            with self.assertRaises(PermissionError):
                freeze_challenger(
                    metadata["model_id"],
                    reason="approval deliberately absent",
                    human_approved=False,
                    root=tmp,
                )

            frozen = freeze_challenger(
                metadata["model_id"],
                reason="unit-test human review",
                human_approved=True,
                root=tmp,
            )
            self.assertEqual(frozen["stage"], STAGE_FROZEN)
            shadow = enable_shadow(metadata["model_id"], root=tmp)
            self.assertEqual(shadow["stage"], STAGE_SHADOW)

            evidence = shadow_infer(
                metadata["model_id"],
                self._bundle(),
                registry_root=tmp,
                persist=False,
            )
            self.assertEqual(evidence["model_status"], STAGE_SHADOW)
            self.assertTrue(evidence["shadow_only"])
            self.assertFalse(evidence["advisory_weight_applied"])
            self.assertFalse(evidence["trade_authorization"])
            self.assertFalse(evidence["order_execution_allowed"])

    def test_registry_fails_closed_on_tampered_model_payload(self):
        result = self._optimize()
        with tempfile.TemporaryDirectory() as tmp:
            metadata = register_optimization(result, code_version="unit-test", root=tmp)
            model_path = Path(tmp) / metadata["model_id"] / "model.joblib"
            with model_path.open("ab") as handle:
                handle.write(b"TAMPER")
            with self.assertRaises(ValueError):
                load_model(metadata["model_id"], root=tmp)


if __name__ == "__main__":
    unittest.main()
