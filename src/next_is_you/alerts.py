"""Deterministic, side-effect-free alert eligibility rules."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from next_is_you.domain import ClinicScope, QueueObservation


NEAR_DISTANCE = 3
NEAR_REMINDER_CAP = 20
# The reminder kinds of #136, in its letter order (a) to (h). Each is stored at most
# once per recipient and visit; `passed` also covers "being seen while not checked in".
REMINDER_KINDS = (
    "check_in_soon",
    "passed",
    "checked_in",
    "getting_close",
    "almost_turn",
    "check_in_order",
    "left_list",
    "left_list_not_checked_in",
)
# Reminders of these kinds and the unavailable message together, per recipient and
# visit. It counts reminders, never LINE retries, and not the skipped ones. The
# database enforces it too.
REMINDER_CAP = 8
UNAVAILABLE_FAILURE_THRESHOLD = 3


@dataclass(frozen=True, slots=True)
class AlertEvaluation:
    near_recipients: tuple[str, ...]
    unavailable_recipients: tuple[str, ...]
    consecutive_unusable_reads: int
    usable_observation: bool


def evaluate_alerts(
    *,
    expected_scope: ClinicScope,
    patient_number: int,
    observation: QueueObservation | None,
    selected_recipients: tuple[str, ...],
    previous_observed_number: int | None = None,
    near_counts: Mapping[str, int] | None = None,
    near_cap: int = NEAR_REMINDER_CAP,
    unavailable_already_sent: frozenset[str] = frozenset(),
    previous_unusable_reads: int = 0,
) -> AlertEvaluation:
    """Evaluate one sample without sending or persisting anything.

    `selected_recipients` must already exclude recipients removed or withdrawn.
    The caller persists returned per-recipient events with a stable retry identity
    before attempting any external LINE request.

    A near reminder is eligible for each selected recipient when the sample is
    usable, the current number is inside the near window (1..``NEAR_DISTANCE``
    numbers before the patient number) and it differs from
    ``previous_observed_number`` (the last usable scheduled read, ``None`` before
    any has happened). Entering the window, moving forward or backward inside it,
    and re-entering after leaving all qualify, because only equality to the prior
    scheduled read suppresses a reminder. ``near_counts`` holds how many near
    reminders a recipient has already accumulated for this logical visit; a
    recipient at or above ``near_cap`` gets no further reminder.
    """
    if patient_number < 1:
        raise ValueError("patient_number must be positive")
    if previous_unusable_reads < 0:
        raise ValueError("previous_unusable_reads cannot be negative")

    usable = observation is not None and observation.is_comparable_to(expected_scope)
    if not usable:
        failures = previous_unusable_reads + 1
        unavailable = (
            tuple(
                recipient
                for recipient in selected_recipients
                if recipient not in unavailable_already_sent
            )
            if failures == UNAVAILABLE_FAILURE_THRESHOLD
            else ()
        )
        return AlertEvaluation((), unavailable, failures, False)

    current_number = observation.current_number
    assert current_number is not None
    counts = near_counts or {}
    distance = patient_number - current_number
    in_window = 1 <= distance <= NEAR_DISTANCE
    moved = current_number != previous_observed_number
    near = (
        tuple(
            recipient
            for recipient in selected_recipients
            if counts.get(recipient, 0) < near_cap
        )
        if in_window and moved
        else ()
    )
    return AlertEvaluation(near, (), 0, True)
