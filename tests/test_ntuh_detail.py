"""NTUH clinic detail page parser against synthetic fixtures only.

The fixtures rebuild the shapes seen on 2026-11-20 with invented clinics,
doctors (合成醫師) and numbers. The raw captures stay private and are never read
here. Nothing in this file reaches the network.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from next_is_you.ntuh_detail import (
    ExpectedCall,
    NumberStatus,
    ProgressObservation,
    parse_detail_page,
)

FIXTURES = Path(__file__).parent / "fixtures" / "hospitals"


def _page(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _observation(html: str) -> ProgressObservation:
    status, observation = parse_detail_page(html)
    assert status == "ok"
    assert observation is not None
    return observation


def test_number_order_page_reads_every_field_the_page_states() -> None:
    observation = _observation(_page("ntuh_detail_number_order.html"))

    assert observation.room == "合成科 91診"
    assert observation.doctor == "合成醫師甲"
    assert observation.current_light == 7
    assert observation.current_flag == "passed"
    assert observation.highest_called == 12
    assert observation.check_in_order is False
    assert observation.check_in_position is None
    assert observation.numbers == (
        NumberStatus(2, "not_checked_in"),
        NumberStatus(3, "checked_in"),
        NumberStatus(5, "first_visit"),
        NumberStatus(7, "in_consultation"),
        NumberStatus(9, "checked_in"),
        NumberStatus(11, "not_checked_in"),
        NumberStatus(12, "checked_in"),
        NumberStatus(14, "first_visit"),
        NumberStatus(15, "not_checked_in"),
    )


def test_expected_calls_the_page_marks_as_none_are_absent() -> None:
    # Both slots read 000 with type (無): the page lists no expected call, so the
    # observation holds none rather than two calls to number 0.
    observation = _observation(_page("ntuh_detail_number_order.html"))

    assert observation.expected == ()


def test_check_in_order_page_has_positions_and_no_highest_called() -> None:
    observation = _observation(_page("ntuh_detail_check_in_order.html"))

    assert observation.check_in_order is True
    # The highest called holds only U+3000 on this page: not shown, so absent.
    assert observation.highest_called is None
    assert observation.current_light == 4
    assert observation.current_flag is None
    assert observation.check_in_position == 3
    assert observation.expected == (
        ExpectedCall(4, "check_in", 3),
        ExpectedCall(6, "check_in", 4),
    )
    assert observation.numbers == (
        NumberStatus(2, "not_checked_in"),
        NumberStatus(6, "checked_in", 4),
        NumberStatus(8, "checked_in", 5),
        NumberStatus(10, "checked_in", 6),
        NumberStatus(13, "not_checked_in"),
    )


def test_exam_flag_and_expected_call_kinds() -> None:
    observation = _observation(_page("ntuh_detail_exam_senior.html"))

    assert observation.current_flag == "exam"
    # Unpadded numbers read the same as zero padded ones.
    assert observation.current_light == 21
    assert observation.highest_called == 26
    assert observation.expected == (
        ExpectedCall(21, "exam"),
        ExpectedCall(17, "passed"),
        ExpectedCall(30, "senior"),
    )


def test_senior_flag_on_the_current_light() -> None:
    html = _page("ntuh_detail_exam_senior.html").replace(
        "<text>檢查號</text>", "<text>敬老號</text>"
    )

    assert _observation(html).current_flag == "senior"


def test_sequential_flag_is_named() -> None:
    html = _page("ntuh_detail_exam_senior.html").replace(
        "<text>檢查號</text>", "<text>順號</text>"
    )

    assert _observation(html).current_flag == "sequential"


def test_check_in_order_flag_with_a_senior_light_keeps_the_position_absent() -> None:
    # A 敬老號 shown in place of 報到順序NN says nothing about the position. The
    # parser never fills it in; keeping the last known one is the rule's job.
    html = _page("ntuh_detail_check_in_order.html").replace(
        "<text>報到順序03</text>", "<text>敬老號</text>"
    )
    observation = _observation(html)

    assert observation.check_in_order is True
    assert observation.current_flag == "senior"
    assert observation.check_in_position is None


def test_page_with_no_numbers_is_a_valid_empty_observation() -> None:
    observation = _observation(_page("ntuh_detail_no_numbers.html"))

    assert observation.room == "合成科 94診"
    assert observation.numbers == ()
    assert observation.expected == ()
    assert observation.current_light is None
    assert observation.highest_called is None
    assert observation.current_flag is None


def test_render_time_is_not_part_of_the_observation() -> None:
    # Freshness is the reader's fetch time; the page's own time never counts.
    first = _observation(_page("ntuh_detail_number_order.html"))
    later = _observation(
        _page("ntuh_detail_number_order.html").replace(
            "2026-11-20 09:44:54", "2026-11-20 09:45:54"
        )
    )

    assert first == later


def test_unknown_number_tag_fails_the_page_instead_of_guessing() -> None:
    html = _page("ntuh_detail_number_order.html").replace(
        '<div class="first-tag">\n                                                                初診',
        '<div class="mystery-tag">\n                                                                未知狀態',
        1,
    )
    assert "mystery-tag" in html

    assert parse_detail_page(html) == ("schema", None)


@pytest.mark.parametrize(
    "html",
    ["", "<html><body>hello</body></html>", "<div class='clinic-modal-progress'>"],
)
def test_page_without_the_progress_list_is_a_schema_failure(html: str) -> None:
    assert parse_detail_page(html) == ("schema", None)


@pytest.mark.parametrize(
    ("body", "status"),
    [("Please solve the captcha", "challenge"), ("Access Denied", "denied")],
)
def test_challenge_and_denial_pages_are_named(body: str, status: str) -> None:
    assert parse_detail_page(f"<html><body>{body}</body></html>") == (status, None)


def test_markup_outside_the_progress_region_is_not_read() -> None:
    page = _page("ntuh_detail_number_order.html")
    stray = (
        '<div class="progress-number">099<span class="checkIn-tag">已報到</span></div>'
    )
    # After the legend, outside the region the parser reads (#170).
    outside = page.replace("</body>", stray + "</body>")

    assert _observation(outside) == _observation(page)


def test_page_without_the_region_wrapper_is_still_read_in_full() -> None:
    page = _page("ntuh_detail_number_order.html")
    unwrapped = page.replace('class="clinic-modal-progress"', 'class="other"')

    assert _observation(unwrapped) == _observation(page)
