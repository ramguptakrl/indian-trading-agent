"""Regression coverage for Trade Brain frontend/backend LLM provider wiring."""

from __future__ import annotations

import os

from backend import settings_manager
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.llm_clients.factory import _OPENAI_COMPATIBLE, create_llm_client
from tradingagents.llm_clients.model_catalog import get_known_models
from tradingagents.llm_clients.openai_client import _PROVIDER_CONFIG


def test_tradebrain_default_is_gemini_not_anthropic():
    assert DEFAULT_CONFIG["llm_provider"] == "google"
    assert DEFAULT_CONFIG["quick_think_llm"] == "gemini-3.6-flash"
    assert DEFAULT_CONFIG["deep_think_llm"] == "gemini-3.1-pro-preview"


def test_groq_is_first_class_settings_and_client_provider():
    assert settings_manager.PROVIDER_ENV_KEYS["groq"] == "GROQ_API_KEY"
    assert "groq" in settings_manager.PROVIDERS_INFO
    assert settings_manager.PROVIDERS_INFO["groq"]["models_quick"] == ["openai/gpt-oss-20b"]
    assert "groq" in _OPENAI_COMPATIBLE
    assert _PROVIDER_CONFIG["groq"] == ("https://api.groq.com/openai/v1", "GROQ_API_KEY")
    assert "openai/gpt-oss-20b" in get_known_models()["groq"]


def test_groq_client_uses_openai_compatible_adapter(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test_not_a_real_credential")
    client = create_llm_client(provider="groq", model="openai/gpt-oss-20b")
    llm = client.get_llm()
    assert client.provider == "groq"
    assert str(llm.openai_api_base).rstrip("/") == "https://api.groq.com/openai/v1"


def test_provider_runtime_status_is_safe_and_does_not_return_key(monkeypatch):
    monkeypatch.setattr(settings_manager, "get_setting", lambda key: None)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    status = settings_manager.get_provider_runtime_status("google")
    assert status["ready"] is False
    assert status["reason"] == "API_KEY_MISSING"
    assert "key" not in status

    monkeypatch.setenv("GOOGLE_API_KEY", "AIza_test_not_a_real_credential")
    status = settings_manager.get_provider_runtime_status("google")
    assert status["ready"] is True
    assert status["source"] == "env"
    assert "AIza_test_not_a_real_credential" not in repr(status)


def test_frontend_provider_metadata_exposes_gemini_and_groq_without_secrets():
    google = settings_manager.PROVIDERS_INFO["google"]
    groq = settings_manager.PROVIDERS_INFO["groq"]
    assert "gemini-3.6-flash" in google["models_quick"]
    assert "gemini-3.1-pro-preview" in google["models_deep"]
    assert groq["key_format"] == "gsk_..."
    blob = repr(settings_manager.PROVIDERS_INFO)
    assert "GROQ_API_KEY" not in blob
    assert "GOOGLE_API_KEY" not in blob
