"""Telethon event wiring."""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Optional

from telethon import events

from .. import db
from ..advice import advice_engine
from ..alerts import pings
from ..metrics import classifiers, compute, thresholds
from ..models import AlertKind
from ..onboarding import OnboardingWizard
from ..onboarding import copy as onboarding_copy
from ..utils import timebox
from . import commands


def register(client) -> None:
    """Register command and message handlers on the client."""

    wizard = OnboardingWizard(client)

    @client.on(events.NewMessage(pattern=r"^/start(?:\s+(.*))?$"))
    async def _start(event):
        if not event.is_private:
            await event.respond("DM me with the deep link to complete onboarding.")
            return
        payload = event.raw_text.split(" ", 1)[1] if " " in event.raw_text else ""
        await wizard.handle_start(event, payload)

    @client.on(events.NewMessage(pattern=r"^/hello"))
    async def _hello(event):
        await event.respond(onboarding_copy.hello_card())

    @client.on(events.NewMessage(pattern=r"^/link"))
    async def _link(event):
        if not event.is_group:
            await event.respond("Run /link in the shared group chat.")
            return
        parts = event.raw_text.split()
        if len(parts) < 3:
            await event.respond("Usage: /link @partnerA @partnerB")
            return
        mentions = parts[1:3]
        ids = []
        for ent in event.message.entities or []:
            if hasattr(ent, "user_id"):
                ids.append(ent.user_id)
        while len(ids) < 2:
            # Fallback to numeric parsing
            try:
                ids.append(int(mentions[len(ids)].lstrip("@")))
            except Exception:
                ids.append(0)
        tz = "UTC"
        message = await commands.link(event.chat_id, ids[0], ids[1], tz)
        await event.respond(message)

    @client.on(events.NewMessage(pattern=r"^/status"))
    async def _status(event):
        couple = _resolve_couple(event)
        if not couple:
            await event.respond("No couple linked here.")
            return
        message = await commands.status(couple["id"])
        await event.respond(message)

    @client.on(events.NewMessage(pattern=r"^/advice"))
    async def _advice(event):
        couple = _resolve_couple(event)
        if not couple:
            await event.respond("No couple linked yet.")
            return
        user_id = event.sender_id or 0
        message = await commands.advice(couple["id"], user_id)
        await event.respond(message)

    @client.on(events.NewMessage(pattern=r"^/pause"))
    async def _pause(event):
        couple = _resolve_couple(event)
        if not couple:
            return
        await event.respond(await commands.pause(couple["id"]))

    @client.on(events.NewMessage(pattern=r"^/resume"))
    async def _resume(event):
        couple = _resolve_couple(event)
        if not couple:
            return
        await event.respond(await commands.resume(couple["id"]))

    @client.on(events.NewMessage(pattern=r"^/export"))
    async def _export(event):
        couple = _resolve_couple(event)
        if not couple:
            return
        await event.respond(await commands.export_messages(couple["id"]))

    @client.on(events.NewMessage(pattern=r"^/consent"))
    async def _consent(event):
        couple = _resolve_couple(event)
        if not couple:
            await event.respond("Link the couple first.")
            return
        value = event.raw_text.lower().strip().endswith("yes")
        msg = await commands.consent(couple["id"], event.sender_id, value)
        await event.respond(msg)

    @client.on(events.NewMessage(pattern=r"^/advocate"))
    async def _advocate(event):
        couple = _resolve_couple(event)
        if not couple:
            return
        issue = event.raw_text.partition(" ")[2]
        await event.respond(await commands.advocate(couple["id"], event.sender_id, issue))

    @client.on(events.NewMessage(pattern=r"^/alerts"))
    async def _alerts(event):
        couple = _resolve_couple(event)
        if not couple:
            return
        enabled = "on" in event.raw_text.lower()
        await event.respond(await commands.toggle_alerts(couple["id"], event.sender_id, enabled))

    @client.on(events.NewMessage(pattern=r"^/sla"))
    async def _sla(event):
        couple = _resolve_couple(event)
        if not couple:
            return
        try:
            minutes = int(event.raw_text.split()[1])
        except Exception:
            await event.respond("Usage: /sla <minutes>")
            return
        await event.respond(await commands.set_sla(couple["id"], event.sender_id, minutes))

    @client.on(events.NewMessage(pattern=r"^/dnd"))
    async def _dnd(event):
        couple = _resolve_couple(event)
        if not couple:
            return
        window = event.raw_text.split(" ", 1)[1] if " " in event.raw_text else ""
        await event.respond(await commands.set_dnd(couple["id"], event.sender_id, window))

    @client.on(events.NewMessage(pattern=r"^/privacy_help"))
    async def _privacy_help(event):
        await event.respond(await commands.privacy_help())

    @client.on(events.NewMessage(pattern=r"^/forget"))
    async def _forget(event):
        couple = _resolve_couple(event)
        if not couple:
            return
        await event.respond(await commands.forget(couple["id"], event.sender_id))

    @client.on(events.NewMessage(pattern=r"^/couples"))
    async def _couples(event):
        await event.respond(await commands.list_couples())

    @client.on(events.NewMessage(pattern=r"^/unlink"))
    async def _unlink(event):
        parts = event.raw_text.split()
        if len(parts) < 2:
            await event.respond("Usage: /unlink <group_id>")
            return
        await event.respond(await commands.unlink(int(parts[1])))

    @client.on(events.NewMessage(pattern=r"^/wipe"))
    async def _wipe(event):
        parts = event.raw_text.split()
        if len(parts) < 2:
            await event.respond("Usage: /wipe <couple_id>")
            return
        await event.respond(await commands.wipe(int(parts[1])))

    @client.on(events.CallbackQuery())
    async def _callbacks(event):
        handled = await wizard.handle_callback(event)
        if handled:
            return

    @client.on(events.NewMessage())
    async def _pipeline(event):
        if event.raw_text.startswith("/"):
            return
        if event.is_private and await wizard.handle_manual_input(event):
            return
        couple = _resolve_couple(event)
        if not couple:
            return
        couple_id = couple["id"]
        if commands.is_tracking_paused(couple_id):
            return
        user_a = couple["user_a_id"]
        user_b = couple["user_b_id"]
        if not (commands.has_consent(couple_id, user_a) and commands.has_consent(couple_id, user_b)):
            return

        sender_id = event.sender_id
        text = event.raw_text or ""
        ts = event.message.date or datetime.now(timezone.utc)

        db.log_message(couple_id, event.chat_id, sender_id, text, ts)

        messages = db.fetch_recent_messages(couple_id, limit=200)
        metrics = compute.compute_metrics(messages)
        flat = compute.flatten_metrics(metrics)
        prev_baselines: dict[str, float] = {}
        for key, value in flat.items():
            if isinstance(value, (int, float)):
                prev_baselines[key] = db.get_stat(
                    couple_id,
                    f"baseline:{key}",
                    default=float("nan"),
                )
                db.upsert_stat(couple_id, key, float(value))
        bands = thresholds.update_baselines(couple_id, metrics)

        # Advice refresh logic
        now = timebox.utc_now()
        for partner in (user_a, user_b):
            counter_key = f"advice_counter:{partner}"
            last_key = f"advice_last:{partner}"
            count = db.get_stat(couple_id, counter_key, default=0) + 1
            last_ts_val = db.get_stat(couple_id, last_key, default=0)
            last_dt = datetime.fromtimestamp(last_ts_val) if last_ts_val else None
            should_refresh = count >= 50 or (
                last_dt is None or (now - last_dt).total_seconds() >= 600
            )
            if should_refresh:
                advice_engine.build_advice_for_user(couple_id, partner)
                db.upsert_stat(couple_id, counter_key, 0)
                db.upsert_stat(couple_id, last_key, now.timestamp())
            else:
                db.upsert_stat(couple_id, counter_key, count)

        # Alerts
        await _maybe_fire_alerts(
            client,
            couple,
            sender_id,
            text,
            metrics,
            flat,
            ts,
            messages,
            bands,
            prev_baselines,
        )


def _resolve_couple(event) -> Optional[dict]:
    if event.is_group or event.is_channel:
        row = db.fetch_couple_by_group(event.chat_id)
        return dict(row) if row else None
    if event.is_private:
        row = db.fetch_couple_by_user(event.sender_id)
        return dict(row) if row else None
    return None


async def _maybe_fire_alerts(
    client,
    couple,
    sender_id,
    text,
    _metrics,
    flat,
    ts,
    recent_messages,
    bands,
    prev_baselines,
):
    couple_id = couple["id"]
    tz_name = couple["tz"]
    user_a = couple["user_a_id"]
    user_b = couple["user_b_id"]

    pref_a = db.fetch_pref(couple_id, user_a)
    pref_b = db.fetch_pref(couple_id, user_b)

    sla_candidates = []
    for pref in (pref_a, pref_b):
        if pref and pref["sla_minutes"]:
            sla_candidates.append(pref["sla_minutes"] * 60)
    sla_seconds = min(sla_candidates) if sla_candidates else None

    def _pref_for(user_id: int):
        if user_id == user_a:
            return pref_a
        if user_id == user_b:
            return pref_b
        return None

    def _band(key: str) -> tuple[float | None, float | None]:
        return bands.get(key, (None, None))

    def _previous_baseline(key: str) -> float | None:
        prev = prev_baselines.get(key)
        if prev is None or math.isnan(prev):
            return None
        return prev

    # Harsh start risk ping
    if classifiers.harsh_start(text):
        await pings.maybe_ping(
            client,
            couple_id=couple_id,
            user_id=sender_id,
            metric_key="harsh_start_rate",
            kind=AlertKind.RISK,
            text=pings.format_ping(
                AlertKind.RISK,
                "harsh_start_rate",
                flat.get("harsh_start_rate"),
            ),
            tz_name=tz_name,
        )
    if classifiers.is_repair_success(text):
        await pings.maybe_ping(
            client,
            couple_id=couple_id,
            user_id=sender_id,
            metric_key="repair_success",
            kind=AlertKind.PRAISE,
            text=pings.format_ping(AlertKind.PRAISE, "repair_success"),
            tz_name=tz_name,
        )
    if classifiers.is_soft_start(text):
        await pings.maybe_ping(
            client,
            couple_id=couple_id,
            user_id=sender_id,
            metric_key="soft_start",
            kind=AlertKind.PRAISE,
            text=pings.format_ping(AlertKind.PRAISE, "soft_start"),
            tz_name=tz_name,
        )
    if classifiers.is_turn_toward(text):
        await pings.maybe_ping(
            client,
            couple_id=couple_id,
            user_id=sender_id,
            metric_key="turn_toward",
            kind=AlertKind.PRAISE,
            text=pings.format_ping(AlertKind.PRAISE, "turn_toward"),
            tz_name=tz_name,
        )
    if classifiers.is_follow_through(text):
        latency = float(flat.get("follow_through_latency_hours", 0.0))
        baseline, sigma = _band("follow_through_latency_hours")
        if thresholds.evaluate_praise(
            "follow_through_latency_hours", latency, baseline, sigma
        ):
            await pings.maybe_ping(
                client,
                couple_id=couple_id,
                user_id=sender_id,
                metric_key="follow_through_latency_hours",
                kind=AlertKind.PRAISE,
                text=pings.format_ping(
                    AlertKind.PRAISE,
                    "follow_through_latency_hours",
                    latency,
                ),
                tz_name=tz_name,
            )
    if classifiers.contains_boundary_violation(text):
        await pings.maybe_ping(
            client,
            couple_id=couple_id,
            user_id=sender_id,
            metric_key="boundary_violations_per_1k",
            kind=AlertKind.RISK,
            text=pings.format_ping(
                AlertKind.RISK,
                "boundary_violations_per_1k",
                flat.get("boundary_violations_per_1k"),
            ),
            tz_name=tz_name,
        )
    if classifiers.contains_contempt(text):
        await pings.maybe_ping(
            client,
            couple_id=couple_id,
            user_id=sender_id,
            metric_key="contempt_markers_per_1k",
            kind=AlertKind.RISK,
            text=pings.format_ping(
                AlertKind.RISK,
                "contempt_markers_per_1k",
                flat.get("contempt_markers_per_1k"),
            ),
            tz_name=tz_name,
        )

    # Praise for high conflict ratio
    conflict_ratio = float(flat.get("p_to_n_conflict_ratio", 0.0))
    baseline_prev = _previous_baseline("p_to_n_conflict_ratio")
    baseline_now, sigma = _band("p_to_n_conflict_ratio")
    baseline_for_eval = baseline_prev if baseline_prev is not None else baseline_now
    if thresholds.evaluate_praise(
        "p_to_n_conflict_ratio", conflict_ratio, baseline_for_eval, sigma
    ):
        for target in (user_a, user_b):
            await pings.maybe_ping(
                client,
                couple_id=couple_id,
                user_id=target,
                metric_key="p_to_n_conflict_ratio",
                kind=AlertKind.PRAISE,
                text=pings.format_ping(
                    AlertKind.PRAISE,
                    "p_to_n_conflict_ratio",
                    conflict_ratio,
                ),
                tz_name=tz_name,
            )

    # Risky reciprocity
    reciprocity = float(flat.get("neg_affect_reciprocity", 0.0))
    baseline_prev = _previous_baseline("neg_affect_reciprocity")
    baseline_now, sigma = _band("neg_affect_reciprocity")
    baseline_for_eval = baseline_prev if baseline_prev is not None else baseline_now
    if thresholds.evaluate_risk(
        "neg_affect_reciprocity", reciprocity, baseline_for_eval, sigma
    ):
        for target in (user_a, user_b):
            await pings.maybe_ping(
                client,
                couple_id=couple_id,
                user_id=target,
                metric_key="neg_affect_reciprocity",
                kind=AlertKind.RISK,
                text=pings.format_ping(
                    AlertKind.RISK,
                    "neg_affect_reciprocity",
                    reciprocity,
                ),
                tz_name=tz_name,
            )

    for key, target in (
        ("demand_withdraw_rate.dw_AtoB", user_a),
        ("demand_withdraw_rate.dw_BtoA", user_b),
    ):
        value = float(flat.get(key, 0.0))
        baseline_now, sigma = _band(key)
        prev = prev_baselines.get(key)
        jump = False
        if prev is not None and not math.isnan(prev) and prev > 0:
            jump = value >= prev * 1.5
        baseline_for_eval = prev if prev is not None and not math.isnan(prev) else baseline_now
        if jump or thresholds.evaluate_risk(key, value, baseline_for_eval, sigma):
            await pings.maybe_ping(
                client,
                couple_id=couple_id,
                user_id=target,
                metric_key=key,
                kind=AlertKind.RISK,
                text=pings.format_ping(AlertKind.RISK, key, value),
                tz_name=tz_name,
            )

    boundary_metric = float(flat.get("boundary_violations_per_1k", 0.0))
    baseline_prev = _previous_baseline("boundary_violations_per_1k")
    baseline_now, sigma = _band("boundary_violations_per_1k")
    baseline_for_eval = baseline_prev if baseline_prev is not None else baseline_now
    if thresholds.evaluate_risk(
        "boundary_violations_per_1k", boundary_metric, baseline_for_eval, sigma
    ):
        for target in (user_a, user_b):
            await pings.maybe_ping(
                client,
                couple_id=couple_id,
                user_id=target,
                metric_key="boundary_violations_per_1k",
                kind=AlertKind.RISK,
                text=pings.format_ping(
                    AlertKind.RISK,
                    "boundary_violations_per_1k",
                    boundary_metric,
                ),
                tz_name=tz_name,
            )

    contempt_metric = float(flat.get("contempt_markers_per_1k", 0.0))
    baseline_prev = _previous_baseline("contempt_markers_per_1k")
    baseline_now, sigma = _band("contempt_markers_per_1k")
    baseline_for_eval = baseline_prev if baseline_prev is not None else baseline_now
    if thresholds.evaluate_risk(
        "contempt_markers_per_1k", contempt_metric, baseline_for_eval, sigma
    ):
        for target in (user_a, user_b):
            await pings.maybe_ping(
                client,
                couple_id=couple_id,
                user_id=target,
                metric_key="contempt_markers_per_1k",
                kind=AlertKind.RISK,
                text=pings.format_ping(
                    AlertKind.RISK,
                    "contempt_markers_per_1k",
                    contempt_metric,
                ),
                tz_name=tz_name,
            )

    # SLA miss check
    other = user_a if sender_id == user_b else user_b
    pref = _pref_for(other)
    sla_minutes = pref["sla_minutes"] if pref and pref["sla_minutes"] else 120
    last_msg = _last_message_from(messages=recent_messages, user_id=other, before=ts)
    if last_msg is not None:
        delta_minutes = (ts - last_msg).total_seconds() / 60.0
        if delta_minutes > sla_minutes:
            await pings.maybe_ping(
                client,
                couple_id=couple_id,
                user_id=other,
                metric_key="sla_miss",
                kind=AlertKind.LOGISTICS,
                text=pings.format_ping(AlertKind.LOGISTICS, "sla_miss", delta_minutes),
                tz_name=tz_name,
            )

    plan_ratio = float(flat.get("plan_to_happen_ratio", 1.0))
    if thresholds.evaluate_logistics("plan_to_happen_ratio", plan_ratio):
        for target in (user_a, user_b):
            await pings.maybe_ping(
                client,
                couple_id=couple_id,
                user_id=target,
                metric_key="plan_to_happen_ratio",
                kind=AlertKind.LOGISTICS,
                text=pings.format_ping(
                    AlertKind.LOGISTICS,
                    "plan_to_happen_ratio",
                    plan_ratio,
                ),
                tz_name=tz_name,
            )

    median_reply = float(flat.get("median_reply_seconds", 0.0))
    if thresholds.evaluate_logistics(
        "median_reply_seconds",
        median_reply,
        sla_seconds=sla_seconds,
    ):
        for target in (user_a, user_b):
            await pings.maybe_ping(
                client,
                couple_id=couple_id,
                user_id=target,
                metric_key="median_reply_seconds",
                kind=AlertKind.LOGISTICS,
                text=pings.format_ping(
                    AlertKind.LOGISTICS,
                    "median_reply_seconds",
                    median_reply,
                ),
                tz_name=tz_name,
            )


def _last_message_from(*, messages, user_id: int, before: datetime):
    for row in reversed(messages):
        ts = datetime.fromisoformat(row["ts"])
        if ts >= before:
            continue
        if row["sender_id"] == user_id:
            return ts
    return None


__all__ = ["register"]
