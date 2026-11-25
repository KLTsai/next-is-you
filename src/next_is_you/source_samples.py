"""Offline parsers for captured hospital source samples (source verification).

This is NOT the live adapter layer. The live layer the rest of the system reads
a hospital through is the `HospitalReader` interface (`domain`), the
`hospital_registry` that dispatches by hospital, and the per-hospital reader
modules it builds (for example `ntuh_reader`). This module instead turns a
captured response sample into a normalized `QueueObservation` with no transport
code, which is what pre-reader source verification (for example Issue #44's
evidence for a new hospital) runs against. Only Shin Kong samples are parsed
here; NTUH pages are read by `ntuh_reader` and `ntuh_detail`. No parser here
can make a request, and observations stay untrusted until source freshness
semantics are verified independently.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import StrEnum
import json
from typing import Any, Mapping, Sequence

from next_is_you.domain import (
    ClinicScope,
    ClinicSession,
    QueueObservation,
    normalize_call_type,
)


class ParseStatus(StrEnum):
    MATCHED = "matched"
    NOT_FOUND = "not_found"
    NOT_DISPLAYED = "not_displayed"
    EMPTY = "empty"
    STALE = "stale"
    SCHEMA_DRIFT = "schema_drift"
    CHALLENGE = "challenge"
    DENIED = "denied"
    AMBIGUOUS = "ambiguous"
    INVALID_SCOPE = "invalid_scope"


@dataclass(frozen=True, slots=True)
class ParseResult:
    status: ParseStatus
    observation: QueueObservation | None
    reason: str


DEFAULT_MAX_AGE = timedelta(minutes=2)
_SESSIONS = {
    "上午": ClinicSession.MORNING,
    "下午": ClinicSession.AFTERNOON,
    "晚診": ClinicSession.EVENING,
    "晚上": ClinicSession.EVENING,
    "morning": ClinicSession.MORNING,
    "afternoon": ClinicSession.AFTERNOON,
    "evening": ClinicSession.EVENING,
}
_SHIN_KONG_FIELDS = {
    "VisitDate",
    "ShiftName",
    "DivisionCode",
    "ClinicCode",
    "ClinicName",
    "DoctorEmpNo",
    "ClinicVisitState",
    "CurrentVisitSeq",
    "CurrentVisitSeqDesc",
    "NextVisitSeq",
    "NextVisitSeqDesc",
}
_CHALLENGE_MARKERS = (
    "captcha",
    "challenge",
    "robot check",
    "驗證碼",
    "安全驗證",
    "機器人驗證",
)
_DENIAL_MARKERS = ("access denied", "forbidden", "拒絕存取", "無權限")


def parse_shin_kong_rows(
    rows: Sequence[Mapping[str, Any]],
    expected: ClinicScope,
    *,
    observed_at: str,
    source_updated_at: str | None = None,
    max_age: timedelta = DEFAULT_MAX_AGE,
) -> ParseResult:
    """Parse synthetic Shin Kong rows while requiring all visit identity fields."""
    if not _valid_scope(expected, "shin-kong-taipei"):
        return ParseResult(ParseStatus.INVALID_SCOPE, None, "scope_incomplete")
    observed = _timestamp(observed_at)
    if observed is None or max_age <= timedelta(0):
        return ParseResult(ParseStatus.INVALID_SCOPE, None, "invalid_observation_time")
    if source_updated_at is not None:
        updated = _timestamp(source_updated_at)
        if updated is None:
            return ParseResult(
                ParseStatus.SCHEMA_DRIFT, None, "invalid_source_timestamp"
            )
        if _is_stale(updated, observed, max_age):
            return ParseResult(ParseStatus.STALE, None, "source_sample_stale")
    if not rows:
        return ParseResult(ParseStatus.EMPTY, None, "empty_rows")
    if any(
        not isinstance(row, Mapping) or not _SHIN_KONG_FIELDS.issubset(row)
        for row in rows
    ):
        return ParseResult(ParseStatus.SCHEMA_DRIFT, None, "required_fields_missing")

    matches = [row for row in rows if _shin_kong_scope_matches(row, expected)]
    if not matches:
        return ParseResult(ParseStatus.NOT_FOUND, None, "exact_visit_not_found")
    if len(matches) != 1:
        return ParseResult(ParseStatus.AMBIGUOUS, None, "multiple_exact_rows")
    row = matches[0]
    if _source_text(row.get("ClinicVisitState")) in {"3", "6"}:
        return ParseResult(ParseStatus.NOT_DISPLAYED, None, "source_filters_row")

    current = _positive_integer(row.get("CurrentVisitSeq"))
    next_number = _positive_integer(row.get("NextVisitSeq"))
    if current is None:
        return ParseResult(ParseStatus.SCHEMA_DRIFT, None, "current_number_unusable")
    observation = QueueObservation(
        scope=expected,
        observed_at=observed_at,
        current_number=current,
        next_number=next_number,
        current_call_type=normalize_call_type(
            _source_text(row.get("CurrentVisitSeqDesc"))
        ),
        next_call_type=normalize_call_type(_source_text(row.get("NextVisitSeqDesc"))),
        source_updated_at=source_updated_at,
        trustworthy_current=False,
    )
    reason = (
        "freshness_unverified"
        if source_updated_at is None
        else "untrusted_source_semantics"
    )
    return ParseResult(ParseStatus.MATCHED, observation, reason)


def parse_shin_kong_payload(
    payload: str | bytes | Mapping[str, Any],
    expected: ClinicScope,
    *,
    observed_at: str,
    max_age: timedelta = DEFAULT_MAX_AGE,
) -> ParseResult:
    """Decode a fixture payload; this function performs no network access."""
    try:
        decoded = json.loads(payload) if isinstance(payload, (str, bytes)) else payload
    except (json.JSONDecodeError, UnicodeDecodeError):
        return ParseResult(ParseStatus.SCHEMA_DRIFT, None, "invalid_json")
    if not isinstance(decoded, Mapping):
        return ParseResult(ParseStatus.SCHEMA_DRIFT, None, "payload_not_object")
    status_text = _source_text(decoded.get("status"))
    message = _source_text(decoded.get("message")) or ""
    marked_status = _page_status(f"{status_text or ''} {message}".casefold())
    if marked_status is not None:
        return ParseResult(marked_status, None, marked_status.value)
    if status_text is not None and status_text.casefold() not in {"ok", "success"}:
        return ParseResult(ParseStatus.DENIED, None, "source_rejected_request")
    rows = decoded.get("rows")
    if not isinstance(rows, list):
        return ParseResult(ParseStatus.SCHEMA_DRIFT, None, "rows_missing_or_invalid")
    updated = decoded.get("updatedAt")
    if updated is not None and not isinstance(updated, str):
        return ParseResult(ParseStatus.SCHEMA_DRIFT, None, "invalid_source_timestamp")
    return parse_shin_kong_rows(
        rows,
        expected,
        observed_at=observed_at,
        source_updated_at=updated,
        max_age=max_age,
    )


def _valid_scope(scope: ClinicScope, hospital: str) -> bool:
    return (
        scope.hospital == hospital
        and bool(scope.department_code)
        and bool(scope.clinic_code)
        and bool(scope.doctor_code)
        and bool(scope.room_code)
        and isinstance(scope.visit_date, date)
        and isinstance(scope.session, ClinicSession)
    )


def _shin_kong_scope_matches(row: Mapping[str, Any], scope: ClinicScope) -> bool:
    return (
        _source_date(row.get("VisitDate")) == scope.visit_date
        and _SESSIONS.get((_source_text(row.get("ShiftName")) or "").casefold())
        == scope.session
        and _source_text(row.get("DivisionCode")) == scope.department_code
        and _source_text(row.get("ClinicCode")) == scope.clinic_code
        and _source_text(row.get("ClinicName")) == scope.room_code
        and _source_text(row.get("DoctorEmpNo")) == scope.doctor_code
    )


def _source_text(value: Any) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip()
    return text or None


def _source_date(value: Any) -> date | None:
    text = _source_text(value)
    if text is None:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _positive_integer(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        number = value
    elif isinstance(value, str) and value.strip().isdigit():
        number = int(value.strip())
    else:
        return None
    return number if number > 0 else None


def _timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return (
        parsed if parsed.tzinfo is not None and parsed.utcoffset() is not None else None
    )


def _is_stale(updated: datetime, observed: datetime, max_age: timedelta) -> bool:
    age = observed - updated
    return age < timedelta(0) or age > max_age


def _page_status(text: str) -> ParseStatus | None:
    if any(marker in text for marker in _CHALLENGE_MARKERS):
        return ParseStatus.CHALLENGE
    if any(marker in text for marker in _DENIAL_MARKERS):
        return ParseStatus.DENIED
    return None
