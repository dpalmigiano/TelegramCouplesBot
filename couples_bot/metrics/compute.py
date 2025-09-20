"""Metric computation utilities."""

from __future__ import annotations

from collections import defaultdict, deque
from datetime import datetime, timedelta
from statistics import median
from typing import Dict, Iterable, List, Mapping, Optional, Sequence

import sqlite3

from ..utils import text as text_utils
from . import classifiers

MessageRow = sqlite3.Row | Mapping[str, object]

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


def _get(row: MessageRow, key: str) -> object:
    if isinstance(row, Mapping):
        return row[key]
    return row[key]


def _hours_span(messages: Sequence[MessageRow]) -> float:
    if not messages:
        return 1.0
    start = datetime.fromisoformat(str(_get(messages[0], "ts")))
    end = datetime.fromisoformat(str(_get(messages[-1], "ts")))
    span = (end - start).total_seconds() / 3600.0
    return max(span, 1 / 60)


def _participants(rows: Sequence[MessageRow]) -> tuple[Optional[int], Optional[int]]:
    seen: List[int] = []
    for row in rows:
        sender = int(_get(row, "sender_id"))
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


def _empty_metrics() -> Dict[str, object]:
    return {
        "p_to_n_conflict_ratio": 0.0,
        "harsh_start_rate": 0.0,
        "repair_attempts_per_hour": 0.0,
        "repair_effectiveness_pct": 0.0,
        "neg_affect_reciprocity": 0.0,
        "demand_withdraw_rate": {"dw_AtoB": 0.0, "dw_BtoA": 0.0},
        "bid_response_ratio": {"affection": 0.0, "info": 0.0, "play": 0.0, "requests": 0.0},
        "median_reply_seconds": 0.0,
        "p90_reply_seconds": 0.0,
        "reply_variability": 0.0,
        "emoji_signal_rate": 0.0,
        "lsm_score": 0.0,
        "we_talk_index": {"value": 0.0, "context": "neutral"},
        "affection_density": 0.0,
        "gratitude_density": 0.0,
        "future_planning_density": 0.0,
        "plan_to_happen_ratio": 1.0,
        "follow_through_latency_hours": 0.0,
        "support_balance_index": {"A": 0.0, "B": 0.0},
        "boundary_violations_per_1k": 0.0,
        "contempt_markers_per_1k": 0.0,
        "ruptures_per_month": 0.0,
        "median_repair_cycle_hours": 0.0,
    }


def flatten_metrics(metrics: Mapping[str, object]) -> Dict[str, object]:
    flat: Dict[str, object] = {}
    for key, value in metrics.items():
        if isinstance(value, Mapping):
            for sub_key, sub_value in value.items():
                flat[f"{key}.{sub_key}"] = sub_value
        else:
            flat[key] = value
    return flat


def compute_metrics(messages: Iterable[MessageRow]) -> Dict[str, object]:
    """Return the full scoreboard for a conversation sample."""

    rows = list(messages)
    if not rows:
        return _empty_metrics()

    rows_sorted = sorted(rows, key=lambda r: _get(r, "ts"))
    metrics = _empty_metrics()

    span_hours = _hours_span(rows_sorted)
    total_messages = max(len(rows_sorted), 1)

    user_a, user_b = _participants(rows_sorted)
    partner_map = {}
    if user_a is not None:
        partner_map[user_a] = user_b
    if user_b is not None:
        partner_map[user_b] = user_a

    conflict_pos = 0
    conflict_neg = 0
    total_pos = 0
    total_neg = 0

    harsh = 0
    repair_attempts: List[dict] = []
    repair_successes = 0
    open_repairs: List[dict] = []
    repair_success_times: List[datetime] = []

    neg_follow_neg = 0
    neg_follow_neg_total = 0
    neg_follow_neutral = 0
    neutral_total = 0
    prev_neg_flag: Optional[bool] = None
    prev_sender: Optional[int] = None
    prev_ts: Optional[datetime] = None

    bid_counts = defaultdict(int)
    bid_responses = defaultdict(int)

    demand_events: List[dict] = []
    demand_counts = {"dw_AtoB": 0, "dw_BtoA": 0}

    reply_deltas: List[float] = []
    emoji_total = 0

    boundary_count = 0
    contempt_count = 0
    rupture_times: List[datetime] = []

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

    conflict_window: deque[MessageRow] = deque(maxlen=10)

    for row in rows_sorted:
        text = str(_get(row, "text") or "")
        sender = int(_get(row, "sender_id"))
        ts = datetime.fromisoformat(str(_get(row, "ts")))

        conflict_window.append(row)

        counts = classifiers.sentiment_counts(text)
        pos = counts["positive"]
        neg = counts["negative"]
        total_pos += pos
        total_neg += neg

        is_boundary = classifiers.contains_boundary_violation(text)
        is_contempt = classifiers.contains_contempt(text)
        is_harsh = classifiers.harsh_start(text)
        is_negative = bool(neg or is_boundary or is_contempt or is_harsh)

        if is_harsh:
            harsh += 1

        # Conflict window aggregation
        if is_negative and "you" in text.lower():
            window_tokens_pos = 0
            window_tokens_neg = 0
            for item in conflict_window:
                counts_window = classifiers.sentiment_counts(str(_get(item, "text") or ""))
                window_tokens_pos += counts_window["positive"]
                window_tokens_neg += counts_window["negative"]
            conflict_pos += window_tokens_pos
            conflict_neg += window_tokens_neg

        if classifiers.is_repair_attempt(text):
            partner = partner_map.get(sender)
            attempt = {"sender": sender, "partner": partner, "ts": ts}
            repair_attempts.append(attempt)
            open_repairs.append(attempt)

        # Attempt resolution within 2 minutes
        if open_repairs:
            surviving: List[dict] = []
            for attempt in open_repairs:
                partner = attempt.get("partner")
                delta = ts - attempt["ts"]
                if partner is None or partner != sender:
                    if delta <= timedelta(minutes=2):
                        surviving.append(attempt)
                    continue
                if delta <= timedelta(minutes=2):
                    success_counts = classifiers.sentiment_counts(text)
                    success = classifiers.is_repair_success(text) or (
                        success_counts["negative"] == 0 and success_counts["positive"] > 0
                    )
                    if success:
                        repair_successes += 1
                        repair_success_times.append(ts)
                    continue
                surviving.append(attempt)
            open_repairs = surviving

        bid_type = classifiers.classify_bid(text)
        if bid_type == "gratitude":  # fold into affection bucket
            bid_type = "affection"
        if bid_type:
            bid_counts[bid_type] += 1
            partner = partner_map.get(sender)
            if partner is None:
                partner = sender
            cutoff = ts + timedelta(hours=6)
            for follow in rows_sorted:
                follow_ts = datetime.fromisoformat(str(_get(follow, "ts")))
                if follow_ts <= ts:
                    continue
                if follow_ts > cutoff:
                    break
                if int(_get(follow, "sender_id")) != partner:
                    continue
                follow_text = str(_get(follow, "text") or "")
                follow_counts = classifiers.sentiment_counts(follow_text)
                if (
                    classifiers.is_turn_toward(follow_text)
                    or classifiers.is_repair_success(follow_text)
                    or follow_counts["positive"] > follow_counts["negative"]
                ):
                    bid_responses[bid_type] += 1
                break

        if is_boundary:
            boundary_count += 1
            rupture_times.append(ts)
        if is_contempt:
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

        if classifiers.is_demand(text):
            demand_events.append({"sender": sender, "ts": ts})

        if demand_events and classifiers.is_withdraw(text):
            surviving_demands: List[dict] = []
            matched = False
            for event in demand_events:
                if matched:
                    surviving_demands.append(event)
                    continue
                if event["sender"] == sender:
                    surviving_demands.append(event)
                    continue
                if ts - event["ts"] <= timedelta(hours=2):
                    if user_a is not None and user_b is not None:
                        if event["sender"] == user_a:
                            demand_counts["dw_AtoB"] += 1
                        elif event["sender"] == user_b:
                            demand_counts["dw_BtoA"] += 1
                    matched = True
                else:
                    surviving_demands.append(event)
            demand_events = surviving_demands

        if prev_sender is not None and sender != prev_sender and prev_ts is not None:
            delta_seconds = (ts - prev_ts).total_seconds()
            if 0 < delta_seconds <= 12 * 3600:
                reply_deltas.append(delta_seconds)

        if prev_sender is not None and sender != prev_sender:
            if prev_neg_flag:
                neg_follow_neg_total += 1
                if is_negative:
                    neg_follow_neg += 1
            else:
                neutral_total += 1
                if is_negative:
                    neg_follow_neutral += 1

        prev_neg_flag = is_negative
        prev_sender = sender
        prev_ts = ts

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
    if conflict_neg == 0 and conflict_pos == 0:
        conflict_pos = total_pos
        conflict_neg = total_neg
    metrics["p_to_n_conflict_ratio"] = (conflict_pos + 1) / (conflict_neg + 1)
    metrics["harsh_start_rate"] = harsh / total_messages
    metrics["repair_attempts_per_hour"] = len(repair_attempts) / span_hours
    metrics["repair_effectiveness_pct"] = (
        (repair_successes / len(repair_attempts)) * 100 if repair_attempts else 0.0
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

    dw = metrics["demand_withdraw_rate"]
    dw["dw_AtoB"] = (demand_counts["dw_AtoB"] * 1000) / total_messages
    dw["dw_BtoA"] = (demand_counts["dw_BtoA"] * 1000) / total_messages

    bid_totals = {"affection": 0, "info": 0, "play": 0, "requests": 0}
    bid_success = {"affection": 0, "info": 0, "play": 0, "requests": 0}
    for key in bid_totals:
        bid_totals[key] = bid_counts.get(key, 0)
        bid_success[key] = bid_responses.get(key, 0)
    metrics["bid_response_ratio"] = {
        key: (bid_success[key] / bid_totals[key] if bid_totals[key] else 0.0)
        for key in bid_totals
    }

    if reply_deltas:
        sorted_deltas = sorted(reply_deltas)
        metrics["median_reply_seconds"] = median(sorted_deltas)
        p90_index = max(int(0.9 * (len(sorted_deltas) - 1)), 0)
        p90 = sorted_deltas[p90_index]
        metrics["p90_reply_seconds"] = p90
        med = metrics["median_reply_seconds"] or 1.0
        metrics["reply_variability"] = max((p90 - med) / med, 0.0)
    else:
        metrics["median_reply_seconds"] = 0.0
        metrics["p90_reply_seconds"] = 0.0
        metrics["reply_variability"] = 0.0

    metrics["emoji_signal_rate"] = emoji_total / total_messages

    if user_a is not None and user_b is not None:
        scores: List[float] = []
        tokens_a = tokens_by_user[user_a]
        tokens_b = tokens_by_user[user_b]
        for words in FUNCTION_WORD_CATEGORIES.values():
            count_a = sum(1 for token in tokens_a if token in words)
            count_b = sum(1 for token in tokens_b if token in words)
            if count_a + count_b == 0:
                continue
            freq_a = count_a / max(len(tokens_a), 1)
            freq_b = count_b / max(len(tokens_b), 1)
            numerator = abs(freq_a - freq_b)
            denominator = freq_a + freq_b if (freq_a + freq_b) else 1.0
            scores.append(1 - numerator / denominator)
        metrics["lsm_score"] = sum(scores) / len(scores) if scores else 0.0
    else:
        metrics["lsm_score"] = 0.0

    we_ratio = (we_count + 1) / (i_you_count + 1)
    context = "neutral"
    if we_plans > we_blame:
        context = "plans"
    elif we_blame > we_plans:
        context = "blame"
    metrics["we_talk_index"] = {"value": we_ratio, "context": context}

    metrics["affection_density"] = (affection_msgs * 100) / total_messages
    metrics["gratitude_density"] = (gratitude_msgs * 100) / total_messages
    metrics["future_planning_density"] = (planning_msgs * 100) / total_messages

    metrics["plan_to_happen_ratio"] = (
        soon_completions / soon_commitments if soon_commitments else 1.0
    )

    metrics["follow_through_latency_hours"] = median(follow_latencies) if follow_latencies else 0.0

    stats_a = support_stats[user_a] if user_a is not None else {"offers": 0, "asks": 0, "completions": 0}
    stats_b = support_stats[user_b] if user_b is not None else {"offers": 0, "asks": 0, "completions": 0}
    balance_a = stats_a["offers"] + stats_a["completions"] - stats_a["asks"]
    balance_b = stats_b["offers"] + stats_b["completions"] - stats_b["asks"]
    metrics["support_balance_index"] = {"A": float(balance_a), "B": float(balance_b)}

    metrics["boundary_violations_per_1k"] = (boundary_count * 1000) / total_messages
    metrics["contempt_markers_per_1k"] = (contempt_count * 1000) / total_messages

    if rupture_times:
        metrics["ruptures_per_month"] = len(rupture_times) * 30 / max(span_hours / 24, 1)
    else:
        metrics["ruptures_per_month"] = 0.0

    repair_cycles = []
    for rupture in rupture_times:
        later = [t for t in repair_success_times if t > rupture]
        if later:
            repair_cycles.append((later[0] - rupture).total_seconds() / 3600.0)
    metrics["median_repair_cycle_hours"] = median(repair_cycles) if repair_cycles else 0.0

    return metrics


__all__ = ["compute_metrics", "flatten_metrics"]
