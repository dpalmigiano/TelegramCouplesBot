"""Advice generation for each partner."""
from __future__ import annotations

from typing import Optional

from .. import db
from ..config import get_settings
from ..llm import prompts, provider
from ..metrics import compute as metrics_compute


def _fallback_advice(user_id: int, metrics: dict) -> str:
    ratio = metrics.get("p_to_n_conflict_ratio", 1.0)
    harsh = metrics.get("harsh_start_rate", 0.0)
    reply = metrics.get("median_reply_seconds", 0.0)
    empathy = (
        "You two have bright moments showing up" if ratio >= 1.5 else "This stretch feels heavy"
    )
    action = (
        "Open with a gentle ask tonight" if harsh > 0.1 else "Keep reinforcing the warm check-ins"
    )
    phrasing = (
        "I want us on the same side, can we reset?"
        if harsh > 0.1
        else "I loved how you backed me up earlier—let's keep that energy."
    )
    if reply > 90:
        action = "Nudge a quick reply during your agreed window"
        phrasing = "I'm around now, can we tackle the errand together?"
    return f"{empathy}. Action: {action}. Try this phrasing: \"{phrasing}\""


def build_advice_for_user(couple_id: int, user_id: int, *, conn: Optional[object] = None) -> str:
    connection = conn or db.get_conn()
    messages = [dict(row) for row in db.iter_messages(connection, couple_id)]
    metrics = metrics_compute.compute_metrics(messages)
    settings = get_settings()

    metrics_summary = (
        f"p:n={metrics.get('p_to_n_conflict_ratio')}, harsh={metrics.get('harsh_start_rate')}, "
        f"reply={metrics.get('median_reply_seconds')}s"
    )
    advice_text: Optional[str] = None
    if settings.enable_llm:
        try:
            completion = provider.llm_complete(
                prompts.advice_prompt(str(user_id), metrics_summary)
            )
            if isinstance(completion, str):
                advice_text = completion.strip()
            else:
                advice_text = "".join(completion).strip()
        except provider.LLMDisabled:
            advice_text = None
        except Exception:
            advice_text = None

    if not advice_text:
        advice_text = _fallback_advice(user_id, metrics)

    db.upsert_advice(connection, couple_id, user_id, advice_text)
    return advice_text


__all__ = ["build_advice_for_user"]
