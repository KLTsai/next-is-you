from __future__ import annotations

import asyncio
import json
import sqlite3
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Sequence

import pytest

from next_is_you.line_messaging import LinePushResult
from next_is_you.persistence import CloudflareD1Store, Statement, VisitRepository
from next_is_you.scheduler import OutboxScheduler
from next_is_you.send_gate import SystemSendGate


ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = sorted((ROOT / "migrations").glob("*.sql"))


class Prepared:
    def __init__(self, database: "LocalD1", sql: str, values: tuple[Any, ...] = ()):
        self.database = database
        self.sql = sql
        self.values = values

    def bind(self, *values: Any) -> "Prepared":
        return Prepared(self.database, self.sql, values)

    async def run(self) -> dict[str, Any]:
        cursor = self.database.connection.execute(self.sql, self.values)
        return {"meta": {"changes": cursor.rowcount}}

    async def all(self) -> dict[str, Any]:
        cursor = self.database.connection.execute(self.sql, self.values)
        return {"results": [dict(row) for row in cursor.fetchall()]}


class LocalD1:
    def __init__(self) -> None:
        self.connection = sqlite3.connect(":memory:", isolation_level=None)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        for migration in MIGRATIONS:
            self.connection.executescript(migration.read_text(encoding="utf-8"))

    def prepare(self, sql: str) -> Prepared:
        return Prepared(self, sql)

    async def batch(self, statements: Sequence[Prepared]) -> list[dict[str, Any]]:
        self.connection.execute("BEGIN")
        try:
            results = [
                self.connection.execute(item.sql, item.values).rowcount
                for item in statements
            ]
        except Exception:
            self.connection.execute("ROLLBACK")
            raise
        self.connection.execute("COMMIT")
        return [{"meta": {"changes": changes}} for changes in results]


class LocalDurableStorage:
    def __init__(self, state: dict[str, Any] | None = None) -> None:
        self.values = state if state is not None else {}

    async def get(self, key: str) -> Any:
        return self.values.get(key)

    async def put(self, key: str, value: Any) -> None:
        self.values[key] = value


class LocalContext:
    def __init__(self, storage: LocalDurableStorage) -> None:
        self.storage = storage


def make_gate(
    database: LocalD1,
    storage: LocalDurableStorage | None = None,
) -> SystemSendGate:
    ctx = LocalContext(storage or LocalDurableStorage())
    env = {
        "DB": database,
        "NIY006_LOCAL_TEST_MODE": "1",
        "NIY_ENVIRONMENT": "local-test",
    }
    return SystemSendGate(ctx, env)


async def seed(
    gate: SystemSendGate,
    *,
    visit_id: str = "v1",
    recipient_id: str = "r1",
    visit_day: str = "2026-09-27",
    patient_number: int = 85,
    now: str = "2026-09-27T13:00:00Z",
) -> None:
    assert await gate.seed_test_visit(
        visit_id, recipient_id, visit_day, patient_number, now
    )


def event(database: LocalD1, visit_id: str = "v1") -> dict[str, Any]:
    row = database.connection.execute(
        "SELECT * FROM outbound_events WHERE visit_id = ?", (visit_id,)
    ).fetchone()
    assert row is not None
    return dict(row)


async def tick(gate: SystemSendGate, when: str = "2026-09-27T13:00:00Z"):
    return await gate.scheduled_tick(when)


def near_rows(database: LocalD1, visit_id: str = "v1") -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in database.connection.execute(
            """SELECT * FROM outbound_events
            WHERE visit_id = ? AND event_kind = 'near'
            ORDER BY created_at, id""",
            (visit_id,),
        ).fetchall()
    ]


def near_count(database: LocalD1, visit_id: str = "v1") -> int:
    return database.connection.execute(
        "SELECT COUNT(*) FROM outbound_events WHERE visit_id = ? AND event_kind = 'near'",
        (visit_id,),
    ).fetchone()[0]


def prev_observed(database: LocalD1, visit_id: str = "v1") -> int | None:
    value = database.connection.execute(
        "SELECT near_prev_observed_number FROM visits WHERE id = ?", (visit_id,)
    ).fetchone()[0]
    return None if value is None else int(value)


async def observe_tick(gate: SystemSendGate, current: int, when: str) -> dict[str, Any]:
    await gate.set_test_observation(current)
    return await tick(gate, when)


@pytest.mark.asyncio
async def test_duplicate_ticks_reading_the_same_number_create_one_near_event() -> None:
    database = LocalD1()
    gate = make_gate(database)
    await seed(gate)
    await gate.set_test_observation(82)

    first = await tick(gate)
    second = await tick(gate, "2026-09-27T13:01:00Z")
    assert first["events_created"] == 1
    assert second["events_created"] == 0
    assert near_count(database) == 1
    assert prev_observed(database) == 82
    assert len((await gate.test_snapshot())["line_requests"]) == 1


@pytest.mark.asyncio
async def test_near_window_sequences_each_create_their_own_reminder() -> None:
    database = LocalD1()
    gate = make_gate(database)
    await seed(gate, patient_number=85)

    # Before the window: an in-range but earlier read, then entering the window.
    assert (await observe_tick(gate, 51, "2026-09-27T13:00:00Z"))["events_created"] == 0
    assert (await observe_tick(gate, 82, "2026-09-27T13:01:00Z"))["events_created"] == 1
    # Moving forward inside the window: 82 -> 83 -> 84 give three reminders total.
    assert (await observe_tick(gate, 83, "2026-09-27T13:02:00Z"))["events_created"] == 1
    assert (await observe_tick(gate, 84, "2026-09-27T13:03:00Z"))["events_created"] == 1
    # Leaving the window and re-entering at the same number sends again.
    assert (await observe_tick(gate, 7, "2026-09-27T13:04:00Z"))["events_created"] == 0
    assert (await observe_tick(gate, 84, "2026-09-27T13:05:00Z"))["events_created"] == 1
    # Moving backward inside the window sends again.
    assert (await observe_tick(gate, 83, "2026-09-27T13:06:00Z"))["events_created"] == 1
    # The target number and numbers past it never send.
    assert (await observe_tick(gate, 85, "2026-09-27T13:07:00Z"))["events_created"] == 0
    assert (await observe_tick(gate, 86, "2026-09-27T13:08:00Z"))["events_created"] == 0

    assert near_count(database) == 5
    assert prev_observed(database) == 86


@pytest.mark.asyncio
async def test_skipped_number_still_counts_as_a_move() -> None:
    database = LocalD1()
    gate = make_gate(database)
    await seed(gate, patient_number=55)

    assert (await observe_tick(gate, 51, "2026-09-27T13:00:00Z"))["events_created"] == 0
    # 51 -> 54 skips 52 and 53 but still enters the window and sends once.
    assert (await observe_tick(gate, 54, "2026-09-27T13:01:00Z"))["events_created"] == 1
    assert near_count(database) == 1


@pytest.mark.asyncio
async def test_corrected_watch_repeats_in_the_new_window() -> None:
    database = LocalD1()
    gate = make_gate(database)
    await seed(gate)
    await gate.set_test_observation(82)

    assert (await tick(gate))["events_created"] == 1
    assert near_count(database) == 1

    assert await gate.correct_test_watch("v1", "2026-09-27", 86, "2026-09-27T13:02:00Z")
    # Patient number is now 86, so the window is 83..85 and 83 is a fresh move.
    assert (await observe_tick(gate, 83, "2026-09-27T13:03:00Z"))["events_created"] == 1
    snapshot = await gate.test_snapshot()
    assert near_count(database) == 2
    assert [event["event_kind"] for event in snapshot["events"]] == ["near", "near"]


@pytest.mark.asyncio
async def test_ui_start_observation_does_not_count_as_a_previous_scheduled_read() -> (
    None
):
    database = LocalD1()
    gate = make_gate(database)
    # seed_test_visit starts the visit; make its observation an in-window number.
    await gate.set_test_observation(83)
    await seed(gate, patient_number=85)
    assert prev_observed(database) is None

    # The first scheduled read repeats that same in-window number and must send,
    # because the Start observation is not a previous scheduled read.
    assert (await observe_tick(gate, 83, "2026-09-27T13:01:00Z"))["events_created"] == 1
    assert prev_observed(database) == 83


@pytest.mark.asyncio
async def test_unusable_reads_do_not_change_the_previous_observed_number() -> None:
    database = LocalD1()
    gate = make_gate(database)
    await seed(gate, patient_number=85)

    assert (await observe_tick(gate, 83, "2026-09-27T13:00:00Z"))["events_created"] == 1
    assert prev_observed(database) == 83

    # An outage: unusable reads neither create a near reminder nor move the
    # previously observed number (the third read raises the separate unavailable
    # warning, which is unchanged by this issue).
    await gate.set_test_observation(None, trustworthy=False)
    for minute in range(1, 4):
        await tick(gate, f"2026-09-27T13:0{minute}:00Z")
    assert prev_observed(database) == 83
    assert near_count(database) == 1

    # The same number read again after the outage creates no reminder.
    assert (await observe_tick(gate, 83, "2026-09-27T13:05:00Z"))["events_created"] == 0
    assert near_count(database) == 1


@pytest.mark.asyncio
async def test_twenty_near_cap_is_enforced_and_survives_restart() -> None:
    database = LocalD1()
    gate = make_gate(database)
    await seed(gate, patient_number=1000)

    # Alternate inside the window so each read is a fresh move. The window for
    # patient 1000 is 997, 998, 999.
    created = 0
    for index in range(30):
        current = 998 if index % 2 == 0 else 999
        minute = f"2026-09-27T{13 + index // 60:02d}:{index % 60:02d}:00Z"
        created += (await observe_tick(gate, current, minute))["events_created"]
    assert created == 20
    assert near_count(database) == 20

    # The cap is stored, not just enforced by application code: a raw 21st insert
    # is rejected by the database.
    with pytest.raises(sqlite3.IntegrityError):
        database.connection.execute(
            """INSERT INTO outbound_events (
                id, visit_id, recipient_id, event_kind, retry_key, payload_json,
                outcome, created_at
            ) VALUES ('overflow', 'v1', 'r1', 'near', 'overflow-key', '{}', 'pending',
                '2026-09-27T14:00:00Z')"""
        )

    # The previously observed number keeps updating past the cap.
    before = prev_observed(database)
    other = 997 if before != 997 else 998
    assert (await observe_tick(gate, other, "2026-09-27T15:00:00Z"))[
        "events_created"
    ] == 0
    assert near_count(database) == 20
    assert prev_observed(database) == other


@pytest.mark.asyncio
async def test_each_recipient_is_capped_independently() -> None:
    database = LocalD1()
    gate = make_gate(database)
    await seed(gate, patient_number=85)
    timestamp = "2026-09-27T13:00:00Z"
    database.connection.execute(
        """INSERT INTO recipients (
            id, line_subject, display_name, consented_at,
            friendship_checked_at, active, created_at
        ) VALUES ('r2', 'U00000000000000000000000000000002', 'Family 2', ?, ?, 1, ?)""",
        (timestamp, timestamp, timestamp),
    )
    database.connection.execute(
        "INSERT INTO visit_recipients (visit_id, recipient_id, selected_at) VALUES ('v1', 'r2', ?)",
        (timestamp,),
    )
    # r1 is already at the cap; r2 has room.
    for index in range(20):
        database.connection.execute(
            """INSERT INTO outbound_events (
                id, visit_id, recipient_id, event_kind, retry_key, payload_json,
                outcome, created_at
            ) VALUES (?, 'v1', 'r1', 'near', ?, '{}', 'accepted', '2026-09-27T12:00:00Z')""",
            (f"r1-near-{index}", f"r1-key-{index}"),
        )
    # Re-align the gate's stored ledger digest with the out-of-band seed rows.
    await gate._save_ledger()

    assert (await observe_tick(gate, 83, "2026-09-27T13:01:00Z"))["events_created"] == 1
    assert near_count_for(database, "r1") == 20
    assert near_count_for(database, "r2") == 1


@pytest.mark.asyncio
async def test_newer_near_supersedes_an_unsent_earlier_one_but_not_an_accepted_one() -> (
    None
):
    database = LocalD1()
    gate = make_gate(database)
    await seed(gate, patient_number=85)
    await gate.set_test_line_mode("unknown")

    # First reminder is attempted but its LINE outcome is unknown (unsent).
    assert (await observe_tick(gate, 82, "2026-09-27T13:00:00Z"))["events_created"] == 1
    first = near_rows(database)[0]
    assert first["outcome"] == "unknown"

    # A fresh move supersedes the unsent reminder and leaves only the newest
    # pending for delivery, while the superseded row still counts toward the cap.
    await gate.set_test_line_mode("accepted")
    assert (await observe_tick(gate, 83, "2026-09-27T13:01:00Z"))["events_created"] == 1
    rows = {row["id"]: row for row in near_rows(database)}
    assert rows[first["id"]]["outcome"] == "superseded"
    accepted = [row for row in rows.values() if row["outcome"] == "accepted"]
    assert len(accepted) == 1
    assert near_count(database) == 2
    # Each reminder keeps its own event id and retry key.
    assert accepted[0]["id"] != first["id"]
    assert accepted[0]["retry_key"] != first["retry_key"]

    # An accepted reminder is never retracted by a later move.
    assert (await observe_tick(gate, 84, "2026-09-27T13:02:00Z"))["events_created"] == 1
    rows = {row["id"]: row for row in near_rows(database)}
    assert rows[accepted[0]["id"]]["outcome"] == "accepted"


@pytest.mark.asyncio
async def test_recovery_digest_detects_previous_observed_number_difference() -> None:
    database = LocalD1()
    gate = make_gate(database)
    await seed(gate, patient_number=85)
    await observe_tick(gate, 83, "2026-09-27T13:00:00Z")

    repository = VisitRepository(CloudflareD1Store(database))
    baseline = await repository.scheduler_ledger_digest()
    database.connection.execute(
        "UPDATE visits SET near_prev_observed_number = 70 WHERE id = 'v1'"
    )
    assert await repository.scheduler_ledger_digest() != baseline


def near_count_for(database: LocalD1, recipient_id: str, visit_id: str = "v1") -> int:
    return database.connection.execute(
        """SELECT COUNT(*) FROM outbound_events
        WHERE visit_id = ? AND recipient_id = ? AND event_kind = 'near'""",
        (visit_id, recipient_id),
    ).fetchone()[0]


@pytest.mark.asyncio
async def test_unavailable_alert_is_created_once_on_third_bad_read() -> None:
    database = LocalD1()
    gate = make_gate(database)
    await seed(gate)
    await gate.set_test_observation(None, trustworthy=False)

    for minute in range(2):
        result = await tick(gate, f"2026-09-27T13:0{minute}:00Z")
        assert result["events_created"] == 0
    third = await tick(gate, "2026-09-27T13:02:00Z")
    fourth = await tick(gate, "2026-09-27T13:03:00Z")

    assert third["events_created"] == 1
    assert fourth["events_created"] == 0
    assert tuple(
        database.connection.execute(
            "SELECT event_kind, outcome FROM outbound_events WHERE visit_id = 'v1'"
        ).fetchone()
    ) == ("unavailable", "accepted")
    assert len((await gate.test_snapshot())["line_requests"]) == 1


@pytest.mark.asyncio
async def test_unknown_retries_reuse_exact_key_and_stop_after_twenty_four_hours() -> (
    None
):
    database = LocalD1()
    gate = make_gate(database)
    await seed(
        gate,
        visit_day="2026-09-30",
        now="2026-09-28T12:00:00Z",
    )
    await gate.set_test_observation(82)
    await gate.set_test_line_mode("unknown")

    await tick(gate, "2026-09-28T12:00:00Z")
    await tick(gate, "2026-09-28T12:01:00Z")
    await tick(gate, "2026-09-29T12:00:00Z")

    snapshot = await gate.test_snapshot()
    assert snapshot["events"][0]["outcome"] == "unknown"
    assert snapshot["events"][0]["attempt_count"] == 2
    assert len(snapshot["line_requests"]) == 2
    assert (
        snapshot["line_requests"][0]["retry_key"]
        == snapshot["line_requests"][1]["retry_key"]
    )
    assert snapshot["line_requests"][0]["body"] == snapshot["line_requests"][1]["body"]
    assert all(request["outbox_persisted"] for request in snapshot["line_requests"])


@pytest.mark.asyncio
async def test_restarted_invocation_recovers_inflight_and_reuses_retry_key() -> None:
    database = LocalD1()
    gate = make_gate(database)
    await seed(gate)
    await gate.set_test_observation(82)
    await gate.set_test_line_mode("crash_once")

    with pytest.raises(asyncio.CancelledError):
        await tick(gate)
    before_restart = event(database)
    assert before_restart["outcome"] == "in_flight"

    result = await tick(gate, "2026-09-27T13:01:00Z")
    after_restart = event(database)
    history = (await gate.test_snapshot())["line_requests"]
    assert result["accepted"] == 1
    assert after_restart["outcome"] == "accepted"
    assert after_restart["attempt_count"] == 2
    assert [request["retry_key"] for request in history] == [
        before_restart["retry_key"],
        before_restart["retry_key"],
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("when", "expected_requests", "expected_state"),
    [
        ("2026-09-27T15:58:59Z", 1, "active"),
        ("2026-09-27T15:59:00Z", 0, "expired"),
        ("2026-09-27T15:59:01Z", 0, "expired"),
    ],
)
async def test_taipei_cutoff_blocks_new_request_at_and_after_boundary(
    when: str, expected_requests: int, expected_state: str
) -> None:
    database = LocalD1()
    gate = make_gate(database)
    await seed(gate, now="2026-09-27T13:00:00Z")
    await gate.set_test_observation(82)

    await tick(gate, when)

    snapshot = await gate.test_snapshot()
    assert len(snapshot["line_requests"]) == expected_requests
    assert (
        database.connection.execute(
            "SELECT state FROM visits WHERE id = 'v1'"
        ).fetchone()[0]
        == expected_state
    )


@pytest.mark.asyncio
async def test_stop_transitions_to_stopping_during_active_request_and_blocks_later_sends() -> (
    None
):
    database = LocalD1()
    gate = make_gate(database)
    await seed(gate)
    await gate.set_test_observation(82)
    await gate.set_test_line_mode("wait")

    sending = asyncio.create_task(tick(gate))
    await gate.wait_test_request_started()
    stopping = asyncio.create_task(gate.stop_visit("v1", "2026-09-27T13:01:00Z"))
    await asyncio.sleep(0)
    assert await asyncio.wait_for(stopping, timeout=1) == "stopping"
    duplicate_stop = asyncio.create_task(gate.stop_visit("v1", "2026-09-27T13:01:01Z"))
    await asyncio.sleep(0)
    assert await asyncio.wait_for(duplicate_stop, timeout=1) == "stopping"
    assert (
        database.connection.execute(
            "SELECT state FROM visits WHERE id = 'v1'"
        ).fetchone()[0]
        == "stopping"
    )
    await gate.release_test_request()

    result = await sending
    assert result["held"] is False
    assert (
        database.connection.execute(
            "SELECT state FROM visits WHERE id = 'v1'"
        ).fetchone()[0]
        == "stopped"
    )
    assert (await tick(gate, "2026-09-27T13:02:00Z"))["held"] is False
    assert len((await gate.test_snapshot())["line_requests"]) == 1


@pytest.mark.asyncio
async def test_withdrawal_waits_for_active_request_then_erases_identity_and_events() -> (
    None
):
    database = LocalD1()
    gate = make_gate(database)
    await seed(gate)
    await gate.set_test_observation(82)
    await gate.set_test_line_mode("wait")

    sending = asyncio.create_task(tick(gate))
    await gate.wait_test_request_started()
    withdrawing = asyncio.create_task(
        gate.withdraw_recipient("r1", "2026-09-27T13:01:00Z")
    )
    await asyncio.sleep(0)
    assert not withdrawing.done()
    await gate.release_test_request()

    await sending
    assert await withdrawing
    assert (
        database.connection.execute("SELECT COUNT(*) FROM recipients").fetchone()[0]
        == 0
    )
    assert (
        database.connection.execute("SELECT COUNT(*) FROM outbound_events").fetchone()[
            0
        ]
        == 0
    )
    await tick(gate, "2026-09-27T13:02:00Z")
    assert len((await gate.test_snapshot())["line_requests"]) == 1


@pytest.mark.asyncio
async def test_visit_recipient_removal_cannot_remove_the_last_recipient() -> None:
    database = LocalD1()
    gate = make_gate(database)
    await seed(gate)
    await gate.set_test_observation(82)
    await gate.set_test_line_mode("wait")

    sending = asyncio.create_task(tick(gate))
    await gate.wait_test_request_started()
    removing = asyncio.create_task(
        gate.remove_visit_recipient("v1", "r1", "2026-09-27T13:01:00Z")
    )
    await asyncio.sleep(0)
    assert not removing.done()
    await gate.release_test_request()

    await sending
    assert not await removing
    assert (
        database.connection.execute("SELECT COUNT(*) FROM outbound_events").fetchone()[
            0
        ]
        == 1
    )
    assert await VisitRepository(CloudflareD1Store(database)).selected_recipient_ids(
        "v1"
    ) == {"r1"}
    await tick(gate, "2026-09-27T13:02:00Z")
    assert len((await gate.test_snapshot())["line_requests"]) == 1


@pytest.mark.asyncio
async def test_removing_a_recipient_keeps_another_selected_recipient() -> None:
    database = LocalD1()
    gate = make_gate(database)
    await seed(gate)
    timestamp = "2026-09-27T13:00:00Z"
    database.connection.execute(
        """INSERT INTO recipients (
            id, line_subject, display_name, consented_at,
            friendship_checked_at, active, created_at
        ) VALUES ('r2', 'U00000000000000000000000000000002', 'Family 2', ?, ?, 1, ?)""",
        (timestamp, timestamp, timestamp),
    )
    database.connection.execute(
        "INSERT INTO visit_recipients (visit_id, recipient_id, selected_at) VALUES ('v1', 'r2', ?)",
        (timestamp,),
    )

    repository = VisitRepository(CloudflareD1Store(database))
    assert await repository.remove_recipient("v1", "r1")
    assert await repository.selected_recipient_ids("v1") == {"r2"}


@pytest.mark.asyncio
async def test_visit_recipient_removal_cannot_block_the_only_recipient() -> None:
    database = LocalD1()
    gate = make_gate(database)
    await seed(gate)
    await gate.set_test_observation(82)

    removing = asyncio.create_task(
        gate.remove_visit_recipient("v1", "r1", "2026-09-27T13:00:00Z")
    )
    sending = asyncio.create_task(tick(gate, "2026-09-27T13:01:00Z"))

    assert not await removing
    await sending

    snapshot = await gate.test_snapshot()
    assert len(snapshot["line_requests"]) == 1
    assert len(snapshot["events"]) == 1
    assert await VisitRepository(CloudflareD1Store(database)).selected_recipient_ids(
        "v1"
    ) == {"r1"}


@pytest.mark.asyncio
async def test_removal_waits_for_draft_update_and_wins_roster_ordering() -> None:
    database = LocalD1()
    gate = make_gate(database)
    repository = gate._repository()
    timestamp = datetime.fromisoformat("2026-09-27T13:00:00+00:00")
    await repository.create_draft(
        visit_id="draft-v1",
        hospital="ntuh-main",
        visit_day=datetime.fromisoformat("2026-09-27").date(),
        department_code="MED",
        clinic_code="MED-A",
        clinic_session="morning",
        patient_number=85,
        now=timestamp,
    )
    await repository._store.execute(
        Statement(
            """INSERT INTO recipients (id, line_subject, display_name, consented_at,
            friendship_checked_at, active, created_at) VALUES
            ('r1', 'line-r1', 'Family A', ?, ?, 1, ?)""",
            (timestamp.isoformat(), timestamp.isoformat(), timestamp.isoformat()),
        )
    )
    assert await repository.add_recipient("draft-v1", "r1", timestamp)
    await repository._store.execute(
        Statement(
            """INSERT INTO recipients (id, line_subject, display_name, consented_at,
            friendship_checked_at, active, created_at) VALUES
            ('r2', 'line-r2', 'Family B', ?, ?, 1, ?)""",
            (timestamp.isoformat(), timestamp.isoformat(), timestamp.isoformat()),
        )
    )
    assert await repository.add_recipient("draft-v1", "r2", timestamp)
    gate._repository = lambda: repository
    eligible_read = asyncio.Event()
    continue_update = asyncio.Event()
    original_fetch = repository._store.fetch_all

    async def pause_after_eligibility(statement: Statement):
        rows = await original_fetch(statement)
        if statement.operation == "validate_draft_recipients":
            eligible_read.set()
            await continue_update.wait()
        return rows

    repository._store.fetch_all = pause_after_eligibility
    updating = asyncio.create_task(
        gate.update_draft(
            "draft-v1",
            hospital="ntuh-main",
            visit_day=datetime.fromisoformat("2026-09-27").date(),
            department_code="MED",
            clinic_code="MED-A",
            clinic_session="morning",
            patient_number=86,
            recipient_ids=("r1", "r2"),
            now=timestamp,
        )
    )
    await eligible_read.wait()
    removing = asyncio.create_task(
        gate.remove_visit_recipient("draft-v1", "r1", timestamp.isoformat())
    )
    await asyncio.sleep(0)
    assert not removing.done()
    continue_update.set()

    assert await updating
    assert await removing
    assert await repository.selected_recipient_ids("draft-v1") == {"r2"}


@pytest.mark.asyncio
async def test_close_wins_ordering_and_no_request_begins_after_close() -> None:
    database = LocalD1()
    gate = make_gate(database)
    await seed(gate)
    await gate.set_test_observation(82)

    assert await gate.stop_visit("v1", "2026-09-27T13:00:00Z") == "stopped"
    await tick(gate, "2026-09-27T13:01:00Z")
    snapshot = await gate.test_snapshot()
    assert snapshot["line_requests"] == []
    assert snapshot["events"] == []


@pytest.mark.asyncio
async def test_withdrawal_wins_ordering_and_no_request_begins_after_close() -> None:
    database = LocalD1()
    gate = make_gate(database)
    await seed(gate)
    await gate.set_test_observation(82)

    assert await gate.withdraw_recipient("r1", "2026-09-27T13:00:00Z")
    await tick(gate, "2026-09-27T13:01:00Z")
    snapshot = await gate.test_snapshot()
    assert snapshot["line_requests"] == []
    assert snapshot["events"] == []


@pytest.mark.asyncio
async def test_recovery_hold_survives_d1_restore_and_gate_restart_until_explicit_resume() -> (
    None
):
    database = LocalD1()
    storage = LocalDurableStorage()
    gate = make_gate(database, storage)
    await seed(gate)
    await gate.set_test_observation(82)
    await tick(gate)
    sent_event = event(database)
    assert await gate.hold_for_reconciliation()
    assert await gate.restore_test_state()

    restarted_gate = make_gate(database, LocalDurableStorage(storage.values))
    assert (await tick(restarted_gate))["held"] is True
    assert (await restarted_gate.test_snapshot())["line_requests"]
    assert not await restarted_gate.resume_after_reconciliation(False)

    database.connection.execute(
        """INSERT INTO outbound_events (
            id, visit_id, recipient_id, event_kind, retry_key, payload_json,
            outcome, created_at, request_started_at, settled_at,
            first_request_at, attempt_count
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        tuple(
            sent_event[name]
            for name in (
                "id",
                "visit_id",
                "recipient_id",
                "event_kind",
                "retry_key",
                "payload_json",
                "outcome",
                "created_at",
                "request_started_at",
                "settled_at",
                "first_request_at",
                "attempt_count",
            )
        ),
    )
    assert await restarted_gate.resume_after_reconciliation(True)
    await tick(restarted_gate, "2026-09-27T13:01:00Z")
    assert len((await restarted_gate.test_snapshot())["line_requests"]) == 1
    assert event(database)["outcome"] == "accepted"


@pytest.mark.asyncio
async def test_draft_deletes_exactly_forty_eight_hours_after_taipei_cutoff() -> None:
    database = LocalD1()
    gate = make_gate(database)
    store = database
    store.connection.execute(
        """INSERT INTO visits (
            id, hospital, visit_date, department_code, clinic_code,
            clinic_session, patient_number, state, created_at, draft_expires_at
        ) VALUES ('draft', 'ntuh-main', '2026-09-27', 'SYN', 'SYN-1',
            'afternoon', 90, 'draft', '2026-09-27T13:00:00Z',
            '2026-09-29T15:59:00Z')"""
    )

    await tick(gate, "2026-09-29T15:58:59Z")
    assert (
        store.connection.execute(
            "SELECT COUNT(*) FROM visits WHERE id = 'draft'"
        ).fetchone()[0]
        == 1
    )
    await tick(gate, "2026-09-29T15:59:00Z")
    assert (
        store.connection.execute(
            "SELECT COUNT(*) FROM visits WHERE id = 'draft'"
        ).fetchone()[0]
        == 0
    )


class RecordingLine:
    def __init__(self, outcome: str) -> None:
        self.outcome = outcome
        self.requests: list[tuple[str, str, str]] = []

    async def push_text(self, recipient_id: str, text: str, *, retry_key: str):
        self.requests.append((recipient_id, text, retry_key))
        return LinePushResult(self.outcome, 500 if self.outcome == "unknown" else 200)


async def create_pending_event(
    repository: VisitRepository, now: datetime, *, visit_id: str = "v1"
) -> str:
    event_id = str(uuid.uuid4())
    await repository.create_event_if_absent(
        event_id=event_id,
        visit_id=visit_id,
        recipient_id="r1",
        event_kind="near",
        retry_key=str(uuid.uuid4()),
        payload_json=json.dumps({"text": "synthetic test"}),
        now=now,
    )
    return event_id


@pytest.mark.asyncio
async def test_cutoff_rechecked_after_durable_pre_request_work() -> None:
    database = LocalD1()
    gate = make_gate(database)
    await seed(gate, visit_day="2026-09-27", now="2026-09-27T13:00:00Z")
    repository = VisitRepository(CloudflareD1Store(database))
    initial_time = datetime.fromisoformat("2026-09-27T15:58:59+00:00")
    event_id = await create_pending_event(repository, initial_time)
    clock = [initial_time]
    line = RecordingLine("accepted")
    scheduler = OutboxScheduler(repository, None, line, lambda: clock[0])

    async def cross_cutoff(_event_id: str) -> None:
        clock[0] = datetime.fromisoformat("2026-09-27T15:59:00+00:00")

    result = await scheduler.send_event(event_id, before_request=cross_cutoff)
    saved = event(database)
    assert result.started is False
    assert line.requests == []
    assert saved["outcome"] == "pending"
    assert saved["attempt_count"] == 0
    assert saved["first_request_at"] is None
    assert (
        database.connection.execute(
            "SELECT state FROM visits WHERE id = 'v1'"
        ).fetchone()[0]
        == "expired"
    )


@pytest.mark.asyncio
async def test_retry_window_rechecked_after_durable_pre_request_work() -> None:
    database = LocalD1()
    gate = make_gate(database)
    await seed(gate, visit_day="2026-09-30", now="2026-09-28T12:00:00Z")
    repository = VisitRepository(CloudflareD1Store(database))
    initial_time = datetime.fromisoformat("2026-09-28T12:00:00+00:00")
    event_id = await create_pending_event(repository, initial_time)
    clock = [initial_time]
    line = RecordingLine("unknown")
    scheduler = OutboxScheduler(repository, None, line, lambda: clock[0])

    await scheduler.send_event(event_id)
    first = event(database)

    clock[0] = datetime.fromisoformat("2026-09-29T11:59:59+00:00")

    async def cross_retry_window(_event_id: str) -> None:
        clock[0] = datetime.fromisoformat("2026-09-29T12:00:00+00:00")

    result = await scheduler.send_event(event_id, before_request=cross_retry_window)
    saved = event(database)
    assert result.outcome == "unknown"
    assert result.started is False
    assert len(line.requests) == 1
    assert saved["outcome"] == "unknown"
    assert saved["retry_key"] == first["retry_key"]
    assert saved["attempt_count"] == 1
    assert saved["first_request_at"] == first["first_request_at"]


@pytest.mark.asyncio
async def test_start_gate_requires_fresh_exact_trusted_observation_and_freezes_roster(
    monkeypatch,
) -> None:
    from next_is_you.domain import (
        ClinicScope,
        QueueObservation,
    )
    import next_is_you.send_gate as send_gate

    database = LocalD1()
    gate = make_gate(database)
    timestamp = datetime.fromisoformat("2026-09-27T13:00:00+00:00")
    store = CloudflareD1Store(database)
    await store.execute(
        Statement(
            """INSERT INTO recipients (id, line_subject, display_name, consented_at,
            friendship_checked_at, active, created_at) VALUES
            ('r1', 'synthetic-r1', 'Synthetic one', ?, ?, 1, ?)""",
            (timestamp.isoformat(), timestamp.isoformat(), timestamp.isoformat()),
        )
    )
    repository = VisitRepository(store)
    await repository.create_draft(
        visit_id="draft-start",
        hospital="ntuh-main",
        visit_day=datetime(2026, 9, 27).date(),
        department_code="MED",
        clinic_code="MED-A",
        clinic_session="morning",
        patient_number=85,
        now=timestamp,
    )
    assert await repository.add_recipient("draft-start", "r1", timestamp)
    await gate.set_test_observation(70, trustworthy=True)

    assert await gate.start_visit("draft-start", timestamp.isoformat()) == {
        "state": "active"
    }
    visit = await repository.get_visit("draft-start")
    assert visit["state"] == "active" and visit["roster_frozen"] == 1

    class MismatchedReader:
        async def observe(self, expected, now):
            wrong = ClinicScope(
                expected.hospital,
                expected.visit_date,
                expected.department_code,
                "OTHER",
                expected.session,
                expected.doctor_code,
                expected.room_code,
            )
            return QueueObservation(
                wrong, now.isoformat(), 70, trustworthy_current=True
            )

    monkeypatch.setattr(
        send_gate, "_TestHospitalReader", lambda _storage: MismatchedReader()
    )
    await repository.create_draft(
        visit_id="draft-mismatch",
        hospital="ntuh-main",
        visit_day=datetime(2026, 9, 27).date(),
        department_code="MED",
        clinic_code="MED-A",
        clinic_session="morning",
        patient_number=86,
        now=timestamp,
    )
    assert await repository.add_recipient("draft-mismatch", "r1", timestamp)
    assert await gate.start_visit("draft-mismatch", timestamp.isoformat()) == {
        "error": "observation_scope_mismatch"
    }
    assert (await repository.get_visit("draft-mismatch"))["state"] == "draft"

    class StaleReader:
        async def observe(self, expected, now):
            return QueueObservation(
                expected,
                (now - timedelta(minutes=3)).isoformat(),
                70,
                trustworthy_current=True,
            )

    monkeypatch.setattr(
        send_gate, "_TestHospitalReader", lambda _storage: StaleReader()
    )
    await repository.create_draft(
        visit_id="draft-stale",
        hospital="ntuh-main",
        visit_day=datetime(2026, 9, 27).date(),
        department_code="MED",
        clinic_code="MED-A",
        clinic_session="morning",
        patient_number=87,
        now=timestamp,
    )
    assert await repository.add_recipient("draft-stale", "r1", timestamp)
    assert await gate.start_visit("draft-stale", timestamp.isoformat()) == {
        "error": "observation_stale"
    }
    assert (await repository.get_visit("draft-stale"))["state"] == "draft"


@pytest.mark.asyncio
async def test_start_fails_closed_without_explicit_local_test_observation_source() -> (
    None
):
    database = LocalD1()
    store = CloudflareD1Store(database)
    timestamp = datetime.fromisoformat("2026-09-27T13:00:00+00:00")
    await store.execute(
        Statement(
            """INSERT INTO recipients (id, line_subject, display_name, consented_at,
            friendship_checked_at, active, created_at) VALUES
            ('r1', 'synthetic-r1', 'Synthetic one', ?, ?, 1, ?)""",
            (timestamp.isoformat(), timestamp.isoformat(), timestamp.isoformat()),
        )
    )
    repository = VisitRepository(store)
    await repository.create_draft(
        visit_id="production-draft",
        hospital="ntuh-main",
        visit_day=datetime(2026, 9, 27).date(),
        department_code="MED",
        clinic_code="MED-A",
        clinic_session="morning",
        patient_number=85,
        now=timestamp,
    )
    assert await repository.add_recipient("production-draft", "r1", timestamp)
    gate = SystemSendGate(LocalContext(LocalDurableStorage()), {"DB": database})

    result = await gate.start_visit("production-draft", timestamp.isoformat())

    assert result == {"error": "observation_unavailable"}
    visit = await repository.get_visit("production-draft")
    assert visit["state"] == "draft"
    assert (visit["latest_source_read_status"], visit["latest_source_read_reason"]) == (
        "unavailable",
        "no_observation",
    )


@pytest.mark.asyncio
async def test_organizer_correction_keeps_logical_id_and_alert_cap() -> None:
    database = LocalD1()
    gate = make_gate(database)
    await seed(gate, visit_day="2026-09-29", now="2026-09-28T12:00:00Z")
    await gate.set_test_observation(82)
    await tick(gate, "2026-09-28T12:00:00Z")
    before = database.connection.execute(
        "SELECT COUNT(*) FROM outbound_events WHERE visit_id = 'v1' AND event_kind = 'near'"
    ).fetchone()[0]
    assert before == 1
    assert await gate.stop_visit("v1", "2026-09-28T12:01:00Z") == "stopped"

    assert await gate.correct_stopped_visit(
        "v1",
        hospital="ntuh-main",
        visit_day=datetime(2026, 9, 29).date(),
        department_code="SYN",
        clinic_code="SYN-2",
        clinic_session="afternoon",
        patient_number=86,
        recipient_ids=("r1",),
    )
    assert await gate.start_visit("v1", "2026-09-28T12:02:00Z") == {"state": "active"}
    await tick(gate, "2026-09-28T12:03:00Z")
    assert (
        database.connection.execute(
            "SELECT COUNT(*) FROM visits WHERE id = 'v1'"
        ).fetchone()[0]
        == 1
    )
    assert (
        database.connection.execute(
            "SELECT COUNT(*) FROM outbound_events WHERE visit_id = 'v1' AND event_kind = 'near'"
        ).fetchone()[0]
        == 1
    )
