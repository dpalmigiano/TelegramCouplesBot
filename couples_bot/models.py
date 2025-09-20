"""Shared models used across the application."""
from __future__ import annotations

from enum import Enum
from typing import Optional, TypedDict


class Message(TypedDict, total=False):
    id: int
    chat_id: int
    sender_id: int
    text: str
    ts: str
    couple_id: int


class Couple(TypedDict, total=False):
    id: int
    user_a_id: int
    user_b_id: int
    group_chat_id: int
    tz: str
    created_at: str


class Advice(TypedDict, total=False):
    couple_id: int
    for_user_id: int
    advice_text: str
    updated_at: str


class AlertKind(str, Enum):
    PRAISE = "praise"
    RISK = "risk"
    LOGISTICS = "logistics"


__all__ = ["Message", "Couple", "Advice", "AlertKind"]
