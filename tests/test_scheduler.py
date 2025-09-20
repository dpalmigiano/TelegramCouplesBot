from __future__ import annotations

from datetime import datetime, timedelta, timezone

from couples_bot import db
from couples_bot.config import get_settings
from couples_bot.db_jobs import reset_chaos_state
from workers import scheduler


def _base_env(monkeypatch, tmp_path):
    monkeypatch.setenv("TELEGRAM_API_ID", "1")
    monkeypatch.setenv("TELEGRAM_API_HASH", "hash")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("BOT_OWNER_USER_ID", "1")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "sched.sqlite"))
    monkeypatch.setenv("DEFAULT_TZ", "UTC")
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    monkeypatch.setenv("REAG_SILENCE_SECS", "180")
    monkeypatch.setenv("REAG_MIN_INTERVAL_SECS", "300")
    monkeypatch.setenv("REAG_QUEUE_HIGH_WATERMARK", "12")
    monkeypatch.setenv("REAG_MAX_OUT_TOKENS", "4096")
    monkeypatch.setenv("GROQ_FALLBACK_MODEL", "fallback")
    monkeypatch.setenv("GROQ_SYSTEM", "")
    monkeypatch.setenv("GROQ_ENABLED_TOOLS", "[\"web_search\",\"code_interpreter\"]")
    monkeypatch.setenv("GRAPH_ENABLED", "false")
    monkeypatch.setenv("CHAOS_MODE", "0")
    monkeypatch.setenv("CHAOS_LLM_P", "0.2")
    monkeypatch.setenv("ONBOARDING_DEEP_LINKS", "1")
    monkeypatch.setenv("ONBOARDING_BRAND_NAME", "Couples Coach")
    monkeypatch.setenv("ONBOARDING_EMOJI_STYLE", "🎯💬❤️")
    monkeypatch.setenv("ONBOARDING_TZ_SUGGESTIONS", "[\"UTC\"]")
    get_settings.cache_clear()
    if hasattr(db, "_CONN"):
        db._CONN = None  # type: ignore[attr-defined]
    reset_chaos_state()
    db.run_migrations()
    couple_id = db.link_couple(1, 2, 111, "UTC")
    return couple_id


def test_enqueue_after_silence(monkeypatch, tmp_path):
    couple_id = _base_env(monkeypatch, tmp_path)
    now = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
    db.log_message(couple_id, 111, 1, "First", now - timedelta(minutes=10))

    monkeypatch.setattr(scheduler.timebox, "utc_now", lambda: now)
    added = scheduler.enqueue_if_calm(now=now)
    assert added == 1

    # Further ticks should not enqueue while a job is pending
    assert scheduler.enqueue_if_calm(now=now) == 0


def test_respects_min_interval(monkeypatch, tmp_path):
    couple_id = _base_env(monkeypatch, tmp_path)
    now = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
    db.log_message(couple_id, 111, 1, "Ping", now - timedelta(minutes=10))

    monkeypatch.setattr(scheduler.timebox, "utc_now", lambda: now)
    assert scheduler.enqueue_if_calm(now=now) == 1

    # Mark job done to simulate worker completion
    with db.get_conn() as conn:
        conn.execute(
            "UPDATE jobs SET status='DONE', finished_ts=?",
            (int(now.timestamp()),),
        )
        conn.execute(
            "INSERT INTO reag_runs(couple_id, window_start_ts, window_end_ts, token_in, token_out, model, created_ts) VALUES(?,?,?,?,?,?,?)",
            (couple_id, int(now.timestamp()), int(now.timestamp()), 0, 0, "model", int(now.timestamp())),
        )

    soon = now + timedelta(minutes=2)
    monkeypatch.setattr(scheduler.timebox, "utc_now", lambda: soon)
    assert scheduler.enqueue_if_calm(now=soon) == 0

    later = now + timedelta(minutes=10)
    monkeypatch.setattr(scheduler.timebox, "utc_now", lambda: later)
    assert scheduler.enqueue_if_calm(now=later) == 0  # still blocked by min interval

    much_later = now + timedelta(minutes=20)
    db.log_message(couple_id, 111, 2, "New context", much_later - timedelta(minutes=6))
    monkeypatch.setattr(scheduler.timebox, "utc_now", lambda: much_later)
    assert scheduler.enqueue_if_calm(now=much_later) == 1


def test_high_water_defers_non_urgent(monkeypatch, tmp_path):
    couple_id = _base_env(monkeypatch, tmp_path)
    now = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
    db.log_message(couple_id, 111, 1, "Ping", now - timedelta(minutes=10))

    monkeypatch.setattr(scheduler.timebox, "utc_now", lambda: now)

    def fake_pending(include_future: bool = False):
        return 99

    monkeypatch.setattr(scheduler, "pending_jobs_count", fake_pending)
    added = scheduler.enqueue_if_calm(now=now)
    assert added == 0
    retry = db.get_stat(couple_id, "reag:retry_after_ts", default=0.0)
    assert retry > int(now.timestamp())


def test_silence_override(monkeypatch, tmp_path):
    couple_id = _base_env(monkeypatch, tmp_path)
    now = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
    db.log_message(couple_id, 111, 1, "Ping", now - timedelta(minutes=10))
    db.upsert_stat(couple_id, "reag:silence_override_secs", 900)

    monkeypatch.setattr(scheduler.timebox, "utc_now", lambda: now)
    assert scheduler.enqueue_if_calm(now=now) == 0

    later = now + timedelta(minutes=16)
    db.log_message(couple_id, 111, 1, "Later", later - timedelta(minutes=10))
    monkeypatch.setattr(scheduler.timebox, "utc_now", lambda: later)
    assert scheduler.enqueue_if_calm(now=later) == 1
