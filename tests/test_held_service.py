"""Fixture regressions for the production hold and runtime configuration boundary."""

import json

import pytest
from httpx import ASGITransport, AsyncClient

from next_is_you.auth import SESSION_COOKIE_NAME, issue_session
from next_is_you.send_gate import SystemSendGate
from test_scheduler_outbox import (
    LocalContext,
    LocalD1,
    LocalDurableStorage,
    make_gate,
    seed,
)
from worker import LineLoginSettings, create_app


@pytest.mark.parametrize(
    "name",
    [
        "LINE_LOGIN_CHANNEL_ID",
        "LINE_LOGIN_CHANNEL_SECRET",
        "LINE_LOGIN_REDIRECT_URI",
        "SESSION_SIGNING_SECRET",
    ],
)
@pytest.mark.parametrize("invalid", [None, "", "   ", True])
def test_missing_or_invalid_auth_values_fail_closed(name, invalid):
    values = {
        "LINE_LOGIN_CHANNEL_ID": "fixture-channel",
        "LINE_LOGIN_CHANNEL_SECRET": "fixture-secret",
        "LINE_LOGIN_REDIRECT_URI": "https://family.example/auth/line/callback",
        "SESSION_SIGNING_SECRET": "fixture-session-signing-secret-at-least-32-bytes",
        "ORGANIZER_LINE_SUBJECTS": "fixture-organizer",
    }
    assert not LineLoginSettings.from_mapping(values | {name: invalid}).ready


@pytest.mark.asyncio
@pytest.mark.parametrize("environment", [None, "production", "unknown"])
async def test_non_test_environment_cannot_send_or_resume_even_with_test_flag(
    environment,
):
    database = LocalD1()
    storage = LocalDurableStorage()
    rehearsal = make_gate(database, storage)
    await seed(rehearsal)
    await rehearsal.set_test_observation(82)
    # An already active row from a restored dataset must also stay held.
    env = {"DB": database, "NIY006_LOCAL_TEST_MODE": "1"}
    if environment is not None:
        env["NIY_ENVIRONMENT"] = environment
    gate = SystemSendGate(LocalContext(storage), env)
    tick = await gate.scheduled_tick("2026-09-27T13:00:00Z")
    assert tick["held"] is True
    assert "requests_started" not in tick
    await gate.hold_for_reconciliation()
    assert not await gate.resume_after_reconciliation(True)
    restarted = SystemSendGate(LocalContext(storage), env)
    assert await restarted.scheduler_status() == {
        "held": True,
        "configuration_hold": True,
        "recovery_hold": True,
        "hospital_reader_available": False,
    }
    assert (
        database.connection.execute("SELECT COUNT(*) FROM outbound_events").fetchone()[
            0
        ]
        == 0
    )
    with pytest.raises(RuntimeError, match="disabled"):
        await gate.set_test_observation(82)


@pytest.mark.asyncio
async def test_production_missing_reader_cannot_start_existing_draft():
    database = LocalD1()
    storage = LocalDurableStorage()
    rehearsal = make_gate(database, storage)
    await seed(rehearsal)
    database.connection.execute("UPDATE visits SET state = 'draft'")
    # Refresh the fixture ledger after reshaping the draft.
    await rehearsal._save_ledger()
    gate = SystemSendGate(
        LocalContext(storage), {"DB": database, "NIY_ENVIRONMENT": "production"}
    )
    assert await gate.start_visit("v1", "2026-09-27T13:00:00Z") == {
        "error": "observation_unavailable"
    }
    assert (
        database.connection.execute("SELECT state FROM visits").fetchone()[0] == "draft"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "callback",
    [
        "https://family.example/wrong",
        "https://family.example/auth/line/callback?other=1",
        "https://family.example:bad/auth/line/callback",
        "https://other.example/auth/line/callback",
    ],
)
async def test_invalid_or_different_origin_runtime_callback_fails_closed(callback):
    env = {
        "NIY_ENVIRONMENT": "production",
        "LINE_LOGIN_CHANNEL_ID": "fixture-channel",
        "LINE_LOGIN_CHANNEL_SECRET": "fixture-secret",
        "LINE_LOGIN_REDIRECT_URI": callback,
        "SESSION_SIGNING_SECRET": "fixture-session-signing-secret-at-least-32-bytes",
        "ORGANIZER_LINE_SUBJECTS": "fixture-organizer",
    }
    app = create_app()

    async def runtime(scope, receive, send):
        await app({**scope, "env": env}, receive, send)

    async with AsyncClient(
        transport=ASGITransport(app=runtime), base_url="https://family.example"
    ) as client:
        assert (await client.get("/auth/line")).status_code == 503
        assert (
            await client.get("/auth/line/callback?code=fixture&state=fixture")
        ).status_code == 503


@pytest.mark.asyncio
async def test_scheduler_status_requires_allowlisted_organizer():
    database = LocalD1()
    gate = SystemSendGate(LocalContext(LocalDurableStorage()), {"DB": database})
    settings = LineLoginSettings(
        "fixture-id",
        "fixture-secret",
        "https://family.example/auth/line/callback",
        "fixture-session-signing-secret-at-least-32-bytes",
        frozenset({"organizer"}),
    )
    app = create_app(settings=settings, send_gate=gate, clock=lambda: 1000)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://family.example"
    ) as client:
        assert (await client.get("/api/organizer/scheduler/status")).status_code == 401
        for subject, role, expected in [
            ("outsider", "organizer", 403),
            ("recipient", "recipient", 403),
            ("organizer", "organizer", 200),
        ]:
            session = issue_session(subject, role, settings.session_secret, now=1000)
            client.cookies.set(SESSION_COOKIE_NAME, session.value)
            response = await client.get("/api/organizer/scheduler/status")
            assert response.status_code == expected
            if expected == 200:
                assert json.loads(response.content)["configuration_hold"] is True
