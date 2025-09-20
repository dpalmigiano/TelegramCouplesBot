"""Rule-based text classifiers for relationship signals."""

from __future__ import annotations

from typing import Dict, Optional

from ..utils import text as text_utils

POSITIVE_WORDS = {"thank", "thanks", "love", "appreciate", "glad", "great", "happy"}
NEGATIVE_WORDS = {"angry", "upset", "mad", "annoyed", "tired", "stupid"}
CONTEMPT_WORDS = {"idiot", "pathetic", "disgusting", "worthless"}
BOUNDARY_WORDS = {"you must", "you better", "or else", "i don't care"}
REPAIR_PHRASES = {"sorry", "let's reset", "i hear you", "thanks for"}
TURN_TOWARD_PHRASES = {"tell me more", "i'm listening", "what do you need"}
FOLLOW_THROUGH_PHRASES = {"i did", "finished", "done with"}

BID_LEXICON: Dict[str, set[str]] = {
    "affection": {"hug", "kiss", "miss you", "cuddle"},
    "play": {"meme", "joke", "game"},
    "gratitude": {"thank", "appreciate"},
}

COMMITMENT_WORDS = {"plan", "schedule", "book", "reserve"}
CONFIRMATION_WORDS = {"confirmed", "locked", "set", "ready"}


def sentiment_counts(text: str) -> Dict[str, int]:
    tokens = text_utils.words(text)
    pos = sum(1 for token in tokens if token in POSITIVE_WORDS)
    neg = sum(1 for token in tokens if token in NEGATIVE_WORDS)
    return {"positive": pos, "negative": neg}


def contains_contempt(text: str) -> bool:
    return text_utils.contains_any(text, CONTEMPT_WORDS)


def contains_boundary_violation(text: str) -> bool:
    return text_utils.contains_any(text, BOUNDARY_WORDS)


def is_repair_attempt(text: str) -> bool:
    return text_utils.contains_any(text, REPAIR_PHRASES)


def is_repair_success(text: str) -> bool:
    return text_utils.contains_any(text, {"thanks", "appreciate"})


def is_turn_toward(text: str) -> bool:
    return text_utils.contains_any(text, TURN_TOWARD_PHRASES)


def is_follow_through(text: str) -> bool:
    return text_utils.contains_any(text, FOLLOW_THROUGH_PHRASES)


def harsh_start(text: str) -> bool:
    return text_utils.sentence_starts_harsh(text)


def classify_bid(text: str) -> Optional[str]:
    lowered = text.lower()
    for bid_type, phrases in BID_LEXICON.items():
        if any(phrase in lowered for phrase in phrases):
            return bid_type
    return None


def contains_commitment(text: str) -> bool:
    return text_utils.contains_any(text, COMMITMENT_WORDS)


def contains_confirmation(text: str) -> bool:
    return text_utils.contains_any(text, CONFIRMATION_WORDS)


def emoji_count(text: str) -> int:
    return text_utils.count_emojis(text)


__all__ = [
    "sentiment_counts",
    "contains_contempt",
    "contains_boundary_violation",
    "is_repair_attempt",
    "is_repair_success",
    "is_turn_toward",
    "is_follow_through",
    "harsh_start",
    "classify_bid",
    "contains_commitment",
    "contains_confirmation",
    "emoji_count",
]
