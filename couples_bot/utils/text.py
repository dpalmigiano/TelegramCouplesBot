"""Text helpers for heuristics."""

from __future__ import annotations

import re
from typing import Iterable, List

TOKEN_RE = re.compile(r"\w+|[\!\?\.]|")
EMOJI_RE = re.compile(
    "[\U0001F300-\U0001F6FF\U0001F900-\U0001F9FF\U0001FA70-\U0001FAFF]",
    flags=re.UNICODE,
)


def tokenize(text: str) -> List[str]:
    return re.findall(r"[\w']+|[.!?]", text.lower())


def count_emojis(text: str) -> int:
    return len(EMOJI_RE.findall(text))


def contains_any(text: str, phrases: Iterable[str]) -> bool:
    lowered = text.lower()
    return any(phrase in lowered for phrase in phrases)


def words(text: str) -> List[str]:
    return re.findall(r"[a-zA-Z']+", text.lower())


def sentence_starts_harsh(text: str) -> bool:
    harsh_openers = {"you never", "you always", "why would", "what's wrong"}
    return any(lowered in text.lower() for lowered in harsh_openers)

