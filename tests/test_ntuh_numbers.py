"""How the NTUH detail page parser turns a shown number into a number.

The detail page usually pads a light to three digits ("008"), but a light shown
unpadded ("8") is the same number (#205 decision 6). This case is covered here,
on the normalizer, rather than by a hand-built page.
"""

from __future__ import annotations

import pytest

from next_is_you.ntuh_detail import MAX_NUMBER_DIGITS, _number


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        pytest.param("008", 8, id="padded"),
        pytest.param("8", 8, id="unpadded"),
        pytest.param("123", 123, id="three-digits"),
        pytest.param(" 008 ", 8, id="surrounding-space"),
        pytest.param(
            "9" * MAX_NUMBER_DIGITS, int("9" * MAX_NUMBER_DIGITS), id="max-digits"
        ),
    ],
)
def test_shown_number_is_read_as_its_value(text: str, expected: int) -> None:
    assert _number(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("　", id="blank-ideographic-space"),
        pytest.param("", id="empty"),
        pytest.param("000", id="zero"),
        pytest.param("1" * (MAX_NUMBER_DIGITS + 1), id="too-many-digits"),
    ],
)
def test_text_that_is_not_a_positive_number_is_none(text: str) -> None:
    assert _number(text) is None
