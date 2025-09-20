import datetime as dt
import sqlite3

from zoneinfo import ZoneInfo

from couples_bot.alerts import pings
from couples_bot.models import AlertKind


def build_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    with open("couples_bot/schema.sql", "r", encoding="utf-8") as fh:
        conn.executescript(fh.read())
    conn.execute(
        "INSERT INTO couples (id, user_a_id, user_b_id, group_chat_id, tz) VALUES (1, 100, 200, 10, 'UTC')"
    )
    conn.commit()
    return conn


def test_maybe_ping_respects_cooldown_and_caps():
    conn = build_conn()
    sent = []
    now = dt.datetime(2024, 1, 1, 12, 0, 0, tzinfo=ZoneInfo("UTC"))

    allowed = pings.maybe_ping(
        conn,
        couple_id=1,
        user_id=100,
        metric_key="harsh_start",
        kind=AlertKind.RISK,
        text="Tone spiked—reset with a softer lead",
        send_func=sent.append,
        now=now,
        tz="UTC",
    )
    assert allowed
    assert sent

    blocked = pings.maybe_ping(
        conn,
        couple_id=1,
        user_id=100,
        metric_key="harsh_start",
        kind=AlertKind.RISK,
        text="duplicate",
        send_func=sent.append,
        now=now + dt.timedelta(minutes=5),
        tz="UTC",
    )
    assert not blocked
    assert len(sent) == 1

    allowed_again = pings.maybe_ping(
        conn,
        couple_id=1,
        user_id=100,
        metric_key="harsh_start",
        kind=AlertKind.RISK,
        text="second",
        send_func=sent.append,
        now=now + dt.timedelta(minutes=11),
        tz="UTC",
    )
    assert allowed_again
    assert len(sent) == 2

    conn.execute(
        "UPDATE prefs SET dnd_start='22:00', dnd_end='07:00', max_neg_per_day=2 WHERE couple_id=1 AND user_id=100"
    )
    conn.commit()

    blocked_dnd = pings.maybe_ping(
        conn,
        couple_id=1,
        user_id=100,
        metric_key="harsh_start",
        kind=AlertKind.RISK,
        text="late",
        send_func=sent.append,
        now=dt.datetime(2024, 1, 1, 23, 0, 0, tzinfo=ZoneInfo("UTC")),
        tz="UTC",
    )
    assert not blocked_dnd
    assert len(sent) == 2

    # exceed daily cap after DND ends next day
    allowed_next_day = pings.maybe_ping(
        conn,
        couple_id=1,
        user_id=100,
        metric_key="harsh_start",
        kind=AlertKind.RISK,
        text="third",
        send_func=sent.append,
        now=dt.datetime(2024, 1, 2, 9, 0, 0, tzinfo=ZoneInfo("UTC")),
        tz="UTC",
    )
    assert allowed_next_day
    assert len(sent) == 3

    allowed_to_limit = pings.maybe_ping(
        conn,
        couple_id=1,
        user_id=100,
        metric_key="harsh_start",
        kind=AlertKind.RISK,
        text="fourth",
        send_func=sent.append,
        now=dt.datetime(2024, 1, 2, 10, 0, 0, tzinfo=ZoneInfo("UTC")),
        tz="UTC",
    )
    assert allowed_to_limit
    assert len(sent) == 4

    blocked_cap = pings.maybe_ping(
        conn,
        couple_id=1,
        user_id=100,
        metric_key="harsh_start",
        kind=AlertKind.RISK,
        text="fifth",
        send_func=sent.append,
        now=dt.datetime(2024, 1, 2, 12, 0, 0, tzinfo=ZoneInfo("UTC")),
        tz="UTC",
    )
    assert not blocked_cap
    assert len(sent) == 4
