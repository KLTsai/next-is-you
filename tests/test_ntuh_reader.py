"""NTUH reader behavior against fixture pages only; nothing here reaches the network."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path
from urllib.parse import parse_qsl

import pytest

from next_is_you.domain import (
    ClinicRoster,
    ClinicScope,
    ClinicSession,
    Hospital,
    QueueObservation,
    ReadFailed,
    ReadSkipped,
    RosterQuery,
)
from next_is_you.ntuh_reader import (
    AMPM_CODES,
    LIGHT_TABLE_URL,
    SCHEDULE_PATH,
    FetchedPage,
    NtuhProgressReader,
    PageRequest,
    ScheduleRow,
    parse_clinic_key,
    parse_light_table,
    parse_request_token,
    parse_retry_after,
    parse_schedule,
    schedule_url,
    selector_page_url,
)
from next_is_you.persistence import CloudflareD1Store, Statement, VisitRepository
from test_scheduler_outbox import (
    LocalContext,
    LocalD1,
    LocalDurableStorage,
)
from next_is_you.send_gate import SystemSendGate

FIXTURES = Path(__file__).parent / "fixtures" / "hospitals"
PAGE = (FIXTURES / "ntuh_oph_light_table.html").read_text(encoding="utf-8")
SELECTOR = (FIXTURES / "ntuh_webreg_selector.html").read_text(encoding="utf-8")
SCHEDULE_FIXTURE = (FIXTURES / "ntuh_oph_schedule.html").read_text(encoding="utf-8")
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
    hospital: Hospital = Hospital.NTUH_MAIN,
) -> ClinicScope:
    return ClinicScope(hospital, DAY, department, clinic_code, session)


def page_with(current: str) -> str:
    return PAGE.replace("025", current)


def _page(item) -> FetchedPage:
    if isinstance(item, Exception):
        raise item
    return item if isinstance(item, FetchedPage) else FetchedPage(200, item)


class FakeSource:
    """Scripted two-step source.

    One read is a GET of the selector page followed by a POST for the clinic
    cards, so the script holds one entry per read and `urls` counts the POSTs.
    An exception instance in a script is raised. A GET of the dept-wide
    schedule page returns `schedule`, when it is set.
    """

    SESSION_COOKIES = ("ASP.NET_SessionId=synthetic", "__RequestVerificationToken_X=t")

    def __init__(self, *script, selector=SELECTOR, schedule=None) -> None:
        self.script = list(script)
        self.selector = selector
        self.schedule = schedule
        self.requests: list[PageRequest] = []

    @property
    def urls(self) -> list[str]:
        return [
            request.url for request in self.requests if request.url == LIGHT_TABLE_URL
        ]

    def last_body(self) -> dict[str, str]:
        posts = [r for r in self.requests if r.method == "POST"]
        return dict(parse_qsl(posts[-1].body or "", keep_blank_values=True))

    def headers_of(self, request: PageRequest) -> dict[str, str]:
        return dict(request.headers)

    async def __call__(self, request: PageRequest) -> FetchedPage:
        self.requests.append(request)
        if request.method == "GET":
            if request.url.startswith(SCHEDULE_PATH) and self.schedule is not None:
                return _page(self.schedule)
            page = _page(self.selector)
            return replace(page, cookies=self.SESSION_COOKIES)
        item = self.script.pop(0) if len(self.script) > 1 else self.script[0]
        return _page(item)


def reader(source: FakeSource, state: LocalDurableStorage | None = None):
    return NtuhProgressReader(state or LocalDurableStorage(), source)


def test_parser_reads_cards_and_ignores_the_fragment_render_time() -> None:
    status, rows = parse_light_table(PAGE)
    assert status == "ok"
    target = [row for row in rows if row.doctor == "合成醫師丙"]
    assert [(r.room, r.clinic_type, r.current) for r in target] == [
        ("11 診", "醫師約診", "025")
    ]
    assert not hasattr(target[0], "updated_at")


def test_parser_keeps_a_blank_light_and_a_check_in_order_card_apart() -> None:
    rows = {row.room: row for row in parse_light_table(PAGE)[1]}
    assert rows["08 診"].current == "" and rows["08 診"].check_in_order == ""
    assert rows["99 診"].current == "" and rows["99 診"].check_in_order == "依報到順序"


@pytest.mark.parametrize(
    "html",
    [
        "<html><body>maintenance</body></html>",
        "<div class='main-container'></div>",
        # An anchor whose card lost the doctor, and one that lost the number.
        '<a class="open-link"><div class="room-number">11 診</div>'
        '<div class="clinic-type">醫師約診</div><div class="number">025</div></a>',
        '<a class="open-link"><div class="room-number">11 診</div>'
        '<div class="clinic-doc-name">合成醫師丙</div>'
        '<div class="clinic-type">醫師約診</div></a>',
    ],
)
def test_parser_fails_closed_on_unrecognized_pages(html: str) -> None:
    assert parse_light_table(html) == ("schema", [])


@pytest.mark.parametrize(
    ("html", "status"),
    [("<p>Please complete the CAPTCHA</p>", "challenge"), ("Access Denied", "denied")],
)
def test_parser_detects_challenge_and_denial(html: str, status: str) -> None:
    assert parse_light_table(html)[0] == status


def test_token_is_read_from_the_selector_page_and_absent_elsewhere() -> None:
    assert parse_request_token(SELECTOR) == "synthetic-token-value"
    assert parse_request_token(PAGE) is None
    assert parse_request_token("<html><body>moved</body></html>") is None


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
        "__RequestVerificationToken": "synthetic-token-value",
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
    source = FakeSource(PAGE, selector="<html><body>moved</body></html>")
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
        "11診/合成醫師丁/醫師約診",
        "12診/合成醫師丙/醫師約診",
        "11診/合成醫師丙/普通門診",
    ],
)
async def test_any_identity_field_mismatch_never_matches(clinic: str) -> None:
    result = await reader(FakeSource(PAGE)).observe(scope(clinic), taipei(15, 0))
    assert result == ReadSkipped("clinic_not_started")


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
    card = (
        '<a class="open-link"><div class="room-number">11 診</div>'
        '<div class="clinic-doc-name">合成醫師丙</div>'
        '<div class="clinic-type">醫師約診</div>'
        '<div class="number">026</div>'
        '<div class="according-to-order"></div></a>'
    )
    result = await reader(FakeSource(PAGE + card)).observe(scope(), taipei(15, 0))
    assert result == ReadFailed("invalid", "ambiguous_match")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad",
    [
        scope(department="MED"),
        scope(hospital=Hospital.SHIN_KONG_TAIPEI),
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
    "session",
    [ClinicSession.MORNING, ClinicSession.AFTERNOON, ClinicSession.EVENING],
)
@pytest.mark.parametrize("hour", [9, 15, 20])
async def test_every_session_is_read_at_any_hour_of_the_entered_day(session, hour):
    source = FakeSource(PAGE)
    observation = await reader(source).observe(scope(session=session), taipei(hour, 0))
    assert isinstance(observation, QueueObservation)
    assert observation.current_number == 25
    assert source.last_body()["AmpmCode"] == AMPM_CODES[session]


@pytest.mark.asyncio
async def test_no_wall_clock_session_boundary_exists() -> None:
    source = FakeSource(PAGE)
    r = reader(source)
    # The old reader refused 13:19 and 16:40; both are ordinary reads now.
    for hour, minute in ((0, 1), (13, 19), (16, 40), (23, 58)):
        assert isinstance(
            await r.observe(scope(), taipei(hour, minute)), QueueObservation
        )
    assert len(source.urls) == 4


@pytest.mark.asyncio
async def test_reads_happen_only_on_the_day_the_owner_entered() -> None:
    source = FakeSource(PAGE)
    other_day = ClinicScope(
        Hospital.NTUH_MAIN,
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
        FetchedPage(200, "<p>Please complete the CAPTCHA to continue</p>"),
        FetchedPage(200, "<h1>Access Denied</h1>"),
    ],
)
async def test_challenge_or_denial_stops_reading_the_source(page: FetchedPage) -> None:
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
@pytest.mark.parametrize(
    "page", [FetchedPage(200, "<html>moved</html>"), FetchedPage(404, "")]
)
async def test_schema_change_fails_closed(page: FetchedPage) -> None:
    result = await reader(FakeSource(page)).observe(scope(), taipei(15, 0))
    assert result == ReadFailed("invalid", "schema_drift")


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["observe", "observe_for_start"])
async def test_card_missing_its_number_is_schema_drift_not_a_clinic_end(method):
    malformed = (
        '<a class="open-link"><div class="room-number">11 診</div>'
        '<div class="clinic-doc-name">合成醫師丙</div>'
        '<div class="clinic-type">醫師約診</div></a>'
    )
    source = FakeSource(malformed)
    result = await getattr(reader(source), method)(scope(), taipei(16, 31))
    assert result == ReadFailed("invalid", "schema_drift")
    assert len(source.urls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "absent",
    [
        pytest.param(page_with(""), id="number-goes-blank"),
        pytest.param(PAGE.replace("合成醫師丙", "其他醫師"), id="card-disappears"),
    ],
)
async def test_the_watch_ends_once_the_number_is_gone_for_two_reads(absent) -> None:
    source = FakeSource(PAGE, absent)
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
    source = FakeSource(PAGE, page_with(""), PAGE, PAGE)
    r = reader(source)
    assert isinstance(await r.observe(scope(), taipei(15, 0)), QueueObservation)
    assert await r.observe(scope(), taipei(15, 2)) == ReadFailed(
        "unavailable", "empty_result"
    )
    assert isinstance(await r.observe(scope(), taipei(15, 4)), QueueObservation)
    # The run restarts, so one later blank is again not the end.
    assert isinstance(await r.observe(scope(), taipei(15, 6)), QueueObservation)


@pytest.mark.asyncio
async def test_a_clinic_that_never_called_is_checked_sparsely_and_never_ends() -> None:
    source = FakeSource(page_with(""))
    r = reader(source)
    not_started = ReadSkipped("clinic_not_started")
    assert await r.observe(scope(), taipei(9, 0)) == not_started
    assert await r.observe(scope(), taipei(9, 2)) == ReadSkipped("not_due")
    assert await r.observe(scope(), taipei(9, 4, 59)) == ReadSkipped("not_due")
    assert await r.observe(scope(), taipei(9, 5)) == not_started
    assert len(source.urls) == 2


@pytest.mark.asyncio
async def test_the_first_number_switches_the_watch_to_the_dense_cadence() -> None:
    source = FakeSource(page_with(""), PAGE)
    r = reader(source)
    assert await r.observe(scope(), taipei(9, 0)) == ReadSkipped("clinic_not_started")
    # Sparse until it starts.
    assert await r.observe(scope(), taipei(9, 3)) == ReadSkipped("not_due")
    assert isinstance(await r.observe(scope(), taipei(9, 5)), QueueObservation)
    # Dense from the read that saw the number, not five minutes after it.
    assert await r.observe(scope(), taipei(9, 6)) == ReadSkipped("not_due")
    assert isinstance(await r.observe(scope(), taipei(9, 7)), QueueObservation)


# Roster listing for the setup picker


@pytest.mark.asyncio
async def test_list_clinics_merges_the_three_sessions() -> None:
    source = FakeSource(PAGE)
    roster = await reader(source).list_clinics(
        RosterQuery(Hospital.NTUH_MAIN, "OPH", DAY), taipei(14, 0)
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
async def test_list_clinics_rejects_past_date_without_fetching() -> None:
    # A past visit date can only produce `visit_date_past`; no source read is
    # worthwhile.
    source = FakeSource(PAGE)
    roster = await reader(source).list_clinics(
        RosterQuery(Hospital.NTUH_MAIN, "OPH", DAY - timedelta(days=1)), taipei(14, 0)
    )
    assert roster == ClinicRoster(False, (), "visit_date_past")
    assert source.requests == []


@pytest.mark.asyncio
async def test_list_clinics_rejects_date_beyond_schedule_window() -> None:
    # NTUH publishes the next 14 days; later dates are unreachable, so the
    # picker degrades to manual entry without a fetch.
    source = FakeSource(PAGE)
    roster = await reader(source).list_clinics(
        RosterQuery(Hospital.NTUH_MAIN, "OPH", DAY + timedelta(days=15)),
        taipei(14, 0),
    )
    assert roster == ClinicRoster(False, (), "visit_date_out_of_schedule_window")
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


def test_parse_schedule_extracts_date_session_room_doctor_clinic_type_status() -> None:
    status, rows = parse_schedule(SCHEDULE_FIXTURE, SCHEDULE_SIM_TODAY)
    assert status == "ok"
    assert len(rows) == 6
    # One open morning card, with 診別 pulled from `.sub-spec` after the pipe.
    assert ScheduleRow(
        SCHEDULE_FIRST_VISIT, ClinicSession.MORNING, "03", "合成醫師甲", "角膜", ""
    ) in rows
    # Status markers are captured verbatim, both open and cancellation.
    full_card = next(r for r in rows if r.doctor == "合成醫師乙")
    assert full_card.status == "額滿"
    cancelled = next(r for r in rows if r.doctor == "合成醫師丙")
    assert cancelled.status == "停診"
    typhoon = next(r for r in rows if r.doctor == "合成醫師己")
    assert typhoon.status == "颱風停診"
    # Afternoon session is tracked distinctly on the same day.
    afternoon = next(r for r in rows if r.session == ClinicSession.AFTERNOON)
    assert afternoon.doctor == "合成醫師丁" and afternoon.room == "11"
    # Day column resolves `MM/DD` against the caller's today year.
    next_day_rows = [r for r in rows if r.visit_date == SCHEDULE_SECOND_VISIT]
    assert len(next_day_rows) == 2


def test_parse_schedule_returns_schema_drift_on_empty_markup() -> None:
    status, rows = parse_schedule("<html><body>no cards</body></html>", SCHEDULE_SIM_TODAY)
    assert status == "schema_drift"
    assert rows == []


@pytest.mark.asyncio
async def test_list_clinics_future_date_filters_schedule_and_drops_cancelled() -> None:
    source = FakeSource(schedule=SCHEDULE_FIXTURE)
    roster = await reader(source).list_clinics(
        RosterQuery(Hospital.NTUH_MAIN, "OPH", SCHEDULE_FIRST_VISIT),
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
async def test_list_clinics_future_date_reports_no_observation_when_cancelled_only() -> None:
    # A date whose every card is cancelled (停診 or 颱風停診) has no viable
    # clinic to list; the roster degrades to no_observation so the picker can
    # fall back to manual entry.
    only_cancelled = (
        "<html><body>"
        '<div class="row gx-2 align-items-stretch" id="deptScheduleResult">'
        '<div class="col-1"><div class="date" style="text-align:center">11/12</div></div>'
        '<div class="col-md-11"><div class="row">'
        '<span class="me-2 date">上午門診</span>'
        '<div class="col-12 col-sm-6 col-lg-3" id="99_合成醫師X">'
        '<button class="doctor-tag">'
        '<div class="doc-name">合成醫師X | 03 診</div>'
        '<div class="tag"><div class="first-reg">停診</div></div>'
        '<div class="sub-spec" title="角膜">一般眼科 | 角膜</div>'
        "</button></div>"
        "</div></div></div></body></html>"
    )
    source = FakeSource(schedule=only_cancelled)
    roster = await reader(source).list_clinics(
        RosterQuery(Hospital.NTUH_MAIN, "OPH", datetime(2026, 11, 12).date()),
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
        RosterQuery(Hospital.NTUH_MAIN, "OPH", SCHEDULE_SECOND_VISIT),
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
        RosterQuery(Hospital.NTUH_MAIN, "OPH", DAY), taipei(14, 0)
    )
    assert not roster.available and roster.reason == "access_denied"
    assert roster.clinics == ()
    # Fails on the first session; the other two are not requested.
    assert len([r for r in source.requests if r.method == "POST"]) == 1


@pytest.mark.asyncio
async def test_list_clinics_rejects_an_unsupported_scope() -> None:
    source = FakeSource(PAGE)
    roster = await reader(source).list_clinics(
        RosterQuery(Hospital.NTUH_MAIN, "CARD", DAY), taipei(14, 0)
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
        (FetchedPage(200, "<html/>"), "schedule_unavailable", "unavailable", "schema_drift"),
        (page_with(""), "observation_unavailable", "unavailable", "no_observation"),
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
    # reads RegDeptSchedule to validate the doctor; without a schedule fixture
    # the parse fails as schema_drift and Start fails closed with
    # schedule_unavailable. No DeptLightTable POST runs.
    source = FakeSource(PAGE)
    database, gate = await gate_with_visit(source)
    repository = await seed_ntuh(database, gate, "d1")
    day_before = (taipei(15, 0) - timedelta(days=1)).isoformat()
    assert await gate.start_visit("d1", day_before) == {
        "error": "schedule_unavailable"
    }
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
    assert result == {"error": "visit_date_out_of_schedule_window"}
    assert source.urls == []
    assert counts(database, "far")[:2] == ("scope_mismatch", "scope_mismatch")


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
    # No schedule in the fake source; parse yields schema_drift and the gate
    # fails closed with a specific schedule_unavailable error.
    source = FakeSource(PAGE)
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
async def test_preflight_resolve_rewrites_clinic_code_for_same_day_schedule_sourced_draft() -> None:
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
    source = FakeSource(page_with("010"), page_with(""))
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
