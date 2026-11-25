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
from urllib.parse import parse_qsl

import pytest

from next_is_you.domain import ClinicScope, ClinicSession, QueueObservation
from next_is_you.ntuh_reader import ListRow, parse_light_table, parse_request_token
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
# The fixed value that stands in for the selector page's anti-forgery token
# (ADR 0006): the token belongs to our request, not to the page.
TOKEN_PLACEHOLDER = "CAPTURE-TOKEN-PLACEHOLDER"
_PLACEHOLDER_TOKEN_FIELD = f'<input name="__RequestVerificationToken" type="hidden" value="{TOKEN_PLACEHOLDER}"'
# What a request or a session carries. A committed capture holds only the page.
_REQUEST_TEXT = re.compile(
    r"set-cookie|cookie|sessionid|session_id|requestverificationtoken|"
    r"authorization|bearer|csrf|xsrf",
    re.IGNORECASE,
)


def test_every_capture_names_its_capture_and_holds_only_the_page() -> None:
    # Clinic schedule captures (`schedule_*`) share this folder and this scan.
    paths = sorted(CAPTURES.glob("*.html"))
    pages = [path.name for path in paths if not path.name.startswith("schedule_")]
    assert len(pages) == 56
    for path in paths:
        text = path.read_text(encoding="utf-8")
        assert _NAMED_CAPTURE.fullmatch(text.split("\n", 1)[0].rstrip("\r")), path.name
        # The token field may stay only with the placeholder as its value.
        page_only = text.replace(_PLACEHOLDER_TOKEN_FIELD, "")
        assert _REQUEST_TEXT.search(page_only) is None, path.name


def test_the_scan_rejects_a_token_value_other_than_the_placeholder() -> None:
    selector = capture("selector_2026-11-25_1015.html")
    leaked = selector.replace(
        f'value="{TOKEN_PLACEHOLDER}"', 'value="aB3-real-looking-token"', 1
    )

    assert _REQUEST_TEXT.search(selector.replace(_PLACEHOLDER_TOKEN_FIELD, "")) is None
    assert _REQUEST_TEXT.search(leaked.replace(_PLACEHOLDER_TOKEN_FIELD, ""))
    # Cookie or session text anywhere in a page is still caught.
    cookie = selector.replace("</html>", "Set-Cookie: a=b</html>")
    assert _REQUEST_TEXT.search(cookie.replace(_PLACEHOLDER_TOKEN_FIELD, ""))


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


# The morning round of 2026-11-25 (AmpmCode=1, captured 10:15:00 to 10:15:47):
# the selector page, the list of 內科, 骨科, 眼科, 外科部 and 神經部, and detail
# pages of clinics on those lists.


def test_selector_page_holds_the_token_field_with_the_placeholder() -> None:
    # The real selector page, its token value replaced (#202 decision 3).
    assert parse_request_token(capture("selector_2026-11-25_1015.html")) == (
        TOKEN_PLACEHOLDER
    )


@pytest.mark.parametrize(
    "name",
    ["list_orth_am_2026-11-25_1015.html", "detail_orth03_senior_2026-11-25_1015.html"],
)
def test_list_and_detail_pages_hold_no_token(name: str) -> None:
    assert parse_request_token(capture(name)) is None


def test_internal_medicine_morning_list_2026_11_25() -> None:
    rows = {row.room: row for row in cards("list_med_am_2026-11-25_1015.html")}

    # 49 cards, 01 診 to 99 診.
    assert len(rows) == 49
    assert rows["01 診"] == ListRow("01 診", "黃政文", "普通門診", "010", "", "8148081")
    assert rows["03 診"] == ListRow("03 診", "廖偉智", "醫師約診", "016", "", "8148281")
    assert rows["11 診"] == ListRow(
        "11 診", "鄭傑隆", "普通門診", "052", "依報到順序看診", "8148536"
    )
    # A substitute doctor on a check-in-order card: 杜孟潔 followed by (代).
    assert rows["31 診"] == ListRow(
        "31 診", "杜孟潔(代)", "普通門診", "005", "依報到順序看診", "8573967"
    )
    # A check-in-order card with a blank light.
    assert rows["24 診"] == ListRow(
        "24 診", "張萬里", "普通門診", "", "依報到順序看診", "8367485"
    )
    # A blank light and no note.
    assert rows["42 診"] == ListRow("42 診", "賴台軒", "教學門診", "", "", "8367517")
    assert rows["99 診"] == ListRow("99 診", "遠距醫師", "醫師約診", "", "", "8148011")


def test_orthopedics_morning_list_2026_11_25() -> None:
    assert cards("list_orth_am_2026-11-25_1015.html") == [
        ListRow("01 診", "侯君翰", "普通門診", "045", "依報到順序看診", "8148438"),
        ListRow("02 診", "張允亮", "普通門診", "073", "依報到順序看診", "8148255"),
        ListRow("03 診", "張志豪", "普通門診", "019", "", "8148022"),
        ListRow("05 診", "黃全敬", "普通門診", "024", "", "8147928"),
        ListRow("06 診", "王貞棣", "普通門診", "057", "", "8148754"),
        ListRow("07 診", "陳宣佑", "普通門診", "014", "", "8393370"),
        ListRow("71 診", "主治醫師", "一日手術", "", "", "8148851"),
        ListRow("72 診", "主治醫師", "一日手術", "", "", "8148620"),
    ]


def test_ophthalmology_morning_list_2026_11_25() -> None:
    assert cards("list_oph_am_2026-11-25_1015.html") == [
        ListRow("02 診", "蘇乾嘉", "醫師約診", "005", "", "8148009"),
        ListRow("04 診", "楊中美", "普通門診", "026", "", "8148686"),
        ListRow("06 診", "何子昌", "普通門診", "034", "", "8148741"),
        ListRow("07 診", "郭柏邑", "教學門診", "", "", "8147934"),
        ListRow("08 診", "林昌平", "普通門診", "009", "", "8148740"),
        ListRow("10 診", "謝易庭", "醫師約診", "073", "", "8148547"),
        ListRow("11 診", "劉耀臨", "普通門診", "033", "", "8148284"),
        ListRow("12 診", "朱筱桑", "普通門診", "033", "", "8148209"),
        ListRow("63 診", "主治醫師", "一日手術", "", "", "8148481"),
        ListRow("80 診", "主治醫師", "一日手術", "", "", "8629817"),
        ListRow("81 診", "主治醫師", "一日手術", "", "", "8629770"),
        ListRow("83 診", "主治醫師", "一日手術", "", "", "8629864"),
        ListRow("95 診", "主治醫師", "一日手術", "", "", "8629723"),
        ListRow("96 診", "主治醫師", "一日手術", "", "", "8629676"),
        ListRow("99 診", "主治醫師", "檢查門診", "", "", "8148303"),
    ]


def test_surgery_morning_list_2026_11_25() -> None:
    assert cards("list_surg_am_2026-11-25_1015.html") == [
        ListRow("02 診", "主治醫師", "一日手術", "", "", "8686114"),
        ListRow("03 診", "陳政維", "普通門診", "023", "", "8148035"),
        ListRow("04 診", "吳明勳", "普通門診", "017", "", "8148572"),
        ListRow("05 診", "林子忻", "普通門診", "010", "依報到順序看診", "8148150"),
        ListRow("07 診", "住院醫師", "普通門診", "019", "", "8148841"),
        ListRow("08 診", "周迺寬", "普通門診", "008", "", "8148605"),
        ListRow("10 診", "黃凱文", "普通門診", "047", "", "8148634"),
        ListRow("12 診", "戴浩志", "普通門診", "009", "", "8148315"),
        ListRow("13 診", "徐紹勛", "普通門診", "003", "", "8148077"),
        ListRow("15 診", "黃約翰", "普通門診", "024", "", "8148570"),
        ListRow("16 診", "黃勝堅", "醫師約診", "", "", "8345164"),
        ListRow("17 診", "田郁文", "普通門診", "019", "", "8148840"),
        ListRow("18 診", "郭庭均", "普通門診", "035", "", "8148279"),
        ListRow("20 診", "謝榮賢", "普通門診", "006", "", "8338172"),
        ListRow("32 診", "蕭輔仁", "醫師約診", "", "", "8148426"),
        ListRow("76 診", "主治醫師", "一日手術", "", "", "8148612"),
        ListRow("77 診", "主治醫師", "一日手術", "", "依報到順序看診", "8147912"),
        ListRow("90 診", "住院醫師", "一日手術", "", "依報到順序看診", "8148184"),
        ListRow("94 診", "遠距醫師", "醫師約診", "", "", "8148045"),
        ListRow("97 診", "遠距醫師", "醫師約診", "", "", "8148247"),
    ]


def test_neurology_morning_list_2026_11_25() -> None:
    assert cards("list_neur_am_2026-11-25_1015.html") == [
        ListRow("01 診", "張楊全", "普通門診", "009", "", "8148735"),
        ListRow("02 診", "戴春暉", "普通門診", "010", "", "8148070"),
        ListRow("03 診", "葉馨喬", "醫師約診", "006", "", "8148089"),
        ListRow("04 診", "趙啟超", "普通門診", "020", "", "8148375"),
        ListRow("05 診", "李承軒", "醫師約診", "006", "", "8418919"),
        ListRow("06 診", "陳達夫", "普通門診", "047", "", "8148678"),
        ListRow("09 診", "主治醫師", "醫師約診", "", "", "8148324"),
        ListRow("10 診", "主治醫師", "醫師約診", "", "", "8279875"),
    ]


ORTH_LIST = "list_orth_am_2026-11-25_1015.html"


def test_the_list_render_time_is_not_kept() -> None:
    # The fragment shows 最後更新時間:2026-11-25 10:15:05. Freshness is the
    # reader's fetch time, so a later render time reads the same cards.
    page = capture(ORTH_LIST)
    later = page.replace("2026-11-25 10:15:05", "2026-11-25 10:16:05")
    assert later != page

    assert parse_light_table(later) == parse_light_table(page)
    assert "10:15:05" not in repr(cards(ORTH_LIST))


def test_a_blank_card_and_a_check_in_order_card_stay_apart() -> None:
    rows = {row.room: row for row in cards("list_surg_am_2026-11-25_1015.html")}

    # 76 診 shows a blank light (U+3000) and no note; 77 診 a blank light and
    # 依報到順序看診; 05 診 a light and 依報到順序看診.
    assert (rows["76 診"].current, rows["76 診"].check_in_order) == ("", "")
    assert (rows["77 診"].current, rows["77 診"].check_in_order) == (
        "",
        "依報到順序看診",
    )
    assert (rows["05 診"].current, rows["05 診"].check_in_order) == (
        "010",
        "依報到順序看診",
    )


def test_a_card_without_a_detail_link_has_no_service_id() -> None:
    page = capture(ORTH_LIST).replace(
        "ClinicCurrentLightNoDetail?ServiceIDSE=8148022&amp;vHospitalCode=T0",
        "ClinicCurrentLightNoDetail?vHospitalCode=T0",
    )
    rows = {row.room: row for row in parse_light_table(page)[1]}

    assert rows["03 診"].service_id == ""
    assert rows["02 診"].service_id == "8148255"


_ORTH_02_DOCTOR = '<div class="clinic-doc-name">張允亮</div>'
_ORTH_02_NUMBER = re.compile(r'<div class="number">\s*073\s*</div>')


@pytest.mark.parametrize(
    "alter",
    [
        # No card at all: every card's anchor is gone.
        lambda page: page.replace('class="open-link"', 'class="closed-link"'),
        # One card lost its doctor, or the doctor's name.
        lambda page: page.replace(_ORTH_02_DOCTOR, ""),
        lambda page: page.replace(
            _ORTH_02_DOCTOR, '<div class="clinic-doc-name"></div>'
        ),
        # One card lost its number.
        lambda page: _ORTH_02_NUMBER.sub("", page),
    ],
    ids=["no-cards", "no-doctor", "blank-doctor", "no-number"],
)
def test_a_list_missing_cards_or_card_fields_is_a_schema_failure(alter) -> None:
    page = capture(ORTH_LIST)
    altered = alter(page)
    assert altered != page

    assert parse_light_table(altered) == ("schema", [])


@pytest.mark.parametrize(
    ("text", "status"),
    [
        ("Please complete the CAPTCHA", "challenge"),
        ("請完成驗證碼", "challenge"),
        ("Access Denied", "denied"),
    ],
)
def test_a_list_showing_a_challenge_or_denial_is_named(text: str, status: str) -> None:
    page = capture(ORTH_LIST).replace(
        '<div class="main-container', f'<p>{text}</p><div class="main-container', 1
    )
    assert text in page

    assert parse_light_table(page) == (status, [])


def test_internal_medicine_number_order_page_2026_11_25() -> None:
    # 內科部 03診 at 10:15:17: light 016 順號, 已叫最大號 018, and 預計叫號 shows one
    # number, 017, with no type after it (read in the test below).
    page = detail("detail_med03_2026-11-25_1015.html")

    assert (page.room, page.doctor) == ("內科部 03診", "廖偉智")
    assert page.current_light == 16
    assert page.current_flag == "sequential"
    assert page.highest_called == 18
    assert page.check_in_order is False
    assert page.check_in_position is None
    assert page.numbers == numbers_as_shown(
        "7 未報到 11 未報到 16 看診中 17 已報到 18 已報到 19 已報到 20 已報到"
        " 21 已報到 22 未報到 23 已報到 24 未報到 25 已報到 26 未報到 27 未報到"
        " 28 未報到 29 未報到 30 未報到 31 已報到 32 未報到 33 未報到 34 已報到"
        " 35 未報到 36 已報到 37 未報到 38 未報到 39 未報到 40 未報到 41 未報到"
        " 42 未報到 43 未報到"
    )


def test_internal_medicine_untyped_expected_call_is_read_2026_11_25() -> None:
    # 預計叫號 shows a bare 017 with no type, so its kind is unknown.
    page = detail("detail_med03_2026-11-25_1015.html")

    assert page.expected == (ExpectedCall(17, None),)


def test_orthopedics_check_in_order_clinic_calling_an_exam_2026_11_25() -> None:
    # 骨科部 02診 at 10:15:22, titled 預計叫號 (依報到順序看診): light 073 檢查號,
    # a blank 已叫最大號, and 預計叫號 073 (檢查號) 057 (報到20) 070 (報到22).
    page = detail("detail_orth02_check_in_order_exam_2026-11-25_1015.html")

    assert (page.room, page.doctor) == ("骨科部 02診", "張允亮")
    assert page.current_light == 73
    assert page.current_flag == "exam"
    assert page.highest_called is None
    assert page.check_in_order is True
    assert page.check_in_position is None
    assert page.expected == (
        ExpectedCall(73, "exam"),
        ExpectedCall(57, "check_in", 20),
        ExpectedCall(70, "check_in", 22),
    )
    assert page.numbers == numbers_as_shown(
        "1 報到23 3 報到42 6 報到35 11 報到37 12 報到30 13 未報到 14 報到32"
        " 16 報到25 18 未報到 27 未報到 28 報到44 31 報到39 33 報到24 34 報到34"
        " 36 報到31 38 未報到 39 報到46 40 未報到 42 報到27 43 報到36 45 未報到"
        " 48 報到26 49 報到40 50 未報到 51 報到29 52 未報到 53 未報到 55 報到47"
        " 56 未報到 57 報到20 69 未報到 70 報到22 71 報到41 73 看診中 74 報到38"
        " 75 報到18 76 未報到 77 報到1 79 未報到 82 未報到 83 未報到 85 報到45"
        " 86 報到43 87 未報到 88 報到19"
    )


def test_orthopedics_senior_call_ahead_of_highest_called_2026_11_25() -> None:
    # 骨科部 03診 at 10:15:24: light 019 敬老號 while 已叫最大號 is 009.
    page = detail("detail_orth03_senior_2026-11-25_1015.html")

    assert (page.room, page.doctor) == ("骨科部 03診", "張志豪")
    assert page.current_light == 19
    assert page.current_flag == "senior"
    assert page.highest_called == 9
    assert page.check_in_order is False
    assert page.expected == (
        ExpectedCall(19, "senior"),
        ExpectedCall(8, "sequential"),
        ExpectedCall(9, "sequential"),
    )
    assert page.numbers == numbers_as_shown(
        "3 未報到 7 已報到 8 已報到 9 已報到 10 未報到 12 已報到 13 未報到"
        " 17 未報到 19 看診中 20 未報到 21 已報到 22 未報到 23 未報到 24 已報到"
        " 25 未報到 26 未報到 27 已報到 29 已報到 31 未報到 33 未報到 34 未報到"
        " 35 未報到 36 未報到 37 未報到 39 未報到 40 未報到 43 未報到 44 未報到"
        " 45 未報到 46 已報到 47 未報到 48 未報到 49 未報到 50 未報到 51 已報到"
        " 52 已報到 53 已報到 55 已報到 56 已報到 57 未報到 68 已報到 69 未報到"
    )


@pytest.mark.parametrize(
    ("name", "room", "doctor", "numbers"),
    [
        # 骨科部 72診 at 10:15:26, a 一日手術 card with a blank light: the page
        # shows a blank (U+3000) light and 已叫最大號 and lists no number.
        ("detail_orth72_empty_2026-11-25_1015.html", "骨科部 72診", "主治醫師", ""),
        # 神經部 10診 at 10:15:47: no number called yet, three numbers waiting.
        (
            "detail_neur10_not_started_2026-11-25_1015.html",
            "神經部 10診",
            "主治醫師",
            "1 未報到 4 未報到 6 未報到",
        ),
    ],
)
def test_clinic_that_has_called_no_number_yet_2026_11_25(
    name: str, room: str, doctor: str, numbers: str
) -> None:
    page = detail(name)

    assert (page.room, page.doctor) == (room, doctor)
    assert page.current_light is None
    assert page.current_flag is None
    assert page.highest_called is None
    assert page.check_in_order is False
    assert page.check_in_position is None
    assert page.expected == ()
    assert page.numbers == numbers_as_shown(numbers)


OPH06_NUMBERS = (
    "1 已報到 2 已報到 4 已報到 5 已報到 7 已報到 8 未報到 11 已報到 12 未報到"
    " 14 已報到 18 已報到 19 已報到 20 已報到 21 已報到 22 已報到 23 未報到"
    " 24 已報到 25 已報到 31 未報到 32 已報到 34 看診中 35 未報到 36 已報到"
    " 37 已報到 38 已報到 39 未報到 40 未報到 41 已報到 42 已報到 43 未報到"
    " 44 未報到 45 已報到 46 已報到 47 未報到 48 未報到 49 已報到 51 已報到"
    " 56 未報到 57 已報到 59 初診 68 已報到 69 已報到 70 未報到 71 未報到"
    " 73 已報到 74 已報到 76 已報到"
)


def test_ophthalmology_page_with_a_first_visit_number_2026_11_25() -> None:
    # 眼科部 06診 at 10:15:31: light 034 順號 at 已叫最大號 034, 預計叫號
    # 035 (順號) 007 (檢查號), and number 59 marked 初診.
    page = detail("detail_oph06_first_visit_2026-11-25_1015.html")

    assert (page.room, page.doctor) == ("眼科部 06診", "何子昌")
    assert page.current_light == 34
    assert page.current_flag == "sequential"
    assert page.highest_called == 34
    assert page.check_in_order is False
    assert page.expected == (ExpectedCall(35, "sequential"), ExpectedCall(7, "exam"))
    assert page.numbers == numbers_as_shown(OPH06_NUMBERS)


def test_surgery_exam_call_far_below_highest_called_2026_11_25() -> None:
    # 外科部 04診 at 10:15:35: light 017 檢查號 with 已叫最大號 119, 預計叫號
    # 017 (檢查號) 026 (過號) 042 (過號).
    page = detail("detail_surg04_exam_2026-11-25_1015.html")

    assert (page.room, page.doctor) == ("外科部 04診", "吳明勳")
    assert page.current_light == 17
    assert page.current_flag == "exam"
    assert page.highest_called == 119
    assert page.check_in_order is False
    assert page.expected == (
        ExpectedCall(17, "exam"),
        ExpectedCall(26, "passed"),
        ExpectedCall(42, "passed"),
    )
    assert page.numbers == numbers_as_shown(
        "8 已報到 11 已報到 14 未報到 17 看診中 18 已報到 19 未報到 20 未報到"
        " 21 未報到 22 已報到 24 未報到 26 已報到 28 已報到 30 已報到 32 未報到"
        " 33 未報到 34 未報到 35 未報到 36 已報到 37 已報到 40 未報到 42 已報到"
        " 45 未報到 46 未報到 47 未報到 48 未報到 51 未報到 53 已報到 54 未報到"
        " 55 未報到 57 已報到 59 未報到 68 已報到 69 未報到 70 未報到 71 未報到"
        " 72 已報到 74 未報到 76 未報到 79 未報到 80 未報到 81 未報到 82 未報到"
        " 86 未報到 88 未報到 89 未報到 90 未報到 91 未報到 92 未報到 93 未報到"
        " 94 未報到 95 未報到 96 已報到 98 未報到 101 未報到 102 未報到 103 未報到"
        " 104 未報到 105 未報到 107 未報到 108 未報到 109 已報到 112 未報到"
        " 113 未報到 114 未報到 115 未報到 116 未報到 117 未報到 118 未報到"
        " 119 未報到"
    )


def test_surgery_check_in_order_clinic_shows_its_position_2026_11_25() -> None:
    # 外科部 05診 at 10:15:38: light 010 with 報到順序05 under it, a blank
    # 已叫最大號, and 預計叫號 (依報到順序看診) 025 (報到07).
    page = detail("detail_surg05_check_in_order_2026-11-25_1015.html")

    assert (page.room, page.doctor) == ("外科部 05診", "林子忻")
    assert page.current_light == 10
    assert page.current_flag is None
    assert page.check_in_order is True
    assert page.check_in_position == 5
    assert page.highest_called is None
    assert page.expected == (ExpectedCall(25, "check_in", 7),)
    assert page.numbers == numbers_as_shown(
        "8 未報到 9 未報到 10 看診中 11 報到9 16 報到10 18 未報到 19 報到8"
        " 22 報到6 25 報到7 32 未報到"
    )


NEUR03_NUMBERS = (
    "6 看診中 9 已報到 15 已報到 16 未報到 17 未報到 18 未報到 19 未報到"
    " 20 已報到 21 未報到 22 已報到 23 未報到 24 未報到 25 未報到 26 已報到"
    " 27 未報到 28 未報到 29 已報到 30 已報到 31 未報到 32 已報到 33 未報到"
    " 34 未報到"
)


def test_neurology_exam_call_with_a_passed_number_expected_2026_11_25() -> None:
    # 神經部 03診 at 10:15:44: light 006 檢查號, 已叫最大號 016, 預計叫號
    # 006 (檢查號) 009 (過號) 016 (順號).
    page = detail("detail_neur03_exam_2026-11-25_1015.html")

    assert (page.room, page.doctor) == ("神經部 03診", "葉馨喬")
    assert page.current_light == 6
    assert page.current_flag == "exam"
    assert page.highest_called == 16
    assert page.check_in_order is False
    assert page.expected == (
        ExpectedCall(6, "exam"),
        ExpectedCall(9, "passed"),
        ExpectedCall(16, "sequential"),
    )
    assert page.numbers == numbers_as_shown(NEUR03_NUMBERS)


def test_each_card_of_2026_11_25_links_to_the_detail_page_showing_its_light() -> None:
    # Each list was captured a few seconds before its detail pages.
    pairs = [
        (
            "list_med_am_2026-11-25_1015.html",
            "03 診",
            "detail_med03_2026-11-25_1015.html",
        ),
        (ORTH_LIST, "02 診", "detail_orth02_check_in_order_exam_2026-11-25_1015.html"),
        (ORTH_LIST, "03 診", "detail_orth03_senior_2026-11-25_1015.html"),
        (ORTH_LIST, "72 診", "detail_orth72_empty_2026-11-25_1015.html"),
        (
            "list_oph_am_2026-11-25_1015.html",
            "06 診",
            "detail_oph06_first_visit_2026-11-25_1015.html",
        ),
        (
            "list_surg_am_2026-11-25_1015.html",
            "04 診",
            "detail_surg04_exam_2026-11-25_1015.html",
        ),
        (
            "list_surg_am_2026-11-25_1015.html",
            "05 診",
            "detail_surg05_check_in_order_2026-11-25_1015.html",
        ),
        (
            "list_neur_am_2026-11-25_1015.html",
            "03 診",
            "detail_neur03_exam_2026-11-25_1015.html",
        ),
        (
            "list_neur_am_2026-11-25_1015.html",
            "10 診",
            "detail_neur10_not_started_2026-11-25_1015.html",
        ),
    ]
    for list_page, room, detail_page in pairs:
        card = next(row for row in cards(list_page) if row.room == room)
        assert f"ServiceIDSE={card.service_id}." in capture(detail_page).splitlines()[0]
        page = detail(detail_page)
        assert page.doctor == card.doctor
        assert page.current_light == (int(card.current) if card.current else None)


@pytest.mark.asyncio
async def test_reader_reads_a_clinic_from_the_real_selector_list_and_detail() -> None:
    # 眼科 06診 何子昌 普通門診, morning of 2026-11-25 (the reader serves 眼科
    # only): it takes the token from the real selector page, finds the card on
    # the 10:15:08 list, then reads the card's detail page captured at 10:15:31.
    source = TwoPageSource(
        capture("list_oph_am_2026-11-25_1015.html"),
        capture("detail_oph06_first_visit_2026-11-25_1015.html"),
    )
    r = reader(source)
    clinic = ClinicScope(
        "ntuh-main",
        date(2026, 11, 25),
        "OPH",
        "06診/何子昌/普通門診",
        ClinicSession.MORNING,
    )
    taipei = timezone(timedelta(hours=8))

    found = await r.observe_for_start(
        clinic, datetime(2026, 11, 25, 10, 15, tzinfo=taipei)
    )
    assert isinstance(found, QueueObservation)
    assert found.current_number == 34
    assert source.detail_urls == []
    (post,) = [request for request in source.requests if request.method == "POST"]
    sent = dict(parse_qsl(post.body or ""))
    assert sent["__RequestVerificationToken"] == TOKEN_PLACEHOLDER
    assert (sent["DeptCode"], sent["AmpmCode"]) == ("OPH", "1")

    read = await r.observe(clinic, datetime(2026, 11, 25, 10, 17, tzinfo=taipei))

    assert [url.split("?")[1] for url in source.detail_urls] == [
        "ServiceIDSE=8148741&vHospitalCode=T0"
    ]
    assert isinstance(read, QueueObservation)
    # The page: light 034 順號, 已叫最大號 034, 預計叫號 035 (順號) 007 (檢查號).
    assert read.current_number == 34
    assert read.current_flag == "sequential"
    assert read.highest_called_number == 34
    assert read.check_in_order is False
    assert read.substitute_doctor is False
    assert read.expected == (ExpectedCall(35, "sequential"), ExpectedCall(7, "exam"))
    assert read.numbers == numbers_as_shown(OPH06_NUMBERS)
