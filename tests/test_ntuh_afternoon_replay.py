"""Replay the NTUH afternoon captures of 2026-11-25 through the reader (#205).

Fixture/mock evidence, ADR 0006. The afternoon session (AmpmCode=2) opens at
13:30. It was captured three times for 內科, 骨科, 眼科, 外科部 and 神經部:
before the clinic opens (12:45), just after it opens (13:50) and midway (15:00),
each round a list page per department followed by detail pages of clinics on it.

Expected values are read off the page as a person sees it, never copied from the
parser's output. A blank light on a list card is a full-width space (U+3000),
which the card shows as nothing. Nothing here reaches the hospital.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from urllib.parse import parse_qsl

import pytest

from next_is_you.domain import ClinicScope, ClinicSession, QueueObservation, ReadSkipped
from next_is_you.ntuh_detail import ExpectedCall
from next_is_you.ntuh_reader import ListRow

from test_ntuh_capture_replay import capture, cards, detail, numbers_as_shown
from test_ntuh_reader import TwoPageSource, reader

ROUNDS = ("before_open", "just_open", "midway")
STAMPS = {"before_open": "1245", "just_open": "1350", "midway": "1500"}
CHECK_IN_ORDER = "依報到順序看診"


def list_page(department: str, round_: str) -> str:
    return f"list_{department}_pm_{round_}_2026-11-25_{STAMPS[round_]}.html"


# Each department's afternoon cards in page order, read off the 12:45 list:
# room, doctor, clinic type, the 依報到順序看診 note and the detail link's
# ServiceIDSE. The 13:50 and 15:00 lists show the same cards in the same order;
# only the lights differ. A doctor followed by (代) is a substitute.
ROSTERS: dict[str, list[tuple[str, str, str, str, str]]] = {
    "med": [
        ("01 診", "于鎧綸", "普通門診", "", "8148005"),
        ("02 診", "鐘桂彬", "普通門診", "", "8148351"),
        ("03 診", "蔡偉", "醫師約診", "", "8148451"),
        ("04 診", "郭耀文", "普通門診", "", "8148286"),
        ("05 診", "楊荔丹", "普通門診", "", "8148169"),
        ("06 診", "王正一", "醫師約診", "", "8148863"),
        ("08 診", "阮聖元", "普通門診", "", "8148384"),
        ("09 診", "林水龍", "普通門診", "", "8148714"),
        ("10 診", "江君揚", "醫師約診", "", "8148197"),
        ("11 診", "呂政勳", "醫師約診", "", "8148298"),
        ("14 診", "侯信安", "普通門診", "", "8148289"),
        ("16 診", "朱景祺", "普通門診", "", "8148866"),
        ("17 診", "黃泰中", "醫師約診", "", "8148498"),
        ("18 診", "楊紹佑", "醫師約診", "", "8148753"),
        ("19 診", "林彥宏", "普通門診", "", "8531540"),
        ("20 診", "何肇基", "醫師約診", "", "8148659"),
        ("21 診", "黃瑞雄", "普通門診", "", "8148696"),
        ("22 診", "陳盈憲", "普通門診", "", "8148744"),
        ("23 診", "魏淑鉁", "醫師約診", "", "8148758"),
        ("24 診", "黃慶昌", "醫師約診", "", "8148573"),
        ("25 診", "姜至剛", "醫師約診", "", "8148558"),
        ("27 診", "何奕倫", "醫師約診", "", "8148833"),
        ("30 診", "王怡智", "普通門診", "", "8148533"),
        ("33 診", "陳明豐", "醫師約診", "", "8148517"),
        ("34 診", "總醫師(代)", "醫師約診", "", "8148542"),
        ("35 診", "陳冠宇", "醫師約診", "", "8148703"),
        ("38 診", "郭佑民", "普通門診", "", "8148377"),
        ("40 診", "江卓鴻", "普通門診", "", "8352844"),
        ("41 診", "黃子寧", "普通門診", "", "8338099"),
        ("43 診", "主治醫師", "醫師約診", "", "8148359"),
        ("44 診", "篩檢醫師", "醫師約診", "", "8148148"),
        ("45 診", "洪子雯", "醫師約診", "", "8148001"),
        ("46 診", "李咏倪", "醫師約診", CHECK_IN_ORDER, "8148102"),
        ("47 診", "李咏倪", "醫師約診", CHECK_IN_ORDER, "8148100"),
        ("50 診", "賴台軒", "醫師約診", "", "8148411"),
        ("85 診", "篩檢醫師", "醫師約診", "", "8148144"),
        ("89 診", "主治醫師", "醫師約診", CHECK_IN_ORDER, "8147996"),
        ("94 診", "遠距醫師", "醫師約診", "", "8148068"),
        ("95 診", "主治醫師", "醫師約診", "", "8148409"),
        ("98 診", "主治醫師", "醫師約診", "", "8148479"),
    ],
    "orth": [
        ("02 診", "張允亮", "普通門診", CHECK_IN_ORDER, "8148256"),
        ("05 診", "黃全敬", "普通門診", "", "8147929"),
        ("06 診", "陳沛裕", "普通門診", "", "8148510"),
        ("07 診", "王廷明", "普通門診", CHECK_IN_ORDER, "8148776"),
    ],
    "oph": [
        ("02 診", "張逖文", "普通門診", "", "8147988"),
        ("05 診", "王詩文", "普通門診", "", "8340538"),
        ("06 診", "何子昌", "普通門診", "", "8334203"),
        ("07 診", "夏昀", "普通門診", "", "8148285"),
        ("09 診", "總醫師", "普通門診", "", "8148507"),
        ("10 診", "謝易庭", "醫師約診", "", "8148373"),
        ("11 診", "廖述朗", "醫師約診", "", "8148392"),
        ("12 診", "廖述朗", "醫師約診", "", "8148738"),
        ("61 診", "王清泓", "醫師約診", "", "8148553"),
        ("68 診", "主治醫師", "一日手術", "", "8148436"),
        ("80 診", "主治醫師", "一日手術", "", "8629582"),
        ("81 診", "主治醫師", "一日手術", "", "8629535"),
        ("83 診", "主治醫師", "一日手術", "", "8629629"),
        ("95 診", "主治醫師", "一日手術", "", "8629488"),
        ("96 診", "主治醫師", "一日手術", "", "8629441"),
    ],
    "surg": [
        ("01 診", "主治醫師", "一日手術", "", "8148484"),
        ("03 診", "虞希禹", "普通門診", "", "8148837"),
        ("04 診", "吳明勳", "醫師約診", "", "8148314"),
        ("05 診", "黃書健", "普通門診", "", "8148817"),
        ("07 診", "洪學義", "普通門診", "", "8148836"),
        ("08 診", "陳敞牧", "普通門診", "", "8148432"),
        ("09 診", "傅薰儀", "普通門診", "", "8147955"),
        ("10 診", "黃凱文", "普通門診", "", "8148508"),
        ("11 診", "洪基翔", "普通門診", "", "8148666"),
        ("12 診", "盧照文", "醫師約診", "", "8555789"),
        ("13 診", "盧照文(代)", "普通門診", "", "8148633"),
        ("14 診", "陳國瑋", "普通門診", "", "8148463"),
        ("15 診", "江旴恒", "普通門診", "", "8148139"),
        ("19 診", "吳健暉", "普通門診", "", "8148322"),
        ("32 診", "曾漢民", "醫師約診", "", "8148771"),
        ("76 診", "主治醫師", "一日手術", "", "8148611"),
        ("86 診", "主治醫師", "一日手術", "", "8148838"),
        ("94 診", "遠距醫師", "醫師約診", "", "8148044"),
    ],
    "neur": [
        ("02 診", "戴春暉", "醫師約診", "", "8147949"),
        ("03 診", "郭懿芝", "普通門診", "", "8148032"),
        ("05 診", "范齡勻", "普通門診", "", "8473160"),
        ("07 診", "朱海瑞", "普通門診", "", "8147975"),
        ("08 診", "沈英琪", "普通門診", "", "8365246"),
        ("10 診", "主治醫師", "醫師約診", "", "8279922"),
    ],
}

# The light on each card, in roster order, as the 13:50 and 15:00 lists show
# it. "" is a blank light. At 12:45 every card of every department is blank.
LIGHTS: dict[tuple[str, str], str] = {
    ("med", "just_open"): (
        "002 002 002 017 032 001 005 020 059 003 003 002 007 002 001 039 001 002"
        " 004 014 007 014 003 019 - 001 009 002 009 - - 005 - 007 - - - - - -"
    ),
    ("med", "midway"): (
        "026 019 010 037 001 006 018 025 019 016 014 016 020 015 038 031 004 081"
        " 015 033 023 013 036 - - 011 020 010 021 - - 010 - 035 - - - - - -"
    ),
    ("orth", "just_open"): "040 - 002 019",
    ("orth", "midway"): "018 023 011 023",
    ("oph", "just_open"): "007 - 007 - 003 - - - - - - - - - -",
    ("oph", "midway"): "056 010 036 015 002 - 005 022 - - - - - - -",
    ("surg", "just_open"): "- - 009 - - 008 - 026 033 007 032 001 002 001 - - - -",
    ("surg", "midway"): "- 007 021 014 032 016 - 019 013 010 024 013 029 019 - - - -",
    ("neur", "just_open"): "003 003 001 009 001 -",
    ("neur", "midway"): "010 019 005 010 005 -",
}


def expected_cards(department: str, round_: str) -> list[ListRow]:
    roster = ROSTERS[department]
    if round_ == "before_open":
        lights = [""] * len(roster)
    else:
        lights = [
            "" if light == "-" else light
            for light in LIGHTS[(department, round_)].split()
        ]
    assert len(lights) == len(roster)
    return [
        ListRow(room, doctor, kind, light, note, service_id)
        for (room, doctor, kind, note, service_id), light in zip(
            roster, lights, strict=True
        )
    ]


@pytest.mark.parametrize("department", list(ROSTERS))
@pytest.mark.parametrize("round_", ROUNDS)
def test_every_card_of_each_afternoon_list(department: str, round_: str) -> None:
    # 12:45 is before the 13:30 opening: every card shows a blank light.
    assert cards(list_page(department, round_)) == expected_cards(department, round_)


def test_no_card_shows_a_light_before_the_afternoon_opens() -> None:
    for department in ROSTERS:
        rows = cards(list_page(department, "before_open"))
        assert rows
        assert {row.current for row in rows} == {""}, department


# The detail pages that follow a card's light through the three rounds.
SERIES = {
    # 神經部 03診 郭懿芝, ServiceIDSE=8148032.
    "neur03": ("neur", "03 診"),
    # 內科部 03診 蔡偉, ServiceIDSE=8148451.
    "med03": ("med", "03 診"),
}


def series_page(clinic: str, round_: str) -> str:
    return f"detail_{clinic}_{round_}_2026-11-25_{STAMPS[round_]}.html"


def test_neurology_clinic_before_it_opens_2026_11_25() -> None:
    # 神經部 03診 at 12:45:43: no light, no 已叫最大號, no 預計叫號, and every
    # number waiting with no one checked in yet except number 12 marked 初診.
    page = detail(series_page("neur03", "before_open"))

    assert (page.room, page.doctor) == ("神經部 03診", "郭懿芝")
    assert page.current_light is None
    assert page.current_flag is None
    assert page.highest_called is None
    assert page.check_in_order is False
    assert page.expected == ()
    assert page.numbers == numbers_as_shown(
        "2 未報到 3 未報到 4 未報到 5 未報到 6 未報到 7 未報到 8 未報到 9 未報到"
        " 10 未報到 11 未報到 12 初診 14 未報到 19 未報到 20 未報到 21 未報到"
        " 22 未報到 23 未報到 24 未報到 25 未報到 27 未報到 28 未報到 29 未報到"
        " 30 未報到 31 未報到 32 未報到 33 未報到 34 未報到 35 未報到 36 未報到"
        " 37 未報到 38 未報到 39 未報到 40 未報到 42 未報到 43 未報到 44 未報到"
        " 46 未報到 47 未報到 48 未報到 49 未報到"
    )


def test_neurology_clinic_just_after_it_opens_2026_11_25() -> None:
    # 神經部 03診 at 13:50:42: light 003 順號, 已叫最大號 004, and 預計叫號
    # 003 (順號) 006 (敬老號) 004 (順號).
    page = detail(series_page("neur03", "just_open"))

    assert (page.room, page.doctor) == ("神經部 03診", "郭懿芝")
    assert page.current_light == 3
    assert page.current_flag == "sequential"
    assert page.highest_called == 4
    assert page.check_in_order is False
    assert page.expected == (
        ExpectedCall(3, "sequential"),
        ExpectedCall(6, "senior"),
        ExpectedCall(4, "sequential"),
    )
    assert page.numbers == numbers_as_shown(
        "2 未報到 3 看診中 4 已報到 5 未報到 6 已報到 8 未報到 9 已報到 10 已報到"
        " 11 已報到 12 初診 14 未報到 19 未報到 20 未報到 21 未報到 22 已報到"
        " 23 已報到 24 未報到 25 未報到 27 未報到 28 未報到 29 未報到 30 未報到"
        " 31 未報到 32 未報到 33 未報到 34 未報到 35 未報到 36 未報到 37 未報到"
        " 38 未報到 39 未報到 40 未報到 42 未報到 43 未報到 44 未報到 46 未報到"
        " 47 未報到 48 未報到 49 未報到"
    )


def test_neurology_clinic_midway_2026_11_25() -> None:
    # 神經部 03診 at 15:00:40: light 019 順號, 已叫最大號 021, and 預計叫號
    # 019 (順號) 020 (順號) 021 (順號).
    page = detail(series_page("neur03", "midway"))

    assert (page.room, page.doctor) == ("神經部 03診", "郭懿芝")
    assert page.current_light == 19
    assert page.current_flag == "sequential"
    assert page.highest_called == 21
    assert page.expected == (
        ExpectedCall(19, "sequential"),
        ExpectedCall(20, "sequential"),
        ExpectedCall(21, "sequential"),
    )
    assert page.numbers == numbers_as_shown(
        "2 未報到 8 未報到 12 初診 19 看診中 20 未報到 21 未報到 22 已報到"
        " 23 已報到 24 已報到 25 已報到 27 已報到 28 已報到 29 未報到 30 已報到"
        " 31 未報到 32 已報到 33 未報到 34 已報到 35 已報到 36 已報到 37 未報到"
        " 38 未報到 39 未報到 40 未報到 42 未報到 43 未報到 44 未報到 46 未報到"
        " 47 已報到 48 未報到 49 未報到"
    )


def test_internal_medicine_clinic_before_it_opens_2026_11_25() -> None:
    # 內科部 03診 at 12:45:18: no light and 23 numbers, none checked in yet.
    page = detail(series_page("med03", "before_open"))

    assert (page.room, page.doctor) == ("內科部 03診", "蔡偉")
    assert page.current_light is None
    assert page.current_flag is None
    assert page.highest_called is None
    assert page.expected == ()
    assert page.numbers == numbers_as_shown(
        "1 未報到 2 未報到 3 未報到 4 未報到 5 未報到 6 未報到 7 未報到 8 未報到"
        " 9 未報到 10 未報到 11 未報到 12 未報到 13 未報到 14 未報到 15 未報到"
        " 16 未報到 17 未報到 18 未報到 20 未報到 21 未報到 22 未報到 23 未報到"
        " 24 未報到"
    )


def test_internal_medicine_clinic_just_after_it_opens_2026_11_25() -> None:
    # 內科部 03診 at 13:50:17: light 002 順號, 已叫最大號 004, 預計叫號 004 (順號).
    page = detail(series_page("med03", "just_open"))

    assert (page.room, page.doctor) == ("內科部 03診", "蔡偉")
    assert page.current_light == 2
    assert page.current_flag == "sequential"
    assert page.highest_called == 4
    assert page.expected == (ExpectedCall(4, "sequential"),)
    assert page.numbers == numbers_as_shown(
        "2 看診中 3 已報到 4 已報到 5 已報到 6 未報到 7 未報到 8 未報到 9 已報到"
        " 10 未報到 11 未報到 12 未報到 13 未報到 14 已報到 15 未報到 16 未報到"
        " 17 未報到 18 未報到 20 未報到 21 未報到 22 未報到 23 未報到 24 未報到"
    )


def test_internal_medicine_clinic_midway_2026_11_25() -> None:
    # 內科部 03診 at 15:00:18: light 010 順號, 已叫最大號 012, and 預計叫號
    # 010 (順號) 011 (順號) 012 (順號). Numbers 1 to 9 have left the list.
    page = detail(series_page("med03", "midway"))

    assert (page.room, page.doctor) == ("內科部 03診", "蔡偉")
    assert page.current_light == 10
    assert page.current_flag == "sequential"
    assert page.highest_called == 12
    assert page.expected == (
        ExpectedCall(10, "sequential"),
        ExpectedCall(11, "sequential"),
        ExpectedCall(12, "sequential"),
    )
    assert page.numbers == numbers_as_shown(
        "10 看診中 11 已報到 12 已報到 13 已報到 14 已報到 15 已報到 16 已報到"
        " 17 未報到 18 未報到 20 未報到 21 未報到 22 未報到 23 未報到 24 已報到"
    )


@pytest.mark.parametrize("clinic", list(SERIES))
def test_the_light_moves_forward_from_before_opening_to_midway(clinic: str) -> None:
    # The same clinic's card and detail page at 12:45, 13:50 and 15:00.
    department, room = SERIES[clinic]
    pages = [detail(series_page(clinic, round_)) for round_ in ROUNDS]
    lights = [
        next(row for row in cards(list_page(department, round_)) if row.room == room)
        for round_ in ROUNDS
    ]

    before, opened, midway = pages
    assert before.current_light is None and before.highest_called is None
    assert opened.current_light is not None and midway.current_light is not None
    assert before.numbers and opened.numbers and midway.numbers
    assert opened.current_light < midway.current_light
    assert opened.highest_called is not None and midway.highest_called is not None
    assert opened.highest_called < midway.highest_called
    assert [card.current for card in lights] == [
        "",
        f"{opened.current_light:03d}",
        f"{midway.current_light:03d}",
    ]
    # One clinic: one detail link through the afternoon.
    assert len({card.service_id for card in lights}) == 1


def test_neurology_passed_number_as_the_current_light_2026_11_25() -> None:
    # 神經部 05診 at 15:00:42: light 005 過號 below 已叫最大號 016, and 預計叫號
    # 005 (過號) 014 (順號) 016 (順號).
    page = detail("detail_neur05_passed_2026-11-25_1500.html")

    assert (page.room, page.doctor) == ("神經部 05診", "范齡勻")
    assert page.current_light == 5
    assert page.current_flag == "passed"
    assert page.highest_called == 16
    assert page.check_in_order is False
    assert page.expected == (
        ExpectedCall(5, "passed"),
        ExpectedCall(14, "sequential"),
        ExpectedCall(16, "sequential"),
    )
    assert page.numbers == numbers_as_shown(
        "2 初診 5 看診中 11 未報到 12 初診 14 未報到 16 未報到 19 未報到 20 已報到"
    )


def test_ophthalmology_passed_number_with_no_expected_call_2026_11_25() -> None:
    # 眼科部 05診 at 15:00:27: light 010 過號, 已叫最大號 011, and both 預計叫號
    # slots read 000 (無): no expected call.
    page = detail("detail_oph05_passed_no_expected_2026-11-25_1500.html")

    assert (page.room, page.doctor) == ("眼科部 05診", "王詩文")
    assert page.current_light == 10
    assert page.current_flag == "passed"
    assert page.highest_called == 11
    assert page.expected == ()
    assert page.numbers == numbers_as_shown(
        "1 已報到 3 已報到 5 已報到 8 已報到 9 已報到 10 看診中 11 已報到"
    )


def test_ophthalmology_exam_call_not_on_the_number_list_2026_11_25() -> None:
    # 眼科部 11診 at 15:00:31: light 005 檢查號 with 已叫最大號 018 and 預計叫號
    # 012 (過號) 009 (過號). Number 5 is not on the list: no number shows 看診中.
    page = detail("detail_oph11_exam_2026-11-25_1500.html")

    assert (page.room, page.doctor) == ("眼科部 11診", "廖述朗")
    assert page.current_light == 5
    assert page.current_flag == "exam"
    assert page.highest_called == 18
    assert page.expected == (ExpectedCall(12, "passed"), ExpectedCall(9, "passed"))
    assert page.numbers == numbers_as_shown(
        "2 未報到 8 已報到 9 已報到 12 已報到 14 已報到 16 未報到 17 已報到 18 已報到"
    )


OPH07_MIDWAY_NUMBERS = (
    "4 已報到 5 未報到 6 已報到 7 未報到 11 已報到 15 看診中 16 已報到 17 已報到"
    " 18 未報到 19 已報到 20 已報到 21 已報到 22 已報到 23 未報到 24 已報到"
    " 25 已報到 26 已報到 27 已報到 28 已報到 29 已報到 30 已報到 32 已報到"
    " 33 已報到 34 已報到 35 已報到 36 已報到 37 已報到 38 已報到 41 已報到"
    " 42 已報到 43 未報到 44 未報到 46 未報到 47 未報到 48 未報到 50 未報到"
    " 51 已報到 52 未報到 53 已報到 54 已報到 55 未報到 56 已報到 57 未報到"
    " 58 已報到 68 已報到 70 已報到 71 未報到 72 已報到 73 未報到 74 已報到"
    " 75 已報到 76 未報到 77 已報到 78 已報到 79 未報到 81 未報到 83 已報到"
    " 84 初診"
)


def test_ophthalmology_clinic_open_with_patients_checked_in_but_none_called() -> None:
    # 眼科部 07診 at 13:50:31, twenty minutes after the 13:30 opening: no light,
    # no 已叫最大號, no 預計叫號, while many numbers already show 已報到.
    page = detail("detail_oph07_checked_in_not_called_2026-11-25_1350.html")

    assert (page.room, page.doctor) == ("眼科部 07診", "夏昀")
    assert page.current_light is None
    assert page.current_flag is None
    assert page.highest_called is None
    assert page.expected == ()
    assert page.numbers == numbers_as_shown(
        "2 已報到 3 已報到 4 已報到 5 未報到 6 未報到 7 未報到 8 已報到 11 未報到"
        " 15 已報到 16 未報到 17 已報到 18 未報到 19 未報到 20 已報到 21 已報到"
        " 22 已報到 23 未報到 24 未報到 25 已報到 26 已報到 27 已報到 28 已報到"
        " 29 未報到 30 未報到 31 已報到 32 已報到 33 已報到 34 已報到 35 已報到"
        " 36 已報到 37 已報到 38 未報到 39 未報到 40 已報到 41 已報到 42 未報到"
        " 43 未報到 44 未報到 45 已報到 46 未報到 47 未報到 48 未報到 49 已報到"
        " 50 未報到 51 未報到 52 未報到 53 未報到 54 已報到 55 未報到 56 未報到"
        " 57 未報到 58 已報到 59 已報到 60 已報到 68 已報到 69 已報到 70 已報到"
        " 71 未報到 72 已報到 73 未報到 74 未報到 75 已報到 76 未報到 77 已報到"
        " 78 未報到 79 未報到 81 未報到 82 已報到 83 未報到 84 初診 85 已報到"
    )


def test_ophthalmology_clinic_midway_2026_11_25() -> None:
    # 眼科部 07診 at 15:00:29: light 015 順號 at 已叫最大號 015, and 預計叫號
    # 016 (順號) 017 (順號).
    page = detail("detail_oph07_midway_2026-11-25_1500.html")

    assert (page.room, page.doctor) == ("眼科部 07診", "夏昀")
    assert page.current_light == 15
    assert page.current_flag == "sequential"
    assert page.highest_called == 15
    assert page.expected == (
        ExpectedCall(16, "sequential"),
        ExpectedCall(17, "sequential"),
    )
    assert page.numbers == numbers_as_shown(OPH07_MIDWAY_NUMBERS)


ORTH07_NUMBERS = (
    "2 未報到 3 未報到 4 未報到 5 未報到 6 未報到 7 未報到 8 報到20 10 報到21"
    " 12 未報到 15 報到26 16 未報到 18 報到30 19 看診中 20 報到25 21 未報到"
    " 22 未報到 23 未報到 25 未報到 26 未報到 27 報到28 31 未報到 33 報到11"
    " 36 未報到 37 未報到 38 未報到 39 未報到 40 未報到 41 未報到 42 報到31"
    " 43 報到32 46 報到29 47 未報到 48 未報到 49 未報到 50 未報到 51 報到18"
    " 52 未報到 53 未報到 54 未報到 58 未報到 59 未報到 60 未報到 68 未報到"
    " 71 未報到 72 未報到 74 未報到 76 未報到 77 未報到 78 未報到 79 未報到"
    " 80 未報到 81 未報到 82 報到24 83 未報到 84 未報到 85 未報到"
)


def test_orthopedics_check_in_order_clinic_just_after_it_opens_2026_11_25() -> None:
    # 骨科部 07診 at 13:50:24, titled 預計叫號 (依報到順序看診): light 019 with
    # 報到順序27 under it and a blank 已叫最大號. 預計叫號 is read in the test below.
    page = detail("detail_orth07_check_in_order_2026-11-25_1350.html")

    assert (page.room, page.doctor) == ("骨科部 07診", "王廷明")
    assert page.current_light == 19
    assert page.current_flag is None
    assert page.check_in_order is True
    assert page.check_in_position == 27
    assert page.highest_called is None
    assert page.numbers == numbers_as_shown(ORTH07_NUMBERS)


def test_orthopedics_untyped_expected_call_is_read_2026_11_25() -> None:
    # 預計叫號 shows a bare 027 with no type, so its kind is unknown.
    page = detail("detail_orth07_check_in_order_2026-11-25_1350.html")

    assert page.expected == (ExpectedCall(27, None),)


SURG05_DASHES_NUMBERS = (
    "2 未報到 3 未報到 4 已報到 5 已報到 8 已報到 9 未報到 10 未報到 14 未報到"
    " 15 未報到 18 未報到 19 未報到 20 未報到 22 未報到 23 已報到 24 未報到"
    " 25 初診 28 已報到 29 未報到 30 未報到 32 未報到 34 未報到 37 未報到"
    " 39 未報到 42 未報到"
)


def test_surgery_clinic_showing_dashes_for_its_light_2026_11_25() -> None:
    # 外科部 05診 at 13:50:35: no number under 目前燈號, ------ where its flag
    # goes, a blank 已叫最大號, and ------ under 預計叫號. ------ is no call type
    # and no number, so the page states no light, flag or expected call.
    page = detail("detail_surg05_dashes_2026-11-25_1350.html")

    assert (page.room, page.doctor) == ("外科部 05診", "黃書健")
    assert page.current_light is None
    assert page.current_flag is None
    assert page.highest_called is None
    assert page.check_in_order is False
    assert page.expected == ()
    assert page.numbers == numbers_as_shown(SURG05_DASHES_NUMBERS)


def test_surgery_clinic_calling_after_showing_dashes_2026_11_25() -> None:
    # 外科部 05診 at 15:00:33: light 014 順號, 已叫最大號 018, and 預計叫號
    # 014 (順號) 015 (順號) 018 (順號).
    page = detail("detail_surg05_midway_2026-11-25_1500.html")

    assert (page.room, page.doctor) == ("外科部 05診", "黃書健")
    assert page.current_light == 14
    assert page.current_flag == "sequential"
    assert page.highest_called == 18
    assert page.expected == (
        ExpectedCall(14, "sequential"),
        ExpectedCall(15, "sequential"),
        ExpectedCall(18, "sequential"),
    )
    assert page.numbers == numbers_as_shown(
        "2 未報到 3 未報到 5 已報到 9 未報到 14 看診中 15 未報到 18 已報到"
        " 20 未報到 22 已報到 23 已報到 24 未報到 25 初診 28 已報到 29 未報到"
        " 30 未報到 32 未報到 34 未報到 37 已報到 39 未報到 42 已報到"
    )


MED34 = "detail_med34_substitute_empty_2026-11-25_1500.html"


def test_substitute_clinic_with_no_numbers_2026_11_25() -> None:
    # 內科部 34診 at 15:00:20: the doctor shows as 總醫師(代), with no light, no
    # 已叫最大號, no 預計叫號 and an empty 所有燈號狀態. The doctor is read in
    # the test below.
    page = detail(MED34)

    assert page.room == "內科部 34診"
    assert page.current_light is None
    assert page.current_flag is None
    assert page.highest_called is None
    assert page.expected == ()
    assert page.numbers == ()


def test_substitute_mark_on_a_detail_page_is_read_2026_11_25() -> None:
    # The detail page puts (代) in a span inside doc-name; it reads as the list does.
    card = next(row for row in cards(list_page("med", "midway")) if row.room == "34 診")
    assert card.doctor == "總醫師(代)"

    assert detail(MED34).doctor == "總醫師(代)"


def test_each_afternoon_card_links_to_the_detail_page_showing_its_light() -> None:
    # Each list was captured seconds before the detail pages of its round.
    pairs = [
        ("neur", "before_open", "03 診", series_page("neur03", "before_open")),
        ("neur", "just_open", "03 診", series_page("neur03", "just_open")),
        ("neur", "midway", "03 診", series_page("neur03", "midway")),
        ("med", "before_open", "03 診", series_page("med03", "before_open")),
        ("med", "just_open", "03 診", series_page("med03", "just_open")),
        ("med", "midway", "03 診", series_page("med03", "midway")),
        ("neur", "midway", "05 診", "detail_neur05_passed_2026-11-25_1500.html"),
        (
            "oph",
            "midway",
            "05 診",
            "detail_oph05_passed_no_expected_2026-11-25_1500.html",
        ),
        (
            "oph",
            "just_open",
            "07 診",
            "detail_oph07_checked_in_not_called_2026-11-25_1350.html",
        ),
        ("oph", "midway", "07 診", "detail_oph07_midway_2026-11-25_1500.html"),
        ("oph", "midway", "11 診", "detail_oph11_exam_2026-11-25_1500.html"),
        (
            "orth",
            "just_open",
            "07 診",
            "detail_orth07_check_in_order_2026-11-25_1350.html",
        ),
        ("surg", "just_open", "05 診", "detail_surg05_dashes_2026-11-25_1350.html"),
        ("surg", "midway", "05 診", "detail_surg05_midway_2026-11-25_1500.html"),
    ]
    for department, round_, room, detail_page in pairs:
        card = next(
            row for row in cards(list_page(department, round_)) if row.room == room
        )
        assert f"ServiceIDSE={card.service_id}." in capture(detail_page).splitlines()[0]
        page = detail(detail_page)
        assert page.doctor == card.doctor
        assert page.current_light == (int(card.current) if card.current else None)


@pytest.mark.asyncio
async def test_reader_follows_an_afternoon_clinic_from_before_opening_to_midway() -> (
    None
):
    # 眼科 07診 夏昀 普通門診, afternoon of 2026-11-25 (the reader serves 眼科
    # only). Its card is blank on the 12:45 and 13:50 lists and shows 015 on the
    # 15:00 list; the next read takes the card's detail page captured at 15:00:29.
    source = TwoPageSource(
        capture(list_page("oph", "before_open")),
        capture("detail_oph07_checked_in_not_called_2026-11-25_1350.html"),
    )
    r = reader(source)
    clinic = ClinicScope(
        "ntuh-main",
        date(2026, 11, 25),
        "OPH",
        "07診/夏昀/普通門診",
        ClinicSession.AFTERNOON,
    )
    taipei = timezone(timedelta(hours=8))

    before = await r.observe_for_start(
        clinic, datetime(2026, 11, 25, 12, 45, tzinfo=taipei)
    )
    assert isinstance(before, ReadSkipped)
    assert before.reason == "clinic_not_started"
    posts = [request for request in source.requests if request.method == "POST"]
    sent = dict(parse_qsl(posts[0].body or ""))
    assert (sent["DeptCode"], sent["AmpmCode"]) == ("OPH", "2")

    source.listed = capture(list_page("oph", "just_open"))
    opened = await r.observe_for_start(
        clinic, datetime(2026, 11, 25, 13, 50, tzinfo=taipei)
    )
    assert isinstance(opened, ReadSkipped)
    assert opened.reason == "clinic_not_started"
    assert source.detail_urls == []

    source.listed = capture(list_page("oph", "midway"))
    source.detail = capture("detail_oph07_midway_2026-11-25_1500.html")
    found = await r.observe_for_start(
        clinic, datetime(2026, 11, 25, 15, 0, tzinfo=taipei)
    )
    assert isinstance(found, QueueObservation)
    assert found.current_number == 15
    assert source.detail_urls == []

    read = await r.observe(clinic, datetime(2026, 11, 25, 15, 2, tzinfo=taipei))

    assert [url.split("?")[1] for url in source.detail_urls] == [
        "ServiceIDSE=8148285&vHospitalCode=T0"
    ]
    assert isinstance(read, QueueObservation)
    # The page: light 015 順號, 已叫最大號 015, 預計叫號 016 (順號) 017 (順號).
    assert read.current_number == 15
    assert read.current_flag == "sequential"
    assert read.highest_called_number == 15
    assert read.check_in_order is False
    assert read.substitute_doctor is False
    assert read.expected == (
        ExpectedCall(16, "sequential"),
        ExpectedCall(17, "sequential"),
    )
    assert read.numbers == numbers_as_shown(OPH07_MIDWAY_NUMBERS)
