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
    """ChatOpenAI with normalized output and Trade Brain Groq free-tier pacing.

    Successful Groq calls reconcile the governor's estimate with actual provider token usage.
    Capacity-rejected reservations are released, and Retry-After/reset timing is imposed
    process-wide so another agent cannot immediately stampede the same exhausted window.
    """

    tradebrain_provider: str = "openai"
    tradebrain_groq_retry_attempts: int = 4
    tradebrain_groq_max_retry_wait_seconds: float = 90.0

    def invoke(self, input, config=None, **kwargs):
        provider = str(self.tradebrain_provider or "").lower()
        if provider != "groq" or not groq_governor_enabled():
            return normalize_content(super().invoke(input, config, **kwargs))

        attempt = 0
        while True:
            reservation = GLOBAL_GROQ_GOVERNOR.reserve(input)
            try:
                response = super().invoke(input, config, **kwargs)
                GLOBAL_GROQ_GOVERNOR.reconcile(reservation, response)
                return normalize_content(response)
            except Exception as exc:
                # A rejected capacity request did not produce a usable completion; do not
                # count its full estimated output against our local rolling token budget.
                GLOBAL_GROQ_GOVERNOR.release(reservation)
                if not is_retryable_llm_capacity_error(exc):
                    raise
                if attempt >= int(self.tradebrain_groq_retry_attempts):
                    raise

                delay = retry_after_seconds(exc)
                GLOBAL_GROQ_GOVERNOR.impose_cooldown(delay + 0.25)
                # A free-tier minute-window reset is normally <=60 s. Much longer reset
                # windows are likely daily/model quota exhaustion, where Gemini fallback is
                # preferable to blocking an analyst for many minutes.
                if delay > float(self.tradebrain_groq_max_retry_wait_seconds):
                    raise

                attempt += 1
                time.sleep(max(0.25, delay + 0.25))


# Kwargs forwarded from user config to ChatOpenAI
_PASSTHROUGH_KWARGS = (
    "timeout", "max_retries", "reasoning_effort", "max_tokens",
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


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


class OpenAIClient(BaseLLMClient):
    """Client for OpenAI and OpenAI-compatible providers."""

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
            "timeout": 60,
            "max_retries": 2,
        }

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

        if self.provider == "groq":
            # Each agent needs a concise decision-quality report, not a multi-thousand-token
            # essay. The lower default materially reduces both TPM pressure and the 200K/day
            # free-tier token burn while leaving room for structured reasoning and levels.
            llm_kwargs["max_retries"] = 0
            llm_kwargs["max_tokens"] = max(
                256,
                min(_env_int("TRADEBRAIN_GROQ_MAX_COMPLETION_TOKENS", 800), 1600),
            )

        # Forward caller overrides last; explicit config overrides safe defaults.
        for key in _PASSTHROUGH_KWARGS:
            if key in self.kwargs:
                llm_kwargs[key] = self.kwargs[key]

        if self.provider == "openai":
            llm_kwargs["use_responses_api"] = True

        return NormalizedChatOpenAI(
            tradebrain_provider=self.provider,
            **llm_kwargs,
        )

    def validate_model(self) -> bool:
        """Validate model for the provider."""
        return validate_model(self.provider, self.model)
