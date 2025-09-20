"""Rule-based text classifiers for relationship signals."""

from __future__ import annotations

from typing import Dict, Optional

from ..utils import text as text_utils

POSITIVE_WORDS = {
    "thank",
    "thanks",
    "love",
    "appreciate",
    "glad",
    "great",
    "happy",
    "cheers",
    "grateful",
    "awesome",
}
NEGATIVE_WORDS = {
    "angry",
    "upset",
    "mad",
    "annoyed",
    "tired",
    "stupid",
    "hate",
    "frustrated",
    "irritated",
}
CONTEMPT_WORDS = {"idiot", "pathetic", "disgusting", "worthless", "loser"}
BOUNDARY_WORDS = {
    "you must",
    "you better",
    "or else",
    "i don't care",
    "you have to",
    "you need to",
}
REPAIR_PHRASES = {"sorry", "let's reset", "i hear you", "thanks for", "i was wrong"}
TURN_TOWARD_PHRASES = {"tell me more", "i'm listening", "what do you need", "i'm here"}
FOLLOW_THROUGH_PHRASES = {"i did", "finished", "done with", "took care of", "handled"}
SOFT_START_PHRASES = {
    "i feel",
    "i noticed",
    "i'm feeling",
    "can we",
    "could we",
    "i appreciate",
}
DEMAND_PHRASES = {
    "you must",
    "you need to",
    "i expect you",
    "you have to",
    "do it now",
    "why haven't you",
}
WITHDRAW_PHRASES = {
    "fine",
    "whatever",
    "forget it",
    "leave it",
    "later",
    "can't right now",
    "idk",
    "i'm tired",
    "not now",
}
AFFECTION_WORDS = {"love", "dear", "babe", "sweetie", "hug", "kiss", "admire"}
GRATITUDE_WORDS = {"thank", "thanks", "grateful", "appreciate", "gratitude"}
FUTURE_WORDS = {"plan", "schedule", "book", "reserve", "tomorrow", "tonight", "later"}
SUPPORT_OFFER_PHRASES = {
    "i can",
    "i'll handle",
    "let me",
    "i've got",
    "i will take",
    "i'll swing by",
}
SUPPORT_REQUEST_PHRASES = {
    "can you",
    "could you",
    "would you",
    "please",
    "i need you",
    "will you",
}

BID_LEXICON: Dict[str, set[str]] = {
    "affection": {"hug", "kiss", "miss you", "cuddle", "hold hands"},
    "play": {"meme", "joke", "game", "funny"},
    "gratitude": {"thank", "appreciate", "grateful"},
}

COMMITMENT_WORDS = {"plan", "schedule", "book", "reserve", "setup", "organize"}
CONFIRMATION_WORDS = {"confirmed", "locked", "set", "ready", "done", "sent"}


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


def is_soft_start(text: str) -> bool:
    return text_utils.contains_any(text, SOFT_START_PHRASES)


def is_demand(text: str) -> bool:
    lowered = text.lower()
    return any(phrase in lowered for phrase in DEMAND_PHRASES)


def is_withdraw(text: str) -> bool:
    tokens = text_utils.words(text)
    lowered = text.lower()
    if any(phrase in lowered for phrase in WITHDRAW_PHRASES):
        return True
    return len(tokens) <= 3 and any(
        token in {"fine", "ok", "whatever", "later", "busy", "maybe"}
        for token in tokens
    )


def is_support_offer(text: str) -> bool:
    lowered = text.lower()
    return any(phrase in lowered for phrase in SUPPORT_OFFER_PHRASES)


def is_support_request(text: str) -> bool:
    lowered = text.lower()
    return any(phrase in lowered for phrase in SUPPORT_REQUEST_PHRASES)


def is_affection(text: str) -> bool:
    tokens = text_utils.words(text)
    return any(token in AFFECTION_WORDS for token in tokens)


def is_gratitude(text: str) -> bool:
    tokens = text_utils.words(text)
    return any(token in GRATITUDE_WORDS for token in tokens)


def mentions_future(text: str) -> bool:
    tokens = text_utils.words(text)
    return any(token in FUTURE_WORDS for token in tokens)


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
    "is_soft_start",
    "is_demand",
    "is_withdraw",
    "is_support_offer",
    "is_support_request",
    "is_affection",
    "is_gratitude",
    "mentions_future",
    "harsh_start",
    "classify_bid",
    "contains_commitment",
    "contains_confirmation",
    "emoji_count",
]
