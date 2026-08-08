"""LLM provider abstraction. Configurable via LLM_PROVIDER=openai|anthropic
(app/config.py), kept behind a single async `generate(prompt)` function so
nothing downstream depends on which SDK is in use.

Nodes that call this (investigate_root_cause, generate_fix's explanation
text) receive it as an injected callable, not a module-level singleton —
this is what makes the golden-file eval and unit tests deterministic
without needing a real API key.
"""

from __future__ import annotations

from typing import Awaitable, Callable, Protocol

from app.config import settings

LLMGenerate = Callable[[str], Awaitable[str]]


class LLMNotConfiguredError(Exception):
    """Raised when a live LLM call is attempted but no API key is set for
    the configured provider. Callers must not silently substitute canned
    text and present it as a model output — that would violate the "don't
    claim mocked functionality is real" constraint the same way a fake
    DataHub write-back would."""


class _ChatModel(Protocol):
    async def ainvoke(self, prompt: str): ...


def _build_chat_model() -> _ChatModel:
    if settings.llm_provider == "anthropic":
        if not settings.anthropic_api_key:
            raise LLMNotConfiguredError("ANTHROPIC_API_KEY is not set")
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(
            model="claude-sonnet-5",
            api_key=settings.anthropic_api_key,
            temperature=0,
        )
    if not settings.openai_api_key:
        raise LLMNotConfiguredError("OPENAI_API_KEY is not set")
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(model="gpt-4o-mini", api_key=settings.openai_api_key, temperature=0)


async def generate(prompt: str) -> str:
    """Real LLM call via the configured provider. Raises
    LLMNotConfiguredError if no key is set — callers decide how to handle
    that (nodes surface it as a failed incident, per the design doc's
    "fail with a clear error state" pattern, never a silent fallback)."""
    model = _build_chat_model()
    response = await model.ainvoke(prompt)
    return str(response.content)
