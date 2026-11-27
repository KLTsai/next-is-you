"""One invocation stays within D1's Free plan query limit at household sizes.

Fixture/mock evidence. The D1 double counts the way the D1 limits page says:
each query is one, and one `db.batch()` call is one whatever it holds. It
refuses every query after the 50th of an invocation. Whether Cloudflare counts
and refuses exactly this way has not been checked on a live Free plan account.

Each call to the send gate under `CountingD1.invoke` stands for one Durable
Object invocation, an alarm or an RPC, with its own count. The gate runs as a
live environment does, with only its reader and LINE replaced, so no query of
the local rehearsal's own controls is counted.

Larger households than the ones here still pass the limit in one tick (#278).
"""

from __future__ import annotations

import contextlib
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Awaitable, Callable, Iterator, Sequence, TypeVar

import pytest

from local_d1 import LocalD1, Prepared
from next_is_you.domain import QueueObservation
from next_is_you.line_messaging import LinePushHttpResponse
from next_is_you.persistence import CloudflareD1Store, VisitRepository
from next_is_you.send_gate import SystemSendGate
from test_scheduler_outbox import LocalContext, LocalDurableStorage

# D1 limits, "Queries per Worker invocation", Workers Free.
FREE_PLAN_QUERIES = 50

DAY = date(2026, 9, 27)
NOW = datetime(2026, 9, 27, 13, 0, tzinfo=timezone.utc)
T = TypeVar("T")


class TooManyQueries(RuntimeError):
    pass


@dataclass
class _Count:
    queries: int = 0


class _CountedStatement:
    def __init__(self, database: CountingD1, inner: Prepared) -> None:
        self.database = database
        self.inner = inner

    def bind(self, *values: Any) -> _CountedStatement:
        return _CountedStatement(self.database, self.inner.bind(*values))

    async def run(self) -> dict[str, Any]:
        self.database.count_query()
        return await self.inner.run()

    async def all(self) -> dict[str, Any]:
        self.database.count_query()
        return await self.inner.all()


class CountingD1(LocalD1):
    """The local database, counting the queries of each invocation."""

    def __init__(self) -> None:
        super().__init__()
        self._current: ContextVar[_Count | None] = ContextVar("count", default=None)

    def prepare(self, sql: str) -> _CountedStatement:
        return _CountedStatement(self, super().prepare(sql))

    async def batch(self, statements: Sequence[_CountedStatement]):
        self.count_query()
        return await super().batch([item.inner for item in statements])

    def count_query(self) -> None:
        count = self._current.get()
        if count is None:
            return
        count.queries += 1
        if count.queries > FREE_PLAN_QUERIES:
            raise TooManyQueries("Too many API requests by single Worker invocation")

    @contextlib.contextmanager
    def invocation(self) -> Iterator[_Count]:
        count = _Count()
        token = self._current.set(count)
        try:
            yield count
        finally:
            self._current.reset(token)

    async def invoke(self, call: Awaitable[T]) -> T:
        with self.invocation():
            return await call


class ScriptedReader:
    """One clinic's called number, or no usable read. It never queries D1."""

    def __init__(self, current: int | None) -> None:
        self.current = current

    async def observe(self, scope, now):
        if self.current is None:
            return None
        return QueueObservation(
            scope=scope,
            observed_at=now.isoformat(),
            current_number=self.current,
            trustworthy_current=True,
        )


class ScriptedLine:
    """LINE's answers, and one action to take while the first request is open."""

    def __init__(self) -> None:
        self.status = 200
        self.requests = 0
        self.during_first: Callable[[], Awaitable[None]] | None = None

    async def post(self, url: str, *, headers: dict[str, str], body: str):
        self.requests += 1
        if self.during_first is not None:
            action, self.during_first = self.during_first, None
            await action()
        return LinePushHttpResponse(status_code=self.status, request_id="fixture")


class OwnAccount:
    async def basic_id(self, channel_access_token: str) -> str:
        return "@111aaaaa"


class Household:
    """One running visit, number 85, told to this many recipients."""

    def __init__(self, database: CountingD1, current: int | None) -> None:
        self.database = database
        self.reader = ScriptedReader(current)
        self.line = ScriptedLine()
        self.gate = SystemSendGate(
            LocalContext(LocalDurableStorage()),
            {
                "DB": database,
                "NIY_ENVIRONMENT": "staging",
                "NIY_LIVE": "true",
                "LINE_BOT_BASIC_ID": "@111aaaaa",
                "LINE_CHANNEL_ACCESS_TOKEN": "fixture-token",
            },
        )
        self.gate._hospital_reader = lambda: self.reader
        self.gate._line_transport = self.line
        self.gate._line_bot_info = OwnAccount()

    async def tick(self, minute: int = 0) -> dict[str, Any]:
        when = f"2026-09-27T13:{minute:02d}:00Z"
        return await self.database.invoke(self.gate.alarm_tick(when))

    def column(self, sql: str) -> list[Any]:
        return [row[0] for row in self.database.connection.execute(sql)]

    async def assert_still_sending(self) -> None:
        result = await self.tick(30)
        assert result["held"] is False, result
        assert await self.gate.sending_interrupted() is False


async def household(recipients: int, current: int | None = 82) -> Household:
    database = CountingD1()
    names = [f"r{number}" for number in range(1, recipients + 1)]
    for number, name in enumerate(names, start=1):
        database.connection.execute(
            """INSERT INTO recipients (id, line_subject, display_name, consented_at,
            friendship_checked_at, active, created_at)
            VALUES (?, ?, 'Synthetic', ?, ?, 1, ?)""",
            (name, f"U{number:032d}", *(NOW.isoformat(),) * 3),
        )
    visits = VisitRepository(CloudflareD1Store(database))
    await visits.create_draft(
        visit_id="v1",
        hospital="ntuh-main",
        visit_day=DAY,
        department_code="SYN",
        clinic_code="SYN-1",
        clinic_session="afternoon",
        patient_number=85,
        now=NOW,
    )
    for name in names:
        assert await visits.add_recipient("v1", name, NOW)
    assert await visits.lifecycle.start("v1", NOW)
    return Household(database, current)


@pytest.mark.asyncio
@pytest.mark.parametrize("recipients", [1, 2, 3])
async def test_a_tick_sends_every_near_reminder_within_the_limit(
    recipients: int,
) -> None:
    home = await household(recipients)

    result = await home.tick()

    assert result["accepted"] == recipients
    assert home.column("SELECT outcome FROM outbound_events") == (
        ["accepted"] * recipients
    )
    await home.assert_still_sending()


@pytest.mark.asyncio
@pytest.mark.parametrize("recipients", [1, 2])
async def test_a_tick_sends_every_unavailable_message_within_the_limit(
    recipients: int,
) -> None:
    home = await household(recipients, current=None)
    await home.tick(0)
    await home.tick(1)

    result = await home.tick(2)

    assert result["accepted"] == recipients
    assert home.column("SELECT outcome FROM outbound_events") == (
        ["accepted"] * recipients
    )
    await home.assert_still_sending()


@pytest.mark.asyncio
async def test_a_tick_retries_one_recipient_within_the_limit() -> None:
    """LINE answers 5xx: the unavailable retry and a new near reminder both go."""
    home = await household(1, current=None)
    home.line.status = 500
    for minute in range(3):
        await home.tick(minute)
    home.reader.current = 82

    result = await home.tick(3)

    assert result["unknown"] == 2
    home.line.status = 200
    await home.assert_still_sending()


@pytest.mark.asyncio
async def test_a_tick_with_a_stop_pressed_during_a_send_stays_within_the_limit() -> (
    None
):
    home = await household(2)
    pressed: list[str | None] = []

    async def stop() -> None:
        # The Stop is an RPC, so it counts as an invocation of its own.
        pressed.append(
            await home.database.invoke(home.gate.stop_visit("v1", NOW.isoformat()))
        )

    home.line.during_first = stop

    result = await home.tick()

    assert pressed == ["stopping"]
    assert result["accepted"] == 1
    assert home.column("SELECT state FROM visits") == ["stopped"]
    await home.assert_still_sending()


@pytest.mark.asyncio
async def test_a_correction_removing_seven_recipients_stays_within_the_limit() -> None:
    home = await household(8)
    assert await home.gate.stop_visit("v1", NOW.isoformat()) == "stopped"

    corrected = await home.database.invoke(
        home.gate.correct_stopped_visit(
            "v1",
            hospital="ntuh-main",
            visit_day=DAY,
            department_code="SYN",
            clinic_code="SYN-1",
            clinic_session="afternoon",
            patient_number=86,
            recipient_ids=("r1",),
        )
    )

    assert corrected is True
    assert home.column("SELECT recipient_id FROM visit_recipients") == ["r1"]
    await home.assert_still_sending()


@pytest.mark.asyncio
async def test_the_send_record_digest_is_one_query() -> None:
    """Every check and every save computes it, several times for each send."""
    home = await household(2)

    with home.database.invocation() as count:
        await VisitRepository(
            CloudflareD1Store(home.database)
        ).scheduler_ledger_digest()

    assert count.queries == 1
