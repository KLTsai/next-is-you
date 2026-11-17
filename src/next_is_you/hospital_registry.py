"""The one place that knows which hospitals exist and how to read each.

Adding a hospital is a module plus one entry here; no other part of the system
names a concrete hospital. `RegistryHospitalReader` is the single
`HospitalReader` the scheduler and Start are given: it looks up `scope.hospital`
and delegates to that hospital's reader. A hospital with no reader (none built
yet, or `UNSUPPORTED`) fails closed to an unavailable read, which the existing
Start and scheduler paths already handle.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping

from next_is_you.domain import (
    ClinicMatch,
    ClinicMatchQuery,
    ClinicRoster,
    ClinicScope,
    Hospital,
    HospitalReader,
    MatchOutcome,
    QueueObservation,
    ReadFailed,
    ReadSkipped,
    RosterQuery,
    SourceCapability,
    SupportedDepartment,
)
from next_is_you.ntuh_reader import SUPPORTED_DEPARTMENT, Fetcher, NtuhProgressReader


@dataclass(frozen=True, slots=True)
class ReaderDeps:
    """Runtime dependencies a hospital reader is built from.

    `storage` is the Durable Object storage the reader keeps its transient
    per-clinic state in; `fetch` is the transport it reads its source through.
    The caller owns both, so transport and test doubles stay out of the registry.
    """

    storage: Any
    fetch: Fetcher


@dataclass(frozen=True, slots=True)
class HospitalEntry:
    """What the system knows about one hospital, independent of transport.

    The entry names the reader *type*, not an instance, so what a hospital can do
    is known without building a reader or touching transport. `capability` is
    derived from that type and is never filled in by hand: no reader is
    unsupported, a reader that can list a clinic schedule is full schedule, any
    other reader is current number only. Retiring a hospital keeps its entry and
    sets `reader_type` to `None`; it then derives as unsupported and reads fail
    closed. A reader type is constructed as `reader_type(storage, fetch)`.

    `display_name`, `capability` and `progress_url` are what the setup UI reads,
    so the frontend carries no hospital names or source assumptions of its own.
    `progress_url` is the fixed, server-owned, HTTPS-only official progress page
    link (NIY-016); it is never taken from a caller.
    """

    display_name: str
    reader_type: type[HospitalReader] | None
    progress_url: str | None = None
    # Departments the setup picker may offer; empty when none are supported yet.
    departments: tuple[SupportedDepartment, ...] = ()
    # Labels for the manual clinic-code parts, so the setup form can show a parse
    # preview without hard-coding any hospital's format. Empty = freeform.
    clinic_code_labels: tuple[str, ...] = ()

    @property
    def capability(self) -> SourceCapability:
        if self.reader_type is None:
            return SourceCapability.UNSUPPORTED
        if callable(getattr(self.reader_type, "list_clinics", None)):
            return SourceCapability.FULL_SCHEDULE
        return SourceCapability.CURRENT_NUMBER_ONLY


HOSPITAL_REGISTRY: Mapping[Hospital, HospitalEntry] = {
    Hospital.NTUH_MAIN: HospitalEntry(
        display_name="臺大醫院總院",
        reader_type=NtuhProgressReader,
        progress_url=(
            "https://registration.ntuh.gov.tw/WebReg/WebReg/"
            "ClinicCurrentLightNo?vHospCode=T0"
        ),
        # Only ophthalmology is evidenced today; mirrors ntuh_reader's scope.
        departments=(SupportedDepartment(SUPPORTED_DEPARTMENT, "眼科"),),
        clinic_code_labels=("診間", "醫師", "門診別"),
    ),
    # No reader until Issue #44 evidences a usable Shin Kong source; until then
    # it is offered to no one and reads fail closed.
    Hospital.SHIN_KONG_TAIPEI: HospitalEntry(
        display_name="新光醫院（台北）",
        reader_type=None,
        progress_url="https://reg.skh.org.tw/",
    ),
}


def capability_of(hospital: Hospital) -> SourceCapability:
    """What a hospital's source exposes, defaulting to unsupported if unknown."""
    entry = HOSPITAL_REGISTRY.get(hospital)
    return entry.capability if entry is not None else SourceCapability.UNSUPPORTED


class RegistryHospitalReader:
    """Dispatch each read to the reader registered for `scope.hospital`."""

    def __init__(self, deps: ReaderDeps) -> None:
        self._deps = deps
        self._readers: dict[Hospital, HospitalReader] = {}

    async def observe(
        self, scope: ClinicScope, now: datetime
    ) -> QueueObservation | ReadSkipped | ReadFailed | None:
        reader = self._reader_for(scope.hospital)
        if reader is None:
            return ReadFailed("unavailable", "no_observation")
        return await reader.observe(scope, now)

    async def observe_for_start(
        self, scope: ClinicScope, now: datetime
    ) -> QueueObservation | ReadSkipped | ReadFailed | None:
        reader = self._reader_for(scope.hospital)
        if reader is None:
            return ReadFailed("unavailable", "no_observation")
        return await reader.observe_for_start(scope, now)

    async def list_clinics(self, query: RosterQuery, now: datetime) -> ClinicRoster:
        if capability_of(query.hospital) is not SourceCapability.FULL_SCHEDULE:
            return ClinicRoster(False, (), "unsupported")
        reader = self._reader_for(query.hospital)
        lister = getattr(reader, "list_clinics", None)
        if lister is None:
            return ClinicRoster(False, (), "no_observation")
        return await lister(query, now)

    async def match_clinic(self, query: ClinicMatchQuery, now: datetime) -> ClinicMatch:
        if capability_of(query.hospital) is not SourceCapability.FULL_SCHEDULE:
            return ClinicMatch(MatchOutcome.UNAVAILABLE, reason="unsupported")
        reader = self._reader_for(query.hospital)
        matcher = getattr(reader, "match_clinic", None)
        if matcher is None:
            return ClinicMatch(MatchOutcome.UNAVAILABLE, reason="no_observation")
        return await matcher(query, now)

    def _reader_for(self, hospital: Hospital) -> HospitalReader | None:
        cached = self._readers.get(hospital)
        if cached is not None:
            return cached
        entry = HOSPITAL_REGISTRY.get(hospital)
        if entry is None or entry.reader_type is None:
            return None
        reader = entry.reader_type(self._deps.storage, self._deps.fetch)
        self._readers[hospital] = reader
        return reader
