"""Schema + encryption helpers for time-series check-ins.

This module implements the two-measurement design described in the product
spec:

- ``checkin_meta`` holds low-sensitivity adherence metadata (plaintext)
- ``checkin_payload`` holds the encrypted answers JSON

All writes share the scheduled timestamp as ``_time`` and a low-cardinality tag
set so a stolen database reveals only ciphertext.
"""

from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

ISO_FMT = "%Y-%m-%dT%H:%M:%SZ"
DEFAULT_LATE_SECONDS = 45 * 60


def _to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _ts(value: datetime | str | None) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return _to_utc(value).strftime(ISO_FMT)


@dataclass
class KeyMaterial:
    kid: int
    key: bytes


@dataclass
class KeyRing:
    """Simple AES-GCM keyring with newest-first ordering."""

    keys: List[KeyMaterial] = field(default_factory=list)

    @classmethod
    def from_serialized(cls, data: str) -> "KeyRing":
        """Parse ``PAYLOAD_KEYRING`` strings like ``"2:...base64...,1:..."``."""

        materials: list[KeyMaterial] = []
        if data.strip():
            for entry in data.split(","):
                kid_str, key_b64 = entry.split(":", 1)
                key = base64.b64decode(key_b64)
                materials.append(KeyMaterial(kid=int(kid_str), key=key))
        # Sort newest (highest kid) first to attempt decrypts in that order.
        materials.sort(key=lambda km: km.kid, reverse=True)
        return cls(materials)

    @property
    def active(self) -> KeyMaterial:
        if not self.keys:
            raise ValueError("Keyring is empty; set PAYLOAD_KEYRING")
        return self.keys[0]

    def encrypt(self, payload: Mapping[str, Any], *, kid: Optional[int] = None) -> Dict[str, Any]:
        """Encrypt the payload JSON with AES-GCM.

        The nonce+ct are base64 encoded for storage.
        """

        key = self._find_key(kid)
        aesgcm = AESGCM(key.key)
        nonce = os.urandom(12)
        raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        ct = aesgcm.encrypt(nonce, raw, None)
        blob = base64.b64encode(nonce + ct).decode("utf-8")
        return {
            "ciphertext": blob,
            "kid": key.kid,
            "length": len(blob),
        }

    def decrypt(self, ciphertext: str) -> Mapping[str, Any]:
        raw = base64.b64decode(ciphertext)
        nonce, ct = raw[:12], raw[12:]
        for key in self.keys:
            aesgcm = AESGCM(key.key)
            try:
                pt = aesgcm.decrypt(nonce, ct, None)
                return json.loads(pt)
            except Exception:
                continue
        raise ValueError("Unable to decrypt payload with available keys")

    def _find_key(self, kid: Optional[int]) -> KeyMaterial:
        if kid is None:
            return self.active
        for key in self.keys:
            if key.kid == kid:
                return key
        raise ValueError(f"Unknown key id {kid}")


def _clamp(value: Optional[float], *, lo: float, hi: float) -> Optional[float]:
    if value is None:
        return None
    return max(lo, min(hi, float(value)))


def _normalize_answer(entry: Any, *, lo: float, hi: float) -> Dict[str, Any]:
    if entry is None:
        return {"v": None, "t": None, "m": None}
    if isinstance(entry, Mapping):
        value = entry.get("v")
        when = entry.get("t")
        method = entry.get("m")
    else:
        value, when, method = entry, None, None
    return {"v": _clamp(value, lo=lo, hi=hi), "t": _ts(when), "m": method}


def _bool_answer(entry: Any) -> Dict[str, Any]:
    if entry is None:
        return {"v": None, "t": None, "m": None}
    if isinstance(entry, Mapping):
        value = entry.get("v")
        when = entry.get("t")
        method = entry.get("m")
    else:
        value, when, method = entry, None, None
    normalized = 1 if value else 0
    return {"v": normalized, "t": _ts(when), "m": method}


def build_payload(
    *,
    schema_v: int,
    checkin_id: str,
    scheduled_at_utc: datetime,
    slot: str,
    set_label: str,
    checkin_type: str,
    tz: Optional[str],
    started_at_utc: Optional[datetime],
    finished_at_utc: Optional[datetime],
    answers: Mapping[str, Any],
    tags: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    """Build the plaintext payload dict before encryption."""

    payload_answers: Dict[str, Any] = {
        "q1": _normalize_answer(answers.get("q1"), lo=0, hi=10),
        "q2": _normalize_answer(answers.get("q2"), lo=0, hi=10),
        "q3": _normalize_answer(answers.get("q3"), lo=-5, hi=5),
        "q4": _normalize_answer(answers.get("q4"), lo=0, hi=10),
        "q5": _normalize_answer(answers.get("q5"), lo=0, hi=10),
        "q6": _normalize_answer(answers.get("q6"), lo=0, hi=24),
        "q7": _normalize_answer(answers.get("q7"), lo=1, hi=5),
        "q8": _bool_answer(answers.get("q8")),
        "q9": _bool_answer(answers.get("q9")),
        "q10": {
            "caffeine_mg": _normalize_answer(answers.get("q10.caffeine_mg"), lo=0, hi=600),
            "baclofen_hours": _normalize_answer(answers.get("q10.baclofen_hours"), lo=0, hi=24),
        },
    }

    return {
        "schema_v": schema_v,
        "checkin_id": checkin_id,
        "scheduled_at_utc": _ts(scheduled_at_utc),
        "started_at_utc": _ts(started_at_utc),
        "finished_at_utc": _ts(finished_at_utc),
        "slot": slot,
        "set": set_label,
        "type": checkin_type,
        "tz": tz,
        "answers": payload_answers,
        "tags": list(tags or []),
    }


def _answered_fraction(payload: Mapping[str, Any]) -> tuple[int, int]:
    """Return (answered, total) using the 10-question contract."""

    answers = payload.get("answers", {})
    simple_keys = ["q1", "q2", "q3", "q4", "q5", "q6", "q7", "q8", "q9"]
    answered = sum(1 for key in simple_keys if answers.get(key, {}).get("v") is not None)
    q10 = answers.get("q10", {})
    if any(entry.get("v") is not None for entry in q10.values()):
        answered += 1
    return answered, 10


def _latency_seconds(scheduled_at: datetime, answered_at: Optional[datetime]) -> Optional[int]:
    if answered_at is None:
        return None
    return int((_to_utc(answered_at) - _to_utc(scheduled_at)).total_seconds())


def _status_code(*, completion_pct: float, latency_sec: Optional[int], missed: bool) -> int:
    if missed and completion_pct == 0:
        return 3
    if completion_pct >= 1.0:
        return 1
    if completion_pct > 0:
        if latency_sec is not None and latency_sec > DEFAULT_LATE_SECONDS:
            return 4
        return 2
    return 0


@dataclass
class Measurement:
    measurement: str
    tags: Dict[str, str]
    fields: Dict[str, Any]
    time: str


class CheckinStore:
    """In-memory representation of measurement writes for testing and exports."""

    def __init__(self, keyring: KeyRing, *, schema_v: int = 1) -> None:
        self.keyring = keyring
        self.schema_v = schema_v
        self.meta: list[Measurement] = []
        self.payloads: list[Measurement] = []

    def record_checkin(
        self,
        *,
        checkin_id: str,
        scheduled_at_utc: datetime,
        slot: str,
        set_label: str,
        checkin_type: str,
        user: str,
        tz: Optional[str],
        answers: Mapping[str, Any],
        started_at_utc: Optional[datetime] = None,
        finished_at_utc: Optional[datetime] = None,
        muted_during_window: bool = False,
        nudge_count: int = 0,
        missed: bool = False,
        tags: Optional[Iterable[str]] = None,
    ) -> tuple[Measurement, Measurement]:
        payload = build_payload(
            schema_v=self.schema_v,
            checkin_id=checkin_id,
            scheduled_at_utc=scheduled_at_utc,
            started_at_utc=started_at_utc,
            finished_at_utc=finished_at_utc,
            slot=slot,
            set_label=set_label,
            checkin_type=checkin_type,
            tz=tz,
            answers=answers,
            tags=tags,
        )
        encrypted = self.keyring.encrypt(payload)

        answered, total = _answered_fraction(payload)
        completion_pct = answered / total if total else 0.0
        answered_at = finished_at_utc or started_at_utc
        latency = _latency_seconds(scheduled_at_utc, answered_at)
        status = _status_code(completion_pct=completion_pct, latency_sec=latency, missed=missed)

        tag_set = {
            "user": user,
            "slot": slot,
            "set": set_label,
            "type": checkin_type,
            "schema_v": str(self.schema_v),
        }
        if tz:
            tag_set["tz"] = tz

        meta_fields: dict[str, Any] = {
            "status_code": status,
            "answered_at_utc": _ts(answered_at),
            "latency_sec": latency,
            "completion_pct": completion_pct,
            "missing_count": total - answered,
            "nudge_count": nudge_count,
            "muted_during_window": 1 if muted_during_window else 0,
        }

        meta = Measurement(
            measurement="checkin_meta",
            tags=tag_set,
            fields=meta_fields,
            time=_ts(scheduled_at_utc) or "",
        )
        payload_measurement = Measurement(
            measurement="checkin_payload",
            tags=tag_set,
            fields={
                "payload_ciphertext": encrypted["ciphertext"],
                "payload_kid": encrypted["kid"],
                "payload_len": encrypted["length"],
            },
            time=_ts(scheduled_at_utc) or "",
        )

        self.meta.append(meta)
        self.payloads.append(payload_measurement)
        return meta, payload_measurement

    def decrypt_payload(self, payload_measurement: Measurement) -> Mapping[str, Any]:
        return self.keyring.decrypt(payload_measurement.fields["payload_ciphertext"])

    def export_csv(
        self,
        *,
        days: Optional[int] = None,
        now: Optional[datetime] = None,
    ) -> str:
        """Decrypt payloads and export a wide CSV for doctor handoff."""

        now = now or datetime.now(timezone.utc)
        cutoff = None
        if days is not None:
            cutoff = _to_utc(now) - timedelta(days=days)

        rows: list[Mapping[str, Any]] = []
        for payload in self.payloads:
            ts = datetime.strptime(payload.time, ISO_FMT).replace(tzinfo=timezone.utc)
            if cutoff and ts < cutoff:
                continue
            decoded = self.decrypt_payload(payload)
            answers = decoded.get("answers", {})
            q10 = answers.get("q10", {})
            rows.append(
                {
                    "checkin_id": decoded.get("checkin_id"),
                    "scheduled_at_utc": decoded.get("scheduled_at_utc"),
                    "started_at_utc": decoded.get("started_at_utc"),
                    "finished_at_utc": decoded.get("finished_at_utc"),
                    "slot": decoded.get("slot"),
                    "set": decoded.get("set"),
                    "type": decoded.get("type"),
                    "q1": answers.get("q1", {}).get("v"),
                    "q2": answers.get("q2", {}).get("v"),
                    "q3": answers.get("q3", {}).get("v"),
                    "q4": answers.get("q4", {}).get("v"),
                    "q5": answers.get("q5", {}).get("v"),
                    "q6": answers.get("q6", {}).get("v"),
                    "q7": answers.get("q7", {}).get("v"),
                    "q8": answers.get("q8", {}).get("v"),
                    "q9": answers.get("q9", {}).get("v"),
                    "q10_caffeine_mg": q10.get("caffeine_mg", {}).get("v"),
                    "q10_baclofen_hours": q10.get("baclofen_hours", {}).get("v"),
                    "tags": "|".join(decoded.get("tags", [])),
                }
            )

        headings = list(rows[0].keys()) if rows else []
        lines = [",".join(headings)]
        for row in rows:
            parts = []
            for key in headings:
                value = row.get(key)
                parts.append("" if value is None else str(value))
            lines.append(",".join(parts))
        return "\n".join(lines).strip()


__all__ = ["KeyRing", "Measurement", "CheckinStore", "build_payload"]
