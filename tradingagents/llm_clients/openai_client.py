import os
import time
from typing import Any, Optional

from langchain_openai import ChatOpenAI

from backend.tradebrain.llm_failover import (
    GLOBAL_GROQ_GOVERNOR,
    groq_governor_enabled,
    is_retryable_llm_capacity_error,
    retry_after_seconds,
)
from .base_client import BaseLLMClient, normalize_content
from .validators import validate_model


class NormalizedChatOpenAI(ChatOpenAI):
    """ChatOpenAI with normalized output and Trade Brain Groq capacity pacing.

    The Responses API returns content as a list of typed blocks (reasoning, text, etc.).
    This normalizes to string for consistent downstream handling.

    For Groq, the wrapper cooperatively paces agent calls and handles short provider
    Retry-After windows locally. A temporary tokens-per-minute 429 therefore pauses the
    current node instead of restarting the entire multi-agent graph on Gemini.
    """

    tradebrain_provider: str = "openai"
    tradebrain_groq_retry_attempts: int = 3
    tradebrain_groq_max_retry_wait_seconds: float = 75.0

    def invoke(self, input, config=None, **kwargs):
        provider = str(self.tradebrain_provider or "").lower()
        if provider != "groq" or not groq_governor_enabled():
            return normalize_content(super().invoke(input, config, **kwargs))

        attempt = 0
        while True:
            GLOBAL_GROQ_GOVERNOR.reserve(input)
            try:
                return normalize_content(super().invoke(input, config, **kwargs))
            except Exception as exc:
                if not is_retryable_llm_capacity_error(exc):
                    raise
                if attempt >= int(self.tradebrain_groq_retry_attempts):
                    raise

                delay = retry_after_seconds(exc)
                # Long reset windows usually indicate a daily/model quota rather than the
                # minute window. Let the outer Trade Brain fallback move to Gemini instead
                # of sleeping for minutes/hours inside one agent node.
                if delay > float(self.tradebrain_groq_max_retry_wait_seconds):
                    raise

                attempt += 1
                time.sleep(max(0.25, delay + 0.25))


# Kwargs forwarded from user config to ChatOpenAI
_PASSTHROUGH_KWARGS = (
    "timeout", "max_retries", "reasoning_effort",
    "api_key", "callbacks", "http_client", "http_async_client",
)

# Provider base URLs and API key env vars
_PROVIDER_CONFIG = {
    "xai": ("https://api.x.ai/v1", "XAI_API_KEY"),
    "deepseek": ("https://api.deepseek.com", "DEEPSEEK_API_KEY"),
    "qwen": ("https://dashscope-intl.aliyuncs.com/compatible-mode/v1", "DASHSCOPE_API_KEY"),
    "glm": ("https://api.z.ai/api/paas/v4/", "ZHIPU_API_KEY"),
    "groq": ("https://api.groq.com/openai/v1", "GROQ_API_KEY"),
    "openrouter": ("https://openrouter.ai/api/v1", "OPENROUTER_API_KEY"),
    "ollama": ("http://localhost:11434/v1", None),
}


class OpenAIClient(BaseLLMClient):
    """Client for OpenAI and OpenAI-compatible providers.

    Native OpenAI models use the Responses API. Third-party compatible providers
    such as Groq, xAI, OpenRouter and Ollama use standard Chat Completions.
    """

    def __init__(
        self,
        model: str,
        base_url: Optional[str] = None,
        provider: str = "openai",
        **kwargs,
    ):
        super().__init__(model, base_url, **kwargs)
        self.provider = provider.lower()

    def get_llm(self) -> Any:
        """Return configured ChatOpenAI instance with bounded transient retries."""
        self.warn_if_unknown_model()
        llm_kwargs = {
            "model": self.model,
            # Keep provider hiccups from failing a whole graph immediately, while
            # remaining bounded so Trade Brain can still move to its alternate provider.
            "timeout": 60,
            "max_retries": 2,
        }

        # Provider-specific base URL and auth
        if self.provider in _PROVIDER_CONFIG:
            base_url, api_key_env = _PROVIDER_CONFIG[self.provider]
            llm_kwargs["base_url"] = base_url
            if api_key_env:
                api_key = os.environ.get(api_key_env)
                if api_key:
                    llm_kwargs["api_key"] = api_key
            else:
                llm_kwargs["api_key"] = "ollama"
        elif self.base_url:
            llm_kwargs["base_url"] = self.base_url

        # Groq retries are handled by our rate governor so Retry-After/reset hints are
        # respected explicitly. Disable opaque SDK retries that would otherwise duplicate
        # calls before Trade Brain has a chance to pace them.
        if self.provider == "groq":
            llm_kwargs["max_retries"] = 0

        # Forward user-provided kwargs; explicit config overrides safe defaults.
        for key in _PASSTHROUGH_KWARGS:
            if key in self.kwargs:
                llm_kwargs[key] = self.kwargs[key]

        # Native OpenAI: use Responses API for consistent behavior across
        # all model families. Third-party providers use Chat Completions.
        if self.provider == "openai":
            llm_kwargs["use_responses_api"] = True

        return NormalizedChatOpenAI(
            tradebrain_provider=self.provider,
            **llm_kwargs,
        )

    def validate_model(self) -> bool:
        """Validate model for the provider."""
        return validate_model(self.provider, self.model)
