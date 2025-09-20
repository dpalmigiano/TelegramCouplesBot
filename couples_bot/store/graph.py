"""Optional graph/vector store adapters."""

from __future__ import annotations

from typing import Iterable, Mapping

from ..config import get_settings


def _enabled() -> bool:
    return bool(get_settings().graph_enabled)


def upsert_people_edges(triples: Iterable[Mapping[str, object]], couple_id: int) -> None:
    """Persist relationship triples when the graph store is enabled."""

    if not _enabled():  # pragma: no cover - feature flag
        return
    _ = triples, couple_id  # Placeholder for integration hook.


def upsert_message_embedding(message_id: str, vector: Iterable[float]) -> None:
    if not _enabled():  # pragma: no cover - feature flag
        return
    _ = message_id, list(vector)


def link_plan_confirmation(plan_id: str, confirmation_id: str) -> None:
    if not _enabled():  # pragma: no cover - feature flag
        return
    _ = plan_id, confirmation_id


__all__ = [
    "upsert_people_edges",
    "upsert_message_embedding",
    "link_plan_confirmation",
]
