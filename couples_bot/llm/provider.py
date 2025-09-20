"""OpenAI → Groq fallback provider."""

from __future__ import annotations

import random
import time
from typing import Iterable, Iterator, Sequence

from ..config import get_settings

try:  # Optional imports; tests mock them.
    from openai import OpenAI  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    OpenAI = None  # type: ignore

try:
    from groq import Groq  # type: ignore
except Exception:  # pragma: no cover
    Groq = None  # type: ignore


REQUEST_TIMEOUT = 30.0
MAX_RETRIES = 3


class LLMDisabled(RuntimeError):
    """Raised when no LLM providers are available."""


Message = Sequence[dict]


def _streaming_iterator(chunks: Iterable) -> Iterator[str]:
    for chunk in chunks:
        choice = chunk.choices[0]
        delta = getattr(choice, "delta", None)
        if delta is not None:
            yield delta.content or ""
        else:
            yield choice.message.get("content", "")


def _with_retries(func):
    delay = 1.0
    last_error: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            return func()
        except Exception as exc:  # pragma: no cover - network/provider failures
            last_error = exc
            if attempt == MAX_RETRIES - 1:
                raise
            time.sleep(delay + random.uniform(0, 0.3))
            delay *= 2
    if last_error:
        raise last_error
    raise RuntimeError("Unreachable")


def _openai_complete(messages, *, max_tokens, temperature, stream):
    settings = get_settings()
    if OpenAI is None or not settings.openai_api_key:
        raise LLMDisabled("OpenAI unavailable")

    client = OpenAI(api_key=settings.openai_api_key, timeout=REQUEST_TIMEOUT)

    def _invoke():
        return client.chat.completions.create(
            model=settings.openai_model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=stream,
        )

    response = _with_retries(_invoke)
    if stream:
        return _streaming_iterator(response)
    return response.choices[0].message.get("content", "")


def _groq_complete(
    messages,
    *,
    max_tokens,
    temperature,
    stream,
    use_tools,
    enabled_tools,
):
    settings = get_settings()
    if Groq is None or not settings.groq_api_key:
        raise LLMDisabled("Groq unavailable")

    client = Groq(api_key=settings.groq_api_key, timeout=REQUEST_TIMEOUT)
    model = settings.groq_model
    extra: dict[str, object] = {}
    if use_tools:
        model = "groq/compound"
        extra["compound_custom"] = {"tools": {"enabled_tools": list(enabled_tools)}}

    def _invoke():
        return client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_completion_tokens=max_tokens,
            stream=stream,
            **extra,
        )

    response = _with_retries(_invoke)
    if stream:
        return _streaming_iterator(response)
    return response.choices[0].message.get("content", "")


def llm_complete(
    messages,
    *,
    max_tokens: int = 300,
    temperature: float = 0.3,
    stream: bool = False,
    use_tools: bool = False,
    enabled_tools: tuple[str, ...] = (),
):
    """Call the primary LLM provider, falling back automatically."""

    settings = get_settings()
    if not settings.enable_llm:
        raise LLMDisabled("LLM usage disabled by configuration")

    errors: list[Exception] = []

    if not use_tools and settings.openai_api_key and OpenAI is not None:
        try:
            return _openai_complete(
                messages,
                max_tokens=max_tokens,
                temperature=temperature,
                stream=stream,
            )
        except Exception as exc:  # pragma: no cover - network/provider failures
            errors.append(exc)

    if settings.groq_api_key and Groq is not None:
        try:
            return _groq_complete(
                messages,
                max_tokens=max_tokens,
                temperature=temperature,
                stream=stream,
                use_tools=use_tools,
                enabled_tools=tuple(enabled_tools),
            )
        except Exception as exc:  # pragma: no cover - provider failure
            errors.append(exc)

    if errors:
        raise LLMDisabled("All LLM providers failed") from errors[-1]
    raise LLMDisabled("LLM providers unavailable")


__all__ = ["llm_complete", "LLMDisabled"]
