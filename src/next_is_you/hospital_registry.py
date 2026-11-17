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
from typing import Any, Callable, Mapping

from next_is_you.domain import (
    ClinicRoster,
    ClinicScope,
    Hospital,
    HospitalReader,
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

    `capability` is derived, never declared: no `reader_type` means
    unsupported; a reader type that can list a clinic schedule means full
    schedule; otherwise current number only. It reads the type, so no reader is
    built and no transport is touched. Retiring a hospital keeps the entry and
    sets `reader_type` to `None`; reads then fail closed and the catalog shows
    it as unsupported.

    `official_link` is the fixed, server-owned, HTTPS-only progress page link
    (NIY-016); it is never taken from a caller. `build_reader` overrides how a
    reader is constructed; by default it is `reader_type(storage, fetch)`.
    """

    display_name: str
    reader_type: type | None
    official_link: str
    build_reader: Callable[[ReaderDeps], HospitalReader] | None = None
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

    def make_reader(self, deps: ReaderDeps) -> HospitalReader | None:
        """Build this hospital's reader, or `None` when it has none."""
        if self.reader_type is None:
            return None
        if self.build_reader is not None:
            return self.build_reader(deps)
        return self.reader_type(deps.storage, deps.fetch)


HOSPITAL_REGISTRY: Mapping[Hospital, HospitalEntry] = {
    Hospital.NTUH_MAIN: HospitalEntry(
        display_name="臺大醫院總院",
        reader_type=NtuhProgressReader,
        official_link=(
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
        official_link="https://reg.skh.org.tw/",
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

    def _reader_for(self, hospital: Hospital) -> HospitalReader | None:
        cached = self._readers.get(hospital)
        if cached is not None:
            return cached
        entry = HOSPITAL_REGISTRY.get(hospital)
        if entry is None:
            return None
        reader = entry.make_reader(self._deps)
        if reader is None:
            return None
        self._readers[hospital] = reader
        return reader
