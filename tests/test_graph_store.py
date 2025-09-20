from __future__ import annotations

from datetime import datetime, timezone

from couples_bot import db
from couples_bot.config import get_settings
from couples_bot.store import graph


def _env(monkeypatch, tmp_path):
    monkeypatch.setenv("TELEGRAM_API_ID", "1")
    monkeypatch.setenv("TELEGRAM_API_HASH", "hash")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("BOT_OWNER_USER_ID", "1")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "graph.sqlite"))
    monkeypatch.setenv("DEFAULT_TZ", "UTC")
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    monkeypatch.setenv("REAG_SILENCE_SECS", "180")
    monkeypatch.setenv("REAG_MIN_INTERVAL_SECS", "300")
    monkeypatch.setenv("REAG_QUEUE_HIGH_WATERMARK", "12")
    monkeypatch.setenv("REAG_MAX_OUT_TOKENS", "4096")
    monkeypatch.setenv("GROQ_FALLBACK_MODEL", "fallback")
    monkeypatch.setenv("GROQ_SYSTEM", "")
    monkeypatch.setenv("GROQ_ENABLED_TOOLS", "[\"web_search\",\"code_interpreter\"]")
    monkeypatch.setenv("GRAPH_ENABLED", "1")
    monkeypatch.setenv("CHAOS_MODE", "0")
    monkeypatch.setenv("CHAOS_LLM_P", "0.0")
    monkeypatch.setenv("ONBOARDING_DEEP_LINKS", "1")
    monkeypatch.setenv("ONBOARDING_BRAND_NAME", "Couples Coach")
    monkeypatch.setenv("ONBOARDING_EMOJI_STYLE", "🎯💬❤️")
    monkeypatch.setenv("ONBOARDING_TZ_SUGGESTIONS", "[\"UTC\"]")


def test_graph_upsert(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    get_settings.cache_clear()
    if hasattr(db, "_CONN"):
        db._CONN = None  # type: ignore[attr-defined]
    db.run_migrations()
    couple_id = db.link_couple(1, 2, 111, "UTC")
    db.log_message(couple_id, 111, 1, "Hi", datetime.now(timezone.utc))

    triples = [{"s": "user:1", "p": "promised", "o": "task:plan", "t": 1700000000}]
    graph.upsert_people_edges(triples, couple_id)

    with db.get_conn() as conn:
        node_count = conn.execute("SELECT COUNT(*) FROM graph_nodes").fetchone()[0]
        edge_count = conn.execute("SELECT COUNT(*) FROM graph_edges").fetchone()[0]
    assert node_count >= 2
    assert edge_count == 1

    # Idempotent second pass
    graph.upsert_people_edges(triples, couple_id)
    with db.get_conn() as conn:
        node_count_after = conn.execute("SELECT COUNT(*) FROM graph_nodes").fetchone()[0]
        edge_count_after = conn.execute("SELECT COUNT(*) FROM graph_edges").fetchone()[0]
    assert node_count_after == node_count
    assert edge_count_after == edge_count

    graph.link_plan_confirmation("couple:1:plan:a", "couple:1:confirm:a")
    with db.get_conn() as conn:
        fulfills = conn.execute(
            "SELECT COUNT(*) FROM graph_edges WHERE kind='fulfills'"
        ).fetchone()[0]
    assert fulfills == 1

    graph.upsert_message_embedding("couple:1:message:abc", [0.1, 0.2, 0.3])
    with db.get_conn() as conn:
        node = conn.execute(
            "SELECT tags, content FROM graph_nodes WHERE id=?",
            ("couple:1:message:abc",),
        ).fetchone()
        fts = conn.execute(
            "SELECT content FROM graph_node_fts WHERE node_id=?",
            ("couple:1:message:abc",),
        ).fetchone()
    assert node is not None
    assert "embedding" in node["tags"]
    assert fts is not None and "0.100" in fts["content"]
