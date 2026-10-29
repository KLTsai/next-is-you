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
    ClinicScope,
    Hospital,
    HospitalReader,
    QueueObservation,
    ReadFailed,
    ReadSkipped,
    SourceCapability,
)
from next_is_you.ntuh_reader import Fetcher, NtuhProgressReader


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

    `capability` is read by the setup UI for graceful degradation.
    `build_reader` is `None` when no reader exists yet (for example a hospital
    whose source is still being evidenced), in which case reads fail closed.
    """

    capability: SourceCapability
    build_reader: Callable[[ReaderDeps], HospitalReader] | None


HOSPITAL_REGISTRY: Mapping[Hospital, HospitalEntry] = {
    Hospital.NTUH_MAIN: HospitalEntry(
        capability=SourceCapability.FULL_SCHEDULE,
        build_reader=lambda deps: NtuhProgressReader(deps.storage, deps.fetch),
    ),
    # No reader until Issue #44 evidences a usable Shin Kong source; until then
    # it is offered to no one and reads fail closed.
    Hospital.SHIN_KONG_TAIPEI: HospitalEntry(
        capability=SourceCapability.UNSUPPORTED,
        build_reader=None,
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

    def _reader_for(self, hospital: Hospital) -> HospitalReader | None:
        cached = self._readers.get(hospital)
        if cached is not None:
            return cached
        entry = HOSPITAL_REGISTRY.get(hospital)
        if entry is None or entry.build_reader is None:
            return None
        reader = entry.build_reader(self._deps)
        self._readers[hospital] = reader
        return reader
