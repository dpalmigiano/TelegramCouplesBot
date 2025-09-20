"""Telethon event wiring."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Optional

from telethon import events

from .. import db
from ..advice import advice_engine
from ..alerts import pings
from ..metrics import compute, classifiers
from ..models import AlertKind
from ..utils import timebox
from . import commands


def register(client) -> None:
    """Register command and message handlers on the client."""

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

    @client.on(events.NewMessage())
    async def _pipeline(event):
        if event.raw_text.startswith("/"):
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
        for key, value in metrics.items():
            db.upsert_stat(couple_id, key, value)

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
        await _maybe_fire_alerts(client, couple, sender_id, text, metrics, ts, messages)


def _resolve_couple(event) -> Optional[dict]:
    if event.is_group or event.is_channel:
        row = db.fetch_couple_by_group(event.chat_id)
        return dict(row) if row else None
    if event.is_private:
        row = db.fetch_couple_by_user(event.sender_id)
        return dict(row) if row else None
    return None


async def _maybe_fire_alerts(client, couple, sender_id, text, metrics, ts, recent_messages):
    couple_id = couple["id"]
    tz_name = couple["tz"]
    # Harsh start risk ping
    if classifiers.harsh_start(text):
        await pings.maybe_ping(
            client,
            couple_id=couple_id,
            user_id=sender_id,
            metric_key="harsh_start_rate",
            kind=AlertKind.RISK,
            text=pings.format_ping(AlertKind.RISK, "harsh_start_rate", metrics.get("harsh_start_rate")),
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

    # SLA miss check
    other = couple["user_a_id"] if sender_id == couple["user_b_id"] else couple["user_b_id"]
    pref = db.fetch_pref(couple_id, other)
    sla_minutes = pref["sla_minutes"] if pref else 120
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


def _last_message_from(*, messages, user_id: int, before: datetime):
    for row in reversed(messages):
        ts = datetime.fromisoformat(row["ts"])
        if ts >= before:
            continue
        if row["sender_id"] == user_id:
            return ts
    return None


__all__ = ["register"]
