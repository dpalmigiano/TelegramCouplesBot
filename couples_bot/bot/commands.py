"""Command handlers for the bot."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from .. import db
from ..advice import advice_engine
from ..llm import provider, prompts
from ..metrics import compute
from ..models import AlertKind
from ..utils import timebox

CONSENT_PREFIX = "consent:"
PAUSE_KEY = "tracking_paused"


def _consent_key(user_id: int) -> str:
    return f"{CONSENT_PREFIX}{user_id}"


def has_consent(couple_id: int, user_id: int) -> bool:
    return db.get_stat(couple_id, _consent_key(user_id), default=0) >= 1


def set_consent(couple_id: int, user_id: int, value: bool) -> None:
    db.upsert_stat(couple_id, _consent_key(user_id), 1.0 if value else 0.0)


def is_tracking_paused(couple_id: int) -> bool:
    return db.get_stat(couple_id, PAUSE_KEY, default=0) >= 1


def set_tracking_paused(couple_id: int, value: bool) -> None:
    db.upsert_stat(couple_id, PAUSE_KEY, 1.0 if value else 0.0)


async def link(group_chat_id: int, user_a_id: int, user_b_id: int, tz: str) -> str:
    couple_id = db.link_couple(user_a_id, user_b_id, group_chat_id, tz)
    db.set_pref(couple_id, user_a_id, sla_minutes=120)
    db.set_pref(couple_id, user_b_id, sla_minutes=120)
    return (
        "Couple linked. Ask both partners to DM /consent yes."
        f" Couple id: {couple_id}."
    )


async def status(couple_id: int) -> str:
    messages = db.fetch_recent_messages(couple_id, limit=120)
    metrics = compute.compute_metrics(messages)
    lines = ["Status snapshot:"]
    lines.append(f"Pos/neg conflict ratio: {metrics['p_to_n_conflict_ratio']:.2f}")
    lines.append(f"Harsh start rate: {metrics['harsh_start_rate']:.2f}")
    lines.append(
        f"Repair attempts/hr: {metrics['repair_attempts_per_hour']:.2f}"
    )
    lines.append(
        f"Median reply: {metrics['median_reply_seconds']/60:.1f} min"
    )
    return "\n".join(lines)


async def advice(couple_id: int, user_id: int, label: Optional[str] = None) -> str:
    existing = db.fetch_advice(couple_id, user_id)
    if existing:
        age = "fresh"
        return f"Advice ({age}): {existing}"
    return advice_engine.build_advice_for_user(couple_id, user_id, label)


async def pause(couple_id: int) -> str:
    set_tracking_paused(couple_id, True)
    return "Tracking paused. Use /resume to restart."


async def resume(couple_id: int) -> str:
    set_tracking_paused(couple_id, False)
    return "Tracking resumed."


async def export_messages(couple_id: int, limit: int = 50) -> str:
    rows = db.fetch_recent_messages(couple_id, limit=limit)
    lines = ["Recent messages:"]
    for row in rows:
        ts = row["ts"]
        sender = row["sender_id"]
        text = row["text"][:120]
        lines.append(f"{ts} | {sender}: {text}")
    return "\n".join(lines[-60:])


async def consent(couple_id: int, user_id: int, value: bool) -> str:
    set_consent(couple_id, user_id, value)
    if has_consent(couple_id, user_id) and has_consent(couple_id, _other_partner(couple_id, user_id)):
        return "Consent logged. Tracking is active."
    return "Consent logged. Waiting for your partner."


def _other_partner(couple_id: int, user_id: int) -> int:
    couple = db.fetch_couple(couple_id)
    if not couple:
        return user_id
    if couple["user_a_id"] == user_id:
        return couple["user_b_id"]
    return couple["user_a_id"]


async def advocate(couple_id: int, user_id: int, issue: str) -> str:
    label = f"partner {user_id}"
    try:
        messages = prompts.advocate_prompt(label, issue)
        result = provider.llm_complete(messages, max_tokens=200)
        if isinstance(result, str):
            return result.strip()
        return "".join(result).strip()
    except provider.LLMDisabled:
        return (
            "Try: 'I value us getting this right. Could we set aside 15 minutes"
            " tonight to decide on {issue}?'"
        ).format(issue=issue)


async def toggle_alerts(couple_id: int, user_id: int, enabled: bool) -> str:
    db.set_pref(couple_id, user_id, enable_alerts=enabled)
    return "Alerts on." if enabled else "Alerts off."


async def set_sla(couple_id: int, user_id: int, minutes: int) -> str:
    db.set_pref(couple_id, user_id, sla_minutes=minutes)
    return f"SLA set to {minutes} minutes."


async def set_dnd(couple_id: int, user_id: int, window: str) -> str:
    if "-" not in window:
        return "Format should be HH:MM-HH:MM"
    start, end = window.split("-", 1)
    db.set_pref(couple_id, user_id, dnd_start=start, dnd_end=end)
    return f"DND set to {window}."


async def forget(couple_id: int, user_id: int) -> str:
    set_consent(couple_id, user_id, False)
    db.set_pref(couple_id, user_id, enable_alerts=False)
    return "Your data has been marked for deletion."


async def list_couples() -> str:
    with db.get_conn() as conn:
        rows = conn.execute(
            "SELECT id, user_a_id, user_b_id, group_chat_id FROM couples"
        ).fetchall()
    if not rows:
        return "No couples linked."
    return "\n".join(
        f"{row['id']}: {row['user_a_id']} & {row['user_b_id']} (group {row['group_chat_id']})"
        for row in rows
    )


async def unlink(group_chat_id: int) -> str:
    couple = db.fetch_couple_by_group(group_chat_id)
    if not couple:
        return "No couple linked to that group."
    db.wipe_couple(couple["id"])
    return "Couple unlinked."


async def wipe(couple_id: int) -> str:
    db.wipe_couple(couple_id)
    return "Couple wiped."


__all__ = [
    "link",
    "status",
    "advice",
    "pause",
    "resume",
    "export_messages",
    "consent",
    "has_consent",
    "set_consent",
    "is_tracking_paused",
    "advocate",
    "toggle_alerts",
    "set_sla",
    "set_dnd",
    "forget",
    "list_couples",
    "unlink",
    "wipe",
]
