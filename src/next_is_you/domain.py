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
    current_call_type: str | None = None
    next_call_type: str | None = None
    source_updated_at: str | None = None
    trustworthy_current: bool = False

    def is_comparable_to(self, expected: ClinicScope) -> bool:
        """Require exact clinic identity and an adapter-validated current value."""
        if self.scope != expected or not self.trustworthy_current:
            return False
        return self.current_number is not None and self.current_number > 0
