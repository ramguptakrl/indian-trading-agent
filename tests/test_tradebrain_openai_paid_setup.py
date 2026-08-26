"""Regression coverage for the paid OpenAI development configuration."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

from backend.settings_manager import PROVIDERS_INFO
from backend.tradebrain.llm_failover import (
    get_capacity_fallback_config,
    get_material_verifier_config,
)


def test_openai_settings_recommend_luna_quick_and_terra_deep():
    info = PROVIDERS_INFO["openai"]
    assert info["models_quick"][0] == "gpt-5.6-luna"
    assert info["models_deep"][0] == "gpt-5.6-terra"

    # Keep Foundation CI lightweight: importing tradingagents.llm_clients pulls optional
    # runtime SDKs that this unit-test job intentionally does not install. The catalog
    # contract can be verified directly from source without weakening coverage.
    root = Path(__file__).resolve().parents[1]
    catalog = (root / "tradingagents/llm_clients/model_catalog.py").read_text(encoding="utf-8")
    assert '("GPT-5.6 Luna - fast, cost-sensitive agent work", "gpt-5.6-luna")' in catalog
    assert '("GPT-5.6 Terra - stronger balanced reasoning", "gpt-5.6-terra")' in catalog


def test_openai_capacity_falls_back_to_gemini_when_configured():
    config = {
        "llm_provider": "openai",
        "quick_think_llm": "gpt-5.6-luna",
        "deep_think_llm": "gpt-5.6-terra",
        "advisory_only": True,
        "order_execution_enabled": False,
    }
    with patch.dict(os.environ, {"GOOGLE_API_KEY": "test-google-key"}, clear=False):
        fallback = get_capacity_fallback_config(config)

    assert fallback is not None
    assert fallback["llm_provider"] == "google"
    assert fallback["quick_think_llm"] == "gemini-3.6-flash"
    assert fallback["deep_think_llm"] == "gemini-3.6-flash"
    assert fallback["google_thinking_level"] == "minimal"
    assert fallback["advisory_only"] is True
    assert fallback["order_execution_enabled"] is False


def test_google_prefers_paid_openai_over_groq_when_both_are_configured():
    config = {
        "llm_provider": "google",
        "quick_think_llm": "gemini-3.6-flash",
        "deep_think_llm": "gemini-3.6-flash",
    }
    with patch.dict(
        os.environ,
        {"OPENAI_API_KEY": "test-openai-key", "GROQ_API_KEY": "test-groq-key"},
        clear=False,
    ):
        fallback = get_capacity_fallback_config(config)

    assert fallback is not None
    assert fallback["llm_provider"] == "openai"
    assert fallback["quick_think_llm"] == "gpt-5.6-luna"
    assert fallback["deep_think_llm"] == "gpt-5.6-terra"


def test_gemini_verifier_is_available_for_openai_primary():
    config = {
        "llm_provider": "openai",
        "llm_verifier_model": "gemini-3.6-flash",
    }
    with patch.dict(os.environ, {"GOOGLE_API_KEY": "test-google-key"}, clear=False):
        verifier = get_material_verifier_config(config)

    assert verifier is not None
    assert verifier["provider"] == "google"
    assert verifier["model"] == "gemini-3.6-flash"
    assert verifier["trade_authorization"] is False
    assert verifier["order_execution_allowed"] is False
