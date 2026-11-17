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
        ("scope_mismatch", "scope_mismatch"),
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
