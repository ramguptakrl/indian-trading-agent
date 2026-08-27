from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from backend.tradebrain.ml_features import FeatureBundle
from backend.tradebrain.ml_replay import (
    ReplayConfig,
    ReplayModelSpec,
    eligible_news_as_of,
    matured_training_frame,
    prequential_replay,
)


class MLHistoricalReplaySafetyTests(unittest.TestCase):
    @staticmethod
    def _bundle() -> FeatureBundle:
        rng = np.random.default_rng(20260826)
        seed = pd.date_range("2024-01-02 09:15", periods=80, freq="B", tz="Asia/Kolkata")
        rows = []
        for day in seed:
            for minute in (0, 15):
                ts_open = day + pd.Timedelta(minutes=minute)
                ts_close = ts_open + pd.Timedelta(minutes=15)
                feature_a = float(rng.normal())
                feature_b = float(rng.normal())
                label = int(feature_a + 0.4 * feature_b > 0.0)
                gross = 0.6 if label else -0.4
                rows.append({
                    "ts_open": ts_open.tz_convert("UTC"),
                    "ts_close": ts_close.tz_convert("UTC"),
                    "label_end": (day + pd.Timedelta(hours=7)).tz_convert("UTC"),
                    "label_net_positive": label,
                    "label_net_return_pct": gross - 0.05,
                    "label_gross_return_pct": gross,
                    "return_1": feature_a,
                    "macd_hist": feature_b,
                })
        frame = pd.DataFrame(rows)
        return FeatureBundle(frame=frame, feature_columns=("return_1", "macd_hist"), metadata={"task": "BSE_INTRADAY_LONG"})

    @staticmethod
    def _model_spec() -> ReplayModelSpec:
        return ReplayModelSpec(
            task="BSE_INTRADAY_LONG",
            family="DECISION_TREE",
            params={"max_depth": 4, "min_samples_leaf": 5},
            feature_columns=("return_1", "macd_hist"),
            threshold=0.55,
        )

    def test_matured_training_frame_excludes_future_outcomes(self):
        frame = pd.DataFrame({
            "ts_close": pd.to_datetime(["2026-01-01T10:00:00Z", "2026-01-02T10:00:00Z", "2026-01-03T10:00:00Z"]),
            "label_end": pd.to_datetime(["2026-01-01T11:00:00Z", "2026-01-05T10:00:00Z", "2026-01-03T11:00:00Z"]),
            "label_net_positive": [1, 0, 1],
        })
        matured = matured_training_frame(frame, decision_at="2026-01-04T00:00:00Z")
        self.assertEqual(len(matured), 2)
        self.assertTrue((pd.to_datetime(matured["label_end"], utc=True) <= pd.Timestamp("2026-01-04T00:00:00Z")).all())

    def test_historical_news_filter_excludes_future_unverified_and_missing_times(self):
        news = pd.DataFrame({
            "headline": ["known", "future", "unverified", "missing"],
            "published_at": ["2026-01-02T09:00:00Z", "2026-01-02T11:01:00Z", "2026-01-02T09:30:00Z", None],
            "available_at": ["2026-01-02T09:01:00Z", "2026-01-02T11:01:00Z", "2026-01-02T09:31:00Z", None],
            "timestamp_verified": [True, True, False, True],
        })
        allowed = eligible_news_as_of(news, decision_at="2026-01-02T11:00:00Z")
        self.assertEqual(allowed["headline"].tolist(), ["known"])

    def test_blind_daily_refit_requires_explicit_research_opt_in(self):
        with self.assertRaises(ValueError):
            ReplayConfig(start="2024-03-01T00:00:00Z", end="2024-04-01T00:00:00Z", retrain_every_sessions=1).validate()
        ReplayConfig(
            start="2024-03-01T00:00:00Z",
            end="2024-04-01T00:00:00Z",
            retrain_every_sessions=1,
            allow_daily_refit_research=True,
        ).validate()

    def test_frozen_replay_fits_once_and_never_uses_future_labels(self):
        result = prequential_replay(
            self._bundle(),
            model_spec=self._model_spec(),
            config=ReplayConfig(
                start="2024-03-01T00:00:00Z",
                end="2024-04-15T00:00:00Z",
                min_train_rows=20,
                retrain_every_sessions=0,
            ),
        )
        self.assertEqual(result["status"], "SUCCESS")
        self.assertEqual(len(result["model_fit_events"]), 1)
        self.assertTrue(all(not item["future_label_used"] for item in result["model_fit_events"]))
        self.assertTrue(result["intraday_model_frozen_within_session"])
        self.assertFalse(result["blind_daily_refit_default"])
        self.assertFalse(result["news_used"])
        self.assertFalse(result["automatic_model_promotion"])
        self.assertFalse(result["trade_authorization"])
        self.assertFalse(result["order_execution_allowed"])

    def test_scheduled_intraday_replay_refits_only_at_session_boundaries(self):
        result = prequential_replay(
            self._bundle(),
            model_spec=self._model_spec(),
            config=ReplayConfig(
                start="2024-03-01T00:00:00Z",
                end="2024-04-15T00:00:00Z",
                min_train_rows=20,
                retrain_every_sessions=5,
            ),
        )
        self.assertEqual(result["status"], "SUCCESS")
        fit_sessions = [item["session"] for item in result["model_fit_events"]]
        self.assertEqual(len(fit_sessions), len(set(fit_sessions)))
        self.assertTrue(all(not item["future_label_used"] for item in result["model_fit_events"]))
        prediction_sessions = {}
        for item in result["predictions"]:
            prediction_sessions.setdefault(item["session"], set()).add(item["decision_at"])
        self.assertTrue(all(len(values) == 1 for values in prediction_sessions.values()))


if __name__ == "__main__":
    unittest.main()
