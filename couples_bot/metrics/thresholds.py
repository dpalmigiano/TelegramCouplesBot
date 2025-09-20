"""Threshold management for alerts and score interpretation."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Mapping, Tuple

from .. import db


@dataclass
class Threshold:
    key: str
    direction: str  # "above" or "below"
    warn: float
    praise: float | None = None


DEFAULTS: Dict[str, Threshold] = {
    "p_to_n_conflict_ratio": Threshold("p_to_n_conflict_ratio", "above", warn=1.2, praise=3.0),
    "harsh_start_rate": Threshold("harsh_start_rate", "above", warn=0.3),
    "repair_attempts_per_hour": Threshold("repair_attempts_per_hour", "below", warn=0.2, praise=0.8),
    "repair_effectiveness_pct": Threshold("repair_effectiveness_pct", "below", warn=40.0, praise=75.0),
    "neg_affect_reciprocity": Threshold("neg_affect_reciprocity", "above", warn=0.25),
    "demand_withdraw_rate_AtoB": Threshold("demand_withdraw_rate_AtoB", "above", warn=80.0),
    "demand_withdraw_rate_BtoA": Threshold("demand_withdraw_rate_BtoA", "above", warn=80.0),
    "bid_response_ratio_affection": Threshold("bid_response_ratio_affection", "below", warn=0.4, praise=0.8),
    "bid_response_ratio_play": Threshold("bid_response_ratio_play", "below", warn=0.3, praise=0.7),
    "bid_response_ratio_gratitude": Threshold("bid_response_ratio_gratitude", "below", warn=0.3, praise=0.7),
    "median_reply_seconds": Threshold("median_reply_seconds", "above", warn=900),
    "p90_reply_seconds": Threshold("p90_reply_seconds", "above", warn=3600),
    "reply_variability": Threshold("reply_variability", "above", warn=1800),
    "emoji_signal_rate": Threshold("emoji_signal_rate", "below", warn=0.02, praise=0.08),
    "lsm_score": Threshold("lsm_score", "below", warn=0.45, praise=0.65),
    "we_talk_index": Threshold("we_talk_index", "below", warn=0.8, praise=1.2),
    "affection_density": Threshold("affection_density", "below", warn=8.0, praise=18.0),
    "gratitude_density": Threshold("gratitude_density", "below", warn=6.0, praise=15.0),
    "future_planning_density": Threshold("future_planning_density", "below", warn=8.0, praise=25.0),
    "plan_to_happen_ratio": Threshold("plan_to_happen_ratio", "below", warn=0.6),
    "follow_through_latency_hours": Threshold("follow_through_latency_hours", "above", warn=18.0),
    "support_balance_index": Threshold("support_balance_index", "above", warn=6.0),
    "boundary_violations_per_1k": Threshold("boundary_violations_per_1k", "above", warn=0.1),
    "contempt_markers_per_1k": Threshold("contempt_markers_per_1k", "above", warn=2.0),
    "ruptures_per_month": Threshold("ruptures_per_month", "above", warn=4.0),
    "median_repair_cycle_hours": Threshold("median_repair_cycle_hours", "above", warn=24.0),
}


def default_thresholds() -> List[Threshold]:
    return list(DEFAULTS.values())


def ewma(previous: float | None, new_value: float, alpha: float = 0.3) -> float:
    if previous is None:
        return new_value
    return alpha * new_value + (1 - alpha) * previous


def _stat_key(prefix: str, metric_key: str) -> str:
    return f"{prefix}:{metric_key}"


def update_baselines(
    couple_id: int,
    metrics: Mapping[str, float | str],
    *,
    alpha: float = 0.25,
) -> Dict[str, Tuple[float, float]]:
    """Update EWMA baselines + variance bands for numeric metrics."""

    bands: Dict[str, Tuple[float, float]] = {}
    for key, value in metrics.items():
        if not isinstance(value, (int, float)):
            continue
        baseline_key = _stat_key("baseline", key)
        variance_key = _stat_key("variance", key)
        prev_baseline = db.get_stat(couple_id, baseline_key, default=float("nan"))
        prev_variance = db.get_stat(couple_id, variance_key, default=float("nan"))

        baseline = ewma(None if math.isnan(prev_baseline) else prev_baseline, value, alpha)
        diff = value - (prev_baseline if not math.isnan(prev_baseline) else value)
        variance = ewma(
            None if math.isnan(prev_variance) else prev_variance,
            diff * diff,
            alpha,
        )
        sigma = math.sqrt(max(variance, 0.0))

        db.upsert_stat(couple_id, baseline_key, baseline)
        db.upsert_stat(couple_id, variance_key, variance)
        bands[key] = (baseline, sigma)
    return bands


def _threshold_for(key: str, overrides: Mapping[str, Threshold] | None = None) -> Threshold | None:
    if overrides and key in overrides:
        return overrides[key]
    return DEFAULTS.get(key)


def evaluate_praise(
    metric_key: str,
    value: float,
    baseline: float | None,
    sigma: float | None,
    thresholds_map: Mapping[str, Threshold] | None = None,
) -> bool:
    threshold = _threshold_for(metric_key, thresholds_map)
    if metric_key == "follow_through_latency_hours" and baseline is not None:
        return value <= baseline * 0.75
    if threshold and threshold.praise is not None:
        if threshold.direction == "above":
            return value >= threshold.praise
        return value <= threshold.praise
    if baseline is None:
        return False
    if threshold:
        if threshold.direction == "below":
            return value <= baseline * 0.75
        if threshold.direction == "above":
            return value >= baseline * 1.25
    return False


def evaluate_risk(
    metric_key: str,
    value: float,
    baseline: float | None,
    sigma: float | None,
    thresholds_map: Mapping[str, Threshold] | None = None,
) -> bool:
    threshold = _threshold_for(metric_key, thresholds_map)
    triggered = False
    if threshold:
        warn = threshold.warn
        check_value = value
        if metric_key == "support_balance_index":
            check_value = abs(value)
        if threshold.direction == "above":
            triggered = check_value >= warn
        else:
            triggered = check_value <= warn
    if not triggered and baseline is not None and sigma is not None and sigma > 0:
        baseline_value = baseline
        if metric_key == "support_balance_index":
            baseline_value = abs(baseline_value)
            value_to_check = abs(value)
        else:
            value_to_check = value
        if threshold and threshold.direction == "above":
            triggered = value_to_check >= baseline_value + 2 * sigma
        elif threshold and threshold.direction == "below":
            triggered = value_to_check <= baseline_value - 2 * sigma
    return triggered


def evaluate_logistics(
    metric_key: str,
    value: float,
    *,
    sla_seconds: float | None = None,
    thresholds_map: Mapping[str, Threshold] | None = None,
) -> bool:
    threshold = _threshold_for(metric_key, thresholds_map)
    if not threshold:
        return False
    warn = threshold.warn
    if metric_key == "median_reply_seconds" and sla_seconds is not None:
        warn = sla_seconds
    if threshold.direction == "above":
        return value >= warn
    return value <= warn


__all__ = [
    "Threshold",
    "default_thresholds",
    "ewma",
    "update_baselines",
    "evaluate_praise",
    "evaluate_risk",
    "evaluate_logistics",
]
