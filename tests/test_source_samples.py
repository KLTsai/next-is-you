import json
from copy import deepcopy
from datetime import date
from pathlib import Path

import pytest

from next_is_you.domain import ClinicScope, ClinicSession
from next_is_you.source_samples import (
    ParseStatus,
    parse_shin_kong_payload,
)


FIXTURES = Path(__file__).parent / "fixtures" / "hospitals"
SHIN_KONG_FIXTURE = (FIXTURES / "shin_kong_taipei.json").read_text()


@pytest.fixture
def shin_kong_scope() -> ClinicScope:
    return ClinicScope(
        hospital="shin-kong-taipei",
        visit_date=date(2026, 9, 27),
        department_code="ND0004",
        clinic_code="236",
        session=ClinicSession.MORNING,
        doctor_code="D-236",
        room_code="本館 3 樓 236 診",
    )


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


def test_duplicate_exact_rows_are_ambiguous(shin_kong_scope):
    payload = json.loads(SHIN_KONG_FIXTURE)
    payload["rows"].append(deepcopy(payload["rows"][0]))
    result = parse_shin_kong_payload(
        payload, shin_kong_scope, observed_at="2026-09-27T09:01:00+08:00"
    )

    assert result.status is ParseStatus.AMBIGUOUS
    assert result.observation is None


def test_empty_schema_drift_challenge_and_denial_fail_closed(shin_kong_scope):
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


def test_stale_samples_never_produce_observations(shin_kong_scope):
    shin_kong = parse_shin_kong_payload(
        SHIN_KONG_FIXTURE,
        shin_kong_scope,
        observed_at="2026-09-27T09:05:00+08:00",
    )

    assert shin_kong.status is ParseStatus.STALE
    assert shin_kong.observation is None


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
