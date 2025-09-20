"""Background worker that processes REAG jobs."""

from __future__ import annotations

import json
import logging
import random
import time
from typing import Any, Dict, Iterable, Mapping, Optional

try:
    from groq import Groq  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    Groq = None  # type: ignore

from couples_bot import db
from couples_bot.config import get_settings
from couples_bot.db_jobs import (
    claim_job,
    complete_job,
    fail_job,
    pending_jobs_count,
)
from couples_bot.metrics.compute import flatten_metrics
from couples_bot.store import graph
from couples_bot.utils import timebox

SCHEMA_PROMPT = (
    "You are a reasoning worker for a couples-coaching bot. Respond with STRICT JSON "
    "matching the provided schema. Do not add commentary or Markdown."
)

STRICT_SCHEMA_DOC = """{\n  \"graph\": [ { \"s\": string, \"p\": string, \"o\": string, \"t\": integer } ],\n  \"scores\": {\n    \"p_to_n_conflict_ratio\": number,\n    \"harsh_start_rate\": number,\n    \"repair_attempts_per_hour\": number,\n    \"repair_effectiveness_pct\": number,\n    \"neg_affect_reciprocity\": number,\n    \"demand_withdraw_rate\": { \"dw_AtoB\": number, \"dw_BtoA\": number },\n    \"bid_response_ratio\": { \"affection\": number, \"info\": number, \"play\": number, \"requests\": number },\n    \"median_reply_seconds\": number,\n    \"p90_reply_seconds\": number,\n    \"reply_variability\": number,\n    \"emoji_signal_rate\": number,\n    \"lsm_score\": number,\n    \"we_talk_index\": { \"value\": number, \"context\": \"plans\" | \"blame\" | \"neutral\" },\n    \"affection_density\": number,\n    \"gratitude_density\": number,\n    \"future_planning_density\": number,\n    \"plan_to_happen_ratio\": number,\n    \"follow_through_latency_hours\": number,\n    \"support_balance_index\": { \"A\": number, \"B\": number },\n    \"boundary_violations_per_1k\": number,\n    \"contempt_markers_per_1k\": number,\n    \"ruptures_per_month\": number,\n    \"median_repair_cycle_hours\": number\n  },\n  \"advice\": { \"user:<id>\": string }\n}"""

logger = logging.getLogger(__name__)


def _choose_model(use_tools: bool, queue_len: int) -> tuple[str, Dict[str, Any]]:
    settings = get_settings()
    if use_tools:
        return "groq/compound", {}
    model = settings.groq_model or "openai/gpt-oss-120b"
    if queue_len >= settings.reag_queue_high_watermark:
        model = settings.groq_fallback_model
    return model, {}


def _validate_scores(scores: Mapping[str, Any]) -> Optional[str]:
    required_numeric = [
        "p_to_n_conflict_ratio",
        "harsh_start_rate",
        "repair_attempts_per_hour",
        "repair_effectiveness_pct",
        "neg_affect_reciprocity",
        "median_reply_seconds",
        "p90_reply_seconds",
        "reply_variability",
        "emoji_signal_rate",
        "lsm_score",
        "affection_density",
        "gratitude_density",
        "future_planning_density",
        "plan_to_happen_ratio",
        "follow_through_latency_hours",
        "boundary_violations_per_1k",
        "contempt_markers_per_1k",
        "ruptures_per_month",
        "median_repair_cycle_hours",
    ]
    for key in required_numeric:
        if key not in scores or not isinstance(scores[key], (int, float)):
            return f"score:{key} missing or not numeric"
    demand = scores.get("demand_withdraw_rate")
    if not isinstance(demand, Mapping) or not all(
        isinstance(demand.get(sub), (int, float)) for sub in ("dw_AtoB", "dw_BtoA")
    ):
        return "demand_withdraw_rate invalid"
    bids = scores.get("bid_response_ratio")
    if not isinstance(bids, Mapping) or not all(
        isinstance(bids.get(kind), (int, float))
        for kind in ("affection", "info", "play", "requests")
    ):
        return "bid_response_ratio invalid"
    we_talk = scores.get("we_talk_index")
    if not isinstance(we_talk, Mapping):
        return "we_talk_index invalid"
    context = we_talk.get("context")
    if context not in {"plans", "blame", "neutral"}:
        return "we_talk context invalid"
    if not isinstance(we_talk.get("value"), (int, float)):
        return "we_talk value invalid"
    support = scores.get("support_balance_index")
    if not isinstance(support, Mapping) or not all(
        isinstance(support.get(partner), (int, float)) for partner in ("A", "B")
    ):
        return "support_balance_index invalid"
    return None


def _validate_payload(parsed: Mapping[str, Any]) -> Optional[str]:
    graph_data = parsed.get("graph")
    if graph_data is None:
        return "graph missing"
    if not isinstance(graph_data, list):
        return "graph must be list"
    for triple in graph_data:
        if not isinstance(triple, Mapping):
            return "graph entry invalid"
        for key in ("s", "p", "o", "t"):
            if key not in triple:
                return f"graph missing {key}"
        if not isinstance(triple["t"], int):
            return "graph timestamp invalid"
    scores = parsed.get("scores")
    if not isinstance(scores, Mapping):
        return "scores missing"
    score_error = _validate_scores(scores)
    if score_error:
        return score_error
    advice = parsed.get("advice")
    if not isinstance(advice, Mapping):
        return "advice missing"
    for key, value in advice.items():
        if not isinstance(key, str) or not key.startswith("user:"):
            return "advice key invalid"
        if not isinstance(value, str):
            return "advice value invalid"
    return None


def apply_graph(triples: Iterable[Mapping[str, Any]], couple_id: int) -> None:
    graph.upsert_people_edges(triples, couple_id)


def apply_scores(scores: Mapping[str, Any], couple_id: int) -> None:
    flat = flatten_metrics(scores)
    for key, value in flat.items():
        if isinstance(value, (int, float)):
            db.upsert_stat(couple_id, f"reag:{key}", float(value))


def apply_advice(advice_map: Mapping[str, str], couple_id: int) -> None:
    for key, text in advice_map.items():
        if not key.startswith("user:"):
            continue
        try:
            user_id = int(key.split(":", 1)[1])
        except ValueError:
            continue
        db.upsert_advice(couple_id, user_id, text)


def _build_messages(docs: Iterable[Mapping[str, Any]]) -> list[dict]:
    payload = json.dumps(list(docs), ensure_ascii=False, indent=2)
    return [
        {"role": "system", "content": SCHEMA_PROMPT},
        {
            "role": "user",
            "content": (
                "You will receive conversation slices as JSON. Respond with EXACTLY the schema below.\n"
                f"Schema: {STRICT_SCHEMA_DOC}\n"
                "Context:\n"
                f"{payload}\n"
            ),
        },
    ]


def _token_usage(response) -> tuple[int, int]:
    usage = getattr(response, "usage", None)
    if not usage:
        return 0, 0
    prompt = getattr(usage, "prompt_tokens", 0)
    completion = getattr(usage, "completion_tokens", 0)
    return int(prompt or 0), int(completion or 0)


def process_job(job_row, client: Groq) -> None:
    job_id = int(job_row["id"])
    couple_id = int(job_row["couple_id"])
    payload = json.loads(job_row["payload_json"])
    docs = payload.get("docs", [])
    use_tools = bool(payload.get("use_tools"))
    enabled_tools = payload.get("enabled_tools", [])

    if not docs:
        complete_job(
            job_id,
            couple_id=couple_id,
            token_in=0,
            token_out=0,
            model="noop",
            window_start_ts=int(timebox.utc_now().timestamp()),
            window_end_ts=int(timebox.utc_now().timestamp()),
        )
        return

    queue_len = pending_jobs_count()
    model, extra_args = _choose_model(use_tools, queue_len)
    if use_tools:
        extra_args["compound_custom"] = {"tools": {"enabled_tools": enabled_tools}}

    messages = _build_messages(docs)
    settings = get_settings()
    logger.info(
        "Processing job %s for couple %s with model=%s queue=%s",
        job_id,
        couple_id,
        model,
        queue_len,
    )
    start_ts = min(int(doc.get("ts_int", int(timebox.utc_now().timestamp()))) for doc in docs)
    end_ts = max(int(doc.get("ts_int", start_ts)) for doc in docs)
    started_monotonic = time.monotonic()

    if settings.chaos_mode and random.random() < settings.chaos_llm_p:
        raise RuntimeError("CHAOS: simulated LLM failure")

    response = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=0.2,
        top_p=1,
        max_completion_tokens=int(settings.reag_max_out_tokens or 4096),
        stream=False,
        **extra_args,
    )

    content = response.choices[0].message.get("content", "")
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        logger.error("Job %s returned non-JSON: %s", job_id, content[:200])
        fail_job(job_id, f"Invalid JSON response: {exc}")
        return

    if not isinstance(parsed, Mapping):
        fail_job(job_id, "Invalid JSON payload type")
        return

    validation_error = _validate_payload(parsed)
    if validation_error:
        logger.error("Job %s failed schema validation: %s", job_id, validation_error)
        fail_job(job_id, validation_error)
        return

    graph_data = parsed.get("graph", [])
    scores = parsed.get("scores", {})
    advice = parsed.get("advice", {})

    try:
        apply_graph(graph_data, couple_id)
        if isinstance(scores, Mapping):
            apply_scores(scores, couple_id)
        if isinstance(advice, Mapping):
            apply_advice(advice, couple_id)
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("Failed applying job %s", job_id)
        fail_job(job_id, f"apply_error: {exc}")
        return

    token_in, token_out = _token_usage(response)
    complete_job(
        job_id,
        couple_id=couple_id,
        token_in=token_in,
        token_out=token_out,
        model=model,
        window_start_ts=start_ts,
        window_end_ts=end_ts,
    )
    duration = time.monotonic() - started_monotonic
    logger.info(
        "Job %s done model=%s queue=%s tok_in=%s tok_out=%s duration=%.2fs",
        job_id,
        model,
        queue_len,
        token_in,
        token_out,
        duration,
    )


def main() -> None:
    settings = get_settings()
    logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))
    if not settings.groq_api_key:
        raise RuntimeError("GROQ_API_KEY is required for the REAG worker")
    client = Groq(api_key=settings.groq_api_key, timeout=30.0)
    logger.info("REAG worker started")
    while True:
        job = claim_job()
        if not job:
            time.sleep(3)
            continue
        try:
            process_job(job, client)
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("Unhandled error processing job %s", job["id"])
            fail_job(int(job["id"]), f"worker_error: {exc}")
            time.sleep(1)


if __name__ == "__main__":
    main()
