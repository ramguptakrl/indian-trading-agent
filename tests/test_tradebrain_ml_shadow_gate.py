from __future__ import annotations

import unittest

from backend.tradebrain.ml_shadow_gate import evaluate_shadow_buffer


class MLShadowBufferTests(unittest.TestCase):
    @staticmethod
    def _sessions(count: int = 35):
        import pandas as pd

        return [d.date().isoformat() for d in pd.bdate_range("2026-09-01", periods=count)]

    @classmethod
    def _predictions(cls, count: int = 30, *, model_hash: str = "abc123"):
        sessions = cls._sessions(max(35, count))
        return [
            {
                "model_id": "BSE_SWING_LONG_MTF_TEST",
                "model_sha256": model_hash,
                "shadow_session_ist": day,
                "as_of": f"{day}T10:00:00+05:30",
                "retuned_during_shadow_session": False,
            }
            for day in sessions[-count:]
        ]

    def test_30_continuous_verified_sessions_pass(self):
        verdict = evaluate_shadow_buffer(
            self._predictions(30),
            model_id="BSE_SWING_LONG_MTF_TEST",
            verified_market_sessions=self._sessions(35),
        )
        self.assertTrue(verdict["passed"])
        self.assertEqual(verdict["continuous_trailing_market_sessions"], 30)
        self.assertFalse(verdict["automatic_promotion"])
        self.assertTrue(verdict["human_review_still_required"])
        self.assertFalse(verdict["trade_authorization"])
        self.assertFalse(verdict["order_execution_allowed"])

    def test_29_sessions_fail(self):
        verdict = evaluate_shadow_buffer(
            self._predictions(29),
            model_id="BSE_SWING_LONG_MTF_TEST",
            verified_market_sessions=self._sessions(35),
        )
        self.assertFalse(verdict["passed"])
        self.assertIn("SHADOW_BUFFER_BELOW_30_CONTINUOUS_MARKET_SESSIONS", verdict["failures"])

    def test_missing_middle_market_session_resets_trailing_streak(self):
        expected = self._sessions(35)
        rows = self._predictions(30)
        missing = expected[-8]
        rows = [row for row in rows if row["shadow_session_ist"] != missing]
        verdict = evaluate_shadow_buffer(
            rows,
            model_id="BSE_SWING_LONG_MTF_TEST",
            verified_market_sessions=expected,
        )
        self.assertFalse(verdict["passed"])
        self.assertLess(verdict["continuous_trailing_market_sessions"], 30)

    def test_artifact_hash_change_fails_zero_retune_rule(self):
        rows = self._predictions(30)
        rows[-1] = dict(rows[-1], model_sha256="different")
        verdict = evaluate_shadow_buffer(
            rows,
            model_id="BSE_SWING_LONG_MTF_TEST",
            verified_market_sessions=self._sessions(35),
        )
        self.assertFalse(verdict["passed"])
        self.assertIn("SHADOW_ARTIFACT_CHANGED_OR_RETUNED", verdict["failures"])

    def test_explicit_retune_marker_fails(self):
        rows = self._predictions(30)
        rows[-5] = dict(rows[-5], retuned_during_shadow_session=True)
        verdict = evaluate_shadow_buffer(
            rows,
            model_id="BSE_SWING_LONG_MTF_TEST",
            verified_market_sessions=self._sessions(35),
        )
        self.assertFalse(verdict["passed"])
        self.assertIn("RETUNE_OCCURRED_DURING_SHADOW_BUFFER", verdict["failures"])

    def test_verified_calendar_is_mandatory(self):
        verdict = evaluate_shadow_buffer(
            self._predictions(30),
            model_id="BSE_SWING_LONG_MTF_TEST",
            verified_market_sessions=[],
        )
        self.assertFalse(verdict["passed"])
        self.assertIn("VERIFIED_MARKET_SESSION_CALENDAR_REQUIRED", verdict["failures"])


if __name__ == "__main__":
    unittest.main()
