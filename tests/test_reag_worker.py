from __future__ import annotations

import json
import types
from datetime import datetime, timezone

import pytest

from couples_bot import db
from couples_bot.config import get_settings
from couples_bot.db_jobs import claim_job, enqueue_job, hash_payload, reset_chaos_state
from workers import reag_worker


def _env(monkeypatch, tmp_path):
    monkeypatch.setenv("TELEGRAM_API_ID", "1")
    monkeypatch.setenv("TELEGRAM_API_HASH", "hash")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("BOT_OWNER_USER_ID", "1")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "worker.sqlite"))
    monkeypatch.setenv("DEFAULT_TZ", "UTC")
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    monkeypatch.setenv("REAG_SILENCE_SECS", "180")
    monkeypatch.setenv("REAG_MIN_INTERVAL_SECS", "300")
    monkeypatch.setenv("REAG_QUEUE_HIGH_WATERMARK", "5")
    monkeypatch.setenv("REAG_MAX_OUT_TOKENS", "4096")
    monkeypatch.setenv("GROQ_FALLBACK_MODEL", "fallback-model")
    monkeypatch.setenv("GRAPH_ENABLED", "false")
    monkeypatch.setenv("ENABLE_LLM", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("GROQ_API_KEY", "fake")
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


def _make_payload(couple_id: int):
    now = datetime.now(timezone.utc)
    doc = {
        "type": "message",
        "role": "user:1",
        "sender_id": 1,
        "text": "We can reset tonight.",
        "ts": now.isoformat(),
        "ts_int": int(now.timestamp()),
    }
    payload = {
        "couple_id": couple_id,
        "docs": [doc],
        "use_tools": False,
        "enabled_tools": [],
        "created_ts": int(now.timestamp()),
    }
    return payload


class DummyGroq:
    def __init__(self, response_text, *, model_capture):
        self.chat = types.SimpleNamespace(
            completions=types.SimpleNamespace(create=self._create)
        )
        self._response_text = response_text
        self.kwargs = model_capture

    def _create(self, **kwargs):
        self.kwargs.clear()
        self.kwargs.update(kwargs)
        usage = types.SimpleNamespace(prompt_tokens=42, completion_tokens=24)
        message = {"content": self._response_text}
        choice = types.SimpleNamespace(message=message)
        return types.SimpleNamespace(choices=[choice], usage=usage)


def test_process_valid_job(monkeypatch, tmp_path):
    couple_id = _env(monkeypatch, tmp_path)
    payload = _make_payload(couple_id)
    payload_json = json.dumps(payload, separators=(",", ":"))
    payload_hash = hash_payload(payload)
    job_id = enqueue_job(couple_id, payload_json, payload_hash)
    assert job_id is not None

    job_row = claim_job()
    assert job_row is not None

    scores = {
        "p_to_n_conflict_ratio": 1.0,
        "harsh_start_rate": 0.0,
        "repair_attempts_per_hour": 1.0,
        "repair_effectiveness_pct": 50.0,
        "neg_affect_reciprocity": 0.1,
        "demand_withdraw_rate": {"dw_AtoB": 0.0, "dw_BtoA": 0.0},
        "bid_response_ratio": {
            "affection": 0.5,
            "info": 0.5,
            "play": 0.5,
            "requests": 0.5,
        },
        "median_reply_seconds": 120.0,
        "p90_reply_seconds": 300.0,
        "reply_variability": 1.0,
        "emoji_signal_rate": 0.1,
        "lsm_score": 0.7,
        "we_talk_index": {"value": 0.4, "context": "plans"},
        "affection_density": 0.2,
        "gratitude_density": 0.3,
        "future_planning_density": 0.4,
        "plan_to_happen_ratio": 0.6,
        "follow_through_latency_hours": 3.0,
        "support_balance_index": {"A": 0.0, "B": 0.0},
        "boundary_violations_per_1k": 0.0,
        "contempt_markers_per_1k": 0.0,
        "ruptures_per_month": 1.0,
        "median_repair_cycle_hours": 2.0,
    }
    response = json.dumps(
        {
            "graph": [{"s": "user:1", "p": "promised", "o": "task:call", "t": 1}],
            "scores": scores,
            "advice": {"user:1": "Try a reset tonight.", "user:2": "Offer a hug."},
        }
    )
    capture = {}
    monkeypatch.setattr(reag_worker, "Groq", lambda *_, **__: DummyGroq(response, model_capture=capture))

    reag_worker.process_job(job_row, reag_worker.Groq("key"))

    stat = db.get_stat(couple_id, "reag:p_to_n_conflict_ratio")
    assert stat == pytest.approx(1.0)
    assert capture["model"] == "openai/gpt-oss-120b"


def test_non_json_failure(monkeypatch, tmp_path):
    couple_id = _env(monkeypatch, tmp_path)
    payload = _make_payload(couple_id)
    payload_json = json.dumps(payload, separators=(",", ":"))
    payload_hash = hash_payload(payload)
    job_id = enqueue_job(couple_id, payload_json, payload_hash)
    assert job_id is not None

    job_row = claim_job()
    assert job_row is not None

    capture = {}
    monkeypatch.setattr(reag_worker, "Groq", lambda *_, **__: DummyGroq("not json", model_capture=capture))

    reag_worker.process_job(job_row, reag_worker.Groq("key"))

    with db.get_conn() as conn:
        status = conn.execute("SELECT status FROM jobs WHERE id = ?", (job_row["id"],)).fetchone()["status"]
    assert status == "FAILED"


def test_duplicate_payload_hash(monkeypatch, tmp_path):
    couple_id = _env(monkeypatch, tmp_path)
    payload = _make_payload(couple_id)
    payload_json = json.dumps(payload, separators=(",", ":"))
    payload_hash = hash_payload(payload)
    first = enqueue_job(couple_id, payload_json, payload_hash)
    assert first is not None
    second = enqueue_job(couple_id, payload_json, payload_hash)
    assert second is None


def test_backpressure_routes_fallback(monkeypatch, tmp_path):
    couple_id = _env(monkeypatch, tmp_path)
    payload = _make_payload(couple_id)
    payload_json = json.dumps(payload, separators=(",", ":"))
    payload_hash = hash_payload(payload)
    job_id = enqueue_job(couple_id, payload_json, payload_hash)
    assert job_id is not None
    job_row = claim_job()
    assert job_row is not None

    capture = {}

    def fake_pending():
        return 10

    monkeypatch.setattr(reag_worker, "pending_jobs_count", fake_pending)
    scores = {
        "p_to_n_conflict_ratio": 0.0,
        "harsh_start_rate": 0.0,
        "repair_attempts_per_hour": 0.0,
        "repair_effectiveness_pct": 0.0,
        "neg_affect_reciprocity": 0.0,
        "demand_withdraw_rate": {"dw_AtoB": 0.0, "dw_BtoA": 0.0},
        "bid_response_ratio": {
            "affection": 0.0,
            "info": 0.0,
            "play": 0.0,
            "requests": 0.0,
        },
        "median_reply_seconds": 0.0,
        "p90_reply_seconds": 0.0,
        "reply_variability": 0.0,
        "emoji_signal_rate": 0.0,
        "lsm_score": 0.0,
        "we_talk_index": {"value": 0.0, "context": "neutral"},
        "affection_density": 0.0,
        "gratitude_density": 0.0,
        "future_planning_density": 0.0,
        "plan_to_happen_ratio": 0.0,
        "follow_through_latency_hours": 0.0,
        "support_balance_index": {"A": 0.0, "B": 0.0},
        "boundary_violations_per_1k": 0.0,
        "contempt_markers_per_1k": 0.0,
        "ruptures_per_month": 0.0,
        "median_repair_cycle_hours": 0.0,
    }
    response = json.dumps(
        {
            "graph": [],
            "scores": scores,
            "advice": {"user:1": "Stay steady.", "user:2": "Offer time."},
        }
    )
    monkeypatch.setattr(reag_worker, "Groq", lambda *_, **__: DummyGroq(response, model_capture=capture))
    reag_worker.process_job(job_row, reag_worker.Groq("key"))
    assert capture["model"] == "fallback-model"
