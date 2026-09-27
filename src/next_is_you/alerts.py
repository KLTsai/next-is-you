"""Deterministic, side-effect-free alert eligibility rules."""

from __future__ import annotations

from dataclasses import dataclass

from next_is_you.domain import ClinicScope, QueueObservation


NEAR_DISTANCE = 3
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
    near_already_sent: frozenset[str] = frozenset(),
    unavailable_already_sent: frozenset[str] = frozenset(),
    previous_unusable_reads: int = 0,
) -> AlertEvaluation:
    """Evaluate one sample without sending or persisting anything.

    `selected_recipients` must already exclude recipients removed or withdrawn.
    The caller persists returned per-recipient events with a stable logical-visit
    uniqueness key before attempting any external LINE request.
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
    distance = patient_number - current_number
    near = (
        tuple(
            recipient
            for recipient in selected_recipients
            if recipient not in near_already_sent
        )
        if 1 <= distance <= NEAR_DISTANCE
        else ()
    )
    return AlertEvaluation(near, (), 0, True)
