"""LLM client supporting OpenAI-compatible APIs and local Ollama models."""
import os
from enum import Enum
from typing import Optional

from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_exponential


class ReasoningEffort(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ModelProvider(str, Enum):
    OPENAI = "openai"
    OLLAMA = "ollama"

# Models that support the reasoning_effort parameter
_REASONING_MODELS = {"o1", "o1-mini", "o1-preview", "o3", "o3-mini", "o4", "o4-mini", "gpt-5"}


def _supports_reasoning(model: str) -> bool:
    """Return True if the model supports the reasoning_effort parameter."""
    return model in _REASONING_MODELS or (model.startswith("o") and model[1:2].isdigit())


class LLMClient:
    """Unified client for OpenAI and Ollama (for Gemma) models."""

    def __init__(
        self,
        model: str,
        provider: ModelProvider = ModelProvider.OPENAI,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        reasoning_effort: ReasoningEffort = ReasoningEffort.LOW,
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ):
        self.model = model
        self.provider = provider
        self.reasoning_effort = reasoning_effort
        self.max_tokens = max_tokens
        self.temperature = temperature

        if provider == ModelProvider.OLLAMA:
            resolved_url = base_url or "http://localhost:11434/v1"
            resolved_key = api_key or "ollama"
        else:
            resolved_url = base_url
            resolved_key = api_key or os.environ.get("OPENAI_API_KEY", "")

        client_kwargs: dict = {"api_key": resolved_key}
        if resolved_url:
            client_kwargs["base_url"] = resolved_url

        self._client = OpenAI(**client_kwargs)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=60))
    def complete(
        self,
        messages: list[dict],
        response_format: Optional[dict] = None,
    ) -> str:
        """Call the LLM and return the text response."""
        kwargs: dict = {
            "model": self.model,
            "messages": messages,
            "max_tokens": self.max_tokens,
        }

        if _supports_reasoning(self.model):
            kwargs["reasoning_effort"] = self.reasoning_effort.value
        else:
            kwargs["temperature"] = self.temperature

        if response_format is not None:
            kwargs["response_format"] = response_format

        response = self._client.chat.completions.create(**kwargs)
        return response.choices[0].message.content or ""


def get_client_from_env(
    model: str,
    reasoning_effort: ReasoningEffort = ReasoningEffort.LOW,
) -> LLMClient:
    """Create an LLMClient using environment variables for credentials."""
    api_key = os.environ.get("OPENAI_API_KEY", "")
    base_url = os.environ.get("OPENAI_BASE_URL") or None
    return LLMClient(
        model=model,
        provider=ModelProvider.OPENAI,
        base_url=base_url,
        api_key=api_key,
        reasoning_effort=reasoning_effort,
    )
