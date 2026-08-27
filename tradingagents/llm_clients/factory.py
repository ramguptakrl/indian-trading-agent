import os
from typing import Optional

from .base_client import BaseLLMClient
from .openai_client import OpenAIClient
from .anthropic_client import AnthropicClient
from .google_client import GoogleClient
from .azure_client import AzureOpenAIClient

# Providers that use the OpenAI-compatible chat completions API.
# Groq exposes an OpenAI-compatible endpoint, so it does not require a separate
# SDK inside Trade Brain.
_OPENAI_COMPATIBLE = (
    "openai", "xai", "deepseek", "qwen", "glm", "groq", "ollama", "openrouter",
)

_PROVIDER_KEY_ENV = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "google": "GOOGLE_API_KEY",
    "groq": "GROQ_API_KEY",
    "xai": "XAI_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "qwen": "DASHSCOPE_API_KEY",
    "glm": "ZHIPU_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
}

_PROVIDER_NAMES = {
    "google": "Google Gemini",
    "groq": "Groq",
    "anthropic": "Anthropic Claude",
    "openai": "OpenAI",
    "xai": "xAI",
    "deepseek": "DeepSeek",
    "qwen": "Qwen",
    "glm": "GLM",
    "openrouter": "OpenRouter",
}


def _require_provider_auth(provider: str, kwargs: dict) -> None:
    """Fail with a Trade Brain UI instruction instead of a raw SDK auth error."""
    env_var = _PROVIDER_KEY_ENV.get(provider)
    if not env_var:
        return
    supplied = kwargs.get("api_key")
    if supplied or os.environ.get(env_var):
        return
    name = _PROVIDER_NAMES.get(provider, provider)
    raise ValueError(
        f"{name} is selected for Deep Analysis but no API key is configured. "
        "Open Settings > Models & Keys, add and test the key locally, set the desired "
        "provider as default, then retry. Do not paste API keys into chat."
    )


def create_llm_client(
    provider: str,
    model: str,
    base_url: Optional[str] = None,
    **kwargs,
) -> BaseLLMClient:
    """Create an LLM client for the specified provider.

    Args:
        provider: LLM provider name
        model: Model name/identifier
        base_url: Optional base URL for API endpoint
        **kwargs: Additional provider-specific arguments

    Returns:
        Configured BaseLLMClient instance

    Raises:
        ValueError: If provider is unsupported or its required local credential is missing
    """
    provider_lower = provider.lower()
    _require_provider_auth(provider_lower, kwargs)

    if provider_lower in _OPENAI_COMPATIBLE:
        return OpenAIClient(model, base_url, provider=provider_lower, **kwargs)

    if provider_lower == "anthropic":
        return AnthropicClient(model, base_url, **kwargs)

    if provider_lower == "google":
        return GoogleClient(model, base_url, **kwargs)

    if provider_lower == "azure":
        return AzureOpenAIClient(model, base_url, **kwargs)

    raise ValueError(f"Unsupported LLM provider: {provider}")
