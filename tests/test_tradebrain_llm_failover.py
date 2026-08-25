"""Regression tests for Deep Analysis LLM capacity failover."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from backend.tradebrain.llm_failover import (
    get_capacity_fallback_config,
    is_retryable_llm_capacity_error,
    public_capacity_error,
)


class TradeBrainLLMFailoverTests(unittest.TestCase):
    def test_google_resource_exhausted_is_retryable(self):
        error = RuntimeError("429 RESOURCE_EXHAUSTED quota exceeded for generate_content_free_tier_requests")
        self.assertTrue(is_retryable_llm_capacity_error(error))

    def test_programming_error_is_not_retryable(self):
        self.assertFalse(is_retryable_llm_capacity_error(RuntimeError("KeyError: ticker")))

    def test_google_uses_groq_when_local_key_exists(self):
        config = {
            "llm_provider": "google",
            "deep_think_llm": "gemini-3.1-pro-preview",
            "quick_think_llm": "gemini-3.6-flash",
            "advisory_only": True,
            "order_execution_enabled": False,
        }
        with patch.dict(os.environ, {"GROQ_API_KEY": "gsk_test_not_real"}, clear=False):
            fallback = get_capacity_fallback_config(config)
        self.assertIsNotNone(fallback)
        assert fallback is not None
        self.assertEqual(fallback["llm_provider"], "groq")
        self.assertEqual(fallback["deep_think_llm"], "openai/gpt-oss-20b")
        self.assertEqual(fallback["quick_think_llm"], "openai/gpt-oss-20b")
        self.assertTrue(fallback["advisory_only"])
        self.assertFalse(fallback["order_execution_enabled"])

    def test_no_key_means_no_automatic_fallback(self):
        config = {"llm_provider": "google"}
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("GROQ_API_KEY", None)
            self.assertIsNone(get_capacity_fallback_config(config))

    def test_public_error_does_not_dump_provider_payload(self):
        error = RuntimeError("429 RESOURCE_EXHAUSTED huge provider payload secret-like-noise")
        message = public_capacity_error(error, fallback_available=False)
        self.assertIn("quota/rate limit", message)
        self.assertNotIn("huge provider payload", message)
        self.assertIn("Settings > Models & Keys", message)


if __name__ == "__main__":
    unittest.main()
