from datetime import date, datetime, timezone

import pytest

from next_is_you import hospital_registry
from test_scheduler_outbox import LocalDurableStorage
from next_is_you.domain import (
    ClinicOption,
    ClinicRoster,
    ClinicScope,
    ClinicSession,
    QueueObservation,
    ReadFailed,
    RosterQuery,
    SourceCapability,
)
from next_is_you.hospital_registry import (
    HospitalEntry,
    ReaderDeps,
    RegistryHospitalReader,
    capability_of,
)

NOW = datetime(2026, 9, 27, 6, 0, tzinfo=timezone.utc)


def _scope(hospital: str = "ntuh-main") -> ClinicScope:
    return ClinicScope(
        hospital=hospital,
        visit_date=date(2026, 9, 27),
        department_code="OPH",
        clinic_code="11/Wang/Dr. Appt.",
        session=ClinicSession.AFTERNOON,
        doctor_code="Wang",
        room_code="11",
    )


class _RecordingReader:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def observe(self, scope, now):
        self.calls.append(("observe", scope.hospital))
        return QueueObservation(scope, now.isoformat(), 7, trustworthy_current=True)

    async def observe_for_start(self, scope, now):
        self.calls.append(("start", scope.hospital))
        return QueueObservation(scope, now.isoformat(), 9, trustworthy_current=True)

    async def list_clinics(self, query, now):
        self.calls.append(("roster", query.hospital))
        return ClinicRoster(
            True,
            (
                ClinicOption(
                    ClinicSession.AFTERNOON,
                    "11",
                    "Wang",
                    "Dr. Appt.",
                    "11/Wang/Dr. Appt.",
                ),
            ),
            "ok",
        )


OFFICIAL = "https://hospital.example/progress"


class _CurrentOnlyReader:
    async def observe(self, scope, now):
        return None

    async def observe_for_start(self, scope, now):
        return None


class _FullReader(_CurrentOnlyReader):
    async def list_clinics(self, query, now):
        return ClinicRoster(False, (), "no_observation")


def test_capability_reflects_the_registered_tier() -> None:
    assert capability_of("ntuh-main") is SourceCapability.FULL_SCHEDULE
    # No reader exists until #44 evidences a source.
    assert capability_of("shin-kong-taipei") is SourceCapability.UNSUPPORTED


def test_registry_declares_supported_departments() -> None:
    from next_is_you.hospital_registry import HOSPITAL_REGISTRY

    ntuh = HOSPITAL_REGISTRY["ntuh-main"].departments
    assert [(d.code, d.display_name) for d in ntuh] == [("OPH", "眼科")]
    # No reader, so no department is offered.
    assert HOSPITAL_REGISTRY["shin-kong-taipei"].departments == ()


@pytest.mark.asyncio
async def test_dispatches_by_hospital_and_builds_the_reader_once(monkeypatch) -> None:
    built: list[ReaderDeps] = []
    reader = _RecordingReader()

    def build(deps: ReaderDeps):
        built.append(deps)
        return reader

    monkeypatch.setattr(
        hospital_registry,
        "HOSPITAL_REGISTRY",
        {
            "ntuh-main": HospitalEntry(
                "Test General", _FullReader, OFFICIAL, build_reader=build
            )
        },
    )
    dispatcher = RegistryHospitalReader(ReaderDeps(storage=object(), fetch=object()))

    observed = await dispatcher.observe(_scope(), NOW)
    started = await dispatcher.observe_for_start(_scope(), NOW)

    assert isinstance(observed, QueueObservation) and observed.current_number == 7
    assert isinstance(started, QueueObservation) and started.current_number == 9
    # Start reaches the reader's Start method, not its scheduled one.
    assert reader.calls == [
        ("observe", "ntuh-main"),
        ("start", "ntuh-main"),
    ]
    # One adapter is built and reused across reads, not rebuilt each call.
    assert len(built) == 1


@pytest.mark.asyncio
async def test_unsupported_hospital_fails_closed() -> None:
    dispatcher = RegistryHospitalReader(ReaderDeps(storage=object(), fetch=object()))
    scope = _scope("shin-kong-taipei")
    unavailable = ReadFailed("unavailable", "no_observation")
    assert await dispatcher.observe(scope, NOW) == unavailable
    assert await dispatcher.observe_for_start(scope, NOW) == unavailable


@pytest.mark.asyncio
async def test_current_number_only_tier_still_reads(monkeypatch) -> None:
    # A hospital that exposes only the current number still produces a read; the
    # setup UI uses the capability tier (#47) to fall back to manual entry.
    reader = _RecordingReader()
    monkeypatch.setattr(
        hospital_registry,
        "HOSPITAL_REGISTRY",
        {
            "shin-kong-taipei": HospitalEntry(
                "Current Only",
                _CurrentOnlyReader,
                OFFICIAL,
                build_reader=lambda _deps: reader,
            )
        },
    )
    assert capability_of("shin-kong-taipei") is SourceCapability.CURRENT_NUMBER_ONLY
    dispatcher = RegistryHospitalReader(ReaderDeps(storage=object(), fetch=object()))
    observed = await dispatcher.observe(_scope("shin-kong-taipei"), NOW)
    assert isinstance(observed, QueueObservation)
    # No schedule to list even though the hospital reads: the picker uses manual
    # entry, so the roster is reported unavailable rather than routed.
    roster = await dispatcher.list_clinics(
        RosterQuery("shin-kong-taipei", "OPH", date(2026, 9, 27)), NOW
    )
    assert roster == ClinicRoster(False, (), "unsupported")


@pytest.mark.asyncio
async def test_roster_is_routed_to_a_full_schedule_reader(monkeypatch) -> None:
    reader = _RecordingReader()
    monkeypatch.setattr(
        hospital_registry,
        "HOSPITAL_REGISTRY",
        {
            "ntuh-main": HospitalEntry(
                "Test General",
                _FullReader,
                OFFICIAL,
                build_reader=lambda _deps: reader,
            )
        },
    )
    dispatcher = RegistryHospitalReader(ReaderDeps(storage=object(), fetch=object()))
    roster = await dispatcher.list_clinics(
        RosterQuery("ntuh-main", "OPH", date(2026, 9, 27)), NOW
    )
    assert roster.available and len(roster.clinics) == 1
    assert reader.calls == [("roster", "ntuh-main")]


@pytest.mark.asyncio
async def test_roster_for_an_unsupported_hospital_is_unavailable() -> None:
    dispatcher = RegistryHospitalReader(ReaderDeps(storage=object(), fetch=object()))
    roster = await dispatcher.list_clinics(
        RosterQuery("shin-kong-taipei", "OPH", date(2026, 9, 27)), NOW
    )
    assert roster == ClinicRoster(False, (), "unsupported")


# --- Derived capability (#99) -------------------------------------------------


def test_capability_is_derived_from_the_reader_type() -> None:
    # fixture/mock: no reader means unsupported.
    assert HospitalEntry("A", None, OFFICIAL).capability is SourceCapability.UNSUPPORTED
    # A reader that can list a clinic schedule means full schedule.
    assert (
        HospitalEntry("B", _FullReader, OFFICIAL).capability
        is SourceCapability.FULL_SCHEDULE
    )
    # Otherwise current number only.
    assert (
        HospitalEntry("C", _CurrentOnlyReader, OFFICIAL).capability
        is SourceCapability.CURRENT_NUMBER_ONLY
    )


def test_capability_is_not_a_field_anyone_fills_in() -> None:
    import dataclasses

    names = {f.name for f in dataclasses.fields(HospitalEntry)}
    assert "capability" not in names


def test_capability_is_known_without_building_a_reader() -> None:
    def explode(_deps):
        raise AssertionError("reader must not be built to learn capability")

    entry = HospitalEntry("D", _FullReader, OFFICIAL, build_reader=explode)
    assert entry.capability is SourceCapability.FULL_SCHEDULE


@pytest.mark.asyncio
async def test_retired_hospital_derives_unsupported_and_fails_closed(
    monkeypatch,
) -> None:
    import dataclasses

    from next_is_you.hospital_registry import HOSPITAL_REGISTRY

    retired = dataclasses.replace(
        HOSPITAL_REGISTRY["ntuh-main"], reader_type=None, build_reader=None
    )
    monkeypatch.setattr(hospital_registry, "HOSPITAL_REGISTRY", {"ntuh-main": retired})
    # Entry stays, so the name is still shown; it just derives as unsupported.
    assert retired.display_name == "臺大醫院總院"
    assert capability_of("ntuh-main") is SourceCapability.UNSUPPORTED
    dispatcher = RegistryHospitalReader(ReaderDeps(storage=object(), fetch=object()))
    unavailable = ReadFailed("unavailable", "no_observation")
    assert await dispatcher.observe(_scope(), NOW) == unavailable
    assert await dispatcher.observe_for_start(_scope(), NOW) == unavailable
    roster = await dispatcher.list_clinics(
        RosterQuery("ntuh-main", "OPH", date(2026, 9, 27)), NOW
    )
    assert roster == ClinicRoster(False, (), "unsupported")


# --- Registry contract (#99): every registered hospital must pass -------------

from pathlib import Path  # noqa: E402
import sqlite3  # noqa: E402

_MIGRATIONS = sorted((Path(__file__).resolve().parents[1] / "migrations").glob("*.sql"))


def contract_hospitals() -> list:
    """Every registered hospital, plus the synthetic current-number-only one.

    Each case is (label, hospital id, entry to register or None for the real
    entry). The synthetic hospital has an id of its own, so it is substituted
    into the registry for the test and is never registered for real; storing it
    with a visit proves the database does not enumerate hospitals.
    """
    from synthetic_hospital import SYNTHETIC_ID, synthetic_entry

    cases = [
        pytest.param((hospital, None), id=hospital)
        for hospital in hospital_registry.HOSPITAL_REGISTRY
    ]
    cases.append(
        pytest.param(
            (SYNTHETIC_ID, synthetic_entry()), id="synthetic-current-number-only"
        )
    )
    return cases


def _ntuh_roster_fixture():

    import test_ntuh_reader as t

    now = t._schedule_sim_now()
    queries = [
        RosterQuery("ntuh-main", "OPH", t.SCHEDULE_FIRST_VISIT),
        RosterQuery("ntuh-main", "OPH", now.date()),
    ]
    return (
        lambda: t.FakeSource(t.PAGE, schedule=t.SCHEDULE_FIXTURE),
        queries,
        now,
    )


# hospital id -> () -> (source factory, queries to list, now)
_ROSTER_FIXTURES = {"ntuh-main": _ntuh_roster_fixture}


@pytest.fixture
def hospital(request, monkeypatch):
    hospital_id, entry = request.param
    if entry is not None:
        monkeypatch.setitem(hospital_registry.HOSPITAL_REGISTRY, hospital_id, entry)
    return hospital_id


@pytest.mark.parametrize("hospital", contract_hospitals(), indirect=True)
class TestRegistryContract:
    def test_the_synthetic_hospital_is_current_number_only(self, hospital) -> None:
        from synthetic_hospital import SYNTHETIC_NAME

        entry = hospital_registry.HOSPITAL_REGISTRY[hospital]
        if entry.display_name == SYNTHETIC_NAME:
            assert entry.capability is SourceCapability.CURRENT_NUMBER_ONLY

    def test_capability_derives_from_the_reader_type(self, hospital) -> None:
        entry = hospital_registry.HOSPITAL_REGISTRY[hospital]
        if entry.reader_type is None:
            expected = SourceCapability.UNSUPPORTED
        elif callable(getattr(entry.reader_type, "list_clinics", None)):
            expected = SourceCapability.FULL_SCHEDULE
        else:
            expected = SourceCapability.CURRENT_NUMBER_ONLY
        assert entry.capability is expected
        assert capability_of(hospital) is expected

    def test_supported_hospital_offers_a_department(self, hospital) -> None:
        entry = hospital_registry.HOSPITAL_REGISTRY[hospital]
        if entry.capability is not SourceCapability.UNSUPPORTED:
            assert len(entry.departments) >= 1

    @pytest.mark.asyncio
    async def test_every_clinic_option_has_a_non_empty_label(self, hospital) -> None:
        # Fixture/mock: each full-schedule hospital supplies a fake source
        # and the days to list. A new full-schedule hospital without an entry
        # in `_ROSTER_FIXTURES` fails here, so no dropdown entry can be blank.
        entry = hospital_registry.HOSPITAL_REGISTRY[hospital]
        if entry.capability is not SourceCapability.FULL_SCHEDULE:
            return
        assert hospital in _ROSTER_FIXTURES, "supply a roster fixture"
        make_source, queries, now = _ROSTER_FIXTURES[hospital]()
        reader = entry.make_reader(ReaderDeps(LocalDurableStorage(), make_source()))
        listed = 0
        for query in queries:
            roster = await reader.list_clinics(query, now)
            assert roster.available
            for option in roster.clinics:
                listed += 1
                assert option.label.strip()
        assert listed > 0

    def test_official_link_is_fixed_https(self, hospital) -> None:
        from urllib.parse import urlparse

        entry = hospital_registry.HOSPITAL_REGISTRY[hospital]
        parsed = urlparse(entry.official_link)
        assert parsed.scheme == "https" and parsed.hostname
        assert not parsed.username and not parsed.password

    def test_hospital_id_can_be_stored_with_a_visit(self, hospital) -> None:
        connection = sqlite3.connect(":memory:")
        for migration in _MIGRATIONS:
            connection.executescript(migration.read_text())
        connection.execute(
            "INSERT INTO visits (id, hospital, visit_date, department_code, "
            "clinic_code, clinic_session, patient_number, state, created_at) "
            "VALUES ('v1', ?, '2026-09-27', 'OPH', 'C-1', 'afternoon', 85, "
            "'draft', '2026-09-27T09:00:00Z')",
            (hospital,),
        )
        row = connection.execute("SELECT hospital FROM visits").fetchone()
        assert row == (hospital,)
