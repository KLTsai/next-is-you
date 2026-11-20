"""The one catalog of every code the organizer can be shown for a visit problem.

Start refusals map a wire code to the HTTP status the organizer API answers
with. Attention reasons are the codes a visit carries while it needs the
organizer's attention; none exist yet (#144 adds them). The frontend keeps one
text map keyed by the same codes, and `tests/test_refusal_catalog.py` fails
when the two drift apart.
"""

from types import MappingProxyType

# `service_unavailable` is the answer for any gate error not listed here, so it
# is a Start refusal the organizer can see too.
START_REFUSAL_FALLBACK = "service_unavailable"

START_REFUSAL_CODES = MappingProxyType(
    {
        "visit_not_found": 404,
        "invalid_lifecycle_state": 409,
        "observation_unavailable": 503,
        "observation_stale": 409,
        "observation_scope_mismatch": 409,
        "observation_untrusted": 409,
        "observation_invalid": 409,
        "ineligible_recipients": 409,
        "scheduler_held": 503,
        "visit_date_past": 409,
        "doctor_not_scheduled": 409,
        "schedule_unavailable": 503,
        "visit_date_out_of_schedule_window": 409,
        "start_on_visit_day_only": 409,
        "hospital_cannot_find_clinic": 409,
        "hospital_page_unreachable": 503,
        START_REFUSAL_FALLBACK: 503,
    }
)

ATTENTION_REASONS: frozenset[str] = frozenset()
