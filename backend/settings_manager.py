"""Settings manager — handles API keys and LLM provider configuration.

API keys can be set via:
1. Settings UI (stored in SQLite DB) — takes priority
2. .env file (environment variable) — fallback

Keys stored in DB are loaded into os.environ at startup so langchain clients pick them up.
No key value is returned by the settings status API; only masked metadata is exposed.
"""

import os
from backend.db import get_setting, set_setting


# Mapping of provider → environment variable name used by langchain clients.
PROVIDER_ENV_KEYS = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "google": "GOOGLE_API_KEY",
    "groq": "GROQ_API_KEY",
    "xai": "XAI_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "qwen": "DASHSCOPE_API_KEY",
}

# Provider display info. This object drives the frontend Models & Keys screen.
# Dict order is intentional: OpenAI is the current recommended paid development primary.
PROVIDERS_INFO = {
    "openai": {
        "name": "OpenAI",
        "key_format": "sk-...",
        "signup_url": "https://platform.openai.com/api-keys",
        "note": (
            "Recommended paid Trade Brain primary during development. Use GPT-5.6 Luna for "
            "high-volume analyst/debate work and GPT-5.6 Terra for deeper decision synthesis. "
            "Gemini can remain the independent verifier and capacity fallback when configured."
        ),
        "models_deep": ["gpt-5.6-terra", "gpt-5.6-sol", "gpt-5.6-luna", "gpt-5.4"],
        "models_quick": ["gpt-5.6-luna", "gpt-5.6-terra", "gpt-5.6-sol", "gpt-5.4-mini"],
    },
    "google": {
        "name": "Google Gemini",
        "key_format": "AIza...",
        "signup_url": "https://aistudio.google.com/app/apikey",
        "note": (
            "Preferred independent verifier/challenger and retryable-capacity fallback when "
            "another cloud provider is primary. Keys are saved locally and masked in the UI."
        ),
        "models_deep": [
            "gemini-3.1-pro-preview",
            "gemini-3.6-flash",
            "gemini-3.5-flash",
            "gemini-2.5-pro",
        ],
        "models_quick": [
            "gemini-3.6-flash",
            "gemini-3.5-flash",
            "gemini-3.5-flash-lite",
            "gemini-2.5-flash",
        ],
    },
    "groq": {
        "name": "Groq",
        "key_format": "gsk_...",
        "signup_url": "https://console.groq.com/keys",
        "note": (
            "Fast OpenAI-compatible inference. Keep the free key available as an optional "
            "capacity fallback; paid Developer access is not required for OpenAI-primary runs."
        ),
        "models_deep": ["openai/gpt-oss-20b"],
        "models_quick": ["openai/gpt-oss-20b"],
    },
    "anthropic": {
        "name": "Anthropic Claude",
        "key_format": "sk-ant-...",
        "signup_url": "https://console.anthropic.com/",
        "models_deep": ["claude-opus-4-6", "claude-sonnet-4-6", "claude-sonnet-4-5"],
        "models_quick": ["claude-sonnet-4-6", "claude-haiku-4-5", "claude-sonnet-4-5"],
    },
    "ollama": {
        "name": "Ollama (Local)",
        "key_format": None,
        "requires_key": False,
        "signup_url": "https://ollama.com/download",
        "note": "Runs models locally — no API key, no cost. Requires the Ollama "
                "server running at http://localhost:11434. Pull a model first, "
                "e.g. `ollama pull qwen3`.",
        "models_deep": ["glm-4.7-flash:latest", "gpt-oss:latest", "qwen3:latest"],
        "models_quick": ["qwen3:latest", "gpt-oss:latest", "glm-4.7-flash:latest"],
    },
}


def load_api_keys_into_env():
    """Load API keys from DB into os.environ. Call this at startup.

    DB values OVERRIDE env variables (UI takes precedence over .env).
    """
    for provider, env_var in PROVIDER_ENV_KEYS.items():
        db_value = get_setting(f"api_key_{provider}")
        if db_value:
            os.environ[env_var] = db_value
            print(f"[Settings] Loaded API key for {provider} from DB", flush=True)


def save_api_key(provider: str, key: str):
    """Save an API key to the local DB and update this process environment."""
    provider = provider.strip().lower()
    if provider not in PROVIDER_ENV_KEYS:
        raise ValueError(f"API-key storage is not supported for provider: {provider}")
    set_setting(f"api_key_{provider}", key if key else None)

    env_var = PROVIDER_ENV_KEYS[provider]
    if key:
        os.environ[env_var] = key
    else:
        os.environ.pop(env_var, None)


def _active_key(provider: str) -> tuple[str, str | None]:
    provider = provider.strip().lower()
    env_var = PROVIDER_ENV_KEYS.get(provider)
    if not env_var:
        return "", None
    db_value = get_setting(f"api_key_{provider}") or ""
    env_value = os.environ.get(env_var, "")
    if db_value:
        return db_value, "ui"
    if env_value:
        return env_value, "env"
    return "", None


def get_api_keys_status() -> dict:
    """Return status of cloud API keys (configured or not, masked only)."""
    result = {}
    for provider, env_var in PROVIDER_ENV_KEYS.items():
        active_value, source = _active_key(provider)
        result[provider] = {
            "provider": provider,
            "name": PROVIDERS_INFO.get(provider, {}).get("name", provider),
            "configured": bool(active_value),
            "source": source,
            "masked": _mask_key(active_value) if active_value else None,
            "signup_url": PROVIDERS_INFO.get(provider, {}).get("signup_url"),
            "key_format": PROVIDERS_INFO.get(provider, {}).get("key_format"),
        }
    return result


def get_provider_runtime_status(provider: str) -> dict:
    """Return whether the selected LLM provider has the local auth it requires.

    This is a preflight only. It never returns the credential itself and it does not
    make a network request. Ollama is keyless; reachability is checked by its own API.
    """
    provider = (provider or "").strip().lower()
    info = PROVIDERS_INFO.get(provider)
    if not info:
        return {
            "provider": provider,
            "ready": False,
            "reason": "UNSUPPORTED_PROVIDER",
            "message": f"Unsupported LLM provider: {provider or '(empty)'}",
        }
    if info.get("requires_key") is False:
        return {
            "provider": provider,
            "ready": True,
            "reason": "KEY_NOT_REQUIRED",
            "message": f"{info['name']} does not require an API key.",
        }
    key, source = _active_key(provider)
    if key:
        return {
            "provider": provider,
            "ready": True,
            "reason": "KEY_CONFIGURED",
            "source": source,
            "message": f"{info['name']} credential is configured locally.",
        }
    return {
        "provider": provider,
        "ready": False,
        "reason": "API_KEY_MISSING",
        "source": None,
        "message": (
            f"{info['name']} is selected for Deep Analysis but no API key is configured. "
            "Open Settings > Models & Keys, add and test the key locally, then retry."
        ),
    }


def _mask_key(key: str) -> str:
    """Mask an API key for display — show only a small prefix and suffix."""
    if not key or len(key) < 15:
        return "****"
    return f"{key[:10]}...{key[-4:]}"


def test_api_key(provider: str, key: str | None = None) -> dict:
    """Test a provider credential with a minimal provider call.

    The supplied key is used in memory for this request and is never returned.
    """
    provider = provider.strip().lower()
    if key is None:
        key, _ = _active_key(provider)

    if not key:
        return {"ok": False, "error": "No API key provided or saved"}

    try:
        if provider == "anthropic":
            from anthropic import Anthropic
            client = Anthropic(api_key=key)
            client.messages.create(
                model="claude-haiku-4-5",
                max_tokens=10,
                messages=[{"role": "user", "content": "Say hi"}],
            )
            return {"ok": True, "model": "claude-haiku-4-5", "message": "API key works!"}

        if provider == "openai":
            from openai import OpenAI
            client = OpenAI(api_key=key)
            client.responses.create(
                model="gpt-5.6-luna",
                input="Reply with: ok",
                max_output_tokens=8,
            )
            return {
                "ok": True,
                "model": "gpt-5.6-luna",
                "message": "OpenAI API key works with GPT-5.6 Luna!",
            }

        if provider == "google":
            from google import genai
            client = genai.Client(api_key=key)
            client.models.generate_content(
                model="gemini-3.6-flash",
                contents="Say hi",
            )
            return {"ok": True, "model": "gemini-3.6-flash", "message": "API key works!"}

        if provider == "groq":
            from openai import OpenAI
            client = OpenAI(api_key=key, base_url="https://api.groq.com/openai/v1")
            models = client.models.list()
            ids = {getattr(item, "id", "") for item in getattr(models, "data", [])}
            model = "openai/gpt-oss-20b" if "openai/gpt-oss-20b" in ids else next(iter(ids), None)
            return {
                "ok": True,
                "model": model,
                "message": "Groq API key works!",
            }

        return {"ok": False, "error": f"Testing not implemented for {provider}"}

    except Exception as e:
        return {"ok": False, "error": str(e)}


def get_llm_config() -> dict:
    """Get current LLM provider and model config (from DB or defaults)."""
    from tradingagents.default_config import DEFAULT_CONFIG

    return {
        "llm_provider": get_setting("llm_provider") or DEFAULT_CONFIG["llm_provider"],
        "deep_think_llm": get_setting("deep_think_llm") or DEFAULT_CONFIG["deep_think_llm"],
        "quick_think_llm": get_setting("quick_think_llm") or DEFAULT_CONFIG["quick_think_llm"],
    }


def save_llm_config(provider: str | None = None, deep_model: str | None = None, quick_model: str | None = None):
    """Save LLM provider/model settings to the local DB."""
    if provider is not None:
        provider = provider.strip().lower()
        if provider not in PROVIDERS_INFO:
            raise ValueError(f"Unsupported LLM provider: {provider}")
        set_setting("llm_provider", provider)
    if deep_model is not None:
        set_setting("deep_think_llm", deep_model)
    if quick_model is not None:
        set_setting("quick_think_llm", quick_model)


def apply_llm_config_to_default():
    """Apply saved LLM config to DEFAULT_CONFIG for new TradingAgentsGraph instances."""
    from tradingagents.default_config import DEFAULT_CONFIG

    llm = get_llm_config()
    DEFAULT_CONFIG["llm_provider"] = llm["llm_provider"]
    DEFAULT_CONFIG["deep_think_llm"] = llm["deep_think_llm"]
    DEFAULT_CONFIG["quick_think_llm"] = llm["quick_think_llm"]
