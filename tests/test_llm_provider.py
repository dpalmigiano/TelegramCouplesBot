import itertools
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
    monkeypatch.setenv("REAG_SILENCE_SECS", "180")
    monkeypatch.setenv("REAG_MIN_INTERVAL_SECS", "300")
    monkeypatch.setenv("REAG_QUEUE_HIGH_WATERMARK", "12")
    monkeypatch.setenv("REAG_MAX_OUT_TOKENS", "4096")
    monkeypatch.setenv("GROQ_FALLBACK_MODEL", "fallback-model")
    monkeypatch.setenv("GRAPH_ENABLED", "false")
    monkeypatch.setenv("CHAOS_MODE", "0")
    monkeypatch.setenv("CHAOS_LLM_P", "0.2")
    monkeypatch.setenv("ONBOARDING_DEEP_LINKS", "1")
    monkeypatch.setenv("ONBOARDING_BRAND_NAME", "Couples Coach")
    monkeypatch.setenv("ONBOARDING_EMOJI_STYLE", "🎯💬❤️")
    monkeypatch.setenv(
        "ONBOARDING_TZ_SUGGESTIONS",
        "[\"America/Los_Angeles\",\"America/New_York\"]",
    )


def test_openai_primary(monkeypatch):
    _base_env(monkeypatch)
    monkeypatch.setenv("ENABLE_LLM", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "key")
    monkeypatch.setenv("GROQ_API_KEY", "")
    get_settings.cache_clear()

    calls = {}

    class DummyOpenAI:
        def __init__(self, api_key, timeout=None):
            calls["client"] = {"api_key": api_key, "timeout": timeout}
            self.chat = types.SimpleNamespace(
                completions=types.SimpleNamespace(create=self._create)
            )

        def _create(self, **kwargs):
            calls["kwargs"] = kwargs
            return types.SimpleNamespace(
                choices=[types.SimpleNamespace(message={"content": "hi"})]
            )

    monkeypatch.setattr(provider, "OpenAI", DummyOpenAI)
    monkeypatch.setattr(provider, "Groq", None)

    result = provider.llm_complete([{"role": "user", "content": "hi"}])
    assert result == "hi"
    assert calls["client"]["api_key"] == "key"
    assert calls["kwargs"]["max_tokens"] == 300
    assert "max_completion_tokens" not in calls["kwargs"]


def test_groq_plain(monkeypatch):
    _base_env(monkeypatch)
    monkeypatch.setenv("ENABLE_LLM", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("GROQ_API_KEY", "groq")
    get_settings.cache_clear()

    calls = {}

    class DummyGroq:
        def __init__(self, api_key, timeout=None):
            calls["client"] = {"api_key": api_key, "timeout": timeout}
            self.chat = types.SimpleNamespace(
                completions=types.SimpleNamespace(create=self._create)
            )

        def _create(self, **kwargs):
            calls["kwargs"] = kwargs
            return types.SimpleNamespace(
                choices=[types.SimpleNamespace(message={"content": "fallback"})]
            )

    monkeypatch.setattr(provider, "OpenAI", None)
    monkeypatch.setattr(provider, "Groq", DummyGroq)

    result = provider.llm_complete([{"role": "user", "content": "hi"}])
    assert result == "fallback"
    assert calls["kwargs"]["model"] == "openai/gpt-oss-120b"
    assert calls["kwargs"]["max_completion_tokens"] == 300


def test_groq_tools(monkeypatch):
    _base_env(monkeypatch)
    monkeypatch.setenv("ENABLE_LLM", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "key")
    monkeypatch.setenv("GROQ_API_KEY", "groq")
    get_settings.cache_clear()

    class StubOpenAI:
        def __init__(self, api_key, timeout=None):
            raise AssertionError("OpenAI should be skipped when tools requested")

    captured = {}

    class DummyGroq:
        def __init__(self, api_key, timeout=None):
            self.chat = types.SimpleNamespace(
                completions=types.SimpleNamespace(create=self._create)
            )

        def _create(self, **kwargs):
            captured["kwargs"] = kwargs
            return types.SimpleNamespace(
                choices=[types.SimpleNamespace(message={"content": "tools"})]
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
    assert captured["kwargs"]["max_completion_tokens"] == 300


def test_streaming(monkeypatch):
    _base_env(monkeypatch)
    monkeypatch.setenv("ENABLE_LLM", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("GROQ_API_KEY", "groq")
    get_settings.cache_clear()

    class DummyGroq:
        def __init__(self, api_key, timeout=None):
            self.chat = types.SimpleNamespace(
                completions=types.SimpleNamespace(create=self._create)
            )

        def _create(self, **kwargs):
            chunk1 = types.SimpleNamespace(
                choices=[types.SimpleNamespace(delta=types.SimpleNamespace(content="hel"))]
            )
            chunk2 = types.SimpleNamespace(
                choices=[types.SimpleNamespace(delta=types.SimpleNamespace(content="lo"))]
            )
            return [chunk1, chunk2]

    monkeypatch.setattr(provider, "OpenAI", None)
    monkeypatch.setattr(provider, "Groq", DummyGroq)

    iterator = provider.llm_complete(
        [{"role": "user", "content": "hi"}],
        stream=True,
    )
    assert "".join(iterator) == "hello"


def test_chaos_retry(monkeypatch):
    _base_env(monkeypatch)
    monkeypatch.setenv("ENABLE_LLM", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "key")
    monkeypatch.setenv("GROQ_API_KEY", "")
    monkeypatch.setenv("CHAOS_MODE", "1")
    get_settings.cache_clear()

    calls = {"attempts": 0}

    class DummyOpenAI:
        def __init__(self, api_key, timeout=None):
            self.chat = types.SimpleNamespace(
                completions=types.SimpleNamespace(create=self._create)
            )

        def _create(self, **kwargs):
            calls["attempts"] += 1
            return types.SimpleNamespace(
                choices=[types.SimpleNamespace(message={"content": "ok"})]
            )

    # First random() call triggers chaos, second allows success
    sequence = itertools.chain([0.0], itertools.repeat(1.0))

    monkeypatch.setattr(provider, "OpenAI", DummyOpenAI)
    monkeypatch.setattr(provider, "Groq", None)
    monkeypatch.setattr(provider.random, "random", lambda: next(sequence))

    result = provider.llm_complete([{"role": "user", "content": "hi"}])
    assert result == "ok"
    # Chaos injection prevented the first attempt from reaching the client
    assert calls["attempts"] == 1


def test_disabled(monkeypatch):
    _base_env(monkeypatch)
    monkeypatch.setenv("ENABLE_LLM", "0")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("GROQ_API_KEY", "")
    get_settings.cache_clear()

    with pytest.raises(provider.LLMDisabled):
        provider.llm_complete([{"role": "user", "content": "hi"}])
