from __future__ import annotations

import os
import pty
import signal
import socket
import subprocess
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen
from zoneinfo import ZoneInfo

import pytest
from playwright.sync_api import expect, sync_playwright


ROOT = Path(__file__).resolve().parents[1]


@contextmanager
def rehearsal(tmp_path, port):
    environment = {
        **os.environ,
        "NIY_REHEARSAL_STATE": str(tmp_path / "state"),
        "NIY_REHEARSAL_PORT": str(port),
    }
    environment.pop("CI", None)
    master, terminal = pty.openpty()
    output = []

    def read_terminal():
        try:
            while chunk := os.read(master, 65536):
                output.append(chunk.decode(errors="replace"))
        except OSError:
            pass  # The terminal closes after the foreground process exits.

    reader = threading.Thread(target=read_terminal)
    try:
        process = subprocess.Popen(
            ["npm", "run", "dev:rehearsal"],
            cwd=ROOT,
            env=environment,
            stdin=terminal,
            stdout=terminal,
            stderr=terminal,
            start_new_session=True,
        )
        os.close(terminal)
        reader.start()
        origin = f"http://127.0.0.1:{port}"
        try:
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise AssertionError("Rehearsal exited:\n" + "".join(output))
                try:
                    with urlopen(origin + "/api/healthz", timeout=1) as response:
                        if response.status == 200:
                            break
                except (OSError, URLError):
                    pass
                time.sleep(0.25)
            else:
                raise AssertionError("Rehearsal startup timed out:\n" + "".join(output))
            yield origin
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGINT)
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=10)
    finally:
        reader.join(timeout=10)
        os.close(master)
        (tmp_path / "server.log").write_text("".join(output))
        assert not reader.is_alive(), "Rehearsal left a terminal reader running"


def control(page, origin, operation, data=None):
    response = page.request.post(
        origin + "/__niy006_test/" + operation, data=data or {}
    )
    assert response.ok, response.text()
    return response.json() if response.status != 204 else {}


def test_rehearsal_empty_dashboard_keeps_reminder_status_list_visible(tmp_path):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = int(listener.getsockname()[1])
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(viewport={"width": 1280, "height": 900})
        origin = f"http://127.0.0.1:{port}"
        context.route(
            "**/*",
            lambda route: (
                route.continue_()
                if route.request.url.startswith(origin + "/")
                else route.abort()
            ),
        )
        page = context.new_page()
        try:
            with rehearsal(tmp_path, port):
                page.goto(origin)
                page.get_by_role("button", name="本機合成測試登入").click()
                status_list = page.get_by_role("region", name="提醒清單")
                expect(status_list).to_be_visible()
                expect(status_list).to_contain_text("尚無提醒狀態")
        finally:
            context.close()
            browser.close()


def test_rehearsal_started_reminder_keeps_its_last_recipient(tmp_path):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = int(listener.getsockname()[1])
    day = (datetime.now(timezone.utc) + timedelta(days=1)).date().isoformat()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context()
        origin = f"http://127.0.0.1:{port}"
        context.route(
            "**/*",
            lambda route: (
                route.continue_()
                if route.request.url.startswith(origin + "/")
                else route.abort()
            ),
        )
        page = context.new_page()
        try:
            with rehearsal(tmp_path, port):
                control(
                    page,
                    origin,
                    "seed",
                    {
                        "visit_id": "rehearsal-remove-recipient",
                        "recipient_id": "rehearsal-removable-recipient",
                        "visit_day": day,
                        "patient_number": 85,
                        "now": datetime.now(timezone.utc).isoformat(),
                    },
                )
                page.goto(origin)
                page.get_by_role("button", name="本機合成測試登入").click()
                control(
                    page,
                    origin,
                    "observation",
                    {"current_number": 82, "trustworthy": True},
                )
                assert page.request.get(origin + "/cdn-cgi/local/scheduled").ok
                page.get_by_role("button", name="重新整理").click()
                card = page.locator(
                    '[aria-labelledby="visit-rehearsal-remove-recipient"]'
                )
                expect(card).to_contain_text("掛號序號")
                expect(card).to_contain_text("85")
                visits = page.evaluate(
                    "async () => (await fetch('/api/organizer/visits')).json()"
                )["visits"]
                checking = next(
                    visit
                    for visit in visits
                    if visit["id"] == "rehearsal-remove-recipient"
                )["observation"]["checked_at"]
                expected_checked_at = (
                    datetime.fromisoformat(checking.replace("Z", "+00:00"))
                    .astimezone(ZoneInfo("Asia/Taipei"))
                    .strftime("%Y/%m/%d %H:%M")
                )
                expect(card).to_contain_text(expected_checked_at)
                expect(card).not_to_contain_text(checking)
                remove = card.locator(
                    '[data-remove-visit="rehearsal-remove-recipient"]'
                    '[data-remove-recipient="rehearsal-removable-recipient"]'
                )
                expect(remove).to_be_visible()
                expect(remove).to_be_disabled()
                expect(card).to_contain_text("至少保留一位通知對象")
                visits = page.evaluate(
                    "async () => (await fetch('/api/organizer/visits')).json()"
                )["visits"]
                retained = next(
                    visit
                    for visit in visits
                    if visit["id"] == "rehearsal-remove-recipient"
                )
                assert retained["state"] == "active"
                assert [recipient["id"] for recipient in retained["recipients"]] == [
                    "rehearsal-removable-recipient"
                ]
        finally:
            context.close()
            browser.close()


def test_rehearsal_stop_shows_stopping_while_fake_line_request_is_in_flight(tmp_path):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = int(listener.getsockname()[1])
    day = (datetime.now(timezone.utc) + timedelta(days=1)).date().isoformat()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context()
        origin = f"http://127.0.0.1:{port}"
        fail_next_visits = False

        def route_request(route):
            nonlocal fail_next_visits
            url = route.request.url
            if not url.startswith(origin + "/"):
                route.abort()
            elif url.endswith("/stop"):
                fail_next_visits = True
                route.continue_()
            elif url.endswith("/api/organizer/visits") and fail_next_visits:
                fail_next_visits = False
                route.fulfill(
                    status=503,
                    content_type="application/json",
                    body='{"error":{"code":"service_unavailable"}}',
                )
            else:
                route.continue_()

        context.route("**/*", route_request)
        page = context.new_page()
        request_waiting = False
        try:
            with rehearsal(tmp_path, port):
                control(
                    page,
                    origin,
                    "seed",
                    {
                        "visit_id": "rehearsal-stop-in-flight",
                        "recipient_id": "rehearsal-stop-recipient",
                        "visit_day": day,
                        "patient_number": 85,
                        "now": datetime.now(timezone.utc).isoformat(),
                    },
                )
                page.goto(origin)
                page.get_by_role("button", name="本機合成測試登入").click()
                control(
                    page,
                    origin,
                    "observation",
                    {"current_number": 82, "trustworthy": True},
                )
                control(page, origin, "line-mode", {"mode": "wait"})
                page.evaluate(
                    "() => { window.scheduledRequest = fetch('/cdn-cgi/local/scheduled'); }"
                )
                control(page, origin, "wait-request")
                request_waiting = True
                try:
                    card = page.locator(
                        '[aria-labelledby="visit-rehearsal-stop-in-flight"]'
                    )
                    card.locator('[data-stop="rehearsal-stop-in-flight"]').click()
                    expect(card.locator(".state")).to_have_text("停止中")
                    expect(card).to_contain_text("停止請求處理中")
                    expect(
                        page.get_by_role("status").filter(has_text="將自動重試")
                    ).to_be_visible()
                    expect(card.locator(".state")).to_have_text("停止中")
                    visits = page.evaluate(
                        "async () => (await fetch('/api/organizer/visits')).json()"
                    )["visits"]
                    stopping = next(
                        visit
                        for visit in visits
                        if visit["id"] == "rehearsal-stop-in-flight"
                    )
                    assert stopping["state"] == "stopping"
                    control(page, origin, "release-request")
                    request_waiting = False
                finally:
                    if request_waiting:
                        control(page, origin, "release-request")
                assert (
                    page.evaluate("async () => (await window.scheduledRequest).status")
                    == 200
                )
                expect(card.locator(".state")).to_have_text("已停止")
                visits = page.evaluate(
                    "async () => (await fetch('/api/organizer/visits')).json()"
                )["visits"]
                stopped = next(
                    visit
                    for visit in visits
                    if visit["id"] == "rehearsal-stop-in-flight"
                )
                assert stopped["state"] == "stopped"
                snapshot = control(page, origin, "snapshot")
                assert not snapshot["held"]
                assert len(snapshot["events"]) == len(snapshot["line_requests"]) == 1
                assert snapshot["events"][0]["outcome"] == "accepted"
                assert page.request.get(origin + "/cdn-cgi/local/scheduled").ok
                assert control(page, origin, "snapshot") == snapshot
        finally:
            context.close()
            browser.close()


def test_rehearsal_stopped_correction_cannot_add_recipients(tmp_path):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = int(listener.getsockname()[1])
    day = (datetime.now(timezone.utc) + timedelta(days=1)).date().isoformat()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context()
        origin = f"http://127.0.0.1:{port}"
        context.route(
            "**/*",
            lambda route: (
                route.continue_()
                if route.request.url.startswith(origin + "/")
                else route.abort()
            ),
        )
        page = context.new_page()
        try:
            with rehearsal(tmp_path, port):
                control(
                    page,
                    origin,
                    "seed",
                    {
                        "visit_id": "rehearsal-other",
                        "recipient_id": "rehearsal-other-recipient",
                        "visit_day": day,
                        "patient_number": 85,
                        "now": datetime.now(timezone.utc).isoformat(),
                    },
                )
                control(
                    page,
                    origin,
                    "stop",
                    {
                        "visit_id": "rehearsal-other",
                        "now": datetime.now(timezone.utc).isoformat(),
                    },
                )
                control(
                    page,
                    origin,
                    "seed",
                    {
                        "visit_id": "rehearsal-no-add",
                        "recipient_id": "rehearsal-selected-recipient",
                        "visit_day": day,
                        "patient_number": 85,
                        "now": datetime.now(timezone.utc).isoformat(),
                    },
                )
                page.goto(origin)
                page.get_by_role("button", name="本機合成測試登入").click()
                stopped_card = page.locator(
                    '[aria-labelledby="visit-rehearsal-no-add"]'
                )
                page.locator('[data-stop="rehearsal-no-add"]').click()
                expect(stopped_card).to_contain_text("掛號序號")
                expect(stopped_card).to_contain_text("85")
                page.locator('[data-correct="rehearsal-no-add"]').click()
                expect(
                    page.get_by_role("heading", name="修正已停止的提醒")
                ).to_be_visible(timeout=15000)
                choices = page.locator('#visit-form input[name="recipient_ids"]')
                expect(choices).to_have_count(1)
                expect(choices).to_have_value("rehearsal-selected-recipient")
                expect(choices).to_be_checked()
                expect(page.locator("#visit-form")).to_contain_text("不能新增通知對象")
        finally:
            context.close()
            browser.close()


def test_rehearsal_expired_reminder_can_be_corrected_and_restarted_without_duplicate_alert(
    tmp_path,
):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = int(listener.getsockname()[1])
    day = (datetime.now(timezone.utc) + timedelta(days=1)).date().isoformat()
    next_day = (datetime.fromisoformat(day) + timedelta(days=1)).date().isoformat()
    expired_at = datetime.fromisoformat(day).replace(tzinfo=timezone.utc) + timedelta(
        hours=16
    )
    next_day_cutoff = datetime.fromisoformat(next_day).replace(
        tzinfo=timezone.utc
    ) + timedelta(hours=15, minutes=59)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context()
        origin = f"http://127.0.0.1:{port}"
        context.route(
            "**/*",
            lambda route: (
                route.continue_()
                if route.request.url.startswith(origin + "/")
                else route.abort()
            ),
        )
        page = context.new_page()
        try:
            with rehearsal(tmp_path, port):
                control(
                    page,
                    origin,
                    "observation",
                    {"current_number": 70, "trustworthy": True},
                )
                control(
                    page,
                    origin,
                    "seed",
                    {
                        "visit_id": "rehearsal-expired-restart",
                        "recipient_id": "rehearsal-expired-recipient",
                        "visit_day": day,
                        "patient_number": 85,
                        "now": datetime.now(timezone.utc).isoformat(),
                    },
                )
                page.goto(origin)
                page.get_by_role("button", name="本機合成測試登入").click()
                control(
                    page,
                    origin,
                    "observation",
                    {"current_number": 82, "trustworthy": True},
                )
                assert page.request.get(origin + "/cdn-cgi/local/scheduled").ok
                first = control(page, origin, "snapshot")
                assert len(first["events"]) == len(first["line_requests"]) == 1
                assert first["events"][0]["event_kind"] == "near"
                control(page, origin, "tick", {"now": expired_at.isoformat()})
                page.get_by_role("button", name="重新整理").click()
                card = page.locator(
                    '[aria-labelledby="visit-rehearsal-expired-restart"]'
                )
                expect(card.locator(".state")).to_have_text("已結束", timeout=15000)
                expect(card).to_contain_text("掛號序號")
                expect(card).to_contain_text("85")
                expect(card).to_contain_text("可重新檢查並啟動")
                correction = card.locator('[data-correct="rehearsal-expired-restart"]')
                expect(correction).to_be_visible()
                correction.click()
                expect(
                    page.get_by_role("heading", name="修正已結束的提醒")
                ).to_be_visible(timeout=15000)
                page.locator('input[name="date"]').fill(next_day)
                page.get_by_role("button", name="儲存修正並回到草稿").click()
                expect(page.get_by_role("heading", name="已儲存草稿 1")).to_be_visible(
                    timeout=120000
                )
                page.get_by_role("button", name="展開草稿").click()
                expect(page.locator("#saved-drafts-list")).to_be_visible(timeout=15000)
                draft = page.locator(
                    '#saved-drafts-list [aria-labelledby="visit-rehearsal-expired-restart"]'
                )
                expect(draft).to_be_visible()
                expect(draft).to_contain_text("掛號序號")
                expect(draft).to_contain_text("85")
                visits = page.evaluate(
                    "async () => (await fetch('/api/organizer/visits')).json()"
                )["visits"]
                corrected = next(
                    visit
                    for visit in visits
                    if visit["id"] == "rehearsal-expired-restart"
                )
                assert corrected["state"] == "draft"
                assert corrected["date"] == next_day
                assert corrected["patient_number"] == 85
                control(
                    page,
                    origin,
                    "observation",
                    {"current_number": 82, "trustworthy": True},
                )
                draft.locator('[data-start="rehearsal-expired-restart"]').click()
                active = page.locator(
                    '[aria-labelledby="visit-rehearsal-expired-restart"]'
                )
                expect(active.locator(".state")).to_have_text("監控中")
                expect(active).to_contain_text("掛號序號")
                expect(active).to_contain_text("85")
                assert page.request.get(origin + "/cdn-cgi/local/scheduled").ok
                restarted = control(page, origin, "snapshot")
                assert restarted["events"] == first["events"]
                assert restarted["line_requests"] == first["line_requests"]
                visits = page.evaluate(
                    "async () => (await fetch('/api/organizer/visits')).json()"
                )["visits"]
                active_api = next(
                    visit
                    for visit in visits
                    if visit["id"] == "rehearsal-expired-restart"
                )
                assert active_api["state"] == "active"
                assert active_api["date"] == next_day
                control(
                    page,
                    origin,
                    "tick",
                    {"now": (next_day_cutoff + timedelta(minutes=1)).isoformat()},
                )
                page.get_by_role("button", name="重新整理").click()
                expect(active.locator(".state")).to_have_text("已結束")
                assert control(page, origin, "snapshot") == restarted
                control(
                    page,
                    origin,
                    "tick",
                    {"now": (next_day_cutoff + timedelta(hours=48)).isoformat()},
                )
                page.get_by_role("button", name="重新整理").click()
                expect(page.get_by_role("heading", name="尚無提醒狀態")).to_be_visible()
                remaining = page.evaluate(
                    "async () => (await fetch('/api/organizer/visits')).json()"
                )["visits"]
                assert not any(
                    visit["id"] == "rehearsal-expired-restart" for visit in remaining
                )
        finally:
            context.close()
            browser.close()


def test_rehearsal_ui_retains_drafts_and_deduplicates_after_process_restart(tmp_path):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    day = (datetime.now(timezone.utc) + timedelta(days=1)).date().isoformat()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context()
        origin = f"http://127.0.0.1:{port}"
        context.route(
            "**/*",
            lambda route: (
                route.continue_()
                if route.request.url.startswith(origin + "/")
                else route.abort()
            ),
        )
        page = context.new_page()
        try:
            with rehearsal(tmp_path, port):
                # Native fixture preparation happens only once, before the UI journey.
                control(
                    page,
                    origin,
                    "observation",
                    {"current_number": 70, "trustworthy": True},
                )
                control(
                    page,
                    origin,
                    "seed",
                    {
                        "visit_id": "rehearsal-setup",
                        "recipient_id": "rehearsal-recipient",
                        "visit_day": day,
                        "patient_number": 85,
                        "now": datetime.now(timezone.utc).isoformat(),
                    },
                )
                page.goto(origin)
                page.get_by_role("button", name="本機合成測試登入").click()
                expect(page.locator("#visit-form")).to_be_visible()
                page.locator('[data-stop="rehearsal-setup"]').click()
                expect(page.locator('[data-correct="rehearsal-setup"]')).to_be_visible(
                    timeout=15000
                )
                page.locator("input[name=date]").fill(day)
                page.locator("input[name=clinic_code]").wait_for()
                page.locator("input[name=patient_number]").fill("85")
                page.locator("input[name=clinic_code]").fill(
                    "11 診/合成醫師丙/醫師約診"
                )
                page.locator("select[name=session]").select_option("afternoon")
                page.locator(
                    'input[name=recipient_ids][value="rehearsal-recipient"]'
                ).check()
                page.get_by_role("button", name="建立草稿").click()
                expect(page.get_by_role("heading", name="已儲存草稿 1")).to_be_visible(
                    timeout=15000
                )
                expect(page.locator("#saved-drafts-list")).to_be_hidden()
                page.get_by_role("button", name="展開草稿").click()
                edit = page.locator("#saved-drafts-list [data-edit]")
                visit_id = edit.get_attribute("data-edit")
                assert visit_id
                expect(page.locator("#saved-drafts-list")).to_contain_text("掛號序號")
                expect(page.locator("#saved-drafts-list")).to_contain_text("85")
                edit.click()
                expect(page.locator("input[name=patient_number]")).to_have_value("85")
                page.locator("input[name=patient_number]").fill("86")
                page.get_by_role("button", name="取消修正").click()
                edit.click()
                expect(page.locator("input[name=patient_number]")).to_have_value("85")
                page.locator("input[name=patient_number]").fill("86")
                page.get_by_role("button", name="儲存草稿", exact=True).click()
                expect(
                    page.get_by_text(
                        "草稿修改已儲存。請在提醒清單重新檢查並開始。", exact=True
                    )
                ).to_be_visible()
                expect(page.locator("#saved-drafts-list")).to_contain_text("86")

            # The command reapplies migrations and rebuilds, without seeding/resetting.
            with rehearsal(tmp_path, port):
                page.reload()
                expect(page.locator("#visit-form")).to_be_visible()
                page.get_by_role("button", name="展開草稿").click()
                expect(page.locator("#saved-drafts-list")).to_contain_text("掛號序號")
                expect(page.locator("#saved-drafts-list")).to_contain_text("86")
                page.locator(f'[data-edit="{visit_id}"]').click()
                expect(page.locator("input[name=patient_number]")).to_have_value("86")
                expect(page.locator("input[name=recipient_ids]")).to_be_checked()
                page.get_by_role("button", name="取消修正").click()
                control(
                    page,
                    origin,
                    "observation",
                    {"current_number": None, "trustworthy": False},
                )
                page.locator(f'[data-start="{visit_id}"]').click()
                expect(
                    page.get_by_text(
                        "目前沒有可用的可信院方觀察，提醒維持草稿。", exact=True
                    )
                ).to_be_visible()
                control(
                    page,
                    origin,
                    "observation",
                    {"current_number": 70, "trustworthy": True},
                )
                page.locator(f'[data-start="{visit_id}"]').click()
                expect(page.locator(f'[data-stop="{visit_id}"]')).to_be_visible()
                active_card = page.locator(f'article:has([data-stop="{visit_id}"])')
                expect(active_card).to_contain_text("掛號序號")
                expect(active_card).to_contain_text("86")
                control(
                    page,
                    origin,
                    "observation",
                    {"current_number": 83, "trustworthy": True},
                )
                assert page.request.get(origin + "/cdn-cgi/local/scheduled").ok
                first = control(page, origin, "snapshot")
                assert not first["held"]
                assert len(first["events"]) == len(first["line_requests"]) == 1
                event = first["events"][0]
                assert event["visit_id"] == visit_id
                assert event["outcome"] == "accepted"
                assert event["attempt_count"] == 1
                assert first["line_requests"][0]["retry_key"] == event["retry_key"]
                assert first["line_requests"][0]["outbox_persisted"]
                for _ in range(2):
                    assert page.request.get(origin + "/cdn-cgi/local/scheduled").ok
                assert control(page, origin, "snapshot") == first

            with rehearsal(tmp_path, port):
                page.reload()
                expect(page.locator(f'[data-stop="{visit_id}"]')).to_be_visible()
                # Both the D1 event and DO fake-request log survived the process exit.
                assert control(page, origin, "snapshot") == first
                for _ in range(2):
                    assert page.request.get(origin + "/cdn-cgi/local/scheduled").ok
                assert control(page, origin, "snapshot") == first
                page.locator(f'[data-stop="{visit_id}"]').click()
                expect(page.locator(f'[data-correct="{visit_id}"]')).to_be_visible(
                    timeout=15000
                )
                stopped_card = page.locator(f'article:has([data-correct="{visit_id}"])')
                expect(stopped_card).to_contain_text("掛號序號")
                expect(stopped_card).to_contain_text("86")
                assert page.request.get(origin + "/cdn-cgi/local/scheduled").ok
                assert control(page, origin, "snapshot") == first
                visits = page.evaluate(
                    "async () => (await fetch('/api/organizer/visits')).json()"
                )["visits"]
                saved = next(v for v in visits if v["id"] == visit_id)
                assert saved["state"] == "stopped"
                assert saved["patient_number"] == 86
                assert saved["date"] == day
        finally:
            context.close()
            browser.close()


def test_rehearsal_promotes_started_drafts_and_returns_corrected_reminders_to_drafts(
    tmp_path,
):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    day = (datetime.now(timezone.utc) + timedelta(days=1)).date().isoformat()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context()
        origin = f"http://127.0.0.1:{port}"
        context.route(
            "**/*",
            lambda route: (
                route.continue_()
                if route.request.url.startswith(origin + "/")
                else route.abort()
            ),
        )
        page = context.new_page()
        try:
            with rehearsal(tmp_path, port):
                control(
                    page,
                    origin,
                    "observation",
                    {"current_number": 70, "trustworthy": True},
                )
                control(
                    page,
                    origin,
                    "seed",
                    {
                        "visit_id": "rehearsal-transition-setup",
                        "recipient_id": "rehearsal-transition-recipient",
                        "visit_day": day,
                        "patient_number": 85,
                        "now": datetime.now(timezone.utc).isoformat(),
                    },
                )
                page.goto(origin)
                page.get_by_role("button", name="本機合成測試登入").click()
                page.locator('[data-stop="rehearsal-transition-setup"]').click()
                expect(
                    page.locator('[data-correct="rehearsal-transition-setup"]')
                ).to_be_visible(timeout=15000)
                page.locator("input[name=date]").fill(day)
                page.locator("input[name=clinic_code]").wait_for()
                page.locator("input[name=patient_number]").fill("88")
                page.locator("input[name=clinic_code]").fill(
                    "SYN-DRAFT 診/合成醫師甲/門診約診"
                )
                page.locator("select[name=session]").select_option("afternoon")
                page.locator(
                    'input[name=recipient_ids][value="rehearsal-transition-recipient"]'
                ).check()
                page.get_by_role("button", name="建立草稿").click()
                expect(page.get_by_role("heading", name="已儲存草稿 1")).to_be_visible(
                    timeout=15000
                )
                page.get_by_role("button", name="展開草稿").click()
                expect(page.locator("#saved-drafts-list")).to_be_visible()

                draft_id = page.locator(
                    "#saved-drafts-list [data-start]"
                ).get_attribute("data-start")
                assert draft_id
                control(
                    page,
                    origin,
                    "observation",
                    {"current_number": 70, "trustworthy": True},
                )
                page.locator(f'[data-start="{draft_id}"]').click()

                expect(page.get_by_role("heading", name="已儲存草稿 0")).to_be_visible(
                    timeout=15000
                )
                expect(
                    page.locator(f'#saved-drafts-list [data-start="{draft_id}"]')
                ).to_have_count(0)
                active_card = page.locator(f'article:has([data-stop="{draft_id}"])')
                expect(active_card).to_be_visible()
                expect(active_card).to_contain_text("掛號序號")
                expect(active_card).to_contain_text("88")
                visits = page.evaluate(
                    "async () => (await fetch('/api/organizer/visits')).json()"
                )["visits"]
                started = next(visit for visit in visits if visit["id"] == draft_id)
                assert started["state"] == "active"
                assert started["patient_number"] == 88

                active_card.locator(f'[data-stop="{draft_id}"]').click()
                expect(page.locator(f'[data-correct="{draft_id}"]')).to_be_visible(
                    timeout=15000
                )
                page.locator(f'[data-correct="{draft_id}"]').click()
                expect(
                    page.get_by_role("heading", name="修正已停止的提醒")
                ).to_be_visible(timeout=15000)
                page.locator("input[name=patient_number]").fill("89")
                page.locator("input[name=clinic_code]").fill(
                    "SYN-CORRECTED 診/合成醫師乙/門診約診"
                )
                assert page.locator("input[name=patient_number]").input_value() == "89"
                assert (
                    page.locator('select[name="department_code"]').input_value()
                    == "OPH"
                )
                assert (
                    page.locator("input[name=clinic_code]").input_value()
                    == "SYN-CORRECTED 診/合成醫師乙/門診約診"
                )
                failed_corrections = []

                def reject_correction(route):
                    payload = route.request.post_data_json
                    payload["date"] = "not-a-date"
                    response = route.fetch(post_data=payload)
                    failed_corrections.append(response.status)
                    route.fulfill(response=response)

                page.route("**/api/organizer/visits/*/correct", reject_correction)
                page.get_by_role("button", name="儲存修正並回到草稿").click()
                expect(
                    page.get_by_text(
                        "資料不完整或格式不正確，請檢查後再試。", exact=True
                    )
                ).to_be_visible()
                assert failed_corrections == [400]
                assert page.locator("input[name=patient_number]").input_value() == "89"
                assert not page.locator("#visit-form button[type=submit]").is_disabled()
                stopped_visits = page.evaluate(
                    "async () => (await fetch('/api/organizer/visits')).json()"
                )["visits"]
                stopped_api = next(
                    visit for visit in stopped_visits if visit["id"] == draft_id
                )
                assert stopped_api["state"] == "stopped"
                assert stopped_api["patient_number"] == 88
                page.unroute("**/api/organizer/visits/*/correct", reject_correction)
                cdp = context.new_cdp_session(page)
                paused_responses = []
                cdp.on(
                    "Fetch.requestPaused", lambda event: paused_responses.append(event)
                )
                cdp.send(
                    "Fetch.enable",
                    {
                        "patterns": [
                            {
                                "urlPattern": "*/api/organizer/visits/*/correct",
                                "requestStage": "Response",
                            }
                        ]
                    },
                )
                try:
                    page.get_by_role("button", name="儲存修正並回到草稿").click()
                    for _ in range(50):
                        if paused_responses:
                            break
                        page.wait_for_timeout(100)
                    assert len(paused_responses) == 1, paused_responses
                    assert paused_responses[0]["responseStatusCode"] == 200
                    pending_submit = page.locator("#visit-form button[type=submit]")
                    assert pending_submit.is_disabled(), "save button stayed enabled"
                    assert (
                        page.get_by_role("status")
                        .filter(has_text="正在儲存修正")
                        .is_visible()
                    ), "pending save status was not shown"
                    corrected_visits = page.evaluate(
                        "async () => (await fetch('/api/organizer/visits')).json()"
                    )["visits"]
                    corrected_api = next(
                        visit for visit in corrected_visits if visit["id"] == draft_id
                    )
                    assert corrected_api["department_code"] == "OPH"

                    def fail_dashboard_refresh(route):
                        route.fulfill(
                            status=503,
                            content_type="application/json",
                            body='{"error":{"code":"service_unavailable"}}',
                        )

                    page.route("**/api/organizer/visits", fail_dashboard_refresh)
                    cdp.send(
                        "Fetch.continueResponse",
                        {"requestId": paused_responses[0]["requestId"]},
                    )
                finally:
                    for paused in paused_responses:
                        try:
                            cdp.send(
                                "Fetch.continueResponse",
                                {"requestId": paused["requestId"]},
                            )
                        except Exception:
                            pass
                    cdp.send("Fetch.disable")
                    cdp.detach()

                expect(
                    page.get_by_text(
                        "修正已儲存為草稿。請在提醒清單重新檢查並開始。",
                        exact=True,
                    )
                ).to_be_visible()
                expect(
                    page.get_by_text(
                        "草稿已儲存，但清單更新失敗。請重新整理確認狀態。", exact=True
                    )
                ).to_be_visible()
                expect(page.get_by_role("heading", name="已儲存草稿 0")).to_be_visible()
                page.unroute("**/api/organizer/visits", fail_dashboard_refresh)
                page.get_by_role("button", name="重新整理").click()
                expect(page.get_by_role("heading", name="已儲存草稿 1")).to_be_visible(
                    timeout=15000
                )
                corrected_draft = page.locator(
                    f'#saved-drafts-list article[aria-labelledby="visit-{draft_id}"]'
                )
                expect(corrected_draft).to_be_visible()
                expect(corrected_draft).to_contain_text("SYN-CORRECTED")
                expect(corrected_draft).to_contain_text("合成醫師乙")
                expect(corrected_draft).to_contain_text("掛號序號")
                expect(corrected_draft).to_contain_text("89")
                expect(
                    page.locator(
                        f'.visits:not(.saved-drafts) article[aria-labelledby="visit-{draft_id}"]'
                    )
                ).to_have_count(0)
                visits = page.evaluate(
                    "async () => (await fetch('/api/organizer/visits')).json()"
                )["visits"]
                corrected = next(visit for visit in visits if visit["id"] == draft_id)
                assert corrected["state"] == "draft"
                assert corrected["department_code"] == "OPH"
                assert (
                    corrected["clinic_code"] == "SYN-CORRECTED 診/合成醫師乙/門診約診"
                )
                assert corrected["patient_number"] == 89
        finally:
            context.close()
            browser.close()


def test_rehearsal_failed_start_explains_reason_on_the_draft_card_and_aligns_fields(
    tmp_path,
):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    day = (datetime.now(timezone.utc) + timedelta(days=1)).date().isoformat()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(viewport={"width": 1280, "height": 900})
        origin = f"http://127.0.0.1:{port}"
        context.route(
            "**/*",
            lambda route: (
                route.continue_()
                if route.request.url.startswith(origin + "/")
                else route.abort()
            ),
        )
        page = context.new_page()
        try:
            with rehearsal(tmp_path, port):
                control(
                    page,
                    origin,
                    "observation",
                    {"current_number": None, "trustworthy": False},
                )
                control(
                    page,
                    origin,
                    "seed",
                    {
                        "visit_id": "rehearsal-failure-setup",
                        "recipient_id": "rehearsal-failure-recipient",
                        "visit_day": day,
                        "patient_number": 85,
                        "now": datetime.now(timezone.utc).isoformat(),
                    },
                )
                page.goto(origin)
                page.get_by_role("button", name="本機合成測試登入").click()
                expect(page.locator("#visit-form")).to_be_visible()
                page.locator('[data-stop="rehearsal-failure-setup"]').click()
                expect(
                    page.locator('[data-correct="rehearsal-failure-setup"]')
                ).to_be_visible(timeout=15000)

                # Department and date share the first cascading row; they stay aligned.
                department_box = page.locator(
                    'select[name="department_code"]'
                ).bounding_box()
                date_box = page.locator("input[name=date]").bounding_box()
                assert department_box and date_box
                assert abs(department_box["height"] - date_box["height"]) < 1
                assert abs(department_box["y"] - date_box["y"]) < 1

                page.locator("input[name=date]").fill(day)
                page.locator("input[name=clinic_code]").wait_for()
                page.locator("input[name=patient_number]").fill("85")
                page.locator("input[name=clinic_code]").fill(
                    "11 診/合成醫師丙/醫師約診"
                )
                page.locator(
                    'input[name=recipient_ids][value="rehearsal-failure-recipient"]'
                ).check()
                page.get_by_role("button", name="建立草稿").click()
                expect(page.get_by_role("heading", name="已儲存草稿 1")).to_be_visible(
                    timeout=15000
                )
                page.get_by_role("button", name="展開草稿").click()
                expect(page.locator("#saved-drafts-list")).to_be_visible()
                draft = page.locator("#saved-drafts-list .visit-card")
                draft.locator("[data-start]").click()

                expect(
                    draft.get_by_role("alert").get_by_text(
                        "目前沒有可用的可信院方觀察，提醒維持草稿。", exact=True
                    )
                ).to_be_visible()
                expect(draft.locator("[data-start]")).to_be_enabled()
                expect(page.get_by_role("heading", name="已儲存草稿 1")).to_be_visible()

                draft.get_by_role("button", name="修正草稿").click()
                expect(page.locator("input[name=patient_number]")).to_have_value("85")
                page.locator("input[name=patient_number]").fill("86")
                page.get_by_role("button", name="儲存草稿").click()
                draft = page.locator("#saved-drafts-list .visit-card")
                expect(draft).to_contain_text("86")
                expect(draft.get_by_role("alert")).to_have_count(0)

                visits = page.evaluate(
                    "async () => (await fetch('/api/organizer/visits')).json()"
                )["visits"]
                saved_draft = next(
                    visit for visit in visits if visit["state"] == "draft"
                )
                assert saved_draft["state"] == "draft"
                assert saved_draft["patient_number"] == 86

                control(
                    page,
                    origin,
                    "observation",
                    {"current_number": 70, "trustworthy": True},
                )
                draft.locator("[data-start]").click()
                expect(page.get_by_role("heading", name="已儲存草稿 0")).to_be_visible(
                    timeout=15000
                )
        finally:
            context.close()
            browser.close()


@pytest.mark.parametrize(
    "scenario", ["settled", "fill_during_load", "click_during_load"]
)
def test_correction_save_vs_roster_latency(tmp_path, scenario):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = int(listener.getsockname()[1])
    day = (datetime.now(timezone.utc) + timedelta(days=1)).date().isoformat()
    next_day = (datetime.fromisoformat(day) + timedelta(days=1)).date().isoformat()
    expired_at = datetime.fromisoformat(day).replace(tzinfo=timezone.utc) + timedelta(
        hours=16
    )
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context()
        origin = f"http://127.0.0.1:{port}"
        context.route(
            "**/*",
            lambda r: (
                r.continue_() if r.request.url.startswith(origin + "/") else r.abort()
            ),
        )
        page = context.new_page()
        held, hold = [], {"on": True}
        page.route(
            "**/clinics?**", lambda r: held.append(r) if hold["on"] else r.continue_()
        )

        def release():
            hold["on"] = False
            while held:
                held.pop().continue_()

        try:
            with rehearsal(tmp_path, port):
                control(
                    page,
                    origin,
                    "seed",
                    {
                        "visit_id": "rehearsal-expired-restart",
                        "recipient_id": "rehearsal-expired-recipient",
                        "visit_day": day,
                        "patient_number": 85,
                        "now": datetime.now(timezone.utc).isoformat(),
                    },
                )
                page.goto(origin)
                page.get_by_role("button", name="本機合成測試登入").click()
                control(page, origin, "tick", {"now": expired_at.isoformat()})
                page.get_by_role("button", name="重新整理").click()
                card = page.locator(
                    '[aria-labelledby="visit-rehearsal-expired-restart"]'
                )
                expect(card.locator(".state")).to_have_text("已結束")
                card.locator('[data-correct="rehearsal-expired-restart"]').click()
                expect(
                    page.get_by_role("heading", name="修正已結束的提醒")
                ).to_be_visible()
                expect(page.locator('input[name="date"]')).to_have_value(day)
                clinic = page.locator('#visit-form [name="clinic_code"]')
                session = page.locator('#visit-form [name="session"]')
                save = page.get_by_role("button", name="儲存修正並回到草稿")
                if scenario in ("settled", "click_during_load"):
                    release()
                    expect(clinic).to_have_value("SYN-1")
                    hold["on"] = True
                page.locator('input[name="date"]').fill(next_day)
                if scenario == "click_during_load":
                    expect(save).to_be_disabled(timeout=3000)
                release()
                expect(clinic).to_have_value("SYN-1")
                expect(session).to_have_value("afternoon")
                save.click()
                expect(page.get_by_role("heading", name="已儲存草稿 1")).to_be_visible(
                    timeout=10000
                )
        finally:
            context.close()
            browser.close()
