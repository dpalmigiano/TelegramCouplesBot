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
    monkeypatch.setenv("GROQ_SYSTEM", "")
    monkeypatch.setenv("GROQ_ENABLED_TOOLS", "[\"web_search\",\"code_interpreter\"]")
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
    provider._BREAKERS.clear()  # type: ignore[attr-defined]


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
    assert "extra_headers" in calls["kwargs"]
    assert "max_completion_tokens" not in calls["kwargs"]


def test_openai_failure_falls_back_to_groq(monkeypatch):
    _base_env(monkeypatch)
    monkeypatch.setenv("ENABLE_LLM", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "key")
    monkeypatch.setenv("GROQ_API_KEY", "groq")
    get_settings.cache_clear()

    calls = {}

    class DummyOpenAI:
        def __init__(self, *_, **__):
            self.chat = types.SimpleNamespace(
                completions=types.SimpleNamespace(create=self._create)
            )

        def _create(self, **kwargs):
            raise RuntimeError("boom")

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

    monkeypatch.setattr(provider, "OpenAI", DummyOpenAI)
    monkeypatch.setattr(provider, "Groq", DummyGroq)

    result = provider.llm_complete([{"role": "user", "content": "hi"}])
    assert result == "fallback"
    assert calls["kwargs"]["model"] == "openai/gpt-oss-120b"
    assert calls["kwargs"]["max_completion_tokens"] == 300
    assert calls["kwargs"]["extra_headers"].keys() == {"x-client-request-id"}


def test_groq_chat_failure_promotes_to_compound(monkeypatch):
    _base_env(monkeypatch)
    monkeypatch.setenv("ENABLE_LLM", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("GROQ_API_KEY", "groq")
    monkeypatch.setenv("GROQ_SYSTEM", "groq/compound")
    monkeypatch.setenv("GROQ_ENABLED_TOOLS", "[\"web_search\",\"code_interpreter\"]")
    get_settings.cache_clear()

    class DummyGroq:
        def __init__(self, api_key, timeout=None):
            self.chat = types.SimpleNamespace(
                completions=types.SimpleNamespace(create=self._create)
            )
            self.calls = []

        def _create(self, **kwargs):
            if kwargs.get("model") == "openai/gpt-oss-120b":
                raise RuntimeError("chat overloaded")
            self.calls.append(kwargs)
            return types.SimpleNamespace(
                choices=[types.SimpleNamespace(message={"content": "compound"})]
            )

    groq_instance = DummyGroq("groq")
    monkeypatch.setattr(provider, "OpenAI", None)
    monkeypatch.setattr(provider, "Groq", lambda *_, **__: groq_instance)

    result = provider.llm_complete([{"role": "user", "content": "hi"}])
    assert result == "compound"
    assert groq_instance.calls[-1]["model"] == "groq/compound"
    assert groq_instance.calls[-1]["compound_custom"] == {
        "tools": {"enabled_tools": ["web_search", "code_interpreter"]}
    }


def test_tools_path_uses_env_enabled_tools(monkeypatch):
    _base_env(monkeypatch)
    monkeypatch.setenv("ENABLE_LLM", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("GROQ_API_KEY", "groq")
    monkeypatch.setenv("GROQ_SYSTEM", "groq/compound")
    monkeypatch.setenv("GROQ_ENABLED_TOOLS", "[\"web_search\",\"calendar\"]")
    get_settings.cache_clear()

    captured = {}

    class DummyGroq:
        def __init__(self, api_key, timeout=None):
            self.chat = types.SimpleNamespace(
                completions=types.SimpleNamespace(create=self._create)
            )

        def _create(self, **kwargs):
            captured.update(kwargs)
            return types.SimpleNamespace(
                choices=[types.SimpleNamespace(message={"content": "tools"})]
            )

    monkeypatch.setattr(provider, "OpenAI", None)
    monkeypatch.setattr(provider, "Groq", DummyGroq)

    result = provider.llm_complete(
        [{"role": "user", "content": "hi"}],
        use_tools=True,
    )
    assert result == "tools"
    assert captured["model"] == "groq/compound"
    assert captured["compound_custom"] == {
        "tools": {"enabled_tools": ["web_search", "calendar"]}
    }
    assert captured["max_completion_tokens"] == 300


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

    sequence = itertools.chain([0.0], itertools.repeat(1.0))

    monkeypatch.setattr(provider, "OpenAI", DummyOpenAI)
    monkeypatch.setattr(provider, "Groq", None)
    monkeypatch.setattr(provider.random, "random", lambda: next(sequence))

    result = provider.llm_complete([{"role": "user", "content": "hi"}])
    assert result == "ok"
    assert calls["attempts"] == 1


def test_disabled(monkeypatch):
    _base_env(monkeypatch)
    monkeypatch.setenv("ENABLE_LLM", "0")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("GROQ_API_KEY", "")
    get_settings.cache_clear()

    with pytest.raises(provider.LLMDisabled):
        provider.llm_complete([{"role": "user", "content": "hi"}])
