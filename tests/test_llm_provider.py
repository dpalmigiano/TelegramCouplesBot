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


def test_groq_plain(monkeypatch):
    _base_env(monkeypatch)
    monkeypatch.setenv("ENABLE_LLM", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("GROQ_API_KEY", "groq")
    get_settings.cache_clear()

    calls = {}

    class DummyGroq:
        def __init__(self, api_key):
            def create(**kwargs):
                calls["kwargs"] = kwargs
                return types.SimpleNamespace(
                    choices=[types.SimpleNamespace(message={"content": "fallback"})]
                )

            self.chat = types.SimpleNamespace(
                completions=types.SimpleNamespace(create=create)
            )

    monkeypatch.setattr(provider, "OpenAI", None)
    monkeypatch.setattr(provider, "Groq", DummyGroq)

    result = provider.llm_complete([{"role": "user", "content": "hi"}])
    assert result == "fallback"
    assert calls["kwargs"]["model"] == "openai/gpt-oss-120b"


def test_groq_tools(monkeypatch):
    _base_env(monkeypatch)
    monkeypatch.setenv("ENABLE_LLM", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "key")
    monkeypatch.setenv("GROQ_API_KEY", "groq")
    get_settings.cache_clear()

    class StubOpenAI:
        def __init__(self, api_key):
            raise AssertionError("OpenAI should be skipped when tools requested")

    captured = {}

    class DummyGroq:
        def __init__(self, api_key):
            def create(**kwargs):
                captured["kwargs"] = kwargs
                return types.SimpleNamespace(
                    choices=[types.SimpleNamespace(message={"content": "tools"})]
                )

            self.chat = types.SimpleNamespace(
                completions=types.SimpleNamespace(create=create)
            )

    monkeypatch.setattr(provider, "OpenAI", StubOpenAI)
    monkeypatch.setattr(provider, "Groq", DummyGroq)

    result = provider.llm_complete(
        [{"role": "user", "content": "hi"}],
        use_tools=True,
        enabled_tools=("calendar",),
    )
    assert result == "tools"
    assert captured["kwargs"]["model"] == "groq/compound"
    assert captured["kwargs"]["compound_custom"] == {"tools": {"enabled_tools": ["calendar"]}}


def test_disabled(monkeypatch):
    _base_env(monkeypatch)
    monkeypatch.setenv("ENABLE_LLM", "0")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("GROQ_API_KEY", "")
    get_settings.cache_clear()

    with pytest.raises(provider.LLMDisabled):
        provider.llm_complete([{"role": "user", "content": "hi"}])
