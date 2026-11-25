"""Browser acceptance for a hospital that publishes only the current number.

Local integration evidence with a synthetic hospital labelled
"合成醫院（僅供測試）". It is not evidence that any real hospital is supported,
and it is registered only for the duration of this test.
"""

from __future__ import annotations

import threading
import time
from datetime import date, timedelta

import pytest
import uvicorn
from playwright.sync_api import sync_playwright

from local_worker import loopback_listener
from next_is_you import hospital_registry
from next_is_you.identity import IdentityRepository
from next_is_you.persistence import VisitRepository
from next_is_you.send_gate import SystemSendGate
from synthetic_hospital import SYNTHETIC_ID, SYNTHETIC_NAME, synthetic_entry
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


def test_current_number_only_hospital_goes_straight_to_manual_entry(
    monkeypatch,
    screen: dict,
) -> None:
    monkeypatch.setitem(
        hospital_registry.HOSPITAL_REGISTRY, SYNTHETIC_ID, synthetic_entry()
    )
    visit_day = (date.today() + timedelta(days=5)).isoformat()
    database = SQLiteStore()
    database.connection.execute(
        """INSERT INTO recipients (
            id, line_subject, display_name, consented_at,
            friendship_checked_at, active, created_at
        ) VALUES ('selected-family', 'U00000000000000000000000000000001',
            'Selected family', ?, ?, 1, ?)""",
        (NOW_TEXT, NOW_TEXT, NOW_TEXT),
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

    requested: list[str] = []
    with loopback_listener() as (listener, origin):
        server = uvicorn.Server(
            uvicorn.Config(LocalTestBindingApp(app), log_level="error", lifespan="off")
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
                context = browser.new_context(**screen)
                context.route(
                    "**/*",
                    lambda route: (
                        route.continue_()
                        if route.request.url.startswith(origin)
                        else route.abort()
                    ),
                )
                page = context.new_page()
                page.on("request", lambda request: requested.append(request.url))
                page.goto(origin, wait_until="networkidle")
                page.get_by_role("button", name="本機合成測試登入").click()
                page.locator("#visit-form").wait_for()

                page.get_by_text(SYNTHETIC_NAME, exact=True).click()
                page.locator("input[name=date]").fill(visit_day)
                # Straight to manual entry: no dropdown, no loading state, and
                # the hospital's own clinic-code label.
                page.locator("input[name=clinic_code]").wait_for()
                assert page.locator("select[name=clinic_code]").count() == 0
                assert (
                    "這家醫院沒有公布門診表"
                    in page.locator(".edit-notice").first.inner_text()
                )
                assert "診間代碼" in page.locator(".source-ref").inner_text()
                page.locator("input[name=patient_number]").fill("85")
                page.locator("input[name=clinic_code]").fill("A-12")
                page.locator(
                    'input[name=recipient_ids][value="selected-family"]'
                ).check()
                page.get_by_role("button", name="建立草稿").click()
                page.get_by_role("heading", name="已儲存草稿 1").wait_for()
                browser.close()
        finally:
            server.should_exit = True
            thread.join(timeout=10)
            assert not thread.is_alive(), "local HTTP test server did not stop"

    assert not [url for url in requested if "/clinics" in url]
    saved = database.connection.execute(
        "SELECT hospital, visit_date, clinic_code, state FROM visits"
    ).fetchall()
    assert [tuple(row) for row in saved] == [(SYNTHETIC_ID, visit_day, "A-12", "draft")]
    assert (
        database.connection.execute("SELECT COUNT(*) FROM outbound_events").fetchone()[
            0
        ]
        == 0
    )
