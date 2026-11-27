"""Fixture/mock regressions for the live switch (#237).

An environment is live (GLOSSARY.md: Live) only when its committed config
says so. Live means it reads the hospital and sends LINE messages together;
not live means it does neither. A live environment still sends nothing while
its LINE token is missing or belongs to another Official Account, and the
status says why.
"""

from __future__ import annotations

from typing import Any

import pytest

from local_d1 import LocalD1
from next_is_you.line_messaging import LinePushHttpResponse
from next_is_you.send_gate import SystemSendGate
from test_ntuh_reader import DAY, PAGE, FakeSource, active_visit, seed_ntuh, taipei
from test_scheduler_outbox import (
    LocalContext,
    LocalDurableStorage,
)

# This module serves NTUH reader values (#205).
pytestmark = pytest.mark.usefixtures("serve_reader_values")

STAGING_ACCOUNT = "@111aaaaa"
PRODUCTION_ACCOUNT = "@222bbbbb"


class RecordingLineTransport:
    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []

    async def post(
        self, url: str, *, headers: dict[str, str], body: str
    ) -> LinePushHttpResponse:
        self.requests.append({"url": url, "headers": headers, "body": body})
        return LinePushHttpResponse(status_code=200, request_id="fixture-request")


class FakeBotInfo:
    """Answers LINE's bot info lookup with the basic ID a token belongs to."""

    def __init__(self, accounts: dict[str, str | None]) -> None:
        self.accounts = accounts
        self.lookups: list[str] = []

    async def basic_id(self, channel_access_token: str) -> str | None:
        self.lookups.append(channel_access_token)
        return self.accounts.get(channel_access_token)


TOKENS = {
    "staging-token": STAGING_ACCOUNT,
    "production-token": PRODUCTION_ACCOUNT,
    "unreadable-token": None,
}


def staging_env(database: LocalD1, **overrides: Any) -> dict[str, Any]:
    env: dict[str, Any] = {
        "DB": database,
        "NIY_ENVIRONMENT": "staging",
        "NIY006_LOCAL_TEST_MODE": "0",
        "NIY_LIVE": "true",
        "LINE_BOT_BASIC_ID": STAGING_ACCOUNT,
        "LINE_CHANNEL_ACCESS_TOKEN": "staging-token",
    }
    env.update(overrides)
    return {name: value for name, value in env.items() if value is not None}


async def live_gate(**overrides: Any):
    database = LocalD1()
    source = FakeSource(PAGE)
    line = RecordingLineTransport()
    bot_info = FakeBotInfo(TOKENS)
    gate = SystemSendGate(
        LocalContext(LocalDurableStorage()), staging_env(database, **overrides)
    )
    gate._ntuh_fetcher = source
    gate._line_transport = line
    gate._line_bot_info = bot_info
    await active_visit(database, gate)
    return gate, source, line, bot_info


def sent_events(gate: SystemSendGate) -> int:
    database = gate.env["DB"]
    return database.connection.execute(
        "SELECT COUNT(*) FROM outbound_events"
    ).fetchone()[0]


@pytest.mark.asyncio
async def test_live_environment_reads_the_hospital_and_sends() -> None:
    gate, source, line, _ = await live_gate()

    result = await gate.scheduled_tick(taipei(15, 2).isoformat())

    assert result["held"] is False
    assert source.urls, "a live environment reads the hospital"
    assert result["accepted"] == 1
    assert len(line.requests) == 1
    assert line.requests[0]["headers"]["Authorization"] == "Bearer staging-token"
    status = await gate.scheduler_status()
    assert status["live"] is True
    assert status["held"] is False
    assert status["hospital_reader_available"] is True
    assert status["line_unavailable_reason"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("live", [None, "false", "", "1", "yes", "TRUE", " true"])
async def test_not_live_environment_neither_reads_nor_sends_even_with_a_token(
    live,
) -> None:
    gate, source, line, bot_info = await live_gate(NIY_LIVE=live)

    result = await gate.scheduled_tick(taipei(15, 2).isoformat())

    assert result["held"] is True
    assert source.urls == []
    assert line.requests == []
    assert bot_info.lookups == []
    assert sent_events(gate) == 0
    status = await gate.scheduler_status()
    assert status == {
        "held": True,
        "live": False,
        "recovery_hold": False,
        "hospital_reader_available": False,
        "line_unavailable_reason": "not_live",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"LINE_CHANNEL_ACCESS_TOKEN": None}, "line_token_missing"),
        ({"LINE_CHANNEL_ACCESS_TOKEN": "   "}, "line_token_missing"),
        (
            {"LINE_CHANNEL_ACCESS_TOKEN": "production-token"},
            "line_token_other_account",
        ),
        ({"LINE_BOT_BASIC_ID": None}, "line_account_not_committed"),
        (
            {"LINE_CHANNEL_ACCESS_TOKEN": "unreadable-token"},
            "line_account_unverified",
        ),
    ],
)
async def test_live_environment_without_its_own_line_token_sends_nothing_and_says_why(
    overrides, reason
) -> None:
    gate, source, line, _ = await live_gate(**overrides)

    result = await gate.scheduled_tick(taipei(15, 2).isoformat())

    assert result["held"] is True
    assert result["line_unavailable_reason"] == reason
    assert line.requests == []
    assert source.urls == []
    assert sent_events(gate) == 0
    status = await gate.scheduler_status()
    assert status["live"] is True
    assert status["held"] is True
    assert status["line_unavailable_reason"] == reason


@pytest.mark.asyncio
async def test_a_verified_token_is_looked_up_once_until_it_changes() -> None:
    gate, _, line, bot_info = await live_gate()

    await gate.scheduled_tick(taipei(15, 2).isoformat())
    await gate.scheduled_tick(taipei(15, 3).isoformat())
    assert bot_info.lookups == ["staging-token"]

    gate.env["LINE_CHANNEL_ACCESS_TOKEN"] = "production-token"
    result = await gate.scheduled_tick(taipei(15, 4).isoformat())
    assert result["line_unavailable_reason"] == "line_token_other_account"
    assert bot_info.lookups == ["staging-token", "production-token"]
    assert len(line.requests) == 1


async def live_draft(**overrides: Any):
    """A live gate holding one draft and no running visit."""
    database = LocalD1()
    source = FakeSource(PAGE)
    gate = SystemSendGate(
        LocalContext(LocalDurableStorage()), staging_env(database, **overrides)
    )
    gate._ntuh_fetcher = source
    gate._line_transport = RecordingLineTransport()
    gate._line_bot_info = FakeBotInfo(TOKENS)
    await seed_ntuh(database, gate, "d1")
    return gate, source


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "overrides",
    [
        {"NIY_LIVE": "false"},
        {"LINE_CHANNEL_ACCESS_TOKEN": None},
        {"LINE_CHANNEL_ACCESS_TOKEN": "production-token"},
    ],
    ids=["not live", "no token", "other account token"],
)
async def test_start_and_the_picker_read_no_hospital_while_nothing_can_be_sent(
    overrides,
) -> None:
    # Reading and sending go together: a visit started now would never get
    # a reminder, so Start is refused before the hospital is read.
    gate, source = await live_draft(**overrides)

    assert await gate.start_visit("d1", taipei(15, 0).isoformat()) == {
        "error": "observation_unavailable"
    }
    roster = await gate.list_clinics(
        "ntuh-main", "OPH", DAY.isoformat(), taipei(14, 0).isoformat()
    )
    assert roster == {"available": False, "reason": "no_observation", "clinics": []}
    assert source.urls == []
    assert (await gate.scheduler_status())["hospital_reader_available"] is False


@pytest.mark.asyncio
async def test_start_and_the_picker_read_the_hospital_once_live_with_its_own_token() -> (
    None
):
    gate, source = await live_draft()

    roster = await gate.list_clinics(
        "ntuh-main", "OPH", DAY.isoformat(), taipei(14, 0).isoformat()
    )
    assert roster["available"] is True
    assert source.urls
