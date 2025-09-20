"""Metric computation utilities."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from statistics import median
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import sqlite3

from ..utils import text as text_utils
from . import classifiers


MessageRow = sqlite3.Row

FUNCTION_WORD_CATEGORIES = {
    "pronouns": {"i", "me", "my", "you", "your", "we", "us", "our", "they", "them"},
    "articles": {"a", "an", "the"},
    "prepositions": {
        "in",
        "on",
        "to",
        "for",
        "with",
        "at",
        "from",
        "about",
        "by",
        "over",
        "after",
    },
    "aux_verbs": {"am", "is", "are", "was", "were", "be", "been", "being", "have", "has", "had"},
    "conjunctions": {"and", "but", "or", "so", "yet", "if", "because"},
    "adverbs": {"really", "very", "so", "too", "quite", "just"},
    "negations": {"not", "no", "never", "n't"},
}

WE_WORDS = {"we", "us", "our", "ours", "let's"}
I_YOU_WORDS = {"i", "me", "my", "mine", "you", "your", "yours"}
BLAME_PHRASES = {"your fault", "because you", "you never", "you always"}
SOON_WORDS = {"tonight", "today", "tomorrow", "noon", "morning", "evening"}


def _hours_span(messages: Sequence[MessageRow]) -> float:
    if not messages:
        return 1.0
    start = datetime.fromisoformat(messages[0]["ts"])
    end = datetime.fromisoformat(messages[-1]["ts"])
    span = (end - start).total_seconds() / 3600.0
    return max(span, 1 / 60)


def _empty_metrics() -> Dict[str, float | str]:
    keys = [
        "p_to_n_conflict_ratio",
        "harsh_start_rate",
        "repair_attempts_per_hour",
        "repair_effectiveness_pct",
        "neg_affect_reciprocity",
        "demand_withdraw_rate_AtoB",
        "demand_withdraw_rate_BtoA",
        "bid_response_ratio_affection",
        "bid_response_ratio_play",
        "bid_response_ratio_gratitude",
        "median_reply_seconds",
        "p90_reply_seconds",
        "reply_variability",
        "emoji_signal_rate",
        "lsm_score",
        "we_talk_index",
        "we_talk_index_context",
        "affection_density",
        "gratitude_density",
        "future_planning_density",
        "plan_to_happen_ratio",
        "follow_through_latency_hours",
        "support_balance_index",
        "boundary_violations_per_1k",
        "contempt_markers_per_1k",
        "ruptures_per_month",
        "median_repair_cycle_hours",
    ]
    return {key: ("neutral" if key == "we_talk_index_context" else 0.0) for key in keys}


def _participants(rows: Sequence[MessageRow]) -> Tuple[Optional[int], Optional[int]]:
    seen: List[int] = []
    for row in rows:
        sender = int(row["sender_id"])
        if sender not in seen:
            seen.append(sender)
        if len(seen) == 2:
            break
    if not seen:
        return None, None
    if len(seen) == 1:
        return seen[0], None
    return seen[0], seen[1]


def _due_soon(text: str) -> bool:
    lowered = text.lower()
    return any(word in lowered for word in SOON_WORDS)


def compute_metrics(messages: Iterable[MessageRow]) -> Dict[str, float | str]:
    """Return the full scoreboard for a conversation sample."""

    rows = list(messages)
    metrics: Dict[str, float | str] = _empty_metrics()

    if not rows:
        return metrics

    rows_sorted = sorted(rows, key=lambda r: r["ts"])
    span_hours = _hours_span(rows_sorted)
    total_messages = max(len(rows_sorted), 1)

    user_a, user_b = _participants(rows_sorted)

    total_pos = 0
    total_neg = 0
    harsh = 0
    repair_attempt_indexes: List[int] = []
    repair_successes = 0
    pending_repairs: List[int] = []
    bid_counts = defaultdict(int)
    bid_responses = defaultdict(int)
    boundary_count = 0
    contempt_count = 0
    rupture_times: List[datetime] = []
    repair_cycles: List[float] = []

    last_message_time: Optional[datetime] = None
    last_sender: Optional[int] = None
    reply_deltas: List[float] = []

    neg_follow_neg = 0
    neg_follow_neg_total = 0
    neg_follow_neutral = 0
    neutral_total = 0
    prev_neg_flag: Optional[bool] = None

    demand_counts = {"AtoB": 0, "BtoA": 0}

    emoji_total = 0
    affection_msgs = 0
    gratitude_msgs = 0
    planning_msgs = 0

    commitments: List[dict] = []
    follow_latencies: List[float] = []
    soon_commitments = 0
    soon_completions = 0

    support_stats = defaultdict(lambda: {"offers": 0, "asks": 0, "completions": 0})

    tokens_by_user = defaultdict(list)

    we_count = 0
    i_you_count = 0
    we_plans = 0
    we_blame = 0

    for idx, row in enumerate(rows_sorted):
        text = row["text"] or ""
        sender = int(row["sender_id"])
        ts = datetime.fromisoformat(row["ts"])

        counts = classifiers.sentiment_counts(text)
        pos = counts["positive"]
        neg = counts["negative"]
        total_pos += pos
        total_neg += neg
        is_negative = bool(neg) or classifiers.contains_boundary_violation(text) or classifiers.contains_contempt(text)
        if classifiers.harsh_start(text):
            harsh += 1
            is_negative = True

        if classifiers.is_repair_attempt(text):
            repair_attempt_indexes.append(idx)
            pending_repairs.append(sender)
        if pending_repairs and sender != pending_repairs[0] and classifiers.is_repair_success(text):
            repair_successes += 1
            pending_repairs.pop(0)

        bid_type = classifiers.classify_bid(text)
        if bid_type:
            bid_counts[bid_type] += 1
            partner = user_b if sender == user_a else user_a
            if partner is None:
                partner = sender
            for follow in rows_sorted[idx + 1 :]:
                follow_ts = datetime.fromisoformat(follow["ts"])
                if follow_ts - ts > timedelta(hours=6):
                    break
                if int(follow["sender_id"]) != partner:
                    continue
                if classifiers.is_turn_toward(follow["text"]) or classifiers.is_repair_success(follow["text"]):
                    bid_responses[bid_type] += 1
                elif classifiers.sentiment_counts(follow["text"])["positive"] >= 1:
                    bid_responses[bid_type] += 1
                break

        if classifiers.contains_boundary_violation(text):
            boundary_count += 1
        if classifiers.contains_contempt(text):
            contempt_count += 1
            rupture_times.append(ts)

        emoji_total += classifiers.emoji_count(text)
        if classifiers.is_affection(text):
            affection_msgs += 1
        if classifiers.is_gratitude(text):
            gratitude_msgs += 1
        if classifiers.contains_commitment(text) or classifiers.mentions_future(text):
            planning_msgs += 1

        if classifiers.contains_commitment(text):
            soon = _due_soon(text)
            commitments.append({"ts": ts, "sender": sender, "soon": soon, "resolved": False})
            if soon:
                soon_commitments += 1

        if classifiers.contains_confirmation(text) or classifiers.is_follow_through(text):
            support_stats[sender]["completions"] += 1
            for item in commitments:
                if item["resolved"]:
                    continue
                latency = (ts - item["ts"]).total_seconds() / 3600.0
                follow_latencies.append(latency)
                item["resolved"] = True
                if item["soon"]:
                    soon_completions += 1
                break

        if classifiers.is_support_offer(text):
            support_stats[sender]["offers"] += 1
        if classifiers.is_support_request(text):
            support_stats[sender]["asks"] += 1

        # Demand/withdraw pattern
        if user_a is not None and user_b is not None and classifiers.is_demand(text):
            partner = user_b if sender == user_a else user_a
            for follow in rows_sorted[idx + 1 :]:
                follow_ts = datetime.fromisoformat(follow["ts"])
                if follow_ts - ts > timedelta(hours=6):
                    break
                if int(follow["sender_id"]) != partner:
                    continue
                if classifiers.is_withdraw(follow["text"]):
                    if sender == user_a:
                        demand_counts["AtoB"] += 1
                    else:
                        demand_counts["BtoA"] += 1
                break

        # Reciprocity calculations
        if last_message_time is not None and sender != last_sender:
            delta = (ts - last_message_time).total_seconds()
            if delta <= 6 * 3600:
                reply_deltas.append(delta)

        if last_sender is not None and sender != last_sender:
            if prev_neg_flag:
                neg_follow_neg_total += 1
                if is_negative:
                    neg_follow_neg += 1
            else:
                neutral_total += 1
                if is_negative:
                    neg_follow_neutral += 1

        prev_neg_flag = is_negative
        last_message_time = ts
        last_sender = sender

        tokens = text_utils.words(text)
        tokens_by_user[sender].extend(tokens)
        we_tokens = [tok for tok in tokens if tok in WE_WORDS]
        i_you_tokens = [tok for tok in tokens if tok in I_YOU_WORDS]
        we_count += len(we_tokens)
        i_you_count += len(i_you_tokens)
        if we_tokens:
            if classifiers.mentions_future(text):
                we_plans += 1
            if any(phrase in text.lower() for phrase in BLAME_PHRASES):
                we_blame += 1

    # Sentiment ratios
    metrics["p_to_n_conflict_ratio"] = (total_pos + 1) / (total_neg + 1)
    metrics["harsh_start_rate"] = harsh / total_messages
    metrics["repair_attempts_per_hour"] = len(repair_attempt_indexes) / span_hours
    metrics["repair_effectiveness_pct"] = (
        (repair_successes / len(repair_attempt_indexes)) * 100 if repair_attempt_indexes else 0.0
    )

    if neg_follow_neg_total:
        p_neg_after_neg = neg_follow_neg / neg_follow_neg_total
    else:
        p_neg_after_neg = 0.0
    if neutral_total:
        p_neg_after_neutral = neg_follow_neutral / neutral_total
    else:
        p_neg_after_neutral = 0.0
    metrics["neg_affect_reciprocity"] = p_neg_after_neg - p_neg_after_neutral

    metrics["demand_withdraw_rate_AtoB"] = (demand_counts["AtoB"] * 1000) / total_messages
    metrics["demand_withdraw_rate_BtoA"] = (demand_counts["BtoA"] * 1000) / total_messages

    for bid_type in ("affection", "play", "gratitude"):
        total = bid_counts[bid_type]
        responded = bid_responses[bid_type]
        metrics[f"bid_response_ratio_{bid_type}"] = responded / total if total else 0.0

    if reply_deltas:
        sorted_deltas = sorted(reply_deltas)
        metrics["median_reply_seconds"] = median(sorted_deltas)
        p90_index = max(int(0.9 * (len(sorted_deltas) - 1)), 0)
        metrics["p90_reply_seconds"] = sorted_deltas[p90_index]
        metrics["reply_variability"] = metrics["p90_reply_seconds"] - metrics["median_reply_seconds"]
    else:
        metrics["median_reply_seconds"] = 0.0
        metrics["p90_reply_seconds"] = 0.0
        metrics["reply_variability"] = 0.0

    metrics["emoji_signal_rate"] = emoji_total / total_messages

    # Language style matching
    if user_a is not None and user_b is not None:
        scores: List[float] = []
        tokens_a = tokens_by_user[user_a]
        tokens_b = tokens_by_user[user_b]
        for words in FUNCTION_WORD_CATEGORIES.values():
            count_a = sum(1 for token in tokens_a if token in words)
            count_b = sum(1 for token in tokens_b if token in words)
            total_cat = count_a + count_b
            if total_cat == 0:
                continue
            freq_a = count_a / max(len(tokens_a), 1)
            freq_b = count_b / max(len(tokens_b), 1)
            numerator = abs(freq_a - freq_b)
            denominator = freq_a + freq_b if (freq_a + freq_b) else 1.0
            scores.append(1 - numerator / denominator)
        metrics["lsm_score"] = sum(scores) / len(scores) if scores else 0.0
    else:
        metrics["lsm_score"] = 0.0

    metrics["we_talk_index"] = (we_count + 1) / (i_you_count + 1)
    if we_plans > we_blame:
        metrics["we_talk_index_context"] = "plans"
    elif we_blame > we_plans:
        metrics["we_talk_index_context"] = "blame"
    else:
        metrics["we_talk_index_context"] = "neutral"

    metrics["affection_density"] = (affection_msgs * 100) / total_messages
    metrics["gratitude_density"] = (gratitude_msgs * 100) / total_messages
    metrics["future_planning_density"] = (planning_msgs * 100) / total_messages

    metrics["plan_to_happen_ratio"] = (
        soon_completions / soon_commitments if soon_commitments else 1.0
    )

    metrics["follow_through_latency_hours"] = median(follow_latencies) if follow_latencies else 0.0

    if user_a is not None:
        stats_a = support_stats[user_a]
    else:
        stats_a = {"offers": 0, "asks": 0, "completions": 0}
    if user_b is not None:
        stats_b = support_stats[user_b]
    else:
        stats_b = {"offers": 0, "asks": 0, "completions": 0}
    balance_a = stats_a["offers"] + stats_a["completions"] - stats_a["asks"]
    balance_b = stats_b["offers"] + stats_b["completions"] - stats_b["asks"]
    metrics["support_balance_index"] = balance_a - balance_b

    metrics["boundary_violations_per_1k"] = (boundary_count * 1000) / total_messages
    metrics["contempt_markers_per_1k"] = (contempt_count * 1000) / total_messages

    if rupture_times and repair_attempt_indexes:
        for rupture_time in rupture_times:
            closes = [
                datetime.fromisoformat(rows_sorted[idx]["ts"])
                for idx in repair_attempt_indexes
                if datetime.fromisoformat(rows_sorted[idx]["ts"]) > rupture_time
            ]
            if closes:
                delta = (min(closes) - rupture_time).total_seconds() / 3600.0
                repair_cycles.append(delta)

    metrics["ruptures_per_month"] = len(rupture_times) * 30 / max(span_hours / 24, 1)
    metrics["median_repair_cycle_hours"] = median(repair_cycles) if repair_cycles else 0.0

    return metrics


__all__ = ["compute_metrics"]
