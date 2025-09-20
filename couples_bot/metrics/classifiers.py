"""Heuristic lexicon and regex classifiers for conversational signals."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from ..utils import text as text_utils

POSITIVE_WORDS = {
    "love",
    "appreciate",
    "thanks",
    "grateful",
    "yay",
    "great",
    "nice",
    "glad",
    "sweet",
}
NEGATIVE_WORDS = {
    "angry",
    "mad",
    "annoyed",
    "frustrated",
    "upset",
    "hate",
    "tired",
    "ignored",
    "ignore",
}
REPAIR_WORDS = {
    "sorry",
    "apologize",
    "let's reset",
    "i hear you",
    "thank you for sharing",
    "i get it",
}
BID_WORDS = {
    "can we",
    "want to",
    "let's",
    "could you",
    "shall we",
    "look at",
    "hey",
}
TURN_TOWARD_WORDS = {
    "sure",
    "of course",
    "i can",
    "i will",
    "on it",
}
BOUNDARY_WORDS = {
    "ignore my boundary",
    "crossed the line",
    "not ok",
    "stop asking",
    "back off",
}
CONTEMPT_WORDS = {
    "eye roll",
    "whatever",
    "pathetic",
    "idiot",
    "disgusting",
}
FOLLOW_THROUGH_WORDS = {
    "done",
    "finished",
    "completed",
    "sent",
    "emailed",
}

HARSH_START_RE = re.compile(r"^(you\s+(?:always|never)|why are you)", re.I)
DEMAND_WITHDRAW_RE = re.compile(r"i (?:keep )?asking|you (?:never|won't)", re.I)


@dataclass
class MessageLabels:
    positive: bool = False
    negative: bool = False
    repair: bool = False
    bid: bool = False
    turn_toward: bool = False
    boundary: bool = False
    contempt: bool = False
    follow_through: bool = False
    harsh_start: bool = False


def label_text(text: str) -> MessageLabels:
    tokens = " ".join(text_utils.tokenize(text))
    labels = MessageLabels()
    labels.positive = any(word in tokens for word in POSITIVE_WORDS)
    labels.negative = any(word in tokens for word in NEGATIVE_WORDS)
    labels.repair = any(word in text.lower() for word in REPAIR_WORDS)
    labels.bid = any(word in text.lower() for word in BID_WORDS)
    labels.turn_toward = any(word in text.lower() for word in TURN_TOWARD_WORDS)
    labels.boundary = any(word in text.lower() for word in BOUNDARY_WORDS)
    labels.contempt = any(word in text.lower() for word in CONTEMPT_WORDS)
    labels.follow_through = any(word in text.lower() for word in FOLLOW_THROUGH_WORDS)
    labels.harsh_start = bool(HARSH_START_RE.search(text.strip())) or text_utils.harsh_start(text)
    return labels


def detect_demand_withdraw(text: str) -> bool:
    return bool(DEMAND_WITHDRAW_RE.search(text))


def is_conflict_message(text: str) -> bool:
    labels = label_text(text)
    return labels.negative or labels.boundary or labels.contempt


def count_positives(texts: Iterable[str]) -> int:
    return sum(1 for text in texts if label_text(text).positive)


def count_negatives(texts: Iterable[str]) -> int:
    return sum(1 for text in texts if label_text(text).negative)


def emoji_signal(text: str) -> bool:
    return text_utils.count_emojis(text) > 0


__all__ = [
    "MessageLabels",
    "label_text",
    "detect_demand_withdraw",
    "is_conflict_message",
    "count_positives",
    "count_negatives",
    "emoji_signal",
]
