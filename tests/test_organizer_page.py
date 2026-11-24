"""What an organizer sees on the organizer page, in a real browser (#182).

The page repaints itself wholesale while the organizer uses it. Every test here
runs against the fake API (fixture/mock) and against the local rehearsal Worker
(local integration), at desktop width and on a 390x844 touch screen. A failed
request and a published day's clinics are mocked with either.

Each test has its own page. The rehearsal Worker is shared, so tests name the
visits they added and never count all of them.
"""

from __future__ import annotations

import json
import re
import socket
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from playwright.sync_api import expect, sync_playwright

from organizer_page import (
    UNREADABLE_SOURCE_TEXT,
    FakeBackend,
    OrganizerPage,
    RehearsalBackend,
    visit_day,
)
from test_rehearsal import rehearsal
from worktree_bootstrap import require_frontend_toolchain

REQUEST_FAILED_TEXT = "操作未完成，請重新載入後再試。"
INVITATION_LINK = re.compile(r"/auth/line\?invite=.+")
ROOT = Path(__file__).resolve().parents[1]
SCREENS = {
    "desktop": {"viewport": {"width": 1280, "height": 900}},
    "phone": {
        "viewport": {"width": 390, "height": 844},
        "device_scale_factor": 2,
        "is_mobile": True,
        "has_touch": True,
    },
}


@pytest.fixture(scope="module")
def organizer_browser():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        yield playwright, browser
        browser.close()


@pytest.fixture(scope="module", params=["fake", "rehearsal"])
def organizer_service(request, tmp_path_factory, organizer_browser):
    """Returns a function that makes the backend for one page."""
    work = tmp_path_factory.mktemp(request.param)
    if request.param == "fake":
        # Built here, so the suite never judges a stale dist/.
        require_frontend_toolchain()
        dist = work / "dist"
        subprocess.run(
            ["npx", "vite", "build", "--outDir", str(dist), "--emptyOutDir"],
            cwd=ROOT,
            check=True,
            capture_output=True,
        )
        yield lambda: FakeBackend(dist)
        return
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = int(listener.getsockname()[1])
    playwright, _ = organizer_browser
    with rehearsal(work, port) as origin:
        controls = playwright.request.new_context()
        yield lambda: RehearsalBackend(origin, controls)
        controls.dispose()


@pytest.fixture(params=SCREENS)
def organizer(request, organizer_browser, organizer_service):
    _, browser = organizer_browser
    backend = organizer_service()
    context = browser.new_context(**SCREENS[request.param])
    page = context.new_page()
    page.set_default_timeout(15_000)
    organizer = OrganizerPage(page, backend, touch=request.param == "phone")
    try:
        yield organizer
        backend.close()
    finally:
        organizer.close()


def test_closing_a_page_while_a_poll_is_answered_leaves_playwright_usable(
    organizer_browser,
):
    # A repaint poll goes through the route handler, which fetches the real
    # answer and then reads its body. Closing the page between the two used to
    # leave Playwright holding the handler's "Response has been disposed", which
    # it raised at the next call: the module's controls.dispose() in CI.
    polled, answer = threading.Event(), threading.Event()

    class Worker(BaseHTTPRequestHandler):
        def log_message(self, *args) -> None:
            pass

        def do_GET(self) -> None:
            if self.path == "/api/organizer/visits":
                polled.set()
                answer.wait(5)
                kind, body = "application/json", json.dumps({"visits": []})
            else:
                kind, body = (
                    "text/html",
                    "<script>fetch('/api/organizer/visits')</script>",
                )
            self.send_response(200)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body.encode())))
            self.end_headers()
            self.wfile.write(body.encode())

    server = ThreadingHTTPServer(("127.0.0.1", 0), Worker)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    playwright, browser = organizer_browser
    controls = playwright.request.new_context()
    try:
        origin = f"http://127.0.0.1:{server.server_port}"
        page = browser.new_context().new_page()
        organizer = OrganizerPage(page, RehearsalBackend(origin, controls), touch=False)
        page.goto(origin)
        for _ in range(100):
            if polled.is_set():
                break
            page.wait_for_timeout(50)
        assert polled.is_set(), "the page never polled"
        answer.set()
        # Blocks Playwright's dispatcher: the fetch finishes, but the handler
        # reads the body only once the close below is under way.
        time.sleep(0.5)
        organizer.close()
    finally:
        controls.dispose()
        server.shutdown()
        server.server_close()


FIELDS = [
    ("member_label", False),
    ("hospital", False),
    ("department_code", False),
    ("date", False),
    ("clinic_code", False),
    ("session", False),
    ("patient_number", False),
    ("recipient_ids", False),
    pytest.param("clinic_code", True, id="published-clinic_code"),
]
each_field = pytest.mark.parametrize(("name", "published"), FIELDS)


def open_with_field(organizer, name, published=False):
    """The dashboard repainting every second, with every form field shown."""
    if published:
        organizer.publish_the_day()
    # Stopped visits make the page long enough to scroll any field off screen.
    organizer.open("stopped", "stopped", "stopped", "stopping")
    organizer.field("date").fill(visit_day())
    organizer.field("clinic_code").wait_for()
    return organizer.field(name)


@each_field
def test_slow_scrolling_with_a_focused_field_is_never_pulled_back(
    organizer, name, published
):
    field = open_with_field(organizer, name, published)
    # At the screen edge it leaves by, so the scroll takes it off screen. More
    # room than the scroll needs, so that a jump ahead cannot hide there.
    organizer.bring_to(field, "start")
    down = organizer.scroll_max - organizer.scroll_y >= 600
    if not down:
        organizer.bring_to(field, "end")
        assert organizer.scroll_y >= 600
    field.focus()
    start = organizer.scroll_y
    organizer.take_scroll_trail()

    organizer.scroll_slowly(480 if down else -480)
    organizer.wait_for_repaints(1)

    trail = [start, *organizer.take_scroll_trail()]
    ahead = [y - start if down else start - y for y in trail]
    assert ahead == sorted(ahead), trail
    # A finger moves a few pixels before the page starts to follow it.
    assert 440 <= ahead[-1] <= 480, trail
    assert organizer.is_off_screen(field)
    expect(field).to_be_focused()


@each_field
def test_a_focused_field_that_is_off_screen_does_not_move_the_page(
    organizer, name, published
):
    field = open_with_field(organizer, name, published)
    field.focus()
    off_screen = 0
    for target in (0, organizer.scroll_max):
        rest = organizer.scroll_to(target)
        off_screen += organizer.is_off_screen(field)
        organizer.wait_for_repaints(1)
        assert organizer.scroll_y == rest
        expect(field).to_be_focused()
    assert off_screen, "the field was never off screen"


@pytest.mark.parametrize("name", ["member_label", "clinic_code", "patient_number"])
def test_typing_across_repaints_keeps_every_character_and_the_caret(organizer, name):
    field = open_with_field(organizer, name)
    organizer.press(field)
    for digit in "12345":
        organizer.type(digit)
        organizer.wait_for_repaints(1)
    expect(field).to_have_value("12345")

    for _ in range(3):
        organizer.page.keyboard.press("ArrowLeft")
    organizer.wait_for_repaints(1)
    organizer.type("9")
    organizer.wait_for_repaints(1)
    expect(field).to_have_value("129345")

    # The "93" after the caret's two digits, selected and then typed over.
    organizer.page.keyboard.press("ArrowLeft")
    organizer.page.keyboard.press("Shift+ArrowRight")
    organizer.page.keyboard.press("Shift+ArrowRight")
    organizer.wait_for_repaints(1)
    organizer.type("7")
    expect(field).to_have_value("12745")
    expect(field).to_be_focused()


@pytest.mark.parametrize("name", ["member_label", "clinic_code"])
def test_a_word_being_composed_keeps_its_candidates_across_polls(organizer, name):
    """With an input method (Chinese, Japanese, Korean), the typed sounds stay
    open for a pick of the word until it is committed; a repaint ends that."""
    field = open_with_field(organizer, name)
    organizer.press(field)
    field.evaluate("field => { field.sameElement = true; }")
    ime = organizer.page.context.new_cdp_session(organizer.page)
    ime.send(
        "Input.imeSetComposition",
        {"text": "ㄇㄚ", "selectionStart": 2, "selectionEnd": 2},
    )
    organizer.wait_for_polls(3)
    # Still the same field, still composing: the candidates can be picked from.
    assert field.evaluate("field => field.sameElement === true")
    expect(field).to_be_focused()
    expect(field).to_have_value("ㄇㄚ")

    ime.send("Input.insertText", {"text": "媽"})
    expect(field).to_have_value("媽")
    organizer.wait_for_repaints(1)
    expect(field).to_have_value("媽")
    expect(field).to_be_focused()


def test_choices_survive_repaints(organizer):
    organizer.open("stopping")
    entered = organizer.enter_everything()
    organizer.wait_for_repaints(2)
    assert organizer.entered() == entered


def test_a_doctor_chosen_from_the_published_clinics_survives_repaints(organizer):
    doctors = open_with_field(organizer, "clinic_code", published=True)
    # The last of them: the form never starts on it.
    chosen = doctors.locator("option").last.get_attribute("value")
    expect(doctors).not_to_have_value(chosen)
    doctors.select_option(chosen)
    entered = organizer.form_values()
    organizer.wait_for_repaints(2)
    expect(doctors).to_have_value(chosen)
    assert organizer.form_values() == entered


# Success


def test_saving_a_draft_shows_the_result_and_keeps_the_scroll_position(organizer):
    organizer.open("stopped")
    drafts = organizer.page.locator("#saved-drafts-list article")
    before = drafts.count()
    organizer.fill_visit_form()
    with organizer.keeps_scroll_position(organizer.button("建立草稿")) as save:
        organizer.press(save)
        organizer.expect_status("草稿已建立。建立草稿不會啟動監控或傳送通知。")
        expect(drafts).to_have_count(before + 1)
        expect(organizer.button("建立草稿")).to_be_enabled()
    organizer.press(organizer.button("展開草稿"))
    expect(drafts.last).to_contain_text("88")
    expect(organizer.field("patient_number")).to_have_value("")


def test_starting_a_visit_shows_the_result_and_keeps_the_scroll_position(organizer):
    [draft, _] = organizer.open("draft", "stopped")
    organizer.press(organizer.button("展開草稿"))
    with organizer.keeps_scroll_position(organizer.start_button(draft)) as start:
        organizer.press(start)
        organizer.expect_status("服務已回覆啟動成功。")
        expect(organizer.state(draft)).to_have_text("監控中")


def test_creating_an_invitation_shows_the_link_and_keeps_the_scroll_position(organizer):
    organizer.open("stopped")
    organizer.field("member_label").fill("媽媽")
    with organizer.keeps_scroll_position(organizer.button("邀請新成員")) as invite:
        organizer.press(invite)
        link = organizer.page.get_by_label("邀請連結（限一次使用）")
        expect(link).to_have_value(INVITATION_LINK)
    expect(organizer.field("member_label")).to_have_value("")


# Pending


def test_a_pending_start_check_says_so_and_ignores_repeat_presses(organizer):
    # A stopping visit repaints the page while the start check is pending.
    [draft, stopping] = organizer.open("draft", "stopping")
    organizer.press(organizer.button("展開草稿"))
    start = organizer.start_button(draft)
    with organizer.holding("POST", "/start"):
        organizer.press(start)
        organizer.wait_for_repaints(2)
        expect(start).to_have_text("重新檢查中…")
        expect(organizer.card(draft)).to_contain_text("正在檢查可信院方觀察…")
        organizer.expect_repeat_presses_ignored(start, "POST", "/start")
        expect(organizer.state(draft)).not_to_have_text("監控中")
        # One visit may run at a time, so the start succeeds once this one is over.
        organizer.backend.settle_stop()
        expect(organizer.state(stopping)).to_have_text("已停止")
    expect(organizer.state(draft)).to_have_text("監控中")


def test_a_pending_stop_request_says_so_and_ignores_repeat_presses(organizer):
    [visit] = organizer.open("active")
    stop = organizer.stop_button(visit)
    with organizer.holding("POST", "/stop"):
        organizer.press(stop)
        expect(organizer.state(visit)).to_have_text("停止中")
        with organizer.repainting():
            organizer.press(organizer.button("重新整理"))
        expect(organizer.card(visit)).to_contain_text("停止請求處理中…")
        organizer.expect_repeat_presses_ignored(stop, "POST", "/stop")
    expect(organizer.state(visit)).to_have_text("已停止")


def test_a_pending_invitation_says_so_and_ignores_repeat_presses(organizer):
    # A stopping visit repaints the page while the invitation is pending.
    organizer.open("stopping")
    organizer.field("member_label").fill("媽媽")
    invite = organizer.page.locator("#invite-member")
    with organizer.holding("POST", "/invitations"):
        organizer.press(invite)
        expect(invite).to_have_text("建立邀請中…")
        organizer.wait_for_repaints(2)
        expect(invite).to_have_text("建立邀請中…")
        expect(organizer.field("member_label")).to_have_value("媽媽")
        organizer.expect_repeat_presses_ignored(invite, "POST", "/invitations")
    expect(invite).to_have_text("邀請新成員")


# Failure, and recovery without a reload


def test_a_failed_start_gives_its_reason_and_the_next_start_works(organizer):
    [draft] = organizer.open("draft")
    entered = organizer.enter_everything()
    organizer.press(organizer.button("展開草稿"))
    organizer.backend.set_source_readable(False)
    organizer.press(organizer.start_button(draft))
    alert = organizer.card(draft).get_by_role("alert")
    expect(alert).to_have_text(UNREADABLE_SOURCE_TEXT)
    expect(organizer.state(draft)).to_contain_text("草稿")
    assert organizer.entered() == entered

    organizer.backend.set_source_readable(True)
    organizer.press(organizer.start_button(draft))
    expect(organizer.state(draft)).to_have_text("監控中")
    expect(alert).to_have_count(0)
    assert organizer.entered() == entered
    organizer.expect_never_reloaded()


def test_a_failed_refresh_says_so_and_the_next_refresh_works(organizer):
    [visit] = organizer.open("stopped")
    entered = organizer.enter_everything()
    service = organizer.page.locator("#service-status")
    with organizer.failing("GET", "/api/organizer/visits"):
        organizer.press(organizer.button("重新整理"))
        organizer.expect_status(REQUEST_FAILED_TEXT)
        expect(service).to_have_text("服務不可用")
        assert organizer.entered() == entered

    organizer.press(organizer.button("重新整理"))
    expect(service).to_have_text("服務正常")
    expect(organizer.page.get_by_text(REQUEST_FAILED_TEXT)).to_have_count(0)
    expect(organizer.state(visit)).to_have_text("已停止")
    assert organizer.entered() == entered
    organizer.expect_never_reloaded()


def test_a_failed_invitation_says_so_and_the_next_invitation_works(organizer):
    organizer.open("stopped")
    entered = organizer.enter_everything()
    invite = organizer.button("邀請新成員")
    with organizer.failing("POST", "/invitations"):
        organizer.press(invite)
        alert = organizer.page.get_by_role("alert")
        expect(alert).to_have_text(REQUEST_FAILED_TEXT)
        assert organizer.entered() == entered

    organizer.press(invite)
    expect(organizer.page.get_by_label("邀請連結（限一次使用）")).to_be_visible()
    expect(alert).to_have_count(0)
    assert organizer.entered() == {**entered, "member_label": ""}
    organizer.expect_never_reloaded()


def test_a_failed_save_says_so_and_the_next_save_works(organizer):
    organizer.open("stopped")
    entered = organizer.enter_everything()
    with organizer.failing("POST", "/api/organizer/visits"):
        organizer.press(organizer.button("建立草稿"))
        organizer.expect_status(REQUEST_FAILED_TEXT)
        assert organizer.entered() == entered

    organizer.press(organizer.button("建立草稿"))
    organizer.expect_status("草稿已建立。建立草稿不會啟動監控或傳送通知。")
    organizer.expect_never_reloaded()


# Cancellation and stop


def test_cancelling_a_correction_leaves_the_stopped_visit_as_it_was(organizer):
    [visit] = organizer.open("stopped")
    organizer.press(organizer.card(visit).get_by_role("button", name="修正後重新檢查"))
    expect(organizer.heading("修正已停止的提醒")).to_be_visible()
    number = organizer.field("patient_number")
    expect(number).to_have_value("85")
    number.fill("99")
    organizer.press(organizer.button("取消修正"))

    expect(organizer.heading("建立候診提醒")).to_be_visible()
    expect(number).to_have_value("")
    expect(organizer.state(visit)).to_have_text("已停止")
    expect(organizer.card(visit)).to_contain_text("85")
    expect(organizer.card(visit)).not_to_contain_text("99")
    assert organizer.count_sent("POST", "/correct") == 0


def test_stopping_a_running_visit_follows_it_until_it_has_stopped(organizer):
    [visit] = organizer.open("active")
    entered = organizer.enter_everything()
    organizer.backend.hold_stop()
    organizer.press(organizer.stop_button(visit))
    organizer.expect_status("停止請求已送出，正在等候關閉確認。")
    expect(organizer.state(visit)).to_have_text("停止中")
    organizer.wait_for_repaints(2)
    expect(organizer.state(visit)).to_have_text("停止中")

    with organizer.failing("GET", "/api/organizer/visits"):
        organizer.expect_status(f"提醒狀態更新失敗，將自動重試。{REQUEST_FAILED_TEXT}")
        expect(organizer.state(visit)).to_have_text("停止中")

    organizer.backend.settle_stop()
    expect(organizer.state(visit)).to_have_text("已停止")
    expect(organizer.stop_button(visit)).to_have_count(0)
    assert organizer.entered() == entered
    organizer.expect_never_reloaded()
