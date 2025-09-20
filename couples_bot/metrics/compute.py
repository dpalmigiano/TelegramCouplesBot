"""Computation for all defined metrics."""
from __future__ import annotations

import statistics
from typing import Dict, Iterable, List, Sequence

from . import classifiers, windows

MetricMap = Dict[str, float | dict]


def _safe_ratio(num: float, denom: float) -> float:
    if denom == 0:
        return float(num > 0)
    return num / denom


def _response_stats(records: Sequence[windows.MessageRecord]) -> List[float]:
    gaps: List[float] = []
    for a, b in windows.cross_user_pairs(records):
        delta = (b.ts - a.ts).total_seconds()
        if delta >= 0:
            gaps.append(delta)
    return gaps


def _count_words(texts: Iterable[str]) -> int:
    return sum(len(text.split()) for text in texts)


def compute_metrics(messages: Sequence[dict]) -> MetricMap:
    records = windows.to_records(messages)
    labels = [classifiers.label_text(record.text) for record in records]

    metrics: MetricMap = {}

    positive_count = sum(1 for label in labels if label.positive)
    negative_count = sum(1 for label in labels if label.negative)
    metrics["p_to_n_conflict_ratio"] = round(_safe_ratio(positive_count + 1, negative_count + 1), 3)

    harsh_starts = 0
    segments = 0
    last_ts = None
    for record, label in zip(records, labels):
        if last_ts is None or (record.ts - last_ts).total_seconds() > 30 * 60:
            segments += 1
            if label.harsh_start:
                harsh_starts += 1
        last_ts = record.ts
    metrics["harsh_start_rate"] = round(_safe_ratio(harsh_starts, max(segments, 1)), 3)

    conv_hours = windows.conversation_hours(records)
    repair_attempts = sum(1 for label in labels if label.repair)
    metrics["repair_attempts_per_hour"] = round(repair_attempts / conv_hours if conv_hours else 0.0, 3)

    effective_repairs = 0
    for idx, label in enumerate(labels):
        if not label.repair:
            continue
        # look for partner response within 10 minutes that is positive or turn_toward
        origin_sender = records[idx].sender_id
        origin_time = records[idx].ts
        for j in range(idx + 1, len(records)):
            if records[j].sender_id == origin_sender:
                continue
            delta_minutes = (records[j].ts - origin_time).total_seconds() / 60
            if delta_minutes > 10:
                break
            if labels[j].positive or labels[j].turn_toward:
                effective_repairs += 1
            break
    metrics["repair_effectiveness_pct"] = round(
        _safe_ratio(effective_repairs, repair_attempts) * 100,
        2,
    )

    metrics["neg_affect_reciprocity"] = 0.0  # TODO

    dw_a_to_b = 0
    dw_b_to_a = 0
    total_a_prompts = 0
    total_b_prompts = 0
    if records:
        first_sender = records[0].sender_id
        for record in records:
            is_demand = classifiers.detect_demand_withdraw(record.text)
            if record.sender_id == first_sender:
                total_a_prompts += 1
                if is_demand:
                    dw_a_to_b += 1
            else:
                total_b_prompts += 1
                if is_demand:
                    dw_b_to_a += 1
    metrics["demand_withdraw_rate"] = {
        "dw_AtoB": round(_safe_ratio(dw_a_to_b, max(total_a_prompts, 1)), 3),
        "dw_BtoA": round(_safe_ratio(dw_b_to_a, max(total_b_prompts, 1)), 3),
    }

    bids = []
    responses = 0
    for idx, label in enumerate(labels):
        if not label.bid:
            continue
        bids.append(idx)
        origin_sender = records[idx].sender_id
        for j in range(idx + 1, len(records)):
            if records[j].sender_id == origin_sender:
                continue
            delta_minutes = (records[j].ts - records[idx].ts).total_seconds() / 60
            if delta_minutes > 10:
                break
            if labels[j].turn_toward or labels[j].positive:
                responses += 1
            break
    metrics["bid_response_ratio"] = {"overall": round(_safe_ratio(responses, len(bids)), 3)}

    gaps = _response_stats(records)
    if gaps:
        metrics["median_reply_seconds"] = round(float(statistics.median(gaps)), 2)
        metrics["p90_reply_seconds"] = round(float(statistics.quantiles(gaps, n=10)[8]), 2)
        metrics["reply_variability"] = round(float(statistics.pstdev(gaps)), 2)
    else:
        metrics["median_reply_seconds"] = 0.0
        metrics["p90_reply_seconds"] = 0.0
        metrics["reply_variability"] = 0.0

    emoji_flags = sum(1 for record in records if classifiers.emoji_signal(record.text))
    metrics["emoji_signal_rate"] = round(_safe_ratio(emoji_flags, max(len(records), 1)), 3)

    metrics["lsm_score"] = 0.0  # TODO
    metrics["we_talk_index"] = 0.0  # TODO
    metrics["affection_density"] = 0.0  # TODO
    metrics["gratitude_density"] = 0.0  # TODO
    metrics["future_planning_density"] = 0.0  # TODO
    metrics["plan_to_happen_ratio"] = 0.0  # TODO
    metrics["follow_through_latency_hours"] = 0.0  # TODO
    metrics["support_balance_index"] = 0.0  # TODO

    total_words = _count_words(record.text for record in records) or 1
    boundary_count = sum(1 for label in labels if label.boundary)
    contempt_count = sum(1 for label in labels if label.contempt)
    metrics["boundary_violations_per_1k"] = round(boundary_count / total_words * 1000, 3)
    metrics["contempt_markers_per_1k"] = round(contempt_count / total_words * 1000, 3)

    segments = windows.conflict_segments(records)
    metrics["ruptures_per_month"] = 0.0
    metrics["median_repair_cycle_hours"] = 0.0
    if segments:
        total_days = max(1 / 24, (records[-1].ts - records[0].ts).total_seconds() / 86400)
        months = max(1 / 30, total_days / 30)
        metrics["ruptures_per_month"] = round(len(segments) / months, 3)

        repair_cycles: List[float] = []
        for segment in segments:
            end_ts = segment[-1].ts
            for record, label in zip(records, labels):
                if record.ts <= end_ts:
                    continue
                if label.positive or label.repair:
                    hours = (record.ts - end_ts).total_seconds() / 3600
                    repair_cycles.append(hours)
                    break
        if repair_cycles:
            metrics["median_repair_cycle_hours"] = round(float(statistics.median(repair_cycles)), 3)

    return metrics


__all__ = ["compute_metrics"]
