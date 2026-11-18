from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import date, datetime, timezone
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
    def __init__(self, visits: VisitRepository) -> None:
        self.visits = visits

    async def update_draft(self, visit_id: str, **values: Any):
        return await self.visits.update_draft(visit_id=visit_id, **values)

    async def update_draft_rpc(self, request_json: str):
        request = json.loads(request_json)
        return await self.update_draft(
            str(request["visit_id"]),
            hospital=str(request["hospital"]),
            visit_day=date.fromisoformat(str(request["visit_day"])),
            department_code=str(request["department_code"]),
            clinic_code=str(request["clinic_code"]),
            clinic_session=str(request["clinic_session"]),
            patient_number=int(request["patient_number"]),
            recipient_ids=tuple(request["recipient_ids"]),
            now=datetime.fromisoformat(str(request["now"]).replace("Z", "+00:00")),
        )

    async def add_visit_recipient(
        self, visit_id: str, recipient_id: str, now: datetime
    ):
        return await self.visits.add_recipient(visit_id, recipient_id, now)

    async def start_visit(self, visit_id: str, _now: str):
        scripted = {
            "unpublished": {
                "error": "visit_date_out_of_schedule_window",
                "schedule_end": "2026-12-01",
                "release_time": "2026-11-21T00:00:00+08:00",
            },
            "unpublished-no-release": {
                "error": "visit_date_out_of_schedule_window",
                "schedule_end": "2026-12-01",
            },
            "day-only": {
                "error": "start_on_visit_day_only",
                "visit_date": "2026-11-20",
            },
            "not-found": {"error": "hospital_cannot_find_clinic"},
            "unreachable": {"error": "hospital_page_unreachable"},
        }
        return scripted.get(visit_id, {"error": "observation_unavailable"})

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
        send_gate=Gate(visits),
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


def test_organizer_reads_eligible_roster_and_creates_draft_with_auth_and_csrf(
    monkeypatch,
):
    from next_is_you import hospital_registry
    from synthetic_hospital import SYNTHETIC_ID, SYNTHETIC_LINK, synthetic_entry

    monkeypatch.setitem(
        hospital_registry.HOSPITAL_REGISTRY, SYNTHETIC_ID, synthetic_entry()
    )

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
            updated_body = {**body, "session": "evening", "patient_number": 86}
            updated = await http.patch(
                f"/api/organizer/visits/{created.json()['id']}",
                json=updated_body,
                headers=headers,
            )
            assert updated.status_code == 200
            assert updated.json() == {"id": created.json()["id"], "state": "draft"}
            second = {**body, "hospital": SYNTHETIC_ID, "clinic_code": "MED-B"}
            assert (
                await http.post("/api/organizer/visits", json=second, headers=headers)
            ).status_code == 201
            listing = await http.get("/api/organizer/visits")
            assert listing.status_code == 200
            visits = {visit["hospital"]: visit for visit in listing.json()["visits"]}
            assert visits["ntuh-main"]["session"] == "evening"
            assert visits["ntuh-main"]["patient_number"] == 86
            assert visits[SYNTHETIC_ID]["patient_number"] == 85
            assert (
                visits["ntuh-main"]["source_url"]
                == "https://registration.ntuh.gov.tw/WebReg/WebReg/ClinicCurrentLightNo?vHospCode=T0"
            )
            assert visits[SYNTHETIC_ID]["source_url"] == SYNTHETIC_LINK
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


def test_correction_patient_number_is_single_visit_authorized_csrf_protected_data():
    async def scenario():
        _, http = make_client()
        try:
            denied = await http.get("/api/organizer/visits/selected/correction")
            assert denied.status_code == 401
            organizer_headers = authorize(http)
            body = {
                "hospital": "ntuh-main",
                "date": "2026-09-29",
                "department_code": "MED",
                "clinic_code": "MED-A",
                "session": "morning",
                "patient_number": 85,
                "recipient_ids": ["eligible"],
            }
            first = await http.post(
                "/api/organizer/visits", json=body, headers=organizer_headers
            )
            second = await http.post(
                "/api/organizer/visits",
                json={**body, "patient_number": 42},
                headers=organizer_headers,
            )
            assert first.status_code == second.status_code == 201
            selected_url = f"/api/organizer/visits/{first.json()['id']}/correction"

            missing_csrf = await http.get(selected_url)
            assert missing_csrf.status_code == 403
            non_organizer = authorize(http, subject="family", role="recipient")
            denied_role = await http.get(selected_url, headers=non_organizer)
            assert denied_role.status_code == 403
            invalid_csrf = await http.get(
                selected_url, headers={"x-csrf-token": "invalid"}
            )
            assert invalid_csrf.status_code == 403

            organizer_headers = authorize(http)
            authorized = await http.get(selected_url, headers=organizer_headers)
            assert authorized.status_code == 200
            assert authorized.json() == {"patient_number": 85}
            reopened = await http.get(selected_url, headers=organizer_headers)
            assert reopened.json() == {"patient_number": 85}
            other = await http.get(
                f"/api/organizer/visits/{second.json()['id']}/correction",
                headers=organizer_headers,
            )
            assert other.json() == {"patient_number": 42}
            listing = await http.get("/api/organizer/visits")
            assert listing.status_code == 200
            visits = {visit["id"]: visit for visit in listing.json()["visits"]}
            assert visits[first.json()["id"]]["patient_number"] == 85
            assert visits[second.json()["id"]]["patient_number"] == 42
        finally:
            await http.aclose()

    asyncio.run(scenario())


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


def test_start_on_a_current_number_only_hospital_returns_its_typed_refusals():
    async def scenario():
        _, http = make_client()
        try:
            headers = authorize(http)
            day_only = await http.post(
                "/api/organizer/visits/day-only/start", headers=headers
            )
            assert day_only.status_code == 409
            assert day_only.json() == {
                "error": {
                    "code": "start_on_visit_day_only",
                    "visit_date": "2026-11-20",
                }
            }
            not_found = await http.post(
                "/api/organizer/visits/not-found/start", headers=headers
            )
            assert not_found.status_code == 409
            assert not_found.json() == {
                "error": {"code": "hospital_cannot_find_clinic"}
            }
            unreachable = await http.post(
                "/api/organizer/visits/unreachable/start", headers=headers
            )
            assert unreachable.status_code == 503
            assert unreachable.json() == {
                "error": {"code": "hospital_page_unreachable"}
            }
        finally:
            await http.aclose()

    asyncio.run(scenario())


def test_start_refusal_for_unpublished_day_carries_end_date_and_release_time():
    async def scenario():
        _, http = make_client()
        try:
            headers = authorize(http)
            refused = await http.post(
                "/api/organizer/visits/unpublished/start", headers=headers
            )
            assert refused.status_code == 409
            assert refused.json() == {
                "error": {
                    "code": "visit_date_out_of_schedule_window",
                    "schedule_end": "2026-12-01",
                    "release_time": "2026-11-21T00:00:00+08:00",
                }
            }
            bare = await http.post(
                "/api/organizer/visits/unpublished-no-release/start",
                headers=headers,
            )
            assert bare.json() == {
                "error": {
                    "code": "visit_date_out_of_schedule_window",
                    "schedule_end": "2026-12-01",
                }
            }
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
        visits = VisitRepository(SQLiteStore())
        app = create_app(clock=lambda: clock_now, send_gate=Gate(visits))

        class TestConfigApp:
            async def __call__(self, scope, receive, send):
                await app(
                    {
                        **scope,
                        "env": {
                            "NIY006_LOCAL_TEST_MODE": "1",
                            "NIY_ENVIRONMENT": "local-test",
                        },
                    },
                    receive,
                    send,
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


def test_hospital_catalog_response_is_unchanged_for_ntuh_and_shin_kong():
    # Snapshot (fixture/mock): the exact bytes the organizer's catalog returned
    # before the registry derived capability and owned the official link.
    expected = (
        '{"hospitals":[{"hospital":"ntuh-main","display_name":"臺大醫院總院",'
        '"capability":"full_schedule","source_url":"https://registration.ntuh.gov.tw'
        '/WebReg/WebReg/ClinicCurrentLightNo?vHospCode=T0",'
        '"clinic_code_labels":["診間","醫師","門診別"],'
        '"departments":[{"code":"OPH","display_name":"眼科"}]},'
        '{"hospital":"shin-kong-taipei","display_name":"新光醫院（台北）",'
        '"capability":"unsupported","source_url":"https://reg.skh.org.tw/",'
        '"clinic_code_labels":[],"departments":[]}]}'
    ).encode()

    async def scenario():
        _store, http = make_client()
        try:
            authorize(http)
            response = await http.get("/api/organizer/hospitals")
            assert response.status_code == 200
            assert response.content == expected
        finally:
            await http.aclose()

    asyncio.run(scenario())


# --- Registry-owned hospital ids (#105): local integration -------------------

UNKNOWN_HOSPITAL = "not-in-the-registry"


def _visit_body(hospital: str) -> dict[str, Any]:
    return {
        "hospital": hospital,
        "date": "2026-09-29",
        "department_code": "MED",
        "clinic_code": "MED-A",
        "session": "morning",
        "patient_number": 85,
        "recipient_ids": ["eligible"],
    }


def _visit_rows(store: SQLiteStore) -> list[tuple]:
    return [
        tuple(row)
        for row in store.connection.execute("SELECT * FROM visits ORDER BY id")
    ]


def test_unknown_hospital_id_is_rejected_on_every_accepting_path_with_no_write():
    async def scenario():
        store, http = make_client()
        try:
            headers = authorize(http)
            created = await http.post(
                "/api/organizer/visits",
                json=_visit_body("ntuh-main"),
                headers=headers,
            )
            assert created.status_code == 201
            visit_id = created.json()["id"]
            before = _visit_rows(store)
            bad = _visit_body(UNKNOWN_HOSPITAL)

            create = await http.post("/api/organizer/visits", json=bad, headers=headers)
            update = await http.patch(
                f"/api/organizer/visits/{visit_id}", json=bad, headers=headers
            )
            correct = await http.post(
                f"/api/organizer/visits/{visit_id}/correct", json=bad, headers=headers
            )
            clinics = await http.get(
                f"/api/organizer/hospitals/{UNKNOWN_HOSPITAL}/clinics",
                params={"department": "OPH", "date": "2026-09-29"},
            )

            for response in (create, update, correct, clinics):
                assert response.status_code == 400
                assert response.json() == {"error": {"code": "invalid_request"}}
            assert _visit_rows(store) == before
        finally:
            await http.aclose()

    asyncio.run(scenario())


UNSUPPORTED_HOSPITAL = "shin-kong-taipei"


def test_unsupported_hospital_is_refused_on_every_draft_path_with_no_write():
    async def scenario():
        store, http = make_client()
        try:
            headers = authorize(http)
            created = await http.post(
                "/api/organizer/visits",
                json=_visit_body("ntuh-main"),
                headers=headers,
            )
            assert created.status_code == 201
            visit_id = created.json()["id"]
            before = _visit_rows(store)
            unsupported = _visit_body(UNSUPPORTED_HOSPITAL)

            create = await http.post(
                "/api/organizer/visits", json=unsupported, headers=headers
            )
            update = await http.patch(
                f"/api/organizer/visits/{visit_id}", json=unsupported, headers=headers
            )
            correct = await http.post(
                f"/api/organizer/visits/{visit_id}/correct",
                json=unsupported,
                headers=headers,
            )

            for response in (create, update, correct):
                assert response.status_code == 400
                assert response.json() == {"error": {"code": "hospital_unsupported"}}
            assert _visit_rows(store) == before
        finally:
            await http.aclose()

    asyncio.run(scenario())


def test_a_hospital_registered_only_in_the_registry_passes_id_validation(
    monkeypatch,
):
    from next_is_you import hospital_registry

    monkeypatch.setattr(
        hospital_registry,
        "HOSPITAL_REGISTRY",
        {
            **hospital_registry.HOSPITAL_REGISTRY,
            "registry-only-test": hospital_registry.HospitalEntry(
                display_name="Registry only",
                reader_type=None,
                official_link="https://registry-only.example/",
            ),
        },
    )
    seen: list[str] = []

    async def list_clinics(self, hospital, department, day, now):
        seen.append(hospital)
        return {"available": False, "reason": "unsupported", "clinics": []}

    monkeypatch.setattr(Gate, "list_clinics", list_clinics, raising=False)

    async def scenario():
        _, http = make_client()
        try:
            authorize(http)
            response = await http.get(
                "/api/organizer/hospitals/registry-only-test/clinics",
                params={"department": "OPH", "date": "2026-09-29"},
            )
            assert response.status_code == 200
            assert seen == ["registry-only-test"]
        finally:
            await http.aclose()

    asyncio.run(scenario())
