"""Text processing helpers."""
from __future__ import annotations

import re
from typing import Iterable, List

EMOJI_PATTERN = re.compile(r"[\U0001F300-\U0001F6FF\U0001F900-\U0001F9FF]+", re.UNICODE)
WORD_RE = re.compile(r"[\w']+")


def tokenize(text: str) -> List[str]:
    return WORD_RE.findall(text.lower())


def count_emojis(text: str) -> int:
    return len(EMOJI_PATTERN.findall(text))


def words(text: str) -> Iterable[str]:
    for token in tokenize(text):
        yield token


def soft_start(text: str) -> bool:
    lowered = text.lower().strip()
    return bool(re.match(r"^(i\s+feel|can we|could we|i noticed)", lowered))


def harsh_start(text: str) -> bool:
    lowered = text.lower().strip()
    return lowered.startswith("you always") or lowered.startswith("you never")


def sentence_count(text: str) -> int:
    return max(1, len([s for s in re.split(r"[.!?]", text) if s.strip()]))


def strip_mentions(text: str) -> str:
    return re.sub(r"@[\w_]+", "", text)


__all__ = [
    "tokenize",
    "count_emojis",
    "words",
    "soft_start",
    "harsh_start",
    "sentence_count",
    "strip_mentions",
]
