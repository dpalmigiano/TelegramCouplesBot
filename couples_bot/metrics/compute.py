"""Metric computation utilities."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from statistics import median
from typing import Dict, Iterable, List, Optional

import sqlite3

from . import classifiers, windows


MessageRow = sqlite3.Row


def _hours_span(messages: List[MessageRow]) -> float:
    if not messages:
        return 1.0
    start = datetime.fromisoformat(messages[0]["ts"])
    end = datetime.fromisoformat(messages[-1]["ts"])
    span = (end - start).total_seconds() / 3600.0
    return max(span, 1 / 60)


def compute_metrics(messages: Iterable[MessageRow]) -> Dict[str, float]:
    """Return all 18 metrics. Some are placeholder zeros for the MVP."""

    rows = list(messages)
    metrics: Dict[str, float] = {}

    if not rows:
        # Fill zeros for all metrics
        keys = [
            "p_to_n_conflict_ratio",
            "harsh_start_rate",
            "repair_attempts_per_hour",
            "repair_effectiveness_pct",
            "neg_affect_reciprocity",
            "demand_withdraw_rate",
            "bid_response_ratio_affection",
            "bid_response_ratio_play",
            "bid_response_ratio_gratitude",
            "median_reply_seconds",
            "p90_reply_seconds",
            "reply_variability",
            "emoji_signal_rate",
            "lsm_score",
            "we_talk_index",
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
        for key in keys:
            metrics[key] = 0.0
        return metrics

    # Sentiment
    total_pos = 0
    total_neg = 0
    harsh = 0
    repair_attempts = []
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

    rows_sorted = sorted(rows, key=lambda r: r["ts"])
    span_hours = _hours_span(rows_sorted)

    for idx, row in enumerate(rows_sorted):
        text = row["text"]
        counts = classifiers.sentiment_counts(text)
        total_pos += counts["positive"]
        total_neg += counts["negative"]
        if classifiers.harsh_start(text):
            harsh += 1
        if classifiers.is_repair_attempt(text):
            repair_attempts.append(idx)
            pending_repairs.append(row["sender_id"])
        if pending_repairs and row["sender_id"] != pending_repairs[0] and classifiers.is_repair_success(text):
            repair_successes += 1
            pending_repairs.pop(0)
        bid_type = classifiers.classify_bid(text)
        if bid_type:
            bid_counts[bid_type] += 1
            # look ahead for response within 5 minutes from other partner
            current_sender = row["sender_id"]
            for follow in rows_sorted[idx + 1 :]:
                follow_ts = datetime.fromisoformat(follow["ts"])
                row_ts = datetime.fromisoformat(row["ts"])
                if follow_ts - row_ts > timedelta(minutes=5):
                    break
                if follow["sender_id"] != current_sender:
                    if classifiers.is_turn_toward(follow["text"]):
                        bid_responses[bid_type] += 1
                    else:
                        bid_responses[bid_type] += 1
                    break
        if classifiers.contains_boundary_violation(text):
            boundary_count += 1
        if classifiers.contains_contempt(text):
            contempt_count += 1
            rupture_times.append(datetime.fromisoformat(row["ts"]))

        ts = datetime.fromisoformat(row["ts"])
        if last_message_time is not None and row["sender_id"] != last_sender:
            reply_deltas.append((ts - last_message_time).total_seconds())
        last_message_time = ts
        last_sender = row["sender_id"]

    # Compute positive/negative ratio.
    metrics["p_to_n_conflict_ratio"] = (total_pos + 1) / (total_neg + 1)

    metrics["harsh_start_rate"] = harsh / max(len(rows_sorted), 1)

    metrics["repair_attempts_per_hour"] = len(repair_attempts) / span_hours
    metrics["repair_effectiveness_pct"] = (
        (repair_successes / len(repair_attempts)) * 100 if repair_attempts else 0.0
    )

    # Placeholder zeros for advanced metrics not implemented yet.
    metrics["neg_affect_reciprocity"] = 0.0  # TODO
    metrics["demand_withdraw_rate"] = 0.0  # TODO combined metric

    for bid_type in ("affection", "play", "gratitude"):
        total = bid_counts[bid_type]
        responded = bid_responses[bid_type]
        key = f"bid_response_ratio_{bid_type}"
        metrics[key] = responded / total if total else 0.0

    if reply_deltas:
        sorted_deltas = sorted(reply_deltas)
        metrics["median_reply_seconds"] = median(sorted_deltas)
        p90_index = int(0.9 * (len(sorted_deltas) - 1))
        metrics["p90_reply_seconds"] = sorted_deltas[p90_index]
        metrics["reply_variability"] = (
            metrics["p90_reply_seconds"] - metrics["median_reply_seconds"]
        )
    else:
        metrics["median_reply_seconds"] = 0.0
        metrics["p90_reply_seconds"] = 0.0
        metrics["reply_variability"] = 0.0

    metrics["emoji_signal_rate"] = 0.0  # TODO
    metrics["lsm_score"] = 0.0  # TODO
    metrics["we_talk_index"] = 0.0  # TODO
    metrics["affection_density"] = 0.0  # TODO
    metrics["gratitude_density"] = 0.0  # TODO
    metrics["future_planning_density"] = 0.0  # TODO
    metrics["plan_to_happen_ratio"] = 0.0  # TODO
    metrics["follow_through_latency_hours"] = 0.0  # TODO
    metrics["support_balance_index"] = 0.0  # TODO

    total_messages = max(len(rows_sorted), 1)
    metrics["boundary_violations_per_1k"] = (boundary_count * 1000) / total_messages
    metrics["contempt_markers_per_1k"] = (contempt_count * 1000) / total_messages

    # Rupture cycles: we mark contempt as rupture, next repair success closes.
    if rupture_times and repair_attempts:
        for rupture_time in rupture_times:
            closes = [
                datetime.fromisoformat(rows_sorted[idx]["ts"])
                for idx in repair_attempts
                if datetime.fromisoformat(rows_sorted[idx]["ts"]) > rupture_time
            ]
            if closes:
                delta = (min(closes) - rupture_time).total_seconds() / 3600.0
                repair_cycles.append(delta)

    metrics["ruptures_per_month"] = len(rupture_times) * 30 / max(span_hours / 24, 1)
    metrics["median_repair_cycle_hours"] = (
        median(repair_cycles) if repair_cycles else 0.0
    )

    return metrics


__all__ = ["compute_metrics"]
