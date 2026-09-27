from datetime import date

import pytest

from next_is_you.alerts import evaluate_alerts
from next_is_you.domain import ClinicScope, ClinicSession, Hospital, QueueObservation


@pytest.fixture
def scope() -> ClinicScope:
    return ClinicScope(
        hospital=Hospital.NTUH_MAIN,
        visit_date=date(2026, 9, 27),
        department_code="MED",
        clinic_code="MED-101",
        session=ClinicSession.AFTERNOON,
        doctor_code="D-01",
        room_code="101",
    )


def observation(scope: ClinicScope, current_number: int, *, trustworthy: bool = True):
    return QueueObservation(
        scope=scope,
        observed_at="2026-09-27T13:00:00+08:00",
        current_number=current_number,
        trustworthy_current=trustworthy,
    )


@pytest.mark.parametrize("current", [82, 83, 84])
def test_near_window_alerts_selected_recipients_once(scope, current):
    result = evaluate_alerts(
        expected_scope=scope,
        patient_number=85,
        observation=observation(scope, current),
        selected_recipients=("family-a", "family-b"),
        near_already_sent=frozenset({"family-a"}),
    )

    assert result.near_recipients == ("family-b",)
    assert result.unavailable_recipients == ()
    assert result.consecutive_unusable_reads == 0


@pytest.mark.parametrize("current", [81, 85, 86])
def test_outside_near_window_never_sends_or_catches_up(scope, current):
    result = evaluate_alerts(
        expected_scope=scope,
        patient_number=85,
        observation=observation(scope, current),
        selected_recipients=("family-a",),
    )

    assert result.near_recipients == ()
    assert result.unavailable_recipients == ()


def test_untrusted_or_wrong_scope_sample_suppresses_near_alert(scope):
    other_scope = ClinicScope(
        hospital=scope.hospital,
        visit_date=scope.visit_date,
        department_code=scope.department_code,
        clinic_code=scope.clinic_code,
        session=ClinicSession.MORNING,
        doctor_code=scope.doctor_code,
        room_code=scope.room_code,
    )
    result = evaluate_alerts(
        expected_scope=scope,
        patient_number=85,
        observation=observation(other_scope, 82),
        selected_recipients=("family-a",),
        previous_unusable_reads=1,
    )

    assert result.near_recipients == ()
    assert result.consecutive_unusable_reads == 2
    assert result.unavailable_recipients == ()


def test_third_consecutive_unusable_read_sends_one_warning(scope):
    result = evaluate_alerts(
        expected_scope=scope,
        patient_number=85,
        observation=None,
        selected_recipients=("family-a", "family-b"),
        unavailable_already_sent=frozenset({"family-a"}),
        previous_unusable_reads=2,
    )

    assert result.unavailable_recipients == ("family-b",)
    assert result.consecutive_unusable_reads == 3


def test_fourth_unusable_read_does_not_repeat_warning(scope):
    result = evaluate_alerts(
        expected_scope=scope,
        patient_number=85,
        observation=None,
        selected_recipients=("family-a",),
        previous_unusable_reads=3,
    )

    assert result.unavailable_recipients == ()
    assert result.consecutive_unusable_reads == 4


def test_valid_sample_resets_unusable_streak_and_equality_is_display_only(scope):
    result = evaluate_alerts(
        expected_scope=scope,
        patient_number=85,
        observation=observation(scope, 85),
        selected_recipients=("family-a",),
        previous_unusable_reads=2,
    )

    assert result.usable_observation is True
    assert result.consecutive_unusable_reads == 0
    assert result.near_recipients == ()
    assert result.unavailable_recipients == ()
