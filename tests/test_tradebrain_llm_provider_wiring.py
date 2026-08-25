"""Regression coverage for Trade Brain frontend/backend LLM provider wiring.

This test stays inside the lean Foundation dependency set: it verifies the LLM adapter
wiring statically instead of importing optional LangChain provider packages.
"""

from __future__ import annotations

import os
import runpy
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import settings_manager
from tradingagents.default_config import DEFAULT_CONFIG

ROOT = Path(__file__).resolve().parents[1]


def _known_models_without_loading_llm_package() -> dict[str, list[str]]:
    """Execute model_catalog.py directly so llm_clients/__init__ cannot import SDKs."""
    namespace = runpy.run_path(str(ROOT / "tradingagents" / "llm_clients" / "model_catalog.py"))
    return namespace["get_known_models"]()


class TradeBrainLLMProviderWiringTests(unittest.TestCase):
    def test_tradebrain_default_is_gemini_not_anthropic(self):
        self.assertEqual(DEFAULT_CONFIG["llm_provider"], "google")
        self.assertEqual(DEFAULT_CONFIG["quick_think_llm"], "gemini-3.6-flash")
        self.assertEqual(DEFAULT_CONFIG["deep_think_llm"], "gemini-3.1-pro-preview")

    def test_groq_is_first_class_settings_and_catalog_provider(self):
        self.assertEqual(settings_manager.PROVIDER_ENV_KEYS["groq"], "GROQ_API_KEY")
        self.assertIn("groq", settings_manager.PROVIDERS_INFO)
        self.assertEqual(
            settings_manager.PROVIDERS_INFO["groq"]["models_quick"],
            ["openai/gpt-oss-20b"],
        )
        self.assertIn("openai/gpt-oss-20b", _known_models_without_loading_llm_package()["groq"])

    def test_groq_openai_compatible_adapter_is_wired_without_importing_optional_sdk(self):
        factory = (ROOT / "tradingagents" / "llm_clients" / "factory.py").read_text(encoding="utf-8")
        openai_client = (ROOT / "tradingagents" / "llm_clients" / "openai_client.py").read_text(encoding="utf-8")
        self.assertIn('"groq"', factory)
        self.assertIn('"groq": ("https://api.groq.com/openai/v1", "GROQ_API_KEY")', openai_client)
        self.assertIn("Settings > Models & Keys", factory)

    def test_provider_runtime_status_is_safe_and_does_not_return_key(self):
        with patch.object(settings_manager, "get_setting", return_value=None):
            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop("GOOGLE_API_KEY", None)
                status = settings_manager.get_provider_runtime_status("google")
                self.assertFalse(status["ready"])
                self.assertEqual(status["reason"], "API_KEY_MISSING")
                self.assertNotIn("key", status)

                os.environ["GOOGLE_API_KEY"] = "AIza_test_not_a_real_credential"
                status = settings_manager.get_provider_runtime_status("google")
                self.assertTrue(status["ready"])
                self.assertEqual(status["source"], "env")
                self.assertNotIn("AIza_test_not_a_real_credential", repr(status))
                os.environ.pop("GOOGLE_API_KEY", None)

    def test_frontend_provider_metadata_exposes_gemini_and_groq_without_secrets(self):
        google = settings_manager.PROVIDERS_INFO["google"]
        groq = settings_manager.PROVIDERS_INFO["groq"]
        self.assertIn("gemini-3.6-flash", google["models_quick"])
        self.assertIn("gemini-3.1-pro-preview", google["models_deep"])
        self.assertEqual(groq["key_format"], "gsk_...")
        blob = repr(settings_manager.PROVIDERS_INFO)
        self.assertNotIn("GROQ_API_KEY", blob)
        self.assertNotIn("GOOGLE_API_KEY", blob)


if __name__ == "__main__":
    unittest.main()
