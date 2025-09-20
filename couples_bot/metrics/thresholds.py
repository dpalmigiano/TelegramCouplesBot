"""Threshold management for alerts."""

from __future__ import annotations

from dataclasses import dataclass
from statistics import mean, pstdev
from typing import Dict, Iterable, List, Mapping, Tuple


@dataclass
class Threshold:
    key: str
    direction: str
    warn: float
    praise: float | None = None


DEFAULTS: Dict[str, Threshold] = {
    "p_to_n_conflict_ratio": Threshold(
        key="p_to_n_conflict_ratio",
        direction="above",
        warn=2.0,
        praise=3.0,
    ),
    "harsh_start_rate": Threshold(
        key="harsh_start_rate", direction="above", warn=0.3, praise=None
    ),
    "contempt_markers_per_1k": Threshold(
        key="contempt_markers_per_1k", direction="above", warn=2.0, praise=None
    ),
    "boundary_violations_per_1k": Threshold(
        key="boundary_violations_per_1k", direction="above", warn=0.1, praise=None
    ),
    "median_reply_seconds": Threshold(
        key="median_reply_seconds", direction="above", warn=900, praise=None
    ),
    "plan_to_happen_ratio": Threshold(
        key="plan_to_happen_ratio", direction="below", warn=0.6, praise=None
    ),
}

CATEGORIES = {
    "p_to_n_conflict_ratio": "praise",
    "harsh_start_rate": "risk",
    "contempt_markers_per_1k": "risk",
    "boundary_violations_per_1k": "risk",
    "median_reply_seconds": "logistics",
    "plan_to_happen_ratio": "logistics",
}


def default_thresholds() -> List[Threshold]:
    return list(DEFAULTS.values())


def ewma(previous: float | None, new_value: float, alpha: float = 0.3) -> float:
    if previous is None:
        return new_value
    return alpha * new_value + (1 - alpha) * previous


def sigma_band(values: Iterable[float]) -> Tuple[float, float]:
    data = list(values)
    if not data:
        return 0.0, 0.0
    if len(data) == 1:
        return data[0], 0.0
    return mean(data), pstdev(data)


def evaluate_thresholds(
    metrics: Mapping[str, float],
    thresholds: Mapping[str, Threshold],
    *,
    sla_seconds: float | None = None,
) -> Dict[str, List[str]]:
    results = {"praise": [], "risk": [], "logistics": []}
    for key, threshold in thresholds.items():
        if key not in metrics:
            continue
        value = metrics[key]
        warn = threshold.warn
        if key == "median_reply_seconds" and sla_seconds is not None:
            warn = sla_seconds
        direction = threshold.direction
        category = CATEGORIES.get(key, "risk")
        if direction == "above":
            if threshold.praise is not None and value >= threshold.praise:
                results["praise"].append(key)
            elif warn is not None and value >= warn:
                results[category].append(key)
        else:
            if threshold.praise is not None and value <= threshold.praise:
                results["praise"].append(key)
            elif warn is not None and value <= warn:
                results[category].append(key)
    return results


__all__ = ["Threshold", "default_thresholds", "ewma", "sigma_band", "evaluate_thresholds"]
