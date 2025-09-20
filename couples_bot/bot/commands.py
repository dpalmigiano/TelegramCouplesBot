"""Command handlers for the bot."""

from __future__ import annotations

import math
from datetime import datetime
from typing import Dict, List, Optional

from .. import db
from ..advice import advice_engine
from ..llm import provider, prompts
from ..metrics import compute, thresholds
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


def _format_metric_lines(metrics: Dict[str, float | str]) -> List[str]:
    order = [
        ("p_to_n_conflict_ratio", "Pos/neg conflict ratio"),
        ("harsh_start_rate", "Harsh start rate"),
        ("repair_attempts_per_hour", "Repair attempts/hr"),
        ("repair_effectiveness_pct", "Repair effectiveness %"),
        ("neg_affect_reciprocity", "Neg affect reciprocity"),
        ("demand_withdraw_rate_AtoB", "Demand→withdraw A→B/1k"),
        ("demand_withdraw_rate_BtoA", "Demand→withdraw B→A/1k"),
        ("bid_response_ratio_affection", "Bid response (affection)"),
        ("bid_response_ratio_play", "Bid response (play)"),
        ("bid_response_ratio_gratitude", "Bid response (gratitude)"),
        ("median_reply_seconds", "Median reply (s)"),
        ("p90_reply_seconds", "P90 reply (s)"),
        ("reply_variability", "Reply variability"),
        ("emoji_signal_rate", "Emoji per msg"),
        ("lsm_score", "Language style match"),
        ("we_talk_index", "We-talk index"),
        ("we_talk_index_context", "We-talk context"),
        ("affection_density", "Affection density/100"),
        ("gratitude_density", "Gratitude density/100"),
        ("future_planning_density", "Future planning/100"),
        ("plan_to_happen_ratio", "Plans → happen ratio"),
        ("follow_through_latency_hours", "Follow-through median (h)"),
        ("support_balance_index", "Support balance index"),
        ("boundary_violations_per_1k", "Boundary hits/1k"),
        ("contempt_markers_per_1k", "Contempt markers/1k"),
        ("ruptures_per_month", "Ruptures/month"),
        ("median_repair_cycle_hours", "Median repair cycle (h)"),
    ]
    lines: List[str] = []
    for key, label in order:
        value = metrics.get(key)
        if isinstance(value, str):
            lines.append(f"{label}: {value}")
            continue
        if value is None:
            formatted = "0.00"
        elif key == "repair_effectiveness_pct":
            formatted = f"{value:.0f}%"
        elif key in {"median_reply_seconds", "p90_reply_seconds", "reply_variability"}:
            formatted = f"{value:.0f}"
        else:
            formatted = f"{value:.2f}"
        lines.append(f"{label}: {formatted}")
    return lines


def _status_tip(metrics: Dict[str, float | str], sla_seconds: float | None = None) -> str:
    reciprocity = float(metrics.get("neg_affect_reciprocity", 0.0))
    plan_ratio = float(metrics.get("plan_to_happen_ratio", 1.0))
    conflict_ratio = float(metrics.get("p_to_n_conflict_ratio", 1.0))
    support_gap = abs(float(metrics.get("support_balance_index", 0.0)))
    median_reply = float(metrics.get("median_reply_seconds", 0.0))
    if sla_seconds and median_reply > sla_seconds:
        minutes = median_reply / 60.0
        return (
            "Tip: send a timestamped reply update and agree on a fresh SLA (current median "
            f"{minutes:.1f}m)."
        )
    if reciprocity > 0.25:
        return "Tip: take a 20-minute breather, then restart with one appreciation + one clear ask."
    if plan_ratio < 0.6:
        return "Tip: confirm today's shared commitments and reschedule any slips before dinner."
    if support_gap >= 6:
        return "Tip: list the next two assists each of you can offer, then swap who starts."
    if conflict_ratio >= 3.0:
        return "Tip: lock in the positive run with a tiny celebration or shared win tonight."
    return "Tip: send a quick gratitude DM and follow it with a doable plan for tomorrow."


async def status(couple_id: int) -> str:
    messages = db.fetch_recent_messages(couple_id, limit=200)
    metrics = compute.compute_metrics(messages)
    prev_baselines: Dict[str, float] = {}
    for key, value in metrics.items():
        if isinstance(value, (int, float)):
            prev_baselines[key] = db.get_stat(
                couple_id,
                f"baseline:{key}",
                default=float("nan"),
            )
    bands = thresholds.update_baselines(couple_id, metrics)

    lines = ["Status snapshot:"]
    lines.extend(_format_metric_lines(metrics))

    couple = db.fetch_couple(couple_id)
    sla_seconds = None
    if couple:
        pref_a = db.fetch_pref(couple_id, couple["user_a_id"])
        pref_b = db.fetch_pref(couple_id, couple["user_b_id"])
        minutes = [
            pref_a["sla_minutes"] if pref_a and pref_a["sla_minutes"] else None,
            pref_b["sla_minutes"] if pref_b and pref_b["sla_minutes"] else None,
        ]
        minutes = [m for m in minutes if m]
        if minutes:
            sla_seconds = min(minutes) * 60

    def _band(key: str) -> tuple[float | None, float | None]:
        return bands.get(key, (None, None))

    def _prev_baseline(key: str) -> float | None:
        val = prev_baselines.get(key)
        if val is None or math.isnan(val):
            return None
        return val

    risks: List[str] = []
    for key in (
        "neg_affect_reciprocity",
        "demand_withdraw_rate_AtoB",
        "demand_withdraw_rate_BtoA",
        "boundary_violations_per_1k",
        "contempt_markers_per_1k",
        "support_balance_index",
    ):
        value = float(metrics.get(key, 0.0))
        prev = _prev_baseline(key)
        baseline, sigma = _band(key)
        baseline_for_eval = prev if prev is not None else baseline
        if thresholds.evaluate_risk(key, value, baseline_for_eval, sigma):
            risks.append(key)

    logistics_alerts: List[str] = []
    for key in ("median_reply_seconds", "plan_to_happen_ratio"):
        value = float(metrics.get(key, 0.0))
        if thresholds.evaluate_logistics(
            key,
            value,
            sla_seconds=sla_seconds,
        ):
            logistics_alerts.append(key)

    praises: List[str] = []
    for key in ("p_to_n_conflict_ratio", "follow_through_latency_hours"):
        value = float(metrics.get(key, 0.0))
        prev = _prev_baseline(key)
        baseline, sigma = _band(key)
        baseline_for_eval = prev if prev is not None else baseline
        if thresholds.evaluate_praise(key, value, baseline_for_eval, sigma):
            praises.append(key)

    if praises:
        lines.append("Active praise: " + ", ".join(praises))
    if risks:
        lines.append("Active risks: " + ", ".join(risks))
    if logistics_alerts:
        lines.append("Active logistics: " + ", ".join(logistics_alerts))

    lines.append(_status_tip(metrics, sla_seconds))
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
