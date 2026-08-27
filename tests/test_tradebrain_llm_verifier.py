import unittest
from unittest.mock import patch

from backend.tradebrain import llm_verifier


class TradeBrainMaterialVerifierTests(unittest.TestCase):
    def test_non_material_finding_does_not_spend_verifier_quota(self):
        with patch.object(llm_verifier, "get_material_verifier_config") as config:
            result = llm_verifier.verify_material_finding(
                research_label="NO_TRADE",
                final_trade_decision="WAIT",
                config={"llm_provider": "groq"},
            )
        self.assertEqual(result["status"], "SKIPPED_NOT_MATERIAL")
        self.assertFalse(result["order_execution_allowed"])
        config.assert_called_once()

    def test_material_finding_without_google_key_degrades_safely(self):
        with patch.object(llm_verifier, "get_material_verifier_config", return_value=None):
            result = llm_verifier.verify_material_finding(
                research_label="LONG_CANDIDATE",
                final_trade_decision="LONG ENTRY 100 SL 95 TP 110",
                config={"llm_provider": "groq"},
            )
        self.assertEqual(result["status"], "UNAVAILABLE_NOT_CONFIGURED")
        self.assertIsNone(result["verdict"])
        self.assertFalse(result["trade_authorization"])

    def test_json_parser_accepts_fenced_compact_output_only(self):
        parsed = llm_verifier._extract_json(
            '```json\n{"verdict":"CONFLICTS","checks":["price mismatch"],"conflicts":[],"missing_evidence":[]}\n```'
        )
        self.assertEqual(parsed["verdict"], "CONFLICTS")
        self.assertEqual(llm_verifier._normalize_verdict("anything else"), "UNCERTAIN")

    def test_safe_checks_limit_count_and_length(self):
        checks = llm_verifier._safe_checks(["x" * 500 for _ in range(10)])
        self.assertEqual(len(checks), 6)
        self.assertTrue(all(len(item) <= 241 for item in checks))


if __name__ == "__main__":
    unittest.main()
