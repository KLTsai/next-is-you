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
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from playwright.sync_api import expect, sync_playwright

from organizer_page import (
    CLINIC,
    UNREADABLE_SOURCE_TEXT,
    FakeBackend,
    OrganizerPage,
    RehearsalBackend,
    lapsing_day,
    visit_day,
)
from screens import SCREENS
from test_rehearsal import rehearsal
from worktree_bootstrap import require_frontend_toolchain

REQUEST_FAILED_TEXT = "操作未完成，請重新載入後再試。"
INVITATION_LINK = re.compile(r"/auth/line\?invite=.+")
STOP_HINT = "看完診或不需要時按，停止後無法恢復。"
STOPPED_TEXT = "已停止追蹤，不會再發新的 LINE 通知。"
ROOT = Path(__file__).resolve().parents[1]


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
    playwright, _ = organizer_browser
    with rehearsal(work) as origin:
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
        # A protocol test about closing a page mid-poll, not a layout test: one screen.
        page = browser.new_context(**SCREENS["desktop"]).new_page()
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


# Setup form


def test_the_note_before_the_day_is_chosen_stands_apart_from_the_next_field(organizer):
    organizer.open("stopped")
    form = organizer.page.locator("#visit-form")
    note = form.get_by_text("請先選擇科別與看診日期。", exact=True)
    expect(note).to_be_visible()
    next_label = form.get_by_text("看診號碼", exact=True)
    gap = organizer.box(next_label)["top"] - organizer.box(note)["bottom"]
    assert gap >= 8


def test_the_official_source_link_looks_the_same_on_the_form_as_on_a_card(organizer):
    [visit] = organizer.open("stopped")
    organizer.field("date").fill(visit_day())
    expect(organizer.field("clinic_code")).to_be_visible()
    name = "開啟院方官方來源（新分頁）"
    on_card = organizer.card(visit).get_by_role("link", name=name)
    on_form = organizer.page.locator("#visit-form").get_by_role("link", name=name)
    for style in ("color", "font-weight"):
        expected = on_card.evaluate(
            "(link, style) => getComputedStyle(link).getPropertyValue(style)", style
        )
        expect(on_form).to_have_css(style, expected)
    # Only the words are the link, as on the card, not the whole row.
    row = organizer.page.locator("#visit-form .source-ref")
    assert organizer.box(on_form)["width"] < organizer.box(row)["width"]


PATIENT_NUMBER_HELP = "僅供這筆追蹤使用；已儲存草稿會顯示看診號碼，方便辨識。"
CLINIC_CODE_HELP = (
    "比對忽略大小寫、空白、標點；上面的即時預覽顯示系統讀到的內容供你核對。"
)
DOCTOR_HELP = (
    "只列出該日該科排班的醫師；診間與診次自動帶入。"
    "院方可能調整排班，系統每天會重新核對，按開始時也會再核對一次。"
)


def expect_named(field, name, help_text):
    """The field is called by its visible name alone; its helper describes it."""
    expect(field).to_have_accessible_name(name)
    expect(field).to_have_accessible_description(help_text)


def press_field_name(organizer, name, field):
    form = organizer.page.locator("#visit-form")
    organizer.press(form.get_by_text(name, exact=True))
    expect(field).to_be_focused()


def test_the_typed_clinic_and_number_fields_are_named_by_their_names_alone(organizer):
    organizer.open("stopped")
    number = organizer.field("patient_number")
    expect_named(number, "看診號碼", PATIENT_NUMBER_HELP)
    organizer.field("date").fill(visit_day())
    clinic = organizer.field("clinic_code")
    expect_named(clinic, "診間代碼", CLINIC_CODE_HELP)
    clinic.fill(CLINIC)
    expect(organizer.page.locator("#clinic-preview")).to_be_visible()
    expect_named(clinic, "診間代碼", CLINIC_CODE_HELP)
    press_field_name(organizer, "診間代碼", clinic)
    press_field_name(organizer, "看診號碼", number)


def test_the_published_doctor_field_is_named_by_its_name_alone(organizer):
    doctors = open_with_field(organizer, "clinic_code", published=True)
    expect_named(doctors, "醫師 / 診間", DOCTOR_HELP)
    doctors.select_option(index=1)
    details = organizer.page.get_by_role(
        "group", name="院方公布的此診的資料", exact=True
    )
    expect(details).to_be_visible()
    expect(details).to_contain_text("合成醫師乙")
    expect_named(doctors, "醫師 / 診間", DOCTOR_HELP)
    press_field_name(organizer, "醫師 / 診間", doctors)

    # The list offers only published clinics and the browser asks for one, so
    # the page's own error shows only once that browser check is taken away.
    doctors.select_option("")
    organizer.field("patient_number").fill("88")
    doctors.evaluate("field => { field.required = false; }")
    organizer.press(organizer.button("建立草稿"))
    error = organizer.page.locator("#visit-form").get_by_role("alert")
    expect(error).to_have_text("請選擇醫師。")
    # The error describes the field after its helper, never names it.
    expect_named(doctors, "醫師 / 診間", f"{DOCTOR_HELP} 請選擇醫師。")


PAST_DATE_ERROR = "看診日期已過，請選擇今天或之後的日期。"


def test_the_department_date_and_session_fields_are_named_by_their_names_alone(
    organizer,
):
    organizer.open("stopped")
    department = organizer.field("department_code")
    date = organizer.field("date")
    expect(department).to_have_accessible_name("科別")
    expect(date).to_have_accessible_name("看診日期")
    press_field_name(organizer, "科別", department)
    press_field_name(organizer, "看診日期", date)

    # A past day opens manual entry, where the session is chosen by hand.
    date.fill(lapsing_day())
    session = organizer.field("session")
    expect(session).to_be_visible()
    expect(session).to_have_accessible_name("診次")
    press_field_name(organizer, "診次", session)

    organizer.field("clinic_code").fill(CLINIC)
    organizer.field("patient_number").fill("88")
    organizer.press(organizer.button("建立草稿"))
    error = organizer.page.locator("#visit-form").get_by_role("alert")
    expect(error).to_have_text(PAST_DATE_ERROR)
    expect(error).to_be_visible()
    expect(date).to_have_accessible_name("看診日期")
    expect(date).to_have_accessible_description(PAST_DATE_ERROR)
    expect(department).to_have_accessible_name("科別")
    expect(session).to_have_accessible_name("診次")
    press_field_name(organizer, "看診日期", date)


# Success


def test_saving_a_draft_shows_the_result_and_keeps_the_scroll_position(organizer):
    organizer.open("stopped")
    drafts = organizer.page.locator("#saved-drafts-list article")
    before = drafts.count()
    organizer.fill_visit_form()
    with organizer.keeps_scroll_position(organizer.button("建立草稿")) as save:
        organizer.press(save)
        organizer.expect_status("草稿已建立。建立草稿不會開始追蹤或傳送通知。")
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
        expect(organizer.state(draft)).to_have_text("追蹤中")


def test_a_running_visit_is_named_with_the_agreed_words_through_its_stop(organizer):
    [visit] = organizer.open("active")
    expect(organizer.heading("叫號追蹤")).to_be_visible()
    running = organizer.page.get_by_role("heading", name=re.compile(r"^進行中 \d+$"))
    expect(running).to_be_visible()
    members_heading = organizer.heading("通知名單")
    # One line, also on a phone.
    assert organizer.box(members_heading)["height"] <= 40
    expect(organizer.state(visit)).to_have_text("追蹤中")
    stop = organizer.stop_button(visit)
    expect(stop).to_have_text("停止追蹤")
    expect(stop).to_have_accessible_description(STOP_HINT)
    hint = organizer.card(visit).get_by_text(STOP_HINT, exact=True)
    expect(hint).to_be_visible()
    layout = organizer.stop_layout(visit)
    # The button keeps one line's height, with the hint directly under it.
    assert layout["height"] <= 60, layout
    assert 0 <= layout["gap"] <= 12, layout

    organizer.press(stop)
    expect(organizer.state(visit)).to_have_text("已停止")
    expect(organizer.page.locator("#app > .message")).to_have_text(STOPPED_TEXT)
    expect(organizer.card(visit).get_by_role("status")).to_have_text(STOPPED_TEXT)


def test_creating_an_invitation_shows_the_link_and_keeps_the_scroll_position(organizer):
    organizer.open("stopped")
    organizer.field("member_label").fill("媽媽")
    with organizer.keeps_scroll_position(organizer.button("邀請家人")) as invite:
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
        expect(organizer.state(draft)).not_to_have_text("追蹤中")
        # One visit may run at a time, so the start succeeds once this one is over.
        organizer.backend.settle_stop()
        expect(organizer.state(stopping)).to_have_text("已停止")
    expect(organizer.state(draft)).to_have_text("追蹤中")


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
    expect(invite).to_have_text("邀請家人")


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
    expect(organizer.state(draft)).to_have_text("追蹤中")
    expect(alert).to_have_count(0)
    assert organizer.entered() == entered
    organizer.expect_never_reloaded()


def expect_start_refusal_without_its_card(organizer, day, text):
    """The organizer reads which visit and why, until the next refresh."""
    alert = organizer.page.get_by_role("alert")
    expect(alert).to_contain_text(text)
    expect(alert).to_contain_text(day)
    expect(alert).to_contain_text("午診")
    expect(alert).to_be_in_viewport()
    organizer.press(organizer.button("重新整理"))
    expect(alert).to_have_count(0)
    organizer.expect_never_reloaded()


def test_starting_a_draft_that_was_deleted_meanwhile_says_why(organizer):
    organizer.open("stopped")
    draft = organizer.backend.add_lapsing_draft()
    organizer.press(organizer.button("重新整理"))
    organizer.press(organizer.button("展開草稿"))
    start = organizer.start_button(draft)
    expect(start).to_be_enabled()

    organizer.backend.expire_lapsing_drafts()
    organizer.press(start)

    expect(organizer.card(draft)).to_have_count(0)
    expect_start_refusal_without_its_card(
        organizer, lapsing_day(), "找不到這筆追蹤，請重新載入。"
    )


def test_starting_a_draft_that_was_started_meanwhile_says_why(organizer):
    [draft] = organizer.open("draft")
    organizer.press(organizer.button("展開草稿"))
    start = organizer.start_button(draft)
    expect(start).to_be_enabled()

    organizer.backend.start_elsewhere(draft)
    organizer.press(start)

    expect(organizer.state(draft)).to_have_text("追蹤中")
    expect_start_refusal_without_its_card(
        organizer, visit_day(), "這筆追蹤的狀態已變更，請重新載入。"
    )


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
    invite = organizer.button("邀請家人")
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
    organizer.expect_status("草稿已建立。建立草稿不會開始追蹤或傳送通知。")
    organizer.expect_never_reloaded()


# Cancellation and stop


def test_cancelling_a_correction_leaves_the_stopped_visit_as_it_was(organizer):
    [visit] = organizer.open("stopped")
    organizer.press(organizer.card(visit).get_by_role("button", name="修正後重新檢查"))
    expect(organizer.heading("修正已停止的追蹤")).to_be_visible()
    number = organizer.field("patient_number")
    expect(number).to_have_value("85")
    number.fill("99")
    organizer.press(organizer.button("取消修正"))

    expect(organizer.heading("建立叫號追蹤")).to_be_visible()
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
        organizer.expect_status(f"狀態更新失敗，將自動重試。{REQUEST_FAILED_TEXT}")
        expect(organizer.state(visit)).to_have_text("停止中")

    organizer.backend.settle_stop()
    expect(organizer.state(visit)).to_have_text("已停止")
    expect(organizer.stop_button(visit)).to_have_count(0)
    assert organizer.entered() == entered
    organizer.expect_never_reloaded()


# Layout


def test_the_recipient_list_adds_no_divider_inside_its_field(organizer):
    [visit] = organizer.open("stopped")
    wrapper = organizer.card(visit).locator(".recipient-summary").locator("xpath=..")

    expect(wrapper).to_have_css("border-top-width", "0px")
    expect(wrapper).to_have_css("padding-top", "0px")
