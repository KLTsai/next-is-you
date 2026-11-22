"""Queue-domain values shared by hospital adapters and alert evaluation."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum
from typing import Literal, Protocol


# A hospital id is a key in the hospital registry; the registry owns which ids
# exist, so the domain only carries the value.
HospitalId = str


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


@dataclass(frozen=True, slots=True)
class SupportedDepartment:
    """A department the setup picker may offer for a hospital.

    `code` is what a draft stores and the reader matches on; `display_name` is
    what the picker shows. Only departments listed here are offered, so the
    frontend never has to know a hospital's own department codes.
    """

    code: str
    display_name: str


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
    hospital: HospitalId
    visit_date: date
    department_code: str
    clinic_code: str
    session: ClinicSession
    doctor_code: str | None = None
    room_code: str | None = None


NumberState = Literal["not_checked_in", "first_visit", "checked_in", "in_consultation"]
CallKind = Literal["sequential", "passed", "exam", "senior", "check_in"]


@dataclass(frozen=True, slots=True)
class NumberStatus:
    """One number on a source's list. `check_in_position` is 報到N in check-in-order clinics."""

    number: int
    state: NumberState
    check_in_position: int | None = None


@dataclass(frozen=True, slots=True)
class ExpectedCall:
    """One number the source says it will call next. `check_in_position` is set for `check_in`."""

    number: int
    kind: CallKind | None
    check_in_position: int | None = None


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
    # The hospital's card for this clinic names a substitute doctor, not the
    # booked one. The visit keeps running and the organizer decides.
    substitute_doctor: bool = False
    # Progress fields (ADR 0003): each is present only when the source states it
    # outright, and a hospital that does not show one leaves it empty. Only
    # `called_in_session` compares what the source showed at different times.
    current_flag: CallKind | None = None
    # The clinic calls by check-in order, so it has no highest called.
    check_in_order: bool = False
    check_in_position: int | None = None
    expected: tuple[ExpectedCall, ...] = ()
    # None when the source read does not list the numbers (a list card). An empty
    # tuple is a source that lists them and has none left.
    numbers: tuple[NumberStatus, ...] | None = None
    # Whether the clinic has called a number in this session. A page can be
    # frozen from an earlier session, so a number on it alone does not say so.
    # None when the source cannot tell.
    called_in_session: bool | None = None

    def is_comparable_to(self, expected: ClinicScope) -> bool:
        """Require exact clinic identity and an adapter-validated current value."""
        if self.scope != expected or not self.trustworthy_current:
            return False
        return self.current_number is not None and self.current_number > 0


@dataclass(frozen=True, slots=True)
class ReadSkipped:
    """A reader outcome that is not a failed read and counts as no failure.

    `not_due` leaves the stored source status untouched. `clinic_not_started`,
    `blank_after_call`, `clinic_ended` and `check_in_order` describe where the
    clinic is in its own day, never a failed read, so they must not feed the
    unavailable alert. `card_not_listed` is a card the hospital has not listed
    before the session's published start: the organizer sees it, but it is not
    yet an unusable read. `unobserved_situation` is one no one has observed on
    the hospital's pages; `unobserved` names it.
    """

    reason: str
    substitute_doctor: bool = False
    unobserved: str = ""
    # The facts the page stated, when a page was read and understood. They never
    # feed the current-number rules (`trustworthy_current` is false); rules that
    # use other progress facts read them from here.
    progress: QueueObservation | None = field(default=None, compare=False)

    @property
    def source_read(self) -> tuple[str, str] | None:
        if self.reason == "card_not_listed":
            return "unavailable", "card_not_found"
        if self.reason in (
            "clinic_not_started",
            "check_in_order",
            "unobserved_situation",
        ):
            if self.substitute_doctor:
                return "unavailable", "substitute_doctor"
            return "unavailable", "no_observation"
        if self.reason in ("blank_after_call", "clinic_ended"):
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

    hospital: HospitalId
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
    # Written by the reader, shown by everything else as given: the way the
    # hospital identifies the clinic, and every labelled field it publishes
    # that helps a person confirm the clinic (room, location, clinic type,
    # substitute doctor, status), in display order as (name, value) pairs.
    label: str = ""
    details: tuple[tuple[str, str], ...] = ()


def clinic_label(room: str, doctor: str, session_name: str) -> str:
    """Join the segments a hospital publishes into one dropdown label.

    A hospital without room numbers passes an empty room, and the label then
    has no empty segment and no stray separator.
    """
    head = " · ".join(part for part in (room.strip(), doctor.strip()) if part)
    session = session_name.strip()
    if head and session:
        return f"{head}（{session}）"
    return head or session


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
    # Set only when the requested day is not yet published: the last day the
    # hospital's clinic schedule covers, and the moment the hospital says the
    # requested day will be added. `release_time` stays None unless the
    # hospital states one publicly; it is never estimated.
    schedule_end: date | None = None
    release_time: datetime | None = None


class MatchKind(StrEnum):
    """How a hospital's clinic schedule answers for a stored draft."""

    MATCHED = "matched"
    NOT_SCHEDULED = "not_scheduled"
    CANCELLED = "cancelled"
    NOT_YET_PUBLISHED = "not_yet_published"
    UNAVAILABLE = "unavailable"
    # The hospital publishes no clinic schedule, so there is nothing to match
    # against. Not a failure and not a mismatch: callers leave the draft alone.
    NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True, slots=True)
class MatchQuery:
    """A stored draft's identity, as the reader needs it to find its clinic."""

    hospital: HospitalId
    department_code: str
    visit_date: date
    session: ClinicSession
    clinic_code: str


@dataclass(frozen=True, slots=True)
class ClinicMatch:
    """A reader's answer to "is this draft on the hospital's clinic schedule".

    `clinic_code` is the hospital's canonical code, set only when matched; shared
    code stores it without parsing it. `reason` names the source problem and is
    set only when unavailable.
    """

    kind: MatchKind
    clinic_code: str = ""
    reason: str = ""
    # Set only when not yet published: the same two facts the clinic schedule
    # answer carries, so a refused Start can state them.
    schedule_end: date | None = None
    release_time: datetime | None = None
    # Set only when matched on the visit day: the card is a substitute doctor's.
    substitute_doctor: bool = False


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

    async def match_clinic(self, query: MatchQuery, now: datetime) -> ClinicMatch:
        """Decide whether a stored draft is on the hospital's clinic schedule.

        The reader owns clinic-code parsing, normalisation and its status
        vocabulary; callers branch only on the returned `MatchKind`.
        """
        ...
