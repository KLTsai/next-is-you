"""Daily pre-flight sweep: once per Taipei day, re-check drafts in the window."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Mapping

import pytest

from next_is_you.domain import (
    ClinicMatch,
    ClinicOption,
    ClinicRoster,
    ClinicSession,
    MatchKind,
    MatchQuery,
    RosterQuery,
)
from next_is_you.scheduler import OutboxScheduler
from test_scheduler_outbox import LocalD1

from next_is_you.persistence import (
    CloudflareD1Store,
    VisitRepository,
)


TAIPEI = timezone(timedelta(hours=8))


def taipei(year: int, month: int, day: int, hour: int = 14) -> datetime:
    return datetime(year, month, day, hour, 0, tzinfo=TAIPEI)


class FakeRosterReader:
    """Hospital-reader fake that implements the roster-listing contract.

    Only `match_clinic` is implemented; the sweep needs nothing else. The
    scripted roster is keyed by `(hospital, department, visit_date)` and stands
    for what the hospital's source shows. Like the NTUH reader, the fake reads
    its source once per (hospital, dept, date) group and day however many drafts ask,
    and `calls` counts those source reads.
    """

    def __init__(self, rosters: Mapping[tuple[str, str, str], ClinicRoster]):
        self._rosters = rosters
        self.calls: list[RosterQuery] = []
        self._read_groups: set[tuple[str, ...]] = set()

    async def match_clinic(self, query: MatchQuery, now: datetime) -> ClinicMatch:
        key = (
            query.hospital.value,
            query.department_code,
            query.visit_date.isoformat(),
        )
        read_key = (*key, now.date().isoformat())
        if read_key not in self._read_groups:
            self._read_groups.add(read_key)
            self.calls.append(
                RosterQuery(query.hospital, query.department_code, query.visit_date)
            )
        roster = self._rosters.get(key, ClinicRoster(False, (), "no_observation"))
        if not roster.available:
            if roster.reason == "visit_date_out_of_schedule_window":
                return ClinicMatch(MatchKind.NOT_YET_PUBLISHED)
            return ClinicMatch(MatchKind.UNAVAILABLE, reason=roster.reason)
        room, doctor = query.clinic_code.split("/")[:2]
        found = next(
            (
                option
                for option in roster.clinics
                if option.session == query.session
                and option.room == room
                and option.doctor == doctor
            ),
            None,
        )
        if found is None:
            return ClinicMatch(MatchKind.NOT_SCHEDULED)
        return ClinicMatch(MatchKind.MATCHED, found.clinic_code)


def _draft_match(session: ClinicSession, room: str, doctor: str) -> ClinicRoster:
    option = ClinicOption(
        session=session,
        room=room,
        doctor=doctor,
        clinic_type="角膜",
        clinic_code=f"{room}/{doctor}/角膜",
    )
    return ClinicRoster(True, (option,), "ok")


def _empty_available(session: ClinicSession = ClinicSession.MORNING) -> ClinicRoster:
    # The schedule page returned something, but the doctor-tag we were
    # expecting is not among its live rows. For the sweep this is the
    # "doctor no longer scheduled" case; a 停診 row would have been dropped
    # upstream by the reader filter.
    other = ClinicOption(
        session=session,
        room="99",
        doctor="合成醫師Z",
        clinic_type="角膜",
        clinic_code="99/合成醫師Z/角膜",
    )
    return ClinicRoster(True, (other,), "ok")


async def _repo(database: LocalD1) -> VisitRepository:
    return VisitRepository(CloudflareD1Store(database))


async def _seed_draft(
    repository: VisitRepository,
    *,
    visit_id: str,
    hospital: str = "ntuh-main",
    department: str = "OPH",
    visit_day: date,
    session: str = "morning",
    room: str = "03",
    doctor: str = "合成醫師甲",
    clinic_type: str = "角膜",
    patient_number: int = 42,
    now: datetime,
) -> None:
    await repository.create_draft(
        visit_id=visit_id,
        hospital=hospital,
        visit_day=visit_day,
        department_code=department,
        clinic_code=f"{room}/{doctor}/{clinic_type}",
        clinic_session=session,
        patient_number=patient_number,
        now=now,
    )


async def _source_read(database: LocalD1, visit_id: str) -> tuple[str, str]:
    row = database.connection.execute(
        "SELECT latest_source_read_status, latest_source_read_reason FROM visits WHERE id = ?",
        (visit_id,),
    ).fetchone()
    return str(row[0]), str(row[1])


async def _preflight_date(database: LocalD1, visit_id: str) -> str | None:
    row = database.connection.execute(
        "SELECT preflight_last_checked_date FROM visits WHERE id = ?",
        (visit_id,),
    ).fetchone()
    return None if row[0] is None else str(row[0])


async def _state(database: LocalD1, visit_id: str) -> str:
    row = database.connection.execute(
        "SELECT state FROM visits WHERE id = ?", (visit_id,)
    ).fetchone()
    return str(row[0])


def _scheduler(
    repository: VisitRepository, reader: FakeRosterReader
) -> OutboxScheduler:
    return OutboxScheduler(repository, reader, None, lambda: taipei(2026, 11, 9))


@pytest.mark.asyncio
async def test_sweep_keeps_a_draft_whose_doctor_is_still_scheduled() -> None:
    database = LocalD1()
    repository = await _repo(database)
    now = taipei(2026, 11, 9, 14)
    await _seed_draft(
        repository,
        visit_id="v-ok",
        visit_day=date(2026, 11, 10),
        now=now,
    )
    reader = FakeRosterReader(
        {
            ("ntuh-main", "OPH", "2026-11-10"): _draft_match(
                ClinicSession.MORNING, "03", "合成醫師甲"
            ),
        }
    )
    scheduler = _scheduler(repository, reader)
    plan = await scheduler.prepare_tick(now)
    assert plan.drafts_rechecked == 1
    assert plan.drafts_scope_mismatch == 0
    assert await _state(database, "v-ok") == "draft"
    status, reason = await _source_read(database, "v-ok")
    assert (status, reason) == ("unavailable", "no_observation")
    assert await _preflight_date(database, "v-ok") == "2026-11-09"


@pytest.mark.asyncio
async def test_sweep_flags_a_draft_whose_doctor_is_no_longer_scheduled() -> None:
    database = LocalD1()
    repository = await _repo(database)
    now = taipei(2026, 11, 9, 14)
    await _seed_draft(
        repository,
        visit_id="v-gone",
        visit_day=date(2026, 11, 10),
        now=now,
    )
    reader = FakeRosterReader(
        {
            ("ntuh-main", "OPH", "2026-11-10"): _empty_available(),
        }
    )
    scheduler = _scheduler(repository, reader)
    plan = await scheduler.prepare_tick(now)
    assert plan.drafts_rechecked == 1
    assert plan.drafts_scope_mismatch == 1
    status, reason = await _source_read(database, "v-gone")
    assert (status, reason) == ("scope_mismatch", "scope_mismatch")


@pytest.mark.asyncio
async def test_sweep_flags_a_draft_whose_doctor_is_cancelled_in_schedule() -> None:
    """A 停診 row is dropped upstream by the schedule reader, so the sweep
    sees "doctor not in roster" and marks the draft the same as removal."""
    database = LocalD1()
    repository = await _repo(database)
    now = taipei(2026, 11, 9, 14)
    await _seed_draft(
        repository,
        visit_id="v-cancelled",
        visit_day=date(2026, 11, 10),
        room="07",
        doctor="合成醫師丙",
        now=now,
    )
    # The reader's _list_future_schedule drops `停診`/`颱風停診`, so the
    # fake returns a roster without the cancelled doctor to match that.
    reader = FakeRosterReader(
        {
            ("ntuh-main", "OPH", "2026-11-10"): _empty_available(),
        }
    )
    scheduler = _scheduler(repository, reader)
    plan = await scheduler.prepare_tick(now)
    assert plan.drafts_scope_mismatch == 1
    status, reason = await _source_read(database, "v-cancelled")
    assert (status, reason) == ("scope_mismatch", "scope_mismatch")


@pytest.mark.asyncio
async def test_sweep_is_a_noop_when_schedule_source_fails() -> None:
    database = LocalD1()
    repository = await _repo(database)
    now = taipei(2026, 11, 9, 14)
    await _seed_draft(
        repository,
        visit_id="v-hiccup",
        visit_day=date(2026, 11, 10),
        now=now,
    )
    reader = FakeRosterReader(
        {
            ("ntuh-main", "OPH", "2026-11-10"): ClinicRoster(False, (), "timeout"),
        }
    )
    scheduler = _scheduler(repository, reader)
    plan = await scheduler.prepare_tick(now)
    assert plan.drafts_rechecked == 0
    assert plan.drafts_scope_mismatch == 0
    # The draft is untouched: no scope_mismatch flag, no preflight marker.
    status, reason = await _source_read(database, "v-hiccup")
    assert (status, reason) == ("unavailable", "no_observation")
    assert await _preflight_date(database, "v-hiccup") is None


@pytest.mark.asyncio
async def test_sweep_is_idempotent_within_one_taipei_day() -> None:
    database = LocalD1()
    repository = await _repo(database)
    now = taipei(2026, 11, 9, 14)
    await _seed_draft(
        repository,
        visit_id="v-ok",
        visit_day=date(2026, 11, 10),
        now=now,
    )
    reader = FakeRosterReader(
        {
            ("ntuh-main", "OPH", "2026-11-10"): _draft_match(
                ClinicSession.MORNING, "03", "合成醫師甲"
            ),
        }
    )
    scheduler = _scheduler(repository, reader)
    first = await scheduler.prepare_tick(now)
    assert first.drafts_rechecked == 1
    # A second tick five minutes later finds the draft already flagged as
    # swept today and skips it entirely.
    later = taipei(2026, 11, 9, 14) + timedelta(minutes=5)
    second = await scheduler.prepare_tick(later)
    assert second.drafts_rechecked == 0
    assert len(reader.calls) == 1


@pytest.mark.asyncio
async def test_sweep_runs_again_on_the_next_taipei_day() -> None:
    database = LocalD1()
    repository = await _repo(database)
    today = taipei(2026, 11, 9, 14)
    tomorrow = taipei(2026, 11, 10, 14)
    await _seed_draft(
        repository,
        visit_id="v-ok",
        visit_day=date(2026, 11, 12),
        now=today,
    )
    reader = FakeRosterReader(
        {
            ("ntuh-main", "OPH", "2026-11-12"): _draft_match(
                ClinicSession.MORNING, "03", "合成醫師甲"
            ),
        }
    )
    scheduler = _scheduler(repository, reader)
    await scheduler.prepare_tick(today)
    assert await _preflight_date(database, "v-ok") == "2026-11-09"
    await scheduler.prepare_tick(tomorrow)
    assert await _preflight_date(database, "v-ok") == "2026-11-10"
    assert len(reader.calls) == 2


@pytest.mark.asyncio
async def test_sweep_validates_a_draft_exactly_at_the_window_edge() -> None:
    database = LocalD1()
    repository = await _repo(database)
    now = taipei(2026, 11, 9, 14)
    edge = date(2026, 11, 23)  # today + 14 days
    await _seed_draft(repository, visit_id="v-edge", visit_day=edge, now=now)
    reader = FakeRosterReader(
        {
            ("ntuh-main", "OPH", edge.isoformat()): _draft_match(
                ClinicSession.MORNING, "03", "合成醫師甲"
            ),
        }
    )
    scheduler = _scheduler(repository, reader)
    plan = await scheduler.prepare_tick(now)
    assert plan.drafts_rechecked == 1


@pytest.mark.asyncio
async def test_sweep_ignores_a_draft_beyond_the_window() -> None:
    database = LocalD1()
    repository = await _repo(database)
    now = taipei(2026, 11, 9, 14)
    beyond = date(2026, 11, 24)  # today + 15 days
    await _seed_draft(repository, visit_id="v-far", visit_day=beyond, now=now)
    reader = FakeRosterReader({})
    scheduler = _scheduler(repository, reader)
    plan = await scheduler.prepare_tick(now)
    assert plan.drafts_rechecked == 0
    assert reader.calls == []


@pytest.mark.asyncio
async def test_sweep_ignores_a_draft_whose_visit_date_is_today() -> None:
    """Today's drafts are the Start-time path's responsibility, not the sweep."""
    database = LocalD1()
    repository = await _repo(database)
    now = taipei(2026, 11, 9, 14)
    await _seed_draft(
        repository,
        visit_id="v-today",
        visit_day=date(2026, 11, 9),
        now=now,
    )
    reader = FakeRosterReader({})
    scheduler = _scheduler(repository, reader)
    plan = await scheduler.prepare_tick(now)
    assert plan.drafts_rechecked == 0
    assert reader.calls == []


@pytest.mark.asyncio
async def test_sweep_shares_one_fetch_across_drafts_of_the_same_group() -> None:
    database = LocalD1()
    repository = await _repo(database)
    now = taipei(2026, 11, 9, 14)
    option_a = ClinicOption(
        session=ClinicSession.MORNING,
        room="03",
        doctor="合成醫師甲",
        clinic_type="角膜",
        clinic_code="03/合成醫師甲/角膜",
    )
    option_b = ClinicOption(
        session=ClinicSession.AFTERNOON,
        room="05",
        doctor="合成醫師乙",
        clinic_type="網膜",
        clinic_code="05/合成醫師乙/網膜",
    )
    await _seed_draft(
        repository,
        visit_id="v-a",
        visit_day=date(2026, 11, 10),
        session="morning",
        room="03",
        doctor="合成醫師甲",
        now=now,
    )
    await _seed_draft(
        repository,
        visit_id="v-b",
        visit_day=date(2026, 11, 10),
        session="afternoon",
        room="05",
        doctor="合成醫師乙",
        clinic_type="網膜",
        now=now,
    )
    reader = FakeRosterReader(
        {
            ("ntuh-main", "OPH", "2026-11-10"): ClinicRoster(
                True, (option_a, option_b), "ok"
            ),
        }
    )
    scheduler = _scheduler(repository, reader)
    plan = await scheduler.prepare_tick(now)
    assert plan.drafts_rechecked == 2
    assert plan.drafts_scope_mismatch == 0
    # Both drafts share the same (hospital, dept, date) and therefore ONE fetch.
    assert len(reader.calls) == 1


@pytest.mark.asyncio
async def test_sweep_separates_fetches_across_different_dates() -> None:
    database = LocalD1()
    repository = await _repo(database)
    now = taipei(2026, 11, 9, 14)
    option = ClinicOption(
        session=ClinicSession.MORNING,
        room="03",
        doctor="合成醫師甲",
        clinic_type="角膜",
        clinic_code="03/合成醫師甲/角膜",
    )
    await _seed_draft(
        repository,
        visit_id="v-a",
        visit_day=date(2026, 11, 10),
        now=now,
    )
    await _seed_draft(
        repository,
        visit_id="v-b",
        visit_day=date(2026, 11, 11),
        now=now,
    )
    reader = FakeRosterReader(
        {
            ("ntuh-main", "OPH", "2026-11-10"): ClinicRoster(True, (option,), "ok"),
            ("ntuh-main", "OPH", "2026-11-11"): ClinicRoster(True, (option,), "ok"),
        }
    )
    scheduler = _scheduler(repository, reader)
    plan = await scheduler.prepare_tick(now)
    assert plan.drafts_rechecked == 2
    # Different visit dates → two fetches, one per (hospital, dept, date).
    assert len(reader.calls) == 2
