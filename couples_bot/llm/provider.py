"""OpenAI → Groq fallback provider."""

from __future__ import annotations

import logging
import random
import time
import uuid
from typing import Callable, Iterable, Iterator, Sequence

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
BREAKER_COOLDOWN = 30.0


class LLMDisabled(RuntimeError):
    """Raised when no LLM providers are available."""


Message = Sequence[dict]

logger = logging.getLogger(__name__)


class CircuitBreaker:
    """Minimal circuit breaker tracking 5xx failures."""

    def __init__(self, name: str, cooldown: float = BREAKER_COOLDOWN) -> None:
        self.name = name
        self.cooldown = cooldown
        self._open_until = 0.0
        self._failures = 0

    def allow(self) -> bool:
        return time.monotonic() >= self._open_until

    def record_success(self) -> None:
        self._failures = 0
        self._open_until = 0.0

    def record_failure(self, exc: Exception) -> None:
        status_code = getattr(exc, "status_code", None)
        try:
            code_int = int(status_code) if status_code is not None else None
        except Exception:  # pragma: no cover - defensive
            code_int = None
        if code_int is not None and 500 <= code_int < 600:
            self._failures += 1
            if self._failures >= 2:
                self._open_until = time.monotonic() + self.cooldown
                logger.warning(
                    "llm_circuit_open name=%s failures=%s cooldown=%.1f", self.name, self._failures, self.cooldown
                )
        else:
            self._failures = 0


_BREAKERS: dict[str, CircuitBreaker] = {}


def _streaming_iterator(chunks: Iterable) -> Iterator[str]:
    for chunk in chunks:
        choice = chunk.choices[0]
        delta = getattr(choice, "delta", None)
        if delta is not None:
            yield delta.content or ""
        else:
            yield choice.message.get("content", "")


def _maybe_inject_failure(provider_name: str) -> None:
    settings = get_settings()
    if not settings.chaos_mode:
        return
    if random.random() < settings.chaos_llm_p:
        raise TimeoutError(f"CHAOS: simulated {provider_name} failure")


def _with_retries(func: Callable[[], object], *, provider_name: str, breaker: CircuitBreaker):
    if not breaker.allow():
        raise LLMDisabled(f"{provider_name} unavailable (circuit open)")
    delay = 1.0
    last_error: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            result = func()
            breaker.record_success()
            return result
        except Exception as exc:  # pragma: no cover - network/provider failures
            last_error = exc
            breaker.record_failure(exc)
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
    breaker = _BREAKERS.setdefault("openai", CircuitBreaker("openai"))
    request_id = f"oa-{uuid.uuid4().hex}"

    def _invoke():
        _maybe_inject_failure("openai")
        return client.chat.completions.create(
            model=settings.openai_model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=stream,
            extra_headers={"x-client-request-id": request_id},
        )

    response = _with_retries(_invoke, provider_name="openai", breaker=breaker)
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
    chat_model = settings.groq_model or "openai/gpt-oss-120b"
    compound_model = settings.groq_system or ""
    tools_list = list(enabled_tools) if enabled_tools else list(settings.groq_enabled_tools)

    def _invoke(model: str, *, breaker_name: str, extra: dict[str, object]) -> object:
        breaker = _BREAKERS.setdefault(breaker_name, CircuitBreaker(breaker_name))
        request_id = f"{breaker_name}-{uuid.uuid4().hex}"

        def _call():
            _maybe_inject_failure(breaker_name)
            payload = {
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "top_p": 1,
                "max_completion_tokens": max_tokens,
                "stream": stream,
                "extra_headers": {"x-client-request-id": request_id},
            }
            payload.update(extra)
            return client.chat.completions.create(**payload)

        return _with_retries(_call, provider_name=breaker_name, breaker=breaker)

    def _chat_call() -> object:
        return _invoke(chat_model, breaker_name="groq-chat", extra={})

    def _compound_call() -> object:
        if not compound_model:
            raise LLMDisabled("Groq compound disabled")
        return _invoke(
            compound_model,
            breaker_name="groq-compound",
            extra={"compound_custom": {"tools": {"enabled_tools": tools_list}}},
        )

    if use_tools:
        try:
            response = _compound_call()
        except LLMDisabled:
            response = _chat_call()
    else:
        try:
            response = _chat_call()
        except Exception as exc:
            if not compound_model:
                raise
            logger.warning("groq_chat_failed fallback=compound reason=%s", exc)
            response = _compound_call()

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
