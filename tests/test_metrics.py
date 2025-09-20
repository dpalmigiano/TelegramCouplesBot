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


def test_full_metrics():
    rows = load_rows()
    metrics = compute.compute_metrics(rows)
    assert metrics["p_to_n_conflict_ratio"] == pytest.approx(0.8333, rel=1e-3)
    assert metrics["harsh_start_rate"] == pytest.approx(0.1053, rel=1e-3)
    assert metrics["repair_attempts_per_hour"] == pytest.approx(0.7273, rel=1e-3)
    assert metrics["repair_effectiveness_pct"] == pytest.approx(50.0, rel=1e-3)
    assert metrics["neg_affect_reciprocity"] == pytest.approx(0.1666, rel=1e-3)
    assert metrics["demand_withdraw_rate_AtoB"] == pytest.approx(52.6315, rel=1e-3)
    assert metrics["demand_withdraw_rate_BtoA"] == pytest.approx(52.6315, rel=1e-3)
    assert metrics["bid_response_ratio_affection"] == 1.0
    assert metrics["bid_response_ratio_play"] == pytest.approx(0.0, abs=1e-6)
    assert metrics["bid_response_ratio_gratitude"] == pytest.approx(0.5, rel=1e-3)
    assert metrics["median_reply_seconds"] == pytest.approx(300.0, rel=1e-3)
    assert metrics["p90_reply_seconds"] == pytest.approx(900.0, rel=1e-3)
    assert metrics["reply_variability"] == pytest.approx(600.0, rel=1e-3)
    assert metrics["emoji_signal_rate"] == pytest.approx(0.0526, rel=1e-3)
    assert metrics["lsm_score"] == pytest.approx(0.5953, rel=1e-3)
    assert metrics["we_talk_index"] == pytest.approx(0.9, rel=1e-3)
    assert metrics["we_talk_index_context"] == "plans"
    assert metrics["affection_density"] == pytest.approx(15.7894, rel=1e-3)
    assert metrics["gratitude_density"] == pytest.approx(10.5263, rel=1e-3)
    assert metrics["future_planning_density"] == pytest.approx(26.3157, rel=1e-3)
    assert metrics["plan_to_happen_ratio"] == pytest.approx(0.5, rel=1e-3)
    assert metrics["follow_through_latency_hours"] == pytest.approx(0.1833, rel=1e-3)
    assert metrics["support_balance_index"] == pytest.approx(0.0, abs=1e-6)
    assert metrics["boundary_violations_per_1k"] == pytest.approx(105.2631, rel=1e-3)
    assert metrics["contempt_markers_per_1k"] == pytest.approx(52.6315, rel=1e-3)
    assert metrics["ruptures_per_month"] == pytest.approx(30.0, rel=1e-3)
    assert metrics["median_repair_cycle_hours"] == pytest.approx(0.1666, rel=1e-3)
