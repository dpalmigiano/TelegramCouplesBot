"""Tap-first onboarding wizard orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Tuple
from zoneinfo import ZoneInfo

from telethon import events
from telethon.errors import RPCError

from .. import db
from ..bot import commands
from ..config import get_settings
from . import copy, keyboard

_PREFIX = "onboarding"
_PENDING_MANUAL: Dict[int, Tuple[str, int]] = {}


@dataclass
class DeepLinkPayload:
    group_id: int
    user_a: int
    user_b: int


class OnboardingWizard:
    """State-light onboarding wizard using inline buttons."""

    def __init__(self, client):
        self.client = client
        self.settings = get_settings()

    @staticmethod
    def _parse_payload(payload: str | None) -> Optional[DeepLinkPayload]:
        if not payload or not payload.startswith("link_"):
            return None
        parts = payload.split("_")
        if len(parts) != 4:
            return None
        try:
            group_id = int(parts[1])
            user_a = int(parts[2])
            user_b = int(parts[3])
        except ValueError:
            return None
        return DeepLinkPayload(group_id=group_id, user_a=user_a, user_b=user_b)

    async def handle_start(self, event: events.NewMessage.Event, payload: str | None) -> None:
        if not self.settings.onboarding_deep_links:
            await event.respond(
                "Deep links are disabled for this bot. Ask your coach to run /link in the group."
            )
            return

        parsed = self._parse_payload(payload)
        if not parsed:
            await event.respond(copy.hello_card())
            return

        if event.sender_id not in {parsed.user_a, parsed.user_b}:
            await event.respond("This invite was generated for a different couple. Request a new link.")
            return

        couple_id = db.link_couple(
            parsed.user_a,
            parsed.user_b,
            parsed.group_id,
            self.settings.default_tz,
        )
        db.set_pref(couple_id, parsed.user_a, sla_minutes=120, enable_alerts=True)
        db.set_pref(couple_id, parsed.user_b, sla_minutes=120, enable_alerts=True)

        group_name = f"chat {parsed.group_id}"
        try:
            dialog = await self.client.get_entity(parsed.group_id)
            title = getattr(dialog, "title", None)
            if title:
                group_name = title
        except Exception:  # pragma: no cover - network/permissions
            pass

        await event.respond(
            copy.welcome(group_name),
            buttons=keyboard.confirmation_keyboard(parsed.group_id),
        )

        privacy_flag = await self._privacy_mode_enabled(parsed.group_id)
        if privacy_flag:
            await event.respond(copy.privacy_mode_alert())

    async def _privacy_mode_enabled(self, group_id: int) -> bool:
        try:
            await self.client.get_messages(group_id, limit=1)
            return False
        except RPCError as exc:  # pragma: no cover - depends on Telegram state
            text = exc.__class__.__name__.lower()
            return any(token in text for token in ("privacy", "bot", "forbidden"))
        except Exception:  # pragma: no cover - fallback
            return True

    async def handle_callback(self, event: events.CallbackQuery.Event) -> bool:
        data = event.data.decode("utf-8")
        if not data.startswith(_PREFIX):
            return False
        await event.answer()
        parts = data.split(":")
        action = parts[1] if len(parts) > 1 else ""
        if action == "confirm" and len(parts) >= 3:
            await self._handle_confirm(event)
            return True
        if action == "abort":
            await event.edit("No worries—run /link in the group when you're ready.")
            return True
        if action == "consent" and len(parts) >= 3:
            await self._handle_consent(event, parts[2])
            return True
        if action == "tz" and len(parts) >= 3:
            await self._handle_timezone(event, parts[2])
            return True
        if action == "dnd" and len(parts) >= 3:
            await self._handle_dnd(event, parts[2])
            return True
        if action == "sla" and len(parts) >= 3:
            await self._handle_sla(event, parts[2])
            return True
        if action == "done":
            await event.edit("Thanks for setting things up! 🎉")
            return True
        return False

    async def _handle_confirm(self, event: events.CallbackQuery.Event) -> None:
        couple = db.fetch_couple_by_user(event.sender_id)
        if not couple:
            await event.edit("Need to link the couple first—ask for a fresh invite.")
            return
        await event.edit("Great, let's capture consent next.")
        await event.respond(
            copy.consent_prompt("You", 1),
            buttons=keyboard.consent_keyboard(),
        )

    async def _handle_consent(self, event: events.CallbackQuery.Event, value: str) -> None:
        couple = db.fetch_couple_by_user(event.sender_id)
        if not couple:
            await event.respond("Couple not linked yet. Use /link in the group.")
            return
        couple_id = couple["id"]
        if value == "yes":
            msg = await commands.consent(couple_id, event.sender_id, True)
            await event.edit("Consent captured—thanks!")
            await event.respond(msg)
            await event.respond(
                copy.timezone_prompt(2, self.settings.onboarding_tz_suggestions),
                buttons=keyboard.timezone_keyboard(self.settings.onboarding_tz_suggestions),
            )
        else:
            await event.edit("Okay, ping me when you're ready to opt in.")

    async def _handle_timezone(self, event: events.CallbackQuery.Event, token: str) -> None:
        couple = db.fetch_couple_by_user(event.sender_id)
        if not couple:
            await event.respond("Couple not linked yet.")
            return
        couple_id = couple["id"]
        if token == "manual":
            _PENDING_MANUAL[event.sender_id] = ("tz", couple_id)
            await event.edit("Type your timezone (e.g. Europe/London).")
            return
        tz_value = token
        try:
            ZoneInfo(tz_value)
        except Exception:
            await event.edit("Didn't recognise that timezone. Try 'Type manually'.")
            return
        db.update_couple_tz(couple_id, tz_value)
        await event.edit(f"Timezone set to {tz_value}.")
        await event.respond(copy.dnd_prompt(3), buttons=keyboard.dnd_keyboard())

    async def _handle_dnd(self, event: events.CallbackQuery.Event, token: str) -> None:
        couple = db.fetch_couple_by_user(event.sender_id)
        if not couple:
            await event.respond("Couple not linked yet.")
            return
        couple_id = couple["id"]
        user_id = event.sender_id
        partner_id = self._other_partner(couple, user_id)
        if token == "none":
            db.set_pref(couple_id, user_id, dnd_start="", dnd_end="")
            db.set_pref(couple_id, partner_id, dnd_start="", dnd_end="")
            await event.edit("No DND window set.")
        else:
            start, end = token.split("-", 1)
            db.set_pref(couple_id, user_id, dnd_start=start, dnd_end=end)
            db.set_pref(couple_id, partner_id, dnd_start=start, dnd_end=end)
            await event.edit(f"Quiet hours saved: {token}.")
        await event.respond(copy.sla_prompt(4), buttons=keyboard.sla_keyboard())

    async def _handle_sla(self, event: events.CallbackQuery.Event, token: str) -> None:
        couple = db.fetch_couple_by_user(event.sender_id)
        if not couple:
            await event.respond("Couple not linked yet.")
            return
        couple_id = couple["id"]
        try:
            minutes = int(token)
        except ValueError:
            await event.edit("Pick one of the preset reply windows.")
            return
        partner_id = self._other_partner(couple, event.sender_id)
        await commands.set_sla(couple_id, event.sender_id, minutes)
        await commands.set_sla(couple_id, partner_id, minutes)
        await event.edit(f"Reply target set to {minutes} minutes.")
        await event.respond(copy.success_card(), buttons=keyboard.success_keyboard())

    async def handle_manual_input(self, event: events.NewMessage.Event) -> bool:
        entry = _PENDING_MANUAL.get(event.sender_id)
        if not entry:
            return False
        kind, couple_id = entry
        text = event.raw_text.strip()
        if kind == "tz":
            try:
                ZoneInfo(text)
            except Exception:
                await event.respond("Couldn't parse that timezone—try format like Continent/City.")
                return True
            db.update_couple_tz(couple_id, text)
            _PENDING_MANUAL.pop(event.sender_id, None)
            await event.respond(copy.dnd_prompt(3), buttons=keyboard.dnd_keyboard())
            return True
        return False

    @staticmethod
    def _other_partner(couple_row, user_id: int) -> int:
        if couple_row["user_a_id"] == user_id:
            return couple_row["user_b_id"]
        return couple_row["user_a_id"]


__all__ = ["OnboardingWizard"]
