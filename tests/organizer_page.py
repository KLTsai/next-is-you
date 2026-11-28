"""Drives the organizer page in a real browser, for test_organizer_page.py.

Two backends answer the same built page:

- FakeBackend: an in-memory organizer API answered in the browser. Fixture/mock.
- RehearsalBackend: the local rehearsal Worker (docs/LOCAL-REHEARSAL.md). Local
  integration, except where a test fails a request or publishes the day's
  clinics: that answer is a mock with either backend.

Requests pass through OrganizerPage first, so a test can hold or fail one the
same way against either backend.
"""

from __future__ import annotations

import itertools
import json
import mimetypes
import re
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import expect

RECIPIENT_ID = "synthetic-recipient"
CLINIC = "SYN-1 診/合成醫師甲/門診約診"
UNREADABLE_SOURCE_TEXT = "目前沒有可用的可信院方觀察，維持草稿。"
SOURCE_URL = "https://synthetic-hospital.example/progress"


def _published_clinic(session: str, doctor: str, label: str) -> dict:
    return {
        "session": session,
        "room": "05",
        "doctor": doctor,
        "clinic_type": "網膜",
        "clinic_code": f"05/{doctor}/網膜",
        "label": label,
        "details": [{"label": "醫師", "value": doctor}],
    }


# A day whose clinics the hospital has published, so the form offers a list to
# choose from instead of a clinic to type. The same answer is given with either
# backend: local test mode never runs the hospital reader.
PUBLISHED_DAY = {
    "available": True,
    "reason": "ok",
    "clinics": [
        _published_clinic("morning", "合成醫師乙", "05 · 合成醫師乙（早診）"),
        _published_clinic("afternoon", "合成醫師丙", "05 · 合成醫師丙（午診）"),
    ],
}

_numbers = itertools.count(1)


def next_id() -> str:
    return f"synthetic-visit-{next(_numbers)}"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def visit_day() -> str:
    """Tomorrow in UTC, as the rehearsal tests use: today or later in Taipei."""
    return (datetime.now(timezone.utc) + timedelta(days=1)).date().isoformat()


def lapsing_day() -> str:
    """Two days ago in Taipei: a draft of that day is deleted from 23:59 today."""
    taipei = timezone(timedelta(hours=8))
    return (datetime.now(taipei) - timedelta(days=2)).date().isoformat()


class FakeBackend:
    """The organizer API as the page sees it, kept in memory for one page."""

    origin = "http://organizer.test"

    def __init__(self, dist: Path) -> None:
        self.dist = dist
        self.visits: list[dict] = []
        self.source_readable = True
        self.stop_settles = True

    def open(self, page) -> None:
        page.goto(self.origin)

    def close(self) -> None:
        pass

    def answer(self, route, edit=None) -> None:
        """Answer the request; `edit` may change a JSON answer before it is sent."""
        request = route.request
        path = urlsplit(request.url).path
        if not path.startswith("/api/"):
            file = self.dist / (path.lstrip("/") or "index.html")
            if not file.is_file():
                route.fulfill(status=404)
                return
            kind = mimetypes.guess_type(file.name)[0] or "application/octet-stream"
            route.fulfill(status=200, content_type=kind, body=file.read_bytes())
            return
        body = request.post_data_json if request.post_data else None
        status, payload = self._answer_api(request.method, path, body)
        if edit:
            edit(payload)
        route.fulfill(
            status=status, content_type="application/json", body=json.dumps(payload)
        )

    def _answer_api(self, method: str, path: str, body) -> tuple[int, dict]:
        if (method, path) == ("GET", "/api/healthz"):
            return 200, {"status": "ok", "mode": "deployed"}
        if (method, path) == ("GET", "/api/organizer/visits"):
            return 200, {"visits": self.visits, "sending_interrupted": False}
        if (method, path) == ("POST", "/api/organizer/visits"):
            visit_id = next_id()
            self._add(visit_id, "draft", **body)
            return 201, {"id": visit_id, "state": "draft"}
        if path == "/api/organizer/recipients":
            recipient = {"id": RECIPIENT_ID, "display_name": "Synthetic recipient"}
            return 200, {"recipients": [recipient]}
        if path == "/api/organizer/hospitals":
            return 200, {
                "hospitals": [
                    {
                        "hospital": "synthetic",
                        "display_name": "合成醫院（僅供測試）",
                        "capability": "full_schedule",
                        "source_url": SOURCE_URL,
                        "clinic_code_labels": ["診間", "醫師", "診別"],
                        "departments": [
                            {"code": "SYN", "display_name": "合成科"},
                            {"code": "SYN2", "display_name": "合成二科"},
                        ],
                    }
                ]
            }
        if path.endswith("/clinics"):
            return 200, {"available": False, "reason": "no_observation", "clinics": []}
        if path == "/api/organizer/invitations":
            return 201, {
                "invitation_url": f"{self.origin}/auth/line?invite=synthetic",
                "expires_at": "2099-01-01T00:00:00Z",
            }
        match = re.fullmatch(r"/api/organizer/visits/([^/]+)(?:/(\w+))?", path)
        visit = match and self._find(match[1])
        if not visit:
            return 404, {"error": {"code": "visit_not_found"}}
        action = match[2]
        if action == "correction":
            return 200, {"patient_number": visit["patient_number"]}
        if action == "start":
            if visit["state"] != "draft":
                return 409, {"error": {"code": "invalid_lifecycle_state"}}
            if not self.source_readable:
                return 409, {"error": {"code": "observation_unavailable"}}
            visit["state"] = "active"
            return 200, {"state": "active"}
        if action == "stop":
            visit["state"] = "stopped" if self.stop_settles else "stopping"
            return 200, {"state": visit["state"]}
        raise NotImplementedError(f"{method} {path}")

    def _find(self, visit_id: str) -> dict | None:
        return next((item for item in self.visits if item["id"] == visit_id), None)

    def _add(
        self, visit_id: str, state: str, *, recipient_ids: list[str], **body
    ) -> None:
        self.visits.append(
            {
                "id": visit_id,
                "state": state,
                "observation": {"current_number": None, "checked_at": None},
                "source_url": SOURCE_URL,
                "source_read": {"status": "unavailable", "reason": "no_observation"},
                "notification": {"count": 0, "accepted": 0, "issues": 0},
                "recipients": [
                    {"id": item, "display_name": "Synthetic recipient"}
                    for item in recipient_ids
                ],
                **body,
            }
        )

    def add_visit(self, state: str) -> str:
        visit_id = next_id()
        self._add(
            visit_id,
            state,
            hospital="synthetic",
            date=visit_day(),
            department_code="SYN",
            clinic_code=CLINIC,
            session="afternoon",
            patient_number=85,
            recipient_ids=[RECIPIENT_ID],
        )
        return visit_id

    def add_lapsing_draft(self) -> str:
        visit_id = self.add_visit("draft")
        self._find(visit_id)["date"] = lapsing_day()
        return visit_id

    def expire_lapsing_drafts(self) -> None:
        """The lifecycle tick of the next day deletes the lapsing drafts."""
        self.visits = [item for item in self.visits if item["date"] != lapsing_day()]

    def start_elsewhere(self, visit_id: str) -> None:
        """The draft is started from somewhere other than this page."""
        self._find(visit_id)["state"] = "active"

    def set_source_readable(self, readable: bool) -> None:
        self.source_readable = readable

    def hold_stop(self) -> None:
        """The running visit has a send in flight: Stop leaves it stopping."""
        self.stop_settles = False

    def settle_stop(self) -> None:
        self.stop_settles = True
        for visit in self.visits:
            if visit["state"] == "stopping":
                visit["state"] = "stopped"


class RehearsalBackend:
    """The rehearsal Worker, shared by the module: each page adds its own visits."""

    def __init__(self, origin: str, request) -> None:
        self.origin = origin
        self.request = request  # a Playwright APIRequestContext of its own
        self.page = None
        self.send_held = False

    def control(self, operation: str, **data):
        response = self.request.post(
            f"{self.origin}/__niy006_test/{operation}", data=data
        )
        assert response.ok, response.text()
        return response.json() if response.status != 204 else {}

    def open(self, page) -> None:
        self.control("line-mode", mode="accepted")
        self.set_source_readable(True)
        # A fresh dataset has no consented recipient; a seeded visit brings one.
        self.add_visit("stopped")
        page.goto(self.origin)
        page.get_by_role("button", name="本機合成測試登入").click()
        expect(page.locator("#visit-form")).to_be_visible()
        self.page = page

    def close(self) -> None:
        if self.page is None:
            return  # never opened
        self.settle_stop()
        for visit in self._call("GET", "/api/organizer/visits")["visits"]:
            if visit["state"] == "active":
                assert self._stop(visit["id"]) == "stopped"

    def answer(self, route, edit=None) -> None:
        if not route.request.url.startswith(self.origin + "/"):
            route.abort()
        elif edit:
            response = route.fetch()
            if not response.ok:
                route.fulfill(response=response)
                return
            payload = response.json()
            edit(payload)
            route.fulfill(response=response, body=json.dumps(payload))
        else:
            route.continue_()

    def _call(self, method: str, path: str, body=None):
        return self.page.evaluate(
            """async ([method, path, body]) => {
                const csrf = document.cookie.match(/__Host-ny_csrf=([^;]*)/)?.[1] ?? "";
                const response = await fetch(path, {
                    method,
                    headers: { "content-type": "application/json", "x-csrf-token": decodeURIComponent(csrf), "x-test-setup": "1" },
                    body: body ? JSON.stringify(body) : undefined,
                });
                if (!response.ok) throw new Error(`${path}: ${response.status}`);
                return response.json();
            }""",
            [method, path, body],
        )

    def _stop(self, visit_id: str) -> str:
        return self.control("stop", visit_id=visit_id, now=now())["state"]

    def _add_draft(self, day: str) -> str:
        hospital = self._call("GET", "/api/organizer/hospitals")["hospitals"][0]
        return self._call(
            "POST",
            "/api/organizer/visits",
            {
                "hospital": hospital["hospital"],
                "date": day,
                "department_code": hospital["departments"][0]["code"],
                "clinic_code": CLINIC,
                "session": "afternoon",
                "patient_number": 85,
                "recipient_ids": [RECIPIENT_ID],
            },
        )["id"]

    def add_lapsing_draft(self) -> str:
        return self._add_draft(lapsing_day())

    def expire_lapsing_drafts(self) -> None:
        """The lifecycle tick of the next day deletes the lapsing drafts."""
        tomorrow = datetime.now(timezone.utc) + timedelta(days=1)
        self.control("tick", now=tomorrow.isoformat())

    def start_elsewhere(self, visit_id: str) -> None:
        """The draft is started from somewhere other than this page."""
        started = self._call("POST", f"/api/organizer/visits/{visit_id}/start")
        assert started["state"] == "active", started

    def add_visit(self, state: str) -> str:
        if state == "draft":
            return self._add_draft(visit_day())
        visit_id = next_id()
        self.control(
            "seed",
            visit_id=visit_id,
            recipient_id=RECIPIENT_ID,
            visit_day=visit_day(),
            patient_number=85,
            now=now(),
        )
        if state == "stopping":
            self.hold_stop()
        if state != "active":
            assert self._stop(visit_id) == state
        return visit_id

    def set_source_readable(self, readable: bool) -> None:
        self.control(
            "observation",
            current_number=70 if readable else None,
            trustworthy=readable,
        )

    def hold_stop(self) -> None:
        """Put a fake LINE send in flight for the running visit: Stop has to wait."""
        self.control("line-mode", mode="wait")
        self.control("observation", current_number=82, trustworthy=True)
        self.page.evaluate(
            "() => { window.heldTick = fetch('/__niy006_test/alarm', { method: 'POST' }); }"
        )
        self.control("wait-request")
        self.send_held = True

    def settle_stop(self) -> None:
        if not self.send_held:
            return
        self.control("release-request")
        status = self.page.evaluate("async () => (await window.heldTick).status")
        assert status == 200, status
        self.control("line-mode", mode="accepted")
        self.set_source_readable(True)
        self.send_held = False


class OrganizerPage:
    """What an organizer does and sees, plus holding or failing a request."""

    def __init__(self, page, backend, *, touch: bool) -> None:
        self.page = page
        self.backend = backend
        self.touch = touch
        self.sent: list[tuple[str, str]] = []
        self._poll_number = 0
        self._failing: set[tuple[str, str]] = set()
        self._held: dict[tuple[str, str], list] = {}
        self._published_day = False
        page.clock.install()
        page.add_init_script(
            """window.scrollTrail = [];
            document.addEventListener("scroll", () => window.scrollTrail.push(window.scrollY));"""
        )
        page.context.route("**/*", self._route)

    def close(self) -> None:
        """Close the page once no request is still inside the route handler.

        The handler fetches a real answer, then reads its body. A close between
        the two disposes that answer, and Playwright raises the handler's
        "Response has been disposed" at whatever call comes next, often in
        another test's fixture. Waiting lets the handler finish first.
        """
        self.page.context.unroute_all(behavior="wait")
        self.page.context.close()

    # Requests

    @staticmethod
    def _matches(key: tuple[str, str], method: str, path: str) -> bool:
        return key[0] == method and path.endswith(key[1])

    def _route(self, route) -> None:
        method, path = route.request.method, urlsplit(route.request.url).path
        if "x-test-setup" in route.request.headers:
            self.backend.answer(route)
            return
        self.sent.append((method, path))
        for key, waiting in self._held.items():
            if self._matches(key, method, path):
                waiting.append(route)
                return
        for key in self._failing:
            if self._matches(key, method, path):
                route.fulfill(status=503, content_type="application/json", body="{}")
                return
        if self._published_day and path.endswith("/clinics"):
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(PUBLISHED_DAY),
            )
            return
        if (method, path) == ("GET", "/api/organizer/visits"):
            self.backend.answer(route, self._stamp_poll)
        else:
            self.backend.answer(route)

    def _stamp_poll(self, payload: dict) -> None:
        """The page skips a repaint when a poll shows nothing new (#190), and
        these tests need every poll to repaint: each brings a change."""
        self._poll_number += 1
        for visit in payload["visits"]:
            visit["poll"] = self._poll_number

    @contextmanager
    def failing(self, method: str, path: str):
        self._failing.add((method, path))
        try:
            yield
        finally:
            self._failing.remove((method, path))

    @contextmanager
    def holding(self, method: str, path: str):
        """Hold matching requests unanswered; answer them normally on exit."""
        waiting = self._held[(method, path)] = []
        try:
            yield
        finally:
            del self._held[(method, path)]
            for route in waiting:
                self.backend.answer(route)

    def count_sent(self, method: str, path: str) -> int:
        return sum(self._matches((method, path), *item) for item in self.sent)

    def publish_the_day(self) -> None:
        self._published_day = True

    # Pages and repaints

    def open(self, *states: str) -> list[str]:
        """Open the dashboard showing one visit per state; returns their ids.

        "stopping" comes last: the rehearsal adds no visit while a send is held.
        """
        self.backend.open(self.page)
        ids = [self.backend.add_visit(state) for state in states]
        self.press(self.button("重新整理"))
        for visit_id in ids:
            expect(self.card(visit_id)).to_have_count(1)
        self.page.evaluate("() => { window.neverReloaded = true; }")
        return ids

    def wait_for_repaints(self, count: int) -> None:
        """Wait until the page has repainted itself `count` times in the background.

        A repaint replaces the whole page, so it takes the mark away. Counting
        polls instead would prove nothing on a page that polls without repainting.
        """
        for _ in range(count):
            with self.repainting():
                # Fires the page's own polling timer now, not a second from now.
                self.page.clock.fast_forward(1000)

    def wait_for_polls(self, count: int) -> None:
        """Wait until the page has asked for the visits `count` more times."""
        target = self.count_sent("GET", "/api/organizer/visits") + count
        for _ in range(500):
            if self.count_sent("GET", "/api/organizer/visits") >= target:
                return
            self.page.clock.fast_forward(1000)
            self.page.wait_for_timeout(20)
        raise AssertionError("The page stopped polling")

    @contextmanager
    def repainting(self):
        """The page repaints because of what happens inside the block."""
        self.page.evaluate(
            "() => { document.querySelector('#app').firstElementChild.beforeRepaint = true; }"
        )
        yield
        for _ in range(500):
            if self.page.evaluate(
                "() => !document.querySelector('#app').firstElementChild.beforeRepaint"
            ):
                return
            self.page.wait_for_timeout(20)
        raise AssertionError("The page did not repaint")

    def card(self, visit_id: str):
        return self.page.locator(f'article[aria-labelledby="visit-{visit_id}"]')

    def field(self, name: str):
        selector = {
            "member_label": "#member-label",
            "recipient_ids": f'#visit-form [name="recipient_ids"][value="{RECIPIENT_ID}"]',
        }.get(name, f'#visit-form [name="{name}"]:not([type="hidden"])')
        return self.page.locator(selector).first

    def press(self, locator) -> None:
        (locator.tap if self.touch else locator.click)()

    def type(self, text: str) -> None:
        self.page.keyboard.type(text, delay=30)

    def button(self, name: str):
        return self.page.get_by_role("button", name=name, exact=True)

    def heading(self, name: str):
        return self.page.get_by_role("heading", name=name, exact=True)

    def state(self, visit_id: str):
        return self.card(visit_id).locator(".state")

    def start_button(self, visit_id: str):
        return self.page.locator(f'[data-start="{visit_id}"]')

    def stop_button(self, visit_id: str):
        return self.page.locator(f'[data-stop="{visit_id}"]')

    def expect_status(self, text: str) -> None:
        status = self.page.locator("#app").get_by_role("status")
        expect(status.filter(has_text=text)).to_be_visible()

    def expect_repeat_presses_ignored(self, button, method: str, path: str) -> None:
        expect(button).to_be_disabled()
        for _ in range(3):
            # force: press the real spot without waiting for it to be enabled.
            (button.tap if self.touch else button.click)(force=True)
        self.page.wait_for_timeout(100)
        assert self.count_sent(method, path) == 1

    def expect_never_reloaded(self) -> None:
        assert self.page.evaluate("() => window.neverReloaded === true")

    def form_values(self) -> list:
        return self.page.evaluate(
            "() => [...new FormData(document.querySelector('#visit-form'))]"
        )

    def entered(self) -> dict:
        return {
            "member_label": self.field("member_label").input_value(),
            "form": self.form_values(),
        }

    def enter_everything(self) -> dict:
        """Fill in every field without saving; returns what is now entered."""
        self.field("member_label").fill("媽媽")
        self.fill_visit_form()
        entered = self.entered()
        assert entered["member_label"] == "媽媽"
        form = dict(entered["form"])
        assert form["hospital"]
        assert form["department_code"]
        assert form["date"] == visit_day()
        assert form["clinic_code"] == CLINIC
        assert form["session"] == "afternoon"
        assert form["patient_number"] == "88"
        assert form["recipient_ids"] == RECIPIENT_ID
        return entered

    def fill_visit_form(self) -> None:
        department = self.field("department_code")
        department.select_option(
            department.locator("option").last.get_attribute("value")
        )
        self.field("date").fill(visit_day())
        expect(self.field("clinic_code")).to_be_visible()
        self.field("clinic_code").fill(CLINIC)
        self.field("session").select_option("afternoon")
        self.field("patient_number").fill("88")
        self.field("recipient_ids").check()

    # Scrolling

    @staticmethod
    def _on_page(locator, expression: str, argument=None):
        """Evaluate with the element, again if a repaint replaced it meanwhile."""
        while True:
            answer = locator.evaluate(
                f"""(element, argument) =>
                    element.isConnected ? [({expression})(element, argument)] : null""",
                argument,
            )
            if answer:
                return answer[0]

    def box(self, locator) -> dict:
        """The element's box on the screen, measured between repaints."""
        return self._on_page(
            locator, "element => element.getBoundingClientRect().toJSON()"
        )

    def stop_layout(self, visit_id: str) -> dict:
        """The Stop button's height and the gap to its hint, from one paint."""
        return self._on_page(
            self.card(visit_id),
            """card => {
                const button = card.querySelector(".stop-button");
                const hint = card.querySelector(".stop-action small");
                const box = button.getBoundingClientRect();
                return { height: box.height, gap: hint.getBoundingClientRect().top - box.bottom };
            }""",
        )

    def is_off_screen(self, locator) -> bool:
        return self._on_page(
            locator,
            """element => {
                const box = element.getBoundingClientRect();
                return box.bottom <= 0 || box.top >= window.innerHeight;
            }""",
        )

    @property
    def scroll_y(self) -> float:
        return self.page.evaluate("() => window.scrollY")

    @property
    def scroll_max(self) -> float:
        return self.page.evaluate(
            "() => document.documentElement.scrollHeight - window.innerHeight"
        )

    def bring_to(self, locator, block: str) -> None:
        """Scroll the element to the "start", "center" or "end" of the screen."""
        self._on_page(
            locator,
            "(element, block) => element.scrollIntoView({ block, behavior: 'instant' })",
            block,
        )
        self.page.wait_for_timeout(50)

    def scroll_to(self, y: float) -> float:
        self.page.evaluate("y => window.scrollTo({ top: y, behavior: 'instant' })", y)
        self.page.wait_for_timeout(50)
        return self.scroll_y

    @contextmanager
    def keeps_scroll_position(self, button):
        """The page never leaves where it was when the organizer reached the button."""
        # Part way down, with the button in view: at the very top or bottom the
        # page could not move one way.
        self.bring_to(button, "center")
        before = self.scroll_y
        if before == 0:
            before = self.scroll_to(60)
        assert 0 < before < self.scroll_max, (before, self.scroll_max)
        self.take_scroll_trail()
        yield button
        self.page.wait_for_timeout(200)
        assert {*self.take_scroll_trail(), self.scroll_y} == {before}

    def take_scroll_trail(self) -> list[float]:
        return self.page.evaluate("() => window.scrollTrail.splice(0)")

    def scroll_slowly(self, distance: int) -> None:
        """Scroll down (positive) or up by wheel or finger, across repaints."""
        size = self.page.viewport_size
        sign = 1 if distance > 0 else -1
        if not self.touch:
            self.page.mouse.move(size["width"] / 2, size["height"] / 2)
            for _ in range(abs(distance) // 60):
                self.page.mouse.wheel(0, 60 * sign)
                self.wait_for_repaints(1)
                self.page.wait_for_timeout(50)
            return
        cdp = self.page.context.new_cdp_session(self.page)
        x, middle = size["width"] / 2, size["height"] / 2
        y = middle + sign * abs(distance) / 2
        touch = lambda kind, points: cdp.send(  # noqa: E731
            "Input.dispatchTouchEvent", {"type": kind, "touchPoints": points}
        )
        touch("touchStart", [{"x": x, "y": y}])
        for move in range(abs(distance) // 12):
            y -= 12 * sign
            touch("touchMove", [{"x": x, "y": y}])
            self.page.wait_for_timeout(20)
            if move % 8 == 7:
                self.wait_for_repaints(1)
        # Hold still before lifting, so the swipe does not fling the page on.
        self.page.wait_for_timeout(300)
        touch("touchMove", [{"x": x, "y": y}])
        touch("touchEnd", [])
        self.page.wait_for_timeout(100)
