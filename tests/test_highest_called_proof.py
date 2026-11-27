"""The page-proven highest called rule (#248, ADR 0003). Fixture/mock only."""

from __future__ import annotations

import pytest

from next_is_you.domain import NumberState, NumberStatus, proven_highest_called


@pytest.mark.parametrize(
    "numbers",
    [
        pytest.param((NumberStatus(16, "in_consultation"),), id="being-seen"),
        pytest.param((NumberStatus(18, "checked_in"),), id="not-listed"),
        pytest.param((), id="none-left"),
    ],
)
def test_a_number_the_list_proves_was_called_is_highest_called(
    numbers: tuple[NumberStatus, ...],
) -> None:
    assert proven_highest_called(16, numbers) == 16


@pytest.mark.parametrize("state", ["not_checked_in", "first_visit", "checked_in"])
def test_a_waiting_number_is_not_highest_called(state: NumberState) -> None:
    assert proven_highest_called(16, (NumberStatus(16, state),)) is None


def test_a_source_that_lists_no_numbers_proves_nothing() -> None:
    assert proven_highest_called(16, None) is None


def test_no_labelled_number_is_no_highest_called() -> None:
    assert proven_highest_called(None, ()) is None
