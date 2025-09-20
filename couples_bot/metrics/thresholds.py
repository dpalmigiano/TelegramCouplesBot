"""Threshold helpers for triggering alerts."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from ..models import AlertKind


DEFAULT_THRESHOLDS: Dict[str, Dict[str, float]] = {
    "p_to_n_conflict_ratio": {"praise": 3.0},
    "harsh_start_rate": {"warn": 0.2},
    "contempt_markers_per_1k": {"warn": 0.5},
    "boundary_violations_per_1k": {"warn": 0.1},
}


def ewma(previous: Optional[float], new_value: float, alpha: float = 0.3) -> float:
    if previous is None:
        return new_value
    return alpha * new_value + (1 - alpha) * previous


@dataclass
class MetricDecision:
    metric: str
    kind: AlertKind
    reason: str


def evaluate_metric(
    metric_key: str,
    value: float,
    *,
    baseline: Optional[float] = None,
    sla_minutes: Optional[int] = None,
) -> Tuple[Optional[AlertKind], Optional[str]]:
    if metric_key == "p_to_n_conflict_ratio" and value >= DEFAULT_THRESHOLDS[metric_key]["praise"]:
        return AlertKind.PRAISE, "Positive-to-negative ratio is soaring"
    if metric_key == "harsh_start_rate" and value >= DEFAULT_THRESHOLDS[metric_key]["warn"]:
        return AlertKind.RISK, "Several recent harsh starts detected"
    if metric_key == "contempt_markers_per_1k" and value > DEFAULT_THRESHOLDS[metric_key]["warn"]:
        return AlertKind.RISK, "Concerning contempt language seen"
    if metric_key == "boundary_violations_per_1k" and value > DEFAULT_THRESHOLDS[metric_key]["warn"]:
        return AlertKind.RISK, "Boundary pushes appearing in chat"
    if metric_key == "median_reply_seconds" and sla_minutes is not None and value > sla_minutes * 60:
        return AlertKind.LOGISTICS, "Median reply time is above SLA"
    if metric_key == "plan_to_happen_ratio" and value < 0.6:
        return AlertKind.LOGISTICS, "Plans are slipping below expectations"
    if metric_key == "follow_through_latency_hours" and baseline is not None and baseline > 0 and value <= 0.75 * baseline:
        return AlertKind.PRAISE, "Follow-through is faster than usual"
    return None, None


__all__ = ["DEFAULT_THRESHOLDS", "ewma", "MetricDecision", "evaluate_metric"]
