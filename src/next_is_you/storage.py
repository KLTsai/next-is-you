"""What every module that writes to D1 shares: statements, the store, time."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Protocol, Sequence
from zoneinfo import ZoneInfo

TAIPEI = ZoneInfo("Asia/Taipei")
UTC = timezone.utc


@dataclass(frozen=True, slots=True)
class Statement:
    sql: str
    values: tuple[Any, ...] = ()
    operation: str | None = None


class SqlStore(Protocol):
    async def execute(self, statement: Statement) -> int: ...

    async def fetch_all(self, statement: Statement) -> list[Mapping[str, Any]]: ...

    async def batch(self, statements: Sequence[Statement]) -> list[int]: ...


def iso_utc(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware")
    return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
