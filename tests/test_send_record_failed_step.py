"""A gate step that fails after its own write is not an outside change (#264).

Fixture/mock evidence. Each case drives the real send gate, through its public
methods or the organizer API routes, over the local database. One statement or
one Durable Object storage call fails after the step has already changed the
send record, and the next tick must not enter a send interruption (ADR 0007).

The last two sections pin what still must interrupt: a change made outside the
gate, an unrecorded send result and a send record changed during a request.
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import datetime, timezone
from typing import Any, Callable

import pytest
from httpx import ASGITransport, AsyncClient

import next_is_you.send_gate as send_gate_module
from next_is_you import hospital_registry
from next_is_you.auth import CSRF_COOKIE_NAME, SESSION_COOKIE_NAME, issue_session
from next_is_you.domain import (
    ClinicMatch,
    ClinicRoster,
    MatchKind,
    ReadSkipped,
    SupportedDepartment,
)
from next_is_you.identity import IdentityRepository
from next_is_you.persistence import CloudflareD1Store, VisitRepository
from next_is_you.send_gate import SystemSendGate
from test_scheduler_outbox import LocalD1, LocalDurableStorage, make_gate, seed
from worker import create_app

SECRET = "failed-step-test-secret-with-at-least-32-bytes"

NOW = "2026-09-27T13:00:00Z"
LATER = "2026-09-27T13:01:00Z"
AFTER = "2026-09-27T13:02:00Z"
BEFORE_CUTOFF = "2026-09-27T15:58:00Z"
CUTOFF = "2026-09-27T15:59:00Z"
PAST_CUTOFF = "2026-09-27T16:00:00Z"

# Statements, named by what they do. Matched with whitespace collapsed.
FIND_STOPPING = "SELECT id FROM visits WHERE state = 'stopping'"
FINISH_STOP = "UPDATE visits SET state = 'stopped'"
FIND_DAY_OVER = "SELECT id, visit_date FROM visits WHERE state = 'active'"
ERASE_WITHDRAWN = "DELETE FROM recipients WHERE active = 0 AND consented_at IS NOT NULL"
ERASE_PENDING = "DELETE FROM recipients WHERE active = 0 AND consented_at IS NULL"
DELETE_ENDED = "DELETE FROM visits WHERE state IN ('stopped', 'expired')"
ACTIVE_ROWS = "SELECT v.*, r.id AS recipient_id"
EVENT_KINDS = "SELECT recipient_id, event_kind FROM outbound_events"
RETRYABLE_FOR_VISIT = "SELECT e.*, r.line_subject FROM outbound_events"
RETRYABLE_ONE = "SELECT e.*, r.line_subject, v.visit_date"
CONFIRM_BATCH = "SELECT id FROM outbound_events WHERE id IN"
CONFIRM_REMINDER = "AS created"
ATTEMPT_COUNT = "SELECT attempt_count FROM outbound_events"
ABORT_ATTEMPT = "attempt_count = attempt_count - 1"
SEND_RESULT = "SET outcome = ?, settled_at = ?, error_code = ? WHERE id = ?"
CHECK_DURING_SEND = "FROM outbound_events WHERE id != ?"
VISIT_BY_ID = "SELECT * FROM visits WHERE id = ?"
STATE_BY_ID = "SELECT state FROM visits WHERE id = ?"
WITHDRAW = "UPDATE recipients SET active = 0"
REMOVE_FROM_VISIT = "DELETE FROM visit_recipients"
CHECK_REMOVED_EVENTS = "AND recipient_id = ? AND outcome = 'in_flight'"
STORE_READ = "UPDATE visits SET near_last_current_number = ?"
STORE_VERDICT = "UPDATE visits SET latest_source_read_status"
CORRECT_CLINIC = "UPDATE visits SET hospital = ?"


class StatementFailed(RuntimeError):
    pass


class StorageFailed(RuntimeError):
    pass


class HookedD1(LocalD1):
    """The local database, running an action the next time a statement is built."""

    def __init__(self) -> None:
        super().__init__()
        self.hooks: dict[str, Callable[[], None]] = {}

    def prepare(self, sql: str):
        flat = " ".join(sql.split())
        for fragment in [item for item in self.hooks if item in flat]:
            self.hooks.pop(fragment)()
        return super().prepare(sql)

    def at(self, fragment: str, action: Callable[[], None]) -> None:
        self.hooks[fragment] = action

    def fail_at(self, fragment: str, first: Callable[[], None] = lambda: None) -> None:
        def fail() -> None:
            first()
            raise StatementFailed(fragment)

        self.at(fragment, fail)

    def sql(self, statement: str, *values: Any) -> None:
        """A write made outside the gate."""
        self.connection.execute(statement, values)

    def state(self, visit_id: str = "v1") -> str:
        return self.connection.execute(
            "SELECT state FROM visits WHERE id = ?", (visit_id,)
        ).fetchone()[0]


class HookedStorage(LocalDurableStorage):
    def __init__(self) -> None:
        super().__init__()
        self.fail_clearing_request = False
        self.on_get: Callable[[str], None] = lambda key: None

    async def get(self, key: str) -> Any:
        self.on_get(key)
        return await super().get(key)

    async def put(self, key: str, value: Any) -> None:
        if self.fail_clearing_request and key == "inflight_event_id" and value == "":
            self.fail_clearing_request = False
            raise StorageFailed(key)
        await super().put(key, value)


class Clock:
    """Stands in for the gate's clock on a tick that is given no fixed time."""

    def __init__(self, monkeypatch, start: str) -> None:
        self.set(start)
        clock = self

        class FakeDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                return clock.current

        monkeypatch.setattr(send_gate_module, "datetime", FakeDatetime)

    def set(self, when: str) -> None:
        self.current = _at(when)


def _at(when: str) -> datetime:
    return datetime.fromisoformat(when.replace("Z", "+00:00")).astimezone(timezone.utc)


async def running(
    storage: LocalDurableStorage | None = None, current: int | None = 82
) -> tuple[HookedD1, SystemSendGate]:
    database = HookedD1()
    gate = make_gate(database, storage)
    await seed(gate)
    await gate.set_test_observation(current, trustworthy=current is not None)
    return database, gate


async def add_second_recipient(database: HookedD1, gate: SystemSendGate) -> None:
    database.sql(
        """INSERT INTO recipients (id, line_subject, display_name, consented_at,
        friendship_checked_at, active, created_at) VALUES
        ('r2', 'U00000000000000000000000000000002', 'Synthetic two', ?, ?, 1, ?)""",
        NOW,
        NOW,
        NOW,
    )
    database.sql(
        "INSERT INTO visit_recipients (visit_id, recipient_id, selected_at)"
        " VALUES ('v1', 'r2', ?)",
        NOW,
    )
    await accept_setup(gate)


async def accept_setup(gate: SystemSendGate) -> None:
    """Records rows a test set up by hand, the way a captain resumes sending."""
    await gate.hold_for_reconciliation()
    assert await gate.resume_after_reconciliation(True)


async def sent(gate: SystemSendGate) -> list[str]:
    """The retry key of every LINE request, in order."""
    return [item["retry_key"] for item in (await gate.test_snapshot())["line_requests"]]


async def assert_not_interrupted(gate: SystemSendGate, when: str = AFTER) -> dict:
    result = await gate.scheduled_tick(when)
    assert result.get("reason") != "d1_ledger_mismatch", result
    assert result["held"] is False, result
    assert await gate.sending_interrupted() is False
    return result


async def interrupt_a_send(gate: SystemSendGate) -> None:
    """A tick dies during its LINE request, leaving the attempt in flight."""
    await gate.set_test_line_mode("crash_once")
    with pytest.raises(asyncio.CancelledError):
        await gate.scheduled_tick(NOW)


async def failing_tick(
    database: HookedD1, gate: SystemSendGate, fragment: str, when: str | None
) -> None:
    database.fail_at(fragment)
    with pytest.raises(StatementFailed):
        await gate.scheduled_tick(when)


# The lifecycle part of a tick.


@pytest.mark.asyncio
async def test_tick_fails_after_recovering_an_interrupted_send() -> None:
    database, gate = await running()
    await interrupt_a_send(gate)

    await failing_tick(database, gate, FIND_STOPPING, LATER)

    await assert_not_interrupted(gate)
    keys = await sent(gate)
    assert len(keys) == 2 and keys[0] == keys[1]


@pytest.mark.asyncio
async def test_tick_fails_after_finishing_a_stop() -> None:
    database, gate = await running()
    await interrupt_a_send(gate)
    assert await gate.stop_visit("v1", LATER) == "stopping"

    await failing_tick(database, gate, FIND_DAY_OVER, LATER)

    assert database.state() == "stopped"
    await assert_not_interrupted(gate)


@pytest.mark.asyncio
async def test_tick_fails_after_ending_a_visit_whose_day_is_over() -> None:
    database, gate = await running()

    await failing_tick(database, gate, ERASE_WITHDRAWN, CUTOFF)

    assert database.state() == "expired"
    await assert_not_interrupted(gate, PAST_CUTOFF)


@pytest.mark.asyncio
async def test_tick_fails_after_erasing_a_withdrawn_recipient() -> None:
    database, gate = await running()
    database.fail_at(ERASE_WITHDRAWN)
    with pytest.raises(StatementFailed):
        await gate.withdraw_recipient("r1", NOW)

    await failing_tick(database, gate, ERASE_PENDING, LATER)

    assert database.connection.execute("SELECT * FROM recipients").fetchall() == []
    await assert_not_interrupted(gate)


@pytest.mark.asyncio
async def test_tick_fails_after_deleting_an_expired_draft_that_had_sends() -> None:
    database, gate = await running()
    await gate.scheduled_tick(NOW)
    assert await gate.stop_visit("v1", LATER) == "stopped"
    assert await gate.correct_stopped_visit(
        "v1",
        hospital="ntuh-main",
        visit_day=_at(NOW).date(),
        department_code="SYN",
        clinic_code="SYN-1",
        clinic_session="afternoon",
        patient_number=85,
        recipient_ids=("r1",),
    )

    await failing_tick(database, gate, DELETE_ENDED, "2026-09-29T15:59:00Z")

    assert database.connection.execute("SELECT * FROM visits").fetchall() == []
    await assert_not_interrupted(gate, "2026-09-29T16:00:00Z")


@pytest.mark.asyncio
async def test_tick_fails_after_deleting_an_ended_visit() -> None:
    database, gate = await running()
    assert await gate.stop_visit("v1", LATER) == "stopped"

    await failing_tick(database, gate, ACTIVE_ROWS, "2026-09-29T13:01:00Z")

    assert database.connection.execute("SELECT * FROM visits").fetchall() == []
    await assert_not_interrupted(gate, "2026-09-29T13:02:00Z")


# The reading and queueing part of a tick.


@pytest.mark.asyncio
async def test_tick_fails_after_storing_an_unusable_read() -> None:
    database, gate = await running(current=None)

    await failing_tick(database, gate, RETRYABLE_FOR_VISIT, NOW)

    await assert_not_interrupted(gate)


@pytest.mark.asyncio
async def test_tick_fails_after_queueing_a_reminder() -> None:
    database, gate = await running()

    await failing_tick(database, gate, CONFIRM_BATCH, NOW)

    await assert_not_interrupted(gate)
    assert len(await sent(gate)) == 1


@pytest.mark.asyncio
async def test_tick_fails_after_queueing_an_unavailable_message() -> None:
    database, gate = await running(current=None)
    await gate.scheduled_tick(NOW)
    await gate.scheduled_tick(LATER)

    await failing_tick(database, gate, CONFIRM_REMINDER, AFTER)

    await assert_not_interrupted(gate, "2026-09-27T13:03:00Z")
    assert len(await sent(gate)) == 1


@pytest.mark.asyncio
async def test_tick_fails_after_ending_a_visit_between_reads(monkeypatch) -> None:
    """Needs a second running visit, which only data older than #172 can hold."""
    database, gate = await running()
    await seed(gate, visit_id="v2", recipient_id="r2", visit_day="2026-09-28")
    clock = Clock(monkeypatch, BEFORE_CUTOFF)
    database.at(ACTIVE_ROWS, lambda: clock.set(PAST_CUTOFF))

    await failing_tick(database, gate, EVENT_KINDS, None)

    assert database.state("v1") == "expired"
    await assert_not_interrupted(gate, PAST_CUTOFF)


# The sending part of a tick, outside the LINE request.


@pytest.mark.asyncio
async def test_tick_fails_after_ending_a_visit_instead_of_sending(monkeypatch) -> None:
    storage = HookedStorage()
    database, gate = await running(storage)
    clock = Clock(monkeypatch, BEFORE_CUTOFF)

    def cross_cutoff() -> None:
        clock.set(PAST_CUTOFF)
        storage.fail_clearing_request = True

    database.at(RETRYABLE_ONE, cross_cutoff)
    # A gate that has nothing left to do after ending the visit does not fail.
    with contextlib.suppress(StorageFailed):
        await gate.scheduled_tick(None)

    assert database.state() == "expired"
    assert await sent(gate) == []
    await assert_not_interrupted(gate, PAST_CUTOFF)


@pytest.mark.asyncio
async def test_tick_fails_after_beginning_an_attempt() -> None:
    database, gate = await running()

    await failing_tick(database, gate, ATTEMPT_COUNT, NOW)

    assert await sent(gate) == []
    await assert_not_interrupted(gate)
    assert len(await sent(gate)) == 1


@pytest.mark.asyncio
async def test_tick_fails_while_abandoning_an_attempt_at_the_cutoff(
    monkeypatch,
) -> None:
    database, gate = await running()
    clock = Clock(monkeypatch, BEFORE_CUTOFF)
    database.at(ATTEMPT_COUNT, lambda: clock.set(PAST_CUTOFF))

    await failing_tick(database, gate, ABORT_ATTEMPT, None)

    assert database.state() == "expired"
    assert await sent(gate) == []
    await assert_not_interrupted(gate, PAST_CUTOFF)


@pytest.mark.asyncio
async def test_tick_fails_clearing_a_request_after_its_result_is_checked() -> None:
    storage = HookedStorage()
    database, gate = await running(storage)
    await add_second_recipient(database, gate)

    def arm() -> None:
        storage.fail_clearing_request = True

    database.at(SEND_RESULT, arm)
    with pytest.raises(StorageFailed):
        await gate.scheduled_tick(NOW)

    await assert_not_interrupted(gate)
    keys = await sent(gate)
    assert len(keys) == 2 and keys[0] != keys[1]


# Organizer actions, through the API routes.


def organizer(database: HookedD1, gate: SystemSendGate):
    now = int(_at(LATER).timestamp())
    store = CloudflareD1Store(database)
    app = create_app(
        settings={
            "session_secret": SECRET,
            "organizer_subjects": {"organizer"},
            "line_login_channel_id": "local",
            "line_login_channel_secret": "local-secret",
            "line_login_redirect_uri": "https://family.example/auth/line/callback",
        },
        identity_repository=IdentityRepository(store),
        visit_repository=VisitRepository(store),
        send_gate=gate,
        clock=lambda: now,
    )
    session = issue_session("organizer", "organizer", SECRET, now=now)
    return AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="https://family.example",
        cookies={
            SESSION_COOKIE_NAME: session.value,
            CSRF_COOKIE_NAME: session.csrf_token,
        },
        headers={"x-csrf-token": session.csrf_token},
    )


async def failing_request(
    database: HookedD1, gate: SystemSendGate, fragment: str, path: str, **request: Any
) -> None:
    """The organizer's action answers an error because one statement failed."""
    database.fail_at(fragment)
    method = request.pop("method", "POST")
    async with organizer(database, gate) as http:
        response = await http.request(method, path, **request)
    assert response.status_code == 500
    assert database.hooks == {}, "the statement was never reached"


@pytest.mark.asyncio
@pytest.mark.parametrize("fragment", [FINISH_STOP, STATE_BY_ID])
async def test_stop_fails_after_closing_the_visit(fragment: str) -> None:
    database, gate = await running()

    await failing_request(database, gate, fragment, "/api/organizer/visits/v1/stop")

    assert database.state() in {"stopping", "stopped"}
    await assert_not_interrupted(gate)
    assert database.state() == "stopped"
    assert await sent(gate) == []


@pytest.mark.asyncio
async def test_stop_fails_after_recovering_an_interrupted_send() -> None:
    database, gate = await running()
    await interrupt_a_send(gate)

    await failing_request(
        database, gate, VISIT_BY_ID, "/api/organizer/visits/unknown/stop"
    )

    await assert_not_interrupted(gate)
    keys = await sent(gate)
    assert len(keys) == 2 and keys[0] == keys[1]


@pytest.mark.asyncio
@pytest.mark.parametrize(("visit_id", "status"), [("unknown", 404), ("draft", 409)])
async def test_a_refused_stop_that_recovered_an_interrupted_send(
    visit_id: str, status: int
) -> None:
    """Nothing raises: the refusal returns after the recovery has been written."""
    database, gate = await running()
    await interrupt_a_send(gate)
    async with organizer(database, gate) as http:
        await create_draft(http, database)
        draft_id = database.connection.execute(
            "SELECT id FROM visits WHERE state = 'draft'"
        ).fetchone()[0]
        target = draft_id if visit_id == "draft" else visit_id
        response = await http.post(f"/api/organizer/visits/{target}/stop")
    assert response.status_code == status

    await assert_not_interrupted(gate)
    keys = await sent(gate)
    assert len(keys) == 2 and keys[0] == keys[1]


@pytest.mark.asyncio
async def test_withdrawal_fails_after_deactivating_the_recipient() -> None:
    database, gate = await running()

    await failing_request(
        database,
        gate,
        ERASE_WITHDRAWN,
        "/api/organizer/recipients/r1/withdraw",
    )

    await assert_not_interrupted(gate)
    assert await sent(gate) == []


@pytest.mark.asyncio
async def test_withdrawal_fails_after_recovering_an_interrupted_send() -> None:
    database, gate = await running()
    await interrupt_a_send(gate)

    await failing_request(
        database, gate, WITHDRAW, "/api/organizer/recipients/r1/withdraw"
    )

    await assert_not_interrupted(gate)
    keys = await sent(gate)
    assert len(keys) == 2 and keys[0] == keys[1]


@pytest.mark.asyncio
async def test_recipient_removal_fails_after_removing_the_recipient() -> None:
    database, gate = await running()
    await add_second_recipient(database, gate)

    await failing_request(
        database,
        gate,
        CHECK_REMOVED_EVENTS,
        "/api/visits/v1/recipients/r2",
        method="DELETE",
    )

    await assert_not_interrupted(gate)
    assert len(await sent(gate)) == 1


@pytest.mark.asyncio
async def test_recipient_removal_fails_after_recovering_an_interrupted_send() -> None:
    database, gate = await running()
    await add_second_recipient(database, gate)
    await interrupt_a_send(gate)

    await failing_request(
        database,
        gate,
        REMOVE_FROM_VISIT,
        "/api/visits/v1/recipients/r2",
        method="DELETE",
    )

    await assert_not_interrupted(gate)


DRAFT_BODY = {
    "hospital": "ntuh-main",
    "date": "2026-09-27",
    "department_code": "SYN",
    "clinic_code": "SYN-1",
    "session": "afternoon",
    "patient_number": 85,
    "recipient_ids": ["r1"],
}


async def create_draft(http: AsyncClient, database: HookedD1, **changes: Any) -> str:
    response = await http.post("/api/organizer/visits", json=DRAFT_BODY | changes)
    assert response.status_code == 201, response.text
    return response.json()["id"]


class ScheduledClinicReader:
    """A full-schedule hospital whose clinic is listed and has not called yet."""

    def __init__(self, storage: Any, fetch: Any) -> None:
        pass

    async def list_clinics(self, query, now):
        return ClinicRoster(False, (), "no_observation")

    async def match_clinic(self, query, now):
        return ClinicMatch(MatchKind.MATCHED)

    async def observe_for_start(self, scope, now):
        return ReadSkipped("clinic_not_started")

    async def observe(self, scope, now):
        return ReadSkipped("clinic_not_started")


SCHEDULED_HOSPITAL = "synthetic-scheduled"


def use_scheduled_hospital(monkeypatch, gate: SystemSendGate) -> None:
    monkeypatch.setitem(
        hospital_registry.HOSPITAL_REGISTRY,
        SCHEDULED_HOSPITAL,
        hospital_registry.HospitalEntry(
            display_name="合成醫院（僅供測試）",
            reader_type=ScheduledClinicReader,
            official_link="https://synthetic-hospital.example/progress",
            departments=(SupportedDepartment("SYN", "合成科"),),
        ),
    )
    gate.env["NTUH_READER_ENABLED"] = "1"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("changes", "fragment"),
    [
        pytest.param({}, STORE_READ, id="first-read-trusted"),
        pytest.param({}, STORE_VERDICT, id="first-read-trusted-verdict"),
        pytest.param(
            {"hospital": SCHEDULED_HOSPITAL}, STORE_VERDICT, id="waiting-for-calls"
        ),
        pytest.param(
            {"hospital": SCHEDULED_HOSPITAL, "date": "2026-09-30"},
            STORE_VERDICT,
            id="future-day",
        ),
    ],
)
async def test_start_fails_after_starting_the_visit(
    monkeypatch, changes: dict[str, str], fragment: str
) -> None:
    database, gate = await running()
    assert await gate.stop_visit("v1", NOW) == "stopped"
    if "hospital" in changes:
        use_scheduled_hospital(monkeypatch, gate)
    async with organizer(database, gate) as http:
        visit_id = await create_draft(http, database, **changes)

    await failing_request(
        database, gate, fragment, f"/api/organizer/visits/{visit_id}/start"
    )

    assert database.state(visit_id) == "active"
    await assert_not_interrupted(gate)


@pytest.mark.asyncio
async def test_correction_fails_after_reopening_the_visit() -> None:
    database, gate = await running()
    assert await gate.stop_visit("v1", NOW) == "stopped"

    await failing_request(
        database,
        gate,
        CORRECT_CLINIC,
        "/api/organizer/visits/v1/correct",
        json=DRAFT_BODY,
    )

    assert database.state() == "draft"
    await assert_not_interrupted(gate)


@pytest.mark.asyncio
async def test_correction_fails_after_erasing_a_removed_recipients_sends() -> None:
    database, gate = await running()
    await add_second_recipient(database, gate)
    await gate.scheduled_tick(NOW)
    assert await gate.stop_visit("v1", LATER) == "stopped"

    await failing_request(
        database,
        gate,
        STORE_VERDICT,
        "/api/organizer/visits/v1/correct",
        json=DRAFT_BODY,
    )

    events = database.connection.execute(
        "SELECT recipient_id FROM outbound_events"
    ).fetchall()
    assert [row[0] for row in events] == ["r1"]
    await assert_not_interrupted(gate)


# A change made outside the gate still interrupts sending.


CHANGE = "UPDATE visits SET near_prev_observed_number = 70 WHERE id = 'v1'"


@pytest.mark.asyncio
async def test_outside_change_before_a_tick_interrupts() -> None:
    database, gate = await running()
    database.sql(CHANGE)

    result = await gate.scheduled_tick(NOW)

    assert result["reason"] == "d1_ledger_mismatch"
    assert await gate.sending_interrupted() is True
    assert await sent(gate) == []


@pytest.mark.asyncio
async def test_outside_change_before_a_send_interrupts() -> None:
    storage = HookedStorage()
    database, gate = await running(storage)
    await add_second_recipient(database, gate)
    reads: list[str] = []

    def change_before_the_second_send(key: str) -> None:
        if key == "recovery_hold":
            reads.append(key)
            # The tick asks once, then once before each send.
            if len(reads) == 3:
                database.sql(CHANGE)

    storage.on_get = change_before_the_second_send
    await gate.scheduled_tick(NOW)
    storage.on_get = lambda key: None

    assert await gate.sending_interrupted() is True
    assert len(await sent(gate)) == 1


@pytest.mark.asyncio
async def test_outside_change_before_an_organizer_action_interrupts() -> None:
    database, gate = await running()
    database.sql(CHANGE)

    async with organizer(database, gate) as http:
        await http.post("/api/organizer/visits/v1/stop")

    assert await gate.sending_interrupted() is True


@pytest.mark.asyncio
async def test_outside_change_before_a_start_refuses_it_and_interrupts() -> None:
    database, gate = await running()
    assert await gate.stop_visit("v1", NOW) == "stopped"
    async with organizer(database, gate) as http:
        visit_id = await create_draft(http, database)
        database.sql(CHANGE)
        response = await http.post(f"/api/organizer/visits/{visit_id}/start")

    assert response.status_code == 503
    assert await gate.sending_interrupted() is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("current", "fragment", "when"),
    [
        pytest.param(None, RETRYABLE_FOR_VISIT, NOW, id="a-read-fails"),
        pytest.param(82, ERASE_WITHDRAWN, CUTOFF, id="a-write-fails"),
    ],
)
async def test_outside_change_that_fails_a_step_still_interrupts(
    current: int | None, fragment: str, when: str
) -> None:
    """A restore cancels the queries in flight: a failed statement records nothing."""
    database, gate = await running(current=current)
    database.fail_at(fragment, first=lambda: database.sql(CHANGE))
    with pytest.raises(StatementFailed):
        await gate.scheduled_tick(when)

    result = await gate.scheduled_tick(when)

    assert result["reason"] == "d1_ledger_mismatch"
    assert await gate.sending_interrupted() is True


# The send path keeps its outcomes.


async def sending(gate: SystemSendGate) -> asyncio.Task:
    await gate.set_test_line_mode("wait")
    task = asyncio.create_task(gate.scheduled_tick(NOW))
    await gate.wait_test_request_started()
    return task


@pytest.mark.asyncio
async def test_an_unrecorded_send_result_interrupts() -> None:
    database, gate = await running()
    task = await sending(gate)
    database.sql("UPDATE outbound_events SET outcome = 'failed'")
    await gate.release_test_request()

    result = await task

    assert result["reason"] == "outbox_settlement_missing"
    assert await gate.sending_interrupted() is True


@pytest.mark.asyncio
async def test_a_send_record_changed_during_a_request_interrupts() -> None:
    database, gate = await running()
    task = await sending(gate)
    database.sql(CHANGE)
    await gate.release_test_request()

    result = await task

    assert result["reason"] == "d1_ledger_changed_during_send"
    assert await gate.sending_interrupted() is True


@pytest.mark.asyncio
async def test_a_change_during_a_request_whose_check_fails_interrupts() -> None:
    """The result is written but unchecked, so it is not recorded as the gate's."""
    database, gate = await running()
    task = await sending(gate)
    database.sql(CHANGE)
    database.fail_at(CHECK_DURING_SEND)
    await gate.release_test_request()
    with pytest.raises(StatementFailed):
        await task

    result = await gate.scheduled_tick(LATER)

    assert result["reason"] == "d1_ledger_mismatch"
    assert await gate.sending_interrupted() is True


@pytest.mark.asyncio
async def test_a_result_that_fails_to_be_written_is_retried_with_the_same_key() -> None:
    database, gate = await running()

    await failing_tick(database, gate, SEND_RESULT, NOW)

    await assert_not_interrupted(gate, LATER)
    keys = await sent(gate)
    assert len(keys) == 2 and keys[0] == keys[1]
