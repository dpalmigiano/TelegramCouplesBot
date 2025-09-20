"""Background worker that processes REAG jobs."""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, Iterable, Mapping

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
from couples_bot.store import graph
from couples_bot.utils import timebox
from couples_bot.metrics.compute import flatten_metrics

SCHEMA_PROMPT = (
    "You are a reasoning worker for a couples-coaching bot. Respond with STRICT JSON "
    "matching the provided schema. Do not add commentary or Markdown."
)

JSON_SCHEMA = (
    "{\n"
    "  \"graph\": [ { \"s\": str, \"p\": str, \"o\": str, \"t\": int } ],\n"
    "  \"scores\": { ... 18 metric fields as described },\n"
    "  \"advice\": { \"user:<id>\": \"Empathy. Action. Try this phrasing: ...\" }\n"
    "}"
)

logger = logging.getLogger(__name__)


def _choose_model(use_tools: bool, queue_len: int) -> tuple[str, Dict[str, Any]]:
    settings = get_settings()
    if use_tools:
        return "groq/compound", {}
    model = settings.groq_model or "openai/gpt-oss-120b"
    if queue_len >= settings.reag_queue_high_watermark:
        model = settings.groq_fallback_model
    return model, {}


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
                f"Schema: {JSON_SCHEMA}\n"
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
        "Processing job %s for couple %s with model=%s queue=%s", job_id, couple_id, model, queue_len
    )
    start_ts = min(int(doc.get("ts_int", int(timebox.utc_now().timestamp()))) for doc in docs)
    end_ts = max(int(doc.get("ts_int", start_ts)) for doc in docs)

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
