from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone

from couples_bot.checkins import CheckinStore, KeyRing



def _keyring(*, kid: int = 1, marker: bytes = b"k") -> str:
    key = (marker * 32)[:32]
    return f"{kid}:{base64.b64encode(key).decode('utf-8')}"


def test_record_checkin_happy_path():
    ring = KeyRing.from_serialized(_keyring(kid=1, marker=b"a"))
    store = CheckinStore(ring)

    scheduled = datetime(2026, 1, 3, 18, 0, 0, tzinfo=timezone.utc)
    started = scheduled + timedelta(minutes=2, seconds=10)
    finished = scheduled + timedelta(minutes=3, seconds=5)

    answers = {
        "q1": {"v": 7, "t": started + timedelta(seconds=5), "m": "button"},
        "q2": {"v": 4, "t": started + timedelta(seconds=10), "m": "button"},
        "q3": {"v": -1, "t": started + timedelta(seconds=15), "m": "button"},
        "q4": {"v": 6, "t": started + timedelta(seconds=20), "m": "button"},
        "q5": {"v": 3, "t": started + timedelta(seconds=25), "m": "button"},
        "q6": {"v": 6.5, "t": started + timedelta(seconds=35), "m": "custom"},
        "q7": {"v": 2, "t": started + timedelta(seconds=40), "m": "button"},
        "q8": {"v": 0, "t": started + timedelta(seconds=45), "m": "button"},
        "q9": {"v": 1, "t": started + timedelta(seconds=50), "m": "button"},
        "q10.caffeine_mg": {"v": 95, "t": finished - timedelta(seconds=3)},
        "q10.baclofen_hours": {"v": 2.0, "t": finished},
    }

    meta, payload = store.record_checkin(
        checkin_id="a1b2c3d4e5",
        scheduled_at_utc=scheduled,
        slot="10:00",
        set_label="FULL",
        checkin_type="scheduled",
        user="user123",
        tz="UTC",
        answers=answers,
        started_at_utc=started,
        finished_at_utc=finished,
        muted_during_window=False,
        nudge_count=1,
    )

    assert meta.measurement == "checkin_meta"
    assert payload.measurement == "checkin_payload"
    assert meta.tags["slot"] == "10:00"
    assert meta.fields["status_code"] == 1
    assert meta.fields["completion_pct"] == 1.0
    assert meta.fields["missing_count"] == 0
    assert payload.fields["payload_kid"] == 1

    decoded = store.decrypt_payload(payload)
    assert decoded["schema_v"] == 1
    assert decoded["answers"]["q1"]["v"] == 7
    assert decoded["answers"]["q10"]["caffeine_mg"]["v"] == 95
    assert decoded["answers"]["q10"]["baclofen_hours"]["v"] == 2.0


def test_clamps_and_missed_status():
    ring = KeyRing.from_serialized(_keyring(marker=b"b"))
    store = CheckinStore(ring)

    scheduled = datetime(2026, 2, 1, 12, 0, 0, tzinfo=timezone.utc)

    meta, payload = store.record_checkin(
        checkin_id="late",
        scheduled_at_utc=scheduled,
        slot="spike",
        set_label="MID",
        checkin_type="spike",
        user="user123",
        tz="UTC",
        answers={},
        missed=True,
    )

    assert meta.fields["status_code"] == 3
    assert meta.fields["completion_pct"] == 0.0
    assert meta.fields["missing_count"] == 10

    decoded = store.decrypt_payload(payload)
    assert decoded["answers"]["q1"]["v"] is None

    # Now test clamping + late_partial
    late_start = scheduled + timedelta(hours=1)
    meta2, _ = store.record_checkin(
        checkin_id="clamped",
        scheduled_at_utc=scheduled,
        slot="11:30",
        set_label="SHORT",
        checkin_type="scheduled",
        user="user123",
        tz="UTC",
        answers={"q1": 99, "q3": -99, "q6": 100},
        started_at_utc=late_start,
    )
    assert meta2.fields["status_code"] == 4
    assert meta2.fields["completion_pct"] == 0.3


def test_key_rotation_decrypts_old_payload():
    old_ring = KeyRing.from_serialized(_keyring(kid=1, marker=b"c"))
    old_store = CheckinStore(old_ring)

    scheduled = datetime(2026, 3, 1, 9, 0, 0, tzinfo=timezone.utc)
    _, payload = old_store.record_checkin(
        checkin_id="rotate",
        scheduled_at_utc=scheduled,
        slot="09:00",
        set_label="SHORT",
        checkin_type="scheduled",
        user="user123",
        tz="UTC",
        answers={},
    )

    rotated_ring = KeyRing.from_serialized(
        ",".join([
            _keyring(kid=2, marker=b"d"),
            _keyring(kid=1, marker=b"c"),
        ])
    )
    rotated_store = CheckinStore(rotated_ring)
    decoded = rotated_store.decrypt_payload(payload)
    assert decoded["checkin_id"] == "rotate"


def test_export_csv_filters_date_range():
    ring = KeyRing.from_serialized(_keyring(marker=b"e"))
    store = CheckinStore(ring)

    now = datetime(2026, 4, 1, 12, 0, 0, tzinfo=timezone.utc)
    store.record_checkin(
        checkin_id="old",
        scheduled_at_utc=now - timedelta(days=10),
        slot="10:00",
        set_label="SHORT",
        checkin_type="scheduled",
        user="user123",
        tz="UTC",
        answers={},
    )
    store.record_checkin(
        checkin_id="recent",
        scheduled_at_utc=now - timedelta(hours=12),
        slot="11:30",
        set_label="SHORT",
        checkin_type="scheduled",
        user="user123",
        tz="UTC",
        answers={"q1": 5},
    )

    csv = store.export_csv(days=7, now=now)
    lines = [line for line in csv.splitlines() if line]
    assert len(lines) == 2  # header + recent row
    headers = lines[0].split(",")
    values = lines[1].split(",")
    row = dict(zip(headers, values))
    assert row["checkin_id"] == "recent"
