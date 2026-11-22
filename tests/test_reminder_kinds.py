"""Migration 0009 and the repository's new reminder kinds and cap of 8 (#164).

Fixture/mock: the real migrations on in-memory SQLite, and the send gate's tick.
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime

import pytest

from next_is_you.alerts import REMINDER_CAP, REMINDER_KINDS
from next_is_you.persistence import CloudflareD1Store, VisitRepository
from next_is_you.scheduler import OutboxScheduler
from test_scheduler_outbox import (
    MIGRATIONS,
    ROOT,
    LocalD1,
    RecordingLine,
    make_gate,
    seed,
    tick,
)

NOW = datetime.fromisoformat("2026-09-27T13:00:00+00:00")
KINDS = (*REMINDER_KINDS, "unavailable")
REBUILD = next(m for m in MIGRATIONS if m.name.startswith("0009_"))


async def visit_for(*recipients: str) -> tuple[LocalD1, object, VisitRepository]:
    database = LocalD1()
    gate = make_gate(database)
    await seed(gate)
    for recipient in recipients:
        database.connection.execute(
            "INSERT INTO recipients (id, line_subject, display_name, consented_at, "
            "friendship_checked_at, active, created_at) VALUES (?, ?, 'x', "
            "'2026-09-27T00:00:00Z', '2026-09-27T00:00:00Z', 1, '2026-09-27T00:00:00Z')",
            (recipient, f"line-{recipient}"),
        )
        database.connection.execute(
            "INSERT INTO visit_recipients VALUES ('v1', ?, '2026-09-27T00:00:00Z')",
            (recipient,),
        )
    return database, gate, VisitRepository(CloudflareD1Store(database))


async def create(repository, kind, recipient="r1", *, skipped=False, event_id=None):
    return await repository.create_reminder(
        event_id=event_id or str(uuid.uuid4()),
        visit_id="v1",
        recipient_id=recipient,
        event_kind=kind,
        retry_key=str(uuid.uuid4()),
        payload_json='{"text":"synthetic"}',
        now=NOW,
        skipped=skipped,
    )


def outcomes(database, recipient="r1") -> dict[str, str]:
    return dict(
        tuple(row)
        for row in database.connection.execute(
            "SELECT event_kind, outcome FROM outbound_events WHERE recipient_id = ?",
            (recipient,),
        )
    )


def raw_insert(database, kind, outcome="pending", recipient="r1"):
    database.connection.execute(
        "INSERT INTO outbound_events (id, visit_id, recipient_id, event_kind, "
        "retry_key, payload_json, outcome, created_at) "
        "VALUES (?, 'v1', ?, ?, ?, '{}', ?, '2026-09-27T00:00:00Z')",
        (str(uuid.uuid4()), recipient, kind, str(uuid.uuid4()), outcome),
    )


@pytest.mark.asyncio
async def test_the_ninth_reminder_is_refused_for_that_recipient_only():
    database, _, repository = await visit_for("r2")
    assert len(KINDS) == REMINDER_CAP + 1
    for kind in KINDS[:-1]:
        assert await create(repository, kind) == "created"
    assert await create(repository, KINDS[-1]) == "cap_reached"
    assert await create(repository, KINDS[-1], "r2") == "created"
    assert set(outcomes(database)) == set(KINDS[:-1])


@pytest.mark.asyncio
async def test_a_second_reminder_of_one_kind_is_refused():
    database, _, repository = await visit_for()
    for kind in KINDS:
        if kind == KINDS[-1]:
            database.connection.execute(
                "DELETE FROM outbound_events WHERE event_kind = ?", (KINDS[0],)
            )
        assert await create(repository, kind) == "created"
        # At the cap too, a repeat is a repeat and not a blocked send.
        assert await create(repository, kind) == "exists"
    for kind in KINDS[1:]:
        with pytest.raises(sqlite3.IntegrityError):
            raw_insert(database, kind, "skipped" if kind != "unavailable" else "failed")


@pytest.mark.asyncio
async def test_skipped_reminders_hold_their_kind_and_never_count_or_send():
    database, gate, repository = await visit_for()
    for kind in KINDS[:3]:
        assert await create(repository, kind, skipped=True) == "created"
        assert await create(repository, kind) == "exists"
    for kind in KINDS[3:]:
        assert await create(repository, kind) == "created"
    assert len(KINDS) == 9 and len(outcomes(database)) == 9
    sendable = {row["event_kind"] for row in await repository.retryable_events("v1")}
    assert sendable == set(KINDS[3:])
    (visit,) = [v for v in await repository.organizer_visits() if v["id"] == "v1"]
    # The organizer's count of reminders does not include the skipped ones.
    assert visit["notification_count"] == len(KINDS[3:])


@pytest.mark.asyncio
async def test_a_skipped_reminder_stays_skipped_and_no_other_outcome_becomes_it():
    database, _, repository = await visit_for()
    await create(repository, "checked_in", skipped=True)
    await create(repository, "passed")
    for kind, outcome in (("checked_in", "pending"), ("passed", "skipped")):
        with pytest.raises(sqlite3.IntegrityError):
            database.connection.execute(
                "UPDATE outbound_events SET outcome = ? WHERE event_kind = ?",
                (outcome, kind),
            )
    for kind in ("near", "unavailable"):
        with pytest.raises(sqlite3.IntegrityError):
            raw_insert(database, kind, "skipped")


@pytest.mark.asyncio
async def test_the_schema_refuses_the_ninth_and_an_unknown_kind():
    database, _, repository = await visit_for()
    for kind in KINDS[:-1]:
        raw_insert(database, kind)
    with pytest.raises(sqlite3.IntegrityError, match="cap of 8"):
        raw_insert(database, KINDS[-1])
    database, _, repository = await visit_for()
    with pytest.raises(sqlite3.IntegrityError):
        await create(repository, "not_a_kind")


@pytest.mark.asyncio
async def test_near_reminders_and_the_new_kinds_have_separate_caps():
    database, _, repository = await visit_for()
    for _ in range(20):
        raw_insert(database, "near")
    with pytest.raises(sqlite3.IntegrityError, match="cap of 20"):
        raw_insert(database, "near")
    for kind in KINDS[:REMINDER_CAP]:
        assert await create(repository, kind) == "created"


@pytest.mark.asyncio
async def test_a_retry_under_the_same_key_never_counts_again():
    database, _, repository = await visit_for()
    event_id = str(uuid.uuid4())
    for kind in KINDS[:6]:
        await create(repository, kind)
    await create(repository, KINDS[6], event_id=event_id)
    line = RecordingLine("unknown")
    scheduler = OutboxScheduler(repository, None, line, lambda: NOW)

    async def nothing(_event_id: str) -> None:
        return None

    for _ in range(4):
        await scheduler.send_event(event_id, before_request=nothing)
    assert len(line.requests) == 4
    assert len({retry_key for _, _, retry_key in line.requests}) == 1
    # One place left, taken by a new reminder; then the cap.
    assert await create(repository, KINDS[7]) == "created"
    assert await create(repository, KINDS[8]) == "cap_reached"


@pytest.mark.asyncio
async def test_a_removed_recipient_gets_no_reminder():
    database, _, repository = await visit_for()
    database.connection.execute("UPDATE recipients SET active = 0 WHERE id = 'r1'")
    assert await create(repository, "passed") == "not_eligible"


@pytest.mark.asyncio
async def test_a_capped_unavailable_message_does_not_fail_the_tick_for_others():
    database, gate, repository = await visit_for("r2")
    for kind in REMINDER_KINDS:
        assert await create(repository, kind) == "created"
    database.connection.execute("UPDATE outbound_events SET outcome = 'accepted'")
    await gate._save_ledger()
    await gate.set_test_observation(None, False)
    results = [await tick(gate, f"2026-09-27T13:0{minute}:00Z") for minute in range(3)]
    assert set(outcomes(database, "r2")) == {"unavailable"}
    assert "unavailable" not in outcomes(database)
    assert [result["events_created"] for result in results] == [0, 0, 1]
    assert [result["requests_started"] for result in results] == [0, 0, 1]


@pytest.mark.asyncio
async def test_the_tick_plan_names_the_recipient_the_cap_blocked():
    database, gate, repository = await visit_for("r2")
    for kind in REMINDER_KINDS:
        await create(repository, kind)
    await gate.set_test_observation(None, False)
    scheduler = OutboxScheduler(
        repository, gate._hospital_reader(), RecordingLine("accepted"), lambda: NOW
    )
    plans = [await scheduler.prepare_tick(NOW) for _ in range(3)]
    assert [plan.cap_reached for plan in plans] == [(), (), (("v1", "r1"),)]


def test_the_rehearsal_seed_survives_the_rebuild_and_every_row_is_unchanged():
    connection = sqlite3.connect(":memory:")
    connection.execute("PRAGMA foreign_keys = ON")
    for migration in MIGRATIONS:
        if migration.name < "0009_":
            connection.executescript(migration.read_text(encoding="utf-8"))
    seed_file = ROOT / "scripts" / "migration-rehearsal" / "0009_seed.sql"
    connection.executescript(seed_file.read_text(encoding="utf-8"))

    def rows():
        return {
            table: connection.execute(f"SELECT * FROM {table} ORDER BY 1, 2").fetchall()
            for table in ("recipients", "visits", "visit_recipients", "outbound_events")
        }

    shapes = set(connection.execute("SELECT event_kind, outcome FROM outbound_events"))
    assert shapes == {
        (kind, outcome)
        for kind in ("near", "unavailable")
        for outcome in (
            "pending",
            "in_flight",
            "accepted",
            "failed",
            "unknown",
            "superseded",
        )
    }
    before = rows()
    connection.executescript(REBUILD.read_text(encoding="utf-8"))
    assert rows() == before
    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    # Withdrawing a recipient still takes their events with them.
    connection.execute("DELETE FROM recipients")
    assert connection.execute("SELECT COUNT(*) FROM outbound_events").fetchone() == (0,)
