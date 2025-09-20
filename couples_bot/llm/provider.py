"""LLM provider with OpenAI primary and Groq fallback."""
from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Any, Dict, List, Sequence

from ..config import get_settings


class LLMDisabled(RuntimeError):
    """Raised when no LLM provider is available."""


def _format_messages(messages: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [dict(message) for message in messages]


def _openai_client():
    from openai import OpenAI  # type: ignore

    settings = get_settings()
    if not settings.openai_api_key:
        raise LLMDisabled("OpenAI key missing")
    return OpenAI(api_key=settings.openai_api_key)


def _groq_client():
    from groq import Groq  # type: ignore

    settings = get_settings()
    if not settings.groq_api_key:
        raise LLMDisabled("Groq key missing")
    return Groq(api_key=settings.groq_api_key)


def _call_openai(
    messages: Sequence[Dict[str, Any]],
    *,
    max_tokens: int,
    temperature: float,
    stream: bool,
) -> Iterable[str] | str:
    settings = get_settings()
    client = _openai_client()
    payload = {
        "model": settings.openai_model,
        "messages": _format_messages(messages),
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": stream,
    }
    if stream:
        stream_resp = client.chat.completions.create(**payload)
        return (
            chunk.choices[0].delta.content or ""
            for chunk in stream_resp
        )
    response = client.chat.completions.create(**payload)
    return response.choices[0].message.content or ""


def _call_groq(
    messages: Sequence[Dict[str, Any]],
    *,
    max_tokens: int,
    temperature: float,
    stream: bool,
    use_tools: bool,
    enabled_tools: Sequence[str],
) -> Iterable[str] | str:
    settings = get_settings()
    client = _groq_client()
    model = "groq/compound" if use_tools else settings.groq_model
    payload: Dict[str, Any] = {
        "model": model,
        "messages": _format_messages(messages),
        "max_completion_tokens": max_tokens,
        "temperature": temperature,
        "stream": stream,
    }
    if use_tools:
        payload["compound_custom"] = {"tools": {"enabled_tools": list(enabled_tools)}}
    if stream:
        stream_resp = client.chat.completions.create(**payload)
        return (
            chunk.choices[0].delta.content or ""
            for chunk in stream_resp
        )
    response = client.chat.completions.create(**payload)
    return response.choices[0].message.content or ""


def llm_complete(
    messages: Sequence[Dict[str, Any]],
    *,
    max_tokens: int = 300,
    temperature: float = 0.3,
    stream: bool = False,
    use_tools: bool = False,
    enabled_tools: Sequence[str] = (),
) -> Iterable[str] | str:
    """Request a completion from OpenAI falling back to Groq."""

    settings = get_settings()
    if not settings.enable_llm:
        raise LLMDisabled("LLM disabled by configuration")

    openai_error: Exception | None = None
    if settings.openai_api_key:
        try:
            return _call_openai(
                messages,
                max_tokens=max_tokens,
                temperature=temperature,
                stream=stream,
            )
        except Exception as exc:  # pragma: no cover - broad but logged via tests
            openai_error = exc

    if settings.groq_api_key:
        try:
            return _call_groq(
                messages,
                max_tokens=max_tokens,
                temperature=temperature,
                stream=stream,
                use_tools=use_tools,
                enabled_tools=enabled_tools,
            )
        except Exception as exc:  # pragma: no cover
            if openai_error:
                raise LLMDisabled(f"OpenAI failed: {openai_error}; Groq failed: {exc}") from exc
            raise LLMDisabled(f"Groq failed: {exc}") from exc

    if openai_error:
        raise LLMDisabled(f"OpenAI failed: {openai_error}")
    raise LLMDisabled("No LLM provider configured")


__all__ = ["llm_complete", "LLMDisabled"]
