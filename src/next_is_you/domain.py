"""Queue-domain values shared by hospital adapters and alert evaluation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Protocol


class Hospital(StrEnum):
    NTUH_MAIN = "ntuh-main"
    SHIN_KONG_TAIPEI = "shin-kong-taipei"


class SourceCapability(StrEnum):
    """How much a hospital's public source exposes, for graceful degradation.

    FULL_SCHEDULE: the source lists the day's roster for a department and
    session (doctors and rooms consulting) plus the current called number, so a
    cascading picker can be offered. CURRENT_NUMBER_ONLY: only the current
    number is readable, so manual entry with pre-submit validation is the
    fallback. UNSUPPORTED: nothing usable is exposed; the hospital is not
    offered for automatic monitoring. The descriptor is the contract the setup
    UI reads; it never implies the numbers are verified against a physical light.
    """

    FULL_SCHEDULE = "full_schedule"
    CURRENT_NUMBER_ONLY = "current_number_only"
    UNSUPPORTED = "unsupported"


class ClinicSession(StrEnum):
    MORNING = "morning"
    AFTERNOON = "afternoon"
    EVENING = "evening"


_CALL_TYPE_ALIASES = {
    "regular": "regular",
    "順號": "regular",
    "examination": "examination",
    "檢查": "examination",
    "senior": "senior",
    "高齡號": "senior",
    "overdue": "overdue",
    "過號": "overdue",
}


def normalize_call_type(value: str | None) -> str | None:
    """Normalize recognized labels without treating unknown text as regular."""
    if value is None:
        return None
    return _CALL_TYPE_ALIASES.get(value.strip().casefold())


@dataclass(frozen=True, slots=True)
class ClinicScope:
    hospital: Hospital
    visit_date: date
    department_code: str
    clinic_code: str
    session: ClinicSession
    doctor_code: str | None = None
    room_code: str | None = None


@dataclass(frozen=True, slots=True)
class QueueObservation:
    scope: ClinicScope
    observed_at: str
    current_number: int | None
    next_number: int | None = None
    highest_called_number: int | None = None
    current_call_type: str | None = None
    next_call_type: str | None = None
    source_updated_at: str | None = None
    trustworthy_current: bool = False

    def is_comparable_to(self, expected: ClinicScope) -> bool:
        """Require exact clinic identity and an adapter-validated current value."""
        if self.scope != expected or not self.trustworthy_current:
            return False
        return self.current_number is not None and self.current_number > 0


@dataclass(frozen=True, slots=True)
class ReadSkipped:
    """A reader outcome that is not a failed read and counts as no failure.

    `not_due` leaves the stored source status untouched. `clinic_not_started`
    and `clinic_ended` describe where the clinic is in its own day, never a
    failed read, so they must not feed the unavailable alert.
    """

    reason: str

    @property
    def source_read(self) -> tuple[str, str] | None:
        if self.reason == "clinic_not_started":
            return "unavailable", "no_observation"
        if self.reason == "clinic_ended":
            return "unavailable", "empty_result"
        return None


@dataclass(frozen=True, slots=True)
class ReadFailed:
    """A reader outcome that is an unusable read inside the clinic window."""

    status: str
    reason: str


@dataclass(frozen=True, slots=True)
class RosterQuery:
    """What the setup UI asks a hospital: who is consulting a department that day.

    No clinic, doctor, room or session: those are what the roster answers with,
    so the owner picks them instead of typing them.
    """

    hospital: Hospital
    department_code: str
    visit_date: date


@dataclass(frozen=True, slots=True)
class ClinicOption:
    """One consulting clinic the owner can pick, carrying its own identity.

    `clinic_code` is the exact value a draft stores and the reader matches on;
    `session` is derived from the chosen clinic, not typed. `room`, `doctor` and
    `clinic_type` are for display. Listing a clinic says it is scheduled, never
    that its number is verified against the room's physical light.
    """

    session: ClinicSession
    room: str
    doctor: str
    clinic_type: str
    clinic_code: str


@dataclass(frozen=True, slots=True)
class ClinicRoster:
    """A hospital's consulting clinics for a department and day, or why not.

    `available` is false and `clinics` empty when the roster cannot be offered -
    the hospital exposes no schedule, reads are held, the day is not today for a
    source that only shows today, or a read failed. `reason` names which, so the
    UI can fall back to manual entry instead of showing a broken picker.
    """

    available: bool
    clinics: tuple[ClinicOption, ...]
    reason: str


class HospitalReader(Protocol):
    """The single interface the rest of the system reads a hospital through.

    Every hospital is reached as one of these; no caller names a concrete
    hospital class. `observe` is the scheduled read and `observe_for_start` is
    the Start read, which may reuse a recent good read. Both are part of the
    contract so Start never has to branch on which hospital it is talking to.
    Implementations fail closed: an unusable read is a `ReadFailed`, a read that
    did not happen is a `ReadSkipped`, and `None` means no observation.
    """

    async def observe(
        self, scope: ClinicScope, now: datetime
    ) -> QueueObservation | ReadSkipped | ReadFailed | None: ...

    async def observe_for_start(
        self, scope: ClinicScope, now: datetime
    ) -> QueueObservation | ReadSkipped | ReadFailed | None: ...


class ScheduleReader(Protocol):
    """A capability a FULL_SCHEDULE hospital adds: list a department's clinics.

    Only hospitals whose source exposes the day's roster implement this; the
    rest are read through `HospitalReader` alone. It always answers with a
    `ClinicRoster`, available or not, and never raises for an absent schedule.
    """

    async def list_clinics(self, query: RosterQuery, now: datetime) -> ClinicRoster: ...
