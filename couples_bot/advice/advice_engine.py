"""Advice generation helpers."""

from __future__ import annotations

from typing import Dict, List, Tuple

from .. import db
from ..llm import provider, prompts
from ..metrics import compute


SIGNAL_TEMPLATES: Dict[str, Dict[str, str]] = {
    "neg_affect": {
        "desc": "the tension kept ricocheting between you",
        "action": "Call a 10-minute timeout, then restart with one validation and one small ask for today.",
        "phrase": "\"Hey, that spiked for both of us. I value you—can we reset at 7 and handle __ together?\"",
    },
    "demand_withdraw": {
        "desc": "demands were met with shutdowns",
        "action": "Swap the demand for two doable choices you can both live with tonight.",
        "phrase": "\"I was pushing hard. Here's option A and option B—what fits you better this evening?\"",
    },
    "boundary": {
        "desc": "a boundary felt crossed",
        "action": "Own the overstep, restate your need, and ask for a yes/no check-in.",
        "phrase": "\"That came out harsh. What I need is __. Could we try __ instead?\"",
    },
    "contempt": {
        "desc": "a contempt spike landed",
        "action": "Step away for 15 minutes, then re-open with one appreciation before the problem-solving.",
        "phrase": "\"I don't want that tone between us. I appreciate __. Can we tackle __ calmly at __?\"",
    },
    "plan_slip": {
        "desc": "plans due today started slipping",
        "action": "Confirm what still happens in the next 24h and reschedule the rest while you're both present.",
        "phrase": "\"We promised __ for today. Let's lock what's still doable and move the rest to __.\"",
    },
    "slow_reply": {
        "desc": "reply times drifted past your agreement",
        "action": "Send a timestamped update and agree on a fresh SLA before the next busy block.",
        "phrase": "\"Quick heads-up: I'm buried until __. I'll reply by __—does that work?\"",
    },
    "support_gap": {
        "desc": "support trades tilted heavily to one side",
        "action": "List two assists each of you can own this week and swap who starts tonight.",
        "phrase": "\"I can take __ and __. Could you grab __ while I cover these?\"",
    },
}


def _trim_words(text: str, limit: int = 120) -> str:
    words = text.split()
    if len(words) <= limit:
        return text
    return " ".join(words[:limit]) + "…"


def _metrics_summary(flat: Dict[str, float]) -> str:
    highlights = [
        f"conflict ratio {flat.get('p_to_n_conflict_ratio', 0):.2f}",
        f"harsh start {flat.get('harsh_start_rate', 0):.2f}",
        f"median reply {flat.get('median_reply_seconds', 0)/60:.1f}m",
        f"neg reciprocity {flat.get('neg_affect_reciprocity', 0):.2f}",
        f"plan ratio {flat.get('plan_to_happen_ratio', 1.0):.2f}",
        f"follow-through {flat.get('follow_through_latency_hours', 0):.1f}h",
    ]
    return ", ".join(highlights)


def _risk_signals(flat: Dict[str, float]) -> List[Tuple[float, str]]:
    scores: List[Tuple[float, str]] = []
    neg = float(flat.get("neg_affect_reciprocity", 0.0))
    if neg > 0.05:
        scores.append((neg, "neg_affect"))
    dw_a = float(flat.get("demand_withdraw_rate.dw_AtoB", 0.0))
    dw_b = float(flat.get("demand_withdraw_rate.dw_BtoA", 0.0))
    if max(dw_a, dw_b) > 0:
        scores.append(((max(dw_a, dw_b) / 100.0), "demand_withdraw"))
    boundary = float(flat.get("boundary_violations_per_1k", 0.0))
    if boundary > 0:
        scores.append(((boundary / 100.0), "boundary"))
    contempt = float(flat.get("contempt_markers_per_1k", 0.0))
    if contempt > 0:
        scores.append(((contempt / 100.0), "contempt"))
    plan_gap = max(0.0, 1.0 - float(flat.get("plan_to_happen_ratio", 1.0)))
    if plan_gap > 0.1:
        scores.append((plan_gap, "plan_slip"))
    median_reply = float(flat.get("median_reply_seconds", 0.0))
    if median_reply > 1200:  # >20 minutes
        scores.append(((median_reply - 1200) / 1200.0, "slow_reply"))
    support_gap = max(abs(float(flat.get("support_balance_index.A", 0.0))), abs(float(flat.get("support_balance_index.B", 0.0))))
    if support_gap >= 4:
        scores.append((support_gap / 10.0, "support_gap"))
    return sorted(scores, key=lambda item: item[0], reverse=True)


def _bright_spots(flat: Dict[str, float]) -> List[str]:
    spots: List[str] = []
    if float(flat.get("repair_effectiveness_pct", 0.0)) >= 50:
        spots.append("your repair attempts landed recently")
    latency = float(flat.get("follow_through_latency_hours", 0.0))
    if 0 < latency <= 6:
        spots.append("follow-through stayed quick")
    if float(flat.get("p_to_n_conflict_ratio", 1.0)) >= 2.0:
        spots.append("the positivity ratio is strong")
    return spots


def _rule_based(metrics: Dict[str, object], partner_label: str) -> str:
    flat = compute.flatten_metrics(metrics)
    signals = _risk_signals({k: float(v) for k, v in flat.items() if isinstance(v, (int, float))})
    bright = _bright_spots({k: float(v) for k, v in flat.items() if isinstance(v, (int, float))})

    if signals:
        descriptions = [SIGNAL_TEMPLATES[sig]["desc"] for _, sig in signals[:2] if sig in SIGNAL_TEMPLATES]
        if descriptions:
            empathy = "It sounds like " + " and ".join(descriptions) + "."
        else:
            empathy = "It sounds like the day carried some friction."
    else:
        empathy = "It sounds like today was full, yet you're both still showing up."

    if bright:
        empathy += f" Good news: {bright[0]}."
    else:
        empathy += " Take one long breath together before the next move."

    primary = signals[0][1] if signals else None
    template = SIGNAL_TEMPLATES.get(primary or "")
    if template:
        action = template["action"]
        phrase = template["phrase"]
    else:
        action = "Pick one 10-minute task you can finish together tonight and set a start time now."
        phrase = "\"I'm glad we're a team. Want to knock out __ together at __? I'll start it.\""

    if bright and template and primary not in {"plan_slip", "slow_reply"}:
        action = "Reuse the repair that already worked—lead with an appreciation, then make the small ask for tonight."
        phrase = "\"I appreciate __. Could we repeat what worked last time and tackle __ at __?\""

    return f"Hey {partner_label}, {empathy} {action} Try this phrasing: {phrase}"


def _call_llm(messages: List[dict], *, max_tokens: int = 320) -> str:
    result = provider.llm_complete(
        messages,
        max_tokens=max_tokens,
        temperature=0.3,
    )
    if isinstance(result, str):
        return result.strip()
    return "".join(result).strip()


def build_advice_for_user(couple_id: int, user_id: int, partner_label: str | None = None) -> str:
    """Generate advice text for the specified partner."""

    partner_label = partner_label or f"partner {user_id}"
    messages = db.fetch_recent_messages(couple_id, limit=120)
    metrics = compute.compute_metrics(messages)
    flat = compute.flatten_metrics(metrics)

    summary = _metrics_summary({k: float(v) for k, v in flat.items() if isinstance(v, (int, float))})
    try:
        chat_messages = prompts.advice_prompt(partner_label, summary)
        advice_text = _call_llm(chat_messages)
    except provider.LLMDisabled:
        advice_text = _rule_based(metrics, partner_label)

    advice_text = _trim_words(advice_text)
    db.upsert_advice(couple_id, user_id, advice_text)
    return advice_text


def build_advocate_for_user(
    couple_id: int,
    user_id: int,
    issue: str,
    partner_label: str | None = None,
) -> str:
    """Generate an advocacy message (steelman + ask) for a partner."""

    partner_label = partner_label or f"partner {user_id}"
    try:
        chat_messages = prompts.advocate_prompt(partner_label, issue)
        text = _call_llm(chat_messages, max_tokens=200)
    except provider.LLMDisabled:
        text = (
            f"Hey {partner_label}, lead with one empathy line then the ask: say you get why it matters, "
            f"name the specific support you need, and confirm timing. Try this phrasing: \"I know __ is a lot. "
            f"Could you handle __ by __? It would help me breathe.\""
        )
    return _trim_words(text)


__all__ = ["build_advice_for_user", "build_advocate_for_user"]
