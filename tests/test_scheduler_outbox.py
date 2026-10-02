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
    env = {"DB": database, "NIY006_LOCAL_TEST_MODE": "1"}
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


@pytest.mark.asyncio
async def test_duplicate_ticks_and_corrected_watch_keep_one_near_event() -> None:
    database = LocalD1()
    gate = make_gate(database)
    await seed(gate)
    await gate.set_test_observation(82)

    first = await tick(gate)
    await tick(gate, "2026-09-27T13:01:00Z")
    assert first["events_created"] == 1
    assert (
        database.connection.execute(
            "SELECT COUNT(*) FROM outbound_events WHERE visit_id = 'v1' AND event_kind = 'near'"
        ).fetchone()[0]
        == 1
    )
    assert len((await gate.test_snapshot())["line_requests"]) == 1

    assert await gate.correct_test_watch("v1", "2026-09-27", 86, "2026-09-27T13:02:00Z")
    await gate.set_test_observation(83)
    await tick(gate, "2026-09-27T13:03:00Z")
    snapshot = await gate.test_snapshot()
    assert len(snapshot["events"]) == 1
    assert snapshot["events"][0]["event_kind"] == "near"
    assert len(snapshot["line_requests"]) == 1


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
    duplicate_stop = asyncio.create_task(
        gate.stop_visit("v1", "2026-09-27T13:01:01Z")
    )
    await asyncio.sleep(0)
    assert (
        database.connection.execute(
            "SELECT state FROM visits WHERE id = 'v1'"
        ).fetchone()[0]
        == "stopping"
    )
    await gate.release_test_request()

    result = await sending
    assert result["held"] is False
    assert await asyncio.wait_for(duplicate_stop, timeout=1) == "stopped"
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
async def test_visit_recipient_removal_waits_then_erases_events_and_blocks_future_sends() -> (
    None
):
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
    assert await removing
    assert (
        database.connection.execute("SELECT COUNT(*) FROM outbound_events").fetchone()[
            0
        ]
        == 0
    )
    await tick(gate, "2026-09-27T13:02:00Z")
    assert len((await gate.test_snapshot())["line_requests"]) == 1


@pytest.mark.asyncio
async def test_visit_recipient_removal_wins_ordering_and_blocks_future_sends() -> None:
    database = LocalD1()
    gate = make_gate(database)
    await seed(gate)
    await gate.set_test_observation(82)

    removing = asyncio.create_task(
        gate.remove_visit_recipient("v1", "r1", "2026-09-27T13:00:00Z")
    )
    sending = asyncio.create_task(tick(gate, "2026-09-27T13:01:00Z"))

    assert await removing
    await sending

    snapshot = await gate.test_snapshot()
    assert snapshot["line_requests"] == []
    assert snapshot["events"] == []


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
            recipient_ids=("r1",),
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
    assert await repository.selected_recipient_ids("draft-v1") == set()


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
