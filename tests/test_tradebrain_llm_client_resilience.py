"""Regression tests for bounded LLM client retry/timeout defaults."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from tradingagents.llm_clients.google_client import GoogleClient
from tradingagents.llm_clients.openai_client import OpenAIClient


class TradeBrainLLMClientResilienceTests(unittest.TestCase):
    def test_groq_client_has_bounded_retry_defaults(self):
        with patch("tradingagents.llm_clients.openai_client.NormalizedChatOpenAI") as cls:
            OpenAIClient("openai/gpt-oss-20b", provider="groq").get_llm()
        kwargs = cls.call_args.kwargs
        self.assertEqual(kwargs["timeout"], 60)
        self.assertEqual(kwargs["max_retries"], 2)

    def test_explicit_groq_retry_config_overrides_defaults(self):
        with patch("tradingagents.llm_clients.openai_client.NormalizedChatOpenAI") as cls:
            OpenAIClient(
                "openai/gpt-oss-20b",
                provider="groq",
                timeout=25,
                max_retries=1,
            ).get_llm()
        kwargs = cls.call_args.kwargs
        self.assertEqual(kwargs["timeout"], 25)
        self.assertEqual(kwargs["max_retries"], 1)

    def test_gemini_client_has_bounded_retry_defaults(self):
        with patch("tradingagents.llm_clients.google_client.NormalizedChatGoogleGenerativeAI") as cls:
            GoogleClient("gemini-3.6-flash").get_llm()
        kwargs = cls.call_args.kwargs
        self.assertEqual(kwargs["timeout"], 60)
        self.assertEqual(kwargs["max_retries"], 2)


if __name__ == "__main__":
    unittest.main()
