"""Telethon event wiring."""
from __future__ import annotations

import asyncio
from typing import Optional

from telethon import events

from .. import db
from ..alerts import pings
from ..config import get_settings
from ..metrics import compute as metrics_compute
from ..metrics import thresholds
from ..metrics import classifiers
from ..models import AlertKind
from ..utils import text as text_utils
from . import commands


async def register_handlers(client) -> None:
    settings = get_settings()
    conn = db.get_conn()

    async def send_dm(user_id: int, message: str) -> None:
        await client.send_message(user_id, message)

    def schedule_send(user_id: int):
        def _sender(text: str) -> None:
            asyncio.create_task(send_dm(user_id, text))

        return _sender

    def resolve_couple_from_group(chat_id: int) -> Optional[int]:
        cur = conn.execute("SELECT id FROM couples WHERE group_chat_id = ?", (chat_id,))
        row = cur.fetchone()
        return row["id"] if row else None

    def resolve_couple_from_user(user_id: int) -> Optional[int]:
        cur = conn.execute(
            "SELECT id FROM couples WHERE user_a_id = ? OR user_b_id = ?",
            (user_id, user_id),
        )
        row = cur.fetchone()
        return row["id"] if row else None

    def couple_members(couple_id: int) -> tuple[int, int]:
        cur = conn.execute("SELECT user_a_id, user_b_id FROM couples WHERE id = ?", (couple_id,))
        row = cur.fetchone()
        if not row:
            return (0, 0)
        return int(row["user_a_id"]), int(row["user_b_id"])

    async def handle_metrics(couple_id: int) -> None:
        messages = [dict(row) for row in db.iter_messages(conn, couple_id)]
        metrics = metrics_compute.compute_metrics(messages)
        for key, value in metrics.items():
            if isinstance(value, dict):
                continue
            try:
                db.write_stat(conn, couple_id, key, float(value))
            except Exception:
                continue
        a_id, b_id = couple_members(couple_id)
        for user_id in (a_id, b_id):
            if not user_id:
                continue
            prefs = db.get_prefs(conn, couple_id, user_id)
            sla_minutes = prefs["sla_minutes"]
            for key in ("p_to_n_conflict_ratio", "harsh_start_rate", "median_reply_seconds"):
                if key not in metrics:
                    continue
                metric_value = metrics[key]
                if isinstance(metric_value, dict):
                    continue
                kind, reason = thresholds.evaluate_metric(
                    key,
                    float(metric_value),
                    sla_minutes=sla_minutes,
                )
                if kind:
                    pings.maybe_ping(
                        conn,
                        couple_id=couple_id,
                        user_id=user_id,
                        metric_key=key,
                        kind=kind,
                        text=reason,
                        send_func=schedule_send(user_id),
                    )

    @client.on(events.NewMessage(pattern=r"^/link"))
    async def handle_link(event):
        parts = event.raw_text.strip().split()
        if len(parts) < 3:
            await event.respond("Usage: /link <user_a_id> <user_b_id>")
            return
        try:
            user_a = int(parts[1].lstrip("@"))
            user_b = int(parts[2].lstrip("@"))
        except ValueError:
            await event.respond("Use numeric IDs for MVP setup.")
            return
        text = commands.link_command(conn, event.chat_id, user_a, user_b, settings.default_tz)
        await event.respond(text)

    @client.on(events.NewMessage(pattern=r"^/status"))
    async def handle_status(event):
        couple_id = resolve_couple_from_user(event.sender_id) or resolve_couple_from_group(event.chat_id)
        if not couple_id:
            await event.respond("Couple not linked yet.")
            return
        await event.respond(commands.status_command(conn, couple_id))

    @client.on(events.NewMessage(pattern=r"^/advice"))
    async def handle_advice(event):
        couple_id = resolve_couple_from_user(event.sender_id) or resolve_couple_from_group(event.chat_id)
        if not couple_id:
            await event.respond("Couple not linked yet.")
            return
        await event.respond(commands.advice_command(conn, couple_id, event.sender_id))

    @client.on(events.NewMessage(pattern=r"^/consent"))
    async def handle_consent(event):
        couple_id = resolve_couple_from_user(event.sender_id)
        if not couple_id:
            await event.respond("Consent only available after linking in a group.")
            return
        accepted = event.raw_text.strip().lower().endswith("yes")
        await event.respond(commands.consent_command(conn, couple_id, event.sender_id, accepted))

    @client.on(events.NewMessage(pattern=r"^/pause"))
    async def handle_pause(event):
        couple_id = resolve_couple_from_group(event.chat_id) or resolve_couple_from_user(event.sender_id)
        if couple_id:
            await event.respond(commands.pause_command(conn, couple_id))

    @client.on(events.NewMessage(pattern=r"^/resume"))
    async def handle_resume(event):
        couple_id = resolve_couple_from_group(event.chat_id) or resolve_couple_from_user(event.sender_id)
        if couple_id:
            await event.respond(commands.resume_command(conn, couple_id))

    @client.on(events.NewMessage(pattern=r"^/export"))
    async def handle_export(event):
        couple_id = resolve_couple_from_group(event.chat_id) or resolve_couple_from_user(event.sender_id)
        if couple_id:
            await event.respond(commands.export_command(conn, couple_id))

    @client.on(events.NewMessage(pattern=r"^/couples"))
    async def handle_admin_list(event):
        if event.sender_id != settings.bot_owner_user_id:
            return
        await event.respond(commands.admin_couples(conn))

    @client.on(events.NewMessage(pattern=r"^/unlink"))
    async def handle_unlink(event):
        if event.sender_id != settings.bot_owner_user_id:
            return
        parts = event.raw_text.strip().split()
        if len(parts) < 2:
            await event.respond("Usage: /unlink <group_id>")
            return
        await event.respond(commands.unlink_command(conn, int(parts[1])))

    @client.on(events.NewMessage(pattern=r"^/wipe"))
    async def handle_wipe(event):
        if event.sender_id != settings.bot_owner_user_id:
            return
        parts = event.raw_text.strip().split()
        if len(parts) < 2:
            await event.respond("Usage: /wipe <couple_id>")
            return
        await event.respond(commands.wipe_command(conn, int(parts[1])))

    @client.on(events.NewMessage())
    async def handle_message(event):
        if event.raw_text.startswith("/"):
            return
        couple_id = None
        if event.is_private:
            couple_id = resolve_couple_from_user(event.sender_id)
        else:
            couple_id = resolve_couple_from_group(event.chat_id)
        if not couple_id:
            return
        db.log_message(
            conn,
            couple_id=couple_id,
            chat_id=event.chat_id,
            sender_id=event.sender_id,
            text=text_utils.strip_mentions(event.raw_text),
            ts=event.message.date.isoformat(),
        )
        labels = classifiers.label_text(event.raw_text)
        a_id, b_id = couple_members(couple_id)
        if labels.harsh_start:
            pings.maybe_ping(
                conn,
                couple_id=couple_id,
                user_id=event.sender_id,
                metric_key="harsh_start",
                kind=AlertKind.RISK,
                text="Try a softer start to keep things steady.",
                send_func=schedule_send(event.sender_id),
            )
        if labels.repair:
            target = event.sender_id
            pings.maybe_ping(
                conn,
                couple_id=couple_id,
                user_id=target,
                metric_key="repair_success",
                kind=AlertKind.PRAISE,
                text="Repair attempt noticed—nice reset!",
                send_func=schedule_send(target),
            )
        if labels.turn_toward:
            pings.maybe_ping(
                conn,
                couple_id=couple_id,
                user_id=event.sender_id,
                metric_key="turn_toward",
                kind=AlertKind.PRAISE,
                text="You turned toward their bid—keep it up!",
                send_func=schedule_send(event.sender_id),
            )
        await handle_metrics(couple_id)


__all__ = ["register_handlers"]
