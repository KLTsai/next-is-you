"""NTUH reader and gate lifecycle, fed with the values the reader's parsers return.

When the reader reads, how it matches a card, and how it fails and backs off are
tested on `ListRow`, `ProgressObservation` and `ScheduleRow` values served by the
fakes below (`ntuh_reads.py`), not on hand-built pages; the request shape (URLs,
headers, body, cookies, token) is asserted as sent. How the hospital's pages
parse is tested on real captures in `test_ntuh_capture_replay.py`. Fixture/mock
only; nothing here reaches the network.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path
from urllib.parse import parse_qsl

import pytest

from next_is_you.domain import (
    ClinicMatch,
    ClinicRoster,
    ClinicScope,
    ClinicSession,
    MatchKind,
    QueueObservation,
    ReadFailed,
    ReadSkipped,
    RosterQuery,
)
from next_is_you.ntuh_reader import (
    AMPM_CODES,
    DETAIL_PATH,
    LIGHT_TABLE_URL,
    SCHEDULE_PATH,
    FetchedPage,
    NtuhProgressReader,
    PageRequest,
    parse_clinic_key,
    parse_request_token,
    parse_retry_after,
    schedule_url,
    selector_page_url,
)
from next_is_you.persistence import CloudflareD1Store, Statement, VisitRepository
from ntuh_reads import (
    ListRead,
    ScheduleRead,
    card,
    listing,
    of_doctor,
    plus,
    progress,
    schedule,
    served,
    slot,
    with_rows,
)
from test_scheduler_outbox import (
    LocalContext,
    LocalD1,
    LocalDurableStorage,
)
from next_is_you.send_gate import SystemSendGate

from next_is_you.domain import clinic_label  # noqa: E402

# This module serves NTUH reader values (#205).
pytestmark = pytest.mark.usefixtures("serve_reader_values")

FIXTURES = Path(__file__).parent / "fixtures" / "hospitals"
CAPTURES = FIXTURES / "ntuh_captures"
# A morning-or-afternoon list of an invented ophthalmology department, as the
# reader returns it. `11 診/合成醫師丙/醫師約診` shows light 025.
PAGE = listing(
    card("07 診", "合成醫師甲", "普通門診", "012", service_id="8000007"),
    card("08 診", "合成醫師乙", "普通門診", "", service_id="8000008"),
    card("11 診", "合成醫師丙", "醫師約診", "025", service_id="8000011"),
    card("11 診", "合成醫師丁", "普通門診", "041", service_id="8000012"),
    card(
        "99 診",
        "合成醫師戊",
        "檢查門診",
        "",
        check_in_order="依報到順序",
        service_id="8000099",
    ),
)
# The real clinic selector page, its anti-forgery token value replaced by a
# placeholder (#205).
SELECTOR = (CAPTURES / "selector_2026-11-25_1015.html").read_text(encoding="utf-8")
_MORNING, _AFTERNOON = ClinicSession.MORNING, ClinicSession.AFTERNOON
_NOV_10, _NOV_11 = datetime(2026, 11, 10).date(), datetime(2026, 11, 11).date()
# An invented ophthalmology schedule for 11/10 and 11/11, as the reader returns it.
SCHEDULE_FIXTURE = schedule(
    slot(_NOV_10, _MORNING, "03", "合成醫師甲", "角膜", "", "一般眼科"),
    slot(_NOV_10, _MORNING, "05", "合成醫師乙", "網膜", "額滿", "一般眼科"),
    slot(_NOV_10, _MORNING, "07", "合成醫師丙", "教學門診", "停診", "一般眼科"),
    slot(_NOV_10, _AFTERNOON, "11", "合成醫師丁", "青光眼", "", "一般眼科"),
    slot(_NOV_11, _MORNING, "03", "合成醫師戊", "葡萄膜炎", "", "一般眼科"),
    slot(_NOV_11, _MORNING, "06", "合成醫師己", "眼整型", "颱風停診", "一般眼科"),
)
DAY = datetime(2026, 10, 22).date()
# The schedule fixture covers 11/10 and 11/11; the simulated today is the day
# before so both are future dates inside the lookahead window.
SCHEDULE_SIM_TODAY = datetime(2026, 11, 9).date()
SCHEDULE_FIRST_VISIT = datetime(2026, 11, 10).date()
SCHEDULE_SECOND_VISIT = datetime(2026, 11, 11).date()
CLINIC = "11診/合成醫師丙/醫師約診"
OTHER_CLINIC = "07診/合成醫師甲/普通門診"
BLANK_CLINIC = "08診/合成醫師乙/普通門診"
CHECK_IN_ORDER_CLINIC = "99診/合成醫師戊/檢查門診"


def taipei(hour: int, minute: int, second: int = 0) -> datetime:
    return datetime(
        2026, 10, 22, hour, minute, second, tzinfo=timezone(timedelta(hours=8))
    )


def scope(
    clinic_code: str = CLINIC,
    *,
    session: ClinicSession = ClinicSession.AFTERNOON,
    department: str = "OPH",
    hospital: str = "ntuh-main",
) -> ClinicScope:
    return ClinicScope(hospital, DAY, department, clinic_code, session)


def page_with(current: str) -> ListRead:
    """`PAGE` with `current` as the light of the `11 診/合成醫師丙` card."""
    return listing(
        *(
            replace(row, current=current) if row.current == "025" else row
            for row in PAGE.rows
        )
    )


def _page(item) -> FetchedPage:
    """A response: an exception is raised, a reader value is `served`."""
    if isinstance(item, Exception):
        raise item
    if isinstance(item, FetchedPage):
        return item
    return FetchedPage(200, item if isinstance(item, str) else served(item))


class FakeSource:
    """Scripted source.

    One read is the session list (a GET of the selector page, then a POST for the
    clinic cards) until the card is found, then one GET of the card's detail page.
    The script holds one entry per read, a session list (`ListRead`). A detail
    read returns the card in its entry as the detail page (its number as the light
    and the highest called), which keeps list and detail in step; `details`
    scripts the detail reads on their own, and a test about the two disagreeing
    uses `TwoPageSource`. An exception instance is raised, and a `FetchedPage` or
    string is served as is. `links=False` drops the cards' detail links. A GET of
    the dept-wide schedule page returns `schedule`, when it is set.
    """

    SESSION_COOKIES = ("ASP.NET_SessionId=synthetic", "__RequestVerificationToken_X=t")

    def __init__(
        self, *script, selector=SELECTOR, schedule=None, details=None, links=True
    ) -> None:
        self.script = list(script)
        self.selector = selector
        self.schedule = schedule
        self.details = list(details) if details is not None else None
        self.links = links
        self.requests: list[PageRequest] = []
        self.reads: list[str] = []

    @property
    def urls(self) -> list[str]:
        """One entry per read: a list POST, or a detail GET."""
        return list(self.reads)

    @property
    def detail_requests(self) -> list[PageRequest]:
        return [r for r in self.requests if r.url.startswith(DETAIL_PATH)]

    def last_body(self) -> dict[str, str]:
        posts = [r for r in self.requests if r.method == "POST"]
        return dict(parse_qsl(posts[-1].body or "", keep_blank_values=True))

    def headers_of(self, request: PageRequest) -> dict[str, str]:
        return dict(request.headers)

    def _next(self):
        return self.script.pop(0) if len(self.script) > 1 else self.script[0]

    async def __call__(self, request: PageRequest) -> FetchedPage:
        self.requests.append(request)
        if request.url.startswith(DETAIL_PATH):
            return self._detail(request)
        if request.method == "GET":
            if request.url.startswith(SCHEDULE_PATH) and self.schedule is not None:
                return _page(self.schedule)
            page = _page(self.selector)
            return replace(page, cookies=self.SESSION_COOKIES)
        self.reads.append(LIGHT_TABLE_URL)
        item = self._next()
        if not self.links and isinstance(item, ListRead):
            item = listing(
                *(replace(row, service_id="") for row in item.rows), status=item.status
            )
        return _page(item)

    def _detail(self, request: PageRequest) -> FetchedPage:
        self.reads.append(DETAIL_PATH)
        if self.details is not None:
            item = self.details.pop(0) if len(self.details) > 1 else self.details[0]
            return _page(item)
        item = self._next()
        if not isinstance(item, ListRead) or item.status != "ok":
            return _page(item)
        service_id = parse_qsl(request.url.split("?", 1)[1])[0][1]
        row = next((r for r in item.rows if r.service_id == service_id), None)
        assert row is not None, f"no card links to {service_id}"
        number = int(row.current) if row.current.isdigit() else None
        return _page(
            progress(
                room=f"合成科 {row.room}",
                doctor=row.doctor,
                current=number or None,
                highest=number or None,
                check_in_order=bool(row.check_in_order),
            )
        )


class TwoPageSource:
    """A source whose session list and detail page are set independently.

    `listed` and `detail` may be a page, a `FetchedPage` or an exception to raise;
    `delay` makes every request take that long.
    """

    def __init__(self, listed, detail, *, delay: float = 0) -> None:
        self.listed, self.detail, self.delay = listed, detail, delay
        self.requests: list[PageRequest] = []

    @property
    def list_posts(self) -> int:
        return sum(request.method == "POST" for request in self.requests)

    @property
    def detail_urls(self) -> list[str]:
        return [r.url for r in self.requests if r.url.startswith(DETAIL_PATH)]

    async def __call__(self, request: PageRequest) -> FetchedPage:
        self.requests.append(request)
        if self.delay:
            await asyncio.sleep(self.delay)
        if request.url.startswith(DETAIL_PATH):
            return _page(self.detail)
        if request.method == "POST":
            return _page(self.listed)
        return replace(_page(SELECTOR), cookies=FakeSource.SESSION_COOKIES)


def reader(source, state: LocalDurableStorage | None = None):
    return NtuhProgressReader(state or LocalDurableStorage(), source)


def test_clinic_key_requires_room_doctor_and_type() -> None:
    assert parse_clinic_key(CLINIC) is not None
    assert parse_clinic_key("11診/合成醫師丙") is None
    assert parse_clinic_key("11診//醫師約診") is None


def test_selector_url_is_the_branch_page_the_owner_opens() -> None:
    expected = (
        "https://registration.ntuh.gov.tw/WebReg/WebReg/"
        "ClinicCurrentLightNo?vHospCode=T0"
    )
    assert selector_page_url() == expected


@pytest.mark.asyncio
async def test_a_read_posts_the_token_branch_department_and_session() -> None:
    source = FakeSource(PAGE)
    assert isinstance(
        await reader(source).observe(scope(), taipei(15, 0)), QueueObservation
    )

    get_request, post_request = source.requests
    assert get_request.url == selector_page_url() and get_request.method == "GET"
    assert post_request.url == LIGHT_TABLE_URL and post_request.method == "POST"
    assert source.last_body() == {
        "__RequestVerificationToken": parse_request_token(SELECTOR),
        "vHospitalCode": "T0",
        "DeptCode": "OPH",
        "RegionCode": "",
        "AmpmCode": AMPM_CODES[ClinicSession.AFTERNOON],
    }

    headers = source.headers_of(post_request)
    assert headers["X-Requested-With"] == "XMLHttpRequest"
    assert headers["Accept-Language"] == "zh-TW"
    # The session's own cookies go back, and the language stays pinned.
    for cookie in FakeSource.SESSION_COOKIES:
        assert cookie in headers["Cookie"]
    assert headers["Cookie"].count("Localization.CurrentUICulture=zh-TW") == 1


@pytest.mark.asyncio
async def test_a_missing_token_fails_closed_without_posting() -> None:
    # A real session list where the selector page was expected: it has no token.
    other_page = (CAPTURES / "list_oph_am_2026-11-20_1130.html").read_text("utf-8")
    source = FakeSource(PAGE, selector=other_page)
    result = await reader(source).observe(scope(), taipei(15, 0))
    assert result == ReadFailed("invalid", "schema_drift")
    assert source.urls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("selector", "expected"),
    [
        (FetchedPage(403, ""), ReadFailed("unavailable", "access_denied")),
        (FetchedPage(503, ""), ReadFailed("unavailable", "no_observation")),
        (TimeoutError(), ReadFailed("unavailable", "timeout")),
    ],
)
async def test_a_failed_selector_read_never_reaches_the_post(
    selector, expected
) -> None:
    source = FakeSource(PAGE, selector=selector)
    assert await reader(source).observe(scope(), taipei(15, 0)) == expected
    assert source.urls == []


@pytest.mark.asyncio
async def test_exact_match_returns_fresh_usable_observation_stamped_with_fetch_time():
    source = FakeSource(PAGE)
    observation = await reader(source).observe(scope(), taipei(15, 0))
    assert isinstance(observation, QueueObservation)
    assert observation.current_number == 25
    assert observation.trustworthy_current
    assert observation.is_comparable_to(scope())
    assert observation.observed_at == taipei(15, 0).isoformat()
    assert observation.source_updated_at is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "clinic",
    [
        "11診/合成醫師己/醫師約診",
        "12診/合成醫師丙/醫師約診",
    ],
)
async def test_a_room_or_doctor_mismatch_is_a_card_not_found(clinic: str) -> None:
    # Cards are listed from midnight, so a missing card is a finding the
    # organizer needs, not a clinic that has merely not started.
    result = await reader(FakeSource(PAGE)).observe(scope(clinic), taipei(15, 0))
    assert result == ReadFailed("unavailable", "card_not_found")


@pytest.mark.asyncio
async def test_the_clinic_type_is_not_an_identity_field() -> None:
    # Room 11 and 合成醫師丙 name the card; the schedule's 診別 and the card's
    # clinic type are different vocabularies and are never compared.
    result = await reader(FakeSource(PAGE)).observe(
        scope("11診/合成醫師丙/普通門診"), taipei(15, 0)
    )
    assert isinstance(result, QueueObservation)
    assert result.current_number == 25


@pytest.mark.asyncio
async def test_current_is_never_inferred_from_neighbors() -> None:
    result = await reader(FakeSource(PAGE)).observe(scope(BLANK_CLINIC), taipei(15, 0))
    assert result == ReadSkipped("clinic_not_started")


@pytest.mark.asyncio
async def test_a_check_in_order_clinic_reports_no_number() -> None:
    result = await reader(FakeSource(PAGE)).observe(
        scope(CHECK_IN_ORDER_CLINIC), taipei(15, 0)
    )
    assert result == ReadSkipped("clinic_not_started")


@pytest.mark.asyncio
@pytest.mark.parametrize("current", ["000", "abc", "²"])
async def test_zero_or_garbled_light_is_invalid_not_zero(current: str) -> None:
    result = await reader(FakeSource(page_with(current))).observe(
        scope(), taipei(15, 0)
    )
    assert result == ReadFailed("invalid", "invalid_data")


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["observe", "observe_for_start"])
async def test_non_ascii_numeric_light_fails_closed_for_each_read_path(method):
    result = await getattr(reader(FakeSource(page_with("²"))), method)(
        scope(), taipei(15, 0)
    )
    assert result == ReadFailed("invalid", "invalid_data")


@pytest.mark.asyncio
async def test_duplicate_exact_rows_are_ambiguous() -> None:
    duplicate = card("11 診", "合成醫師丙", "醫師約診", "026")
    result = await reader(FakeSource(plus(PAGE, duplicate))).observe(
        scope(), taipei(15, 0)
    )
    assert result == ReadFailed("invalid", "ambiguous_match")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad",
    [
        scope(department="MED"),
        scope(hospital="shin-kong-taipei"),
        scope("not-a-composite-code"),
    ],
)
async def test_unsupported_scope_is_rejected_without_a_request(bad) -> None:
    source = FakeSource(PAGE)
    result = await reader(source).observe(bad, taipei(15, 0))
    assert result == ReadFailed("scope_mismatch", "scope_mismatch")
    assert source.urls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("session", "hour"),
    [
        (ClinicSession.MORNING, 8),
        (ClinicSession.MORNING, 15),
        (ClinicSession.MORNING, 20),
        (ClinicSession.AFTERNOON, 15),
        (ClinicSession.AFTERNOON, 20),
        (ClinicSession.EVENING, 20),
    ],
)
async def test_every_session_is_read_at_any_hour_once_its_reads_began(session, hour):
    source = FakeSource(PAGE)
    observation = await reader(source).observe(scope(session=session), taipei(hour, 0))
    if session == ClinicSession.EVENING:
        # Nobody has observed an evening session: it is read, flagged and
        # recorded, and sends nothing (#163).
        assert observation == ReadSkipped(
            "unobserved_situation", unobserved="evening_session"
        )
    else:
        assert isinstance(observation, QueueObservation)
        assert observation.current_number == 25
    assert source.last_body()["AmpmCode"] == AMPM_CODES[session]


@pytest.mark.asyncio
async def test_no_wall_clock_session_boundary_exists_once_reads_began() -> None:
    source = FakeSource(PAGE)
    r = reader(source)
    # The old reader refused 13:19 and 16:40; both are ordinary reads now.
    for hour, minute in ((12, 30), (13, 19), (16, 40), (23, 58)):
        assert isinstance(
            await r.observe(scope(), taipei(hour, minute)), QueueObservation
        )
    assert len(source.urls) == 4


@pytest.mark.asyncio
async def test_reads_happen_only_on_the_day_the_owner_entered() -> None:
    source = FakeSource(PAGE)
    other_day = ClinicScope(
        "ntuh-main",
        DAY + timedelta(days=1),
        "OPH",
        CLINIC,
        ClinicSession.AFTERNOON,
    )
    skipped = ReadSkipped("clinic_not_started")
    assert await reader(source).observe(other_day, taipei(15, 0)) == skipped
    assert source.urls == []


@pytest.mark.asyncio
async def test_cadence_skips_ticks_inside_two_minutes_and_reads_at_two() -> None:
    source = FakeSource(PAGE)
    r = reader(source)
    assert isinstance(await r.observe(scope(), taipei(15, 0)), QueueObservation)
    assert await r.observe(scope(), taipei(15, 1)) == ReadSkipped("not_due")
    assert await r.observe(scope(), taipei(15, 1, 59)) == ReadSkipped("not_due")
    assert isinstance(await r.observe(scope(), taipei(15, 2)), QueueObservation)
    assert len(source.urls) == 2


@pytest.mark.asyncio
async def test_distinct_clinics_read_independently_and_save_only_their_rows() -> None:
    state = LocalDurableStorage()
    source = FakeSource(PAGE)
    r = reader(source, state)
    first = await r.observe(scope(), taipei(15, 0))
    second = await r.observe(scope(OTHER_CLINIC), taipei(15, 0, 1))
    assert first.current_number == 25 and second.current_number == 12
    assert len(source.urls) == 2
    saved = json.loads(await state.get("ntuh_reader_state"))
    assert len(saved) == 2
    serialized_results = [
        json.dumps(entry["result"], ensure_ascii=False) for entry in saved.values()
    ]
    assert any("合成醫師丙" in result for result in serialized_results)
    assert any("合成醫師甲" in result for result in serialized_results)
    assert all("合成醫師乙" not in result for result in serialized_results)


@pytest.mark.asyncio
async def test_saved_read_contains_only_rows_for_tracked_clinics() -> None:
    state = LocalDurableStorage()
    source = FakeSource(PAGE)
    r = reader(source, state)
    await r.observe(scope(), taipei(15, 0))
    saved = json.dumps(
        json.loads(await state.get("ntuh_reader_state")), ensure_ascii=False
    )
    assert "合成醫師丙" in saved
    assert "合成醫師甲" not in saved
    assert "合成醫師乙" not in saved


@pytest.mark.asyncio
async def test_start_reuses_a_fresh_read_but_reads_once_it_is_older_than_two_minutes():
    source = FakeSource(PAGE)
    r = reader(source)
    await r.observe(scope(), taipei(15, 0))
    assert isinstance(
        await r.observe_for_start(scope(), taipei(15, 1)), QueueObservation
    )
    assert len(source.urls) == 1
    assert isinstance(
        await r.observe_for_start(scope(), taipei(15, 2, 1)), QueueObservation
    )
    assert len(source.urls) == 2


@pytest.mark.asyncio
async def test_cadence_is_independent_for_each_clinic() -> None:
    source = FakeSource(PAGE)
    r = reader(source)
    second_scope = scope(OTHER_CLINIC)
    assert isinstance(await r.observe(scope(), taipei(15, 0)), QueueObservation)
    assert isinstance(await r.observe(second_scope, taipei(15, 0, 1)), QueueObservation)
    assert await r.observe(scope(), taipei(15, 1)) == ReadSkipped("not_due")
    assert await r.observe(second_scope, taipei(15, 1)) == ReadSkipped("not_due")
    assert isinstance(await r.observe(scope(), taipei(15, 2)), QueueObservation)
    assert isinstance(await r.observe(second_scope, taipei(15, 2, 1)), QueueObservation)
    assert len(source.urls) == 4


@pytest.mark.asyncio
async def test_start_reads_another_clinic_without_using_shared_state() -> None:
    source = FakeSource(PAGE)
    r = reader(source)
    second_scope = scope(OTHER_CLINIC)
    assert isinstance(await r.observe(scope(), taipei(15, 0)), QueueObservation)
    second_start = await r.observe_for_start(second_scope, taipei(15, 0, 1))
    assert isinstance(second_start, QueueObservation)
    assert second_start.current_number == 12
    assert len(source.urls) == 2


@pytest.mark.asyncio
async def test_state_survives_a_new_reader_instance() -> None:
    state = LocalDurableStorage()
    source = FakeSource(PAGE)
    await reader(source, state).observe(scope(), taipei(15, 0))
    assert await reader(source, state).observe(scope(), taipei(15, 1)) == ReadSkipped(
        "not_due"
    )
    assert len(source.urls) == 1


@pytest.mark.asyncio
async def test_transient_failures_back_off_one_two_then_four_minutes_capped() -> None:
    source = FakeSource(FetchedPage(503, ""))
    r = reader(source)
    reads = []
    for minute in range(0, 14):
        result = await r.observe(scope(), taipei(15, minute))
        if result != ReadSkipped("not_due"):
            reads.append(minute)
            assert result == ReadFailed("unavailable", "no_observation")
    assert reads == [0, 1, 3, 7, 11]
    assert len(source.urls) == 5


@pytest.mark.asyncio
async def test_timeout_is_transient_and_recovers_to_normal_cadence() -> None:
    source = FakeSource(TimeoutError(), PAGE)
    r = reader(source)
    assert await r.observe(scope(), taipei(15, 0)) == ReadFailed(
        "unavailable", "timeout"
    )
    assert await r.observe(scope(), taipei(15, 0, 30)) == ReadSkipped("not_due")
    assert isinstance(await r.observe(scope(), taipei(15, 1)), QueueObservation)
    assert await r.observe(scope(), taipei(15, 2)) == ReadSkipped("not_due")
    assert isinstance(await r.observe(scope(), taipei(15, 3)), QueueObservation)


@pytest.mark.asyncio
async def test_rate_limit_retry_after_extends_the_wait_within_a_cap() -> None:
    source = FakeSource(FetchedPage(429, "", retry_after=300), PAGE)
    r = reader(source)
    assert isinstance(await r.observe(scope(), taipei(15, 0)), ReadFailed)
    assert await r.observe(scope(), taipei(15, 4, 59)) == ReadSkipped("not_due")
    assert isinstance(await r.observe(scope(), taipei(15, 5)), QueueObservation)


@pytest.mark.asyncio
async def test_http_date_retry_after_extends_the_wait_within_a_cap() -> None:
    now = taipei(15, 0)
    assert parse_retry_after("300", now=now) == 300
    retry_at = taipei(15, 5).astimezone(timezone.utc)
    header = format_datetime(retry_at, usegmt=True)
    retry_after = parse_retry_after(header, now=now)
    assert retry_after == 300

    source = FakeSource(FetchedPage(503, "", retry_after=retry_after), PAGE)
    r = reader(source)
    assert isinstance(await r.observe(scope(), now), ReadFailed)
    assert await r.observe(scope(), taipei(15, 4, 59)) == ReadSkipped("not_due")
    assert isinstance(await r.observe(scope(), taipei(15, 5)), QueueObservation)


@pytest.mark.asyncio
async def test_start_does_not_hammer_the_source_during_backoff() -> None:
    source = FakeSource(FetchedPage(500, ""), PAGE)
    r = reader(source)
    await r.observe(scope(), taipei(15, 0))
    assert await r.observe_for_start(scope(), taipei(15, 0, 40)) == ReadFailed(
        "unavailable", "no_observation"
    )
    assert len(source.urls) == 1
    assert isinstance(
        await r.observe_for_start(scope(), taipei(15, 1)), QueueObservation
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "page",
    [
        FetchedPage(403, "Forbidden"),
        FetchedPage(401, ""),
        FetchedPage(302, ""),
        ListRead(status="challenge"),
        ListRead(status="denied"),
    ],
)
async def test_challenge_or_denial_stops_reading_the_source(page) -> None:
    source = FakeSource(page, PAGE)
    r = reader(source)
    denied = ReadFailed("unavailable", "access_denied")
    assert await r.observe(scope(), taipei(15, 0)) == denied
    assert await r.observe(scope(OTHER_CLINIC), taipei(15, 0, 1)) == denied
    for minute in (1, 3, 10, 30):
        assert await r.observe(scope(), taipei(15, minute)) == denied
        assert await r.observe_for_start(scope(), taipei(15, minute)) == denied
    assert len(source.urls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("page", [ListRead(status="schema"), FetchedPage(404, "")])
async def test_schema_change_fails_closed(page) -> None:
    result = await reader(FakeSource(page)).observe(scope(), taipei(15, 0))
    assert result == ReadFailed("invalid", "schema_drift")


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["observe", "observe_for_start"])
async def test_card_missing_its_number_is_schema_drift_not_a_clinic_end(method):
    # The list parser rejects a card that lost its number as "schema"; that is
    # drift, never the end of a clinic whose number went blank.
    source = FakeSource(ListRead(status="schema"))
    result = await getattr(reader(source), method)(scope(), taipei(16, 31))
    assert result == ReadFailed("invalid", "schema_drift")
    assert len(source.urls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "absent",
    [
        pytest.param(page_with(""), id="number-goes-blank"),
        pytest.param(
            with_rows(PAGE, of_doctor("合成醫師丙"), doctor="其他醫師"),
            id="card-disappears",
        ),
    ],
)
async def test_the_watch_ends_once_the_number_is_gone_for_two_reads(absent) -> None:
    # A card without a detail link is read from the list alone, as before #163.
    source = FakeSource(PAGE, absent, links=False)
    r = reader(source)
    # A number opens the watch.
    assert isinstance(await r.observe(scope(), taipei(15, 0)), QueueObservation)
    # One read without it is an unusable read, not the end: the source may yet
    # come back, and a single blank must not stop the watch for good.
    assert await r.observe(scope(), taipei(15, 2)) == ReadFailed(
        "unavailable", "empty_result"
    )
    assert await r.observe(scope(), taipei(15, 4)) == ReadSkipped("clinic_ended")
    # Ended means ended: no further reads that day.
    assert await r.observe(scope(), taipei(15, 6)) == ReadSkipped("clinic_ended")
    assert await r.observe_for_start(scope(), taipei(15, 8)) == ReadSkipped(
        "clinic_ended"
    )
    assert len(source.urls) == 3


@pytest.mark.asyncio
async def test_a_number_returning_clears_the_blank_run() -> None:
    source = FakeSource(PAGE, page_with(""), PAGE, PAGE, links=False)
    r = reader(source)
    assert isinstance(await r.observe(scope(), taipei(15, 0)), QueueObservation)
    assert await r.observe(scope(), taipei(15, 2)) == ReadFailed(
        "unavailable", "empty_result"
    )
    assert isinstance(await r.observe(scope(), taipei(15, 4)), QueueObservation)
    # The run restarts, so one later blank is again not the end.
    assert isinstance(await r.observe(scope(), taipei(15, 6)), QueueObservation)


@pytest.mark.asyncio
async def test_a_clinic_that_never_called_is_checked_sparsely() -> None:
    # The list alone is read sparsely until the card's detail page is found.
    source = FakeSource(page_with(""), links=False)
    r = reader(source)
    not_started = ReadSkipped("clinic_not_started")
    assert await r.observe(scope(), taipei(13, 0)) == not_started
    assert await r.observe(scope(), taipei(13, 2)) == ReadSkipped("not_due")
    assert await r.observe(scope(), taipei(13, 4, 59)) == ReadSkipped("not_due")
    assert await r.observe(scope(), taipei(13, 5)) == not_started
    assert len(source.urls) == 2


@pytest.mark.asyncio
async def test_the_first_number_switches_the_watch_to_the_dense_cadence() -> None:
    source = FakeSource(page_with(""), PAGE, links=False)
    r = reader(source)
    assert await r.observe(scope(), taipei(13, 0)) == ReadSkipped("clinic_not_started")
    # Sparse until it starts.
    assert await r.observe(scope(), taipei(13, 3)) == ReadSkipped("not_due")
    assert isinstance(await r.observe(scope(), taipei(13, 5)), QueueObservation)
    # Dense from the read that saw the number, not five minutes after it.
    assert await r.observe(scope(), taipei(13, 6)) == ReadSkipped("not_due")
    assert isinstance(await r.observe(scope(), taipei(13, 7)), QueueObservation)


# Roster listing for the setup picker


@pytest.mark.asyncio
async def test_list_clinics_merges_the_three_sessions() -> None:
    source = FakeSource(PAGE)
    roster = await reader(source).list_clinics(
        RosterQuery("ntuh-main", "OPH", DAY), taipei(14, 0)
    )
    assert roster.available and roster.reason == "ok"
    bodies = [
        dict(parse_qsl(request.body or "", keep_blank_values=True))
        for request in source.requests
        if request.method == "POST"
    ]
    # One request per session, each selecting its own roster.
    assert [body["AmpmCode"] for body in bodies] == [
        AMPM_CODES[session]
        for session in (
            ClinicSession.MORNING,
            ClinicSession.AFTERNOON,
            ClinicSession.EVENING,
        )
    ]
    # Five cards in the fixture, kept for each of the three sessions.
    assert len(roster.clinics) == 15
    assert {clinic.session for clinic in roster.clinics} == {
        ClinicSession.MORNING,
        ClinicSession.AFTERNOON,
        ClinicSession.EVENING,
    }
    afternoon = {
        clinic.clinic_code
        for clinic in roster.clinics
        if clinic.session is ClinicSession.AFTERNOON
    }
    assert "11 診/合成醫師丙/醫師約診" in afternoon


@pytest.mark.asyncio
async def test_today_roster_labels_and_details_match_the_light_table_card() -> None:
    # Fixture/mock: field by field against the card for 合成醫師丙 on the
    # captured light-table page (room 11 診, clinic type 醫師約診).
    source = FakeSource(PAGE)
    roster = await reader(source).list_clinics(
        RosterQuery("ntuh-main", "OPH", DAY), taipei(14, 0)
    )
    option = next(
        c
        for c in roster.clinics
        if c.clinic_code == "11 診/合成醫師丙/醫師約診"
        and c.session is ClinicSession.AFTERNOON
    )
    assert option.label == "11 診 · 合成醫師丙（午診）"
    assert option.details == (
        ("診間", "11 診"),
        ("醫師", "合成醫師丙"),
        ("診別", "醫師約診"),
        ("時段", "午診"),
    )
    assert all(c.label for c in roster.clinics)


@pytest.mark.asyncio
async def test_future_roster_labels_and_details_match_the_schedule_cards() -> None:
    # Fixture/mock: 11/10 schedule page. Card 乙 is 05 診, 一般眼科 | 網膜,
    # tagged 額滿; card 甲 is 03 診, 一般眼科 | 角膜 with no status tag.
    source = FakeSource(schedule=SCHEDULE_FIXTURE)
    roster = await reader(source).list_clinics(
        RosterQuery("ntuh-main", "OPH", SCHEDULE_FIRST_VISIT),
        _schedule_sim_now(),
    )
    by_doctor = {c.doctor: c for c in roster.clinics}
    assert by_doctor["合成醫師甲"].label == "03 · 合成醫師甲（早診）"
    assert by_doctor["合成醫師甲"].details == (
        ("診間", "03"),
        ("醫師", "合成醫師甲"),
        ("科別", "一般眼科"),
        ("診別", "角膜"),
        ("時段", "早診"),
    )
    assert by_doctor["合成醫師乙"].details == (
        ("診間", "05"),
        ("醫師", "合成醫師乙"),
        ("科別", "一般眼科"),
        ("診別", "網膜"),
        ("時段", "早診"),
        ("狀態", "額滿"),
    )
    assert by_doctor["合成醫師丁"].label == "11 · 合成醫師丁（午診）"
    assert all(c.label for c in roster.clinics)


@pytest.mark.asyncio
async def test_gate_roster_wire_carries_label_and_details() -> None:
    source = FakeSource(PAGE)
    _, gate = await gate_with_visit(source)
    result = await gate.list_clinics(
        "ntuh-main", "OPH", DAY.isoformat(), taipei(14, 0).isoformat()
    )
    first = result["clinics"][0]
    assert first["label"] == "07 診 · 合成醫師甲（早診）"
    assert first["details"][0] == {"label": "診間", "value": "07 診"}


def test_a_label_joins_only_the_segments_a_hospital_publishes() -> None:
    # A synthetic hospital without room numbers: no empty segment, no stray
    # separator.
    assert clinic_label("", "王醫師", "早診") == "王醫師（早診）"
    assert clinic_label("  ", "王醫師", "") == "王醫師"
    assert clinic_label("11 診", "王醫師", "午診") == "11 診 · 王醫師（午診）"


@pytest.mark.asyncio
async def test_list_clinics_rejects_past_date_without_fetching() -> None:
    # A past visit date can only produce `visit_date_past`; no source read is
    # worthwhile.
    source = FakeSource(PAGE)
    roster = await reader(source).list_clinics(
        RosterQuery("ntuh-main", "OPH", DAY - timedelta(days=1)), taipei(14, 0)
    )
    assert roster == ClinicRoster(False, (), "visit_date_past")
    assert source.requests == []


@pytest.mark.asyncio
async def test_list_clinics_rejects_date_beyond_schedule_window() -> None:
    # NTUH publishes the next 14 days; later dates are unreachable, so the
    # picker degrades to manual entry without a fetch.
    source = FakeSource(PAGE)
    roster = await reader(source).list_clinics(
        RosterQuery("ntuh-main", "OPH", DAY + timedelta(days=15)),
        taipei(14, 0),
    )
    assert roster == ClinicRoster(
        False,
        (),
        "visit_date_out_of_schedule_window",
        schedule_end=DAY + timedelta(days=14),
        release_time=datetime(2026, 10, 23, tzinfo=timezone(timedelta(hours=8))),
    )
    assert source.requests == []


def _schedule_sim_now() -> datetime:
    """A Taipei `now` whose date is the day before the schedule fixture starts."""
    return datetime(
        SCHEDULE_SIM_TODAY.year,
        SCHEDULE_SIM_TODAY.month,
        SCHEDULE_SIM_TODAY.day,
        14,
        0,
        tzinfo=timezone(timedelta(hours=8)),
    )


@pytest.mark.asyncio
async def test_list_clinics_future_date_filters_schedule_and_drops_cancelled() -> None:
    source = FakeSource(schedule=SCHEDULE_FIXTURE)
    roster = await reader(source).list_clinics(
        RosterQuery("ntuh-main", "OPH", SCHEDULE_FIRST_VISIT),
        _schedule_sim_now(),
    )
    assert roster.available and roster.reason == "ok"
    doctors = {clinic.doctor for clinic in roster.clinics}
    # 停診 dropped; the three live cards survive.
    assert "合成醫師丙" not in doctors
    assert {"合成醫師甲", "合成醫師乙", "合成醫師丁"} <= doctors
    assert any(c.clinic_code == "03/合成醫師甲/角膜" for c in roster.clinics)
    # 11/11 rows must not leak into 11/10's roster.
    assert "合成醫師戊" not in doctors
    # The schedule page is GET only; no POST, no selector hit.
    schedule_requests = [r for r in source.requests if r.url.startswith(SCHEDULE_PATH)]
    assert len(schedule_requests) == 1
    assert schedule_requests[0].method == "GET"
    assert not any(r.method == "POST" for r in source.requests)


@pytest.mark.asyncio
async def test_list_clinics_future_date_reports_no_observation_when_cancelled_only() -> (
    None
):
    # A date whose every card is cancelled (停診 or 颱風停診) has no viable
    # clinic to list; the roster degrades to no_observation so the picker can
    # fall back to manual entry.
    only_cancelled = schedule(
        slot(
            datetime(2026, 11, 12).date(),
            _MORNING,
            "03",
            "合成醫師X",
            "角膜",
            "停診",
            "一般眼科",
        )
    )
    source = FakeSource(schedule=only_cancelled)
    roster = await reader(source).list_clinics(
        RosterQuery("ntuh-main", "OPH", datetime(2026, 11, 12).date()),
        _schedule_sim_now(),
    )
    assert roster == ClinicRoster(False, (), "no_observation")


@pytest.mark.asyncio
async def test_list_clinics_future_date_timeout_degrades_without_crashing() -> None:
    class TimeoutFetch:
        requests: list[PageRequest] = []

        async def __call__(self, request: PageRequest) -> FetchedPage:
            self.requests.append(request)
            raise TimeoutError

    roster = await reader(TimeoutFetch()).list_clinics(
        RosterQuery("ntuh-main", "OPH", SCHEDULE_SECOND_VISIT),
        _schedule_sim_now(),
    )
    assert not roster.available
    assert roster.reason in {"timeout", "no_observation"}


def test_schedule_url_carries_showall_in_14_day_window() -> None:
    url = schedule_url("OPH")
    assert "RegDeptSchedule" in url
    assert "vhospCode=T0" in url and "showBlock=A" in url
    assert "vDeptCode=OPH" in url and "realSubDeptCode=showAll" in url


@pytest.mark.asyncio
async def test_list_clinics_is_unavailable_when_a_session_is_denied() -> None:
    source = FakeSource(FetchedPage(403, ""))
    roster = await reader(source).list_clinics(
        RosterQuery("ntuh-main", "OPH", DAY), taipei(14, 0)
    )
    assert not roster.available and roster.reason == "access_denied"
    assert roster.clinics == ()
    # Fails on the first session; the other two are not requested.
    assert len([r for r in source.requests if r.method == "POST"]) == 1


@pytest.mark.asyncio
async def test_list_clinics_rejects_an_unsupported_scope() -> None:
    source = FakeSource(PAGE)
    roster = await reader(source).list_clinics(
        RosterQuery("ntuh-main", "CARD", DAY), taipei(14, 0)
    )
    assert not roster.available and roster.reason == "scope_mismatch"
    assert source.requests == []


# Scheduler and gate wiring


async def gate_with_visit(source: FakeSource, *, enabled: bool = True):
    database = LocalD1()
    env = {
        "DB": database,
        "NIY006_LOCAL_TEST_MODE": "1",
        "NIY_ENVIRONMENT": "local-test",
    }
    if enabled:
        env["NTUH_READER_ENABLED"] = "1"
    gate = SystemSendGate(LocalContext(LocalDurableStorage()), env)
    gate._ntuh_fetcher = source
    return database, gate


def counts(database: LocalD1, visit_id: str) -> tuple[str, str, int]:
    row = database.connection.execute(
        "SELECT latest_source_read_status, latest_source_read_reason,"
        " consecutive_unusable_reads FROM visits WHERE id = ?",
        (visit_id,),
    ).fetchone()
    return tuple(row)


async def seed_ntuh(database: LocalD1, gate, visit_id: str, patient: int = 28):
    now = taipei(14, 0)
    store = CloudflareD1Store(database)
    await store.execute(
        Statement(
            """INSERT OR IGNORE INTO recipients (id, line_subject, display_name,
            consented_at, friendship_checked_at, active, created_at) VALUES
            ('r1', 'U' || lower(hex(zeroblob(16))), 'Synthetic one', ?, ?, 1, ?)""",
            (now.isoformat(),) * 3,
        )
    )
    repository = VisitRepository(store)
    await repository.create_draft(
        visit_id=visit_id,
        hospital="ntuh-main",
        visit_day=DAY,
        department_code="OPH",
        clinic_code=CLINIC,
        clinic_session="afternoon",
        patient_number=patient,
        now=now,
    )
    assert await repository.add_recipient(visit_id, "r1", now)
    return repository


@pytest.mark.asyncio
async def test_start_activates_on_fresh_exact_positive_read() -> None:
    source = FakeSource(PAGE)
    database, gate = await gate_with_visit(source)
    repository = await seed_ntuh(database, gate, "d1")
    started = await gate.start_visit("d1", taipei(15, 0).isoformat())
    assert started == {"state": "active"}
    visit = await repository.get_visit("d1")
    assert visit["state"] == "active"
    assert counts(database, "d1")[:2] == ("usable", "none")
    # Pre-flight loads today's roster (one POST per session) before the
    # authoritative observe_for_start read.
    assert source.urls == [LIGHT_TABLE_URL] * 4


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("page", "error", "status", "reason"),
    [
        (
            FetchedPage(503, ""),
            "schedule_unavailable",
            "unavailable",
            "no_observation",
        ),
        (
            FetchedPage(403, ""),
            "schedule_unavailable",
            "unavailable",
            "access_denied",
        ),
        (
            ListRead(status="schema"),
            "schedule_unavailable",
            "unavailable",
            "schema_drift",
        ),
        (page_with("000"), "observation_invalid", "invalid", "invalid_data"),
    ],
)
async def test_start_stays_draft_with_the_source_reason(page, error, status, reason):
    database, gate = await gate_with_visit(FakeSource(page))
    repository = await seed_ntuh(database, gate, "d1")
    assert await gate.start_visit("d1", taipei(15, 0).isoformat()) == {"error": error}
    assert (await repository.get_visit("d1"))["state"] == "draft"
    assert counts(database, "d1")[:2] == (status, reason)


@pytest.mark.asyncio
async def test_start_on_an_earlier_day_degrades_to_schedule_unavailable() -> None:
    # The visit is one day in the future from the simulated clock. Pre-flight
    # reads RegDeptSchedule to validate the doctor; the schedule does not parse
    # (schema_drift) and Start fails closed with schedule_unavailable. No
    # DeptLightTable POST runs.
    source = FakeSource(PAGE, schedule=ScheduleRead(status="schema_drift"))
    database, gate = await gate_with_visit(source)
    repository = await seed_ntuh(database, gate, "d1")
    day_before = (taipei(15, 0) - timedelta(days=1)).isoformat()
    assert await gate.start_visit("d1", day_before) == {"error": "schedule_unavailable"}
    assert source.urls == []
    assert (await repository.get_visit("d1"))["state"] == "draft"


@pytest.mark.asyncio
async def test_start_succeeds_at_any_hour_of_the_visit_day() -> None:
    source = FakeSource(PAGE)
    database, gate = await gate_with_visit(source)
    repository = await seed_ntuh(database, gate, "d1")
    assert await gate.start_visit("d1", taipei(9, 0).isoformat()) == {"state": "active"}
    assert (await repository.get_visit("d1"))["state"] == "active"


@pytest.mark.asyncio
async def test_reader_is_off_without_the_explicit_flag() -> None:
    source = FakeSource(PAGE)
    database, gate = await gate_with_visit(source, enabled=False)
    await seed_ntuh(database, gate, "d1")
    assert await gate.start_visit("d1", taipei(15, 0).isoformat()) == {
        "error": "observation_unavailable"
    }
    assert source.urls == []


@pytest.mark.asyncio
async def test_production_hold_disables_start_and_reader_status_even_if_enabled() -> (
    None
):
    source = FakeSource(PAGE)
    database = LocalD1()
    env = {
        "DB": database,
        "NIY_ENVIRONMENT": "production",
        "NTUH_READER_ENABLED": "1",
    }
    gate = SystemSendGate(LocalContext(LocalDurableStorage()), env)
    gate._ntuh_fetcher = source
    repository = await seed_ntuh(database, gate, "d1")

    assert await gate.start_visit("d1", taipei(15, 0).isoformat()) == {
        "error": "observation_unavailable"
    }
    assert (await repository.get_visit("d1"))["state"] == "draft"
    assert source.urls == []
    status = await gate.scheduler_status()
    assert status["held"]
    assert not status["hospital_reader_available"]


async def seed_ntuh_at(
    database: LocalD1,
    gate,
    visit_id: str,
    visit_day,
    clinic_code: str = CLINIC,
    session: str = "afternoon",
    patient: int = 28,
):
    now = taipei(14, 0)
    store = CloudflareD1Store(database)
    await store.execute(
        Statement(
            """INSERT OR IGNORE INTO recipients (id, line_subject, display_name,
            consented_at, friendship_checked_at, active, created_at) VALUES
            ('r1', 'U' || lower(hex(zeroblob(16))), 'Synthetic one', ?, ?, 1, ?)""",
            (now.isoformat(),) * 3,
        )
    )
    repository = VisitRepository(store)
    await repository.create_draft(
        visit_id=visit_id,
        hospital="ntuh-main",
        visit_day=visit_day,
        department_code="OPH",
        clinic_code=clinic_code,
        clinic_session=session,
        patient_number=patient,
        now=now,
    )
    assert await repository.add_recipient(visit_id, "r1", now)
    return repository


# Pre-flight validation for Start (Issue #58)


_PREFLIGHT_SIM_SOURCE_DATE = datetime(2026, 11, 9).date()


def _preflight_now() -> datetime:
    return datetime(
        _PREFLIGHT_SIM_SOURCE_DATE.year,
        _PREFLIGHT_SIM_SOURCE_DATE.month,
        _PREFLIGHT_SIM_SOURCE_DATE.day,
        14,
        0,
        tzinfo=timezone(timedelta(hours=8)),
    )


@pytest.mark.asyncio
async def test_preflight_blocks_start_when_visit_date_is_in_the_past() -> None:
    source = FakeSource(PAGE)
    database, gate = await gate_with_visit(source)
    past = _PREFLIGHT_SIM_SOURCE_DATE - timedelta(days=1)
    await seed_ntuh_at(database, gate, "past", past)
    result = await gate.start_visit("past", _preflight_now().isoformat())
    assert result == {"error": "visit_date_past"}
    # No live fetches: pre-flight short-circuits before touching the source.
    assert source.urls == []
    assert counts(database, "past")[:2] == ("scope_mismatch", "scope_mismatch")


@pytest.mark.asyncio
async def test_preflight_blocks_start_when_date_is_out_of_schedule_window() -> None:
    source = FakeSource(PAGE)
    database, gate = await gate_with_visit(source)
    beyond = _PREFLIGHT_SIM_SOURCE_DATE + timedelta(days=20)
    await seed_ntuh_at(database, gate, "far", beyond)
    result = await gate.start_visit("far", _preflight_now().isoformat())
    assert result == {
        "error": "visit_date_out_of_schedule_window",
        "schedule_end": "2026-11-23",
        "release_time": "2026-11-15T00:00:00+08:00",
    }
    assert source.urls == []
    # The draft is kept unchanged (ticket #101).
    assert counts(database, "far")[:2] == ("unavailable", "no_observation")


@pytest.mark.asyncio
async def test_preflight_blocks_start_when_doctor_not_scheduled() -> None:
    # The schedule fixture lists 合成醫師甲 at 11/10 morning room 03. A draft
    # that names a different (session, room, doctor) must fail closed.
    source = FakeSource(schedule=SCHEDULE_FIXTURE)
    database, gate = await gate_with_visit(source)
    await seed_ntuh_at(
        database,
        gate,
        "mismatch",
        SCHEDULE_FIRST_VISIT,
        clinic_code="99/陌生醫師/角膜",
        session="morning",
    )
    result = await gate.start_visit("mismatch", _preflight_now().isoformat())
    assert result == {"error": "doctor_not_scheduled"}
    assert counts(database, "mismatch")[:2] == ("scope_mismatch", "scope_mismatch")


@pytest.mark.asyncio
async def test_preflight_blocks_start_when_schedule_source_is_unreachable() -> None:
    # The schedule does not parse (schema_drift); the gate fails closed with a
    # specific schedule_unavailable error.
    source = FakeSource(PAGE, schedule=ScheduleRead(status="schema_drift"))
    database, gate = await gate_with_visit(source)
    await seed_ntuh_at(database, gate, "down", SCHEDULE_FIRST_VISIT, session="morning")
    result = await gate.start_visit("down", _preflight_now().isoformat())
    assert result == {"error": "schedule_unavailable"}
    assert counts(database, "down")[:2] == ("unavailable", "schema_drift")


@pytest.mark.asyncio
async def test_future_date_start_transitions_to_active_without_an_observation() -> None:
    source = FakeSource(schedule=SCHEDULE_FIXTURE)
    database, gate = await gate_with_visit(source)
    repository = await seed_ntuh_at(
        database,
        gate,
        "future",
        SCHEDULE_FIRST_VISIT,
        clinic_code="03/合成醫師甲/角膜",
        session="morning",
    )
    result = await gate.start_visit("future", _preflight_now().isoformat())
    assert result == {"state": "active"}
    visit = await repository.get_visit("future")
    assert visit["state"] == "active"
    # No DeptLightTable POST; the clinic hasn't opened yet, so no observation.
    assert source.urls == []
    assert counts(database, "future")[:2] == ("unavailable", "no_observation")


@pytest.mark.asyncio
async def test_preflight_resolve_rewrites_clinic_code_for_same_day_schedule_sourced_draft() -> (
    None
):
    # A draft left with the schedule-side 診別 (e.g. "角膜") is resolved to the
    # today-side `clinic_type` from the live roster at Start time.
    source = FakeSource(PAGE)
    database, gate = await gate_with_visit(source)
    repository = await seed_ntuh_at(
        database,
        gate,
        "resolve",
        DAY,
        clinic_code="11診/合成醫師丙/角膜",
    )
    result = await gate.start_visit("resolve", taipei(14, 0).isoformat())
    assert result == {"state": "active"}
    updated = await repository.get_visit("resolve")
    assert "醫師約診" in str(updated["clinic_code"])
    assert "角膜" not in str(updated["clinic_code"])
    assert "合成醫師丙" in str(updated["clinic_code"])


async def active_visit(database, gate, visit_id="d1", patient=28):
    repository = await seed_ntuh(database, gate, visit_id, patient)
    assert await repository.start(visit_id, taipei(14, 59))
    assert await repository.update_observation(
        visit_id,
        current_number=25,
        observed_at=taipei(14, 59),
        consecutive_unusable_reads=0,
    )
    assert await repository.set_source_read(visit_id, "usable", "none")


@pytest.mark.asyncio
async def test_scheduled_checks_repeat_near_alerts_as_the_number_moves() -> None:
    # The scripted source reads 025 first, then 026 on every later tick.
    source = FakeSource(PAGE, page_with("026"))
    database, gate = await gate_with_visit(source)
    await active_visit(database, gate)
    # Patient 28, window 25..27: entering at 25 sends, moving to 26 sends again.
    result = await gate.scheduled_tick(taipei(15, 2).isoformat())
    assert result["events_created"] == 1
    moved = await gate.scheduled_tick(taipei(15, 4).isoformat())
    assert moved["events_created"] == 1
    # Reading 026 again is the same number as the last scheduled read: no reminder.
    again = await gate.scheduled_tick(taipei(15, 6).isoformat())
    assert again["events_created"] == 0
    assert counts(database, "d1")[:2] == ("usable", "none")
    snapshot = await gate.test_snapshot()
    assert [event["event_kind"] for event in snapshot["events"]] == ["near", "near"]
    assert snapshot["line_requests"]


@pytest.mark.asyncio
async def test_skipped_ticks_never_count_as_failed_reads() -> None:
    source = FakeSource(PAGE)
    database, gate = await gate_with_visit(source)
    await active_visit(database, gate)
    await gate.scheduled_tick(taipei(15, 0).isoformat())
    unusable_reads = counts(database, "d1")[2]
    await gate.scheduled_tick(taipei(15, 1).isoformat())
    await gate.scheduled_tick(taipei(15, 1, 30).isoformat())
    assert counts(database, "d1")[2] == unusable_reads
    assert len(source.urls) == 1


@pytest.mark.asyncio
async def test_three_failed_reads_inside_the_window_send_the_existing_unavailable_alert():
    source = FakeSource(FetchedPage(503, ""))
    database, gate = await gate_with_visit(source)
    await active_visit(database, gate)
    created = 0
    for minute in (2, 3, 5):  # reads follow the 1 then 2 minute backoff
        created += (await gate.scheduled_tick(taipei(15, minute).isoformat()))[
            "events_created"
        ]
    assert created == 1
    kinds = [e["event_kind"] for e in (await gate.test_snapshot())["events"]]
    assert kinds == ["unavailable"]


@pytest.mark.asyncio
async def test_clinic_end_stops_reads_and_sends_no_unavailable_alert() -> None:
    # The clinic is calling well short of the patient's number, then its number
    # goes blank and stays blank.
    source = FakeSource(page_with("010"), page_with(""), links=False)
    database, gate = await gate_with_visit(source)
    await active_visit(database, gate)
    for minute in (31, 33, 35, 40, 50):
        result = await gate.scheduled_tick(taipei(16, minute).isoformat())
        assert result["events_created"] == 0
    # One opening read, then the two blank reads that end the watch.
    assert len(source.urls) == 3
    assert (await gate.test_snapshot())["events"] == []


@pytest.mark.asyncio
async def test_challenge_stops_the_source_and_keeps_the_visit_unavailable() -> None:
    source = FakeSource(PAGE, FetchedPage(403, ""), PAGE)
    database, gate = await gate_with_visit(source)
    await active_visit(database, gate)
    for minute in (2, 3, 4, 10):
        await gate.scheduled_tick(taipei(15, minute).isoformat())
    assert counts(database, "d1")[:2] == ("unavailable", "access_denied")
    assert len(source.urls) == 2


@pytest.mark.asyncio
async def test_gate_lists_clinics_when_the_reader_is_enabled() -> None:
    source = FakeSource(PAGE)
    _, gate = await gate_with_visit(source)
    result = await gate.list_clinics(
        "ntuh-main", "OPH", DAY.isoformat(), taipei(14, 0).isoformat()
    )
    assert result["available"] is True and result["reason"] == "ok"
    assert len(result["clinics"]) == 15
    assert result["clinics"][0].keys() == {
        "label",
        "details",
        "session",
        "room",
        "doctor",
        "clinic_type",
        "clinic_code",
    }


@pytest.mark.asyncio
async def test_gate_roster_is_held_without_the_reader() -> None:
    source = FakeSource(PAGE)
    _, gate = await gate_with_visit(source, enabled=False)
    result = await gate.list_clinics(
        "ntuh-main", "OPH", DAY.isoformat(), taipei(14, 0).isoformat()
    )
    assert result == {"available": False, "reason": "no_observation", "clinics": []}


@pytest.mark.asyncio
async def test_gate_roster_rejects_an_unknown_hospital() -> None:
    source = FakeSource(PAGE)
    _, gate = await gate_with_visit(source)
    result = await gate.list_clinics(
        "not-a-hospital", "OPH", DAY.isoformat(), taipei(14, 0).isoformat()
    )
    assert result == {"available": False, "reason": "invalid_data", "clinics": []}


@pytest.mark.asyncio
async def test_gate_reports_end_date_and_release_time_for_an_unpublished_day() -> None:
    # Fixture/mock: real registry, fake transport. Today is 10/22, so NTUH's
    # clinic schedule ends 11/05 and 11/06 opens at 00:00 Taipei on 10/23.
    source = FakeSource(PAGE)
    _, gate = await gate_with_visit(source)
    result = await gate.list_clinics(
        "ntuh-main",
        "OPH",
        (DAY + timedelta(days=15)).isoformat(),
        taipei(14, 0).isoformat(),
    )
    assert result == {
        "available": False,
        "reason": "visit_date_out_of_schedule_window",
        "clinics": [],
        "schedule_end": "2026-11-05",
        "release_time": "2026-10-23T00:00:00+08:00",
    }
    assert source.requests == []


@pytest.mark.asyncio
async def test_gate_reports_no_release_time_when_the_reader_states_none(
    monkeypatch,
) -> None:
    # Fixture/mock: a synthetic full-schedule hospital that publishes an end
    # date but no release time for the days it has not published.
    import dataclasses

    from next_is_you import hospital_registry

    class SyntheticReader:
        def __init__(self, storage, fetch) -> None:
            pass

        async def observe(self, scope, now):
            return None

        async def observe_for_start(self, scope, now):
            return None

        async def match_clinic(self, query, now):
            return ClinicMatch(MatchKind.NOT_YET_PUBLISHED)

        async def list_clinics(self, query, now):
            return ClinicRoster(
                False,
                (),
                "visit_date_out_of_schedule_window",
                schedule_end=datetime(2026, 11, 3).date(),
            )

    entry = dataclasses.replace(
        hospital_registry.HOSPITAL_REGISTRY["shin-kong-taipei"],
        reader_type=SyntheticReader,
    )
    monkeypatch.setattr(
        hospital_registry,
        "HOSPITAL_REGISTRY",
        {**hospital_registry.HOSPITAL_REGISTRY, "shin-kong-taipei": entry},
    )
    _, gate = await gate_with_visit(FakeSource(PAGE))
    result = await gate.list_clinics(
        "shin-kong-taipei", "ANY", "2026-11-20", taipei(14, 0).isoformat()
    )
    assert result["schedule_end"] == "2026-11-03"
    assert "release_time" not in result
    assert result["reason"] == "visit_date_out_of_schedule_window"


# Issue #135: the clinic code a schedule-picked visit stores (`11/醫師/角膜`, the
# room without 診 and the schedule's 診別) never equals the visit-day card
# (`11 診/醫師/醫師約診`). The reader identifies the day's card by session, room
# and doctor instead.
SCHEDULE_FORM_CLINIC = "11/合成醫師丙/角膜"


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["observe", "observe_for_start"])
async def test_a_schedule_form_clinic_code_reads_the_visit_day_card(method) -> None:
    result = await getattr(reader(FakeSource(PAGE)), method)(
        scope(SCHEDULE_FORM_CLINIC), taipei(15, 0)
    )
    assert isinstance(result, QueueObservation)
    assert result.current_number == 25
    assert result.scope == scope(SCHEDULE_FORM_CLINIC)


@pytest.mark.asyncio
async def test_one_doctor_with_two_clinic_types_in_a_room_is_ambiguous() -> None:
    # A schedule-form code names no clinic type the cards use, so two cards for
    # the same doctor in one room and session cannot be told apart: no guess.
    page = plus(PAGE, card("11 診", "合成醫師丙", "普通門診", "031"))
    result = await reader(FakeSource(page)).observe(
        scope(SCHEDULE_FORM_CLINIC), taipei(15, 0)
    )
    assert result == ReadFailed("invalid", "ambiguous_match")


@pytest.mark.asyncio
async def test_a_stored_clinic_type_tells_two_cards_of_one_doctor_apart() -> None:
    page = plus(PAGE, card("11 診", "合成醫師丙", "普通門診", "031"))
    result = await reader(FakeSource(page)).observe(scope(CLINIC), taipei(15, 0))
    assert isinstance(result, QueueObservation)
    assert result.current_number == 25


@pytest.mark.asyncio
async def test_a_substitute_card_in_the_room_is_the_visits_card_marked_as_such() -> (
    None
):
    page = with_rows(PAGE, of_doctor("合成醫師丙"), doctor="住院醫師(代)")
    result = await reader(FakeSource(page)).observe(
        scope(SCHEDULE_FORM_CLINIC), taipei(15, 0)
    )
    assert isinstance(result, QueueObservation)
    assert result.current_number == 25
    assert result.substitute_doctor is True


@pytest.mark.asyncio
async def test_a_substitute_card_that_has_not_called_yet_is_still_marked() -> None:
    page = with_rows(PAGE, of_doctor("合成醫師丙"), doctor="住院醫師(代)", current="")
    result = await reader(FakeSource(page)).observe(
        scope(SCHEDULE_FORM_CLINIC), taipei(13, 0)
    )
    assert result == ReadSkipped("clinic_not_started", substitute_doctor=True)
    assert result.source_read == ("unavailable", "substitute_doctor")


@pytest.mark.asyncio
async def test_the_booked_doctor_wins_over_a_substitute_in_the_same_room() -> None:
    page = plus(PAGE, card("11 診", "住院醫師(代)", "普通門診", "031"))
    result = await reader(FakeSource(page)).observe(
        scope(SCHEDULE_FORM_CLINIC), taipei(15, 0)
    )
    assert isinstance(result, QueueObservation)
    assert result.current_number == 25
    assert result.substitute_doctor is False


@pytest.mark.asyncio
async def test_two_substitute_cards_in_the_room_are_ambiguous() -> None:
    page = listing(
        *with_rows(PAGE, of_doctor("合成醫師丙"), doctor="住院醫師(代)").rows,
        card("11 診", "主治醫師(代)", "普通門診", "031"),
    )
    result = await reader(FakeSource(page)).observe(
        scope(SCHEDULE_FORM_CLINIC), taipei(15, 0)
    )
    assert result == ReadFailed("invalid", "ambiguous_match")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mark", ["住院醫師 (代)", "住院醫師（代）", "住院醫師（ 代 ）"]
)
async def test_a_substitute_mark_is_recognised_with_spacing_or_full_width(mark) -> None:
    page = with_rows(PAGE, of_doctor("合成醫師丙"), doctor=mark)
    result = await reader(FakeSource(page)).observe(
        scope(SCHEDULE_FORM_CLINIC), taipei(15, 0)
    )
    assert isinstance(result, QueueObservation)
    assert result.substitute_doctor is True
