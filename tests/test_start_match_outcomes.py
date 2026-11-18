"""Start through the send gate, real registry, fake hospital transport.

Fixture/mock evidence: one test per way a hospital's reader can answer "does this
draft match the clinic schedule", asserting what the organizer observes (the Start
result), the stored source-read status, and that no outbound event was created.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from test_ntuh_reader import (
    PAGE,
    SCHEDULE_FIRST_VISIT,
    SCHEDULE_FIXTURE,
    FakeSource,
    _PREFLIGHT_SIM_SOURCE_DATE,
    _preflight_now,
    counts,
    gate_with_visit,
    seed_ntuh_at,
)

# outcome -> (draft clinic code, days after the simulated today or None for the
# first fixture day, schedule page served, expected Start result, stored read)
OUTCOMES = {
    "matched": (
        "03/合成醫師甲/角膜",
        None,
        True,
        {"state": "active"},
        ("unavailable", "no_observation"),
    ),
    "not_scheduled": (
        "99/陌生醫師/角膜",
        None,
        True,
        {"error": "doctor_not_scheduled"},
        ("scope_mismatch", "scope_mismatch"),
    ),
    "cancelled": (
        "07/合成醫師丙/教學門診",
        None,
        True,
        {"error": "doctor_not_scheduled"},
        ("scope_mismatch", "scope_mismatch"),
    ),
    "not_yet_published": (
        "03/合成醫師甲/角膜",
        20,
        True,
        {
            "error": "visit_date_out_of_schedule_window",
            "schedule_end": "2026-11-23",
            "release_time": "2026-11-15T00:00:00+08:00",
        },
        # Ticket #101: the refused draft is kept unchanged, so the status stays
        # what a fresh draft carries.
        ("unavailable", "no_observation"),
    ),
    "unavailable": (
        "03/合成醫師甲/角膜",
        None,
        False,
        {"error": "schedule_unavailable"},
        ("unavailable", "schema_drift"),
    ),
}


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", list(OUTCOMES))
async def test_start_reports_each_clinic_match_outcome(outcome: str) -> None:
    code, days_ahead, has_schedule, expected, stored = OUTCOMES[outcome]
    source = FakeSource(schedule=SCHEDULE_FIXTURE) if has_schedule else FakeSource(PAGE)
    database, gate = await gate_with_visit(source)
    visit_day = (
        SCHEDULE_FIRST_VISIT
        if days_ahead is None
        else _PREFLIGHT_SIM_SOURCE_DATE + timedelta(days=days_ahead)
    )
    await seed_ntuh_at(
        database, gate, "v", visit_day, clinic_code=code, session="morning"
    )

    result = await gate.start_visit("v", _preflight_now().isoformat())

    assert result == expected
    if outcome == "not_yet_published":
        # The reader refuses the day without contacting the hospital.
        assert source.urls == []
    assert counts(database, "v")[:2] == stored
    events = database.connection.execute("SELECT COUNT(*) FROM outbound_events")
    assert events.fetchone()[0] == 0


def _every_clinic_cancelled(page: str) -> str:
    """The schedule fixture with every card marked as a typhoon cancellation."""
    import re

    without_tags = re.sub(r'<div class="tag">.*?</div></div>', "", page)
    return without_tags.replace(
        '<div class="sub-spec"',
        '<div class="tag"><div class="first-reg">颱風停診</div></div>\n'
        '<div class="sub-spec"',
    )


@pytest.mark.asyncio
async def test_start_says_not_scheduled_when_the_hospital_cancelled_every_clinic() -> (
    None
):
    """#98 behavior change: a fully cancelled day is "not scheduled", not
    "schedule unavailable", so the organizer is not told to retry (fixture/mock)."""
    source = FakeSource(schedule=_every_clinic_cancelled(SCHEDULE_FIXTURE))
    database, gate = await gate_with_visit(source)
    await seed_ntuh_at(
        database,
        gate,
        "v",
        SCHEDULE_FIRST_VISIT,
        clinic_code="03/合成醫師甲/角膜",
        session="morning",
    )

    result = await gate.start_visit("v", _preflight_now().isoformat())

    assert result == {"error": "doctor_not_scheduled"}
    assert counts(database, "v")[:2] == ("scope_mismatch", "scope_mismatch")
    events = database.connection.execute("SELECT COUNT(*) FROM outbound_events")
    assert events.fetchone()[0] == 0


@pytest.mark.asyncio
async def test_start_refuses_an_unparseable_clinic_code_without_asking_the_hospital() -> (
    None
):
    """#98 behavior change: a malformed code is refused before any read, and the
    draft keeps its code (fixture/mock). Wording and early detection: #110."""
    source = FakeSource(schedule=SCHEDULE_FIXTURE)
    database, gate = await gate_with_visit(source)
    await seed_ntuh_at(
        database,
        gate,
        "v",
        SCHEDULE_FIRST_VISIT,
        clinic_code="not a clinic code",
        session="morning",
    )

    result = await gate.start_visit("v", _preflight_now().isoformat())

    assert result == {"error": "observation_invalid"}
    assert source.urls == []
    stored = database.connection.execute(
        "SELECT clinic_code, state FROM visits WHERE id = 'v'"
    ).fetchone()
    assert tuple(stored) == ("not a clinic code", "draft")
    events = database.connection.execute("SELECT COUNT(*) FROM outbound_events")
    assert events.fetchone()[0] == 0
