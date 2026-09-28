from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from httpx import ASGITransport, AsyncClient

from next_is_you.auth import CSRF_COOKIE_NAME, SESSION_COOKIE_NAME, issue_session
from next_is_you.identity import IdentityRepository
from next_is_you.persistence import Statement, VisitRepository
from next_is_you.progress_links import progress_link
from worker import create_app


ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = sorted((ROOT / "migrations").glob("*.sql"))
SECRET = "organizer-api-test-secret-with-at-least-32-bytes"


class SQLiteStore:
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


class Gate:
    async def start_visit(self, _visit_id: str, _now: str):
        return {"error": "observation_unavailable"}

    async def stop_visit(self, visit_id: str, _now: str):
        return "stopped" if visit_id == "existing" else None

    async def correct_stopped_visit(self, *_args, **_kwargs):
        return False


def make_client():
    store = SQLiteStore()
    store.connection.execute(
        """INSERT INTO recipients (id, line_subject, display_name, consented_at,
            friendship_checked_at, active, created_at) VALUES
            ('eligible', 'private-subject', 'Family Name', '2026-09-27T00:00:00Z',
            '2026-09-27T00:00:00Z', 1, '2026-09-27T00:00:00Z'),
            ('inactive', 'inactive-subject', 'Inactive', NULL, NULL, 0, '2026-09-27T00:00:00Z')"""
    )
    visits = VisitRepository(store)
    app = create_app(
        settings={
            "session_secret": SECRET,
            "organizer_subjects": {"organizer"},
            "line_login_channel_id": "local",
            "line_login_channel_secret": "local-secret",
            "line_login_redirect_uri": "https://family.example/auth/line/callback",
        },
        identity_repository=IdentityRepository(store),
        visit_repository=visits,
        send_gate=Gate(),
        clock=lambda: datetime(2026, 9, 28, 10, 0, tzinfo=timezone.utc).timestamp(),
    )
    http = AsyncClient(
        transport=ASGITransport(app=app), base_url="https://family.example"
    )
    return store, http


def authorize(
    http: AsyncClient, subject="organizer", role="organizer"
) -> dict[str, str]:
    now = int(datetime(2026, 9, 28, 10, 0, tzinfo=timezone.utc).timestamp())
    session = issue_session(subject, role, SECRET, now=now)
    http.cookies.set(
        SESSION_COOKIE_NAME, session.value, domain="family.example", path="/"
    )
    http.cookies.set(
        CSRF_COOKIE_NAME, session.csrf_token, domain="family.example", path="/"
    )
    return {"x-csrf-token": session.csrf_token}


def test_organizer_reads_eligible_roster_and_creates_draft_with_auth_and_csrf():
    async def scenario():
        store, http = make_client()
        try:
            denied = await http.get("/api/organizer/recipients")
            assert denied.status_code == 401
            headers = authorize(http)
            missing_csrf = await http.post("/api/organizer/visits", json={})
            assert missing_csrf.status_code == 403
            recipients = await http.get("/api/organizer/recipients")
            assert recipients.json() == {
                "recipients": [{"id": "eligible", "display_name": "Family Name"}]
            }
            body = {
                "hospital": "ntuh-main",
                "date": "2026-09-29",
                "department_code": "MED",
                "clinic_code": "MED-A",
                "session": "morning",
                "patient_number": 85,
                "recipient_ids": ["eligible"],
                "source_url": "https://attacker.invalid/echo",
            }
            rejected_url = await http.post(
                "/api/organizer/visits", json=body, headers=headers
            )
            assert rejected_url.status_code == 400
            body.pop("source_url")
            created = await http.post(
                "/api/organizer/visits", json=body, headers=headers
            )
            assert created.status_code == 201
            assert created.json()["state"] == "draft"
            shin_kong = {**body, "hospital": "shin-kong-taipei", "clinic_code": "MED-B"}
            assert (
                await http.post(
                    "/api/organizer/visits", json=shin_kong, headers=headers
                )
            ).status_code == 201
            listing = await http.get("/api/organizer/visits")
            assert listing.status_code == 200
            visits = {visit["hospital"]: visit for visit in listing.json()["visits"]}
            assert (
                visits["ntuh-main"]["source_url"]
                == "https://registration.ntuh.gov.tw/WebReg/WebReg/ClinicCurrentLightNo?vHospCode=T0"
            )
            assert visits["shin-kong-taipei"]["source_url"] == "https://reg.skh.org.tw/"
            for visit in visits.values():
                assert visit["source_read"] == {
                    "status": "unavailable",
                    "reason": "no_observation",
                }
                assert visit["recipients"] == [
                    {"id": "eligible", "display_name": "Family Name"}
                ]
            assert "private-subject" not in repr(listing.json())
            assert "retry_key" not in repr(listing.json())
            assert "attacker.invalid" not in repr(listing.json())
            assert "payload_json" not in repr(listing.json())
        finally:
            await http.aclose()

    asyncio.run(scenario())


def test_progress_link_catalog_is_limited_to_fixed_https_hospitals():
    assert (
        progress_link("ntuh-main")
        == "https://registration.ntuh.gov.tw/WebReg/WebReg/ClinicCurrentLightNo?vHospCode=T0"
    )
    assert progress_link("shin-kong-taipei") == "https://reg.skh.org.tw/"
    assert progress_link("unsupported-hospital") is None
    assert progress_link("https://attacker.invalid") is None


def test_mutations_recheck_allowlist_and_start_returns_typed_safe_error():
    async def scenario():
        _, http = make_client()
        try:
            authorize(http, subject="removed-organizer")
            denied = await http.post(
                "/api/organizer/visits/id/start",
                headers={"x-csrf-token": http.cookies[CSRF_COOKIE_NAME]},
            )
            assert denied.status_code == 403
            headers = authorize(http)
            started = await http.post("/api/organizer/visits/id/start", headers=headers)
            assert started.status_code == 503
            assert started.json() == {"error": {"code": "observation_unavailable"}}
            assert "detail" not in started.json()
        finally:
            await http.aclose()

    asyncio.run(scenario())


def test_synthetic_session_fixture_is_missing_without_explicit_test_binding():
    async def scenario():
        _, http = make_client()
        try:
            response = await http.post("/__niy006_test/organizer-session", json={})
            assert response.status_code == 404
        finally:
            await http.aclose()

    asyncio.run(scenario())


def test_synthetic_organizer_session_requires_explicit_niy006_test_binding():
    async def scenario():
        clock_now = int(datetime(2026, 9, 28, 10, 0, tzinfo=timezone.utc).timestamp())
        app = create_app(clock=lambda: clock_now, send_gate=Gate())

        class TestConfigApp:
            async def __call__(self, scope, receive, send):
                await app(
                    {**scope, "env": {"NIY006_LOCAL_TEST_MODE": "1"}}, receive, send
                )

        async with AsyncClient(
            transport=ASGITransport(app=TestConfigApp()),
            base_url="https://family.example",
        ) as http:
            fixture = await http.post("/__niy006_test/organizer-session", json={})
            assert fixture.status_code == 200
            assert SESSION_COOKIE_NAME in http.cookies
            assert CSRF_COOKIE_NAME in http.cookies
            authorized = await http.get("/api/organizer/visits")
            assert authorized.status_code == 503
            assert authorized.json() == {"error": {"code": "service_unavailable"}}

    asyncio.run(scenario())
