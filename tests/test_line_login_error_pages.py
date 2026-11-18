from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

import pytest
from httpx import ASGITransport, AsyncClient

from next_is_you.identity import IdentityRepository
from next_is_you.persistence import VisitRepository
from test_line_identity_routes import (
    SECRET,
    FakeFriendship,
    FakeOAuth,
    FakeSendGate,
    SQLiteStore,
    csrf,
    run,
    set_session,
)
from worker import create_app

READY_SETTINGS = {
    "line_login_channel_id": "local-channel",
    "line_login_channel_secret": "local-channel-secret",
    "line_login_redirect_uri": "https://family.example/auth/line/callback",
    "session_secret": SECRET,
    "organizer_subjects": {"line-organizer"},
}
INTERNAL_DETAILS = (
    "detail",
    "Invitation",
    "LINE Login",
    "not configured",
    "unavailable",
    "authorized",
    "verified",
    "official account",
)


class FailingOAuth:
    async def verify_login(self, **_kwargs):
        raise RuntimeError("LINE said no")


def make_app(store, *, settings=READY_SETTINGS, oauth=None, friendship=None):
    visits = VisitRepository(store)
    return create_app(
        settings=settings,
        line_client=oauth or FakeOAuth(),
        friendship_client=friendship,
        identity_repository=IdentityRepository(store),
        visit_repository=visits,
        send_gate=FakeSendGate(visits),
        clock=lambda: 1_000,
    )


def client_for(app) -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=app), base_url="https://family.example"
    )


async def new_invitation(store) -> str:
    invitation = await IdentityRepository(store).create_invitation(
        "line-organizer", "媽媽", datetime.fromtimestamp(1_000, timezone.utc)
    )
    return invitation.token


def state_of(start) -> str:
    return parse_qs(urlparse(start.headers["location"]).query)["state"][0]


def assert_plain_page(response, status: int, cause: str, next_step: str) -> None:
    assert response.status_code == status
    assert response.headers["content-type"].startswith("text/html")
    assert response.headers.get("cache-control") == "no-store"
    text = response.text
    assert '<html lang="zh-Hant">' in text
    assert cause in text
    assert next_step in text
    for leaked in INTERNAL_DETAILS:
        assert leaked not in text


def test_start_with_unusable_invitation_shows_plain_page():
    async def scenario():
        store = SQLiteStore()
        async with client_for(make_app(store)) as http:
            response = await http.get("/auth/line", params={"invite": "nope"})
        assert_plain_page(response, 410, "邀請連結已失效", "聯絡管理者重新發送邀請連結")

    run(scenario())


def test_start_with_invitation_while_sign_in_is_not_configured_shows_plain_page():
    async def scenario():
        store = SQLiteStore()
        async with client_for(make_app(store, settings={})) as http:
            response = await http.get("/auth/line", params={"invite": "any"})
        assert_plain_page(response, 503, "LINE 登入目前無法使用", "稍後再試")

    run(scenario())


def test_organizer_start_while_sign_in_is_not_configured_shows_plain_page():
    async def scenario():
        async with client_for(make_app(SQLiteStore(), settings={})) as http:
            response = await http.get("/auth/line")
        assert_plain_page(response, 503, "LINE 登入目前無法使用", "稍後再試")

    run(scenario())


def test_callback_while_sign_in_is_not_configured_shows_plain_page():
    async def scenario():
        async with client_for(make_app(SQLiteStore(), settings={})) as http:
            response = await http.get("/auth/line/callback")
        assert_plain_page(response, 503, "LINE 登入目前無法使用", "稍後再試")

    run(scenario())


def test_callback_without_a_matching_sign_in_shows_plain_page():
    async def scenario():
        async with client_for(make_app(SQLiteStore())) as http:
            response = await http.get(
                "/auth/line/callback", params={"code": "c", "state": "s"}
            )
        assert_plain_page(response, 401, "無法確認你的 LINE 登入", "重新開啟")

    run(scenario())


def test_callback_when_line_rejects_the_code_shows_plain_page():
    async def scenario():
        async with client_for(make_app(SQLiteStore(), oauth=FailingOAuth())) as http:
            start = await http.get("/auth/line")
            response = await http.get(
                "/auth/line/callback",
                params={"code": "c", "state": state_of(start)},
            )
        assert_plain_page(response, 401, "無法確認你的 LINE 登入", "重新開啟")

    run(scenario())


def test_callback_without_friendship_client_shows_plain_page():
    async def scenario():
        store = SQLiteStore()
        token = await new_invitation(store)
        async with client_for(make_app(store, friendship=None)) as http:
            start = await http.get("/auth/line", params={"invite": token})
            response = await http.get(
                "/auth/line/callback",
                params={"code": "c", "state": state_of(start)},
            )
        assert_plain_page(response, 503, "暫時無法確認", "稍後再開啟邀請連結")

    run(scenario())


@pytest.mark.parametrize(
    ("is_friend", "status", "cause", "next_step"),
    [
        (None, 503, "暫時無法確認", "稍後再開啟邀請連結"),
        (False, 409, "還沒有加入官方帳號", "加入官方帳號為好友後"),
    ],
)
def test_callback_with_missing_or_unverifiable_friendship_shows_plain_page(
    is_friend, status, cause, next_step
):
    async def scenario():
        store = SQLiteStore()
        token = await new_invitation(store)
        app = make_app(store, friendship=FakeFriendship(is_friend))
        async with client_for(app) as http:
            start = await http.get("/auth/line", params={"invite": token})
            response = await http.get(
                "/auth/line/callback",
                params={"code": "c", "state": state_of(start)},
            )
        assert_plain_page(response, status, cause, next_step)

    run(scenario())


def test_callback_for_an_invitation_used_in_the_meantime_shows_plain_page():
    async def scenario():
        store = SQLiteStore()
        token = await new_invitation(store)
        app = make_app(store, friendship=FakeFriendship(True))
        async with client_for(app) as first, client_for(app) as second:
            first_start = await first.get("/auth/line", params={"invite": token})
            second_start = await second.get("/auth/line", params={"invite": token})
            joined = await first.get(
                "/auth/line/callback",
                params={"code": "c", "state": state_of(first_start)},
            )
            response = await second.get(
                "/auth/line/callback",
                params={"code": "c", "state": state_of(second_start)},
            )
        assert joined.status_code == 303
        assert_plain_page(response, 410, "邀請連結已失效", "聯絡管理者重新發送邀請連結")

    run(scenario())


def test_callback_for_an_account_that_is_not_the_manager_shows_plain_page():
    async def scenario():
        async with client_for(make_app(SQLiteStore())) as http:
            start = await http.get("/auth/line")
            response = await http.get(
                "/auth/line/callback",
                params={"code": "c", "state": state_of(start)},
            )
        assert_plain_page(response, 403, "不是管理者", "邀請連結")

    run(scenario())


def test_failure_pages_clear_the_login_transaction_cookie():
    async def scenario():
        async with client_for(make_app(SQLiteStore(), oauth=FailingOAuth())) as http:
            start = await http.get("/auth/line")
            response = await http.get(
                "/auth/line/callback",
                params={"code": "c", "state": state_of(start)},
            )
        assert "Max-Age=0" in response.headers["set-cookie"]

    run(scenario())


def test_api_routes_keep_their_json_error_bodies():
    async def scenario():
        async with client_for(make_app(SQLiteStore())) as http:
            set_session(http, "line-organizer", "organizer")
            response = await http.post("/api/organizer/invitations", headers=csrf(http))
        assert response.status_code == 422
        assert response.headers["content-type"].startswith("application/json")
        assert "detail" in response.json() or "error" in response.json()

    run(scenario())
