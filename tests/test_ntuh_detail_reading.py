"""Issue #163: the visit-day read takes the card's detail page and reports progress.

Fixture/mock evidence: a scripted source serves the session list and synthetic
detail pages (`ntuh_detail_pages.py`). The local integration test runs Start and the
scheduled tick through the send gate. Nothing reaches the hospital.
"""

from __future__ import annotations

import json
from datetime import timedelta

import pytest

from next_is_you.domain import (
    ClinicSession,
    ExpectedCall,
    NumberStatus,
    QueueObservation,
    ReadSkipped,
)
from next_is_you.send_gate import _TestHospitalReader
from ntuh_detail_pages import detail_page
from test_ntuh_reader import (
    PAGE,
    FakeSource,
    LocalDurableStorage,
    page_with,
    reader,
    scope,
    taipei,
)
from test_visit_day_matching import (
    SCHEDULE_FIXTURE,
    VISIT_DAY,
    SwitchableSource,
    at,
    card_page,
    started_three_days_ahead,
)
from test_ntuh_reader import _card

# The `11診/合成醫師丙/醫師約診` card of the list fixture links to this ID.
SERVICE_ID = "8000011"
NO_CARD = PAGE.replace("合成醫師丙", "其他醫師")


def live(**fields) -> str:
    return detail_page(**fields)


@pytest.mark.asyncio
async def test_the_list_is_read_until_the_card_is_found_then_only_the_detail_page():
    source = FakeSource(
        NO_CARD,
        page_with(""),
        details=[
            live(),
            live(current=25, highest=30),
            live(current=26, highest=31),
        ],
    )
    r = reader(source)
    # The card is not listed yet: the list is read again, on the pre-call cadence.
    first = await r.observe(scope(), taipei(0, 40))
    # Before the session's published start a missing card is recorded, not an
    # unusable read.
    assert first == ReadSkipped("card_not_listed")
    assert not source.detail_requests
    # NO_CARD is retried; the card appears, so the list read finds its link.
    assert await r.observe(scope(), taipei(0, 41)) == ReadSkipped("not_due")
    assert await r.observe(scope(), taipei(0, 46)) == ReadSkipped("clinic_not_started")
    assert [q.method for q in source.requests if q.method == "POST"] == ["POST", "POST"]
    detail_url = source.detail_requests[-1].url
    assert f"ServiceIDSE={SERVICE_ID}" in detail_url
    # From here on only the detail page, every 2 minutes and never sooner.
    assert await r.observe(scope(), taipei(0, 47)) == ReadSkipped("not_due")
    assert isinstance(await r.observe(scope(), taipei(0, 48)), QueueObservation)
    assert await r.observe(scope(), taipei(0, 49)) == ReadSkipped("not_due")
    assert isinstance(await r.observe(scope(), taipei(0, 50)), QueueObservation)
    assert len([q for q in source.requests if q.method == "POST"]) == 2
    assert len(source.detail_requests) == 3


@pytest.mark.asyncio
async def test_the_detail_request_carries_the_language_and_no_session_cookie():
    source = FakeSource(PAGE, details=[live(current=25, highest=30)])
    await reader(source).observe(scope(), taipei(15, 0))
    (request,) = source.detail_requests
    headers = dict(request.headers)
    assert request.method == "GET" and request.body is None
    assert headers["Cookie"] == "Localization.CurrentUICulture=zh-TW"
    assert headers["User-Agent"].startswith("next-is-you/")


@pytest.mark.asyncio
async def test_the_observation_carries_the_progress_fields_the_page_states():
    page = live(
        current=25,
        flag="passed",
        highest=30,
        expected=((27, "順號"), (31, "過號")),
        numbers=((25, "in_consultation"), (28, "checked_in"), (29, "not_checked_in")),
    )
    source = FakeSource(PAGE, details=[page])
    observation = await reader(source).observe(scope(), taipei(15, 0))

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
async def test_before_the_clinic_calls_the_visit_is_pending_and_sends_nothing():
    source = FakeSource(page_with(""), details=[live()])
    r = reader(source)
    pending = ReadSkipped("clinic_not_started")
    assert await r.observe(scope(), taipei(9, 0)) == pending
    assert await r.observe(scope(), taipei(9, 2)) == pending
    assert await r.observe(scope(), taipei(9, 4)) == pending


@pytest.mark.asyncio
async def test_a_page_frozen_from_an_earlier_session_is_not_called_in_this_session():
    frozen = live(current=22, highest=80, numbers=((30, "checked_in"),))
    source = FakeSource(
        page_with(""),
        details=[frozen, frozen, frozen, live(current=5, highest=5)],
    )
    r = reader(source)
    pending = ReadSkipped("clinic_not_started")
    # The leftover light and highest called of the morning are on the afternoon's
    # page before it starts; unchanged, they are not a call.
    for minute in (0, 2, 4):
        assert await r.observe(scope(), taipei(13, minute)) == pending
    observation = await r.observe(scope(), taipei(13, 6))
    assert isinstance(observation, QueueObservation)
    assert observation.called_in_session is True
    assert observation.current_number == 5


@pytest.mark.asyncio
async def test_a_number_on_the_list_card_says_the_clinic_has_called():
    # A read that starts mid-session has no frozen baseline to compare with.
    source = FakeSource(PAGE, details=[live(current=25, highest=30)])
    observation = await reader(source).observe(scope(), taipei(15, 0))
    assert observation.called_in_session is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("flag", "session", "page"),
    [
        ("evening_session", ClinicSession.EVENING, live(current=26, highest=31)),
        ("midday_blank", ClinicSession.AFTERNOON, live(highest=31)),
        ("later_block_opening", ClinicSession.AFTERNOON, live(current=1, highest=1)),
    ],
)
async def test_unobserved_situations_are_flagged_recorded_and_send_nothing(
    flag, session, page
):
    state = LocalDurableStorage()
    source = FakeSource(PAGE, details=[live(current=25, highest=30), page])
    r = reader(source, state)
    first = await r.observe(scope(session=session), taipei(15, 0))
    if session == ClinicSession.EVENING:
        assert first == ReadSkipped("unobserved_situation", unobserved=flag)
    else:
        assert isinstance(first, QueueObservation)
    flagged = await r.observe(scope(session=session), taipei(15, 2))

    assert flagged == ReadSkipped("unobserved_situation", unobserved=flag)
    assert flagged.source_read is None
    recorded = json.loads(await state.get("ntuh_reader_state"))
    assert [entry["unobserved"] for entry in recorded.values()] == [[flag]]


@pytest.mark.asyncio
async def test_a_card_that_calls_by_check_in_order_stays_pending():
    page = live(check_in_order=True, check_in_position=3)
    source = FakeSource(PAGE, details=[page])
    result = await reader(source).observe(scope(), taipei(15, 0))
    assert result == ReadSkipped("clinic_not_started")


@pytest.mark.asyncio
async def test_a_detail_page_without_its_panel_fails_closed():
    source = FakeSource(PAGE, details=["<html><body>moved</body></html>"])
    result = await reader(source).observe(scope(), taipei(15, 0))
    assert (result.status, result.reason) == ("invalid", "schema_drift")


@pytest.mark.asyncio
async def test_a_refused_detail_page_stops_the_source_for_the_day():
    source = FakeSource(PAGE, details=[live(current=25, highest=30)])
    r = reader(source)
    assert isinstance(await r.observe(scope(), taipei(15, 0)), QueueObservation)
    source.details = ["<html>請完成驗證 captcha</html>"]
    refused = await r.observe(scope(), taipei(15, 2))
    assert (refused.status, refused.reason) == ("unavailable", "access_denied")
    count = len(source.requests)
    again = await r.observe(scope(), taipei(15, 40))
    assert again.reason == "access_denied" and len(source.requests) == count


@pytest.mark.asyncio
async def test_the_detail_link_is_forgotten_when_the_day_is_over():
    state = LocalDurableStorage()
    source = FakeSource(PAGE, details=[live(current=25, highest=30)])
    r = reader(source, state)
    assert isinstance(await r.observe(scope(), taipei(15, 0)), QueueObservation)
    assert SERVICE_ID in await state.get("ntuh_reader_state")

    next_day = taipei(15, 0) + timedelta(days=1)
    assert await r.observe(scope(), next_day) == ReadSkipped("clinic_not_started")

    assert SERVICE_ID not in json.dumps(state.values)
    assert not json.loads(await state.get("ntuh_reader_state"))


@pytest.mark.asyncio
async def test_a_visit_started_days_ahead_reads_the_detail_page_on_its_day():
    detail = live(room="合成科 03診", doctor="合成醫師甲", current=12, highest=15)
    source = SwitchableSource(
        card_page(_card("03 診", "合成醫師甲", "普通門診", "012")),
        schedule=SCHEDULE_FIXTURE,
        details=[detail],
    )
    database, gate = await started_three_days_ahead(source)
    assert not source.detail_requests

    tick = await gate.scheduled_tick(at(VISIT_DAY, 9, 0).isoformat())

    assert tick["events_created"] == 1
    (request,) = source.detail_requests
    service_id = (
        _card("03 診", "合成醫師甲", "普通門診").split("ServiceIDSE=")[1].split("&")[0]
    )
    assert f"ServiceIDSE={service_id}" in request.url
    snapshot = await gate.test_snapshot()
    assert [event["event_kind"] for event in snapshot["events"]] == ["near"]

    # The link is kept only in that day's transient state.
    stored = await gate.ctx.storage.get("ntuh_reader_state")
    assert service_id in stored
    await gate.scheduled_tick(at(VISIT_DAY + timedelta(days=1), 0, 5).isoformat())
    assert service_id not in (await gate.ctx.storage.get("ntuh_reader_state") or "")


@pytest.mark.asyncio
async def test_the_local_synthetic_observation_hook_accepts_the_progress_fields():
    storage = LocalDurableStorage()
    hook = _TestHospitalReader(storage)
    gate_progress = {
        "highest_called_number": 30,
        "current_flag": "senior",
        "check_in_order": False,
        "called_in_session": True,
        "expected": [[27, "sequential", None]],
        "numbers": [[28, "checked_in", None], [29, "checked_in", 2]],
    }
    await storage.put("test_current_number", 25)
    await storage.put("test_trustworthy", True)
    await storage.put("test_progress", json.dumps(gate_progress))

    observation = await hook.observe(scope(), taipei(15, 0))

    assert observation.highest_called_number == 30
    assert observation.current_flag == "senior"
    assert observation.called_in_session is True
    assert observation.expected == (ExpectedCall(27, "sequential"),)
    assert observation.numbers == (
        NumberStatus(28, "checked_in"),
        NumberStatus(29, "checked_in", 2),
    )
