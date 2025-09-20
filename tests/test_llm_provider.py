import json

import pytest

from couples_bot.llm import provider
from couples_bot.llm.provider import LLMDisabled
from couples_bot.config import get_settings


@pytest.fixture(autouse=True)
def configure_env(monkeypatch):
    monkeypatch.setenv("TELEGRAM_API_ID", "1")
    monkeypatch.setenv("TELEGRAM_API_HASH", "hash")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("BOT_OWNER_USER_ID", "1")
    monkeypatch.setenv("DATABASE_PATH", ":memory:")
    monkeypatch.setenv("DEFAULT_TZ", "UTC")
    monkeypatch.setenv("ENABLE_LLM", "true")
    monkeypatch.setenv("OPENAI_MODEL", "o4-mini")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_openai_primary(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    get_settings.cache_clear()

    called = {}

    def fake_call(messages, **kwargs):
        called["openai"] = json.dumps(messages)
        return "openai-result"

    monkeypatch.setattr(provider, "_call_openai", fake_call)
    result = provider.llm_complete([{"role": "user", "content": "hi"}])
    assert result == "openai-result"
    assert "openai" in called


def test_groq_fallback(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    monkeypatch.setenv("GROQ_API_KEY", "groq-key")
    get_settings.cache_clear()

    def failing_openai(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(provider, "_call_openai", failing_openai)

    def fake_groq(messages, **kwargs):
        return "groq-result"

    monkeypatch.setattr(provider, "_call_groq", fake_groq)

    result = provider.llm_complete([{"role": "user", "content": "hi"}])
    assert result == "groq-result"


def test_llm_disabled(monkeypatch):
    monkeypatch.setenv("ENABLE_LLM", "false")
    get_settings.cache_clear()
    with pytest.raises(LLMDisabled):
        provider.llm_complete([{"role": "user", "content": "hi"}])
