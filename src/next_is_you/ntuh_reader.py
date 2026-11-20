"""NTU Hospital main campus ophthalmology reader for Start and scheduled checks.

The source is the official public registration progress list for branch T0,
read the way the site's own page reads it: a GET of the selector page for an
anti-forgery token and its cookies, then a POST to `DeptLightTable` carrying
the department and the session. The POST answers with an HTML fragment of
clinic cards holding room, doctor, clinic type and the current light.

The request contract and the fragment's markup were captured on 2026-10-29
(`research/private/source-evidence/ntuh-oph-clinic-end-2026-10-29.md`). The
same evidence shows the list is that session's schedule rather than the set of
clinics consulting right now, so row presence says a clinic is scheduled and
nothing more, and the current light is the number most recently called rather
than a queue position. Supported scope stays department OPH, afternoon session,
as Issue #20 set it.

The fragment's "Last updated" text is render time and the detail page's
expected call number is undefined, so neither is read. Freshness is the time
this reader fetched the page; it is never taken from the page.

Live hospital behavior is unverified. Tests drive this module with fixture
pages and an injected fetcher and never contact the hospital.
Each clinic keeps its own transient read state; cross-clinic sharing is outside
this ticket and may be considered as a future optimization.
"""

from __future__ import annotations

import asyncio
import json
import math
import re
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from typing import Any, Awaitable, Callable, Mapping, Protocol
from urllib.parse import urlencode

from next_is_you.domain import (
    ClinicOption,
    clinic_label,
    ClinicMatch,
    ClinicRoster,
    ClinicScope,
    ClinicSession,
    MatchKind,
    MatchQuery,
    QueueObservation,
    ReadFailed,
    ReadSkipped,
    RosterQuery,
)
from next_is_you.source_samples import _page_status
from next_is_you.persistence import TAIPEI

# Both hosts serve the same application; this one is what the owner opens and
# what the organizer progress link already points at. The reader stays behind
# NTUH_READER_ENABLED. Trust means a fresh, exact source read, not verified
# accuracy against the room's physical indicator.
WEBREG_BASE = "https://registration.ntuh.gov.tw/WebReg/WebReg"
SELECTOR_PATH = f"{WEBREG_BASE}/ClinicCurrentLightNo"
LIGHT_TABLE_URL = f"{WEBREG_BASE}/DeptLightTable"
SCHEDULE_PATH = f"{WEBREG_BASE}/RegDeptSchedule"
HOSPITAL_ID = "ntuh-main"
BRANCH_CODE = "T0"
SUPPORTED_DEPARTMENT = "OPH"
# RegDeptSchedule publishes the next two weekdays-filled calendar weeks; dates
# past this cap are not reachable until they enter the window and are reported
# as `visit_date_out_of_schedule_window` for the picker to degrade gracefully.
SCHEDULE_LOOKAHEAD_DAYS = 14
# One schedule read serves every match asked within this many seconds.
_SCHEDULE_MEMO_SECONDS = 60
# The site negotiates its language, and the rendering decides whether rows read
# "11 診 / 合成醫師丙" or "Room 11 / ...". The owner enters the clinic from a
# Traditional Chinese registration slip, so the reader pins that rendering.
UI_LANGUAGE = "zh-TW"
LANGUAGE_COOKIE = "Localization.CurrentUICulture"
# `DropDownAMPM` option values on the selector page.
AMPM_CODES = {
    ClinicSession.MORNING: "1",
    ClinicSession.AFTERNOON: "2",
    ClinicSession.EVENING: "3",
}
# The session's published start, Taipei time (#144). A card missing before it is
# not yet an unusable read. NTUH publishes no evening start the reader can read,
# so 18:00 stands in for it until a source gives one.
PUBLISHED_SESSION_START = {
    ClinicSession.MORNING: time(9, 0),
    ClinicSession.AFTERNOON: time(13, 30),
    ClinicSession.EVENING: time(18, 0),
}
# One read per source every 2 to 3 minutes while the clinic is calling. The
# one-minute cron only offers the reader a chance to read; the reader skips
# ticks inside the interval.
MIN_READ_INTERVAL = timedelta(minutes=2)
# Before the clinic has called anyone, reads only have to notice that it has
# started, so they are sparse.
PRE_ACTIVE_READ_INTERVAL = timedelta(minutes=5)
# Blank reads in a row that end the watch once the clinic has been calling.
END_BLANK_READS = 2
# Duplicate reads of the same clinic in one tick reuse the same result.
SAME_READ_WINDOW = timedelta(seconds=30)
# Matches the scheduler and Start freshness bound.
FRESH_MAX_AGE = timedelta(minutes=2)
RETRY_BACKOFF = (timedelta(minutes=1), timedelta(minutes=2), timedelta(minutes=4))
RETRY_AFTER_CAP = timedelta(minutes=10)
REQUEST_TIMEOUT_SECONDS = 10
MAX_BODY_CHARS = 2_000_000
# The dept-wide schedule page is larger than the per-session light table (the
# 2026-11-03 OPH showAll capture was 2.2 MB), so it carries its own ceiling.
MAX_SCHEDULE_BODY_CHARS = 3_500_000
STATE_KEY = "ntuh_reader_state"
USER_AGENT = "next-is-you/1.0 (family-internal, non-commercial; one read per 2-3 min)"

# Clinic card classes in the `DeptLightTable` fragment.
_ROW_CLASSES = {
    "room-number": "room",
    "clinic-doc-name": "doctor",
    "clinic-type": "clinic_type",
    "number": "current",
    "according-to-order": "check_in_order",
}
_REQUIRED_ROW_FIELDS = ("room", "doctor", "clinic_type", "current")
_VOID_ELEMENTS = frozenset(
    "area base br col embed hr img input link meta param source track wbr".split()
)
_TOKEN_FIELD = "__RequestVerificationToken"
_TRANSIENT_STATUSES = {408, 429}
_DENIED_STATUSES = {401, 403, 451}

# `RegDeptSchedule` session header text (left of the clinic cards). Any other
# string makes the session unparseable and the schedule read fails closed.
SCHEDULE_SESSION_TEXT = {
    "上午門診": ClinicSession.MORNING,
    "下午門診": ClinicSession.AFTERNOON,
    "夜間門診": ClinicSession.EVENING,
}
# A doctor-tag whose status marker is one of these means the clinic will not
# run on that day. Other markers (`額滿`, `已逾當日掛號時間`, `代診不續掛`,
# `代診可續掛`, `僅存本院初診`, `本院初診`, `本科初診`, `本科複診`,
# `18:00開放`) only restrict REGISTRATION; a patient who already has a number
# still has a clinic, so the roster keeps those rows.
_SCHEDULE_CANCELLED_STATUSES = frozenset(("停診", "颱風停診"))
# `MM/DD` as rendered in the day-column header; a date more than seven days
# behind today rolls to next year so Dec→Jan edges stay correct.
_MONTH_DAY_RE = re.compile(r"\s*(\d{1,2})/(\d{1,2})")
# Card doc-name reads `doctor | NN 診`; the ` 診` suffix is dropped.
_DOC_NAME_RE = re.compile(r"\s*(?P<doctor>[^|]+?)\s*\|\s*(?P<room>[^\s]+)\s*診?\s*$")


@dataclass(frozen=True, slots=True)
class PageRequest:
    url: str
    method: str = "GET"
    headers: tuple[tuple[str, str], ...] = ()
    body: str | None = None


@dataclass(frozen=True, slots=True)
class FetchedPage:
    status: int
    body: str
    retry_after: int | None = None
    # `name=value` pairs taken from the response's Set-Cookie headers.
    cookies: tuple[str, ...] = ()


Fetcher = Callable[[PageRequest], Awaitable[FetchedPage]]


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
    # Non-empty when the card says the clinic calls by check-in order, in which
    # case the light number is not a called number.
    check_in_order: str = ""


@dataclass(frozen=True, slots=True)
class ScheduleRow:
    """One (date, session, room, doctor) slot the dept schedule publishes.

    `clinic_type` is the schedule-side 診別 (`角膜`, `網膜`, `教學門診` ...)
    which uses a different vocabulary from the today-side light-table
    `clinic_type` (`醫師約診`, `特別門診` ...). Pre-flight validation matches on
    `(visit_date, session, room, doctor)` only, and the visit-day read finds
    the card by room and doctor too (`_identify`). A same-day Start may update
    the stored clinic code to the matched card's code; scheduled reads do not
    depend on that update.
    """

    visit_date: date
    session: ClinicSession
    room: str
    doctor: str
    clinic_type: str
    status: str
    # The department or specialty text before the `|` in `.sub-spec`
    # (`一般眼科 | 角膜`); empty when the card shows none.
    department: str = ""


_SESSION_NAMES = {
    ClinicSession.MORNING: "早診",
    ClinicSession.AFTERNOON: "午診",
    ClinicSession.EVENING: "晚診",
}


def _details(*pairs: tuple[str, str]) -> tuple[tuple[str, str], ...]:
    """Keep the published fields, in order; an unpublished one is left out."""
    return tuple((name, value.strip()) for name, value in pairs if value.strip())


def parse_clinic_key(clinic_code: str) -> ClinicKey | None:
    """Read `room/doctor/clinic type`, for example `11/Hsiao-Sang Chu/Dr. Appt.`."""
    parts = [part.strip() for part in clinic_code.split("/")]
    if len(parts) != 3 or not all(parts):
        return None
    return ClinicKey(*parts)


def selector_page_url() -> str:
    """The page whose GET carries the anti-forgery token and the session cookies."""
    return f"{SELECTOR_PATH}?{urlencode({'vHospCode': BRANCH_CODE})}"


def schedule_url(department_code: str) -> str:
    """The dept-wide schedule for the active 14-day window, Traditional Chinese."""
    return f"{SCHEDULE_PATH}?{
        urlencode(
            {
                'vhospCode': BRANCH_CODE,
                'showBlock': 'A',
                'vDeptCode': department_code,
                'realSubDeptCode': 'showAll',
            }
        )
    }"


def _resolve_schedule_date(month: int, day: int, today: date) -> date | None:
    """`MM/DD` on the day-column has no year; roll Dec→Jan forward from today."""
    try:
        candidate = date(today.year, month, day)
    except ValueError:
        return None
    if candidate < today - timedelta(days=7):
        try:
            return date(today.year + 1, month, day)
        except ValueError:
            return None
    return candidate


class _LightTableCollector(HTMLParser):
    """Collect the fragment's clinic cards, each an `open-link` anchor."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.cards: list[dict[str, str]] = []
        self.text: list[str] = []
        self._card: dict[str, str] | None = None
        self._card_depth = 0
        self._field: str | None = None
        self._field_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _VOID_ELEMENTS:
            return
        classes = set()
        for name, value in attrs:
            if name == "class" and value:
                classes = set(value.split())
        if self._card is None:
            if tag == "a" and "open-link" in classes:
                self._card = {}
                self._card_depth = 1
            return
        self._card_depth += 1
        if self._field is not None:
            self._field_depth += 1
            return
        for css, field in _ROW_CLASSES.items():
            if css in classes:
                self._field = field
                self._field_depth = 1
                self._card.setdefault(field, "")
                return

    def handle_endtag(self, tag: str) -> None:
        if tag in _VOID_ELEMENTS or self._card is None:
            return
        if self._field is not None:
            self._field_depth -= 1
            if self._field_depth == 0:
                self._field = None
        self._card_depth -= 1
        if self._card_depth == 0:
            self.cards.append(self._card)
            self._card = None

    def handle_data(self, data: str) -> None:
        self.text.append(data)
        if self._card is not None and self._field is not None:
            self._card[self._field] = (self._card[self._field] + data).strip()


def parse_light_table(html: str) -> tuple[str, list[ListRow]]:
    """Return ("ok", rows) or a page-level failure ("challenge", "denied", "schema")."""
    collector = _LightTableCollector()
    try:
        collector.feed(html)
        collector.close()
    except (ValueError, AssertionError):
        return "schema", []
    marker = _page_status(" ".join(collector.text).casefold())
    if marker is not None:
        return marker.value, []
    if not collector.cards:
        return "schema", []
    rows = []
    for card in collector.cards:
        if any(field not in card for field in _REQUIRED_ROW_FIELDS):
            return "schema", []
        if not all(card[field] for field in ("room", "doctor", "clinic_type")):
            return "schema", []
        rows.append(
            ListRow(
                card["room"],
                card["doctor"],
                card["clinic_type"],
                card["current"],
                card.get("check_in_order", ""),
            )
        )
    return "ok", rows


class _ScheduleCollector(HTMLParser):
    """Walk `RegDeptSchedule` in document order and emit one row per card.

    Day blocks appear in chronological order; each day block has one or more
    session blocks (`上午門診` / `下午門診` / `夜間門診`), each with its own
    doctor-tag buttons. The current date and session are tracked as we walk,
    so a button inherits whichever date and session block it is nested under.
    """

    def __init__(self, today: date) -> None:
        super().__init__(convert_charrefs=True)
        self._today = today
        self.rows: list[ScheduleRow] = []
        self.text: list[str] = []
        self._current_date: date | None = None
        self._current_session: ClinicSession | None = None
        # A stack of (kind, depth) frames; `kind` names the text we are
        # collecting into (`day_date`, `session`, `doc_name`, `status`,
        # `sub_spec`), `depth` is the open-tag depth when the frame started.
        # The frame is popped once endtag brings depth back below its start.
        self._frames: list[tuple[str, int]] = []
        self._depth = 0
        self._in_button = 0
        self._card: dict[str, str] = {}
        self._buffers: dict[str, list[str]] = {
            "day_date": [],
            "session": [],
            "doc_name": [],
            "status": [],
            "sub_spec": [],
        }

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _VOID_ELEMENTS:
            return
        self._depth += 1
        # Some rows carry two `class="..."` attributes on the same tag (the
        # live page's own markup is invalid). Union them instead of letting
        # the second clobber the first.
        classes: set[str] = set()
        style = ""
        for name, value in attrs:
            if value is None:
                continue
            if name == "class":
                classes.update(value.split())
            elif name == "style":
                style = value

        # Day-column date: `<div class="date" style="text-align:center">`. The
        # inline style disambiguates it from the session header, which also
        # uses the `date` class on a `<span>`.
        if tag == "div" and "date" in classes and "text-align:center" in style:
            self._frames.append(("day_date", self._depth))
            self._buffers["day_date"] = []
            return
        # Session header: `<span class="me-2 date">上午門診</span>`.
        if tag == "span" and "me-2" in classes and "date" in classes:
            self._frames.append(("session", self._depth))
            self._buffers["session"] = []
            return
        # Clinic card button.
        if tag == "button" and "doctor-tag" in classes:
            self._in_button = self._depth
            self._card = {"status": ""}
            return
        if self._in_button == 0:
            return
        # Fields inside a card button.
        if "doc-name" in classes:
            self._frames.append(("doc_name", self._depth))
            self._buffers["doc_name"] = []
            return
        if "first-reg" in classes:
            self._frames.append(("status", self._depth))
            self._buffers["status"] = []
            return
        if "sub-spec" in classes:
            self._frames.append(("sub_spec", self._depth))
            self._buffers["sub_spec"] = []
            return

    def handle_endtag(self, tag: str) -> None:
        if tag in _VOID_ELEMENTS:
            return
        depth = self._depth
        self._depth = max(0, self._depth - 1)
        # Close any frames that end at or above this depth.
        while self._frames and self._frames[-1][1] >= depth:
            kind, _ = self._frames.pop()
            self._on_frame_end(kind)
        if self._in_button and depth <= self._in_button:
            self._on_button_end()
            self._in_button = 0

    def handle_data(self, data: str) -> None:
        self.text.append(data)
        if not self._frames:
            return
        kind = self._frames[-1][0]
        self._buffers[kind].append(data)

    def _on_frame_end(self, kind: str) -> None:
        text = "".join(self._buffers[kind]).strip()
        if kind == "day_date":
            match = _MONTH_DAY_RE.match(text)
            if match is not None:
                resolved = _resolve_schedule_date(
                    int(match.group(1)), int(match.group(2)), self._today
                )
                if resolved is not None:
                    self._current_date = resolved
        elif kind == "session":
            self._current_session = SCHEDULE_SESSION_TEXT.get(text)
        elif self._in_button:
            if kind == "doc_name":
                self._card["doc_name"] = text
            elif kind == "status":
                self._card["status"] = text
            elif kind == "sub_spec":
                self._card["sub_spec"] = text

    def _on_button_end(self) -> None:
        doc_name = self._card.get("doc_name", "").strip()
        match = _DOC_NAME_RE.match(doc_name)
        if match is None or self._current_date is None or self._current_session is None:
            return
        sub_spec = self._card.get("sub_spec", "")
        clinic_type = (
            sub_spec.split("|")[-1].strip() if "|" in sub_spec else sub_spec.strip()
        )
        department = sub_spec.split("|")[0].strip() if "|" in sub_spec else ""
        self.rows.append(
            ScheduleRow(
                visit_date=self._current_date,
                session=self._current_session,
                room=match.group("room"),
                doctor=match.group("doctor"),
                clinic_type=clinic_type,
                status=self._card.get("status", ""),
                department=department,
            )
        )


def parse_schedule(html: str, today: date) -> tuple[str, list[ScheduleRow]]:
    """Return `("ok", rows)` or a page-level failure reason for the schedule.

    `today` resolves the day-column `MM/DD` to a full date; use the Taipei date
    the caller is working against (the one that opens the picker's window).
    """
    collector = _ScheduleCollector(today)
    try:
        collector.feed(html)
        collector.close()
    except (ValueError, AssertionError):
        return "schema_drift", []
    marker = _page_status(" ".join(collector.text).casefold())
    if marker is not None:
        return marker.value, []
    if not collector.rows:
        return "schema_drift", []
    return "ok", collector.rows


class _TokenCollector(HTMLParser):
    """Read the first anti-forgery token the selector page renders."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.token: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "input" or self.token is not None:
            return
        values = dict(attrs)
        if values.get("name") == _TOKEN_FIELD and values.get("value"):
            self.token = values["value"]


def parse_request_token(html: str) -> str | None:
    collector = _TokenCollector()
    try:
        collector.feed(html)
        collector.close()
    except (ValueError, AssertionError):
        return None
    return collector.token


def _norm(text: str) -> str:
    return "".join(character for character in text.casefold() if character.isalnum())


def _room_norm(text: str) -> str:
    """A room without its 診 suffix: the schedule writes `03`, the card `03 診`."""
    return _norm(text).removesuffix("診")


def _matches(row: ListRow, key: ClinicKey) -> bool:
    return (
        _room_norm(row.room) == _room_norm(key.room)
        and _norm(row.doctor) == _norm(key.doctor)
        and _norm(row.clinic_type) == _norm(key.clinic_type)
    )


_SUBSTITUTE_MARKS = ("(代)", "（代）")


def _is_substitute(row: ListRow) -> bool:
    doctor = "".join(row.doctor.split())
    return any(mark in doctor for mark in _SUBSTITUTE_MARKS)


def _identify(rows: list[ListRow], key: ClinicKey) -> tuple[list[ListRow], bool]:
    """The visit-day cards that are the visit's clinic, in one session's list.

    A visit picked from the clinic schedule stores the schedule's 診別, which
    shares almost no vocabulary with the card's clinic type, so identity is the
    room and the doctor. A card that also agrees on the clinic type wins, so a
    doctor with two cards in one room is told apart when the visit names one.
    With the booked doctor absent, a substitute card (`(代)`) in the same room
    stands in for the visit and is reported as such.

    Returns the matching cards and whether they are substitute cards. More than
    one card means the answer is ambiguous; none means the card was not found.
    """
    exact = [row for row in rows if _matches(row, key)]
    if exact:
        return exact, False
    in_room = [row for row in rows if _room_norm(row.room) == _room_norm(key.room)]
    booked = [row for row in in_room if _norm(row.doctor) == _norm(key.doctor)]
    if booked:
        return booked, False
    return [row for row in in_room if _is_substitute(row)], True


def _unpublished_window(today: date, visit_date: date) -> tuple[date, datetime]:
    """NTUH's stated rule for a day it has not published: (end date, release time).

    The clinic schedule ends 14 days after today, and a day opens at 00:00 Taipei
    14 days before it. One place, so the setup form and Start refusal agree.
    """
    lookahead = timedelta(days=SCHEDULE_LOOKAHEAD_DAYS)
    return today + lookahead, datetime.combine(
        visit_date - lookahead, time(0, 0), tzinfo=TAIPEI
    )


class NtuhProgressReader:
    """Reads the official progress list under the owner-approved cadence."""

    def __init__(self, state: ReaderState, fetch: Fetcher) -> None:
        self._state = state
        self._fetch = fetch
        self._schedule_memo: dict[
            tuple[str, date], tuple[datetime, str, list[ScheduleRow]]
        ] = {}

    async def observe(
        self, scope: ClinicScope, now: datetime
    ) -> QueueObservation | ReadSkipped | ReadFailed:
        return await self._read(scope, now, for_start=False)

    async def observe_for_start(
        self, scope: ClinicScope, now: datetime
    ) -> QueueObservation | ReadSkipped | ReadFailed:
        return await self._read(scope, now, for_start=True)

    async def list_clinics(self, query: RosterQuery, now: datetime) -> ClinicRoster:
        """List the department's clinics for the setup picker.

        Dispatches on `visit_date`: today reads the live light-table (one POST
        per session), a date in `[today+1, today+14]` reads the 14-day
        dept-wide `RegDeptSchedule` (one GET for the whole window, filtered to
        the requested date), a date past `today+14` returns
        `visit_date_out_of_schedule_window`, and a date before today returns
        `visit_date_past`. Any read that is not a clean card list makes the
        whole roster unavailable, so the picker falls back to manual entry
        rather than offering a partial list.
        """
        if (
            query.hospital != HOSPITAL_ID
            or query.department_code != SUPPORTED_DEPARTMENT
        ):
            return ClinicRoster(False, (), "scope_mismatch")
        today = now.astimezone(TAIPEI).date()
        if query.visit_date < today:
            return ClinicRoster(False, (), "visit_date_past")
        days_ahead = (query.visit_date - today).days
        if days_ahead == 0:
            return await self._list_today_roster(query.department_code)
        if days_ahead > SCHEDULE_LOOKAHEAD_DAYS:
            # NTUH states its rule: schedule from midnight 14 days before
            # consultation, so a day opens at 00:00 Taipei 14 days earlier.
            schedule_end, release_time = _unpublished_window(today, query.visit_date)
            return ClinicRoster(
                False,
                (),
                "visit_date_out_of_schedule_window",
                schedule_end=schedule_end,
                release_time=release_time,
            )
        return await self._list_future_schedule(query, today)

    async def _future_schedule_rows(
        self, department_code: str, today: date, memo_at: datetime | None = None
    ) -> tuple[str, list[ScheduleRow]]:
        """The department's schedule rows, or the status the read failed with.

        With `memo_at`, a read made within `_SCHEDULE_MEMO_SECONDS` is reused, so a
        sweep matching many drafts of one department costs the hospital one request.
        Only a clean read is remembered, so a transient failure is retried by the
        next draft, and entries of earlier days are dropped.
        """
        memo_key = (department_code, today)
        if memo_at is not None:
            memo = self._schedule_memo.get(memo_key)
            if memo is not None and 0 <= (memo_at - memo[0]).total_seconds() < (
                _SCHEDULE_MEMO_SECONDS
            ):
                return memo[1], memo[2]
        try:
            status, rows = await asyncio.wait_for(
                self._fetch_schedule_rows(department_code, today),
                REQUEST_TIMEOUT_SECONDS,
            )
        except TimeoutError:
            status, rows = "timeout", []
        except Exception:
            status, rows = "no_observation", []
        if memo_at is not None and status == "ok":
            self._schedule_memo = {
                key: value
                for key, value in self._schedule_memo.items()
                if key[1] == today
            }
            self._schedule_memo[memo_key] = (memo_at, status, rows)
        return status, rows

    async def match_clinic(self, query: MatchQuery, now: datetime) -> ClinicMatch:
        """Decide whether a stored draft is on NTUH's clinic schedule.

        Matches on (session, room, doctor) and ignores the clinic type, because
        the schedule's 診別 and the light table's clinic type use different
        vocabularies. A matched answer carries the canonical clinic code of the
        row found, so a same-day draft can be updated to what monitoring reads.
        A row marked `停診` or `颱風停診` answers as cancelled by the hospital.
        """
        if (
            query.hospital != HOSPITAL_ID
            or query.department_code != SUPPORTED_DEPARTMENT
        ):
            return ClinicMatch(MatchKind.UNAVAILABLE, reason="scope_mismatch")
        today = now.astimezone(TAIPEI).date()
        if query.visit_date < today:
            return ClinicMatch(MatchKind.UNAVAILABLE, reason="visit_date_past")
        days_ahead = (query.visit_date - today).days
        if days_ahead > SCHEDULE_LOOKAHEAD_DAYS:
            schedule_end, release_time = _unpublished_window(today, query.visit_date)
            return ClinicMatch(
                MatchKind.NOT_YET_PUBLISHED,
                schedule_end=schedule_end,
                release_time=release_time,
            )
        key = parse_clinic_key(query.clinic_code)
        if key is None:
            return ClinicMatch(MatchKind.UNAVAILABLE, reason="invalid_data")

        def same_clinic(session: ClinicSession, room: str, doctor: str) -> bool:
            return (
                session == query.session
                and _room_norm(room) == _room_norm(key.room)
                and _norm(doctor) == _norm(key.doctor)
            )

        if days_ahead == 0:
            roster = await self._list_today_roster(query.department_code)
            if not roster.available:
                return ClinicMatch(MatchKind.UNAVAILABLE, reason=roster.reason)
            # The same identification the visit-day read uses, so Start and the
            # scheduled read can never disagree about which card is the visit's.
            cards, substitute = _identify(
                [
                    ListRow(o.room, o.doctor, o.clinic_type, "")
                    for o in roster.clinics
                    if o.session == query.session
                ],
                key,
            )
            if not cards:
                return ClinicMatch(MatchKind.NOT_SCHEDULED)
            if len(cards) > 1:
                return ClinicMatch(MatchKind.UNAVAILABLE, reason="ambiguous_match")
            if substitute:
                # The booked doctor stays on the visit; only the card differs.
                return ClinicMatch(
                    MatchKind.MATCHED, query.clinic_code, substitute_doctor=True
                )
            card = cards[0]
            return ClinicMatch(
                MatchKind.MATCHED, f"{card.room}/{card.doctor}/{card.clinic_type}"
            )

        status, rows = await self._future_schedule_rows(
            query.department_code, today, memo_at=now
        )
        if status != "ok":
            return ClinicMatch(MatchKind.UNAVAILABLE, reason=status)
        day_rows = [row for row in rows if row.visit_date == query.visit_date]
        live = [r for r in day_rows if r.status not in _SCHEDULE_CANCELLED_STATUSES]
        found_row = next(
            (r for r in live if same_clinic(r.session, r.room, r.doctor)), None
        )
        if found_row is not None:
            return ClinicMatch(
                MatchKind.MATCHED,
                f"{found_row.room}/{found_row.doctor}/{found_row.clinic_type}",
            )
        if any(
            same_clinic(r.session, r.room, r.doctor)
            for r in day_rows
            if r.status in _SCHEDULE_CANCELLED_STATUSES
        ):
            return ClinicMatch(MatchKind.CANCELLED)
        if not live:
            return ClinicMatch(MatchKind.UNAVAILABLE, reason="no_observation")
        return ClinicMatch(MatchKind.NOT_SCHEDULED)

    async def _list_today_roster(self, department_code: str) -> ClinicRoster:
        """Today's roster, merged across all three sessions from the light table."""
        options: list[ClinicOption] = []
        for session in AMPM_CODES:
            status, rows = await self._fetch_session_rows(department_code, session)
            if status != "ok":
                return ClinicRoster(False, (), status)
            options.extend(
                ClinicOption(
                    session=session,
                    room=row.room,
                    doctor=row.doctor,
                    clinic_type=row.clinic_type,
                    clinic_code=f"{row.room}/{row.doctor}/{row.clinic_type}",
                    label=clinic_label(row.room, row.doctor, _SESSION_NAMES[session]),
                    details=_details(
                        ("診間", row.room),
                        ("醫師", row.doctor),
                        ("診別", row.clinic_type),
                        ("時段", _SESSION_NAMES[session]),
                    ),
                )
                for row in rows
            )
        return ClinicRoster(True, tuple(options), "ok")

    async def _list_future_schedule(
        self, query: RosterQuery, today: date
    ) -> ClinicRoster:
        """A future date inside the 14-day window, filtered from the schedule.

        Cancelled rows (`停診`, `颱風停診`) are dropped; other status markers
        (`額滿`, `已逾當日掛號時間`, 代診-related and restricted-registration
        markers) only limit new registration and leave the clinic running, so
        a holder of an existing number still has a clinic and the row stays.
        """
        status, rows = await self._future_schedule_rows(query.department_code, today)
        if status != "ok":
            return ClinicRoster(False, (), status)
        matching = [
            row
            for row in rows
            if row.visit_date == query.visit_date
            and row.status not in _SCHEDULE_CANCELLED_STATUSES
        ]
        if not matching:
            return ClinicRoster(False, (), "no_observation")
        options = tuple(
            ClinicOption(
                session=row.session,
                room=row.room,
                doctor=row.doctor,
                clinic_type=row.clinic_type,
                clinic_code=f"{row.room}/{row.doctor}/{row.clinic_type}",
                label=clinic_label(row.room, row.doctor, _SESSION_NAMES[row.session]),
                details=_details(
                    ("診間", row.room),
                    ("醫師", row.doctor),
                    ("科別", row.department),
                    ("診別", row.clinic_type),
                    ("時段", _SESSION_NAMES[row.session]),
                    ("狀態", row.status),
                ),
            )
            for row in matching
        )
        return ClinicRoster(True, options, "ok")

    async def _fetch_schedule_rows(
        self, department_code: str, today: date
    ) -> tuple[str, list[ScheduleRow]]:
        """One GET of the dept-wide 14-day schedule, parsed into rows."""
        page = await self._fetch(
            PageRequest(
                schedule_url(department_code),
                headers=_headers({"Cookie": f"{LANGUAGE_COOKIE}={UI_LANGUAGE}"}),
            )
        )
        failure = _transport_failure(page, max_body_chars=MAX_SCHEDULE_BODY_CHARS)
        if failure is not None:
            return failure["failure"][1], []
        return parse_schedule(page.body, today)

    async def _fetch_session_rows(
        self, department_code: str, session: ClinicSession
    ) -> tuple[str, list[ListRow]]:
        """A department+session's full card list, under one request budget."""
        try:
            return await asyncio.wait_for(
                self._session_rows(department_code, session), REQUEST_TIMEOUT_SECONDS
            )
        except TimeoutError:
            return "timeout", []
        except Exception:
            return "no_observation", []

    async def _session_rows(
        self, department_code: str, session: ClinicSession
    ) -> tuple[str, list[ListRow]]:
        selector = await self._fetch(
            PageRequest(
                selector_page_url(),
                headers=_headers({"Cookie": f"{LANGUAGE_COOKIE}={UI_LANGUAGE}"}),
            )
        )
        failure = _transport_failure(selector)
        if failure is not None:
            return failure["failure"][1], []
        token = parse_request_token(selector.body)
        if token is None:
            return "schema_drift", []
        page = await self._fetch(
            PageRequest(
                LIGHT_TABLE_URL,
                method="POST",
                headers=_headers(
                    {
                        "Content-Type": (
                            "application/x-www-form-urlencoded; charset=UTF-8"
                        ),
                        "X-Requested-With": "XMLHttpRequest",
                        "Referer": selector_page_url(),
                        "Cookie": _cookie_header(selector.cookies),
                    }
                ),
                body=urlencode(
                    {
                        _TOKEN_FIELD: token,
                        "vHospitalCode": BRANCH_CODE,
                        "DeptCode": department_code,
                        "RegionCode": "",
                        "AmpmCode": AMPM_CODES[session],
                    }
                ),
            )
        )
        failure = _transport_failure(page)
        if failure is not None:
            return failure["failure"][1], []
        status, rows = parse_light_table(page.body)
        return status, rows

    async def _read(
        self, scope: ClinicScope, now: datetime, *, for_start: bool
    ) -> QueueObservation | ReadSkipped | ReadFailed:
        key = parse_clinic_key(scope.clinic_code)
        if (
            scope.hospital != HOSPITAL_ID
            or scope.department_code != SUPPORTED_DEPARTMENT
            or scope.session not in AMPM_CODES
            or key is None
        ):
            return ReadFailed("scope_mismatch", "scope_mismatch")

        # The only clock left: reads happen on the day the owner entered, and
        # the scheduler's 23:59 Taipei cutoff closes the visit from above.
        if now.astimezone(TAIPEI).date() != scope.visit_date:
            return ReadSkipped("clinic_not_started")

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
            return ReadSkipped("clinic_ended")
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
            result = await self._fetch_result(key, scope)
            self._record(entry, result, now)
            if result.get("blocked"):
                states[blocked_key] = {"blocked": True}
            read_at = now
            await self._save(states, scope.visit_date)

        failure = _failure(result)
        if failure is not None:
            return failure
        rows = [ListRow(*row) for row in result["rows"]]
        substitute = bool(result.get("substitute"))
        if not rows:
            # Once the clinic has called, its card going away is how this source
            # ends a clinic. Before that, a card that is not listed is a finding.
            if entry.get("called"):
                return await self._without_a_number(
                    entry, states, scope, fetched=not reuse
                )
            # Before the session's published start the finding is recorded but
            # is not an unusable read, so nobody is messaged in the night.
            if not for_start and now < _published_start(scope):
                return ReadSkipped("card_not_listed")
            return ReadFailed("unavailable", "card_not_found")
        if len(rows) > 1:
            return ReadFailed("invalid", "ambiguous_match")
        # A card that calls by check-in order shows no called number at all, so
        # it is read as having none rather than as a number.
        text = "" if rows[0].check_in_order else rows[0].current.strip()
        if not text:
            skipped = await self._without_a_number(
                entry, states, scope, fetched=not reuse
            )
            if substitute and isinstance(skipped, ReadSkipped):
                return replace(skipped, substitute_doctor=True)
            return skipped
        if not text.isascii() or not text.isdigit():
            return ReadFailed("invalid", "invalid_data")
        try:
            current_number = int(text)
        except ValueError:
            return ReadFailed("invalid", "invalid_data")
        if current_number < 1:
            return ReadFailed("invalid", "invalid_data")
        await self._calling(entry, states, scope, now, fetched=not reuse)
        assert read_at is not None
        return QueueObservation(
            scope=scope,
            observed_at=read_at.isoformat(),
            current_number=current_number,
            # This validates the read and requested scope, not the physical
            # room light. Department/session are not labeled in source rows.
            trustworthy_current=True,
            substitute_doctor=substitute,
        )

    async def _calling(
        self,
        entry: dict[str, Any],
        states: dict[str, dict[str, Any]],
        scope: ClinicScope,
        now: datetime,
        *,
        fetched: bool,
    ) -> None:
        """A called number opens the watch and clears any run of blank reads."""
        if not fetched:
            return
        entry["called"] = True
        entry["blanks"] = 0
        entry["due_at"] = (now + MIN_READ_INTERVAL).isoformat()
        await self._save(states, scope.visit_date)

    async def _without_a_number(
        self,
        entry: dict[str, Any],
        states: dict[str, dict[str, Any]],
        scope: ClinicScope,
        *,
        fetched: bool,
    ) -> ReadSkipped | ReadFailed:
        """No called number: the clinic has not started, or it is over.

        A clinic that has never shown a number today has not started, and that
        is not a failed read. Once it has shown one, the number going blank is
        how this source ends a clinic; a run of blank reads confirms it before
        the watch stops for the day.
        """
        if not entry.get("called"):
            return ReadSkipped("clinic_not_started")
        blanks = int(entry.get("blanks", 0)) + 1 if fetched else int(entry["blanks"])
        entry["blanks"] = blanks
        if blanks >= END_BLANK_READS:
            entry["ended"] = True
        await self._save(states, scope.visit_date)
        if entry.get("ended"):
            return ReadSkipped("clinic_ended")
        return ReadFailed("unavailable", "empty_result")

    async def _fetch_result(self, key: ClinicKey, scope: ClinicScope) -> dict[str, Any]:
        """One read: GET the selector page for a token, then POST for the rows."""
        try:
            return await asyncio.wait_for(
                self._read_light_table(key, scope), REQUEST_TIMEOUT_SECONDS
            )
        except TimeoutError:
            return _failed("unavailable", "timeout")
        except Exception:
            return _failed("unavailable", "no_observation")

    async def _read_light_table(
        self, key: ClinicKey, scope: ClinicScope
    ) -> dict[str, Any]:
        selector = await self._fetch(
            PageRequest(
                selector_page_url(),
                headers=_headers({"Cookie": f"{LANGUAGE_COOKIE}={UI_LANGUAGE}"}),
            )
        )
        failure = _transport_failure(selector)
        if failure is not None:
            return failure
        token = parse_request_token(selector.body)
        if token is None:
            return _failed("invalid", "schema_drift")

        page = await self._fetch(
            PageRequest(
                LIGHT_TABLE_URL,
                method="POST",
                headers=_headers(
                    {
                        "Content-Type": (
                            "application/x-www-form-urlencoded; charset=UTF-8"
                        ),
                        "X-Requested-With": "XMLHttpRequest",
                        "Referer": selector_page_url(),
                        "Cookie": _cookie_header(selector.cookies),
                    }
                ),
                body=urlencode(
                    {
                        _TOKEN_FIELD: token,
                        "vHospitalCode": BRANCH_CODE,
                        "DeptCode": scope.department_code,
                        "RegionCode": "",
                        "AmpmCode": AMPM_CODES[scope.session],
                    }
                ),
            )
        )
        failure = _transport_failure(page)
        if failure is not None:
            return failure
        status, rows = parse_light_table(page.body)
        if status in {"challenge", "denied"}:
            return _failed("unavailable", "access_denied", blocked=True)
        if status != "ok":
            return _failed("invalid", "schema_drift")
        matched, substitute = _identify(rows, key)
        return {
            "rows": [
                [row.room, row.doctor, row.clinic_type, row.current, row.check_in_order]
                for row in matched
            ],
            "substitute": substitute,
        }

    def _record(self, entry: dict[str, Any], result: dict[str, Any], now: datetime):
        entry["read_at"] = now.isoformat()
        entry["result"] = result
        if "failure" not in result:
            entry["failures"] = 0
            # Dense checks are for a clinic that is calling; a clinic that has
            # not started yet is checked sparsely. `_calling` tightens this as
            # soon as a number appears.
            interval = (
                MIN_READ_INTERVAL if entry.get("called") else PRE_ACTIVE_READ_INTERVAL
            )
            entry["due_at"] = (now + interval).isoformat()
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


def _headers(extra: Mapping[str, str]) -> tuple[tuple[str, str], ...]:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html",
        "Accept-Language": UI_LANGUAGE,
        **extra,
    }
    return tuple(headers.items())


def _cookie_header(cookies: tuple[str, ...]) -> str:
    """Send back the session's own cookies, with the language kept pinned."""
    pairs = [
        cookie for cookie in cookies if not cookie.startswith(f"{LANGUAGE_COOKIE}=")
    ]
    pairs.append(f"{LANGUAGE_COOKIE}={UI_LANGUAGE}")
    return "; ".join(pairs)


def _transport_failure(
    page: FetchedPage, *, max_body_chars: int = MAX_BODY_CHARS
) -> dict[str, Any] | None:
    if page.status in _DENIED_STATUSES or 300 <= page.status < 400:
        return _failed("unavailable", "access_denied", blocked=True)
    if page.status in _TRANSIENT_STATUSES or page.status >= 500:
        result = _failed(
            "unavailable", "timeout" if page.status == 408 else "no_observation"
        )
        result["retry_after"] = page.retry_after
        return result
    if page.status != 200 or len(page.body) > max_body_chars:
        return _failed("invalid", "schema_drift")
    return None


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


def _published_start(scope: ClinicScope) -> datetime:
    return datetime.combine(
        scope.visit_date, PUBLISHED_SESSION_START[scope.session], tzinfo=TAIPEI
    )


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
    """One request through the Workers runtime; never follows redirects."""

    async def __call__(self, request: PageRequest) -> FetchedPage:
        from js import Object, fetch
        from pyodide.ffi import to_js

        options: dict[str, Any] = {
            "method": request.method,
            "redirect": "manual",
            "headers": dict(request.headers),
        }
        if request.body is not None:
            options["body"] = request.body
        response = await fetch(
            request.url, to_js(options, dict_converter=Object.fromEntries)
        )
        retry_after = parse_retry_after(response.headers.get("Retry-After"))
        return FetchedPage(
            status=int(response.status),
            body=str(await response.text()) if int(response.status) == 200 else "",
            retry_after=retry_after,
            cookies=_set_cookies(response.headers),
        )


def _set_cookies(headers: Any) -> tuple[str, ...]:
    """Read every Set-Cookie header, keeping only each cookie's name=value."""
    try:
        raw = list(headers.getSetCookie())
    except (AttributeError, TypeError):
        single = headers.get("Set-Cookie")
        raw = [single] if single else []
    return tuple(
        str(value).split(";", 1)[0].strip() for value in raw if str(value).strip()
    )
