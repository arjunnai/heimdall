from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.config import Settings


@dataclass(frozen=True)
class ProviderResponse:
    content: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0


class LLMProvider(ABC):
    @abstractmethod
    def complete(
        self, messages: list[dict[str, str]], *, temperature: float = 0
    ) -> ProviderResponse:
        raise NotImplementedError


class AnthropicProvider(LLMProvider):
    def __init__(self, settings: Settings) -> None:
        if not settings.anthropic_api_key:
            raise ValueError("ANTHROPIC_API_KEY is required for the Anthropic provider")
        from anthropic import Anthropic

        self.client = Anthropic(api_key=settings.anthropic_api_key)
        self.model = settings.anthropic_model

    def complete(
        self, messages: list[dict[str, str]], *, temperature: float = 0
    ) -> ProviderResponse:
        system = next((item["content"] for item in messages if item["role"] == "system"), "")
        conversation = [item for item in messages if item["role"] != "system"]
        response = self.client.messages.create(
            model=self.model,
            max_tokens=1800,
            temperature=temperature,
            system=system,
            messages=conversation,
        )
        return ProviderResponse(
            content="".join(block.text for block in response.content if block.type == "text"),
            model=self.model,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )


class OpenAIProvider(LLMProvider):
    def __init__(self, settings: Settings) -> None:
        if not settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY is required for the OpenAI provider")
        from openai import OpenAI

        self.client = OpenAI(api_key=settings.openai_api_key)
        self.model = settings.openai_model

    def complete(
        self, messages: list[dict[str, str]], *, temperature: float = 0
    ) -> ProviderResponse:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
            response_format={"type": "json_object"},
        )
        usage = response.usage
        return ProviderResponse(
            content=response.choices[0].message.content or "{}",
            model=self.model,
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
        )


class DeterministicProvider(LLMProvider):
    """Offline provider used by the reproducible eval harness, never an LLM judge."""

    def complete(
        self, messages: list[dict[str, str]], *, temperature: float = 0
    ) -> ProviderResponse:
        return ProviderResponse(content=json.dumps({"mode": "deterministic"}), model="rules-v1")


def make_provider(settings: Settings) -> LLMProvider:
    providers: dict[str, type[LLMProvider]] = {
        "anthropic": AnthropicProvider,
        "openai": OpenAIProvider,
    }
    if settings.llm_provider == "deterministic":
        return DeterministicProvider()
    try:
        return providers[settings.llm_provider](settings)
    except KeyError as exc:
        raise ValueError(f"Unsupported LLM_PROVIDER={settings.llm_provider}") from exc
