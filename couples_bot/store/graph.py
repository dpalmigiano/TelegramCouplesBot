"""Optional graph/vector store adapters."""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from typing import Iterable, Mapping, Sequence

from .. import db
from ..config import get_settings

logger = logging.getLogger(__name__)


class GraphStore:
    """Lightweight graph writer guarded by GRAPH_ENABLED."""

    def __init__(self) -> None:
        self._enabled = bool(get_settings().graph_enabled)

    @property
    def enabled(self) -> bool:
        return self._enabled

    def upsert_batch(
        self,
        *,
        couple_id: int,
        nodes: Sequence[Mapping[str, object]] = (),
        edges: Sequence[Mapping[str, object]] = (),
    ) -> None:
        if not self.enabled:
            return

        node_map: dict[str, Mapping[str, object]] = {}
        for node in nodes:
            node_id = str(node.get("id", ""))
            if not node_id:
                continue
            node_map[node_id] = {
                "id": node_id,
                "type": str(node.get("type", "node")),
                "label": str(node.get("label", node_id)),
                "ts": int(node.get("ts", int(time.time()))),
                "tags": list(node.get("tags", [])),
                "content": str(node.get("content", "")),
            }

        edge_list = []
        for edge in edges:
            src = edge.get("src")
            dst = edge.get("dst")
            kind = edge.get("kind")
            if not src or not dst or not kind:
                continue
            created = int(edge.get("ts", int(time.time())))
            edge_list.append(
                {
                    "src": str(src),
                    "dst": str(dst),
                    "kind": str(kind),
                    "created_ts": created,
                }
            )

        attempts = 0
        while attempts < 3:
            try:
                with db.get_conn() as conn:
                    for node in node_map.values():
                        tags_json = json.dumps(node["tags"], ensure_ascii=False)
                        conn.execute(
                            """
                            INSERT INTO graph_nodes(id, couple_id, type, label, ts, tags, content)
                            VALUES(?,?,?,?,?,?,?)
                            ON CONFLICT(id) DO UPDATE SET
                                couple_id=excluded.couple_id,
                                type=excluded.type,
                                label=excluded.label,
                                ts=excluded.ts,
                                tags=excluded.tags,
                                content=excluded.content
                            """,
                            (
                                node["id"],
                                couple_id,
                                node["type"],
                                node["label"],
                                node["ts"],
                                tags_json,
                                node["content"],
                            ),
                        )
                        conn.execute(
                            "DELETE FROM graph_node_fts WHERE node_id = ?",
                            (node["id"],),
                        )
                        conn.execute(
                            "INSERT INTO graph_node_fts(node_id, content) VALUES(?, ?)",
                            (node["id"], node["content"]),
                        )
                    for edge in edge_list:
                        conn.execute(
                            """
                            INSERT INTO graph_edges(couple_id, src, dst, kind, created_ts)
                            VALUES(?,?,?,?,?)
                            ON CONFLICT(couple_id, src, dst, kind) DO UPDATE SET
                                created_ts=excluded.created_ts
                            """,
                            (
                                couple_id,
                                edge["src"],
                                edge["dst"],
                                edge["kind"],
                                edge["created_ts"],
                            ),
                        )
                return
            except sqlite3.OperationalError as exc:  # pragma: no cover - transient
                attempts += 1
                logger.warning("graph_upsert_retry couple_id=%s error=%s attempts=%s", couple_id, exc, attempts)
                time.sleep(0.05 * attempts)
        raise RuntimeError("graph upsert failed")


_STORE: GraphStore | None = None


def _store() -> GraphStore:
    global _STORE
    settings = get_settings()
    if _STORE is None or _STORE.enabled != bool(settings.graph_enabled):
        _STORE = GraphStore()
    return _STORE


def _infer_couple_id(identifier: str) -> int | None:
    parts = identifier.split(":")
    for index, part in enumerate(parts):
        if part == "couple" and index + 1 < len(parts):
            try:
                return int(parts[index + 1])
            except ValueError:  # pragma: no cover - defensive parsing
                continue
    return None


def upsert_people_edges(triples: Iterable[Mapping[str, object]], couple_id: int) -> None:
    store = _store()
    if not store.enabled:
        return
    nodes = {}
    edges = []
    for triple in triples:
        src = str(triple.get("s", ""))
        dst = str(triple.get("o", ""))
        predicate = str(triple.get("p", "rel"))
        ts = int(triple.get("t", int(time.time())))
        if not src or not dst:
            continue
        nodes[src] = {
            "id": src,
            "type": "entity",
            "label": src,
            "ts": ts,
            "tags": ["person"] if src.startswith("user:") else [],
            "content": src,
        }
        nodes[dst] = {
            "id": dst,
            "type": "entity",
            "label": dst,
            "ts": ts,
            "tags": [],
            "content": dst,
        }
        edges.append({"src": src, "dst": dst, "kind": predicate, "ts": ts})
    store.upsert_batch(couple_id=couple_id, nodes=list(nodes.values()), edges=edges)


def upsert_message_embedding(message_id: str, vector: Iterable[float]) -> None:
    store = _store()
    if not store.enabled:
        return
    couple_id = _infer_couple_id(message_id)
    if couple_id is None:
        return
    vector_list = [float(x) for x in vector]
    snippet = ",".join(f"{value:.3f}" for value in vector_list[:8])
    store.upsert_batch(
        couple_id=couple_id,
        nodes=[
            {
                "id": message_id,
                "type": "message",
                "label": message_id,
                "ts": int(time.time()),
                "tags": ["embedding"],
                "content": snippet,
            }
        ],
        edges=[],
    )


def link_plan_confirmation(plan_id: str, confirmation_id: str) -> None:
    store = _store()
    if not store.enabled:
        return
    couple_id = _infer_couple_id(plan_id) or _infer_couple_id(confirmation_id)
    if couple_id is None:
        return
    now_ts = int(time.time())
    nodes = [
        {
            "id": plan_id,
            "type": "event",
            "label": plan_id,
            "ts": now_ts,
            "tags": ["plan"],
            "content": plan_id,
        },
        {
            "id": confirmation_id,
            "type": "event",
            "label": confirmation_id,
            "ts": now_ts,
            "tags": ["confirmation"],
            "content": confirmation_id,
        },
    ]
    edges = [
        {"src": plan_id, "dst": confirmation_id, "kind": "fulfills", "ts": now_ts}
    ]
    store.upsert_batch(couple_id=couple_id, nodes=nodes, edges=edges)


__all__ = [
    "GraphStore",
    "upsert_people_edges",
    "upsert_message_embedding",
    "link_plan_confirmation",
]
