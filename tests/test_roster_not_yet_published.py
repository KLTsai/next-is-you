"""The clinic schedule answer for a day the hospital has not published yet.

Seam: the send gate's public `list_clinics`, with the real registry and a fake
hospital transport. Evidence is fixture/mock: nothing here contacts a hospital.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from next_is_you import hospital_registry
from next_is_you.domain import ClinicRoster, Hospital
from next_is_you.hospital_registry import HospitalEntry
from test_ntuh_reader import DAY, FakeSource, gate_with_visit, taipei


@pytest.mark.asyncio
async def test_ntuh_day_past_its_end_date_returns_end_date_and_release_time() -> None:
    source = FakeSource()
    _, gate = await gate_with_visit(source)
    visit_day = DAY + timedelta(days=20)
    result = await gate.list_clinics(
        "ntuh-main", "OPH", visit_day.isoformat(), taipei(14, 0).isoformat()
    )
    assert result == {
        "available": False,
        "reason": "visit_date_out_of_schedule_window",
        # Today (10/22) plus 14 days.
        "schedule_end_date": "2026-11-05",
        # 14 days before 11/11, at midnight Taipei time.
        "release_time": "2026-10-28T00:00:00+08:00",
        "clinics": [],
    }
    assert source.requests == []


@pytest.mark.asyncio
async def test_ntuh_day_on_the_end_date_is_still_read_not_refused() -> None:
    source = FakeSource()
    _, gate = await gate_with_visit(source)
    result = await gate.list_clinics(
        "ntuh-main",
        "OPH",
        (DAY + timedelta(days=14)).isoformat(),
        taipei(14, 0).isoformat(),
    )
    assert result["reason"] != "visit_date_out_of_schedule_window"
    assert result["release_time"] is None


class _NoReleaseTimeReader:
    """A full-schedule reader whose hospital states no release time."""

    def __init__(self, storage=None, fetch=None) -> None:
        pass

    async def observe(self, scope, now):
        return None

    async def observe_for_start(self, scope, now):
        return None

    async def list_clinics(self, query, now):
        return ClinicRoster(
            False,
            (),
            "visit_date_out_of_schedule_window",
            schedule_end_date=date(2026, 12, 1),
        )


@pytest.mark.asyncio
async def test_hospital_stating_no_release_time_returns_end_date_only(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        hospital_registry,
        "HOSPITAL_REGISTRY",
        {Hospital.NTUH_MAIN: HospitalEntry("Synthetic", _NoReleaseTimeReader)},
    )
    _, gate = await gate_with_visit(FakeSource())
    result = await gate.list_clinics(
        "ntuh-main", "OPH", "2026-12-05", taipei(14, 0).isoformat()
    )
    assert result["schedule_end_date"] == "2026-12-01"
    assert result["release_time"] is None
    assert result["clinics"] == []
