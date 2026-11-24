"""Replay real NTUH pages through the reader (#205, ADR 0006).

Fixture/mock evidence. Every page under
`fixtures/hospitals/ntuh_captures/` is a public NTUH page committed as the
hospital served it, with one leading comment naming its capture. Expected values
are read off the page as a person sees it, and checked against
`research/private/source-evidence/ntuh-progress-validation-2026-11-20.md` where
that analysis covers the capture. They are never copied from the parser's output.
Nothing here reaches the hospital.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import re

import pytest

from next_is_you.domain import ClinicScope, ClinicSession, QueueObservation
from next_is_you.ntuh_reader import ListRow, parse_light_table
from next_is_you.ntuh_detail import (
    ExpectedCall,
    NumberStatus,
    ProgressObservation,
    parse_detail_page,
)

from test_ntuh_reader import TwoPageSource, reader

CAPTURES = Path(__file__).parent / "fixtures" / "hospitals" / "ntuh_captures"

# The status words of the page's 所有燈號狀態 list, as a person reads them.
_STATES = {
    "未報到": "not_checked_in",
    "初診": "first_visit",
    "已報到": "checked_in",
    "看診中": "in_consultation",
}


_NAMED_CAPTURE = re.compile(
    r"<!-- Captured 2026-\d\d-\d\d \d\d:\d\d:\d\d Taipei time .*"
    r" Source file: research/private/source-evidence/raw/\S+\.html\. .* -->"
)
# What a request or a session carries. A committed capture holds only the page.
_REQUEST_TEXT = re.compile(
    r"set-cookie|cookie|sessionid|session_id|requestverificationtoken|"
    r"authorization|bearer|csrf|xsrf",
    re.IGNORECASE,
)


def test_every_capture_names_its_capture_and_holds_only_the_page() -> None:
    names = sorted(path.name for path in CAPTURES.glob("*.html"))
    assert len(names) == 11
    for name in names:
        text = capture(name)
        assert _NAMED_CAPTURE.fullmatch(text.split("\n", 1)[0].rstrip("\r")), name
        assert _REQUEST_TEXT.search(text) is None, name


def capture(name: str) -> str:
    return (CAPTURES / name).read_text(encoding="utf-8")


def numbers_as_shown(listing: str) -> tuple[NumberStatus, ...]:
    """The 所有燈號狀態 list written the way the page shows it.

    It maps the page's visible words, while the parser reads the tag classes, so
    the two disagree when the parser misreads a tag.

    "2 未報到 14 報到10" is number 2 not checked in and number 14 checked in as the
    tenth to check in.
    """
    words = listing.split()
    statuses = []
    for number, status in zip(words[::2], words[1::2], strict=True):
        if status.startswith("報到"):
            statuses.append(NumberStatus(int(number), "checked_in", int(status[2:])))
        else:
            statuses.append(NumberStatus(int(number), _STATES[status]))
    return tuple(statuses)


def detail(name: str) -> ProgressObservation:
    status, observation = parse_detail_page(capture(name))
    assert status == "ok"
    assert observation is not None
    return observation


def test_orthopedics_number_order_page_2026_11_23() -> None:
    # 骨科部 02診 at 10:30:17: light 011 順號, 已叫最大號 014, 預計叫號 014 (順號).
    page = detail("detail_orth02_2026-11-23_1030.html")

    assert page.room == "骨科部 02診"
    assert page.doctor == "王貞棣"
    assert page.current_light == 11
    assert page.current_flag == "sequential"
    assert page.highest_called == 14
    assert page.check_in_order is False
    assert page.check_in_position is None
    assert [(call.number, call.kind) for call in page.expected] == [(14, "sequential")]
    assert page.numbers == numbers_as_shown(
        "2 未報到 8 未報到 11 看診中 13 已報到 14 未報到 15 已報到 16 已報到"
        " 17 未報到 18 已報到 19 已報到 20 未報到 21 已報到 22 已報到 23 已報到"
        " 24 已報到 25 未報到 26 已報到 28 已報到 29 已報到 30 已報到 32 已報到"
        " 33 已報到 34 已報到 35 已報到 37 未報到 39 未報到 41 已報到 42 未報到"
        " 43 已報到 44 未報到 45 已報到 46 已報到 47 未報到 48 已報到 49 未報到"
        " 50 未報到 51 已報到 52 未報到 53 未報到 54 未報到 55 未報到 56 初診"
        " 57 未報到 59 已報到 68 未報到 69 已報到 70 未報到 71 未報到 73 未報到"
        " 74 已報到 75 未報到 76 未報到 77 未報到 78 未報到 79 未報到 81 未報到"
        " 84 未報到"
    )


def test_internal_medicine_passed_number_page_2026_11_23() -> None:
    # 內科部 03診 at 10:30:13: light 025 過號 below 已叫最大號 033.
    page = detail("detail_med03_2026-11-23_1030.html")

    assert (page.room, page.doctor) == ("內科部 03診", "章明珠")
    assert page.current_light == 25
    assert page.current_flag == "passed"
    assert page.highest_called == 33
    assert page.check_in_order is False
    assert page.expected == (
        ExpectedCall(25, "passed"),
        ExpectedCall(31, "sequential"),
        ExpectedCall(33, "sequential"),
    )
    assert page.numbers == numbers_as_shown(
        "24 已報到 25 看診中 26 未報到 27 已報到 28 已報到 29 已報到 30 已報到"
        " 31 已報到 33 未報到 39 已報到 40 已報到 41 未報到 42 已報到 43 已報到"
        " 44 已報到 45 已報到 46 已報到 47 已報到 48 已報到 51 未報到"
    )


def test_internal_medicine_check_in_order_page_2026_11_20() -> None:
    # 內科部 28診 at 09:57:11, a 依報到順序看診 clinic: light 027 報到順序06 and a
    # blank 已叫最大號. The validation notes list 8140533 as check-in order.
    page = detail("detail_med28_check_in_order_2026-11-20_0957.html")

    assert (page.room, page.doctor) == ("內科部 28診", "黃懷萱")
    assert page.check_in_order is True
    assert page.current_light == 27
    assert page.current_flag is None
    assert page.check_in_position == 6
    assert page.highest_called is None
    assert page.expected == (
        ExpectedCall(27, "check_in", 6),
        ExpectedCall(16, "check_in", 7),
        ExpectedCall(18, "check_in", 8),
    )
    assert page.numbers == numbers_as_shown(
        "2 未報到 4 未報到 5 未報到 14 報到10 16 報到7 17 未報到 18 報到8"
        " 19 未報到 20 未報到 21 未報到 22 報到4 23 報到11 24 未報到 27 看診中"
        " 28 報到9"
    )


def test_check_in_order_page_calling_a_senior_shows_no_position_2026_11_20() -> None:
    # 內科部 10診 at 14:05:37 shows 010 敬老號 where 報到順序NN usually is. The
    # validation notes record this clinic (8614993) doing so at 14:05-14:15. The
    # page states no position, so the parser gives none.
    page = detail("detail_med10_check_in_order_senior_2026-11-20_1405.html")

    assert (page.room, page.doctor) == ("內科部 10診", "尤達權")
    assert page.check_in_order is True
    assert page.current_light == 10
    assert page.current_flag == "senior"
    assert page.check_in_position is None
    assert page.highest_called is None
    assert page.expected == (
        ExpectedCall(10, "senior"),
        ExpectedCall(9, "check_in", 4),
        ExpectedCall(4, "check_in", 6),
    )
    assert page.numbers == numbers_as_shown("4 報到6 6 未報到 9 報到4 10 看診中")


def test_senior_call_far_ahead_of_highest_called_2026_11_20() -> None:
    # 內科部 08診 at 14:15:43: 034 敬老號 while 已叫最大號 is 008, as the validation
    # notes record for 8140141 #34 at 14:15.
    page = detail("detail_med08_senior_2026-11-20_1415.html")

    assert (page.room, page.doctor) == ("內科部 08診", "蘇東弘")
    assert page.current_light == 34
    assert page.current_flag == "senior"
    assert page.highest_called == 8
    assert page.expected == (
        ExpectedCall(34, "senior"),
        ExpectedCall(6, "sequential"),
        ExpectedCall(8, "sequential"),
    )
    assert page.numbers == numbers_as_shown(
        "4 已報到 6 已報到 8 已報到 9 已報到 10 未報到 11 未報到 12 已報到"
        " 13 已報到 14 已報到 15 已報到 16 已報到 17 已報到 18 未報到 19 未報到"
        " 20 未報到 21 未報到 22 已報到 23 已報到 24 未報到 25 已報到 26 未報到"
        " 27 未報到 28 未報到 29 未報到 30 未報到 31 已報到 32 未報到 33 未報到"
        " 34 看診中 35 未報到 36 未報到 37 未報到 38 未報到 39 未報到 40 已報到"
        " 41 已報到 42 未報到 43 未報到 45 未報到 46 已報到 47 未報到 48 未報到"
        " 49 未報到 50 未報到"
    )


def test_exam_call_above_highest_called_with_no_expected_call_2026_11_20() -> None:
    # 眼科部 12診 at 16:35:41: 049 檢查號 with 已叫最大號 047, as the validation notes
    # record for 8140753. Both 預計叫號 slots read 000 (無): no expected call.
    page = detail("detail_oph12_exam_2026-11-20_1635.html")

    assert (page.room, page.doctor) == ("眼科部 12診", "李承雍")
    assert page.current_light == 49
    assert page.current_flag == "exam"
    assert page.highest_called == 47
    assert page.expected == ()
    assert page.numbers == numbers_as_shown(
        "1 未報到 5 未報到 34 已報到 42 已報到 44 未報到 49 看診中"
    )


def test_blank_clinic_page_has_no_light_and_no_numbers_2026_11_20() -> None:
    # 眼科部 53診 at 11:30:52: blank light and 已叫最大號 (U+3000) and an empty
    # list, as the validation notes record for 8767139 at every read that day.
    page = detail("detail_oph53_empty_2026-11-20_1130.html")

    assert (page.room, page.doctor) == ("眼科部 53診", "薛琴")
    assert page.current_light is None
    assert page.current_flag is None
    assert page.highest_called is None
    assert page.expected == ()
    assert page.numbers == ()


def cards(name: str) -> list[ListRow]:
    status, rows = parse_light_table(capture(name))
    assert status == "ok"
    return rows


def test_orthopedics_morning_list_2026_11_23() -> None:
    # Every card of the 10:30:08 list, read off the page: room, doctor, clinic
    # type, light, the 依報到順序看診 note and the card's detail link.
    assert cards("list_orth_am_2026-11-23_1030.html") == [
        ListRow("01 診", "黃全敬", "普通門診", "029", "", "8150268"),
        ListRow("02 診", "王貞棣", "普通門診", "011", "", "8143725"),
        ListRow("03 診", "洪志凱", "普通門診", "016", "", "8142927"),
        ListRow("05 診", "王廷明", "普通門診", "040", "依報到順序看診", "8143743"),
        ListRow("06 診", "王崇禮", "教學門診", "001", "依報到順序看診", "8143348"),
        ListRow("07 診", "侯君翰", "普通門診", "025", "依報到順序看診", "8143519"),
        ListRow("71 診", "主治醫師", "一日手術", "", "", "8143819"),
        ListRow("72 診", "主治醫師", "一日手術", "", "", "8143616"),
    ]


def test_internal_medicine_morning_list_2026_11_23() -> None:
    rows = {row.room: row for row in cards("list_med_am_2026-11-23_1030.html")}

    # 49 cards, 01 診 to 99 診.
    assert len(rows) == 49
    assert rows["03 診"] == ListRow("03 診", "章明珠", "醫師約診", "025", "", "8143279")
    assert rows["31 診"] == ListRow(
        "31 診", "劉旺達", "普通門診", "013", "依報到順序看診", "8143278"
    )
    # A check-in-order card with a blank light.
    assert rows["40 診"] == ListRow(
        "40 診", "總醫師", "醫師約診", "", "依報到順序看診", "8154935"
    )


def test_ophthalmology_morning_list_2026_11_20() -> None:
    rows = {row.room: row for row in cards("list_oph_am_2026-11-20_1130.html")}

    assert len(rows) == 21
    assert rows["02 診"] == ListRow("02 診", "薛琴", "普通門診", "037", "", "8140452")
    # A substitute doctor: the card shows 住院醫師 followed by (代).
    assert rows["06 診"] == ListRow(
        "06 診", "住院醫師(代)", "普通門診", "012", "", "8140532"
    )
    # Listed clinics with a blank light.
    assert rows["12 診"] == ListRow("12 診", "曾佳慧", "普通門診", "", "", "8140650")
    assert rows["53 診"] == ListRow("53 診", "薛琴", "醫師約診", "", "", "8767139")


def test_a_card_links_to_the_detail_page_showing_the_same_light() -> None:
    # Captured a few seconds apart: each card's link leads to the detail page
    # captured with it, and both pages show the same light.
    pairs = [
        (
            "list_orth_am_2026-11-23_1030.html",
            "02 診",
            "detail_orth02_2026-11-23_1030.html",
        ),
        (
            "list_med_am_2026-11-23_1030.html",
            "03 診",
            "detail_med03_2026-11-23_1030.html",
        ),
        (
            "list_oph_am_2026-11-20_1130.html",
            "02 診",
            "detail_oph02_exam_2026-11-20_1130.html",
        ),
        (
            "list_oph_am_2026-11-20_1130.html",
            "53 診",
            "detail_oph53_empty_2026-11-20_1130.html",
        ),
    ]
    for list_page, room, detail_page in pairs:
        card = next(row for row in cards(list_page) if row.room == room)
        assert f"ServiceIDSE={card.service_id}." in capture(detail_page).splitlines()[0]
        page = detail(detail_page)
        assert page.doctor == card.doctor
        assert page.current_light == (int(card.current) if card.current else None)


@pytest.mark.asyncio
async def test_reader_finds_the_card_on_a_real_list_and_reads_its_real_detail_page() -> (
    None
):
    # The visit-day read of 眼科 02診 薛琴, morning of 2026-11-20: the first read
    # finds the card on the 11:30:48 list, the next one reads the card's detail
    # page captured at 11:30:51.
    source = TwoPageSource(
        capture("list_oph_am_2026-11-20_1130.html"),
        capture("detail_oph02_exam_2026-11-20_1130.html"),
    )
    r = reader(source)
    clinic = ClinicScope(
        "ntuh-main",
        date(2026, 11, 20),
        "OPH",
        "02診/薛琴/普通門診",
        ClinicSession.MORNING,
    )
    taipei = timezone(timedelta(hours=8))

    found = await r.observe_for_start(
        clinic, datetime(2026, 11, 20, 11, 30, tzinfo=taipei)
    )
    assert isinstance(found, QueueObservation)
    assert found.current_number == 37
    assert source.detail_urls == []

    read = await r.observe(clinic, datetime(2026, 11, 20, 11, 32, tzinfo=taipei))

    assert [url.split("?")[1] for url in source.detail_urls] == [
        "ServiceIDSE=8140452&vHospitalCode=T0"
    ]
    assert isinstance(read, QueueObservation)
    # The page: light 037 檢查號, 已叫最大號 043, 預計叫號 032 (過號) 044 (順號).
    assert read.current_number == 37
    assert read.current_flag == "exam"
    assert read.highest_called_number == 43
    assert read.substitute_doctor is False
    assert read.expected == (ExpectedCall(32, "passed"), ExpectedCall(44, "sequential"))
    assert read.numbers == numbers_as_shown(
        "14 未報到 16 已報到 20 已報到 23 未報到 25 已報到 32 已報到 33 已報到"
        " 34 已報到 35 已報到 36 已報到 37 看診中 43 已報到 44 未報到 45 已報到"
        " 46 已報到 47 已報到 49 未報到"
    )
