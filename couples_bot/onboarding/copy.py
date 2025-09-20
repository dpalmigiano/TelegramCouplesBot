"""Microcopy for the onboarding wizard."""

from __future__ import annotations

from typing import Iterable

from ..config import get_settings

_FILLED = "▰"
_EMPTY = "▱"
_TOTAL_STEPS = 5


def progress(step: int, total: int = _TOTAL_STEPS) -> str:
    step = max(0, min(step, total))
    return _FILLED * step + _EMPTY * (total - step)


def brand_prefix() -> str:
    settings = get_settings()
    return f"{settings.onboarding_emoji_style} {settings.onboarding_brand_name}"


def welcome(group_name: str) -> str:
    prefix = brand_prefix()
    return (
        f"{prefix}\n"
        f"We're almost set for {group_name}. We'll confirm the group, capture consent,"
        " and set your timezone + quiet hours—tap the buttons to move ahead."
    )


def privacy_mode_alert() -> str:
    return (
        "⚠️ Privacy mode looks enabled. Telegram stops the bot from reading the group."
        "\nTurn it off in 3 taps:\n1) DM @BotFather\n2) Send /setprivacy\n3) Pick your bot and choose 'Turn off'."
    )


def consent_prompt(partner_name: str, step: int) -> str:
    return (
        f"{progress(step)} Step {step}/{_TOTAL_STEPS}\n"
        f"{partner_name}, tap consent so we can log messages only after both of you opt in."
    )


def timezone_prompt(step: int, suggestions: Iterable[str]) -> str:
    options = ", ".join(suggestions)
    return (
        f"{progress(step)} Step {step}/{_TOTAL_STEPS}\n"
        "Pick the timezone the two of you mostly share."
        f"\nQuick picks: {options}."
    )


def dnd_prompt(step: int) -> str:
    return (
        f"{progress(step)} Step {step}/{_TOTAL_STEPS}\n"
        "Choose a Do-Not-Disturb window so pings pause while you're sleeping."
    )


def sla_prompt(step: int) -> str:
    return (
        f"{progress(step)} Step {step}/{_TOTAL_STEPS}\n"
        "How fast do you want to reply during active hours? Pick an SLA that feels doable."
    )


def success_card() -> str:
    prefix = brand_prefix()
    return (
        f"{prefix}\nAll set! The bot is listening in the group, and each partner can DM /status or /advice anytime."
        " We'll refresh guidance every few minutes and ping softly when milestones pop up."
    )


def hello_card() -> str:
    prefix = brand_prefix()
    return (
        f"{prefix}\nQuick setup: add me to your group, run /link @partnerA @partnerB, and DM /consent yes."
        " If you prefer taps, ask for a deep link and follow the wizard."
    )
