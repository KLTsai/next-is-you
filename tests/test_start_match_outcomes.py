"""Start pre-flight through the send gate for each clinic match outcome.

The real registry and the real NTUH reader answer; only the hospital transport
is a scripted fake. Evidence is fixture/mock: nothing here contacts a hospital.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from test_ntuh_reader import (
    PAGE,
    SCHEDULE_FIRST_VISIT,
    SCHEDULE_FIXTURE,
    SCHEDULE_SECOND_VISIT,
    FakeSource,
    _preflight_now,
    counts,
    gate_with_visit,
    seed_ntuh_at,
)


async def _start(source: FakeSource, visit_day, clinic_code: str, session: str):
    database, gate = await gate_with_visit(source)
    repository = await seed_ntuh_at(
        database, gate, "v1", visit_day, clinic_code=clinic_code, session=session
    )
    result = await gate.start_visit("v1", _preflight_now().isoformat())
    visit = await repository.get_visit("v1")
    return result, visit, counts(database, "v1")[:2]


@pytest.mark.asyncio
async def test_matched_clinic_starts_and_records_no_attention_signal() -> None:
    source = FakeSource(schedule=SCHEDULE_FIXTURE)
    result, visit, stored = await _start(
        source, SCHEDULE_FIRST_VISIT, "03/合成醫師甲/角膜", "morning"
    )
    assert result == {"state": "active"}
    assert visit["state"] == "active"
    assert stored == ("unavailable", "no_observation")


@pytest.mark.asyncio
async def test_clinic_not_on_the_schedule_is_refused_and_flagged() -> None:
    source = FakeSource(schedule=SCHEDULE_FIXTURE)
    result, visit, stored = await _start(
        source, SCHEDULE_FIRST_VISIT, "99/陌生醫師/角膜", "morning"
    )
    assert result == {"error": "doctor_not_scheduled"}
    assert visit["state"] == "draft"
    assert stored == ("scope_mismatch", "scope_mismatch")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("visit_day", "clinic_code"),
    [
        (SCHEDULE_FIRST_VISIT, "07/合成醫師丙/角膜"),  # 停診
        (SCHEDULE_SECOND_VISIT, "06/合成醫師己/角膜"),  # 颱風停診
    ],
)
async def test_clinic_cancelled_by_the_hospital_is_refused_and_flagged(
    visit_day, clinic_code
) -> None:
    source = FakeSource(schedule=SCHEDULE_FIXTURE)
    result, visit, stored = await _start(source, visit_day, clinic_code, "morning")
    assert result == {"error": "doctor_not_scheduled"}
    assert visit["state"] == "draft"
    assert stored == ("scope_mismatch", "scope_mismatch")


@pytest.mark.asyncio
async def test_day_not_yet_published_is_refused_without_contacting_the_hospital() -> (
    None
):
    source = FakeSource(schedule=SCHEDULE_FIXTURE)
    beyond = SCHEDULE_FIRST_VISIT + timedelta(days=20)
    result, visit, stored = await _start(
        source, beyond, "03/合成醫師甲/角膜", "morning"
    )
    # Preflight "today" is 11/9; the end date is today plus 14 days, and the
    # day's release time is midnight Taipei 14 days before it.
    assert result == {
        "error": "visit_date_out_of_schedule_window",
        "schedule_end_date": "2026-11-23",
        "release_time": f"{(beyond - timedelta(days=14)).isoformat()}T00:00:00+08:00",
    }
    assert visit["state"] == "draft"
    assert stored == ("scope_mismatch", "scope_mismatch")
    assert source.requests == []


@pytest.mark.asyncio
async def test_refused_start_keeps_the_draft_and_creates_no_outbound_event() -> None:
    source = FakeSource(schedule=SCHEDULE_FIXTURE)
    database, gate = await gate_with_visit(source)
    beyond = SCHEDULE_FIRST_VISIT + timedelta(days=20)
    repository = await seed_ntuh_at(database, gate, "v1", beyond)
    before = await repository.get_visit("v1")
    result = await gate.start_visit("v1", _preflight_now().isoformat())
    assert result["error"] == "visit_date_out_of_schedule_window"
    after = await repository.get_visit("v1")
    for field in (
        "state",
        "visit_day",
        "department_code",
        "clinic_code",
        "clinic_session",
        "patient_number",
    ):
        assert after.get(field) == before.get(field)
    events = database.connection.execute(
        "SELECT COUNT(*) FROM outbound_events"
    ).fetchone()[0]
    assert events == 0
    assert source.requests == []


@pytest.mark.asyncio
async def test_unreadable_schedule_is_refused_with_the_source_reason() -> None:
    # The fake serves no schedule page, so the read fails closed as schema drift.
    source = FakeSource(PAGE)
    result, visit, stored = await _start(
        source, SCHEDULE_FIRST_VISIT, "03/合成醫師甲/角膜", "morning"
    )
    assert result == {"error": "schedule_unavailable"}
    assert visit["state"] == "draft"
    assert stored == ("unavailable", "schema_drift")
