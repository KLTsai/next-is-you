"""The one catalog of every code the organizer can be shown for a visit problem.

Start refusals map a wire code to the HTTP status the organizer API answers
with. Attention reasons are the codes a visit carries while it needs the
organizer's attention; none exist yet (#144 adds them). The frontend keeps one
text map keyed by the same codes, and `tests/test_refusal_catalog.py` fails
when the two drift apart.
"""

from enum import StrEnum
from types import MappingProxyType


class RefusalCode(StrEnum):
    """Every code the send gate or the worker can refuse Start or Stop with."""

    VISIT_NOT_FOUND = "visit_not_found"
    INVALID_LIFECYCLE_STATE = "invalid_lifecycle_state"
    ANOTHER_VISIT_RUNNING = "another_visit_running"
    OBSERVATION_UNAVAILABLE = "observation_unavailable"
    OBSERVATION_STALE = "observation_stale"
    OBSERVATION_SCOPE_MISMATCH = "observation_scope_mismatch"
    OBSERVATION_UNTRUSTED = "observation_untrusted"
    OBSERVATION_INVALID = "observation_invalid"
    CLINIC_AMBIGUOUS = "clinic_ambiguous"
    INELIGIBLE_RECIPIENTS = "ineligible_recipients"
    SCHEDULER_HELD = "scheduler_held"
    VISIT_DATE_PAST = "visit_date_past"
    DOCTOR_NOT_SCHEDULED = "doctor_not_scheduled"
    SCHEDULE_UNAVAILABLE = "schedule_unavailable"
    VISIT_DATE_OUT_OF_SCHEDULE_WINDOW = "visit_date_out_of_schedule_window"
    START_ON_VISIT_DAY_ONLY = "start_on_visit_day_only"
    HOSPITAL_CANNOT_FIND_CLINIC = "hospital_cannot_find_clinic"
    HOSPITAL_PAGE_UNREACHABLE = "hospital_page_unreachable"
    SERVICE_UNAVAILABLE = "service_unavailable"


# The worker also answers `service_unavailable` when the gate is missing, so it
# is a Start refusal the organizer can see too.
START_REFUSAL_FALLBACK = RefusalCode.SERVICE_UNAVAILABLE

START_REFUSAL_CODES = MappingProxyType(
    {
        RefusalCode.VISIT_NOT_FOUND: 404,
        RefusalCode.INVALID_LIFECYCLE_STATE: 409,
        RefusalCode.ANOTHER_VISIT_RUNNING: 409,
        RefusalCode.OBSERVATION_UNAVAILABLE: 503,
        RefusalCode.OBSERVATION_STALE: 409,
        RefusalCode.OBSERVATION_SCOPE_MISMATCH: 409,
        RefusalCode.OBSERVATION_UNTRUSTED: 409,
        RefusalCode.OBSERVATION_INVALID: 409,
        RefusalCode.CLINIC_AMBIGUOUS: 409,
        RefusalCode.INELIGIBLE_RECIPIENTS: 409,
        RefusalCode.SCHEDULER_HELD: 503,
        RefusalCode.VISIT_DATE_PAST: 409,
        RefusalCode.DOCTOR_NOT_SCHEDULED: 409,
        RefusalCode.SCHEDULE_UNAVAILABLE: 503,
        RefusalCode.VISIT_DATE_OUT_OF_SCHEDULE_WINDOW: 409,
        RefusalCode.START_ON_VISIT_DAY_ONLY: 409,
        RefusalCode.HOSPITAL_CANNOT_FIND_CLINIC: 409,
        RefusalCode.HOSPITAL_PAGE_UNREACHABLE: 503,
        START_REFUSAL_FALLBACK: 503,
    }
)

ATTENTION_REASONS: frozenset[str] = frozenset()
