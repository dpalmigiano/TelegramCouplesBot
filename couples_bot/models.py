"""Shared models for the couples bot."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional, TypedDict


class Message(TypedDict):
    id: int
    chat_id: int
    sender_id: int
    text: str
    ts: datetime
    couple_id: int


class Couple(TypedDict, total=False):
    id: int
    user_a_id: int
    user_b_id: int
    group_chat_id: int
    tz: str
    created_at: datetime


class Advice(TypedDict):
    couple_id: int
    for_user_id: int
    advice_text: str
    updated_at: datetime


class AlertKind(str, Enum):
    PRAISE = "praise"
    RISK = "risk"
    LOGISTICS = "logistics"


__all__ = ["Message", "Couple", "Advice", "AlertKind"]
