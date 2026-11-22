"""Start allows one running visit at a time (#172).

Fixture/mock evidence: the real send gate and registry over a local database
and a fake hospital transport. Each test asserts what the organizer observes
(the Start result), the stored visit state, and that the refused draft got no
alarm and no source read.
"""

from __future__ import annotations

import asyncio

import pytest

from test_ntuh_reader import (
    SCHEDULE_FIRST_VISIT,
    SCHEDULE_FIXTURE,
    SCHEDULE_SECOND_VISIT,
    FakeSource,
    _preflight_now,
    counts,
    gate_with_visit,
    seed_ntuh_at,
)

DRAFT_CLINIC = "03/合成醫師甲/角膜"
RUNNING_CLINIC = "07/合成醫師丙/教學門診"
REFUSED = {"error": "another_visit_running"}


def _set_state(database, visit_id: str, state: str) -> None:
    database.connection.execute(
        "UPDATE visits SET state = ? WHERE id = ?", (state, visit_id)
    )
    database.connection.commit()


def _state(database, visit_id: str) -> str:
    row = database.connection.execute(
        "SELECT state FROM visits WHERE id = ?", (visit_id,)
    ).fetchone()
    return row[0]


async def _two_visits(running_day=SCHEDULE_FIRST_VISIT):
    source = FakeSource(schedule=SCHEDULE_FIXTURE)
    database, gate = await gate_with_visit(source)
    await seed_ntuh_at(
        database,
        gate,
        "running",
        running_day,
        clinic_code=RUNNING_CLINIC,
        session="morning",
        patient=5,
    )
    await seed_ntuh_at(
        database,
        gate,
        "draft",
        SCHEDULE_FIRST_VISIT,
        clinic_code=DRAFT_CLINIC,
        session="morning",
        patient=6,
    )
    return source, database, gate


@pytest.mark.asyncio
@pytest.mark.parametrize("running_state", ["active", "stopping"])
async def test_start_is_refused_while_another_visit_is_running(running_state):
    source, database, gate = await _two_visits()
    _set_state(database, "running", running_state)
    before = counts(database, "draft")

    result = await gate.start_visit("draft", _preflight_now().isoformat())

    assert result == REFUSED
    assert _state(database, "draft") == "draft"
    assert counts(database, "draft") == before
    assert source.urls == []
    assert await gate.ctx.storage.getAlarm() is None


@pytest.mark.asyncio
async def test_start_is_refused_when_the_running_visit_is_dated_another_day():
    _, database, gate = await _two_visits(running_day=SCHEDULE_SECOND_VISIT)
    _set_state(database, "running", "active")

    result = await gate.start_visit("draft", _preflight_now().isoformat())

    assert result == REFUSED
    assert _state(database, "draft") == "draft"


@pytest.mark.asyncio
async def test_start_succeeds_after_the_running_visit_is_stopped():
    _, database, gate = await _two_visits()
    _set_state(database, "running", "active")
    now = _preflight_now().isoformat()
    assert await gate.start_visit("draft", now) == REFUSED

    _set_state(database, "running", "stopped")
    result = await gate.start_visit("draft", now)

    assert result == {"state": "active"}
    assert _state(database, "draft") == "active"


@pytest.mark.asyncio
async def test_two_starts_at_the_same_moment_leave_one_active_visit():
    _, database, gate = await _two_visits()
    now = _preflight_now().isoformat()

    results = await asyncio.gather(
        gate.start_visit("draft", now), gate.start_visit("running", now)
    )

    assert sorted(map(str, results)) == sorted([str({"state": "active"}), str(REFUSED)])
    rows = database.connection.execute(
        "SELECT COUNT(*) FROM visits WHERE state = 'active'"
    ).fetchone()
    assert rows[0] == 1
