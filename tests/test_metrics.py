import json

import pytest

from couples_bot.metrics.compute import compute_metrics


@pytest.fixture
def sample_messages():
    with open("tests/samples/conversation.jsonl", "r", encoding="utf-8") as fh:
        return [json.loads(line) for line in fh]


def test_core_metrics(sample_messages):
    metrics = compute_metrics(sample_messages)
    assert metrics["p_to_n_conflict_ratio"] == pytest.approx(2.0)
    assert metrics["harsh_start_rate"] == pytest.approx(0.5)
    assert metrics["repair_attempts_per_hour"] == pytest.approx(1.714, rel=1e-3)
    assert metrics["repair_effectiveness_pct"] == pytest.approx(100.0)
    assert metrics["bid_response_ratio"]["overall"] == pytest.approx(1.0)
    assert metrics["median_reply_seconds"] == pytest.approx(60.0)
    assert metrics["p90_reply_seconds"] == pytest.approx(2190.0)
    assert metrics["reply_variability"] == pytest.approx(794.17, rel=1e-3)
    assert metrics["boundary_violations_per_1k"] == pytest.approx(22.727, rel=1e-3)
    assert metrics["contempt_markers_per_1k"] == pytest.approx(0.0)
    assert metrics["ruptures_per_month"] == pytest.approx(30.0)
    assert metrics["median_repair_cycle_hours"] == pytest.approx(0.017, rel=1e-3)
