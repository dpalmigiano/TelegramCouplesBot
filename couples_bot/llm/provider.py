"""OpenAI → Groq fallback provider."""

from __future__ import annotations

from typing import Generator, Iterable, Iterator, Sequence

from . import prompts  # noqa: F401  # re-export for convenience
from ..config import get_settings

try:  # Optional imports; tests mock them.
    from openai import OpenAI  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    OpenAI = None  # type: ignore

try:
    from groq import Groq  # type: ignore
except Exception:  # pragma: no cover
    Groq = None  # type: ignore


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


def _openai_complete(messages, *, max_tokens, temperature, stream):
    settings = get_settings()
    if OpenAI is None or not settings.openai_api_key:
        raise LLMDisabled("OpenAI unavailable")
    client = OpenAI(api_key=settings.openai_api_key)
    if stream:
        chunks = client.chat.completions.create(
            model=settings.openai_model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
        )
        return _streaming_iterator(chunks)
    response = client.chat.completions.create(
        model=settings.openai_model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )
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
    client = Groq(api_key=settings.groq_api_key)
    model = settings.groq_model
    extra = {}
    if use_tools:
        model = "groq/compound"
        extra["compound_custom"] = {
            "tools": {"enabled_tools": list(enabled_tools)}
        }
    if stream:
        chunks = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_completion_tokens=max_tokens,
            stream=True,
            **extra,
        )
        return _streaming_iterator(chunks)
    response = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature,
        max_completion_tokens=max_tokens,
        **extra,
    )
    return response.choices[0].message.get("content", "")


def llm_complete(
    messages,
    *,
    max_tokens: int = 300,
    temperature: float = 0.3,
    stream: bool = False,
    use_tools: bool = False,
    enabled_tools: Iterable[str] = (),
):
    """Call the primary LLM provider, falling back automatically."""

    settings = get_settings()
    if not settings.enable_llm:
        raise LLMDisabled("LLM usage disabled by configuration")

    # Attempt OpenAI first.
    try:
        result = _openai_complete(
            messages,
            max_tokens=max_tokens,
            temperature=temperature,
            stream=stream,
        )
        return result
    except Exception:
        pass

    # Fall back to Groq.
    try:
        return _groq_complete(
            messages,
            max_tokens=max_tokens,
            temperature=temperature,
            stream=stream,
            use_tools=use_tools,
            enabled_tools=tuple(enabled_tools),
        )
    except Exception as exc:
        raise LLMDisabled("All LLM providers failed") from exc


__all__ = ["llm_complete", "LLMDisabled"]
