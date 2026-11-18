"""A hospital that publishes only the current number, end to end (#104).

Fixture/mock evidence: the send gate and scheduler tick run with the real
registry dispatch, a synthetic current-number-only hospital substituted into the
registry, and a scripted fake hospital transport. Each test asserts what the
organizer observes (the Start result), the stored draft, whether an outbound
event exists, and whether a request reached the fake hospital.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from next_is_you import hospital_registry
from next_is_you.persistence import CloudflareD1Store, Statement, VisitRepository
from next_is_you.scheduler import OutboxScheduler
from synthetic_hospital import (
    SYNTHETIC_ID,
    SyntheticSource,
    synthetic_entry,
)
from test_ntuh_reader import LocalDurableStorage, gate_with_visit
from test_scheduler_outbox import LocalD1

TAIPEI = timezone(timedelta(hours=8))
TODAY = date(2026, 11, 17)
NOW = datetime(2026, 11, 17, 14, 0, tzinfo=TAIPEI)
CLINIC = "A-12"


@pytest.fixture(autouse=True)
def synthetic_hospital(monkeypatch):
    monkeypatch.setitem(
        hospital_registry.HOSPITAL_REGISTRY, SYNTHETIC_ID, synthetic_entry()
    )


async def seed(database, visit_day: date, visit_id: str = "v") -> VisitRepository:
    store = CloudflareD1Store(database)
    await store.execute(
        Statement(
            """INSERT OR IGNORE INTO recipients (id, line_subject, display_name,
            consented_at, friendship_checked_at, active, created_at) VALUES
            ('r1', 'U' || lower(hex(zeroblob(16))), 'Synthetic one', ?, ?, 1, ?)""",
            (NOW.isoformat(),) * 3,
        )
    )
    repository = VisitRepository(store)
    await repository.create_draft(
        visit_id=visit_id,
        hospital=SYNTHETIC_ID,
        visit_day=visit_day,
        department_code="OPH",
        clinic_code=CLINIC,
        clinic_session="morning",
        patient_number=28,
        now=NOW,
    )
    assert await repository.add_recipient(visit_id, "r1", NOW)
    return repository


def row(database, visit_id: str = "v"):
    return tuple(
        database.connection.execute(
            "SELECT state, clinic_code, clinic_session, patient_number, visit_date,"
            " latest_source_read_status, latest_source_read_reason,"
            " preflight_last_checked_date"
            " FROM visits WHERE id = ?",
            (visit_id,),
        ).fetchone()
    )


def draft_contents(database):
    return row(database)[:5]


def event_count(database) -> int:
    return database.connection.execute(
        "SELECT COUNT(*) FROM outbound_events"
    ).fetchone()[0]


@pytest.mark.asyncio
async def test_start_before_the_visit_day_is_refused_with_the_visit_date() -> None:
    source = SyntheticSource()
    database, gate = await gate_with_visit(source)
    await seed(database, TODAY + timedelta(days=3))
    before = row(database)

    result = await gate.start_visit("v", NOW.isoformat())

    assert result == {"error": "start_on_visit_day_only", "visit_date": "2026-11-20"}
    assert row(database) == before
    assert event_count(database) == 0
    assert source.requests == []


@pytest.mark.asyncio
async def test_start_on_the_visit_day_is_admitted_when_the_hospital_confirms() -> None:
    source = SyntheticSource(7)
    database, gate = await gate_with_visit(source)
    await seed(database, TODAY)

    result = await gate.start_visit("v", NOW.isoformat())

    assert result == {"state": "active"}
    assert row(database)[0] == "active"
    assert source.requests == [CLINIC]


@pytest.mark.asyncio
async def test_start_on_the_visit_day_says_the_hospital_cannot_find_the_clinic() -> (
    None
):
    source = SyntheticSource(None)
    database, gate = await gate_with_visit(source)
    await seed(database, TODAY)
    before = draft_contents(database)

    result = await gate.start_visit("v", NOW.isoformat())

    assert result == {"error": "hospital_cannot_find_clinic"}
    assert draft_contents(database) == before
    assert event_count(database) == 0


@pytest.mark.asyncio
async def test_start_on_the_visit_day_says_the_hospital_page_is_unreachable() -> None:
    source = SyntheticSource(TimeoutError())
    database, gate = await gate_with_visit(source)
    await seed(database, TODAY)
    before = draft_contents(database)

    result = await gate.start_visit("v", NOW.isoformat())

    assert result == {"error": "hospital_page_unreachable"}
    assert draft_contents(database) == before
    assert event_count(database) == 0


@pytest.mark.asyncio
async def test_the_daily_sweep_leaves_current_number_only_drafts_unflagged() -> None:
    database = LocalD1()
    repository = await seed(database, TODAY + timedelta(days=3))
    before = row(database)
    source = SyntheticSource()
    reader = hospital_registry.RegistryHospitalReader(
        hospital_registry.ReaderDeps(storage=LocalDurableStorage(), fetch=source)
    )
    scheduler = OutboxScheduler(repository, reader, None, lambda: NOW)

    await scheduler.prepare_tick(NOW)

    # Not flagged and nothing read; only the sweep's own bookkeeping date moves,
    # so these drafts are not re-fetched on every later tick of the same day.
    after = row(database)
    assert after[:-1] == before[:-1]
    assert after[-1] == TODAY.isoformat()
    assert source.requests == []
    assert await repository.drafts_due_for_preflight_sweep(TODAY) == []


def test_current_number_only_error_maps_only_the_clinic_not_open_skips() -> None:
    from next_is_you.domain import ReadFailed, ReadSkipped
    from next_is_you.send_gate import _current_number_only_error

    for reason in ("clinic_not_started", "clinic_ended"):
        assert (
            _current_number_only_error(ReadSkipped(reason))
            == "hospital_cannot_find_clinic"
        )
    # A skip that says nothing about the clinic is not "cannot find the clinic".
    assert _current_number_only_error(ReadSkipped("not_due")) == (
        "hospital_page_unreachable"
    )
    # An unmapped failure status must not raise.
    assert _current_number_only_error(ReadFailed("weird", "x")) == (
        "observation_unavailable"
    )


@pytest.mark.asyncio
async def test_the_registry_answers_not_applicable_for_a_hospital_without_a_schedule():
    from next_is_you.domain import ClinicSession, MatchKind, MatchQuery

    reader = hospital_registry.RegistryHospitalReader(
        hospital_registry.ReaderDeps(
            storage=LocalDurableStorage(), fetch=SyntheticSource()
        )
    )
    query = MatchQuery(
        SYNTHETIC_ID, "OPH", TODAY + timedelta(days=3), ClinicSession.MORNING, CLINIC
    )
    match = await reader.match_clinic(query, NOW)
    assert match.kind is MatchKind.NOT_APPLICABLE
    assert match.kind is not MatchKind.UNAVAILABLE


@pytest.mark.asyncio
async def test_the_sweep_needs_no_registry_entry_to_skip_a_not_applicable_draft():
    from next_is_you.domain import ClinicMatch, MatchKind

    class Matcher:
        async def match_clinic(self, query, now):
            return ClinicMatch(MatchKind.NOT_APPLICABLE)

    database = LocalD1()
    repository = await seed(database, TODAY + timedelta(days=3))
    # An unregistered hospital id: only the reader's answer may decide.
    database.connection.execute("PRAGMA foreign_keys = OFF")
    database.connection.execute("UPDATE visits SET hospital = 'unregistered-x'")
    scheduler = OutboxScheduler(repository, Matcher(), None, lambda: NOW)

    await scheduler.prepare_tick(NOW)

    status = row(database)[5:7]
    assert status[0] != "scope_mismatch"
    assert await repository.drafts_due_for_preflight_sweep(TODAY) == []


@pytest.mark.asyncio
async def test_stop_after_start_behaves_as_it_does_for_any_hospital() -> None:
    """Outcome-table row "Stop after Start: unchanged" (#45, #104)."""
    source = SyntheticSource(7)
    database, gate = await gate_with_visit(source)
    await seed(database, TODAY)
    assert await gate.start_visit("v", NOW.isoformat()) == {"state": "active"}
    requests_after_start = list(source.requests)

    stopped = await gate.stop_visit("v", NOW.isoformat())

    assert stopped == "stopped"
    assert row(database)[0] == "stopped"
    # Stopping reads nothing from the hospital and messages nobody.
    assert source.requests == requests_after_start
    assert event_count(database) == 0
    # Stop is idempotent, as for every hospital.
    assert await gate.stop_visit("v", NOW.isoformat()) == "stopped"
