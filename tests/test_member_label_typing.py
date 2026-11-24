"""A member label typed in 成員稱呼 survives the dashboard's background updates.

Local integration: real browser on the local rehearsal Worker, synthetic login.
"""

from __future__ import annotations

from playwright.sync_api import expect, sync_playwright

from test_rehearsal import rehearsal


def test_rehearsal_member_label_typed_by_the_organizer_is_not_cleared(tmp_path):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(viewport={"width": 1280, "height": 900})
        context.grant_permissions(["clipboard-read", "clipboard-write"])
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
            with rehearsal(tmp_path) as origin:
                page.goto(origin)
                page.get_by_role("button", name="本機合成測試登入").click()
                label = page.get_by_label("成員稱呼")
                expect(label).to_be_visible()
                label.fill("媽媽")
                page.get_by_role("button", name="邀請新成員").click()
                page.get_by_role("button", name="複製連結").click()
                expect(page.get_by_role("button", name="已複製")).to_be_visible()
                # The organizer now types the next member's label.
                label.press_sequentially("小", delay=100)
                # Past the 2 s "已複製" reset, which re-renders the dashboard.
                page.wait_for_timeout(2500)
                label.press_sequentially("妹", delay=100)
                page.wait_for_timeout(500)
                assert label.input_value() == "小妹"
                expect(label).to_be_focused()
        finally:
            context.close()
            browser.close()


def test_rehearsal_member_label_survives_refresh_and_follows_the_invitation_result(
    tmp_path,
):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(viewport={"width": 1280, "height": 900})
        fail_invitations = {"on": False}

        def route(route):
            request = route.request
            if not request.url.startswith(origin + "/"):
                route.abort()
            elif fail_invitations["on"] and request.url.endswith(
                "/api/organizer/invitations"
            ):
                route.fulfill(status=500, body="{}")
            else:
                route.continue_()

        context.route("**/*", route)
        page = context.new_page()
        try:
            with rehearsal(tmp_path) as origin:
                page.goto(origin)
                page.get_by_role("button", name="本機合成測試登入").click()
                label = page.get_by_label("成員稱呼")
                label.press_sequentially("小妹", delay=50)
                page.get_by_role("button", name="重新整理").click()
                page.wait_for_timeout(500)
                assert label.input_value() == "小妹"

                fail_invitations["on"] = True
                page.get_by_role("button", name="邀請新成員").click()
                expect(page.get_by_role("alert")).to_be_visible()
                assert label.input_value() == "小妹"

                fail_invitations["on"] = False
                page.get_by_role("button", name="邀請新成員").click()
                expect(page.get_by_label("邀請連結（限一次使用）")).to_be_visible()
                assert label.input_value() == ""
        finally:
            context.close()
            browser.close()
