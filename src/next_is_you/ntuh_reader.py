"""NTU Hospital main campus ophthalmology reader for Start and scheduled checks.

Scope is exactly what the Issue #17 evidence supports: the official public
registration progress list for branch T0, department OPH, afternoon session
of the current day. Morning session hours are unverified and outside scope.
The list shows room, doctor, clinic type and the current light.
The "Last updated" text is render time and the detail page's expected call
number is undefined, so neither is read. Freshness is the time this reader
fetched the page; it is never taken from the page.

Live hospital behavior is unverified. Tests drive this module with fixture
pages and an injected fetcher and never contact the hospital.
Each clinic keeps its own transient read state; cross-clinic sharing is outside
this ticket and may be considered as a future optimization.
"""

from __future__ import annotations

import asyncio
import json
import math
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Awaitable, Callable, Protocol
from urllib.parse import urlencode

from next_is_you.domain import (
    ClinicScope,
    ClinicSession,
    Hospital,
    QueueObservation,
    ReadFailed,
    ReadSkipped,
)
from next_is_you.hospital_adapters import _page_status, _TableCollector
from next_is_you.persistence import TAIPEI

# This route is derived from manual observation and is not live-verified.
# The default list's department and session are unverified; the reader stays
# behind NTUH_READER_ENABLED. Trust means a fresh, exact source read, not
# verified accuracy against the room's physical indicator.
PROGRESS_LIST_URL = "https://reg.ntuh.gov.tw/WebReg/WebReg/ClinicCurrentLightNo"
BRANCH_CODE = "T0"
SUPPORTED_DEPARTMENT = "OPH"
# Afternoon hours come from the evidence. Morning session hours are unverified
# and outside the supported scope.
SESSION_WINDOWS = {
    ClinicSession.AFTERNOON: (time(13, 30), time(16, 30)),
}
WINDOW_BUFFER = timedelta(minutes=10)

# One read per source every 2 to 3 minutes. The one-minute cron only offers the
# reader a chance to read; the reader skips ticks inside the interval.
MIN_READ_INTERVAL = timedelta(minutes=2)
# Duplicate reads of the same clinic in one tick reuse the same result.
SAME_READ_WINDOW = timedelta(seconds=30)
# Matches the scheduler and Start freshness bound.
FRESH_MAX_AGE = timedelta(minutes=2)
RETRY_BACKOFF = (timedelta(minutes=1), timedelta(minutes=2), timedelta(minutes=4))
RETRY_AFTER_CAP = timedelta(minutes=10)
REQUEST_TIMEOUT_SECONDS = 10
MAX_BODY_CHARS = 2_000_000
STATE_KEY = "ntuh_reader_state"
USER_AGENT = "next-is-you/1.0 (family-internal, non-commercial; one read per 2-3 min)"

_ROW_FIELDS = {
    "room": {"room", "診間"},
    "doctor": {"doctor", "醫師"},
    "clinic_type": {"clinic type", "type", "門診別"},
    "current": {"current light", "current light indicator", "目前燈號"},
}
_TRANSIENT_STATUSES = {408, 429}
_DENIED_STATUSES = {401, 403, 451}


@dataclass(frozen=True, slots=True)
class FetchedPage:
    status: int
    body: str
    retry_after: int | None = None


Fetcher = Callable[[str], Awaitable[FetchedPage]]


class ReaderState(Protocol):
    async def get(self, key: str) -> Any: ...

    async def put(self, key: str, value: Any) -> None: ...


@dataclass(frozen=True, slots=True)
class ClinicKey:
    room: str
    doctor: str
    clinic_type: str


@dataclass(frozen=True, slots=True)
class ListRow:
    room: str
    doctor: str
    clinic_type: str
    current: str


def parse_clinic_key(clinic_code: str) -> ClinicKey | None:
    """Read `room/doctor/clinic type`, for example `11/Hsiao-Sang Chu/Dr. Appt.`."""
    parts = [part.strip() for part in clinic_code.split("/")]
    if len(parts) != 3 or not all(parts):
        return None
    return ClinicKey(*parts)


def progress_list_url() -> str:
    return f"{PROGRESS_LIST_URL}?{urlencode({'vHospCode': BRANCH_CODE})}"


def parse_progress_list(html: str) -> tuple[str, list[ListRow]]:
    """Return ("ok", rows) or a page-level failure ("challenge", "denied", "schema")."""
    collector = _TableCollector()
    try:
        collector.feed(html)
        collector.close()
    except (ValueError, AssertionError):
        return "schema", []
    marker = _page_status(" ".join(collector.text).casefold())
    if marker is not None:
        return marker.value, []
    for table in collector.tables:
        for index, header in enumerate(table):
            columns = _columns(header)
            if columns is None:
                continue
            data_rows = table[index + 1 :]
            if any(len(row) <= max(columns.values()) for row in data_rows):
                return "schema", []
            rows = [
                ListRow(*(row[columns[field]] for field in _ROW_FIELDS))
                for row in data_rows
            ]
            return "ok", rows
    return "schema", []


def _columns(header: list[str]) -> dict[str, int] | None:
    columns: dict[str, int] = {}
    for index, value in enumerate(header):
        label = value.strip().casefold()
        for field, aliases in _ROW_FIELDS.items():
            if label in aliases:
                columns.setdefault(field, index)
    return columns if set(columns) == set(_ROW_FIELDS) else None


def _norm(text: str) -> str:
    return "".join(character for character in text.casefold() if character.isalnum())


def _matches(row: ListRow, key: ClinicKey) -> bool:
    return (
        _norm(row.room) == _norm(key.room)
        and _norm(row.doctor) == _norm(key.doctor)
        and _norm(row.clinic_type) == _norm(key.clinic_type)
    )


def session_window(day: date, session: ClinicSession) -> tuple[datetime, datetime]:
    start, end = SESSION_WINDOWS[session]
    return (
        datetime.combine(day, start, TAIPEI),
        datetime.combine(day, end, TAIPEI),
    )


class NtuhProgressReader:
    """Reads the official progress list under the owner-approved cadence."""

    def __init__(self, state: ReaderState, fetch: Fetcher) -> None:
        self._state = state
        self._fetch = fetch

    async def observe(
        self, scope: ClinicScope, now: datetime
    ) -> QueueObservation | ReadSkipped | ReadFailed:
        return await self._read(scope, now, for_start=False)

    async def observe_for_start(
        self, scope: ClinicScope, now: datetime
    ) -> QueueObservation | ReadSkipped | ReadFailed:
        return await self._read(scope, now, for_start=True)

    async def _read(
        self, scope: ClinicScope, now: datetime, *, for_start: bool
    ) -> QueueObservation | ReadSkipped | ReadFailed:
        key = parse_clinic_key(scope.clinic_code)
        if (
            scope.hospital != Hospital.NTUH_MAIN
            or scope.department_code != SUPPORTED_DEPARTMENT
            or scope.session not in SESSION_WINDOWS
            or key is None
        ):
            return ReadFailed("scope_mismatch", "scope_mismatch")

        start, end = session_window(scope.visit_date, scope.session)
        if now < start - WINDOW_BUFFER:
            return ReadSkipped("before_session")
        if now >= end + WINDOW_BUFFER:
            return ReadSkipped("session_ended")

        source = f"{BRANCH_CODE}|{scope.department_code}|{scope.session}"
        day = scope.visit_date.isoformat()
        clinic_id = json.dumps(
            [_norm(key.room), _norm(key.doctor), _norm(key.clinic_type)],
            separators=(",", ":"),
        )
        entry_key = f"{source}|clinic|{clinic_id}|{day}"
        blocked_key = f"{source}|blocked|{day}"
        states = await self._load()
        entry = states.setdefault(entry_key, {})
        legacy_entry = states.get(f"{source}|{scope.visit_date}", {})
        if legacy_entry.get("blocked"):
            states[blocked_key] = {"blocked": True}
            await self._save(states, scope.visit_date)
            return ReadFailed("unavailable", "access_denied")
        if entry.get("ended"):
            return ReadSkipped("session_ended")
        if states.get(blocked_key, {}).get("blocked"):
            return ReadFailed("unavailable", "access_denied")

        read_at = _parse(entry.get("read_at"))
        age = now - read_at if read_at is not None else None
        result = entry.get("result")
        # Start may reuse a recent good read for this clinic, never a failure.
        reuse = (
            result is not None
            and age is not None
            and timedelta(0) <= age
            and (
                age < SAME_READ_WINDOW
                or (for_start and age <= FRESH_MAX_AGE and "failure" not in result)
            )
        )
        if not reuse:
            due = _parse(entry.get("due_at"))
            if due is not None and now < due:
                if not for_start:
                    return ReadSkipped("not_due")
                return _failure(entry.get("result")) or ReadFailed(
                    "unavailable", "no_observation"
                )
            result = await self._fetch_result(key)
            self._record(entry, result, now)
            if result.get("blocked"):
                states[blocked_key] = {"blocked": True}
            read_at = now
            await self._save(states, scope.visit_date)

        failure = _failure(result)
        if failure is not None:
            return failure
        rows = [ListRow(*row) for row in result["rows"]]
        matched = [row for row in rows if _matches(row, key)]
        if not matched:
            if now >= end:
                entry["ended"] = True
                await self._save(states, scope.visit_date)
                return ReadSkipped("session_ended")
            return ReadFailed("unavailable", "empty_result")
        if len(matched) > 1:
            return ReadFailed("invalid", "ambiguous_match")
        text = matched[0].current.strip()
        if not text:
            return ReadFailed("unavailable", "no_observation")
        if not text.isascii() or not text.isdigit():
            return ReadFailed("invalid", "invalid_data")
        try:
            current_number = int(text)
        except ValueError:
            return ReadFailed("invalid", "invalid_data")
        if current_number < 1:
            return ReadFailed("invalid", "invalid_data")
        assert read_at is not None
        return QueueObservation(
            scope=scope,
            observed_at=read_at.isoformat(),
            current_number=current_number,
            # This validates the read and requested scope, not the physical
            # room light. Department/session are not labeled in source rows.
            trustworthy_current=True,
        )

    async def _fetch_result(self, key: ClinicKey) -> dict[str, Any]:
        try:
            page = await asyncio.wait_for(
                self._fetch(progress_list_url()), REQUEST_TIMEOUT_SECONDS
            )
        except TimeoutError:
            return _failed("unavailable", "timeout")
        except Exception:
            return _failed("unavailable", "no_observation")
        if page.status in _DENIED_STATUSES or 300 <= page.status < 400:
            return _failed("unavailable", "access_denied", blocked=True)
        if page.status in _TRANSIENT_STATUSES or page.status >= 500:
            result = _failed(
                "unavailable", "timeout" if page.status == 408 else "no_observation"
            )
            result["retry_after"] = page.retry_after
            return result
        if page.status != 200 or len(page.body) > MAX_BODY_CHARS:
            return _failed("invalid", "schema_drift")
        status, rows = parse_progress_list(page.body)
        if status in {"challenge", "denied"}:
            return _failed("unavailable", "access_denied", blocked=True)
        if status != "ok":
            return _failed("invalid", "schema_drift")
        matched = [row for row in rows if _matches(row, key)]
        return {
            "rows": [
                [row.room, row.doctor, row.clinic_type, row.current] for row in matched
            ],
        }

    def _record(self, entry: dict[str, Any], result: dict[str, Any], now: datetime):
        entry["read_at"] = now.isoformat()
        entry["result"] = result
        if "failure" not in result:
            entry["failures"] = 0
            entry["due_at"] = (now + MIN_READ_INTERVAL).isoformat()
            return
        failures = int(entry.get("failures", 0)) + 1
        entry["failures"] = failures
        delay = RETRY_BACKOFF[min(failures, len(RETRY_BACKOFF)) - 1]
        retry_after = result.get("retry_after")
        if isinstance(retry_after, int) and retry_after > 0:
            delay = max(
                delay,
                timedelta(
                    seconds=min(retry_after, int(RETRY_AFTER_CAP.total_seconds()))
                ),
            )
        entry["due_at"] = (now + delay).isoformat()

    async def _load(self) -> dict[str, dict[str, Any]]:
        raw = await self._state.get(STATE_KEY)
        try:
            loaded = json.loads(raw) if raw else {}
        except (TypeError, ValueError):
            return {}
        return loaded if isinstance(loaded, dict) else {}

    async def _save(self, states: dict[str, dict[str, Any]], today: date) -> None:
        kept = {
            entry_key: entry
            for entry_key, entry in states.items()
            if entry_key.endswith(f"|{today}")
            and ("|clinic|" in entry_key or "|blocked|" in entry_key)
        }
        await self._state.put(STATE_KEY, json.dumps(kept, separators=(",", ":")))


def _failed(status: str, reason: str, *, blocked: bool = False) -> dict[str, Any]:
    result: dict[str, Any] = {"failure": [status, reason]}
    if blocked:
        result["blocked"] = True
    return result


def _failure(result: dict[str, Any] | None) -> ReadFailed | None:
    if result is not None and "failure" in result:
        status, reason = result["failure"]
        return ReadFailed(status, reason)
    return None


def _parse(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def parse_retry_after(value: str | None, *, now: datetime | None = None) -> int | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    if value.isdigit():
        return int(value)
    try:
        retry_at = parsedate_to_datetime(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if retry_at.tzinfo is None:
        retry_at = retry_at.replace(tzinfo=timezone.utc)
    reference = now or datetime.now(timezone.utc)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    return max(0, math.ceil((retry_at - reference).total_seconds()))


class WorkersFetcher:
    """Plain GET through the Workers runtime; never follows redirects."""

    async def __call__(self, url: str) -> FetchedPage:
        from js import Object, fetch
        from pyodide.ffi import to_js

        options = to_js(
            {
                "method": "GET",
                "redirect": "manual",
                "headers": {"User-Agent": USER_AGENT, "Accept": "text/html"},
            },
            dict_converter=Object.fromEntries,
        )
        response = await fetch(url, options)
        retry_after = parse_retry_after(response.headers.get("Retry-After"))
        return FetchedPage(
            status=int(response.status),
            body=str(await response.text()) if int(response.status) == 200 else "",
            retry_after=retry_after,
        )
