"""Regression tests for Deep Analysis LLM capacity failover and Groq pacing."""

from __future__ import annotations

import os
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from backend.tradebrain.llm_failover import (
    GroqFreeTierGovernor,
    get_capacity_fallback_config,
    groq_governor_enabled,
    is_retryable_llm_capacity_error,
    public_capacity_error,
    response_rate_limit_headers,
    response_total_tokens,
    retry_after_seconds,
)


class TradeBrainLLMFailoverTests(unittest.TestCase):
    def test_google_resource_exhausted_is_retryable(self):
        error = RuntimeError("429 RESOURCE_EXHAUSTED quota exceeded for generate_content_free_tier_requests")
        self.assertTrue(is_retryable_llm_capacity_error(error))

    def test_groq_ratelimiterror_is_retryable(self):
        error = RuntimeError("RateLimitError: server overloaded, please retry")
        self.assertTrue(is_retryable_llm_capacity_error(error))

    def test_transient_gateway_errors_are_retryable(self):
        self.assertTrue(is_retryable_llm_capacity_error(RuntimeError("502 bad gateway capacity issue")))
        self.assertTrue(is_retryable_llm_capacity_error(RuntimeError("504 gateway timeout")))

    def test_programming_error_is_not_retryable(self):
        self.assertFalse(is_retryable_llm_capacity_error(RuntimeError("KeyError: ticker")))

    def test_retry_after_prefers_provider_header(self):
        error = RuntimeError("429 RateLimitError")
        error.response = SimpleNamespace(headers={"retry-after": "12.5"})
        self.assertAlmostEqual(retry_after_seconds(error), 12.5)

    def test_retry_after_parses_groq_token_reset_header(self):
        error = RuntimeError("429 RateLimitError")
        error.response = SimpleNamespace(headers={"x-ratelimit-reset-tokens": "1m3.25s"})
        self.assertAlmostEqual(retry_after_seconds(error), 63.25)

    def test_retry_after_parses_message_hint(self):
        error = RuntimeError("Rate limit reached. Please try again in 8.75s")
        self.assertAlmostEqual(retry_after_seconds(error), 8.75)

    def test_groq_governor_is_enabled_by_default_and_can_be_disabled(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("TRADEBRAIN_GROQ_GOVERNOR", None)
            self.assertTrue(groq_governor_enabled())
            os.environ["TRADEBRAIN_GROQ_GOVERNOR"] = "0"
            self.assertFalse(groq_governor_enabled())

    def test_governor_uses_conservative_headroom_below_hard_tpm(self):
        governor = GroqFreeTierGovernor(tpm_budget=6200, output_reserve=1500)
        reservation = governor.reserve("small prompt")
        self.assertEqual(reservation["soft_tpm_budget"], 6200)
        self.assertGreaterEqual(reservation["estimated_tokens"], 1500)
        self.assertLess(reservation["estimated_tokens"], 6200)
        self.assertGreater(reservation["reservation_id"], 0)

    def test_response_total_tokens_reads_langchain_usage_metadata(self):
        response = SimpleNamespace(
            usage_metadata={"input_tokens": 2100, "output_tokens": 900, "total_tokens": 3000},
            response_metadata={},
        )
        self.assertEqual(response_total_tokens(response), 3000)

    def test_response_total_tokens_reads_openai_response_metadata(self):
        response = SimpleNamespace(
            usage_metadata=None,
            response_metadata={"token_usage": {"prompt_tokens": 1800, "completion_tokens": 700}},
        )
        self.assertEqual(response_total_tokens(response), 2500)

    def test_response_rate_headers_are_normalized(self):
        response = SimpleNamespace(
            response_metadata={
                "headers": {
                    "X-RateLimit-Limit-Tokens": "8000",
                    "X-RateLimit-Remaining-Tokens": "6200",
                }
            }
        )
        headers = response_rate_limit_headers(response)
        self.assertEqual(headers["x-ratelimit-limit-tokens"], "8000")
        self.assertEqual(headers["x-ratelimit-remaining-tokens"], "6200")

    def test_governor_observes_live_provider_limit_headers(self):
        governor = GroqFreeTierGovernor(tpm_budget=6200, output_reserve=1000, min_request_interval=0)
        snapshot = governor.observe_headers({
            "x-ratelimit-limit-tokens": "6000",
            "x-ratelimit-remaining-tokens": "2400",
            "x-ratelimit-remaining-requests": "777",
            "x-ratelimit-reset-tokens": "4.5s",
        })
        self.assertEqual(snapshot["provider_limit_tokens_per_minute"], 6000)
        self.assertEqual(snapshot["provider_remaining_tokens"], 2400)
        self.assertEqual(snapshot["provider_remaining_requests_per_day"], 777)
        self.assertGreater(snapshot["provider_token_reset_seconds"], 0)
        # 78% adaptive headroom is lower than the configured 6200 ceiling.
        self.assertEqual(snapshot["soft_tpm_budget"], 4680)

    def test_governor_reconciles_estimate_to_actual_usage(self):
        governor = GroqFreeTierGovernor(tpm_budget=6200, output_reserve=1500, min_request_interval=0)
        reservation = governor.reserve("tiny")
        response = SimpleNamespace(
            usage_metadata={"total_tokens": 3100},
            response_metadata={},
        )
        actual = governor.reconcile(reservation, response)
        self.assertEqual(actual, 3100)
        self.assertEqual(governor.snapshot()["rolling_tokens"], 3100)

    def test_capacity_rejected_reservation_can_be_released(self):
        governor = GroqFreeTierGovernor(tpm_budget=6200, output_reserve=1500, min_request_interval=0)
        reservation = governor.reserve("tiny")
        self.assertGreater(governor.snapshot()["rolling_tokens"], 0)
        governor.release(reservation)
        self.assertEqual(governor.snapshot()["rolling_tokens"], 0)

    def test_provider_cooldown_is_process_wide(self):
        governor = GroqFreeTierGovernor(tpm_budget=6200, output_reserve=1500, min_request_interval=0)
        governor.impose_cooldown(0.05)
        self.assertGreater(governor.snapshot()["cooldown_remaining_seconds"], 0)

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

    def test_groq_uses_google_when_local_key_exists(self):
        config = {
            "llm_provider": "groq",
            "deep_think_llm": "openai/gpt-oss-20b",
            "quick_think_llm": "openai/gpt-oss-20b",
            "advisory_only": True,
        }
        with patch.dict(os.environ, {"GOOGLE_API_KEY": "test_not_real"}, clear=False):
            fallback = get_capacity_fallback_config(config)
        self.assertIsNotNone(fallback)
        assert fallback is not None
        self.assertEqual(fallback["llm_provider"], "google")
        self.assertEqual(fallback["deep_think_llm"], "gemini-3.6-flash")
        self.assertEqual(fallback["google_thinking_level"], "minimal")
        self.assertTrue(fallback["advisory_only"])

    def test_no_key_means_no_automatic_fallback(self):
        config = {"llm_provider": "google"}
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("GROQ_API_KEY", None)
            self.assertIsNone(get_capacity_fallback_config(config))

    def test_public_error_does_not_dump_provider_payload_and_fails_closed(self):
        error = RuntimeError("429 RESOURCE_EXHAUSTED huge provider payload secret-like-noise")
        message = public_capacity_error(error, fallback_available=False)
        self.assertIn("AI_UNAVAILABLE / WAIT", message)
        self.assertIn("quota/rate limit", message)
        self.assertIn("WAIT / NO TRADE", message)
        self.assertNotIn("huge provider payload", message)
        self.assertIn("Settings > Models & Keys", message)


if __name__ == "__main__":
    unittest.main()
