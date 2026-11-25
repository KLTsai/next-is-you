"""Issue #163: the visit-day read takes the card's detail page and reports progress.

Fixture/mock evidence: a source whose session list and detail page are set
independently (`TwoPageSource`), so the two may disagree. Both are served as the
values the readers return (`ntuh_reads.py`, #205): a list is a `ListRead`, a
detail page a `ProgressObservation` or, when its parse fails, a `DetailRead`.
How the hospital's pages parse is tested on real captures. Local integration
evidence: tests that name the gate run Start and the scheduled tick through it.
Nothing reaches the hospital.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import timedelta

import pytest

import next_is_you.ntuh_reader as ntuh_reader
from next_is_you.domain import (
    ClinicSession,
    ExpectedCall,
    NumberStatus,
    QueueObservation,
    ReadFailed,
    ReadSkipped,
)
from next_is_you.hospital_registry import forget_other_days
from next_is_you.ntuh_reader import STATE_KEY, FetchedPage
from next_is_you.persistence import CloudflareD1Store, VisitRepository
from ntuh_reads import DetailRead, ListRead, listing, progress
from test_ntuh_reader import (
    CHECK_IN_ORDER_CLINIC,
    DAY,
    PAGE,
    LocalDurableStorage,
    TwoPageSource,
    _card,
    counts,
    gate_with_visit,
    page_with,
    reader,
    scope,
    seed_ntuh_at,
    taipei,
)
from test_visit_day_matching import (
    SCHEDULE_FIXTURE,
    VISIT_DAY,
    SwitchableSource,
    at,
    card_page,
    started_three_days_ahead,
    tick_every_minute,
)

# The `11診/合成醫師丙/醫師約診` card of the list fixture links to this ID.
SERVICE_ID = "8000011"


def with_rows(read: ListRead, match, **changes) -> ListRead:
    """`read` with `changes` made to every card `match` accepts."""
    return listing(
        *(replace(row, **changes) if match(row) else row for row in read.rows),
        status=read.status,
    )


def of_doctor(doctor: str):
    return lambda row: row.doctor == doctor


NO_CARD = with_rows(PAGE, of_doctor("合成醫師丙"), doctor="其他醫師")
BLANK_LIST = page_with("")
SUBSTITUTE_LIST = with_rows(PAGE, of_doctor("合成醫師丙"), doctor="住院醫師(代)")
UNUSABLE_PAGES = [
    pytest.param(FetchedPage(404, ""), id="not-found"),
    pytest.param(FetchedPage(410, ""), id="gone"),
    # A page without the progress panel parses as "schema".
    pytest.param(DetailRead("schema"), id="panel-gone"),
    pytest.param(progress(room="合成科 99診", current=26, highest=30), id="room"),
    pytest.param(progress(room="合成科 111診", current=26, highest=30), id="111"),
]


async def running_visit(source, *, patient: int = 28, session: str = "afternoon"):
    """A visit on the fixture clinic that is already running on its day."""
    database, gate = await gate_with_visit(source)
    await seed_ntuh_at(database, gate, "v", DAY, session=session, patient=patient)
    repository = VisitRepository(CloudflareD1Store(database))
    assert await repository.start("v", taipei(0, 1))
    return database, gate


async def tick(gate, hour: int, minute: int) -> dict:
    return await gate.scheduled_tick(taipei(hour, minute).isoformat())


async def kinds(gate) -> list[str]:
    return [event["event_kind"] for event in (await gate.test_snapshot())["events"]]


def stored_number(database):
    return database.connection.execute(
        "SELECT near_last_current_number FROM visits"
    ).fetchone()[0]


# Which page is read, and when


@pytest.mark.asyncio
async def test_the_list_is_read_until_the_card_is_found_then_only_the_progress():
    source = TwoPageSource(NO_CARD, progress())
    r = reader(source)
    # Before the session's published start a missing card is recorded, not an
    # unusable read.
    assert await r.observe(scope(), taipei(12, 40)) == ReadSkipped("card_not_listed")
    source.listed = page_with("024")
    assert await r.observe(scope(), taipei(12, 41)) == ReadSkipped("not_due")
    assert isinstance(await r.observe(scope(), taipei(12, 45)), QueueObservation)
    assert source.list_posts == 2 and not source.detail_urls
    source.detail = progress(current=25, highest=30)
    # From here on only the detail page, every 2 minutes and never sooner.
    for minute in range(46, 60):
        await r.observe(scope(), taipei(12, minute))
    assert source.list_posts == 2
    assert len(source.detail_urls) == 7
    assert all(f"ServiceIDSE={SERVICE_ID}&" in url for url in source.detail_urls)


@pytest.mark.asyncio
async def test_the_list_is_rechecked_every_thirty_minutes_only_until_the_clinic_calls():
    source = TwoPageSource(BLANK_LIST, progress())
    r = reader(source)
    lists = []
    for minute in range(0, 120):
        before = source.list_posts
        requests = len(source.requests)
        await r.observe(scope(), taipei(13 + minute // 60, minute % 60))
        if source.list_posts > before:
            lists.append(minute)
        # One read is one page: never the list and the detail page together.
        assert len(source.requests) - requests <= 2
    assert lists == [0, 30, 60, 90]

    source.detail = progress(current=1, highest=1)
    await r.observe(scope(), taipei(15, 2))
    assert isinstance(await r.observe(scope(), taipei(15, 4)), QueueObservation)
    posts = source.list_posts
    for minute in range(5, 60):
        await r.observe(scope(), taipei(15, minute))
    assert source.list_posts == posts


@pytest.mark.asyncio
async def test_a_failed_recheck_reads_the_detail_page_and_backs_off():
    source = TwoPageSource(BLANK_LIST, progress())
    r = reader(source)
    await r.observe(scope(), taipei(13, 0))
    source.listed = FetchedPage(503, "")
    pending = ReadSkipped("clinic_not_started")
    posts = []
    for minute in range(1, 45):
        before = source.list_posts
        assert await r.observe(scope(), taipei(13, minute)) in (
            pending,
            ReadSkipped("not_due"),
        )
        if source.list_posts > before:
            posts.append(minute)
    # Due at 30; then again no sooner than 5 minutes after each failure.
    assert posts == [30, 36, 42]


@pytest.mark.asyncio
async def test_a_refused_recheck_stops_the_source_for_the_day():
    source = TwoPageSource(BLANK_LIST, progress())
    r = reader(source)
    await r.observe(scope(), taipei(13, 0))
    source.listed = FetchedPage(403, "")
    denied = ReadFailed("unavailable", "access_denied")
    assert await r.observe(scope(), taipei(13, 30)) == denied
    count = len(source.requests)
    assert await r.observe(scope(), taipei(14, 30)) == denied
    assert len(source.requests) == count


@pytest.mark.asyncio
async def test_the_detail_request_carries_the_language_and_no_session_cookie():
    source = TwoPageSource(PAGE, progress(current=25, highest=30))
    r = reader(source)
    await r.observe(scope(), taipei(15, 0))
    await r.observe(scope(), taipei(15, 2))
    request = source.requests[-1]
    headers = dict(request.headers)
    assert request.method == "GET" and request.body is None
    assert headers["Cookie"] == "Localization.CurrentUICulture=zh-TW"
    assert headers["User-Agent"].startswith("next-is-you/")


@pytest.mark.asyncio
async def test_each_page_has_its_own_request_budget(monkeypatch):
    monkeypatch.setattr(ntuh_reader, "REQUEST_TIMEOUT_SECONDS", 0.25)
    # Two list requests of 0.1 s follow a 0.1 s page that does not answer as the
    # clinic's: 0.3 s together, each page inside its own budget.
    source = TwoPageSource(PAGE, progress(current=24, highest=24), delay=0.1)
    r = reader(source)
    assert isinstance(await r.observe(scope(), taipei(15, 0)), QueueObservation)
    source.detail = FetchedPage(404, "")
    assert isinstance(await r.observe(scope(), taipei(15, 2)), QueueObservation)


@pytest.mark.asyncio
async def test_one_read_is_saved_once_and_the_cadence_survives_a_broken_outcome(
    monkeypatch,
):
    class CountingStorage(LocalDurableStorage):
        puts = 0

        async def put(self, key, value):
            self.puts += 1
            await super().put(key, value)

    state = CountingStorage()
    source = TwoPageSource(PAGE, progress(current=25, highest=30))
    r = reader(source, state)
    for minute in (0, 2, 4):
        await r.observe(scope(), taipei(15, minute))
    assert state.puts == 3
    # A repeated read in the same tick changes nothing, so it saves nothing.
    await r.observe(scope(), taipei(15, 4, 10))
    assert state.puts == 3

    monkeypatch.setattr(r, "_outcome", lambda *a, **k: 1 / 0)
    with pytest.raises(ZeroDivisionError):
        await r.observe(scope(), taipei(15, 6))
    count = len(source.requests)
    assert await r.observe(scope(), taipei(15, 7)) == ReadSkipped("not_due")
    assert len(source.requests) == count


# What the page says


@pytest.mark.asyncio
async def test_the_observation_carries_the_progress_fields_the_page_states():
    source = TwoPageSource(
        page_with("024"),
        progress(
            current=25,
            flag="passed",
            highest=30,
            expected=((27, "sequential"), (31, "passed")),
            numbers=(
                (25, "in_consultation"),
                (28, "checked_in"),
                (29, "not_checked_in"),
            ),
        ),
    )
    r = reader(source)
    await r.observe(scope(), taipei(15, 0))
    observation = await r.observe(scope(), taipei(15, 2))

    assert isinstance(observation, QueueObservation)
    assert observation.current_number == 25
    assert observation.highest_called_number == 30
    assert observation.current_flag == "passed"
    assert observation.expected == (
        ExpectedCall(27, "sequential"),
        ExpectedCall(31, "passed"),
    )
    assert observation.numbers == (
        NumberStatus(25, "in_consultation"),
        NumberStatus(28, "checked_in"),
        NumberStatus(29, "not_checked_in"),
    )
    assert observation.called_in_session is True
    assert observation.is_comparable_to(scope())


@pytest.mark.asyncio
async def test_a_repeated_read_in_one_tick_gives_the_same_answer():
    for page in (
        progress(current=26, highest=31),
        progress(highest=31),
        progress(current=1, highest=1),
    ):
        source = TwoPageSource(PAGE, progress(current=25, highest=30))
        r = reader(source)
        await r.observe(scope(), taipei(15, 0))
        await r.observe(scope(), taipei(15, 2))
        source.detail = page
        first = await r.observe(scope(), taipei(15, 4))
        count = len(source.requests)
        assert await r.observe(scope(), taipei(15, 4, 10)) == first
        assert await r.observe_for_start(scope(), taipei(15, 5)) == first
        assert len(source.requests) == count


@pytest.mark.asyncio
@pytest.mark.parametrize("light", ["abc", "000", "9" * 5000, "²"])
async def test_a_garbled_detail_light_is_invalid_data_and_reaches_the_family(light):
    source = TwoPageSource(page_with("010"), progress(current=10, highest=10))
    database, gate = await running_visit(source)
    await tick(gate, 14, 0)
    # A light that is not a number parses as "invalid", whatever it shows.
    source.detail = DetailRead("invalid")
    for minute in (2, 3, 5):
        await tick(gate, 14, minute)
    assert counts(database, "v")[:2] == ("invalid", "invalid_data")
    assert await kinds(gate) == ["unavailable"]
    # The link still leads to the clinic's page, so the list is not read again.
    assert source.list_posts == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("light", ["9" * 5000, "000", "²"])
async def test_a_garbled_list_light_never_raises(light):
    r = reader(TwoPageSource(page_with(light), progress()))
    assert await r.observe(scope(), taipei(15, 0)) == ReadFailed(
        "invalid", "invalid_data"
    )


# Called in this session


@pytest.mark.asyncio
async def test_before_the_clinic_calls_the_visit_is_pending_and_sends_nothing():
    page = progress(numbers=((28, "not_checked_in"), (29, "first_visit")))
    source = TwoPageSource(BLANK_LIST, page)
    database, gate = await running_visit(source)
    created = await tick_every_minute(gate, taipei(13, 0), taipei(14, 30))
    assert created == 0 and await kinds(gate) == []
    assert counts(database, "v") == ("unavailable", "no_observation", 0)


@pytest.mark.asyncio
async def test_a_pending_read_delivers_the_facts_but_never_a_comparable_number():
    frozen = progress(
        current=22, highest=80, numbers=((28, "not_checked_in"), (29, "first_visit"))
    )
    r = reader(TwoPageSource(BLANK_LIST, frozen))
    listed = await r.observe(scope(), taipei(13, 0))
    assert listed.progress.called_in_session is False
    pending = await r.observe(scope(), taipei(13, 2))
    assert pending == ReadSkipped("clinic_not_started")
    assert pending.progress.called_in_session is False
    assert pending.progress.numbers == (
        NumberStatus(28, "not_checked_in"),
        NumberStatus(29, "first_visit"),
    )
    assert pending.progress.is_comparable_to(scope()) is False


@pytest.mark.asyncio
async def test_a_page_frozen_from_an_earlier_session_is_not_called_in_this_session():
    frozen = progress(current=22, highest=80, numbers=((30, "checked_in"),))
    source = TwoPageSource(BLANK_LIST, frozen)
    r = reader(source)
    # The leftover light and highest called of the morning are on the afternoon's
    # page before it starts; unchanged, they are not a call.
    for minute in range(0, 40, 2):
        assert await r.observe(scope(), taipei(13, minute)) == ReadSkipped(
            "clinic_not_started"
        )
    source.detail = progress(current=5, highest=5)
    observation = await r.observe(scope(), taipei(13, 40))
    assert isinstance(observation, QueueObservation)
    assert observation.called_in_session is True
    assert observation.current_number == 5


@pytest.mark.asyncio
async def test_a_frozen_page_that_only_clears_is_not_a_call():
    frozen = progress(current=22, highest=80)
    source = TwoPageSource(BLANK_LIST, frozen)
    r = reader(source)
    for minute in (0, 2, 4):
        await r.observe(scope(), taipei(13, minute))
    for page in (progress(highest=80), progress(), frozen):
        source.detail = page
        for _ in range(3):
            result = await r.observe(scope(), taipei(13, minute := minute + 2))
            assert result == ReadSkipped("clinic_not_started")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "resets",
    [
        pytest.param(
            [progress(highest=80), progress(current=1, highest=1)],
            id="light-clears-first",
        ),
        pytest.param(
            [progress(current=1, highest=80)], id="light-resets-before-highest"
        ),
    ],
)
async def test_the_frozen_highest_called_never_looks_like_a_later_block(resets):
    # The page of the day keeps 22/80 until the clinic starts; patient 28's clinic
    # then calls 20 to 31, and 25, 26 and 27 are each a near reminder.
    source = TwoPageSource(BLANK_LIST, progress(current=22, highest=80))
    database, gate = await running_visit(source)
    await tick(gate, 13, 0)
    await tick(gate, 13, 2)
    # The page's unexplained number asks the list once; the resets come after it.
    await tick(gate, 13, 4)
    assert source.list_posts == 2
    minute = 6
    for page in (*resets, *(progress(current=n, highest=n) for n in range(20, 32))):
        source.detail = page
        await tick(gate, 13, minute)
        minute += 2
    assert await kinds(gate) == ["near"] * 3


@pytest.mark.asyncio
async def test_a_number_on_the_list_card_says_the_clinic_has_called():
    # A read that starts mid-session has no frozen baseline to compare with.
    r = reader(TwoPageSource(PAGE, progress(current=25, highest=30)))
    observation = await r.observe(scope(), taipei(15, 0))
    assert observation.called_in_session is True and observation.current_number == 25
    observation = await r.observe(scope(), taipei(15, 2))
    assert observation.called_in_session is True


@pytest.mark.asyncio
async def test_a_clinic_that_called_between_the_two_pages_is_noticed_at_once():
    # The list was read just before the first call and the page just after it, so
    # the page's number looks frozen until the list is asked again.
    source = TwoPageSource(BLANK_LIST, progress(current=25, highest=25))
    database, gate = await running_visit(source)
    await tick(gate, 13, 30)
    source.listed = PAGE
    await tick(gate, 13, 32)
    assert await kinds(gate) == []
    await tick(gate, 13, 34)
    assert await kinds(gate) == ["near"]


@pytest.mark.asyncio
async def test_a_number_that_never_changes_asks_the_list_once_not_on_every_read():
    source = TwoPageSource(BLANK_LIST, progress(current=22, highest=80))
    r = reader(source)
    for minute in range(0, 30):
        await r.observe(scope(), taipei(13, minute))
    assert source.list_posts == 2


# Situations no one has observed, and clinics without a current number


@pytest.mark.asyncio
async def test_an_evening_session_is_recorded_and_sends_nothing(capsys):
    source = TwoPageSource(PAGE, progress(current=25, highest=30))
    database, gate = await running_visit(source, session="evening")
    for minute, number in ((0, 25), (2, 26), (4, 27)):
        source.detail = progress(current=number, highest=30)
        await tick(gate, 19, minute)
    assert await kinds(gate) == []
    assert counts(database, "v") == ("unavailable", "no_observation", 0)
    logged = [
        json.loads(line)
        for line in capsys.readouterr().out.splitlines()
        if "ntuh_unobserved_situation" in line
    ]
    assert logged == [
        {
            "event": "ntuh_unobserved_situation",
            "situation": "evening_session",
            "session": "evening",
            "date": "2026-10-22",
        }
    ]


@pytest.mark.asyncio
async def test_an_evening_card_without_a_detail_link_sends_nothing_either():
    source = TwoPageSource(with_rows(PAGE, lambda row: True, service_id=""), progress())
    database, gate = await running_visit(source, session="evening")
    await tick(gate, 19, 0)
    assert await kinds(gate) == []
    assert not source.detail_urls


@pytest.mark.asyncio
async def test_an_evening_substitute_is_still_shown_to_the_organizer():
    source = TwoPageSource(
        SUBSTITUTE_LIST, progress(doctor="住院醫師", current=25, highest=25)
    )
    database, gate = await running_visit(source, session="evening")
    for minute in (0, 2):
        await tick(gate, 19, minute)
        assert counts(database, "v")[:2] == ("unavailable", "substitute_doctor")


@pytest.mark.asyncio
async def test_an_evening_source_that_fails_still_reaches_the_family():
    source = TwoPageSource(FetchedPage(503, ""), FetchedPage(503, ""))
    database, gate = await running_visit(source, session="evening")
    for minute in (0, 2, 3, 5):
        await tick(gate, 19, minute)
    assert await kinds(gate) == ["unavailable"]


@pytest.mark.asyncio
async def test_a_blank_after_the_clinic_called_is_not_a_failure_and_sends_nothing():
    source = TwoPageSource(page_with("010"), progress(current=10, highest=10))
    database, gate = await running_visit(source)
    await tick(gate, 14, 0)
    await tick(gate, 14, 2)
    assert stored_number(database) == 10
    source.detail = progress(
        highest=10, numbers=((28, "checked_in"), (29, "not_checked_in"))
    )
    await tick_every_minute(gate, taipei(14, 3), taipei(20, 0))
    # The organizer no longer sees the number of hours ago as usable.
    assert counts(database, "v") == ("unavailable", "empty_result", 0)
    assert stored_number(database) is None
    assert await kinds(gate) == []


@pytest.mark.asyncio
async def test_a_blank_carries_the_numbers_and_a_resumed_clinic_is_recorded():
    state = LocalDurableStorage()
    source = TwoPageSource(PAGE, progress(current=25, highest=30))
    r = reader(source, state)
    await r.observe(scope(), taipei(15, 0))
    await r.observe(scope(), taipei(15, 2))
    source.detail = progress(highest=30, numbers=((31, "checked_in"),))
    blank = await r.observe(scope(), taipei(15, 4))
    assert blank == ReadSkipped("blank_after_call")
    assert blank.progress.called_in_session is True
    assert blank.progress.numbers == (NumberStatus(31, "checked_in"),)
    assert blank.progress.is_comparable_to(scope()) is False

    def recorded():
        (entry,) = json.loads(state.values[STATE_KEY]).values()
        return entry.get("unobserved")

    # Every clinic observed stayed blank after its last call, so the blank alone
    # is not the unobserved situation; calling again after it is.
    assert recorded() is None
    source.detail = progress(current=31, highest=31)
    assert isinstance(await r.observe(scope(), taipei(15, 6)), QueueObservation)
    assert recorded() == ["midday_blank"]


@pytest.mark.asyncio
async def test_a_later_block_is_recorded_and_sends_nothing():
    state = LocalDurableStorage()
    source = TwoPageSource(PAGE, progress(current=25, highest=30))
    r = reader(source, state)
    await r.observe(scope(), taipei(15, 0))
    await r.observe(scope(), taipei(15, 2))
    source.detail = progress(current=1, highest=1, numbers=((2, "checked_in"),))
    flagged = await r.observe(scope(), taipei(15, 4))
    assert flagged == ReadSkipped(
        "unobserved_situation", unobserved="later_block_opening"
    )
    assert flagged.progress.numbers == (NumberStatus(2, "checked_in"),)
    (entry,) = json.loads(state.values[STATE_KEY]).values()
    assert entry["unobserved"] == ["later_block_opening"]


@pytest.mark.asyncio
async def test_a_check_in_order_clinic_delivers_its_position_and_sends_nothing():
    source = TwoPageSource(BLANK_LIST, progress(check_in_order=True))
    database, gate = await running_visit(source)
    await tick(gate, 13, 30)
    source.detail = progress(
        current=26,
        check_in_order=True,
        check_in_position=3,
        numbers=((28, "checked_in", 5),),
    )
    await tick(gate, 13, 32)
    source.detail = replace(source.detail, check_in_position=4)
    await tick(gate, 13, 34)
    assert await kinds(gate) == []

    r = gate._hospital_reader()
    result = await r.observe(scope(), taipei(13, 34))
    assert result == ReadSkipped("check_in_order")
    assert result.progress.check_in_order is True
    assert result.progress.check_in_position == 4
    assert result.progress.called_in_session is True
    assert result.progress.numbers == (NumberStatus(28, "checked_in", 5),)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("session", "page"),
    [
        ("evening", progress(current=25, highest=30)),
        ("afternoon", progress(current=3, check_in_order=True, check_in_position=3)),
        ("afternoon", progress(highest=30)),
    ],
)
async def test_start_is_accepted_while_the_found_clinic_shows_no_usable_number(
    session, page
):
    source = TwoPageSource(PAGE, page)
    database, gate = await gate_with_visit(source)
    await seed_ntuh_at(database, gate, "v", DAY, session=session)
    r = gate._hospital_reader()
    hour = 19 if session == "evening" else 15
    for minute in (0, 2):
        await r.observe(scope(session=ClinicSession(session)), taipei(hour, minute))
    started = await gate.start_visit("v", taipei(hour, 3).isoformat())
    assert started == {"state": "active"}


# The link and the clinic it leads to


@pytest.mark.asyncio
@pytest.mark.parametrize("page", UNUSABLE_PAGES)
async def test_a_link_that_stops_leading_to_the_clinic_falls_back_to_the_list(page):
    source = TwoPageSource(page_with("024"), progress(current=24, highest=24))
    database, gate = await running_visit(source)
    await tick(gate, 15, 0)
    await tick(gate, 15, 2)
    source.detail = page
    source.listed = page_with("026")
    await tick(gate, 15, 4)
    # 26 is the list's; the wrong page's own number is never used.
    assert counts(database, "v") == ("usable", "none", 0)
    assert stored_number(database) == 26
    assert await kinds(gate) == ["near"]
    # The same link is not asked for again on every read.
    details = len(source.detail_urls)
    await tick_every_minute(gate, taipei(15, 5), taipei(15, 33))
    assert len(source.detail_urls) == details
    source.detail = progress(current=27, highest=27)
    await tick_every_minute(gate, taipei(15, 34), taipei(15, 37))
    assert len(source.detail_urls) > details
    assert stored_number(database) == 27


@pytest.mark.asyncio
@pytest.mark.parametrize("page", UNUSABLE_PAGES)
async def test_a_dead_link_before_the_session_starts_messages_no_one_and_recovers(page):
    source = TwoPageSource(BLANK_LIST, page)
    database, gate = await running_visit(source)
    await tick_every_minute(gate, taipei(12, 30), taipei(13, 29))
    assert await kinds(gate) == []
    assert counts(database, "v") == ("unavailable", "no_observation", 0)
    source.listed = PAGE
    await tick_every_minute(gate, taipei(13, 30), taipei(13, 36))
    assert await kinds(gate) == ["near"]


@pytest.mark.asyncio
async def test_a_new_link_is_followed_and_learns_the_page_afresh():
    source = TwoPageSource(BLANK_LIST, progress(current=22, highest=80))
    r = reader(source)
    await r.observe(scope(), taipei(13, 0))
    await r.observe(scope(), taipei(13, 2))
    source.listed = with_rows(
        BLANK_LIST, lambda row: row.service_id == SERVICE_ID, service_id="8000099"
    )
    source.detail = FetchedPage(404, "")
    assert await r.observe(scope(), taipei(13, 4)) == ReadSkipped("clinic_not_started")
    source.detail = progress(current=60, highest=70)
    assert await r.observe(scope(), taipei(13, 6)) == ReadSkipped("clinic_not_started")
    assert "ServiceIDSE=8000099&" in source.detail_urls[-1]


@pytest.mark.asyncio
async def test_a_card_that_disappears_before_the_clinic_calls_is_noticed():
    source = TwoPageSource(BLANK_LIST, progress())
    database, gate = await running_visit(source)
    await tick(gate, 12, 30)
    await tick(gate, 12, 32)
    source.listed = NO_CARD
    await tick_every_minute(gate, taipei(12, 33), taipei(13, 29))
    # The organizer sees it at once; the family is not messaged until it counts.
    assert counts(database, "v")[:2] == ("unavailable", "card_not_found")
    assert await kinds(gate) == []
    await tick_every_minute(gate, taipei(13, 30), taipei(14, 0))
    assert await kinds(gate) == ["unavailable"]


@pytest.mark.asyncio
async def test_a_substitute_who_takes_the_clinic_before_it_calls_is_noticed():
    source = TwoPageSource(BLANK_LIST, progress())
    database, gate = await running_visit(source)
    await tick(gate, 13, 0)
    await tick(gate, 13, 2)
    assert counts(database, "v")[:2] == ("unavailable", "no_observation")
    source.listed = with_rows(
        BLANK_LIST, of_doctor("合成醫師丙"), doctor="住院醫師(代)"
    )
    await tick_every_minute(gate, taipei(13, 3), taipei(13, 30))
    assert counts(database, "v")[:2] == ("unavailable", "substitute_doctor")
    source.detail = progress(doctor="住院醫師", current=25, highest=25)
    await tick(gate, 13, 32)
    assert counts(database, "v")[:2] == ("usable", "substitute_doctor")


@pytest.mark.asyncio
async def test_a_refused_detail_page_stops_the_source_for_the_day():
    source = TwoPageSource(PAGE, progress(current=25, highest=30))
    r = reader(source)
    await r.observe(scope(), taipei(15, 0))
    # A captcha page parses as "challenge".
    source.detail = DetailRead("challenge")
    refused = await r.observe(scope(), taipei(15, 2))
    assert refused == ReadFailed("unavailable", "access_denied")
    count = len(source.requests)
    again = await r.observe(scope(), taipei(15, 40))
    assert again.reason == "access_denied" and len(source.requests) == count


@pytest.mark.asyncio
async def test_a_redirected_detail_page_stops_reading_the_session_for_the_day():
    source = TwoPageSource(page_with("010"), progress(current=10, highest=10))
    database, gate = await running_visit(source)
    await tick(gate, 15, 0)
    source.detail = FetchedPage(302, "")
    await tick(gate, 15, 2)
    assert counts(database, "v")[:2] == ("unavailable", "access_denied")
    count = len(source.requests)
    # Healthy again, and in the near window, but a refusal is never read around.
    source.detail = progress(current=26, highest=26)
    source.listed = page_with("026")
    await tick_every_minute(gate, taipei(15, 3), taipei(16, 0))
    assert len(source.requests) == count
    assert await kinds(gate) == ["unavailable"]


@pytest.mark.asyncio
async def test_a_list_read_states_no_numbers_and_an_empty_page_states_none_left():
    source = TwoPageSource(PAGE, progress(current=25, highest=25))
    r = reader(source)
    listed = await r.observe(scope(), taipei(15, 0))
    # The list card does not show the numbers: unknown, not "nobody is waiting".
    assert listed.current_number == 25 and listed.numbers is None
    read = await r.observe(scope(), taipei(15, 2))
    assert read.current_number == 25 and read.numbers == ()
    source.detail = FetchedPage(404, "")
    fallback = await r.observe(scope(), taipei(15, 4))
    assert fallback.current_number == 25 and fallback.numbers is None


# Near and unavailable on detail-page observations


@pytest.mark.asyncio
async def test_near_follows_the_detail_light_whatever_the_list_says():
    source = TwoPageSource(page_with("010"), progress(current=10, highest=40))
    database, gate = await running_visit(source)
    await tick(gate, 15, 0)
    for minute, light in ((2, 24), (4, 25), (6, 25), (8, 27), (10, 26), (12, 28)):
        source.detail = progress(current=light, highest=40)
        await tick(gate, 15, minute)
    # 25, 27 and 26 each moved inside the window of patient 28; the repeated 25
    # and the numbers outside it did not.
    assert await kinds(gate) == ["near"] * 3


@pytest.mark.asyncio
async def test_three_failed_detail_reads_send_one_unavailable_message():
    source = TwoPageSource(page_with("010"), progress(current=10, highest=10))
    database, gate = await running_visit(source)
    await tick(gate, 15, 0)
    source.detail = source.listed = FetchedPage(503, "")
    for minute in (2, 3, 5, 9, 13):
        await tick(gate, 15, minute)
    assert await kinds(gate) == ["unavailable"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "outage", [FetchedPage(500, ""), FetchedPage(503, ""), TimeoutError()]
)
async def test_a_page_that_keeps_failing_gives_way_to_a_healthy_list(outage):
    # A dead link may well answer 500. The list alone is what the family had.
    source = TwoPageSource(BLANK_LIST, outage)
    database, gate = await running_visit(source)
    await tick_every_minute(gate, taipei(12, 30), taipei(13, 29))
    assert await kinds(gate) == []
    source.listed = page_with("026")
    await tick_every_minute(gate, taipei(13, 30), taipei(13, 40))
    assert await kinds(gate) == ["near"]
    assert counts(database, "v") == ("usable", "none", 0)


@pytest.mark.asyncio
async def test_one_failed_page_keeps_the_link_and_never_asks_the_list():
    source = TwoPageSource(page_with("024"), FetchedPage(503, ""))
    r = reader(source)
    await r.observe(scope(), taipei(15, 0))
    assert isinstance(await r.observe(scope(), taipei(15, 2)), ReadFailed)
    source.detail = progress(current=25, highest=25)
    assert (await r.observe(scope(), taipei(15, 3))).current_number == 25
    assert source.list_posts == 1


@pytest.mark.asyncio
async def test_a_dead_page_behind_a_failed_recheck_is_dropped_too():
    state = LocalDurableStorage()
    source = TwoPageSource(BLANK_LIST, progress())
    r = reader(source, state)
    await r.observe(scope(), taipei(13, 0))
    source.listed, source.detail = FetchedPage(503, ""), FetchedPage(404, "")
    assert await r.observe(scope(), taipei(13, 30)) == ReadFailed(
        "unavailable", "no_observation"
    )
    (entry,) = json.loads(state.values[STATE_KEY]).values()
    assert "service_id" not in entry


@pytest.mark.asyncio
async def test_a_throttled_source_is_left_alone_on_both_pages():
    source = TwoPageSource(BLANK_LIST, progress())
    r = reader(source)
    await r.observe(scope(), taipei(13, 0))
    for minute in range(2, 30, 2):
        await r.observe(scope(), taipei(13, minute))
    source.listed = FetchedPage(429, "", retry_after=600)
    assert isinstance(await r.observe(scope(), taipei(13, 30)), ReadFailed)
    count = len(source.requests)
    for minute in range(31, 40):
        assert await r.observe(scope(), taipei(13, minute)) == ReadSkipped("not_due")
    assert len(source.requests) == count
    # The same holds when the detail page is the one that asks, twice in a row.
    source.listed = BLANK_LIST
    await r.observe(scope(), taipei(13, 40))
    source.detail = FetchedPage(429, "")
    posts = source.list_posts
    for minute in (42, 43, 45):
        assert isinstance(await r.observe(scope(), taipei(13, minute)), ReadFailed)
    assert source.list_posts == posts


@pytest.mark.asyncio
async def test_a_reminder_with_an_unknown_outcome_is_retried_after_the_page_blanks():
    source = TwoPageSource(page_with("010"), progress(current=26, highest=26))
    database, gate = await running_visit(source)
    await tick(gate, 14, 0)
    await gate.set_test_line_mode("unknown")
    await tick(gate, 14, 2)
    await gate.set_test_line_mode("accepted")
    source.detail = progress(highest=26)
    await tick(gate, 14, 4)
    (event,) = (await gate.test_snapshot())["events"]
    assert (event["outcome"], event["attempt_count"]) == ("accepted", 2)


@pytest.mark.asyncio
async def test_a_check_in_order_clinic_never_ends_on_list_reads():
    source = TwoPageSource(
        PAGE,
        progress(room="合成科 99診", check_in_order=True, check_in_position=3),
    )
    r = reader(source)
    clinic = scope(CHECK_IN_ORDER_CLINIC)
    await r.observe(clinic, taipei(14, 0))
    unknown = await r.observe(clinic, taipei(14, 2))
    # Nothing says whether an unchanged position is this session's.
    assert unknown == ReadSkipped("clinic_not_started")
    assert unknown.progress.called_in_session is None
    source.detail = replace(source.detail, check_in_position=4)
    assert await r.observe(clinic, taipei(14, 4)) == ReadSkipped("check_in_order")
    source.detail = FetchedPage(404, "")
    for minute in (6, 8, 10, 12):
        listed = await r.observe(clinic, taipei(14, minute))
        assert listed == ReadSkipped("check_in_order")
        assert listed.progress.check_in_order is True


@pytest.mark.asyncio
async def test_a_page_the_list_contradicts_is_not_used():
    # The page still shows the earlier session's 26 of 30 while the list, which is
    # this session's, has called 1.
    source = TwoPageSource(BLANK_LIST, progress(current=26, highest=30))
    database, gate = await running_visit(source)
    await tick(gate, 13, 30)
    await tick(gate, 13, 32)
    source.listed = page_with("001")
    await tick_every_minute(gate, taipei(13, 33), taipei(14, 20))
    assert await kinds(gate) == []
    assert stored_number(database) == 1


@pytest.mark.asyncio
async def test_a_readable_page_between_failures_ends_their_run():
    source = TwoPageSource(page_with("010"), progress(current=10, highest=10))
    database, gate = await running_visit(source)
    await tick(gate, 14, 0)
    source.detail = source.listed = FetchedPage(503, "")
    await tick(gate, 14, 2)
    await tick(gate, 14, 3)
    assert counts(database, "v")[2] == 2
    source.detail, source.listed = progress(highest=10), page_with("010")
    await tick_every_minute(gate, taipei(14, 4), taipei(16, 59))
    source.detail = source.listed = FetchedPage(503, "")
    await tick(gate, 17, 1)
    assert counts(database, "v")[2] == 1
    assert await kinds(gate) == []


@pytest.mark.asyncio
async def test_a_visit_started_days_ahead_reads_the_detail_page_on_its_day():
    source = SwitchableSource(
        card_page(_card("03 診", "合成醫師甲", "普通門診", "")),
        schedule=SCHEDULE_FIXTURE,
        details=[progress(room="合成科 03診", doctor="合成醫師甲")],
    )
    database, gate = await started_three_days_ahead(source)
    assert not source.detail_requests

    await gate.scheduled_tick(at(VISIT_DAY, 8, 40).isoformat())
    await gate.scheduled_tick(at(VISIT_DAY, 8, 42).isoformat())
    source.details = [
        progress(room="合成科 03診", doctor="合成醫師甲", current=12, highest=15)
    ]
    called = await gate.scheduled_tick(at(VISIT_DAY, 8, 44).isoformat())

    assert called["events_created"] == 1
    assert await kinds(gate) == ["near"]
    service_id = _card("03 診", "合成醫師甲", "普通門診").service_id
    assert len(source.detail_requests) == 2
    assert all(f"ServiceIDSE={service_id}" in r.url for r in source.detail_requests)

    # The link is kept only in that day's transient state, never in the database.
    assert service_id in await gate.ctx.storage.get(STATE_KEY)
    assert service_id not in "".join(database.connection.iterdump())
    await gate.scheduled_tick(at(VISIT_DAY + timedelta(days=1), 0, 5).isoformat())
    assert service_id not in json.dumps(gate.ctx.storage.values, default=str)


# The link never outlives its day


async def linked_gate():
    source = TwoPageSource(page_with("010"), progress(current=10, highest=10))
    database, gate = await running_visit(source)
    await tick(gate, 15, 0)
    await tick(gate, 15, 2)
    assert SERVICE_ID in gate.ctx.storage.values[STATE_KEY]
    return database, gate


async def recovery_hold(gate):
    await gate.ctx.storage.put("recovery_hold", True)


async def ledger_mismatch(gate):
    await gate.ctx.storage.put("scheduler_ledger_digest", "changed")


async def send_hold(gate):
    gate.env["NIY_ENVIRONMENT"] = "production"


async def reader_off(gate):
    gate.env.pop("NTUH_READER_ENABLED")


async def nothing_held(gate):
    pass


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "held", [nothing_held, recovery_hold, ledger_mismatch, send_hold, reader_off]
)
async def test_the_link_is_dropped_the_next_day_whatever_holds_the_tick(held):
    database, gate = await linked_gate()
    await held(gate)
    # The same day keeps it, so a hold does not cost the running visit its state.
    await tick(gate, 23, 58)
    assert SERVICE_ID in gate.ctx.storage.values[STATE_KEY]
    await gate.scheduled_tick((taipei(0, 1) + timedelta(days=1)).isoformat())
    assert SERVICE_ID not in json.dumps(gate.ctx.storage.values, default=str)


@pytest.mark.asyncio
async def test_a_failing_cleanup_never_stops_the_tick(monkeypatch, capsys):
    database, gate = await linked_gate()

    async def boom(*args):
        raise RuntimeError("storage")

    monkeypatch.setattr("next_is_you.send_gate.forget_other_days", boom)
    await gate.scheduled_tick((taipei(0, 1) + timedelta(days=1)).isoformat())
    state = database.connection.execute("SELECT state FROM visits").fetchone()[0]
    assert state == "expired"
    assert "forget_other_days_failed" in capsys.readouterr().out


@pytest.mark.asyncio
@pytest.mark.parametrize("raw", ["not json", "[1]", '"x"'])
async def test_unreadable_reader_state_is_dropped_whole(raw):
    storage = LocalDurableStorage({STATE_KEY: raw})
    await forget_other_days(storage, DAY)
    assert storage.values[STATE_KEY] == "{}"


@pytest.mark.asyncio
async def test_a_refusal_of_today_survives_the_cleanup():
    yesterday = DAY - timedelta(days=1)
    storage = LocalDurableStorage(
        {
            STATE_KEY: json.dumps(
                {
                    f"T0|OPH|afternoon|blocked|{DAY}": {"blocked": True},
                    f"T0|OPH|morning|{DAY}": {"blocked": True},
                    f"T0|OPH|afternoon|clinic|[]|{yesterday}": {"service_id": "1"},
                }
            )
        }
    )
    await forget_other_days(storage, DAY)
    kept = json.loads(storage.values[STATE_KEY])
    assert sorted(kept) == [
        f"T0|OPH|afternoon|blocked|{DAY}",
        f"T0|OPH|morning|{DAY}",
    ]
    source = TwoPageSource(PAGE, progress())
    refused = await reader(source, storage).observe(scope(), taipei(13, 0))
    assert refused.reason == "access_denied" and not source.requests


# The local synthetic observation hook


async def hooked_gate():
    database, gate = await gate_with_visit(
        TwoPageSource(PAGE, progress()), enabled=False
    )
    return gate


@pytest.mark.asyncio
async def test_the_local_synthetic_observation_hook_accepts_the_progress_fields():
    gate = await hooked_gate()
    assert await gate.set_test_observation(
        25,
        True,
        {
            "highest_called_number": 30,
            "current_flag": "senior",
            "called_in_session": True,
            "expected": [[27, "sequential", None]],
            "numbers": [[28, "checked_in", None], [29, "checked_in", 2]],
        },
    )
    observation = await gate._hospital_reader().observe(scope(), taipei(15, 0))
    assert observation.current_number == 25
    assert observation.highest_called_number == 30
    assert observation.current_flag == "senior"
    assert observation.called_in_session is True
    assert observation.expected == (ExpectedCall(27, "sequential"),)
    assert observation.numbers == (
        NumberStatus(28, "checked_in"),
        NumberStatus(29, "checked_in", 2),
    )
    # A later observation without progress clears the scripted one.
    assert await gate.set_test_observation(26, True)
    observation = await gate._hospital_reader().observe(scope(), taipei(15, 2))
    assert observation.numbers is None and observation.called_in_session is None
    # A scripted page with no number left is empty, not absent.
    assert await gate.set_test_observation(27, True, {"numbers": []})
    observation = await gate._hospital_reader().observe(scope(), taipei(15, 4))
    assert observation.numbers == ()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("progress", "reason"),
    [
        ({"called_in_session": False}, "clinic_not_started"),
        ({"check_in_order": True, "check_in_position": 4}, "check_in_order"),
    ],
)
async def test_the_hook_reports_a_waiting_clinic_the_way_a_reader_does(
    progress, reason
):
    gate = await hooked_gate()
    numbers = {"numbers": [[28, "not_checked_in", None]]}
    for current in (None, 27):
        assert await gate.set_test_observation(current, True, {**progress, **numbers})
        result = await gate._hospital_reader().observe(scope(), taipei(15, 0))
        assert result == ReadSkipped(reason)
        assert result.progress.numbers == (NumberStatus(28, "not_checked_in"),)
        assert result.progress.is_comparable_to(scope()) is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "progress",
    [
        [1],
        "x",
        {"highest": 5},
        {"expected": [5]},
        {"expected": [[27, "later"]]},
        {"numbers": [[28, "gone"]]},
        {"numbers": [["28", "checked_in"]]},
        {"highest_called_number": 0},
        {"current_flag": "unknown"},
        {"current_flag": "check_in"},
        {"called_in_session": "yes"},
        {"called_in_session": 0},
        {"check_in_order": 1},
    ],
)
async def test_the_hook_refuses_fields_it_cannot_hold(progress):
    gate = await hooked_gate()
    assert await gate.set_test_observation(25, True)
    assert await gate.set_test_observation(5, True, progress) is False
    observation = await gate._hospital_reader().observe(scope(), taipei(15, 0))
    assert observation.current_number == 25
