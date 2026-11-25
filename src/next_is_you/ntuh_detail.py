"""Parser for NTUH's per-clinic detail page (`ClinicCurrentLightNoDetail`).

The page states the current light with a flag, 已叫最大號, 預計叫號 (with a type
for each entry, or as one bare number with none), and the status of every
number still on the list
(`docs/NTUH-READER.md`, `docs/adr/0003-hospital-neutral-progress-model.md`).
`parse_detail_page` turns it into a `ProgressObservation` that holds only what
the page states. A field the page does not show is `None` or empty, never
estimated, and the page's own render time is never read: freshness is the time
the reader fetched it.

This module is only the pure parser. Fetching the page and wiring it into the
scheduler belong to the reader that calls it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser

from next_is_you.domain import CallKind, ExpectedCall, NumberState, NumberStatus
from next_is_you.page_markers import page_status

__all__ = [
    "MAX_NUMBER_DIGITS",
    "CallKind",
    "ExpectedCall",
    "NumberState",
    "NumberStatus",
    "ProgressObservation",
    "parse_detail_page",
]

_VOID_ELEMENTS = frozenset(
    "area base br col embed hr img input link meta param source track wbr".split()
)

# Tag classes on a number in the list of every number's status.
_TAG_STATES: dict[str, NumberState] = {
    "not-checkIn-tag": "not_checked_in",
    "first-tag": "first_visit",
    "checkIn-tag": "checked_in",
    "onCall-tag": "in_consultation",
}

# The flag under the current light and the type after each expected number.
_KINDS: dict[str, CallKind] = {
    "順號": "sequential",
    "過號": "passed",
    "檢查號": "exam",
    "敬老號": "senior",
}

_DIGITS = re.compile(r"\d+", re.ASCII)
# Longer than any clinic number. A longer run of digits is not a number.
MAX_NUMBER_DIGITS = 6
# The region the parser reads, from the progress panel up to the legend after
# the number list (#170). Everything else on the page is skipped unparsed.
_REGION_START = re.compile(r'<[^<>]*class="[^"]*\bclinic-modal-progress\b')
_REGION_END = re.compile(r'<[^<>]*class="[^"]*\bnumber-explain\b')
_CHECK_IN_POSITION = re.compile(r"^報到(?:順序)?\s*(\d+)$")
_CHECK_IN_ORDER_NOTE = "依報到順序看診"


@dataclass(frozen=True, slots=True)
class ProgressObservation:
    room: str
    doctor: str
    current_light: int | None
    # The flag under the current light: 順號, 過號, 檢查號 or 敬老號. Absent when
    # the page shows none, and for a check-in-order clinic's 報到順序NN, which is
    # `check_in_position`.
    current_flag: CallKind | None
    highest_called: int | None
    # The clinic calls by check-in order (依報到順序看診): there is no highest called.
    check_in_order: bool
    # The clinic's current 報到順序, only while the flag shows it.
    check_in_position: int | None
    expected: tuple[ExpectedCall, ...]
    numbers: tuple[NumberStatus, ...]


def _number(text: str) -> int | None:
    """A positive number from padded, unpadded or blank (U+3000) text, else None."""
    match = _DIGITS.search(text)
    if match is None or len(match.group()) > MAX_NUMBER_DIGITS:
        return None
    value = int(match.group())
    return value if value > 0 else None


def _is_garbled(text: str) -> bool:
    """A light that is neither blank nor a positive number, such as 000 or abc."""
    text = text.strip()
    return bool(text) and (_DIGITS.fullmatch(text) is None or _number(text) is None)


class _DetailCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.text: list[str] = []
        self.has_progress_list = False
        self.room = ""
        self.doctor = ""
        self.light = ""
        self.flag = ""
        self.highest = ""
        self.title = ""
        self.expected: list[list[str]] = []
        # 預計叫號 shown as a bare number, outside any expected-item.
        self.bare_expected = ""
        self.numbers: list[dict[str, str]] = []
        self.unknown_tag = False
        self._stack: list[tuple[str, frozenset[str]]] = []

    def _inside(self, css: str) -> bool:
        return any(css in classes for _, classes in self._stack)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _VOID_ELEMENTS:
            return
        classes = frozenset(
            next((v.split() for k, v in attrs if k == "class" and v), [])
        )
        if "clinic-progress" in classes:
            self.has_progress_list = True
        if "expected-item" in classes:
            self.expected.append(["", ""])
        if "progress-number" in classes:
            self.numbers.append({"number": "", "tag": "", "tag_class": ""})
        if self._inside("progress-number"):
            tag_class = next((c for c in classes if c.endswith("-tag")), "")
            if tag_class:
                self.numbers[-1]["tag_class"] = tag_class
        self._stack.append((tag, classes))

    def handle_endtag(self, tag: str) -> None:
        if tag in _VOID_ELEMENTS:
            return
        while self._stack:
            popped, _ = self._stack.pop()
            if popped == tag:
                return

    def handle_data(self, data: str) -> None:
        self.text.append(data)
        if not self._stack:
            return
        classes = self._stack[-1][1]
        if "room-number" in classes:
            self.room += data
        elif self._inside("doc-name"):
            # Includes a substitute's (代), which sits in a span inside doc-name.
            self.doctor += data
        elif self._inside("now-number"):
            if self._inside("according-to-order-inside"):
                self.flag += data
            elif "number" in classes:
                self.light += data
        elif self._inside("biggest-number") and "number" in classes:
            self.highest += data
        elif self._inside("expected-item"):
            if "number" in classes:
                self.expected[-1][0] += data
            elif "type" in classes:
                self.expected[-1][1] += data
        elif self._inside("next-number") and "title" in classes:
            self.title += data
        elif self._inside("next-number") and "number" in classes:
            self.bare_expected += data
        elif self._inside("progress-number"):
            entry = self.numbers[-1]
            if entry["tag_class"]:
                entry["tag"] += data
            else:
                entry["number"] += data


def _kind(text: str) -> CallKind | None:
    return _KINDS.get(text.strip().strip("()（）").strip())


def _progress_region(html: str) -> str:
    """The progress panel, or the whole page when it has none.

    Without the panel (a challenge, a denial, a changed layout) the full page is
    read, so those still fail the way they always did.
    """
    start = _REGION_START.search(html)
    if start is None:
        return html
    end = _REGION_END.search(html, start.end())
    return html[start.start() : end.start() if end else len(html)]


def parse_detail_page(html: str) -> tuple[str, ProgressObservation | None]:
    """Return ("ok", observation) or a page-level failure.

    Failures are `challenge`, `denied`, `schema` and `invalid` (the current light
    or the highest called is not a number). A page whose number list is
    empty is a valid observation with no numbers. A number carrying a tag this
    parser does not know fails the page, because skipping it would make the
    number look like it left the list.
    """
    collector = _DetailCollector()
    try:
        collector.feed(_progress_region(html))
        collector.close()
    except (ValueError, AssertionError):
        return "schema", None
    marker = page_status(" ".join(collector.text).casefold())
    if marker is not None:
        return marker, None
    room = collector.room.strip()
    doctor = collector.doctor.strip()
    if not collector.has_progress_list or not room or not doctor:
        return "schema", None

    if _is_garbled(collector.light) or _is_garbled(collector.highest):
        return "invalid", None

    numbers: list[NumberStatus] = []
    for entry in collector.numbers:
        number = _number(entry["number"])
        state = _TAG_STATES.get(entry["tag_class"])
        if number is None or state is None:
            return "schema", None
        position = _CHECK_IN_POSITION.match(entry["tag"].strip())
        numbers.append(
            NumberStatus(number, state, int(position.group(1)) if position else None)
        )

    flag = collector.flag.strip()
    flag_position = _CHECK_IN_POSITION.match(flag)
    expected: list[ExpectedCall] = []
    for raw_number, raw_type in collector.expected:
        number = _number(raw_number)
        if number is None:
            continue
        type_text = raw_type.strip().strip("()（）").strip()
        position = _CHECK_IN_POSITION.match(type_text)
        if position:
            expected.append(ExpectedCall(number, "check_in", int(position.group(1))))
        else:
            expected.append(ExpectedCall(number, _kind(type_text)))
    bare_number = _number(collector.bare_expected)
    if not expected and bare_number is not None:
        # The page gives no type for a bare number, so its kind is unknown.
        expected.append(ExpectedCall(bare_number, None))

    return "ok", ProgressObservation(
        room=room,
        doctor=doctor,
        current_light=_number(collector.light),
        current_flag=_kind(flag),
        highest_called=_number(collector.highest),
        check_in_order=_CHECK_IN_ORDER_NOTE in collector.title
        or flag_position is not None,
        check_in_position=int(flag_position.group(1)) if flag_position else None,
        expected=tuple(expected),
        numbers=tuple(numbers),
    )
