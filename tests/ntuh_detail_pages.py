"""Synthetic NTUH detail pages for reader tests (#163).

`detail_page` builds the panel of a clinic's `ClinicCurrentLightNoDetail` page
with the progress fields the real page shows: the current light with its flag,
the highest called, the expected calls and the status of every number on the
list. Every clinic, doctor and number is invented. Fixture/mock only.
"""

from __future__ import annotations

_TAG_CLASSES = {
    "not_checked_in": ("not-checkIn-tag", "未報到"),
    "first_visit": ("first-tag", "初診"),
    "checked_in": ("checkIn-tag", "已報到"),
    "in_consultation": ("onCall-tag", "看診中"),
}
_FLAG_TEXT = {
    "passed": "過號",
    "exam": "檢查號",
    "senior": "敬老號",
    "sequential": "順號",
}


def detail_page(
    *,
    room: str = "合成科 11診",
    doctor: str = "合成醫師丙",
    current: int | None = None,
    flag: str | None = None,
    highest: int | None = None,
    check_in_order: bool = False,
    check_in_position: int | None = None,
    expected: tuple[tuple[int, str], ...] = (),
    numbers: tuple[tuple[int, str] | tuple[int, str, int], ...] = (),
) -> str:
    """The detail page of a clinic. `None` renders the page's own blank (000)."""
    light = f"{current:03d}" if current is not None else "000"
    flag_text = (
        f"報到順序{check_in_position:02d}"
        if check_in_position is not None
        else _FLAG_TEXT.get(flag or "", "")
    )
    note = "依報到順序看診" if check_in_order else ""
    highest_text = f"{highest:03d}" if highest is not None else ""
    expected_html = "".join(
        f'<span class="expected-item"><span class="number">{number:03d}</span>'
        f'<span class="type">({kind})</span></span>'
        for number, kind in expected
    )
    rows = []
    for item in numbers:
        number, state = item[0], item[1]
        css, text = _TAG_CLASSES[state]
        if len(item) == 3:
            text = f"報到{item[2]}"
        rows.append(
            f'<div class="col-4"><div class="progress-number">{number}'
            f'<div class="{css}">{text}</div></div></div>'
        )
    return f"""<!DOCTYPE html><html lang="zh-TW"><body><div id="main">
<div class="clinic-modal-progress"><div class="row g-2">
<div class="room-number">{room}</div><div class="doc-name">{doctor}</div>
<div class="now-number"><div class="title">目前燈號</div>
<div class="number">{light}</div>
<div class="according-to-order-inside"><text>{flag_text}</text></div></div>
<div class="biggest-number"><div class="title">已叫最大號</div>
<div class="number">{highest_text}</div></div>
<div class="next-number"><div class="title">預計叫號 {note}</div>
<div class="expected-inline">{expected_html}</div></div>
</div>
<div class="clinic-progress"><div class="title">所有燈號狀態</div>
<div class="row">{"".join(rows)}</div></div></div>
<div class="number-explain">legend</div></div></body></html>"""
