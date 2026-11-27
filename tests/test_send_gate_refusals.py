"""The send gate answers Start and Stop only with catalog refusal codes (#146).

The worker answers a code it does not know as `service_unavailable`, so the
gate must raise on one instead. The codes cross the Durable Object RPC
boundary, which serializes built-in `str`, not enum instances.

Fixture/mock evidence: the real send gate over a local database, no network.
"""

from __future__ import annotations

import pytest

from test_scheduler_outbox import LocalD1, make_gate, seed

NOW = "2026-09-27T13:00:00Z"


@pytest.mark.asyncio
async def test_a_refused_start_answers_a_plain_string_code():
    gate = make_gate(LocalD1())

    result = await gate.start_visit("missing", NOW)

    assert result == {"error": "visit_not_found"}
    assert type(result["error"]) is str


@pytest.mark.asyncio
async def test_a_refused_stop_answers_a_plain_string_code():
    database = LocalD1()
    gate = make_gate(database)
    await seed(gate)
    database.connection.execute("UPDATE visits SET state = 'draft' WHERE id = 'v1'")

    answer = await gate.stop_visit("v1", NOW)

    assert answer == "invalid_lifecycle_state"
    assert type(answer) is str


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "call,inner,answer",
    [
        ("start_visit", "_start_visit", {"error": "unlisted_code"}),
        ("stop_visit", "_stop_visit", "unlisted_code"),
    ],
    ids=["start", "stop"],
)
async def test_a_code_outside_the_catalog_raises_instead_of_leaving_the_gate(
    monkeypatch, call, inner, answer
):
    gate = make_gate(LocalD1())

    async def unlisted(*_args):
        return answer

    monkeypatch.setattr(gate, inner, unlisted)

    with pytest.raises(ValueError, match="unlisted_code"):
        await getattr(gate, call)("v1", NOW)
