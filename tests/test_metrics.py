import json
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
    flat = compute.flatten_metrics(metrics)

    assert pytest.approx(metrics["p_to_n_conflict_ratio"], rel=1e-3) == 1.08333
    assert pytest.approx(metrics["harsh_start_rate"], rel=1e-3) == 0.10526
    assert pytest.approx(metrics["repair_attempts_per_hour"], rel=1e-3) == 0.72727
    assert pytest.approx(metrics["neg_affect_reciprocity"], rel=1e-3) == 0.16666
    assert pytest.approx(flat["demand_withdraw_rate.dw_AtoB"], rel=1e-3) == 52.6315
    assert pytest.approx(flat["demand_withdraw_rate.dw_BtoA"], rel=1e-3) == 52.6315
    assert pytest.approx(metrics["bid_response_ratio"]["affection"], rel=1e-3) == 0.66666
    assert metrics["bid_response_ratio"]["info"] == 0.0
    assert pytest.approx(metrics["median_reply_seconds"], rel=1e-3) == 300.0
    assert pytest.approx(metrics["p90_reply_seconds"], rel=1e-3) == 900.0
    assert pytest.approx(metrics["reply_variability"], rel=1e-3) == 2.0
    assert pytest.approx(metrics["emoji_signal_rate"], rel=1e-3) == 0.05263
    assert pytest.approx(metrics["lsm_score"], rel=1e-3) == 0.59535
    assert metrics["we_talk_index"]["context"] == "plans"
    assert pytest.approx(metrics["we_talk_index"]["value"], rel=1e-3) == 0.9
    assert pytest.approx(metrics["affection_density"], rel=1e-3) == 15.7894
    assert pytest.approx(metrics["plan_to_happen_ratio"], rel=1e-3) == 0.5
    assert pytest.approx(metrics["follow_through_latency_hours"], rel=1e-3) == 0.18333
    assert metrics["support_balance_index"]["A"] == pytest.approx(2.0)
    assert metrics["support_balance_index"]["B"] == pytest.approx(2.0)
    assert pytest.approx(metrics["boundary_violations_per_1k"], rel=1e-3) == 105.2631
    assert pytest.approx(metrics["contempt_markers_per_1k"], rel=1e-3) == 52.6315


def test_monotonicity_signals():
    base_rows = load_rows()
    baseline = compute.compute_metrics(base_rows)
    extra_positive = dict(base_rows[-1])
    extra_positive["id"] = 999
    extra_positive["ts"] = "2024-01-01T12:00:00"
    extra_positive["text"] = "Thanks for owning it, I appreciate the reset."
    boosted = compute.compute_metrics(base_rows + [extra_positive])

    assert boosted["p_to_n_conflict_ratio"] >= baseline["p_to_n_conflict_ratio"]
    assert boosted["repair_attempts_per_hour"] >= baseline["repair_attempts_per_hour"]
