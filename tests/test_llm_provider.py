from __future__ import annotations

import types

import pytest

from couples_bot.config import get_settings
from couples_bot.llm import provider


def _base_env(monkeypatch):
    monkeypatch.setenv("TELEGRAM_API_ID", "1")
    monkeypatch.setenv("TELEGRAM_API_HASH", "hash")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("BOT_OWNER_USER_ID", "1")
    monkeypatch.setenv("DATABASE_PATH", ":memory:")
    monkeypatch.setenv("DEFAULT_TZ", "UTC")
    monkeypatch.setenv("LOG_LEVEL", "INFO")


def test_openai_primary(monkeypatch):
    _base_env(monkeypatch)
    monkeypatch.setenv("ENABLE_LLM", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "key")
    monkeypatch.setenv("GROQ_API_KEY", "")
    get_settings.cache_clear()

    class DummyOpenAI:
        def __init__(self, api_key):
            self.chat = types.SimpleNamespace(
                completions=types.SimpleNamespace(
                    create=lambda **kwargs: types.SimpleNamespace(
                        choices=[types.SimpleNamespace(message={"content": "hi"})]
                    )
                )
            )

    monkeypatch.setattr(provider, "OpenAI", DummyOpenAI)
    monkeypatch.setattr(provider, "Groq", None)

    result = provider.llm_complete([{"role": "user", "content": "hi"}])
    assert result == "hi"


def test_groq_fallback(monkeypatch):
    _base_env(monkeypatch)
    monkeypatch.setenv("ENABLE_LLM", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "key")
    monkeypatch.setenv("GROQ_API_KEY", "groq")
    get_settings.cache_clear()

    class FailingOpenAI:
        def __init__(self, api_key):
            raise RuntimeError("fail")

    class DummyGroq:
        def __init__(self, api_key):
            self.chat = types.SimpleNamespace(
                completions=types.SimpleNamespace(
                    create=lambda **kwargs: types.SimpleNamespace(
                        choices=[types.SimpleNamespace(message={"content": "fallback"})]
                    )
                )
            )

    monkeypatch.setattr(provider, "OpenAI", FailingOpenAI)
    monkeypatch.setattr(provider, "Groq", DummyGroq)

    result = provider.llm_complete([{"role": "user", "content": "hi"}])
    assert result == "fallback"


def test_disabled(monkeypatch):
    _base_env(monkeypatch)
    monkeypatch.setenv("ENABLE_LLM", "0")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("GROQ_API_KEY", "")
    get_settings.cache_clear()

    with pytest.raises(provider.LLMDisabled):
        provider.llm_complete([{"role": "user", "content": "hi"}])
