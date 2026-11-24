"""Browser acceptance for the two setup states no browser test proved (#116).

Local integration evidence with synthetic hospitals, each labelled
"（僅供測試）". They are not evidence that any real hospital is supported. Each is
registered only for the duration of its test, so neither is reachable in staging
or production. No request leaves the local test server.
"""

from __future__ import annotations

import threading
import time
from datetime import date, timedelta
from typing import Any, Iterator

import pytest
import uvicorn
from playwright.sync_api import Page, expect, sync_playwright

from local_worker import loopback_listener
from next_is_you import hospital_registry
from next_is_you.domain import ClinicRoster
from next_is_you.identity import IdentityRepository
from next_is_you.persistence import VisitRepository
from next_is_you.send_gate import SystemSendGate
from synthetic_hospital import (
    FULL_SCHEDULE_ID,
    FULL_SCHEDULE_NAME,
    UNSUPPORTED_ID,
    UNSUPPORTED_NAME,
    full_schedule_entry,
    unsupported_entry,
)
from test_local_acceptance import (
    NOW,
    NOW_TEXT,
    SECRET,
    LocalContext,
    LocalTestBindingApp,
    SQLiteStore,
)
from worker import create_app

# These journeys serve the built UI from dist/ through create_app.
pytestmark = pytest.mark.usefixtures("built_ui")


class RegistryReaderBindingApp(LocalTestBindingApp):
    """Local test binding that also routes reads through the hospital registry."""

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["path"].startswith(("/__niy006_test/", "/api/", "/auth/")):
            scope = {
                **scope,
                "env": {
                    "NIY006_LOCAL_TEST_MODE": "1",
                    "NIY_ENVIRONMENT": "local-test",
                    "NTUH_READER_ENABLED": "1",
                },
            }
            await self.app(scope, receive, send)
            return
        await self.app(scope, receive, send)


class Journey:
    def __init__(self) -> None:
        self.database = SQLiteStore()
        self.requested: list[str] = []
        self.database.connection.execute(
            """INSERT INTO recipients (
                id, line_subject, display_name, consented_at,
                friendship_checked_at, active, created_at
            ) VALUES ('selected-family', 'U00000000000000000000000000000001',
                'Selected family', ?, ?, 1, ?)""",
            (NOW_TEXT, NOW_TEXT, NOW_TEXT),
        )

    def app(self) -> Any:
        gate = SystemSendGate(
            LocalContext(),
            {
                "DB": self.database,
                "NIY006_LOCAL_TEST_MODE": "1",
                "NIY_ENVIRONMENT": "local-test",
                "NTUH_READER_ENABLED": "1",
            },
        )
        return RegistryReaderBindingApp(
            create_app(
                settings={
                    "session_secret": SECRET,
                    "organizer_subjects": {"niy006-synthetic-organizer"},
                },
                identity_repository=IdentityRepository(self.database),
                visit_repository=VisitRepository(self.database),
                send_gate=gate,
                clock=lambda: NOW.timestamp(),
            )
        )

    def visits(self) -> list[tuple[Any, ...]]:
        rows = self.database.connection.execute(
            "SELECT hospital, visit_date, clinic_code, state FROM visits"
        ).fetchall()
        return [tuple(row) for row in rows]

    def outbound_events(self) -> int:
        return self.database.connection.execute(
            "SELECT COUNT(*) FROM outbound_events"
        ).fetchone()[0]


@pytest.fixture
def journey() -> Iterator[Journey]:
    yield Journey()


def run_in_browser(journey: Journey, steps: Any) -> None:
    with loopback_listener() as (listener, origin):
        server = uvicorn.Server(
            uvicorn.Config(journey.app(), log_level="error", lifespan="off")
        )
        thread = threading.Thread(
            target=server.run, kwargs={"sockets": [listener]}, daemon=True
        )
        thread.start()
        deadline = time.monotonic() + 10
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert server.started, "local HTTP test server did not start"

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
                page.on(
                    "request", lambda request: journey.requested.append(request.url)
                )
                page.goto(origin, wait_until="networkidle")
                page.get_by_role("button", name="本機合成測試登入").click()
                page.locator("#visit-form").wait_for()
                steps(page)
                browser.close()
        finally:
            server.should_exit = True
            thread.join(timeout=10)
            assert not thread.is_alive(), "local HTTP test server did not stop"

    assert all(url.startswith(origin) for url in journey.requested)


def test_unsupported_hospital_cannot_be_selected_or_saved(
    monkeypatch, journey: Journey
) -> None:
    monkeypatch.setitem(
        hospital_registry.HOSPITAL_REGISTRY, UNSUPPORTED_ID, unsupported_entry()
    )

    def steps(page: Page) -> None:
        choice = page.locator("label.choice", has_text=UNSUPPORTED_NAME)
        assert choice.locator("input[name=hospital]").is_disabled()
        assert choice.locator(".choice-note").inner_text() == "尚未支援"
        # Selecting it is impossible: forcing the click leaves it unchecked.
        choice.locator("span").first.click(force=True)
        assert not choice.locator("input[name=hospital]").is_checked()
        # The form stays on the hospital it started with.
        assert (
            page.locator("input[name=hospital]:checked").get_attribute("value")
            != UNSUPPORTED_ID
        )

    run_in_browser(journey, steps)

    assert [row for row in journey.visits() if row[0] == UNSUPPORTED_ID] == []
    assert journey.visits() == []
    assert journey.outbound_events() == 0


def test_failed_clinic_schedule_read_falls_back_to_manual_entry(
    monkeypatch, journey: Journey
) -> None:
    failed_day = (date.today() + timedelta(days=5)).isoformat()
    unpublished_day = (date.today() + timedelta(days=40)).isoformat()
    rosters = {
        failed_day: ClinicRoster(False, (), "timeout"),
        unpublished_day: ClinicRoster(
            False,
            (),
            "visit_date_out_of_schedule_window",
            schedule_end=date.today() + timedelta(days=14),
        ),
    }
    reads: list[str] = []
    monkeypatch.setitem(
        hospital_registry.HOSPITAL_REGISTRY,
        FULL_SCHEDULE_ID,
        full_schedule_entry(rosters, reads),
    )

    def fill_and_save(page: Page, clinic_code: str) -> None:
        page.locator("input[name=clinic_code]").fill(clinic_code)
        page.locator("input[name=patient_number]").fill("85")
        page.locator('input[name=recipient_ids][value="selected-family"]').check()
        page.get_by_role("button", name="建立草稿").click()

    def steps(page: Page) -> None:
        page.locator("#visit-form").get_by_text(FULL_SCHEDULE_NAME, exact=True).click()

        # A failed read: the reader's notice, then manual entry, never an
        # empty doctor dropdown.
        page.locator("input[name=date]").fill(failed_day)
        expect(page.locator(".edit-notice").first).to_contain_text(
            "讀取院方名單逾時，已切換為手動輸入。"
        )
        page.locator("input[name=clinic_code]").wait_for()
        assert page.locator("select[name=clinic_code]").count() == 0
        fill_and_save(page, "A-12")
        page.get_by_role("heading", name="已儲存草稿 1").wait_for()

        # A day the hospital has not published: its own notice, same fallback.
        # Saving resets the form to the default hospital, so choose it again.
        page.locator("#visit-form").get_by_text(FULL_SCHEDULE_NAME, exact=True).click()
        page.locator("input[name=date]").fill(unpublished_day)
        expect(page.locator(".edit-notice").first).to_contain_text("目前只公布到")
        page.locator("input[name=clinic_code]").wait_for()
        assert page.locator("select[name=clinic_code]").count() == 0
        fill_and_save(page, "B-34")
        page.get_by_role("heading", name="已儲存草稿 2").wait_for()

    run_in_browser(journey, steps)

    assert sorted(set(reads)) == sorted([failed_day, unpublished_day])
    assert sorted(journey.visits()) == sorted(
        [
            (FULL_SCHEDULE_ID, failed_day, "A-12", "draft"),
            (FULL_SCHEDULE_ID, unpublished_day, "B-34", "draft"),
        ]
    )
    assert journey.outbound_events() == 0
