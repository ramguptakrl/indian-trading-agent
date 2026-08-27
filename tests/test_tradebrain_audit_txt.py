from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from backend.tradebrain.audit_txt import append_audit_record, audit_final_advisory


class TradeBrainAuditTxtTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.previous = os.environ.get("TRADEBRAIN_AUDIT_DIR")
        os.environ["TRADEBRAIN_AUDIT_DIR"] = self.temp.name

    def tearDown(self):
        if self.previous is None:
            os.environ.pop("TRADEBRAIN_AUDIT_DIR", None)
        else:
            os.environ["TRADEBRAIN_AUDIT_DIR"] = self.previous
        self.temp.cleanup()

    def _read_only_audit(self) -> str:
        files = list(Path(self.temp.name).glob("*.txt"))
        self.assertEqual(len(files), 1)
        return files[0].read_text(encoding="utf-8")

    def test_append_audit_redacts_nested_credentials(self):
        path = append_audit_record(
            category="TEST",
            event="SECRET_REDACTION",
            payload={
                "KITE_API_KEY": "public-ish-key-but-still-redact",
                "nested": {
                    "KITE_API_SECRET": "do-not-write-me",
                    "access_token": "daily-secret-token",
                    "safe": "BSE",
                },
            },
            rationale_summary="Credential safety test.",
            interpretation="The text audit must remain useful without persisting secrets.",
        )
        self.assertTrue(Path(path).exists())
        text = self._read_only_audit()
        self.assertIn("SECRET_REDACTION", text)
        self.assertIn("BSE", text)
        self.assertIn("[REDACTED]", text)
        self.assertNotIn("do-not-write-me", text)
        self.assertNotIn("daily-secret-token", text)
        self.assertNotIn("public-ish-key-but-still-redact", text)
        self.assertIn("HIDDEN CHAIN-OF-THOUGHT STORED: NO", text)

    def test_rationale_with_credential_like_material_is_suppressed(self):
        append_audit_record(
            category="DECISION",
            event="RATIONALE_REDACTION",
            rationale_summary="access_token=should-never-persist",
            payload={"safe": True},
        )
        text = self._read_only_audit()
        self.assertNotIn("should-never-persist", text)
        self.assertIn("REDACTED: contained credential-like material", text)

    def test_final_advisory_writes_structured_summary(self):
        audit_final_advisory(
            {
                "final_status": "WAIT",
                "ai_candidate": {"research_label": "LONG_CANDIDATE", "mode": "INTRADAY", "direction": "LONG"},
                "gate": {"action": "WAIT", "reasons": ["risk gate"]},
                "trade_geometry": {"mode": "INTRADAY", "direction": "LONG", "entry": 100.0, "stop_loss": 98.0, "take_profit": 104.0},
                "advisory_only": True,
                "order_execution_allowed": False,
            },
            request={"ticker": "BSE", "exchange": "NSE", "KITE_ACCESS_TOKEN": "never-log-this"},
        )
        text = self._read_only_audit()
        self.assertIn("FINAL_ADVISORY", text)
        self.assertIn("Final status WAIT", text)
        self.assertIn('"entry": 100.0', text)
        self.assertNotIn("never-log-this", text)
        self.assertIn('"KITE_ACCESS_TOKEN": "[REDACTED]"', text)


if __name__ == "__main__":
    unittest.main()
