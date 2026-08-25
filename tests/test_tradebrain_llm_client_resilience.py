"""Source-level regression tests for bounded LLM retry/timeout defaults.

Foundation CI intentionally installs only the lightweight Trade Brain test dependencies,
not the full LangChain provider stack. These tests therefore verify the runtime contract
without importing provider SDKs.
"""

from __future__ import annotations

import unittest
from pathlib import Path


class TradeBrainLLMClientResilienceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[1]
        cls.openai_source = (root / "tradingagents/llm_clients/openai_client.py").read_text(encoding="utf-8")
        cls.google_source = (root / "tradingagents/llm_clients/google_client.py").read_text(encoding="utf-8")

    def test_openai_compatible_client_has_bounded_defaults(self):
        self.assertIn('"timeout": 60', self.openai_source)
        self.assertIn('"max_retries": 2', self.openai_source)
        self.assertIn("explicit config overrides safe defaults", self.openai_source)

    def test_gemini_client_has_bounded_defaults(self):
        self.assertIn('"timeout": 60', self.google_source)
        self.assertIn('"max_retries": 2', self.google_source)

    def test_provider_clients_still_allow_explicit_override(self):
        self.assertIn('if key in self.kwargs:', self.openai_source)
        self.assertIn('if key in self.kwargs:', self.google_source)


if __name__ == "__main__":
    unittest.main()
