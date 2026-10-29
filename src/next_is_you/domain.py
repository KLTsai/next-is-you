"""Queue-domain values shared by hospital adapters and alert evaluation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum


class Hospital(StrEnum):
    NTUH_MAIN = "ntuh-main"
    SHIN_KONG_TAIPEI = "shin-kong-taipei"


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
