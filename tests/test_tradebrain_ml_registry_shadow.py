from __future__ import annotations

import tempfile
import unittest

import numpy as np
import pandas as pd

from backend.tradebrain.ml_models import MODEL_DECISION_TREE, ModelSpec, fit_model
from backend.tradebrain.ml_optimizer import OptimizationResult
from backend.tradebrain.ml_registry import (
    STAGE_ELIGIBLE,
    enable_shadow,
    freeze_challenger,
    mark_historical_pass,
    mark_integration_eligible,
    register_optimization,
)


class MLRegistryShadowEvidenceTests(unittest.TestCase):
    @staticmethod
    def _result() -> OptimizationResult:
        rng = np.random.default_rng(42)
        n = 120
        frame = pd.DataFrame(
            {
                "return_1": rng.normal(size=n),
                "relative_volume_20": rng.normal(size=n),
                "label_net_positive": np.asarray([i % 2 for i in range(n)], dtype=int),
            }
        )
        spec = ModelSpec(MODEL_DECISION_TREE, {"max_depth": 3, "min_samples_leaf": 5})
        model = fit_model(
            frame,
            feature_columns=("return_1", "relative_volume_20"),
            spec=spec,
        )
        normal = {
            "trades": 120,
            "mean_net_return_pct": 0.20,
            "profit_factor": 1.60,
            "max_drawdown_pct": 10.0,
            "regime_expectancy_pct": {"HIGH_VOL": 0.2, "RANGE": 0.1},
        }
        stress15 = dict(normal, mean_net_return_pct=0.15, profit_factor=1.45)
        stress20 = dict(normal, mean_net_return_pct=0.10, profit_factor=1.35)
        walk_forward = [
            {"year": "2023", "normal": normal, "stress_15x": stress15, "stress_20x": stress20},
            {"year": "2024", "normal": normal, "stress_15x": stress15, "stress_20x": stress20},
        ]
        return OptimizationResult(
            status="OOS_PASS",
            task="BSE_SWING_LONG_MTF",
            model=model,
            feature_columns=("return_1", "relative_volume_20"),
            winner={
                "family": MODEL_DECISION_TREE,
                "params": {"max_depth": 3, "min_samples_leaf": 5},
                "threshold": 0.55,
                "validation": normal,
            },
            trials=[],
            oos_metrics=normal,
            oos_stress_15x=stress15,
            oos_stress_20x=stress20,
            walk_forward=walk_forward,
            metadata={
                "dataset_snapshot_hash": "registry-shadow-test",
                "method_version": "BSE_ML_OPTIMIZER_V1",
                "feature_method_version": "BSE_ML_FEATURES_V1",
                "rows": {"TRAIN": 1000, "VALIDATION": 300, "OOS": 120, "HOLDOUT": 0},
            },
        )

    def _shadow_stage(self, tmp: str):
        metadata = register_optimization(self._result(), code_version="unit-test", root=tmp)
        historical = mark_historical_pass(
            metadata["model_id"],
            promotion_quality={"passed": True, "verdict": "PROMOTION_QUALITY_PASS"},
            cpcv_robustness={"passed": True, "verdict": "CPCV_ROBUSTNESS_PASS"},
            root=tmp,
        )
        freeze_challenger(
            historical["model_id"],
            reason="unit-test review",
            human_approved=True,
            root=tmp,
        )
        enable_shadow(historical["model_id"], root=tmp)
        return metadata

    def test_human_approval_cannot_bypass_missing_shadow_buffer(self):
        with tempfile.TemporaryDirectory() as tmp:
            metadata = self._shadow_stage(tmp)
            with self.assertRaises(ValueError):
                mark_integration_eligible(
                    metadata["model_id"],
                    reason="should fail",
                    human_approved=True,
                    shadow_buffer_evidence={"passed": False},
                    root=tmp,
                )

    def test_mismatched_artifact_hash_fails_shadow_buffer(self):
        with tempfile.TemporaryDirectory() as tmp:
            metadata = self._shadow_stage(tmp)
            with self.assertRaises(ValueError):
                mark_integration_eligible(
                    metadata["model_id"],
                    reason="wrong artifact",
                    human_approved=True,
                    shadow_buffer_evidence={
                        "passed": True,
                        "continuous_trailing_market_sessions": 30,
                        "artifact_hashes_seen": ["different-hash"],
                    },
                    root=tmp,
                )

    def test_verified_30_session_same_artifact_buffer_can_reach_eligible_stage(self):
        with tempfile.TemporaryDirectory() as tmp:
            metadata = self._shadow_stage(tmp)
            eligible = mark_integration_eligible(
                metadata["model_id"],
                reason="30 verified prospective sessions completed",
                human_approved=True,
                shadow_buffer_evidence={
                    "passed": True,
                    "continuous_trailing_market_sessions": 30,
                    "artifact_hashes_seen": [metadata["model_sha256"]],
                },
                root=tmp,
            )
            self.assertEqual(eligible["stage"], STAGE_ELIGIBLE)
            self.assertFalse(eligible["advisory_weight_enabled"])
            self.assertFalse(eligible["trade_authorization"])
            self.assertFalse(eligible["order_execution_allowed"])


if __name__ == "__main__":
    unittest.main()
