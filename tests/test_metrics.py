from __future__ import annotations

import json
from pathlib import Path

import pytest

from couples_bot.metrics import compute


def load_rows() -> list[dict]:
    path = Path(__file__).parent / "samples" / "conversation.jsonl"
    rows = []
    with path.open() as fh:
        for line in fh:
            rows.append(json.loads(line))
    return rows


def test_core_metrics():
    rows = load_rows()
    metrics = compute.compute_metrics(rows)
    assert metrics["p_to_n_conflict_ratio"] == pytest.approx(2.5, rel=1e-2)
    assert metrics["harsh_start_rate"] == pytest.approx(0.125, rel=1e-2)
    assert metrics["repair_attempts_per_hour"] == pytest.approx(0.83, rel=1e-2)
    assert metrics["repair_effectiveness_pct"] == pytest.approx(100.0)
    assert metrics["bid_response_ratio_affection"] == 1.0
    assert metrics["median_reply_seconds"] == pytest.approx(180.0, rel=1e-2)
    assert metrics["p90_reply_seconds"] == pytest.approx(300.0, rel=1e-2)
    assert metrics["boundary_violations_per_1k"] == pytest.approx(125.0, rel=1e-2)
    assert metrics["contempt_markers_per_1k"] == pytest.approx(125.0, rel=1e-2)
    assert metrics["ruptures_per_month"] == pytest.approx(30.0, rel=1e-2)
    assert metrics["median_repair_cycle_hours"] == 0.0
