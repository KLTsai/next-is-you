"""Registry contract: every registered hospital must pass these assertions.

Local fixture/mock evidence only; nothing here contacts a hospital. The test is
parametrized over every registry entry plus synthetic entries, so a later ticket
adds an assertion once and it applies to all of them, and a synthetic hospital
is added by appending to `SYNTHETIC_ENTRIES`. The `Hospital` enum still names
the ids a visit can store (until #95), so a synthetic entry borrows a known id.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import pytest

from next_is_you.domain import Hospital, SourceCapability, SupportedDepartment
from next_is_you.hospital_registry import HOSPITAL_REGISTRY, HospitalEntry
from next_is_you.persistence import Statement, VisitRepository

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = sorted((ROOT / "migrations").glob("*.sql"))


class _SyntheticCurrentNumberReader:
    """Reads a current number only; cannot list a clinic schedule."""

    def __init__(self, storage, fetch) -> None:
        pass

    async def observe(self, scope, now):
        return None

    async def observe_for_start(self, scope, now):
        return None


# (case id, hospital id, entry). Add a synthetic hospital here to run every
# contract assertion against it.
SYNTHETIC_ENTRIES: tuple[tuple[str, Hospital, HospitalEntry], ...] = (
    (
        "synthetic-current-number-only",
        Hospital.SHIN_KONG_TAIPEI,
        HospitalEntry(
            "合成醫院（僅供測試）",
            _SyntheticCurrentNumberReader,
            progress_url="https://hospital.example/progress",
            departments=(SupportedDepartment("SYN", "合成科"),),
            clinic_code_labels=("診間",),
        ),
    ),
)

CASES = [
    pytest.param(hospital, entry, id=hospital.value)
    for hospital, entry in HOSPITAL_REGISTRY.items()
] + [
    pytest.param(hospital, entry, id=name)
    for name, hospital, entry in SYNTHETIC_ENTRIES
]


class _SQLiteStore:
    def __init__(self) -> None:
        self.connection = sqlite3.connect(":memory:", isolation_level=None)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        for migration in MIGRATIONS:
            self.connection.executescript(migration.read_text())

    async def execute(self, statement: Statement) -> int:
        return self.connection.execute(statement.sql, statement.values).rowcount

    async def fetch_all(self, statement: Statement) -> list[Mapping[str, Any]]:
        return [
            dict(row)
            for row in self.connection.execute(statement.sql, statement.values)
        ]

    async def batch(self, statements: Sequence[Statement]) -> list[int]:
        return [await self.execute(statement) for statement in statements]


def _expected_capability(entry: HospitalEntry) -> SourceCapability:
    if entry.reader_type is None:
        return SourceCapability.UNSUPPORTED
    if hasattr(entry.reader_type, "list_clinics"):
        return SourceCapability.FULL_SCHEDULE
    return SourceCapability.CURRENT_NUMBER_ONLY


@pytest.mark.parametrize(("hospital", "entry"), CASES)
def test_capability_derives_from_the_reader(
    hospital: Hospital, entry: HospitalEntry
) -> None:
    assert entry.capability is _expected_capability(entry)


@pytest.mark.parametrize(("hospital", "entry"), CASES)
def test_every_supported_hospital_offers_a_department(
    hospital: Hospital, entry: HospitalEntry
) -> None:
    if entry.capability is SourceCapability.UNSUPPORTED:
        pytest.skip("an unsupported hospital is offered to no one")
    assert len(entry.departments) >= 1


@pytest.mark.parametrize(("hospital", "entry"), CASES)
def test_every_official_link_is_fixed_https(
    hospital: Hospital, entry: HospitalEntry
) -> None:
    assert entry.progress_url is not None
    assert entry.progress_url.startswith("https://")


@pytest.mark.asyncio
@pytest.mark.parametrize(("hospital", "entry"), CASES)
async def test_every_registered_id_can_be_stored_with_a_visit(
    hospital: Hospital, entry: HospitalEntry
) -> None:
    store = _SQLiteStore()
    repo = VisitRepository(store)
    now = datetime(2026, 9, 27, 0, 0, tzinfo=timezone.utc)
    await repo.create_draft(
        visit_id="contract-visit",
        hospital=hospital.value,
        visit_day=date(2026, 9, 28),
        department_code="SYN",
        clinic_code="SYN-1",
        clinic_session="morning",
        patient_number=10,
        now=now,
    )
    stored = await repo.get_visit("contract-visit")
    assert stored is not None
    assert stored["hospital"] == hospital.value
