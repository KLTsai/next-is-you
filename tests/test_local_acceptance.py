from __future__ import annotations

import asyncio
import json
import sqlite3
import socket
import threading
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from httpx import ASGITransport, AsyncClient
from playwright.sync_api import expect, sync_playwright
import uvicorn

from next_is_you.auth import CSRF_COOKIE_NAME
from next_is_you.domain import ClinicScope, ClinicSession
from next_is_you.source_samples import ParseStatus, parse_ntuh_fragment
from next_is_you.identity import IdentityRepository
from next_is_you.persistence import Statement, VisitRepository
from next_is_you.send_gate import SystemSendGate
from worker import create_app


ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = sorted((ROOT / "migrations").glob("*.sql"))
SECRET = "local-acceptance-secret-with-more-than-32-bytes"
NOW = datetime(2026, 9, 27, 13, 1, tzinfo=timezone.utc)
NOW_TEXT = "2026-09-27T13:01:00Z"


class Prepared:
    def __init__(
        self, database: "SQLiteStore", sql: str, values: tuple[Any, ...] = ()
    ) -> None:
        self.database = database
        self.sql = sql
        self.values = values

    def bind(self, *values: Any) -> "Prepared":
        return Prepared(self.database, self.sql, values)

    async def run(self) -> dict[str, Any]:
        cursor = self.database.connection.execute(self.sql, self.values)
        return {"meta": {"changes": cursor.rowcount}}

    async def all(self) -> dict[str, Any]:
        cursor = self.database.connection.execute(self.sql, self.values)
        return {"results": [dict(row) for row in cursor.fetchall()]}


class SQLiteStore:
    def __init__(self) -> None:
        self.connection = sqlite3.connect(
            ":memory:", isolation_level=None, check_same_thread=False
        )
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        for migration in MIGRATIONS:
            self.connection.executescript(migration.read_text(encoding="utf-8"))

    def prepare(self, sql: str) -> Prepared:
        return Prepared(self, sql)

    async def execute(self, statement: Statement) -> int:
        return self.connection.execute(statement.sql, statement.values).rowcount

    async def fetch_all(self, statement: Statement) -> list[Mapping[str, Any]]:
        return [
            dict(row)
            for row in self.connection.execute(statement.sql, statement.values)
        ]

    async def batch(self, statements: Sequence[Statement]) -> list[int]:
        self.connection.execute("BEGIN")
        try:
            results = [await self.execute(statement) for statement in statements]
        except Exception:
            self.connection.execute("ROLLBACK")
            raise
        self.connection.execute("COMMIT")
        return results


class LocalStorage:
    def __init__(self) -> None:
        self.values: dict[str, Any] = {}

    async def get(self, key: str) -> Any:
        return self.values.get(key)

    async def put(self, key: str, value: Any) -> None:
        self.values[key] = value


class LocalContext:
    def __init__(self) -> None:
        self.storage = LocalStorage()


class LocalTestBindingApp:
    """Enable only the explicit test binding for this in-process HTTP app."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["path"].startswith(("/__niy006_test/", "/api/", "/auth/")):
            scope = {
                **scope,
                "env": {"NIY006_LOCAL_TEST_MODE": "1", "NIY_ENVIRONMENT": "local-test"},
            }
        await self.app(scope, receive, send)


def test_local_http_acceptance_journey() -> None:
    async def scenario() -> None:
        database = SQLiteStore()
        database.connection.execute(
            """INSERT INTO recipients (
                id, line_subject, display_name, consented_at,
                friendship_checked_at, active, created_at
            ) VALUES
                ('selected-family', 'U00000000000000000000000000000001', 'Selected family', ?, ?, 1, ?),
                ('unselected-family', 'U00000000000000000000000000000002', 'Unselected family', ?, ?, 1, ?)""",
            (NOW_TEXT, NOW_TEXT, NOW_TEXT, NOW_TEXT, NOW_TEXT, NOW_TEXT),
        )
        gate = SystemSendGate(
            LocalContext(),
            {
                "DB": database,
                "NIY006_LOCAL_TEST_MODE": "1",
                "NIY_ENVIRONMENT": "local-test",
            },
        )
        visits = VisitRepository(database)
        app = create_app(
            settings={
                "session_secret": SECRET,
                "organizer_subjects": {"niy006-synthetic-organizer"},
            },
            identity_repository=IdentityRepository(database),
            visit_repository=visits,
            send_gate=gate,
            clock=lambda: NOW.timestamp(),
        )
        transport = ASGITransport(app=LocalTestBindingApp(app))
        async with AsyncClient(
            transport=transport, base_url="https://family.example"
        ) as http:
            page = await http.get("/")
            assert page.status_code == 200
            assert 'id="app"' in page.text

            login = await http.post("/__niy006_test/organizer-session", json={})
            assert login.status_code == 200
            csrf = http.cookies[CSRF_COOKIE_NAME]
            headers = {"x-csrf-token": csrf}
            recipients = await http.get("/api/organizer/recipients")
            assert recipients.json() == {
                "recipients": [
                    {"id": "selected-family", "display_name": "Selected family"},
                    {"id": "unselected-family", "display_name": "Unselected family"},
                ],
            }

            # The frontend learns the hospitals and their capability from the
            # backend, not from constants of its own.
            hospitals = await http.get("/api/organizer/hospitals")
            assert hospitals.json() == {
                "hospitals": [
                    {
                        "hospital": "ntuh-main",
                        "display_name": "臺大醫院總院",
                        "capability": "full_schedule",
                        "source_url": (
                            "https://registration.ntuh.gov.tw/WebReg/WebReg/"
                            "ClinicCurrentLightNo?vHospCode=T0"
                        ),
                        "clinic_code_labels": ["診間", "醫師", "門診別"],
                        "departments": [{"code": "OPH", "display_name": "眼科"}],
                    },
                    {
                        "hospital": "shin-kong-taipei",
                        "display_name": "新光醫院（台北）",
                        "capability": "unsupported",
                        "source_url": "https://reg.skh.org.tw/",
                        "clinic_code_labels": [],
                        "departments": [],
                    },
                ],
            }
            # With reads held (no reader configured here) the roster is simply
            # unavailable, so the picker degrades to manual entry.
            held_roster = await http.get(
                "/api/organizer/hospitals/ntuh-main/clinics"
                "?department=OPH&date=2026-09-28"
            )
            assert held_roster.status_code == 200
            assert held_roster.json() == {
                "available": False,
                "reason": "no_observation",
                "clinics": [],
            }
            # A malformed hospital is rejected before reaching the gate.
            bad_roster = await http.get(
                "/api/organizer/hospitals/not-a-hospital/clinics"
                "?department=OPH&date=2026-09-28"
            )
            assert bad_roster.status_code == 400

            created = await http.post(
                "/api/organizer/visits",
                headers=headers,
                json={
                    "hospital": "ntuh-main",
                    "date": "2026-09-28",
                    "department_code": "MED",
                    "clinic_code": "MED-101",
                    "session": "afternoon",
                    "patient_number": 85,
                    "recipient_ids": ["selected-family"],
                },
            )
            assert created.status_code == 201
            visit_id = created.json()["id"]

            fixture_scope = ClinicScope(
                hospital="ntuh-main",
                visit_date=date(2026, 9, 27),
                department_code="MED",
                clinic_code="MED-101",
                session=ClinicSession.AFTERNOON,
                doctor_code="D-01",
                room_code="101診",
            )
            fixture = (ROOT / "tests/fixtures/hospitals/ntuh_main.html").read_text()
            parsed = parse_ntuh_fragment(
                fixture,
                fixture_scope,
                observed_at="2026-09-27T13:01:00+08:00",
            )
            assert parsed.status is ParseStatus.MATCHED
            assert parsed.observation is not None
            assert parsed.observation.current_number == 82
            assert parsed.observation.trustworthy_current is False
            assert parsed.observation.is_comparable_to(fixture_scope) is False

            unavailable_start = await http.post(
                f"/api/organizer/visits/{visit_id}/start", headers=headers
            )
            assert unavailable_start.status_code == 503
            assert unavailable_start.json() == {
                "error": {"code": "observation_unavailable"}
            }

            configured = await http.post(
                "/__niy006_test/observation",
                json={"current_number": 82, "trustworthy": True},
            )
            assert configured.json() == {"configured": True}
            started = await http.post(
                f"/api/organizer/visits/{visit_id}/start", headers=headers
            )
            assert started.status_code == 200
            assert started.json() == {"state": "active"}

            for current in (85, 86):
                await http.post(
                    "/__niy006_test/observation",
                    json={"current_number": current, "trustworthy": True},
                )
                tick = await http.post("/__niy006_test/tick", json={"now": NOW_TEXT})
                assert tick.json()["events_created"] == 0
            await http.post(
                "/__niy006_test/observation",
                json={"current_number": 82, "trustworthy": True},
            )
            first_alert = await http.post("/__niy006_test/tick", json={"now": NOW_TEXT})
            assert first_alert.json()["events_created"] == 1
            repeated = await http.post(
                "/__niy006_test/tick",
                json={"now": "2026-09-27T13:02:00Z"},
            )
            assert repeated.json()["events_created"] == 0

            snapshot = await http.post("/__niy006_test/snapshot", json={})
            events = snapshot.json()["events"]
            requests = snapshot.json()["line_requests"]
            assert [
                (event["recipient_id"], event["event_kind"]) for event in events
            ] == [("selected-family", "near")]
            assert len(requests) == 1, (snapshot.json(), first_alert.json())
            assert requests[0]["outbox_persisted"] is True
            assert (
                database.connection.execute(
                    "SELECT COUNT(*) FROM outbound_events WHERE visit_id = ?",
                    (visit_id,),
                ).fetchone()[0]
                == 1
            )

            stopped = await http.post(
                f"/api/organizer/visits/{visit_id}/stop", headers=headers
            )
            assert stopped.status_code == 200
            assert stopped.json() == {"state": "stopped"}
            await http.post(
                "/__niy006_test/observation",
                json={"current_number": 82, "trustworthy": True},
            )
            after_stop = await http.post(
                "/__niy006_test/tick",
                json={"now": "2026-09-27T13:03:00Z"},
            )
            assert after_stop.json()["events_created"] == 0
            final_snapshot = await http.post("/__niy006_test/snapshot", json={})
            assert len(final_snapshot.json()["line_requests"]) == 1

    asyncio.run(scenario())


def test_local_browser_acceptance_journey() -> None:
    # The cascading form validates against the browser's real date, so use a
    # clearly-future appointment day (manual-entry mode, since the day is not
    # today) and a synthetic clinic in the required 診間/醫師/門診別 format.
    visit_day = (date.today() + timedelta(days=2)).isoformat()
    clinic_code = "11 診/合成醫師丙/醫師約診"
    heading_text = f"{visit_day} · OPH · {clinic_code}"
    database = SQLiteStore()
    database.connection.execute(
        """INSERT INTO recipients (
            id, line_subject, display_name, consented_at,
            friendship_checked_at, active, created_at
        ) VALUES
            ('selected-family', 'U00000000000000000000000000000001', 'Selected family', ?, ?, 1, ?),
            ('unselected-family', 'U00000000000000000000000000000002', 'Unselected family', ?, ?, 1, ?)""",
        (NOW_TEXT, NOW_TEXT, NOW_TEXT, NOW_TEXT, NOW_TEXT, NOW_TEXT),
    )
    gate = SystemSendGate(
        LocalContext(),
        {
            "DB": database,
            "NIY006_LOCAL_TEST_MODE": "1",
            "NIY_ENVIRONMENT": "local-test",
        },
    )
    app = create_app(
        settings={
            "session_secret": SECRET,
            "organizer_subjects": {"niy006-synthetic-organizer"},
        },
        identity_repository=IdentityRepository(database),
        visit_repository=VisitRepository(database),
        send_gate=gate,
        clock=lambda: NOW.timestamp(),
    )

    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        server = uvicorn.Server(
            uvicorn.Config(
                LocalTestBindingApp(app),
                log_level="error",
                lifespan="off",
            )
        )
        thread = threading.Thread(
            target=server.run,
            kwargs={"sockets": [listener]},
            daemon=True,
        )
        thread.start()
        deadline = time.monotonic() + 10
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert server.started, "local HTTP test server did not start"

        origin = f"http://127.0.0.1:{port}"
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                context = browser.new_context()
                context.route(
                    "**/*",
                    lambda route: (
                        route.continue_()
                        if route.request.url.startswith(origin)
                        else route.abort()
                    ),
                )
                page = context.new_page()
                page.goto(origin, wait_until="networkidle")
                page.get_by_role("button", name="本機合成測試登入").click()
                page.locator("#visit-form").wait_for()

                # 眼科 (OPH) is the only supported department, pre-selected in the
                # catalog-driven dropdown; the clinic is entered manually.
                page.locator("input[name=date]").fill(visit_day)
                page.locator("input[name=clinic_code]").wait_for()
                page.locator("input[name=patient_number]").fill("85")
                page.locator("input[name=clinic_code]").fill(clinic_code)
                page.locator('select[name="session"]').select_option("afternoon")
                page.locator(
                    'input[name=recipient_ids][value="selected-family"]'
                ).check()
                page.get_by_role("button", name="建立草稿").click()
                toggle = page.get_by_role("button", name="展開草稿")
                assert toggle.get_attribute("aria-expanded") == "false"
                assert toggle.get_attribute("aria-controls") == "saved-drafts-list"
                draft_count = page.get_by_role("heading", name="已儲存草稿 1")
                draft_count.wait_for()
                assert draft_count.is_visible()
                assert page.locator("#saved-drafts-list").is_hidden()
                csrf_token = page.evaluate(
                    "document.cookie.split('; ').find((cookie) => cookie.startsWith('__Host-ny_csrf='))?.split('=')[1]"
                )
                assert csrf_token
                second_draft = page.evaluate(
                    """async (csrf) => (await fetch('/api/organizer/visits', {
                        method: 'POST',
                        headers: {'content-type': 'application/json', 'x-csrf-token': csrf},
                        body: JSON.stringify({
                            hospital: 'ntuh-main', date: '2026-09-30',
                            department_code: 'SYN2', clinic_code: 'SYN-2',
                            session: 'morning', patient_number: 91,
                            recipient_ids: ['unselected-family'],
                        }),
                    })).status""",
                    csrf_token,
                )
                assert second_draft == 201
                page.get_by_role("button", name="重新整理").click()
                draft_count = page.get_by_role("heading", name="已儲存草稿 2")
                draft_count.wait_for()
                assert draft_count.is_visible()
                toggle = page.get_by_role("button", name="展開草稿")
                toggle.focus()
                page.keyboard.press("Enter")
                toggle = page.get_by_role("button", name="收合草稿")
                assert toggle.get_attribute("aria-expanded") == "true"
                drafts = page.locator("#saved-drafts-list article.visit-card")
                assert drafts.count() == 2
                assert sorted(drafts.locator("h3").all_text_contents()) == sorted(
                    [heading_text, "2026-09-30 · SYN2 · SYN-2"]
                )
                toggle.focus()
                page.keyboard.press("Enter")
                toggle = page.get_by_role("button", name="展開草稿")
                assert page.locator("#saved-drafts-list").is_hidden()
                assert toggle.evaluate(
                    "(element) => element === document.activeElement"
                )
                toggle.click()
                first_draft = page.locator(
                    "#saved-drafts-list article.visit-card"
                ).filter(has_text=heading_text)
                first_visit = page.locator("article.visit-card").filter(
                    has_text=heading_text
                )
                visit_heading = first_draft.locator('h3[id^="visit-"]')
                visit_heading.wait_for()
                assert heading_text in visit_heading.inner_text()
                assert (
                    first_draft.get_by_text("Selected family", exact=True).count() == 1
                )
                assert page.get_by_text("來源暫不可用", exact=False).count() >= 1

                page.locator('input[name="patient_number"]').fill("5")
                first_draft.get_by_role("button", name="修正草稿").click()
                page.get_by_text(
                    "目前設定尚未儲存。請先儲存或取消修正，再開啟其他提醒。", exact=True
                ).wait_for()
                page.get_by_role("button", name="清除未儲存草稿").click()
                assert page.locator('input[name="patient_number"]').input_value() == ""

                first_draft.get_by_role("button", name="重新檢查並開始提醒").click()
                page.get_by_text(
                    "目前沒有可用的可信院方觀察，提醒維持草稿。"
                ).first.wait_for()
                assert "草稿" in first_draft.locator(".state").inner_text()

                # The general projection omits patient_number. The selected-draft
                # correction request supplies it, and Cancel then reopening must
                # restore that saved value.
                first_draft.get_by_role("button", name="修正草稿").click()
                page.wait_for_function(
                    "document.querySelector('input[name=patient_number]')?.value === '85'"
                )
                assert (
                    page.locator('select[name="department_code"]').input_value()
                    == "OPH"
                )
                assert (
                    page.locator('input[name="clinic_code"]').input_value()
                    == clinic_code
                )
                assert (
                    page.locator('select[name="session"]').input_value() == "afternoon"
                )
                assert (
                    page.locator('input[name="patient_number"]').input_value() == "85"
                )
                page.get_by_role("button", name="收合草稿").click()
                assert page.locator("#saved-drafts-list").is_hidden()
                page.get_by_role("button", name="展開草稿").click()
                assert (
                    page.locator('input[name="patient_number"]').input_value() == "85"
                )
                assert (
                    page.locator('input[name="clinic_code"]').input_value()
                    == clinic_code
                )
                page.locator('input[name="clinic_code"]').fill("臨時變更/未存/門診")
                page.get_by_role("button", name="重新整理").click()
                assert (
                    page.locator('input[name="clinic_code"]').input_value()
                    == "臨時變更/未存/門診"
                )
                page.get_by_role("button", name="取消修正").click()
                page.locator('select[name="department_code"]').wait_for()
                assert (
                    page.locator('select[name="department_code"]').input_value()
                    == "OPH"
                )
                assert heading_text in first_draft.locator("h3").inner_text()

                first_draft.get_by_role("button", name="修正草稿").click()
                page.wait_for_function(
                    "document.querySelector('input[name=patient_number]')?.value === '85'"
                )
                page.locator('input[name="patient_number"]').fill("85")
                page.locator('select[name="session"]').select_option("evening")
                page.get_by_role("button", name="儲存草稿").click()
                page.get_by_text(
                    "草稿修改已儲存。請在提醒清單重新檢查並開始。", exact=True
                ).wait_for()
                # The saved message renders before the list reload completes, so
                # wait for the card to reflect the new session rather than asserting
                # immediately.
                expect(
                    page.get_by_text("晚診（evening）", exact=True).first
                ).to_be_visible()

                configured = page.request.post(
                    f"{origin}/__niy006_test/observation",
                    data={"current_number": 82, "trustworthy": True},
                )
                assert configured.status == 200
                first_draft.get_by_role("button", name="重新檢查並開始提醒").click()
                page.get_by_text("監控中", exact=True).wait_for()
                assert (
                    page.locator("#saved-drafts-list article.visit-card").count() == 1
                )
                assert (
                    page.locator(
                        "section.visits:not(.saved-drafts) article.visit-card"
                    ).count()
                    == 1
                )
                assert (
                    page.get_by_text(
                        "停止確認後，系統會停止後續檢查與通知。", exact=False
                    ).count()
                    == 1
                )

                for current, tick_at in (
                    (85, NOW_TEXT),
                    (86, "2026-09-27T13:02:00Z"),
                    (82, "2026-09-27T13:03:00Z"),
                ):
                    page.request.post(
                        f"{origin}/__niy006_test/observation",
                        data={"current_number": current, "trustworthy": True},
                    )
                    page.request.post(
                        f"{origin}/__niy006_test/tick", data={"now": tick_at}
                    )

                stop_route = "**/api/organizer/visits/*/stop"
                page.route(stop_route, lambda route: route.abort())
                first_visit.get_by_role("button", name="停止提醒").click()
                page.get_by_text("連線失敗，請確認服務後重試。", exact=True).wait_for()
                assert first_visit.locator(".state").inner_text() == "監控中"
                assert first_visit.get_by_role("button", name="停止提醒").is_visible()
                page.unroute(stop_route)

                first_visit.get_by_role("button", name="停止提醒").click()
                first_visit.locator(".inline-state").filter(
                    has_text="已停止"
                ).wait_for()
                visit_id = first_visit.locator('h3[id^="visit-"]').get_attribute("id")
                first_visit.get_by_role("button", name="修正後重新檢查").click()
                page.wait_for_function(
                    "document.querySelector('input[name=patient_number]')?.value === '85'"
                )
                assert page.locator("#setup-heading").inner_text() == "修正已停止的提醒"
                assert page.locator(
                    'input[name="recipient_ids"][value="selected-family"]'
                ).is_checked()
                page.locator('input[name="patient_number"]').fill("85")
                page.get_by_role("button", name="收合草稿").click()
                assert page.locator("#saved-drafts-list").is_hidden()
                page.get_by_role("button", name="展開草稿").click()
                assert (
                    page.locator('input[name="patient_number"]').input_value() == "85"
                )
                assert (
                    page.locator('select[name="department_code"]').input_value()
                    == "OPH"
                )
                page.get_by_role("button", name="儲存修正並回到草稿").click()
                page.get_by_text(
                    "修正已儲存為草稿。請在提醒清單重新檢查並開始。", exact=True
                ).wait_for()
                assert (
                    first_draft.locator('h3[id^="visit-"]').get_attribute("id")
                    == visit_id
                )
                assert "草稿" in first_draft.locator(".state").inner_text()
                page.request.post(
                    f"{origin}/__niy006_test/observation",
                    data={"current_number": 82, "trustworthy": True},
                )
                page.request.post(
                    f"{origin}/__niy006_test/tick",
                    data={"now": "2026-09-27T13:04:00Z"},
                )
                browser.close()
        finally:
            server.should_exit = True
            thread.join(timeout=10)
            assert not thread.is_alive(), "local HTTP test server did not stop"

    assert [
        tuple(row)
        for row in database.connection.execute(
            "SELECT recipient_id, event_kind, outcome FROM outbound_events"
        ).fetchall()
    ] == [("selected-family", "near", "accepted")]
    requests = json.loads(gate.ctx.storage.values["test_line_requests"])
    assert len(requests) == 1
    assert requests[0]["outbox_persisted"] is True
