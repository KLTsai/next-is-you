"""The reader's clinic matching operation (fixture/mock evidence).

Shared code asks the reader whether a stored draft matches the hospital's clinic
schedule and branches only on the answer.
"""

from __future__ import annotations

import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from next_is_you.domain import (
    ClinicMatch,
    ClinicSession,
    MatchKind,
    MatchQuery,
)
from test_ntuh_reader import (
    PAGE,
    SCHEDULE_FIRST_VISIT,
    SCHEDULE_FIXTURE,
    FakeSource,
    reader,
)

TAIPEI = timezone(timedelta(hours=8))
TODAY_EVE = datetime(2026, 11, 9, 14, 0, tzinfo=TAIPEI)


def query(code: str, session=ClinicSession.MORNING, day=SCHEDULE_FIRST_VISIT):
    return MatchQuery("ntuh-main", "OPH", day, session, code)


@pytest.mark.asyncio
async def test_matches_on_session_room_doctor_and_returns_canonical_code() -> None:
    match = await reader(FakeSource(schedule=SCHEDULE_FIXTURE)).match_clinic(
        query("03/合成醫師甲/別的診別"), TODAY_EVE
    )
    assert match == ClinicMatch(MatchKind.MATCHED, "03/合成醫師甲/角膜")


@pytest.mark.asyncio
async def test_normalises_room_and_doctor_before_comparing() -> None:
    match = await reader(FakeSource(schedule=SCHEDULE_FIXTURE)).match_clinic(
        query(" 03 /合成 醫師甲/x"), TODAY_EVE
    )
    assert match.kind is MatchKind.MATCHED


@pytest.mark.asyncio
async def test_other_session_is_not_scheduled() -> None:
    match = await reader(FakeSource(schedule=SCHEDULE_FIXTURE)).match_clinic(
        query("03/合成醫師甲/角膜", ClinicSession.AFTERNOON), TODAY_EVE
    )
    assert match.kind is MatchKind.NOT_SCHEDULED


@pytest.mark.asyncio
@pytest.mark.parametrize("code", ["07/合成醫師丙/教學門診"])
async def test_a_cancelled_row_is_cancelled_by_the_hospital(code: str) -> None:
    match = await reader(FakeSource(schedule=SCHEDULE_FIXTURE)).match_clinic(
        query(code), TODAY_EVE
    )
    assert match.kind is MatchKind.CANCELLED


@pytest.mark.asyncio
async def test_typhoon_cancellation_is_cancelled_too() -> None:
    match = await reader(FakeSource(schedule=SCHEDULE_FIXTURE)).match_clinic(
        query("06/合成醫師己/x", day=SCHEDULE_FIRST_VISIT + timedelta(days=1)),
        TODAY_EVE,
    )
    assert match.kind is MatchKind.CANCELLED


@pytest.mark.asyncio
async def test_a_date_past_the_schedule_is_not_yet_published_without_a_request() -> (
    None
):
    source = FakeSource(schedule=SCHEDULE_FIXTURE)
    match = await reader(source).match_clinic(
        query("03/合成醫師甲/角膜", day=TODAY_EVE.date() + timedelta(days=20)),
        TODAY_EVE,
    )
    assert match.kind is MatchKind.NOT_YET_PUBLISHED
    assert source.requests == []


@pytest.mark.asyncio
async def test_a_source_failure_is_unavailable_with_its_reason() -> None:
    match = await reader(FakeSource(PAGE)).match_clinic(
        query("03/合成醫師甲/角膜"), TODAY_EVE
    )
    assert match == ClinicMatch(MatchKind.UNAVAILABLE, reason="schema_drift")


@pytest.mark.asyncio
async def test_an_unparseable_clinic_code_is_unavailable_invalid_data() -> None:
    match = await reader(FakeSource(schedule=SCHEDULE_FIXTURE)).match_clinic(
        query("not-a-clinic-code"), TODAY_EVE
    )
    assert match == ClinicMatch(MatchKind.UNAVAILABLE, reason="invalid_data")


@pytest.mark.asyncio
async def test_matching_many_drafts_of_one_day_costs_the_hospital_one_request() -> None:
    source = FakeSource(schedule=SCHEDULE_FIXTURE)
    ntuh = reader(source)
    for code in ("03/合成醫師甲/角膜", "99/陌生醫師/角膜", "07/合成醫師丙/x"):
        await ntuh.match_clinic(query(code), TODAY_EVE)
    assert len(source.requests) == 1


def test_shared_modules_do_not_know_ntuh_clinic_rules() -> None:
    src = Path(__file__).parent.parent / "src" / "next_is_you"
    for name in ("send_gate.py", "scheduler.py"):
        tree = ast.parse((src / name).read_text(encoding="utf-8"))
        imported = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            and node.module == "next_is_you.ntuh_reader"
            for alias in node.names
        }
        assert imported <= {"WorkersFetcher"}, (name, imported)
        text = (src / name).read_text(encoding="utf-8")
        assert "停診" not in text, name


class _FailsOnce:
    """Fails the first request, then behaves like the wrapped source."""

    def __init__(self, inner: FakeSource) -> None:
        self.inner = inner
        self.failed = False

    async def __call__(self, request):
        if not self.failed:
            self.failed = True
            raise RuntimeError("synthetic transport failure")
        return await self.inner(request)


@pytest.mark.asyncio
async def test_a_failed_schedule_read_is_not_remembered() -> None:
    ntuh = reader(_FailsOnce(FakeSource(schedule=SCHEDULE_FIXTURE)))
    first = await ntuh.match_clinic(query("03/合成醫師甲/角膜"), TODAY_EVE)
    assert first.kind is MatchKind.UNAVAILABLE
    # The next match in the same sweep must retry, not replay the failure.
    second = await ntuh.match_clinic(query("03/合成醫師甲/角膜"), TODAY_EVE)
    assert second.kind is MatchKind.MATCHED


@pytest.mark.asyncio
async def test_schedule_memo_keeps_only_the_current_day() -> None:
    ntuh = reader(FakeSource(schedule=SCHEDULE_FIXTURE))
    await ntuh.match_clinic(query("03/合成醫師甲/角膜"), TODAY_EVE)
    await ntuh.match_clinic(
        query("03/合成醫師甲/角膜", day=SCHEDULE_FIRST_VISIT + timedelta(days=1)),
        TODAY_EVE + timedelta(days=1),
    )
    assert {today for (_dept, today) in ntuh._schedule_memo} == {
        (TODAY_EVE + timedelta(days=1)).date()
    }


@pytest.mark.asyncio
async def test_an_unparseable_clinic_code_is_invalid_without_a_request() -> None:
    # Ticket #98 review: a code that cannot name a clinic is a permanent
    # condition, so it is reported as invalid_data and never costs a hospital
    # request (the old Start read first and only then said observation_invalid).
    source = FakeSource(schedule=SCHEDULE_FIXTURE)
    match = await reader(source).match_clinic(query("not-a-clinic-code"), TODAY_EVE)
    assert match == ClinicMatch(MatchKind.UNAVAILABLE, reason="invalid_data")
    assert source.requests == []
