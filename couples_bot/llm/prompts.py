"""Prompt templates for advice and advocacy."""
from __future__ import annotations

from typing import Sequence


BASE_SYSTEM_PROMPT = (
    "You are a concise couples coach. You speak plainly, avoid therapy jargon, and always give "
    "one empathy observation, one concrete action, and one suggested phrase."
)


def advice_prompt(partner_name: str, metrics_summary: str) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": BASE_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"Partner: {partner_name}. Metrics summary: {metrics_summary}. "
                "Write guidance with the format: Empathy. Action. Try this phrasing."
            ),
        },
    ]


def advocate_prompt(partner_name: str, needs: Sequence[str]) -> list[dict[str, str]]:
    needs_text = ", ".join(needs) if needs else "no specific needs logged"
    return [
        {"role": "system", "content": BASE_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"Partner: {partner_name}. Advocate for these needs: {needs_text}. "
                "Respond with one-sentence encouragement and one boundary reminder."
            ),
        },
    ]


__all__ = ["BASE_SYSTEM_PROMPT", "advice_prompt", "advocate_prompt"]
