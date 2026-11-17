from datetime import date, datetime, timezone

import pytest

from next_is_you import hospital_registry
from next_is_you.domain import (
    ClinicOption,
    ClinicRoster,
    ClinicScope,
    ClinicSession,
    Hospital,
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


def _scope(hospital: Hospital = Hospital.NTUH_MAIN) -> ClinicScope:
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
    """Reader double; the registry builds a reader type as `type(storage, fetch)`."""

    instances: list["_RecordingReader"] = []

    def __init__(self, storage=None, fetch=None) -> None:
        self.calls: list[tuple[str, Hospital]] = []
        _RecordingReader.instances.append(self)

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


def test_capability_reflects_the_registered_tier() -> None:
    assert capability_of(Hospital.NTUH_MAIN) is SourceCapability.FULL_SCHEDULE
    # No reader exists until #44 evidences a source.
    assert capability_of(Hospital.SHIN_KONG_TAIPEI) is SourceCapability.UNSUPPORTED


def test_registry_declares_supported_departments() -> None:
    from next_is_you.hospital_registry import HOSPITAL_REGISTRY

    ntuh = HOSPITAL_REGISTRY[Hospital.NTUH_MAIN].departments
    assert [(d.code, d.display_name) for d in ntuh] == [("OPH", "眼科")]
    # No reader, so no department is offered.
    assert HOSPITAL_REGISTRY[Hospital.SHIN_KONG_TAIPEI].departments == ()


@pytest.mark.asyncio
async def test_dispatches_by_hospital_and_builds_the_reader_once(monkeypatch) -> None:
    _RecordingReader.instances = []
    monkeypatch.setattr(
        hospital_registry,
        "HOSPITAL_REGISTRY",
        {Hospital.NTUH_MAIN: HospitalEntry("Test General", _RecordingReader)},
    )
    dispatcher = RegistryHospitalReader(ReaderDeps(storage=object(), fetch=object()))

    observed = await dispatcher.observe(_scope(), NOW)
    started = await dispatcher.observe_for_start(_scope(), NOW)
    built = _RecordingReader.instances
    reader = built[0]

    assert isinstance(observed, QueueObservation) and observed.current_number == 7
    assert isinstance(started, QueueObservation) and started.current_number == 9
    # Start reaches the reader's Start method, not its scheduled one.
    assert reader.calls == [
        ("observe", Hospital.NTUH_MAIN),
        ("start", Hospital.NTUH_MAIN),
    ]
    # One adapter is built and reused across reads, not rebuilt each call.
    assert len(built) == 1


@pytest.mark.asyncio
async def test_unsupported_hospital_fails_closed() -> None:
    dispatcher = RegistryHospitalReader(ReaderDeps(storage=object(), fetch=object()))
    scope = _scope(Hospital.SHIN_KONG_TAIPEI)
    unavailable = ReadFailed("unavailable", "no_observation")
    assert await dispatcher.observe(scope, NOW) == unavailable
    assert await dispatcher.observe_for_start(scope, NOW) == unavailable


@pytest.mark.asyncio
async def test_current_number_only_tier_still_reads(monkeypatch) -> None:
    # A hospital that exposes only the current number still produces a read; the
    # setup UI uses the capability tier (#47) to fall back to manual entry.
    class CurrentOnly(_RecordingReader):
        list_clinics = None  # a reader that cannot list a clinic schedule

    monkeypatch.setattr(
        hospital_registry,
        "HOSPITAL_REGISTRY",
        {Hospital.SHIN_KONG_TAIPEI: HospitalEntry("Current Only", CurrentOnly)},
    )
    assert (
        capability_of(Hospital.SHIN_KONG_TAIPEI) is SourceCapability.CURRENT_NUMBER_ONLY
    )
    dispatcher = RegistryHospitalReader(ReaderDeps(storage=object(), fetch=object()))
    observed = await dispatcher.observe(_scope(Hospital.SHIN_KONG_TAIPEI), NOW)
    assert isinstance(observed, QueueObservation)
    # No schedule to list even though the hospital reads: the picker uses manual
    # entry, so the roster is reported unavailable rather than routed.
    roster = await dispatcher.list_clinics(
        RosterQuery(Hospital.SHIN_KONG_TAIPEI, "OPH", date(2026, 9, 27)), NOW
    )
    assert roster == ClinicRoster(False, (), "unsupported")


@pytest.mark.asyncio
async def test_roster_is_routed_to_a_full_schedule_reader(monkeypatch) -> None:
    _RecordingReader.instances = []
    monkeypatch.setattr(
        hospital_registry,
        "HOSPITAL_REGISTRY",
        {Hospital.NTUH_MAIN: HospitalEntry("Test General", _RecordingReader)},
    )
    dispatcher = RegistryHospitalReader(ReaderDeps(storage=object(), fetch=object()))
    roster = await dispatcher.list_clinics(
        RosterQuery(Hospital.NTUH_MAIN, "OPH", date(2026, 9, 27)), NOW
    )
    assert roster.available and len(roster.clinics) == 1
    assert _RecordingReader.instances[0].calls == [("roster", Hospital.NTUH_MAIN)]


@pytest.mark.asyncio
async def test_roster_for_an_unsupported_hospital_is_unavailable() -> None:
    dispatcher = RegistryHospitalReader(ReaderDeps(storage=object(), fetch=object()))
    roster = await dispatcher.list_clinics(
        RosterQuery(Hospital.SHIN_KONG_TAIPEI, "OPH", date(2026, 9, 27)), NOW
    )
    assert roster == ClinicRoster(False, (), "unsupported")


class _NumberOnlyReader:
    """A reader that reads the current number but cannot list a clinic schedule."""

    async def observe(self, scope, now):
        return None

    async def observe_for_start(self, scope, now):
        return None


def test_capability_is_derived_from_the_reader_type() -> None:
    # No reader: unsupported.
    assert HospitalEntry("Retired", None).capability is SourceCapability.UNSUPPORTED
    # A reader that cannot list a clinic schedule: current number only.
    assert (
        HospitalEntry("Number", _NumberOnlyReader).capability
        is SourceCapability.CURRENT_NUMBER_ONLY
    )
    # A reader that can list a clinic schedule: full schedule.
    assert (
        HospitalEntry("Schedule", _RecordingReader).capability
        is SourceCapability.FULL_SCHEDULE
    )


def test_capability_is_not_a_field_anyone_fills_in() -> None:
    with pytest.raises(TypeError):
        HospitalEntry("Declared", None, capability=SourceCapability.FULL_SCHEDULE)  # type: ignore[call-arg]


@pytest.mark.asyncio
async def test_retiring_a_hospital_removes_its_reader_and_reads_fail_closed(
    monkeypatch,
) -> None:
    ntuh = hospital_registry.HOSPITAL_REGISTRY[Hospital.NTUH_MAIN]
    retired = HospitalEntry(
        ntuh.display_name,
        None,
        progress_url=ntuh.progress_url,
        departments=ntuh.departments,
        clinic_code_labels=ntuh.clinic_code_labels,
    )
    monkeypatch.setattr(
        hospital_registry, "HOSPITAL_REGISTRY", {Hospital.NTUH_MAIN: retired}
    )
    assert capability_of(Hospital.NTUH_MAIN) is SourceCapability.UNSUPPORTED
    # The entry is kept, so the name and link still resolve for old visits.
    assert hospital_registry.HOSPITAL_REGISTRY[Hospital.NTUH_MAIN].display_name
    dispatcher = RegistryHospitalReader(ReaderDeps(storage=object(), fetch=object()))
    unavailable = ReadFailed("unavailable", "no_observation")
    assert await dispatcher.observe(_scope(), NOW) == unavailable
    assert await dispatcher.observe_for_start(_scope(), NOW) == unavailable
    assert await dispatcher.list_clinics(
        RosterQuery(Hospital.NTUH_MAIN, "OPH", date(2026, 9, 27)), NOW
    ) == ClinicRoster(False, (), "unsupported")
