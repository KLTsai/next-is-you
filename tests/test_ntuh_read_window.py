"""Issue #181: a clinic is read only from one hour before its published start.

Fixture/mock evidence: a fixed clock, a fake hospital transport, and Start and the
scheduled tick run through the send gate. Nothing reaches the hospital.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from next_is_you.domain import ReadSkipped
from next_is_you.ntuh_reader import FetchedPage
from ntuh_detail_pages import detail_page
from test_ntuh_detail_reading import BLANK_LIST, kinds, running_visit, tick
from test_ntuh_reader import (
    DAY,
    PAGE,
    TwoPageSource,
    counts,
    gate_with_visit,
    reader,
    scope,
    seed_ntuh_at,
    taipei,
)
from test_visit_day_matching import tick_every_minute

NOT_DUE = ReadSkipped("not_due")
FIRST_READ = [
    pytest.param("morning", (8, 0), id="morning"),
    pytest.param("afternoon", (12, 30), id="afternoon"),
    pytest.param("evening", (17, 0), id="evening"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(("session", "first"), FIRST_READ)
async def test_the_first_scheduled_read_leaves_one_hour_before_the_published_start(
    session, first
):
    source = TwoPageSource(BLANK_LIST, detail_page())
    _, gate = await running_visit(source, session=session)
    await tick_every_minute(gate, taipei(0, 1), taipei(*first) - timedelta(minutes=1))
    assert source.requests == []
    await tick(gate, *first)
    assert source.list_posts == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [403, 503])
async def test_a_page_that_fails_before_the_first_read_neither_blocks_nor_messages(
    status,
):
    source = TwoPageSource(FetchedPage(status, ""), FetchedPage(status, ""))
    database, gate = await running_visit(source)
    await tick_every_minute(gate, taipei(0, 1), taipei(12, 29))
    assert source.requests == []
    assert await kinds(gate) == []
    assert counts(database, "v")[2] == 0
    # The source is healthy by the first read, and nothing earlier is held against it.
    source.listed, source.detail = PAGE, detail_page(current=25, highest=25)
    await tick(gate, 12, 30)
    assert counts(database, "v") == ("usable", "none", 0)
    assert await kinds(gate) == ["near"]


@pytest.mark.asyncio
async def test_start_before_the_first_read_reads_once_and_nothing_follows_until_then():
    source = TwoPageSource(BLANK_LIST, detail_page())
    database, gate = await gate_with_visit(source)
    await seed_ntuh_at(database, gate, "v", DAY)
    assert await gate.start_visit("v", taipei(7, 0).isoformat()) == {"state": "active"}
    # The roster's three sessions confirm the clinic; then the one read of it.
    assert source.list_posts == 4 and source.detail_urls == []
    requests = len(source.requests)
    # What Start found stays shown while nothing is read.
    found = counts(database, "v")
    await tick_every_minute(gate, taipei(7, 1), taipei(12, 29))
    assert len(source.requests) == requests
    assert counts(database, "v") == found == ("unavailable", "no_observation", 0)
    await tick(gate, 12, 30)
    assert source.list_posts == 5


@pytest.mark.asyncio
async def test_a_substitute_found_by_an_early_start_stays_shown_until_the_first_read():
    source = TwoPageSource(
        BLANK_LIST.replace("合成醫師丙", "住院醫師(代)"), detail_page()
    )
    database, gate = await gate_with_visit(source)
    await seed_ntuh_at(database, gate, "v", DAY)
    assert await gate.start_visit("v", taipei(7, 0).isoformat()) == {"state": "active"}
    await tick_every_minute(gate, taipei(7, 1), taipei(12, 29))
    assert counts(database, "v") == ("unavailable", "substitute_doctor", 0)


@pytest.mark.asyncio
async def test_a_clinic_that_called_before_its_first_read_is_seen_as_called():
    # It called early: the list card shows a number, and the page a frozen-looking one.
    source = TwoPageSource(PAGE, detail_page(current=25, highest=30))
    r = reader(source)
    assert await r.observe(scope(), taipei(12, 29)) == NOT_DUE
    first = await r.observe(scope(), taipei(12, 30))
    assert first.current_number == 25 and first.called_in_session is True
    second = await r.observe(scope(), taipei(12, 32))
    assert second.current_number == 25 and second.called_in_session is True


@pytest.mark.asyncio
async def test_a_clinic_that_first_calls_late_in_its_session_is_still_followed():
    # An afternoon clinic first showed a number after 16:05 on 2026-11-20; here 18:00.
    source = TwoPageSource(BLANK_LIST, detail_page())
    _, gate = await running_visit(source)
    await tick_every_minute(gate, taipei(12, 30), taipei(17, 59))
    source.listed, source.detail = PAGE, detail_page(current=25, highest=25)
    await tick_every_minute(gate, taipei(18, 0), taipei(18, 2))
    assert await kinds(gate) == ["near"]


@pytest.mark.asyncio
async def test_a_visit_whose_clinic_never_called_ends_at_the_end_of_the_day():
    source = TwoPageSource(BLANK_LIST, detail_page())
    database, gate = await running_visit(source)
    await tick_every_minute(gate, taipei(12, 30), taipei(23, 59))
    (state,) = database.connection.execute("SELECT state FROM visits").fetchone()
    assert state == "expired"
    assert await kinds(gate) == []
