"""How the NTUH clinic detail page parser fails and what it ignores.

What it reads off real pages is replayed in `test_ntuh_capture_replay.py` (#205).
These tests alter a real capture (ADR 0006) to show what the parser does with a
page the hospital has not served yet. Nothing in this file reaches the network.
"""

from __future__ import annotations

import re

import pytest

from next_is_you.ntuh_detail import ProgressObservation, parse_detail_page
from test_ntuh_capture_replay import capture

# 骨科部 02診 at 10:30:17 on 2026-11-23, with a 初診 number.
PAGE = capture("detail_orth02_2026-11-23_1030.html")
# 骨科部 03診 at 10:15:24 on 2026-11-25: light 019 敬老號, 已叫最大號 009.
SENIOR_PAGE = capture("detail_orth03_senior_2026-11-25_1015.html")
# 內科部 03診 at 10:15 on 2026-11-25: 預計叫號 is a bare 017 with no type.
BARE_EXPECTED_PAGE = capture("detail_med03_2026-11-25_1015.html")
_BARE_EXPECTED = re.compile(r'(預計叫號\s*</div>\s*<div class="number">\s*)017')
_LIGHT = re.compile(r'(目前燈號</div>\s*<div class="number">\s*)019')
_HIGHEST = re.compile(r'(已叫最大號</div>\s*<div class="number">\s*)009')


def _observation(html: str) -> ProgressObservation:
    status, observation = parse_detail_page(html)
    assert status == "ok"
    assert observation is not None
    return observation


def test_render_time_is_not_part_of_the_observation() -> None:
    # Freshness is the reader's fetch time; the page's own time never counts.
    later_page = PAGE.replace(
        "最後更新時間:2026-11-23 10:30:17", "最後更新時間:2026-11-23 10:31:17"
    )
    assert later_page != PAGE
    first = _observation(PAGE)
    later = _observation(later_page)

    assert first == later


def test_unknown_number_tag_fails_the_page_instead_of_guessing() -> None:
    html = PAGE.replace('<div class="first-tag">', '<div class="mystery-tag">', 1)
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
    stray = (
        '<div class="progress-number">099<span class="checkIn-tag">已報到</span></div>'
    )
    # After the legend, outside the region the parser reads (#170).
    outside = PAGE.replace("</body>", stray + "</body>")
    assert outside != PAGE

    assert _observation(outside) == _observation(PAGE)


def test_page_without_the_region_wrapper_is_still_read_in_full() -> None:
    unwrapped = PAGE.replace('class="clinic-modal-progress"', 'class="other"')
    assert unwrapped != PAGE

    assert _observation(unwrapped) == _observation(PAGE)


@pytest.mark.parametrize(
    "shown", ["abc", "000", "9" * 7, "9" * 5000, "\u00b2", "1\u00b2"]
)
def test_a_garbled_current_light_is_invalid(shown: str) -> None:
    html, replaced = _LIGHT.subn(rf"\g<1>{shown}", SENIOR_PAGE)
    assert replaced == 1

    assert parse_detail_page(html) == ("invalid", None)


@pytest.mark.parametrize("shown", ["abc", "000", "9" * 7])
def test_a_garbled_highest_called_is_invalid(shown: str) -> None:
    html, replaced = _HIGHEST.subn(rf"\g<1>{shown}", SENIOR_PAGE)
    assert replaced == 1

    assert parse_detail_page(html) == ("invalid", None)


def test_a_real_page_without_the_number_list_is_a_schema_failure() -> None:
    html = SENIOR_PAGE.replace('class="clinic-progress"', 'class="other"')
    assert html != SENIOR_PAGE

    assert parse_detail_page(html) == ("schema", None)


@pytest.mark.parametrize(
    ("text", "status"),
    [("請完成驗證 captcha", "challenge"), ("Access Denied", "denied")],
)
def test_a_real_page_showing_a_challenge_instead_of_progress_is_named(
    text: str, status: str
) -> None:
    # The hospital's page frame with the progress panel replaced by a message.
    start = SENIOR_PAGE.index('<div class="clinic-modal-progress">')
    end = SENIOR_PAGE.index('class="number-explain"')
    html = SENIOR_PAGE[:start] + f"<p>{text}</p><div " + SENIOR_PAGE[end:]

    assert parse_detail_page(html) == (status, None)


@pytest.mark.parametrize("shown", ["", "\u3000", "000", "(無)"])
def test_a_bare_expected_placeholder_is_no_expected_call(shown: str) -> None:
    html, replaced = _BARE_EXPECTED.subn(rf"\g<1>{shown}", BARE_EXPECTED_PAGE)
    assert replaced == 1

    assert _observation(html).expected == ()
