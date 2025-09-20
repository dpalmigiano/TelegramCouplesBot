import pytest

from couples_bot import db
from couples_bot.config import get_settings
from couples_bot.onboarding.wizard import OnboardingWizard


class DummyClient:
    def __init__(self):
        self.entities = {}

    async def get_entity(self, group_id):
        return type("Chat", (), {"title": f"Group {group_id}"})()

    async def get_messages(self, group_id, limit=1):
        return []


class DummyEvent:
    def __init__(self, sender_id: int):
        self.sender_id = sender_id
        self.is_private = True
        self.raw_text = "/start"
        self.responses: list[str] = []

    async def respond(self, text, buttons=None):  # pragma: no cover - buttons unused
        self.responses.append(text)

    async def edit(self, text):
        self.responses.append(text)


def _env(monkeypatch, tmp_path):
    monkeypatch.setenv("TELEGRAM_API_ID", "1")
    monkeypatch.setenv("TELEGRAM_API_HASH", "hash")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("BOT_OWNER_USER_ID", "1")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "onboarding.sqlite"))
    monkeypatch.setenv("DEFAULT_TZ", "UTC")
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    monkeypatch.setenv("REAG_SILENCE_SECS", "180")
    monkeypatch.setenv("REAG_MIN_INTERVAL_SECS", "300")
    monkeypatch.setenv("REAG_QUEUE_HIGH_WATERMARK", "12")
    monkeypatch.setenv("REAG_MAX_OUT_TOKENS", "4096")
    monkeypatch.setenv("GROQ_FALLBACK_MODEL", "fallback")
    monkeypatch.setenv("GROQ_SYSTEM", "")
    monkeypatch.setenv("GROQ_ENABLED_TOOLS", "[\"web_search\",\"code_interpreter\"]")
    monkeypatch.setenv("GRAPH_ENABLED", "0")
    monkeypatch.setenv("CHAOS_MODE", "0")
    monkeypatch.setenv("CHAOS_LLM_P", "0.0")
    monkeypatch.setenv("ONBOARDING_DEEP_LINKS", "1")
    monkeypatch.setenv("ONBOARDING_BRAND_NAME", "Couples Coach")
    monkeypatch.setenv("ONBOARDING_EMOJI_STYLE", "🎯💬❤️")
    monkeypatch.setenv(
        "ONBOARDING_TZ_SUGGESTIONS", "[\"UTC\",\"Europe/London\"]"
    )


def test_parse_payload():
    payload = OnboardingWizard._parse_payload("link_100_1_2")
    assert payload and payload.group_id == 100 and payload.user_a == 1 and payload.user_b == 2


@pytest.mark.asyncio
async def test_handle_start_happy(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    get_settings.cache_clear()
    if hasattr(db, "_CONN"):
        db._CONN = None  # type: ignore[attr-defined]
    db.run_migrations()

    client = DummyClient()
    wizard = OnboardingWizard(client)
    event = DummyEvent(sender_id=1)

    await wizard.handle_start(event, "link_111_1_2")

    couple = db.fetch_couple_by_user(1)
    assert couple is not None
    assert any("almost set" in resp.lower() for resp in event.responses)


@pytest.mark.asyncio
async def test_handle_start_wrong_user(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    get_settings.cache_clear()
    if hasattr(db, "_CONN"):
        db._CONN = None  # type: ignore[attr-defined]
    db.run_migrations()

    client = DummyClient()
    wizard = OnboardingWizard(client)
    event = DummyEvent(sender_id=99)

    await wizard.handle_start(event, "link_222_1_2")
    assert any("different couple" in resp for resp in event.responses)
