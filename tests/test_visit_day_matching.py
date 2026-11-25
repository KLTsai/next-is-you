"""Issue #135: a visit finds its card on the visit day, or its organizer is told.

Fixture/mock evidence: Start and the scheduled tick run through the send gate, the
real registry and a fake hospital transport. The cards use the shape NTUH showed
on 2026-11-20 (`03 診`, `普通門診`) and the clinic code a schedule-picked visit
stores (`03/醫師/角膜`, the room without 診 and the schedule's 診別).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from ntuh_reads import ListRead, card, listing, of_doctor, plus, with_rows
from test_ntuh_reader import (
    DAY,
    PAGE,
    SCHEDULE_FIXTURE,
    SCHEDULE_FIRST_VISIT,
    FakeSource,
    counts,
    gate_with_visit,
    page_with,
    seed_ntuh_at,
    taipei,
)

# This module serves NTUH reader values (#205).
pytestmark = pytest.mark.usefixtures("serve_reader_values")

SCHEDULE_FORM = "11/合成醫師丙/角膜"
TAIPEI = timezone(timedelta(hours=8))


class SwitchableSource(FakeSource):
    """A source whose light table changes between reads, whatever the read count."""

    def __init__(self, page: ListRead, **kwargs) -> None:
        super().__init__(page, **kwargs)
        self._page = page

    @property
    def page(self) -> ListRead:
        return self._page

    @page.setter
    def page(self, page: ListRead) -> None:
        self._page = self.script[0] = page


def at(day, hour: int, minute: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=TAIPEI)


@pytest.mark.asyncio
async def test_a_schedule_picked_draft_started_on_the_visit_day_is_accepted() -> None:
    # No `11診` seeding shortcut: the stored code is what the schedule parser makes.
    source = FakeSource(PAGE)
    database, gate = await gate_with_visit(source)
    await seed_ntuh_at(database, gate, "v", DAY, clinic_code=SCHEDULE_FORM)

    assert await gate.start_visit("v", taipei(14, 0).isoformat()) == {"state": "active"}
    assert counts(database, "v")[:2] == ("usable", "none")


@pytest.mark.asyncio
async def test_a_same_day_start_before_the_first_number_is_accepted() -> None:
    source = FakeSource(page_with(""))
    database, gate = await gate_with_visit(source)
    await seed_ntuh_at(database, gate, "v", DAY, clinic_code=SCHEDULE_FORM)

    assert await gate.start_visit("v", taipei(9, 0).isoformat()) == {"state": "active"}
    assert counts(database, "v")[:2] == ("unavailable", "no_observation")


@pytest.mark.asyncio
async def test_the_visit_runs_once_numbers_appear_after_an_early_start() -> None:
    # Patient 28; the clinic has not called at Start, then shows 025.
    source = SwitchableSource(page_with(""))
    database, gate = await gate_with_visit(source)
    await seed_ntuh_at(database, gate, "v", DAY, clinic_code=SCHEDULE_FORM)
    assert await gate.start_visit("v", taipei(9, 0).isoformat()) == {"state": "active"}

    # The list when the reads begin, then the clinic's own page, still blank.
    for minute in (30, 32):
        waiting = await gate.scheduled_tick(taipei(12, minute).isoformat())
        assert waiting["events_created"] == 0
    source.page = PAGE
    called = await gate.scheduled_tick(taipei(12, 34).isoformat())
    assert called["events_created"] == 1
    assert counts(database, "v")[:2] == ("usable", "none")


# The day-3 Start and the visit-day tick below use the schedule fixture's first
# clinic: a schedule-picked `03/合成醫師甲/角膜` in the morning. The hospital shows
# that clinic on the visit day as the card `03 診 / 合成醫師甲 / 普通門診`, the shape
# captured on 2026-11-20.
MORNING_CLINIC = "03/合成醫師甲/角膜"
VISIT_DAY = SCHEDULE_FIRST_VISIT


async def started_three_days_ahead(source, *, patient: int = 14):
    database, gate = await gate_with_visit(source)
    await seed_ntuh_at(
        database,
        gate,
        "v",
        VISIT_DAY,
        clinic_code=MORNING_CLINIC,
        session="morning",
        patient=patient,
    )
    started = await gate.start_visit(
        "v", at(VISIT_DAY - timedelta(days=3), 14).isoformat()
    )
    assert started == {"state": "active"}
    return database, gate


@pytest.mark.asyncio
async def test_a_visit_started_three_days_ahead_reaches_a_near_reminder() -> None:
    source = SwitchableSource(
        listing(card("03 診", "合成醫師甲", "普通門診", "012")),
        schedule=SCHEDULE_FIXTURE,
    )
    database, gate = await started_three_days_ahead(source)

    tick = await gate.scheduled_tick(at(VISIT_DAY, 9, 0).isoformat())

    assert tick["events_created"] == 1
    assert counts(database, "v")[:2] == ("usable", "none")
    snapshot = await gate.test_snapshot()
    assert [event["event_kind"] for event in snapshot["events"]] == ["near"]


@pytest.mark.asyncio
async def test_a_doctor_absent_on_the_day_needs_attention_with_the_reason() -> None:
    source = SwitchableSource(
        listing(card("05 診", "合成醫師己", "普通門診", "012")),
        schedule=SCHEDULE_FIXTURE,
    )
    database, gate = await started_three_days_ahead(source)

    tick = await gate.scheduled_tick(at(VISIT_DAY, 8, 0).isoformat())

    assert tick["events_created"] == 0
    assert counts(database, "v")[:2] == ("unavailable", "card_not_found")


async def tick_every_minute(gate, start: datetime, end: datetime) -> int:
    """Run the one-minute cron from start to end inclusive; return events made."""
    created = 0
    now = start
    while now <= end:
        created += (await gate.scheduled_tick(now.isoformat()))["events_created"]
        now += timedelta(minutes=1)
    return created


@pytest.mark.asyncio
async def test_an_unlisted_card_sends_nothing_before_the_session_start() -> None:
    # A card that is not listed when the reads begin at 08:00 is not a failed read
    # until the published start. The family must not get a LINE message before it.
    source = SwitchableSource(
        listing(card("05 診", "合成醫師己", "普通門診", "")),
        schedule=SCHEDULE_FIXTURE,
    )
    database, gate = await started_three_days_ahead(source)

    created = await tick_every_minute(gate, at(VISIT_DAY, 0, 0), at(VISIT_DAY, 8, 59))

    assert created == 0
    assert counts(database, "v") == ("unavailable", "card_not_found", 0)
    snapshot = await gate.test_snapshot()
    assert snapshot["events"] == []


@pytest.mark.asyncio
async def test_an_unlisted_card_counts_as_unusable_once_the_session_has_started() -> (
    None
):
    # Past the published morning start (09:00), a card that is still missing is
    # an unusable read, and three of them reach the family's unavailable message.
    source = SwitchableSource(
        listing(card("05 診", "合成醫師己", "普通門診", "")),
        schedule=SCHEDULE_FIXTURE,
    )
    database, gate = await started_three_days_ahead(source)

    await tick_every_minute(gate, at(VISIT_DAY, 8, 50), at(VISIT_DAY, 9, 20))

    assert counts(database, "v")[:2] == ("unavailable", "card_not_found")
    snapshot = await gate.test_snapshot()
    assert [event["event_kind"] for event in snapshot["events"]] == ["unavailable"]


@pytest.mark.asyncio
async def test_a_substitute_card_runs_the_visit_and_marks_it() -> None:
    source = SwitchableSource(
        listing(card("03 診", "住院醫師(代)", "普通門診", "012")),
        schedule=SCHEDULE_FIXTURE,
    )
    database, gate = await started_three_days_ahead(source)

    tick = await gate.scheduled_tick(at(VISIT_DAY, 9, 0).isoformat())

    assert tick["events_created"] == 1
    assert counts(database, "v")[:2] == ("usable", "substitute_doctor")


@pytest.mark.asyncio
async def test_a_substitute_card_before_the_first_number_is_marked_not_silent() -> None:
    source = SwitchableSource(
        listing(card("03 診", "住院醫師(代)", "普通門診", "")),
        schedule=SCHEDULE_FIXTURE,
    )
    database, gate = await started_three_days_ahead(source)

    tick = await gate.scheduled_tick(at(VISIT_DAY, 8, 0).isoformat())

    assert tick["events_created"] == 0
    assert counts(database, "v")[:2] == ("unavailable", "substitute_doctor")


@pytest.mark.asyncio
async def test_two_cards_that_could_match_send_nothing_from_a_guess() -> None:
    source = SwitchableSource(
        listing(
            card("03 診", "合成醫師甲", "普通門診", "012"),
            card("03 診", "合成醫師甲", "醫師約診", "013"),
        ),
        schedule=SCHEDULE_FIXTURE,
    )
    database, gate = await started_three_days_ahead(source)

    tick = await gate.scheduled_tick(at(VISIT_DAY, 9, 0).isoformat())

    assert tick["events_created"] == 0
    assert counts(database, "v")[:2] == ("invalid", "ambiguous_match")


@pytest.mark.asyncio
async def test_a_same_day_start_with_two_matching_cards_is_refused_without_a_guess() -> (
    None
):
    source = FakeSource(plus(PAGE, card("11 診", "合成醫師丙", "普通門診", "031")))
    database, gate = await gate_with_visit(source)
    await seed_ntuh_at(database, gate, "v", DAY, clinic_code=SCHEDULE_FORM)

    result = await gate.start_visit("v", taipei(14, 0).isoformat())

    assert result == {"error": "clinic_ambiguous"}
    assert counts(database, "v")[:2] == ("invalid", "ambiguous_match")
    snapshot = await gate.test_snapshot()
    assert snapshot["events"] == []


@pytest.mark.asyncio
async def test_same_day_start_maps_roster_change_ambiguity_to_typed_refusal() -> None:
    source = FakeSource(
        PAGE, plus(PAGE, card("11 診", "合成醫師丙", "普通門診", "031"))
    )
    database, gate = await gate_with_visit(source)
    await seed_ntuh_at(database, gate, "v", DAY, clinic_code=SCHEDULE_FORM)

    result = await gate.start_visit("v", taipei(14, 0).isoformat())

    assert result == {"error": "clinic_ambiguous"}
    assert counts(database, "v")[:2] == ("invalid", "ambiguous_match")


@pytest.mark.asyncio
async def test_a_same_day_start_on_a_substitute_card_is_accepted_and_marked() -> None:
    source = FakeSource(with_rows(PAGE, of_doctor("合成醫師丙"), doctor="住院醫師(代)"))
    database, gate = await gate_with_visit(source)
    repository = await seed_ntuh_at(database, gate, "v", DAY, clinic_code=SCHEDULE_FORM)

    assert await gate.start_visit("v", taipei(14, 0).isoformat()) == {"state": "active"}

    assert counts(database, "v")[:2] == ("usable", "substitute_doctor")
    # The booked doctor stays on the visit; only the day's card differs.
    assert (await repository.get_visit("v"))["clinic_code"] == SCHEDULE_FORM
