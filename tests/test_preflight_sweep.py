"""Daily pre-flight sweep: once per Taipei day, re-check drafts in the window."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from typing import Mapping

import pytest

from next_is_you.domain import (
    ClinicMatch,
    ClinicMatchQuery,
    ClinicOption,
    ClinicRoster,
    ClinicSession,
    MatchOutcome,
    RosterQuery,
)
from next_is_you import hospital_registry
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

    Only `match_clinic` is called by the sweep. Like a real reader it answers
    from a scripted roster keyed by `(hospital, department, visit_date)` and
    shares one roster read across matches made with the same clock reading.
    `calls` counts roster reads so the test can prove one sweep shares reads
    per group.
    """

    def __init__(self, rosters: Mapping[tuple[str, str, str], ClinicRoster]):
        self._rosters = rosters
        self.calls: list[RosterQuery] = []
        self._shared: dict[tuple[str, str, str, datetime], ClinicRoster] = {}

    async def match_clinic(self, query: ClinicMatchQuery, now: datetime) -> ClinicMatch:
        group = (
            query.hospital,
            query.department_code,
            query.visit_date.isoformat(),
            now,
        )
        roster = self._shared.get(group)
        if roster is None:
            roster = await self.list_clinics(
                RosterQuery(query.hospital, query.department_code, query.visit_date),
                now,
            )
            self._shared[group] = roster
        if roster.reason == "visit_date_out_of_schedule_window":
            return ClinicMatch(MatchOutcome.NOT_YET_PUBLISHED)
        if not roster.available:
            return ClinicMatch(MatchOutcome.UNAVAILABLE, reason=roster.reason)
        room, doctor, _ = query.clinic_code.split("/")
        for option in roster.clinics:
            if (
                option.session == query.session
                and option.room == room
                and option.doctor == doctor
            ):
                return ClinicMatch(MatchOutcome.MATCHED, clinic_code=option.clinic_code)
        return ClinicMatch(MatchOutcome.NOT_SCHEDULED)

    async def list_clinics(self, query: RosterQuery, now: datetime) -> ClinicRoster:
        self.calls.append(query)
        key = (
            query.hospital,
            query.department_code,
            query.visit_date.isoformat(),
        )
        if key not in self._rosters:
            return ClinicRoster(False, (), "no_observation")
        return self._rosters[key]


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


_UNPUBLISHED = ClinicRoster(False, (), "visit_date_out_of_schedule_window")


@pytest.mark.asyncio
async def test_sweep_skips_an_unpublished_day_then_checks_it_once_published() -> None:
    """Fixture/mock: today + 20 days, through the scheduler tick."""
    database = LocalD1()
    repository = await _repo(database)
    day_one = taipei(2026, 11, 9, 14)
    far = date(2026, 11, 29)  # today + 20 days
    await _seed_draft(repository, visit_id="v-far", visit_day=far, now=day_one)
    rosters: dict[tuple[str, str, str], ClinicRoster] = {
        ("ntuh-main", "OPH", far.isoformat()): _UNPUBLISHED,
    }
    reader = FakeRosterReader(rosters)
    scheduler = _scheduler(repository, reader)

    first = await scheduler.prepare_tick(day_one)
    assert first.drafts_scope_mismatch == 0
    # Not flagged: source-read status untouched, but marked checked today.
    assert await _source_read(database, "v-far") == ("unavailable", "no_observation")
    assert await _preflight_date(database, "v-far") == "2026-11-09"

    # Same day again: already checked, no second read.
    await scheduler.prepare_tick(day_one + timedelta(minutes=5))
    assert len(reader.calls) == 1

    # The hospital publishes the day; the next Taipei day's sweep matches it.
    rosters[("ntuh-main", "OPH", far.isoformat())] = _draft_match(
        ClinicSession.MORNING, "03", "合成醫師甲"
    )
    day_two = taipei(2026, 11, 10, 14)
    second = await scheduler.prepare_tick(day_two)
    assert second.drafts_rechecked == 1
    assert second.drafts_scope_mismatch == 0
    assert await _preflight_date(database, "v-far") == "2026-11-10"


@pytest.mark.asyncio
async def test_sweep_flags_a_published_day_without_the_doctor() -> None:
    database = LocalD1()
    repository = await _repo(database)
    now = taipei(2026, 11, 9, 14)
    far = date(2026, 12, 20)  # far beyond any fixed range
    await _seed_draft(repository, visit_id="v-far", visit_day=far, now=now)
    reader = FakeRosterReader(
        {("ntuh-main", "OPH", far.isoformat()): _empty_available()}
    )
    plan = await _scheduler(repository, reader).prepare_tick(now)
    assert plan.drafts_scope_mismatch == 1
    assert await _source_read(database, "v-far") == ("scope_mismatch", "scope_mismatch")


@pytest.mark.asyncio
async def test_sweep_leaves_a_hospital_without_a_clinic_schedule_alone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class CurrentNumberOnly:
        def __init__(self, storage, fetch) -> None:
            pass

    entry = hospital_registry.HOSPITAL_REGISTRY["ntuh-main"]
    monkeypatch.setattr(
        hospital_registry,
        "HOSPITAL_REGISTRY",
        {"ntuh-main": replace(entry, reader_type=CurrentNumberOnly)},
    )
    database = LocalD1()
    repository = await _repo(database)
    now = taipei(2026, 11, 9, 14)
    await _seed_draft(
        repository, visit_id="v-cn", visit_day=date(2026, 11, 20), now=now
    )
    reader = FakeRosterReader({})
    plan = await _scheduler(repository, reader).prepare_tick(now)
    assert plan.drafts_rechecked == 0
    assert reader.calls == []
    assert await _preflight_date(database, "v-cn") is None


def test_no_sweep_query_or_rule_names_a_day_count() -> None:
    """Static check: the sweep source carries no fixed day range."""
    import inspect
    import re

    for fn in (
        VisitRepository.drafts_due_for_preflight_sweep,
        OutboxScheduler._preflight_sweep,
    ):
        source = inspect.getsource(fn)
        assert not re.search(r"timedelta\(days=\s*\d{2,}", source)
        assert not re.search(r"\b14\b", source)


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
