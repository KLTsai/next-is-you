"""Background updates leave the organizer's open calendar and typing alone.

Fixture/mock: the built page in a real browser, the organizer API answered here.
"""

from __future__ import annotations

import json
import mimetypes
import subprocess
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from playwright.sync_api import expect, sync_playwright

from worktree_bootstrap import require_frontend_toolchain

ROOT = Path(__file__).resolve().parents[1]
ORIGIN = "http://organizer.test"
DATE = '#visit-form input[name="date"]'
NUMBER = '#visit-form input[name="patient_number"]'
# How far the calendar button sits inside the right edge of the date field.
CALENDAR_BUTTON_INSET = 22


@pytest.fixture(scope="module")
def dist(tmp_path_factory) -> Path:
    require_frontend_toolchain()
    out = tmp_path_factory.mktemp("dist")
    subprocess.run(
        ["npx", "vite", "build", "--outDir", str(out), "--emptyOutDir"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return out


class Organizer:
    """The organizer page and the API it talks to."""

    def __init__(self, page, dist: Path) -> None:
        self.page = page
        self.dist = dist
        self.visits: list[dict] = []
        self.polls = 0
        self.hold_clinics = False
        self.held: list = []
        self.clinic_days: list[str] = []

    def add_stopping_visit(self) -> None:
        self.visits.append(
            {
                "id": "synthetic-visit",
                "state": "stopping",
                "hospital": "synthetic",
                "date": "2099-01-04",
                "department_code": "SYN",
                "clinic_code": "SYN-1 診/合成醫師甲/門診約診",
                "session": "afternoon",
                "patient_number": 85,
                "recipients": [
                    {"id": "synthetic-recipient", "display_name": "Synthetic"}
                ],
                "observation": {"current_number": None, "checked_at": None},
                "source_read": {"status": "unavailable", "reason": "no_observation"},
                "notification": {"count": 0, "accepted": 0, "issues": 0},
            }
        )

    def answer(self, route) -> None:
        path = urlsplit(route.request.url).path
        if not path.startswith("/api/"):
            file = self.dist / (path.lstrip("/") or "index.html")
            if not file.is_file():
                route.fulfill(status=404)
                return
            kind = mimetypes.guess_type(file.name)[0] or "application/octet-stream"
            route.fulfill(status=200, content_type=kind, body=file.read_bytes())
            return
        if path.endswith("/clinics"):
            query = parse_qs(urlsplit(route.request.url).query)
            self.clinic_days += query["date"]
            if self.hold_clinics:
                self.held.append(route)
            else:
                self._json(route, {"available": False, "reason": "no_observation"})
            return
        if path == "/api/organizer/visits":
            self.polls += 1
            self._json(route, {"visits": self.visits, "sending_interrupted": False})
            return
        self._json(
            route,
            {
                "/api/healthz": {"status": "ok", "mode": "deployed"},
                "/api/organizer/recipients": {"recipients": []},
                "/api/organizer/hospitals": {
                    "hospitals": [
                        {
                            "hospital": "synthetic",
                            "display_name": "合成醫院（僅供測試）",
                            "capability": "full_schedule",
                            "source_url": "https://synthetic-hospital.example/progress",
                            "clinic_code_labels": ["診間", "醫師", "診別"],
                            "departments": [{"code": "SYN", "display_name": "合成科"}],
                        }
                    ]
                },
            }[path],
        )

    @staticmethod
    def _json(route, payload) -> None:
        if "available" in payload:
            payload = {"clinics": [], **payload}
        route.fulfill(
            status=200, content_type="application/json", body=json.dumps(payload)
        )

    def open(self) -> None:
        self.page.route("**/*", self.answer)
        self.page.goto(ORIGIN)
        expect(self.page.locator(DATE)).to_be_visible()

    def plain_date_page(self, value: str = ""):
        """A page of its own with only a date field: what the browser itself does."""
        page = self.page.context.new_page()
        page.set_content(f'<input type="date" value="{value}">')
        return page

    def wait_for_polls(self, count: int) -> None:
        seen = self.polls
        for _ in range(100):
            if self.polls >= seen + count:
                return
            self.page.wait_for_timeout(100)
        raise AssertionError(f"the page polled {self.polls - seen} times")

    def open_calendar(self) -> None:
        field = self.page.locator(DATE)
        field.scroll_into_view_if_needed()
        box = field.bounding_box()
        self.page.mouse.click(
            box["x"] + box["width"] - CALENDAR_BUTTON_INSET,
            box["y"] + box["height"] / 2,
        )
        self.page.wait_for_timeout(150)
        assert self.calendar_is_open()

    def calendar_is_open(self) -> bool:
        return self.page.locator(DATE).evaluate("field => field.matches(':open')")

    def choose_date_while_clinics_load(self) -> None:
        self.hold_clinics = True
        self.page.locator(DATE).fill("2099-01-05")
        self.page.locator(DATE).dispatch_event("change")
        for _ in range(50):
            if self.held:
                return
            self.page.wait_for_timeout(100)
        raise AssertionError("the page did not ask for the day's clinics")

    def clinics_arrive(self) -> None:
        self._json(
            self.held.pop(0),
            {
                "available": True,
                "reason": "ok",
                "clinics": [
                    {
                        "session": "morning",
                        "room": "05",
                        "doctor": "合成醫師乙",
                        "clinic_type": "網膜",
                        "clinic_code": "05/合成醫師乙/網膜",
                        "label": "05 · 合成醫師乙（早診）",
                        "details": [],
                    }
                ],
            },
        )


@contextmanager
def organizer(dist: Path, screen: dict):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(**screen)
        page = context.new_page()
        try:
            yield Organizer(page, dist)
        finally:
            browser.close()


def test_calendar_stays_open_while_a_visit_is_stopping(dist, screen):
    with organizer(dist, screen) as app:
        app.add_stopping_visit()
        app.open()
        app.open_calendar()
        app.wait_for_polls(3)
        assert app.calendar_is_open()


def test_calendar_stays_open_when_the_visit_finishes_stopping(dist, screen):
    with organizer(dist, screen) as app:
        app.add_stopping_visit()
        app.open()
        app.open_calendar()
        app.visits[0]["state"] = "stopped"
        app.wait_for_polls(1)
        app.page.wait_for_timeout(600)
        assert app.calendar_is_open()
        app.page.keyboard.press("Escape")
        expect(app.page.get_by_text("已停止").first).to_be_visible()


def test_calendar_stays_open_when_the_clinics_arrive(dist, screen):
    with organizer(dist, screen) as app:
        app.open()
        app.choose_date_while_clinics_load()
        app.open_calendar()
        app.clinics_arrive()
        app.page.wait_for_timeout(600)
        assert app.calendar_is_open()
        app.page.keyboard.press("Escape")
        expect(app.page.get_by_text("合成醫師乙").first).to_be_attached()


def test_half_typed_date_is_kept_while_a_visit_is_stopping(dist, screen):
    def type_date(page, pause) -> str:
        page.locator('input[type="date"]').focus()
        page.keyboard.type("01", delay=50)
        pause()
        page.keyboard.type("052099", delay=50)
        return page.locator('input[type="date"]').input_value()

    with organizer(dist, screen) as app:
        expected = type_date(app.plain_date_page(), lambda: None)
        app.add_stopping_visit()
        app.open()
        assert type_date(app.page, lambda: app.wait_for_polls(2)) == expected != ""


def test_last_part_of_a_date_can_be_typed(dist, screen):
    """The last part is the day or the year, by the machine's language."""

    def retype_last_part(page) -> str:
        field = page.locator('input[type="date"]')
        field.focus()
        page.keyboard.press("ArrowRight")
        page.keyboard.press("ArrowRight")
        page.keyboard.type("18", delay=150)
        return field.input_value()

    with organizer(dist, screen) as app:
        expected = retype_last_part(app.plain_date_page("2099-01-05"))
        app.open()
        app.page.locator(DATE).fill("2099-01-05")
        app.page.wait_for_timeout(500)
        assert retype_last_part(app.page) == expected != "2099-01-05"
        # The page follows the date once the typing stops.
        app.page.wait_for_timeout(1500)
        assert app.page.locator(DATE).input_value() == expected
        assert app.clinic_days[-1] == expected or expected < "2099"
        assert set(app.clinic_days) <= {"2099-01-05", expected}


def test_number_typed_while_the_clinics_load_is_kept(dist, screen):
    with organizer(dist, screen) as app:
        app.open()
        app.choose_date_while_clinics_load()
        app.page.locator(NUMBER).press_sequentially("85", delay=50)
        app.clinics_arrive()
        expect(app.page.get_by_text("合成醫師乙").first).to_be_attached()
        assert app.page.locator(NUMBER).input_value() == "85"


def test_visit_that_finishes_stopping_is_shown_without_a_reload(dist, screen):
    with organizer(dist, screen) as app:
        app.add_stopping_visit()
        app.open()
        expect(app.page.get_by_text("已停止")).to_have_count(0)
        app.visits[0]["state"] = "stopped"
        expect(app.page.get_by_text("已停止").first).to_be_visible(timeout=10_000)


def test_dropdown_stays_open_while_a_visit_is_stopping(dist, screen):
    with organizer(dist, screen) as app:
        app.add_stopping_visit()
        app.open()
        dropdown = app.page.locator('#visit-form select[name="department_code"]')
        dropdown.click()
        assert dropdown.evaluate("field => field.matches(':open')")
        app.visits[0]["state"] = "stopped"
        app.wait_for_polls(1)
        app.page.wait_for_timeout(600)
        assert dropdown.evaluate("field => field.matches(':open')")
