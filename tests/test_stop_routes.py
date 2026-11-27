"""Both Stop routes answer the send gate's outcome the same way (#265).

Fixture/mock evidence: the real API routes over the real send gate and the local
database, with the local test LINE transport holding a request in flight.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime

import pytest
from httpx import ASGITransport, AsyncClient

from next_is_you.auth import CSRF_COOKIE_NAME, SESSION_COOKIE_NAME, issue_session
from next_is_you.identity import IdentityRepository
from next_is_you.persistence import CloudflareD1Store, VisitRepository
from next_is_you.send_gate import SystemSendGate
from test_scheduler_outbox import LocalD1, make_gate, seed
from worker import create_app

SECRET = "stop-routes-test-secret-with-at-least-32-bytes"
NOW = "2026-09-27T13:00:00Z"

ROUTES = ("/api/organizer/visits/{}/stop", "/api/visits/{}/stop")


@pytest.fixture(params=ROUTES, ids=["organizer", "legacy"])
def route(request: pytest.FixtureRequest) -> str:
    return request.param


def organizer(database: LocalD1, gate: SystemSendGate) -> AsyncClient:
    now = int(datetime.fromisoformat(NOW).timestamp())
    store = CloudflareD1Store(database)
    app = create_app(
        settings={
            "session_secret": SECRET,
            "organizer_subjects": {"organizer"},
            "line_login_channel_id": "local",
            "line_login_channel_secret": "local-secret",
            "line_login_redirect_uri": "https://family.example/auth/line/callback",
        },
        identity_repository=IdentityRepository(store),
        visit_repository=VisitRepository(store),
        send_gate=gate,
        clock=lambda: now,
    )
    session = issue_session("organizer", "organizer", SECRET, now=now)
    return AsyncClient(
        transport=ASGITransport(app=app),
        base_url="https://family.example",
        cookies={
            SESSION_COOKIE_NAME: session.value,
            CSRF_COOKIE_NAME: session.csrf_token,
        },
        headers={"x-csrf-token": session.csrf_token},
    )


async def running() -> tuple[LocalD1, SystemSendGate]:
    database = LocalD1()
    gate = make_gate(database)
    await seed(gate)
    await gate.set_test_observation(82)
    return database, gate


@asynccontextmanager
async def message_in_flight(gate: SystemSendGate):
    """A tick holding its LINE request open until the block ends."""
    await gate.set_test_line_mode("wait")
    tick = asyncio.create_task(gate.scheduled_tick(NOW))
    await gate.wait_test_request_started()
    try:
        yield
    finally:
        await gate.release_test_request()
        await tick


def state(database: LocalD1, visit_id: str = "v1") -> str:
    return database.connection.execute(
        "SELECT state FROM visits WHERE id = ?", (visit_id,)
    ).fetchone()[0]


async def stop(database: LocalD1, gate: SystemSendGate, route: str, visit_id="v1"):
    async with organizer(database, gate) as http:
        response = await http.post(route.format(visit_id))
    return response.status_code, response.json()


@pytest.mark.asyncio
async def test_a_stop_refused_as_held_answers_503(route: str) -> None:
    database, gate = await running()
    async with message_in_flight(gate):
        # Changed outside the gate, so the send record no longer matches.
        database.connection.execute(
            "UPDATE visits SET near_prev_observed_number = 70 WHERE id = 'v1'"
        )

        answer = await stop(database, gate, route)

        assert answer == (503, {"error": {"code": "scheduler_held"}})
        assert state(database) == "active"
    assert await gate.sending_interrupted() is True


@pytest.mark.asyncio
async def test_a_stopped_visit_answers_stopped(route: str) -> None:
    database, gate = await running()

    assert await stop(database, gate, route) == (200, {"state": "stopped"})
    assert state(database) == "stopped"


@pytest.mark.asyncio
async def test_a_stop_during_a_send_answers_stopping(route: str) -> None:
    database, gate = await running()
    async with message_in_flight(gate):
        assert await stop(database, gate, route) == (200, {"state": "stopping"})


@pytest.mark.asyncio
async def test_an_unknown_visit_answers_404(route: str) -> None:
    database, gate = await running()

    assert await stop(database, gate, route, "unknown") == (
        404,
        {"error": {"code": "visit_not_found"}},
    )


@pytest.mark.asyncio
async def test_a_draft_answers_409(route: str) -> None:
    database, gate = await running()
    async with organizer(database, gate) as http:
        created = await http.post(
            "/api/organizer/visits",
            json={
                "hospital": "ntuh-main",
                "date": "2026-09-27",
                "department_code": "SYN",
                "clinic_code": "SYN-1",
                "session": "afternoon",
                "patient_number": 90,
                "recipient_ids": ["r1"],
            },
        )
    assert created.status_code == 201

    assert await stop(database, gate, route, created.json()["id"]) == (
        409,
        {"error": {"code": "invalid_lifecycle_state"}},
    )
