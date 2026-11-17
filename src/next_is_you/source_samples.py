"""Offline parsers for captured hospital source samples (source verification).

This is NOT the live adapter layer. The live layer the rest of the system reads
a hospital through is the `HospitalReader` interface (`domain`), the
`hospital_registry` that dispatches by hospital, and the per-hospital reader
modules it builds (for example `ntuh_reader`). This module instead turns a
captured response sample into a normalized `QueueObservation` with no transport
code, which is what pre-reader source verification (for example Issue #44's
evidence for a new hospital) runs against. Neither parser can make a request,
and observations stay untrusted until source freshness semantics are verified
independently.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import StrEnum
from html.parser import HTMLParser
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


NTUH_HOSPITAL_ID = "ntuh-main"
SHIN_KONG_HOSPITAL_ID = "shin-kong-taipei"
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
_NTUH_HEADERS = {
    "date": {"visit date", "就診日期"},
    "department": {"department code", "科別代碼"},
    "session": {"session", "診次"},
    "clinic": {"clinic code", "診間代碼"},
    "doctor": {"doctor", "醫師代碼"},
    "room": {"room", "診間"},
    "current": {"current light", "目前燈號"},
    "highest": {"highest called", "最高已叫號"},
    "current_call_type": {"call type", "叫號類型"},
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


def parse_ntuh_fragment(
    fragment: str,
    expected: ClinicScope,
    *,
    observed_at: str,
    max_age: timedelta = DEFAULT_MAX_AGE,
) -> ParseResult:
    """Parse an NTUH-shaped HTML sample with identity columns on each row."""
    if not _valid_scope(expected, NTUH_HOSPITAL_ID):
        return ParseResult(ParseStatus.INVALID_SCOPE, None, "scope_incomplete")
    observed = _timestamp(observed_at)
    if observed is None or max_age <= timedelta(0):
        return ParseResult(ParseStatus.INVALID_SCOPE, None, "invalid_observation_time")

    collector = _TableCollector()
    try:
        collector.feed(fragment)
        collector.close()
    except (ValueError, AssertionError):
        return ParseResult(ParseStatus.SCHEMA_DRIFT, None, "malformed_html")
    marker_status = _page_status(" ".join(collector.text).casefold())
    if marker_status is not None:
        return ParseResult(marker_status, None, marker_status.value)

    tables_with_rows: list[tuple[dict[str, int], list[list[str]]]] = []
    for table in collector.tables:
        indexes = _header_indexes(table)
        if indexes is None:
            continue
        header_index = next(i for i, row in enumerate(table) if _header_indexes([row]))
        rows = table[header_index + 1 :]
        tables_with_rows.append((indexes, rows))
    if not tables_with_rows:
        return ParseResult(ParseStatus.SCHEMA_DRIFT, None, "recognized_table_not_found")

    matches: list[tuple[list[str], dict[str, int]]] = []
    has_rows = False
    for indexes, rows in tables_with_rows:
        has_rows |= bool(rows)
        matches.extend(
            (row, indexes)
            for row in rows
            if _ntuh_scope_matches(row, indexes, expected)
        )
    if not has_rows:
        return ParseResult(ParseStatus.EMPTY, None, "empty_rows")
    if not matches:
        return ParseResult(ParseStatus.NOT_FOUND, None, "exact_visit_not_found")
    if len(matches) != 1:
        return ParseResult(ParseStatus.AMBIGUOUS, None, "multiple_exact_rows")

    row, indexes = matches[0]
    current = _positive_integer(_cell(row, indexes, "current"))
    highest = _positive_integer(_cell(row, indexes, "highest"))
    updated_at = _timestamp(collector.updated_at)
    if collector.updated_at is not None and updated_at is None:
        return ParseResult(ParseStatus.SCHEMA_DRIFT, None, "invalid_source_timestamp")
    if updated_at is not None and _is_stale(updated_at, observed, max_age):
        return ParseResult(ParseStatus.STALE, None, "source_sample_stale")
    observation = QueueObservation(
        scope=expected,
        observed_at=observed_at,
        current_number=current,
        highest_called_number=highest,
        current_call_type=normalize_call_type(_cell(row, indexes, "current_call_type")),
        source_updated_at=collector.updated_at,
        trustworthy_current=False,
    )
    if current is None:
        return ParseResult(ParseStatus.SCHEMA_DRIFT, None, "current_number_unusable")
    reason = (
        "freshness_unverified" if updated_at is None else "untrusted_source_semantics"
    )
    return ParseResult(ParseStatus.MATCHED, observation, reason)


def parse_shin_kong_rows(
    rows: Sequence[Mapping[str, Any]],
    expected: ClinicScope,
    *,
    observed_at: str,
    source_updated_at: str | None = None,
    max_age: timedelta = DEFAULT_MAX_AGE,
) -> ParseResult:
    """Parse synthetic Shin Kong rows while requiring all visit identity fields."""
    if not _valid_scope(expected, SHIN_KONG_HOSPITAL_ID):
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


def _ntuh_scope_matches(
    row: list[str], indexes: dict[str, int], scope: ClinicScope
) -> bool:
    return (
        _source_date(_cell(row, indexes, "date")) == scope.visit_date
        and _cell(row, indexes, "department") == scope.department_code
        and _SESSIONS.get((_cell(row, indexes, "session") or "").casefold())
        == scope.session
        and _cell(row, indexes, "clinic") == scope.clinic_code
        and _cell(row, indexes, "doctor") == scope.doctor_code
        and _cell(row, indexes, "room") == scope.room_code
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


def _header_indexes(table: list[list[str]]) -> dict[str, int] | None:
    for row in table:
        indexes: dict[str, int] = {}
        for index, value in enumerate(row):
            normalized = value.strip().casefold()
            for field, aliases in _NTUH_HEADERS.items():
                if normalized in aliases:
                    indexes[field] = index
        if set(indexes) == set(_NTUH_HEADERS):
            return indexes
    return None


def _cell(row: list[str], indexes: dict[str, int], field: str) -> str | None:
    index = indexes[field]
    return _source_text(row[index]) if index < len(row) else None


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


class _TableCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[str]]] = []
        self.text: list[str] = []
        self.updated_at: str | None = None
        self._table: list[list[str]] | None = None
        self._depth = 0
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if attributes.get("data-updated-at"):
            self.updated_at = attributes["data-updated-at"]
        if tag == "table":
            self._depth += 1
            if self._table is None:
                self._table = []
                self.tables.append(self._table)
        elif tag == "tr" and self._table is not None and self._depth == 1:
            self._row = []
        elif tag in {"th", "td"} and self._row is not None and self._depth == 1:
            self._cell = []

    def handle_data(self, data: str) -> None:
        self.text.append(data)
        if self._cell is not None and self._depth == 1:
            self._cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"th", "td"} and self._cell is not None and self._row is not None:
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif tag == "tr" and self._row is not None and self._table is not None:
            if self._row:
                self._table.append(self._row)
            self._row = None
        elif tag == "table" and self._depth:
            self._depth -= 1
            if self._depth == 0:
                self._table = None
