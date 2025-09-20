"""Advice builder for each partner."""

from __future__ import annotations

from typing import Dict

from .. import db
from ..llm import provider, prompts
from ..metrics import compute


def _metrics_summary(metrics: Dict[str, float]) -> str:
    highlights = [
        f"conflict ratio {metrics.get('p_to_n_conflict_ratio', 0):.2f}",
        f"harsh start rate {metrics.get('harsh_start_rate', 0):.2f}",
        f"median reply {metrics.get('median_reply_seconds', 0)/60:.1f}m",
    ]
    return ", ".join(highlights)


def build_advice_for_user(couple_id: int, user_id: int, partner_label: str | None = None) -> str:
    """Generate advice text for the specified partner."""

    partner_label = partner_label or f"partner {user_id}"
    messages = db.fetch_recent_messages(couple_id, limit=120)
    metrics = compute.compute_metrics(messages)

    summary = _metrics_summary(metrics)
    try:
        chat_messages = prompts.advice_prompt(partner_label, summary)
        result = provider.llm_complete(chat_messages, max_tokens=260, temperature=0.4)
        if isinstance(result, str):
            advice_text = result.strip()
        else:
            advice_text = "".join(result).strip()
    except provider.LLMDisabled:
        # Rule-based fallback
        advice_text = (
            f"Hey {partner_label}, it looks like your conflict positivity ratio is"
            f" {metrics.get('p_to_n_conflict_ratio', 0):.1f}. Lead with one"
            " appreciation and suggest a specific plan. Try this phrasing:"
            " 'Thanks for hanging in—can we tackle the dishes together at 7?'"
        )

    db.upsert_advice(couple_id, user_id, advice_text)
    return advice_text


__all__ = ["build_advice_for_user"]
