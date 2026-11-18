"""A synthetic hospital that publishes only the current number (#104).

Fixture/mock only. It is labelled "合成醫院（僅供測試）" and is not evidence
that any real hospital is supported. It has an id of its own, which the database
stores because it no longer enumerates hospitals (#95). Tests substitute it into
the registry for the duration of one test and never ship it.

Its reader has no `list_clinics`, so the registry derives it as current number
only. Its transport is a scripted fake: the scripted `fetch` returns the clinic's
current number, `None` when the hospital cannot find the clinic, or raises
`TimeoutError` when the page is unreachable.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Awaitable, Callable

from next_is_you.domain import (
    ClinicScope,
    QueueObservation,
    ReadFailed,
    ReadSkipped,
    SupportedDepartment,
)
from next_is_you.hospital_registry import HospitalEntry

SYNTHETIC_ID = "synthetic-current-number-only"
SYNTHETIC_NAME = "合成醫院（僅供測試）"
SYNTHETIC_LINK = "https://synthetic-hospital.example/progress"

Result = QueueObservation | ReadSkipped | ReadFailed | None


class SyntheticSource:
    """Scripted transport; `requests` records every clinic read it served."""

    def __init__(self, outcome: int | None | Exception = 7) -> None:
        self.outcome = outcome
        self.requests: list[str] = []

    async def __call__(self, clinic_code: str) -> int | None:
        self.requests.append(clinic_code)
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


class SyntheticCurrentNumberReader:
    def __init__(
        self, storage: Any, fetch: Callable[[str], Awaitable[int | None]]
    ) -> None:
        self._fetch = fetch

    async def observe(self, scope: ClinicScope, now: datetime) -> Result:
        return await self._read(scope, now)

    async def observe_for_start(self, scope: ClinicScope, now: datetime) -> Result:
        return await self._read(scope, now)

    async def _read(self, scope: ClinicScope, now: datetime) -> Result:
        try:
            number = await self._fetch(scope.clinic_code)
        except TimeoutError:
            return ReadFailed("unavailable", "timeout")
        if number is None:
            return ReadFailed("unavailable", "empty_result")
        return QueueObservation(
            scope, now.isoformat(), number, trustworthy_current=True
        )


def synthetic_entry() -> HospitalEntry:
    return HospitalEntry(
        display_name=SYNTHETIC_NAME,
        reader_type=SyntheticCurrentNumberReader,
        official_link=SYNTHETIC_LINK,
        departments=(SupportedDepartment("OPH", "眼科"),),
        clinic_code_labels=("診間代碼",),
    )
