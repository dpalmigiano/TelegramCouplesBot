"""Prompt templates for advice generation."""

from __future__ import annotations

from typing import List

SYSTEM_PROMPT = (
    "You are a pragmatic couples coach. Offer short, concrete support in plain"
    " English. Avoid therapy jargon and never diagnose."
)


def advice_prompt(partner_name: str, metrics_summary: str) -> List[dict]:
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                "Partner {name} needs a check-in. Metrics summary:\n{summary}\n"
                "Provide: 1 empathy sentence, 1 concrete action for today, and"
                " suggest a short phrasing they can send."
            ).format(name=partner_name, summary=metrics_summary),
        },
    ]


def advocate_prompt(partner_name: str, issue: str) -> List[dict]:
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                "Help {name} advocate for their need. Situation: {issue}."
                " Give one validating sentence and one clear ask."
            ).format(name=partner_name, issue=issue),
        },
    ]


__all__ = ["advice_prompt", "advocate_prompt", "SYSTEM_PROMPT"]
