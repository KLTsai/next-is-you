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
    return response.json()


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
                expect(page.locator('[data-correct="rehearsal-setup"]')).to_be_visible()
                page.locator("input[name=date]").fill(day)
                page.locator("input[name=patient_number]").fill("85")
                page.locator("input[name=department_code]").fill("SYN")
                page.locator("input[name=clinic_code]").fill("SYN-1")
                page.locator("select[name=session]").select_option("afternoon")
                page.locator(
                    'input[name=recipient_ids][value="rehearsal-recipient"]'
                ).check()
                page.get_by_role("button", name="建立草稿").click()
                expect(page.get_by_role("heading", name="已儲存草稿 1")).to_be_visible()
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
                expect(page.locator(f'[data-correct="{visit_id}"]')).to_be_visible()
                assert page.request.get(origin + "/cdn-cgi/local/scheduled").ok
                assert control(page, origin, "snapshot") == first
                visits = page.evaluate(
                    "async () => (await fetch('/api/organizer/visits')).json()"
                )["visits"]
                saved = next(v for v in visits if v["id"] == visit_id)
                assert saved["state"] == "stopped"
                assert saved["date"] == day
        finally:
            context.close()
            browser.close()
