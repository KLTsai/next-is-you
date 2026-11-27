"""The send gate and the organizer API follow the visit lifecycle (#251).

Fixture/mock evidence: the real send gate, scheduler and API routes over a local
database, with a fixed clock and a synthetic LINE transport.
"""

from __future__ import annotations

import asyncio
from datetime import datetime

import pytest
from httpx import ASGITransport, AsyncClient

from local_d1 import LocalD1, LocalStore
from next_is_you import visit_lifecycle
from next_is_you.auth import CSRF_COOKIE_NAME, SESSION_COOKIE_NAME, issue_session
from next_is_you.identity import IdentityRepository
from next_is_you.persistence import VisitRepository
from next_is_you.send_gate import SystemSendGate
from test_scheduler_outbox import LocalDurableStorage, make_gate
from visit_states import add_draft, move_draft_to
from worker import create_app

SECRET = "visit-lifecycle-test-secret-with-32-bytes"
# 21:00 Asia/Taipei on the visit day, and that day's 23:59 cutoff.
BEFORE_CUTOFF = "2026-09-27T13:00:00Z"
AT_CUTOFF = "2026-09-27T15:59:00Z"
AFTER_CUTOFF = "2026-09-27T16:00:00Z"
NOW = datetime.fromisoformat("2026-09-27T13:00:00+00:00")


async def organizer(
    database: LocalD1, gate: SystemSendGate
) -> tuple[AsyncClient, dict[str, str]]:
    store = LocalStore(database)
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
        clock=NOW.timestamp,
    )
    http = AsyncClient(
        transport=ASGITransport(app=app), base_url="https://family.example"
    )
    session = issue_session("organizer", "organizer", SECRET, now=int(NOW.timestamp()))
    http.cookies.set(SESSION_COOKIE_NAME, session.value, domain="family.example")
    http.cookies.set(CSRF_COOKIE_NAME, session.csrf_token, domain="family.example")
    return http, {"x-csrf-token": session.csrf_token}


async def visit_in(
    state: str,
) -> tuple[LocalD1, SystemSendGate, VisitRepository]:
    """A visit of two recipients, with the gate holding its send record."""
    database = LocalD1()
    gate = make_gate(database)
    repository = VisitRepository(LocalStore(database))
    await add_draft(repository, recipient_ids=("r1", "r2"))
    await move_draft_to(repository, state)
    return database, gate, repository


CORRECTION = {
    "hospital": "ntuh-main",
    "date": "2026-09-27",
    "department_code": "OPH",
    "clinic_code": "SYN-2",
    "session": "afternoon",
    "patient_number": 86,
    "recipient_ids": ["r1"],
}


async def correct(gate: SystemSendGate) -> bool:
    return await gate.correct_stopped_visit(
        "v1",
        hospital="ntuh-main",
        visit_day=NOW.date(),
        department_code="OPH",
        clinic_code="SYN-2",
        clinic_session="afternoon",
        patient_number=86,
        recipient_ids=("r1",),
    )


# One definition of what each state allows


@pytest.mark.asyncio
@pytest.mark.parametrize("changed", [False, True])
async def test_the_gate_and_the_stop_routes_follow_the_stop_rule(
    monkeypatch, changed: bool
) -> None:
    database, gate, _ = await visit_in("stopped")
    http, headers = await organizer(database, gate)
    if changed:
        monkeypatch.setattr(visit_lifecycle, "STOP_ACCEPTS", ("active", "stopping"))

    from_gate = await gate.stop_visit("v1", BEFORE_CUTOFF)
    answers = [
        await http.post(path, headers=headers)
        for path in ("/api/organizer/visits/v1/stop", "/api/visits/v1/stop")
    ]

    assert from_gate == ("invalid_lifecycle_state" if changed else "stopped")
    assert [answer.status_code for answer in answers] == [409 if changed else 200] * 2


@pytest.mark.asyncio
@pytest.mark.parametrize("changed", [False, True])
async def test_the_gate_and_the_removal_route_follow_the_removal_rule(
    monkeypatch, changed: bool
) -> None:
    _, gate, _ = await visit_in("active")
    route_database, route_gate, _ = await visit_in("active")
    http, headers = await organizer(route_database, route_gate)
    if changed:
        monkeypatch.setattr(visit_lifecycle, "RECIPIENT_REMOVAL_FROM", ("draft",))

    from_gate = await gate.remove_visit_recipient("v1", "r2", BEFORE_CUTOFF)
    answer = await http.delete("/api/visits/v1/recipients/r2", headers=headers)

    assert from_gate is not changed
    assert answer.status_code == (404 if changed else 204)


@pytest.mark.asyncio
@pytest.mark.parametrize("changed", [False, True])
async def test_the_gate_and_the_correction_routes_follow_the_reopen_rule(
    monkeypatch, changed: bool
) -> None:
    _, gate, _ = await visit_in("expired")
    route_database, route_gate, _ = await visit_in("expired")
    http, headers = await organizer(route_database, route_gate)
    if changed:
        monkeypatch.setattr(visit_lifecycle, "CORRECTION_REOPENS_FROM", ("stopped",))

    from_gate = await correct(gate)
    read = await http.get("/api/organizer/visits/v1/correction", headers=headers)
    written = await http.post(
        "/api/organizer/visits/v1/correct", headers=headers, json=CORRECTION
    )

    assert from_gate is not changed
    assert read.status_code == (409 if changed else 200)
    assert written.status_code == (409 if changed else 200)


@pytest.mark.asyncio
@pytest.mark.parametrize("changed", [False, True])
async def test_the_gate_follows_the_start_rule(monkeypatch, changed: bool) -> None:
    _, gate, _ = await visit_in("draft")
    await gate.set_test_observation(70)
    if changed:
        monkeypatch.setattr(visit_lifecycle, "START_FROM", ())

    result = await gate.start_visit("v1", BEFORE_CUTOFF)

    assert result == (
        {"error": "invalid_lifecycle_state"} if changed else {"state": "active"}
    )


# One end step, inside the gate's guarded write on the send record


class EndSteps:
    """Every use of the end step, and whether the gate lock was held for it."""

    def __init__(self, monkeypatch, gate: SystemSendGate) -> None:
        self.under_lock: list[bool] = []
        end = visit_lifecycle.VisitLifecycle._end

        def recorded(lifecycle, *args):
            self.under_lock.append(gate._lock.locked())
            return end(lifecycle, *args)

        monkeypatch.setattr(visit_lifecycle.VisitLifecycle, "_end", recorded)


def use_clock(gate: SystemSendGate, *readings: str) -> list[str]:
    """Give the tick's scheduler these clock readings; the last one repeats."""
    left = list(readings)
    scheduler = gate._scheduler

    def clock() -> datetime:
        reading = left.pop(0) if len(left) > 1 else left[0]
        return datetime.fromisoformat(reading.replace("Z", "+00:00"))

    gate._scheduler = lambda _clock, line: scheduler(clock, line)
    return left


async def running_visit() -> tuple[LocalD1, LocalDurableStorage, SystemSendGate]:
    database = LocalD1()
    storage = LocalDurableStorage()
    gate = make_gate(database, storage)
    assert await gate.seed_test_visit("v1", "r1", "2026-09-27", 85, BEFORE_CUTOFF)
    await gate.set_test_observation(82)
    return database, storage, gate


def end_of(database: LocalD1) -> tuple[str, str, str]:
    row = database.connection.execute(
        "SELECT state, stopped_at, delete_after FROM visits WHERE id = 'v1'"
    ).fetchone()
    return tuple(row)


async def assert_send_record_is_saved(
    database: LocalD1,
    storage: LocalDurableStorage,
    gate: SystemSendGate,
    next_tick: str,
) -> None:
    repository = VisitRepository(LocalStore(database))
    assert storage.values["scheduler_ledger_digest"] == (
        await repository.scheduler_ledger_digest()
    )
    result = await gate.scheduled_tick(next_tick)
    assert result["held"] is False
    assert await gate.sending_interrupted() is False


@pytest.mark.asyncio
async def test_a_stop_ends_through_the_end_step(monkeypatch) -> None:
    database, storage, gate = await running_visit()
    ends = EndSteps(monkeypatch, gate)

    assert await gate.stop_visit("v1", BEFORE_CUTOFF) == "stopped"

    assert ends.under_lock == [True]
    assert end_of(database) == (
        "stopped",
        "2026-09-27T13:00:00Z",
        "2026-09-29T13:00:00Z",
    )
    await assert_send_record_is_saved(database, storage, gate, "2026-09-27T13:01:00Z")


@pytest.mark.asyncio
async def test_a_stop_during_a_send_ends_through_the_end_step_once_it_settles(
    monkeypatch,
) -> None:
    database, storage, gate = await running_visit()
    ends = EndSteps(monkeypatch, gate)
    await gate.set_test_line_mode("wait")
    tick = asyncio.create_task(gate.scheduled_tick(BEFORE_CUTOFF))
    await gate.wait_test_request_started()

    assert await gate.stop_visit("v1", BEFORE_CUTOFF) == "stopping"
    assert ends.under_lock == []
    await gate.release_test_request()
    result = await tick

    assert result["held"] is False
    assert ends.under_lock == [True]
    assert end_of(database) == (
        "stopped",
        "2026-09-27T13:00:00Z",
        "2026-09-29T13:00:00Z",
    )
    await assert_send_record_is_saved(database, storage, gate, "2026-09-27T13:01:00Z")


# The scheduler's four day-over call sites, reached by what its clock reads:
# once per visit while preparing the tick, then before the attempt and again
# before the request of each send. Each site gives the tick time, the readings,
# and how many visits the tick reports as expired by the chores and closed while
# preparing; the two send sites report neither.
DAY_OVER_SITES = {
    "lifecycle chores": (AT_CUTOFF, (AT_CUTOFF,), 1, 0),
    "preparing the tick": (BEFORE_CUTOFF, (AT_CUTOFF,), 0, 1),
    "before the attempt": (BEFORE_CUTOFF, (BEFORE_CUTOFF, AT_CUTOFF), 0, 0),
    "before the request": (
        BEFORE_CUTOFF,
        (BEFORE_CUTOFF, BEFORE_CUTOFF, AT_CUTOFF),
        0,
        0,
    ),
}


@pytest.mark.asyncio
@pytest.mark.parametrize("site", DAY_OVER_SITES)
async def test_every_day_over_call_site_ends_through_the_end_step(
    monkeypatch, site: str
) -> None:
    tick_time, readings, expired, closed = DAY_OVER_SITES[site]
    database, storage, gate = await running_visit()
    ends = EndSteps(monkeypatch, gate)
    left = use_clock(gate, *readings)

    result = await gate.scheduled_tick(tick_time)

    # Each reading up to the cutoff was taken, so the named site is the one.
    assert left == [AT_CUTOFF]
    assert result["held"] is False
    assert result["requests_started"] == 0
    assert (result["visits_expired"], result["closed"]) == (expired, closed)
    assert ends.under_lock == [True]
    assert end_of(database) == (
        "expired",
        "2026-09-27T15:59:00Z",
        "2026-09-29T15:59:00Z",
    )
    await assert_send_record_is_saved(database, storage, gate, AFTER_CUTOFF)
