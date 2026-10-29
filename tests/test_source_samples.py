import json
from copy import deepcopy
from datetime import date
from pathlib import Path

import pytest

from next_is_you.domain import ClinicScope, ClinicSession, Hospital
from next_is_you.source_samples import (
    ParseStatus,
    parse_ntuh_fragment,
    parse_shin_kong_payload,
)


FIXTURES = Path(__file__).parent / "fixtures" / "hospitals"
NTUH_FIXTURE = (FIXTURES / "ntuh_main.html").read_text()
SHIN_KONG_FIXTURE = (FIXTURES / "shin_kong_taipei.json").read_text()


@pytest.fixture
def ntuh_scope() -> ClinicScope:
    return ClinicScope(
        hospital=Hospital.NTUH_MAIN,
        visit_date=date(2026, 9, 27),
        department_code="MED",
        clinic_code="MED-101",
        session=ClinicSession.AFTERNOON,
        doctor_code="D-01",
        room_code="101診",
    )


@pytest.fixture
def shin_kong_scope() -> ClinicScope:
    return ClinicScope(
        hospital=Hospital.SHIN_KONG_TAIPEI,
        visit_date=date(2026, 9, 27),
        department_code="ND0004",
        clinic_code="236",
        session=ClinicSession.MORNING,
        doctor_code="D-236",
        room_code="本館 3 樓 236 診",
    )


def test_ntuh_fixture_preserves_current_and_highest_called_without_trust(ntuh_scope):
    result = parse_ntuh_fragment(
        NTUH_FIXTURE, ntuh_scope, observed_at="2026-09-27T13:01:00+08:00"
    )

    assert result.status is ParseStatus.MATCHED
    assert result.observation is not None
    assert result.observation.current_number == 82
    assert result.observation.highest_called_number == 84
    assert result.observation.next_number is None
    assert result.observation.current_call_type == "regular"
    assert result.observation.next_call_type is None
    assert result.observation.trustworthy_current is False
    assert not result.observation.is_comparable_to(ntuh_scope)


def test_shin_kong_fixture_keeps_current_next_and_each_call_type_separate(
    shin_kong_scope,
):
    result = parse_shin_kong_payload(
        SHIN_KONG_FIXTURE,
        shin_kong_scope,
        observed_at="2026-09-27T09:01:00+08:00",
    )

    assert result.status is ParseStatus.MATCHED
    assert result.observation is not None
    assert result.observation.current_number == 82
    assert result.observation.current_call_type == "regular"
    assert result.observation.next_number == 79
    assert result.observation.next_call_type == "examination"
    assert result.observation.trustworthy_current is False
    assert not result.observation.is_comparable_to(shin_kong_scope)


@pytest.mark.parametrize(
    "field,value",
    [
        ("Visit date", "2026-09-28"),
        ("Department code", "SUR"),
        ("Session", "morning"),
        ("Clinic code", "MED-102"),
        ("Doctor", "D-02"),
        ("Room", "102診"),
    ],
)
def test_ntuh_identity_mismatch_fails_closed(ntuh_scope, field, value):
    original = {
        "Visit date": "2026-09-27",
        "Department code": "MED",
        "Session": "afternoon",
        "Clinic code": "MED-101",
        "Doctor": "D-01",
        "Room": "101診",
    }[field]
    fragment = NTUH_FIXTURE.replace(f"<td>{original}</td>", f"<td>{value}</td>")

    result = parse_ntuh_fragment(
        fragment, ntuh_scope, observed_at="2026-09-27T13:01:00+08:00"
    )

    assert result.status is ParseStatus.NOT_FOUND
    assert result.observation is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("VisitDate", "2026-09-28"),
        ("DivisionCode", "ND0005"),
        ("ShiftName", "下午"),
        ("ClinicCode", "237"),
        ("DoctorEmpNo", "D-237"),
        ("ClinicName", "另一間診間"),
    ],
)
def test_shin_kong_identity_mismatch_fails_closed(shin_kong_scope, field, value):
    payload = json.loads(SHIN_KONG_FIXTURE)
    payload["rows"][0][field] = value

    result = parse_shin_kong_payload(
        payload, shin_kong_scope, observed_at="2026-09-27T09:01:00+08:00"
    )

    assert result.status is ParseStatus.NOT_FOUND
    assert result.observation is None


@pytest.mark.parametrize("parser", ["ntuh", "shin-kong"])
def test_duplicate_exact_rows_are_ambiguous(ntuh_scope, shin_kong_scope, parser):
    if parser == "ntuh":
        row = NTUH_FIXTURE.split("<tbody>", 1)[1].split("</tbody>", 1)[0]
        result = parse_ntuh_fragment(
            NTUH_FIXTURE.replace(row, row + row),
            ntuh_scope,
            observed_at="2026-09-27T13:01:00+08:00",
        )
    else:
        payload = json.loads(SHIN_KONG_FIXTURE)
        payload["rows"].append(deepcopy(payload["rows"][0]))
        result = parse_shin_kong_payload(
            payload, shin_kong_scope, observed_at="2026-09-27T09:01:00+08:00"
        )

    assert result.status is ParseStatus.AMBIGUOUS
    assert result.observation is None


def test_empty_schema_drift_challenge_and_denial_fail_closed(
    ntuh_scope, shin_kong_scope
):
    empty = """<table><tr>
      <th>Visit date</th><th>Department code</th><th>Session</th>
      <th>Clinic code</th><th>Doctor</th><th>Room</th>
      <th>Current light</th><th>Highest called</th><th>Call type</th>
    </tr></table>"""
    assert (
        parse_ntuh_fragment(
            empty, ntuh_scope, observed_at="2026-09-27T13:01:00+08:00"
        ).status
        is ParseStatus.EMPTY
    )
    assert (
        parse_ntuh_fragment(
            "<table><tr><td>No appointments</td></tr></table>",
            ntuh_scope,
            observed_at="2026-09-27T13:01:00+08:00",
        ).status
        is ParseStatus.SCHEMA_DRIFT
    )
    assert (
        parse_ntuh_fragment(
            "<p>Captcha challenge</p>",
            ntuh_scope,
            observed_at="2026-09-27T13:01:00+08:00",
        ).status
        is ParseStatus.CHALLENGE
    )
    assert (
        parse_ntuh_fragment(
            "<p>Access denied</p>",
            ntuh_scope,
            observed_at="2026-09-27T13:01:00+08:00",
        ).status
        is ParseStatus.DENIED
    )
    invalid_timestamp = NTUH_FIXTURE.replace(
        'data-updated-at="2026-09-27T13:00:00+08:00"', 'data-updated-at="unknown"'
    )
    assert (
        parse_ntuh_fragment(
            invalid_timestamp, ntuh_scope, observed_at="2026-09-27T13:01:00+08:00"
        ).status
        is ParseStatus.SCHEMA_DRIFT
    )

    base = json.loads(SHIN_KONG_FIXTURE)
    base["rows"] = []
    assert (
        parse_shin_kong_payload(
            base, shin_kong_scope, observed_at="2026-09-27T09:01:00+08:00"
        ).status
        is ParseStatus.EMPTY
    )
    base["rows"] = [{"VisitDate": "2026-09-27"}]
    assert (
        parse_shin_kong_payload(
            base, shin_kong_scope, observed_at="2026-09-27T09:01:00+08:00"
        ).status
        is ParseStatus.SCHEMA_DRIFT
    )
    base["status"] = "challenge"
    assert (
        parse_shin_kong_payload(
            base, shin_kong_scope, observed_at="2026-09-27T09:01:00+08:00"
        ).status
        is ParseStatus.CHALLENGE
    )
    base["status"] = "denied"
    assert (
        parse_shin_kong_payload(
            base, shin_kong_scope, observed_at="2026-09-27T09:01:00+08:00"
        ).status
        is ParseStatus.DENIED
    )


def test_stale_samples_never_produce_observations(ntuh_scope, shin_kong_scope):
    ntuh = parse_ntuh_fragment(
        NTUH_FIXTURE, ntuh_scope, observed_at="2026-09-27T13:05:00+08:00"
    )
    shin_kong = parse_shin_kong_payload(
        SHIN_KONG_FIXTURE,
        shin_kong_scope,
        observed_at="2026-09-27T09:05:00+08:00",
    )

    assert ntuh.status is ParseStatus.STALE
    assert ntuh.observation is None
    assert shin_kong.status is ParseStatus.STALE
    assert shin_kong.observation is None


def test_unknown_call_type_is_not_normalized_and_bad_numbers_fail_closed(ntuh_scope):
    fragment = NTUH_FIXTURE.replace("<td>082</td>", "<td>unavailable</td>").replace(
        "<td>順號</td>", "<td>unknown type</td>"
    )

    result = parse_ntuh_fragment(
        fragment, ntuh_scope, observed_at="2026-09-27T13:01:00+08:00"
    )

    assert result.status is ParseStatus.SCHEMA_DRIFT
    assert result.observation is None


def test_shin_kong_unknown_next_call_type_does_not_inherit_current_type(
    shin_kong_scope,
):
    payload = json.loads(SHIN_KONG_FIXTURE)
    payload["rows"][0]["NextVisitSeqDesc"] = "unknown type"

    result = parse_shin_kong_payload(
        payload, shin_kong_scope, observed_at="2026-09-27T09:01:00+08:00"
    )

    assert result.observation is not None
    assert result.observation.current_call_type == "regular"
    assert result.observation.next_call_type is None
