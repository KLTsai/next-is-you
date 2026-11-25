"""What the NTUH readers return, for visit and reminder tests (#205, ADR 0006).

Visit and reminder logic is tested on the values a reader returns, not on HTML:
a clinic list is `ListRow`s, a detail page is a `ProgressObservation`, and a
clinic schedule is `ScheduleRow`s. A fake source serves such a value with
`served(value)`, and while a test runs, the readers in `next_is_you.ntuh_reader`
return it for that body instead of parsing. A module whose tests serve values
turns this on with
`pytestmark = pytest.mark.usefixtures("serve_reader_values")`. A body that is not `served` is parsed as usual, so
a real capture still goes through the real reader.

How the hospital's pages read is tested on real captures, in
`test_ntuh_capture_replay.py`. Every clinic, doctor and number here is invented.
Fixture/mock only.
"""

from __future__ import annotations

import itertools
from collections.abc import Callable, Iterator
from dataclasses import dataclass, replace
from datetime import date
from typing import Any

import pytest

import next_is_you.ntuh_reader as ntuh_reader
from next_is_you.domain import (
    CallKind,
    ClinicSession,
    ExpectedCall,
    NumberState,
    NumberStatus,
)
from next_is_you.ntuh_detail import ProgressObservation
from next_is_you.ntuh_reader import ListRow, ScheduleRow


@dataclass(frozen=True, slots=True)
class ListRead:
    """What `parse_light_table` returns for one session list."""

    status: str = "ok"
    rows: tuple[ListRow, ...] = ()


@dataclass(frozen=True, slots=True)
class DetailRead:
    """What `parse_detail_page` returns for one detail page."""

    status: str = "ok"
    progress: ProgressObservation | None = None


@dataclass(frozen=True, slots=True)
class ScheduleRead:
    """What `parse_schedule` returns for one department schedule."""

    status: str = "ok"
    rows: tuple[ScheduleRow, ...] = ()


def listing(*rows: ListRow, status: str = "ok") -> ListRead:
    return ListRead(status, rows)


def with_rows(read: ListRead, match: Callable[[ListRow], bool], **changes) -> ListRead:
    """`read` with `changes` made to every card `match` accepts."""
    return ListRead(
        read.status,
        tuple(replace(row, **changes) if match(row) else row for row in read.rows),
    )


def plus(read: ListRead, *rows: ListRow) -> ListRead:
    """`read` with `rows` listed after its cards."""
    return ListRead(read.status, (*read.rows, *rows))


def of_doctor(doctor: str) -> Callable[[ListRow], bool]:
    """Matches the cards of `doctor`."""
    return lambda row: row.doctor == doctor


def card(
    room: str,
    doctor: str,
    clinic_type: str,
    current: str = "",
    *,
    check_in_order: str = "",
    service_id: str | None = None,
) -> ListRow:
    """One clinic card. Every card links to its detail page, one ID per card."""
    if service_id is None:
        service_id = str(9_000_000 + sum(ord(c) for c in room + doctor + clinic_type))
    return ListRow(room, doctor, clinic_type, current, check_in_order, service_id)


def progress(
    *,
    room: str = "合成科 11診",
    doctor: str = "合成醫師丙",
    current: int | None = None,
    flag: CallKind | None = None,
    highest: int | None = None,
    check_in_order: bool = False,
    check_in_position: int | None = None,
    expected: tuple[tuple[int, CallKind | None], ...] = (),
    numbers: tuple[tuple[int, NumberState] | tuple[int, NumberState, int], ...] = (),
) -> ProgressObservation:
    """A clinic's detail page as the reader returns it.

    `numbers` holds `(number, state)` or `(number, "checked_in", 報到N)`.
    """
    return ProgressObservation(
        room=room,
        doctor=doctor,
        current_light=current,
        current_flag=flag,
        highest_called=highest,
        check_in_order=check_in_order,
        check_in_position=check_in_position,
        expected=tuple(ExpectedCall(number, kind) for number, kind in expected),
        numbers=tuple(_number_status(item) for item in numbers),
    )


def _number_status(
    item: tuple[int, NumberState] | tuple[int, NumberState, int],
) -> NumberStatus:
    if len(item) == 3:
        number, state, check_in_position = item
        return NumberStatus(number, state, check_in_position)
    number, state = item
    return NumberStatus(number, state, None)


def schedule(*rows: ScheduleRow, status: str = "ok") -> ScheduleRead:
    return ScheduleRead(status, rows)


def slot(
    visit_date: date,
    session: ClinicSession,
    room: str,
    doctor: str,
    clinic_type: str = "",
    status: str = "",
    department: str = "",
) -> ScheduleRow:
    """One clinic the department schedule publishes."""
    return ScheduleRow(
        visit_date, session, room, doctor, clinic_type, status, department
    )


_SERVED: dict[str, Any] = {}
_KEYS = itertools.count(1)
_PREFIX = "<!-- reader value "


def served(value: Any) -> str:
    """A response body for which the readers return `value`.

    A bare `ProgressObservation` is an "ok" detail read.
    """
    if isinstance(value, ProgressObservation):
        value = DetailRead("ok", value)
    if not isinstance(value, ListRead | DetailRead | ScheduleRead):
        raise TypeError(f"not a reader value: {value!r}")
    key = f"{_PREFIX}{next(_KEYS)} -->"
    _SERVED[key] = value
    return key


def _value(body: str, kind: type) -> Any:
    if not body.startswith(_PREFIX):
        return None
    value = _SERVED[body]
    assert isinstance(value, kind), f"a {kind.__name__} was read, {value!r} served"
    return value


@pytest.fixture
def serve_reader_values(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    real_list = ntuh_reader.parse_light_table
    real_detail = ntuh_reader.parse_detail_page
    real_schedule = ntuh_reader.parse_schedule

    def light_table(html: str) -> tuple[str, list[ListRow]]:
        value = _value(html, ListRead)
        return real_list(html) if value is None else (value.status, list(value.rows))

    def detail(html: str) -> tuple[str, ProgressObservation | None]:
        value = _value(html, DetailRead)
        return real_detail(html) if value is None else (value.status, value.progress)

    def dept_schedule(html: str, today: date) -> tuple[str, list[ScheduleRow]]:
        value = _value(html, ScheduleRead)
        if value is None:
            return real_schedule(html, today)
        return value.status, list(value.rows)

    monkeypatch.setattr(ntuh_reader, "parse_light_table", light_table)
    monkeypatch.setattr(ntuh_reader, "parse_detail_page", detail)
    monkeypatch.setattr(ntuh_reader, "parse_schedule", dept_schedule)
    yield
    _SERVED.clear()
