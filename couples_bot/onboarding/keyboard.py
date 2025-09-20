"""Inline keyboard helpers for onboarding."""

from __future__ import annotations

from typing import Iterable, List

from telethon import Button

PREFIX = "onboarding"


def consent_keyboard() -> List[List[Button]]:
    return [
        [
            Button.inline("I consent", f"{PREFIX}:consent:yes".encode("utf-8")),
            Button.inline("Not yet", f"{PREFIX}:consent:no".encode("utf-8")),
        ]
    ]


def timezone_keyboard(suggestions: Iterable[str]) -> List[List[Button]]:
    rows: List[List[Button]] = []
    current_row: List[Button] = []
    for tz in suggestions:
        current_row.append(Button.inline(tz, f"{PREFIX}:tz:{tz}".encode("utf-8")))
        if len(current_row) == 2:
            rows.append(current_row)
            current_row = []
    if current_row:
        rows.append(current_row)
    rows.append([Button.inline("Type manually", f"{PREFIX}:tz:manual".encode("utf-8"))])
    return rows


def dnd_keyboard() -> List[List[Button]]:
    options = ["22:00-07:00", "21:00-06:00", "00:00-08:00", "No DND"]
    rows = []
    for option in options:
        key = option if option != "No DND" else "none"
        rows.append([Button.inline(option, f"{PREFIX}:dnd:{key}".encode("utf-8"))])
    return rows


def sla_keyboard() -> List[List[Button]]:
    options = [15, 30, 45, 60, 90, 120]
    rows: List[List[Button]] = []
    current: List[Button] = []
    for minutes in options:
        current.append(Button.inline(f"{minutes} min", f"{PREFIX}:sla:{minutes}".encode("utf-8")))
        if len(current) == 3:
            rows.append(current)
            current = []
    if current:
        rows.append(current)
    return rows


def confirmation_keyboard(group_id: int) -> List[List[Button]]:
    return [
        [
            Button.inline("Looks good", f"{PREFIX}:confirm:{group_id}".encode("utf-8")),
            Button.inline("Not our group", f"{PREFIX}:abort".encode("utf-8")),
        ]
    ]


def success_keyboard() -> List[List[Button]]:
    return [[Button.inline("Thanks!", f"{PREFIX}:done".encode("utf-8"))]]
