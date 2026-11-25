"""Replay real NTUH clinic schedule pages through the reader (#205, ADR 0006).

Fixture/mock evidence. The five `schedule_*` pages under
`fixtures/hospitals/ntuh_captures/` are the public `RegDeptSchedule` pages
(`showBlock=A`, `realSubDeptCode=showAll`) of NTUH Main, captured on 2026-11-25
between 10:15 and 10:16 Taipei time, each committed as the hospital served it
below one leading comment that names the capture. The only change is the value of
the page's three anti-forgery token fields, which belong to our request.

Clinic counts, per-day counts and the rows asserted are read off the page, never
copied from the parser's output. On this page one clinic is one card, a
`<button class="doctor-tag ...">`; the page's legend also uses the `doctor-tag`
class on three `<div>`s that are not clinics, so the class string is not the
count. Every count below was taken by hand with `grep -o '<button
class="doctor-tag' <page> | wc -l` and cross-checked by counting the cards under
each day's date column. Nothing here reaches the hospital.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from functools import cache
from pathlib import Path

import pytest

import next_is_you.ntuh_reader as ntuh_reader
from next_is_you.domain import (
    ClinicMatch,
    ClinicSession,
    MatchKind,
    MatchQuery,
    RosterQuery,
)
from next_is_you.ntuh_reader import (
    MAX_SCHEDULE_BODY_CHARS,
    SCHEDULE_PATH,
    FetchedPage,
    NtuhProgressReader,
    PageRequest,
    ScheduleRow,
    parse_schedule,
    schedule_url,
)
from test_scheduler_outbox import LocalDurableStorage

CAPTURES = Path(__file__).parent / "fixtures" / "hospitals" / "ntuh_captures"
TAIPEI = timezone(timedelta(hours=8))
# The capture day: it resolves the page's `MM/DD` date column.
TODAY = date(2026, 11, 25)
NOW = datetime(2026, 11, 25, 10, 16, tzinfo=TAIPEI)

MORNING = ClinicSession.MORNING
AFTERNOON = ClinicSession.AFTERNOON

# Clinics on each page within the reader's size cap, counted by hand (see the
# module docstring). `grep -o '<div class="doc-name">' <page> | wc -l`, one
# doctor name per card, gives the same numbers.
CLINICS_ON_PAGE = {"orth": 126, "oph": 136, "neur": 115}

# The second count: the cards under each of the page's 11 date columns (the
# page lists weekdays only, 11/25 to 12/9), counted between one
# `<div class="date" style="text-align:center">` and the next. Each sums to the
# page count above.
CLINICS_PER_DAY = {
    "orth": (11, 13, 13, 12, 10, 11, 12, 12, 12, 9, 11),
    "oph": (12, 13, 12, 12, 14, 11, 12, 12, 12, 14, 12),
    "neur": (10, 9, 12, 10, 11, 11, 9, 12, 10, 11, 10),
}
PAGE_DAYS = tuple(
    date(2026, month, day)
    for month, day in (
        (11, 25),
        (11, 26),
        (11, 27),
        (11, 30),
        (12, 1),
        (12, 2),
        (12, 3),
        (12, 4),
        (12, 7),
        (12, 8),
        (12, 9),
    )
)


def row(
    month: int,
    day: int,
    session: ClinicSession,
    room: str,
    doctor: str,
    sub_spec: str,
    status: str = "",
) -> ScheduleRow:
    """A card as the page shows it: `doctor | NN 診`, `department | 診別`."""
    department, clinic_type = (part.strip() for part in sub_spec.split("|"))
    return ScheduleRow(
        date(2026, month, day), session, room, doctor, clinic_type, status, department
    )


# Cards read off each page: date column, session header, `doctor | room 診`, the
# status tag in the card's corner (none when blank) and the `.sub-spec` line.
ROWS_ON_PAGE = {
    "orth": (
        # The page's first card.
        row(11, 25, MORNING, "01", "侯君翰", "一般骨科 | 普通門診", "額滿"),
        row(11, 25, MORNING, "02", "張允亮", "手外科 | 手外科"),
        row(11, 25, AFTERNOON, "01", "蔡岳呈", "運動醫學科 | 運動傷害", "停診"),
        row(11, 26, AFTERNOON, "07", "江鴻生", "運動醫學科 | 膝關節障礙", "本科複診"),
        # The page's last card.
        row(12, 9, AFTERNOON, "07", "王廷明", "一般骨科 | 普通門診", "僅存本院初診"),
    ),
    "oph": (
        row(11, 25, MORNING, "04", "楊中美", "視網膜科 | 網膜", "額滿"),
        row(11, 25, AFTERNOON, "03", "王清泓", "青光眼科 | 青光眼", "停診"),
        row(
            11,
            26,
            MORNING,
            "06",
            "侯鈞賀",
            "角膜科 | 屈光矯正手術自費評估門診(近視、老花)",
            "僅存本院初診",
        ),
        # The department name is cut short on the page itself.
        row(
            12,
            4,
            AFTERNOON,
            "01",
            "劉耀臨",
            "成人斜視與屈調.. | 成人斜視與屈調",
            "停診",
        ),
        row(12, 9, AFTERNOON, "09", "總醫師", "一般眼科 | 普通門診", "僅存本院初診"),
    ),
    "neur": (
        row(11, 25, MORNING, "01", "張楊全", "一般神經疾病 | 初診", "額滿"),
        row(11, 25, MORNING, "08", "鄭建興", "腦血管疾病 | 普通門診", "停診"),
        row(12, 4, MORNING, "06", "蘇真真", "神經肌病疾病 | 普通門診", "本科複診"),
        row(12, 9, AFTERNOON, "08", "沈英琪", "一般神經疾病 | 普通門診"),
    ),
}


@cache
def capture(name: str) -> str:
    """A committed capture as served: CRLF kept, the header comment dropped."""
    text = (CAPTURES / name).read_bytes().decode("utf-8")
    header, page = text.split("\r\n", 1)
    assert header.startswith("<!-- Captured 2026-11-25 "), name
    return page


def schedule_page(dept: str) -> str:
    return capture(f"schedule_{dept}_2026-11-25_1015.html")


@cache
def read(dept: str) -> tuple[str, tuple[ScheduleRow, ...]]:
    status, rows = parse_schedule(schedule_page(dept), TODAY)
    return status, tuple(rows)


@pytest.mark.parametrize("dept", sorted(CLINICS_ON_PAGE))
def test_a_page_within_the_cap_reads_every_clinic(dept: str) -> None:
    assert len(schedule_page(dept)) <= MAX_SCHEDULE_BODY_CHARS
    status, rows = read(dept)
    assert status == "ok"
    assert len(rows) == CLINICS_ON_PAGE[dept]
    per_day = Counter(r.visit_date for r in rows)
    assert tuple(per_day[day] for day in PAGE_DAYS) == CLINICS_PER_DAY[dept]
    assert sum(CLINICS_PER_DAY[dept]) == CLINICS_ON_PAGE[dept]


@pytest.mark.parametrize("dept", sorted(ROWS_ON_PAGE))
def test_cards_read_as_the_page_shows_them(dept: str) -> None:
    _, rows = read(dept)
    for expected in ROWS_ON_PAGE[dept]:
        assert expected in rows
    assert rows[0] == ROWS_ON_PAGE[dept][0]


def test_rows_keep_page_order_across_days_and_sessions() -> None:
    _, rows = read("orth")
    assert rows[-1] == ROWS_ON_PAGE["orth"][-1]
    # Dates never go back, and within a day the morning cards come first.
    keys = [(r.visit_date, r.session is AFTERNOON) for r in rows]
    assert keys == sorted(keys)
    # On 11/25 the page lists 6 morning and 5 afternoon cards.
    first_day = Counter(r.session for r in rows if r.visit_date == TODAY)
    assert first_day == {MORNING: 6, AFTERNOON: 5}


def test_status_tags_are_kept_verbatim() -> None:
    # Tags found on cards of the three pages: 額滿, 停診, 僅存本院初診 and
    # 本科複診. 颱風停診 is on no card on any of the five pages; the page shows
    # it only in its legend, which is not a clinic.
    found = {r.status for dept in CLINICS_ON_PAGE for r in read(dept)[1]}
    assert found == {"", "額滿", "停診", "僅存本院初診", "本科複診"}
    assert "颱風停診" in schedule_page("orth")
    # The legend's tags are no clinic; 停診 cards on the 骨科 page: 3.
    _, rows = read("orth")
    assert sum(r.status == "停診" for r in rows) == 3


def test_a_schedule_page_without_cards_is_schema_drift() -> None:
    page = re.sub(
        r'<button class="doctor-tag.*?</button>', "", schedule_page("orth"), flags=re.S
    )
    assert '<button class="doctor-tag' not in page
    assert parse_schedule(page, TODAY) == ("schema_drift", [])


@pytest.mark.parametrize(
    "name",
    [
        "selector_2026-11-25_1015.html",
        "list_oph_am_2026-11-25_1015.html",
    ],
)
def test_a_page_that_is_not_a_schedule_is_schema_drift(name: str) -> None:
    text = (CAPTURES / name).read_bytes().decode("utf-8")
    assert parse_schedule(text, TODAY) == ("schema_drift", [])


@pytest.mark.parametrize(
    ("marker", "reason"),
    [("Please complete the CAPTCHA", "challenge"), ("Access Denied", "denied")],
)
def test_a_challenge_or_denial_inside_a_real_page_reads_nothing(
    marker: str, reason: str
) -> None:
    header = '<div class="col-12 sm-table-header">11/25(三), 骨科部</div>'
    page = schedule_page("orth")
    assert header in page
    page = page.replace(header, f"{header}<p>{marker}</p>", 1)
    assert parse_schedule(page, TODAY) == (reason, [])


class CaptureSource:
    """Serves a captured schedule page for the reader's schedule GET only."""

    def __init__(self, page: str) -> None:
        self.page = page
        self.requests: list[PageRequest] = []

    async def __call__(self, request: PageRequest) -> FetchedPage:
        self.requests.append(request)
        assert request.method == "GET" and request.url.startswith(SCHEDULE_PATH)
        return FetchedPage(200, self.page)


def reader(page: str) -> tuple[NtuhProgressReader, CaptureSource]:
    source = CaptureSource(page)
    return NtuhProgressReader(LocalDurableStorage(), source), source


@pytest.mark.asyncio
async def test_the_picker_offers_every_running_clinic_of_a_real_page() -> None:
    picker, source = reader(schedule_page("oph"))
    roster = await picker.list_clinics(
        RosterQuery("ntuh-main", "OPH", date(2026, 11, 26)), NOW
    )
    assert [r.url for r in source.requests] == [schedule_url("OPH")]
    assert roster.available
    # 11/26 on the 眼科 page: 13 cards, one of them 停診 (王清泓, 03 診, 下午).
    assert len(roster.clinics) == 12
    assert ("03", "王清泓") not in {(c.room, c.doctor) for c in roster.clinics}
    assert any(
        (c.room, c.doctor, c.session) == ("06", "侯鈞賀", MORNING)
        for c in roster.clinics
    )


# Over the reader's size cap. Until #188 lifts the cap these pages must be
# refused as unreadable, never read in part; #188 turns these tests into a
# complete read. The reader serves 眼科 only today, so the department gate is
# opened for the test to drive the real page through the production path.
OVER_CAP = {
    # A card on each page, so a read would have found the clinic.
    "med": ("MED", row(11, 26, MORNING, "01", "吳卓鍇", "心臟血管科 | 普通門診")),
    "surg": ("SURG", row(11, 26, MORNING, "03", "林孟暐", "胸腔外科 | 胸腔外科")),
}


@pytest.mark.parametrize("dept", sorted(OVER_CAP))
def test_a_page_over_the_cap_is_on_the_page_but_too_large(dept: str) -> None:
    assert len(schedule_page(dept)) > MAX_SCHEDULE_BODY_CHARS
    assert OVER_CAP[dept][1].doctor in schedule_page(dept)


@pytest.mark.asyncio
@pytest.mark.parametrize("dept", sorted(OVER_CAP))
async def test_a_page_over_the_cap_gives_no_roster(
    dept: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    code, _ = OVER_CAP[dept]
    monkeypatch.setattr(ntuh_reader, "SUPPORTED_DEPARTMENT", code)
    picker, source = reader(schedule_page(dept))
    roster = await picker.list_clinics(
        RosterQuery("ntuh-main", code, date(2026, 11, 26)), NOW
    )
    assert [r.url for r in source.requests] == [schedule_url(code)]
    assert not roster.available
    assert roster.clinics == ()
    assert roster.reason == "schema_drift"


@pytest.mark.asyncio
@pytest.mark.parametrize("dept", sorted(OVER_CAP))
async def test_a_page_over_the_cap_matches_nothing(
    dept: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    code, card = OVER_CAP[dept]
    monkeypatch.setattr(ntuh_reader, "SUPPORTED_DEPARTMENT", code)
    picker, source = reader(schedule_page(dept))
    match = await picker.match_clinic(
        MatchQuery(
            "ntuh-main",
            code,
            card.visit_date,
            card.session,
            f"{card.room}/{card.doctor}/{card.clinic_type}",
        ),
        NOW,
    )
    assert [r.url for r in source.requests] == [schedule_url(code)]
    assert match == ClinicMatch(MatchKind.UNAVAILABLE, reason="schema_drift")
