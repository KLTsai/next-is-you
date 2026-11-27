"""Issue #134: an invitee on the consent page is kept until they opt in.

Fixture/mock: the real HTTP routes, the real `SystemSendGate` and the real
migrations on in-memory SQLite. LINE login and the friendship check are fakes.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import pytest
from httpx import ASGITransport, AsyncClient

from local_d1 import LocalD1, LocalStore
from next_is_you.identity import IdentityRepository
from next_is_you.line_login import VerifiedLineIdentity
from next_is_you.persistence import VisitRepository, iso_utc
from next_is_you.send_gate import SystemSendGate
from test_line_identity_routes import SECRET, FakeFriendship, csrf, set_session
from test_local_acceptance import LocalContext
from worker import create_app

ORGANIZER = "line-organizer"
ACCEPTED_AT = datetime(2026, 11, 20, 2, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now.timestamp()


class FakeLogin:
    """LINE login that signs in whoever the test says is at the browser."""

    def __init__(self) -> None:
        self.subject = "line-invitee"

    async def verify_login(self, **_kwargs):
        return VerifiedLineIdentity(self.subject, "transient-user-token")


class Family:
    """One deployment: the database, its send gate and the Worker's routes."""

    def __init__(self, environment: str) -> None:
        self.database = LocalD1()
        self.clock = Clock(ACCEPTED_AT)
        self.login = FakeLogin()
        self.gate = SystemSendGate(
            LocalContext(),
            {
                "DB": self.database,
                "NIY_ENVIRONMENT": environment,
                "NIY006_LOCAL_TEST_MODE": "1" if environment == "local-test" else "0",
            },
        )
        self.app = create_app(
            settings={
                "line_login_channel_id": "local-channel",
                "line_login_channel_secret": "local-channel-secret",
                "line_login_redirect_uri": "https://family.example/auth/line/callback",
                "session_secret": SECRET,
                "organizer_subjects": {ORGANIZER},
            },
            line_client=self.login,
            friendship_client=FakeFriendship(True),
            identity_repository=IdentityRepository(LocalStore(self.database)),
            visit_repository=VisitRepository(LocalStore(self.database)),
            send_gate=self.gate,
            clock=self.clock,
        )

    def browser(self) -> AsyncClient:
        return AsyncClient(
            transport=ASGITransport(app=self.app), base_url="https://family.example"
        )

    def sign_in_organizer(self, browser: AsyncClient) -> None:
        set_session(browser, ORGANIZER, "organizer", now=int(self.clock()))

    async def invite(self, label: str) -> str:
        async with self.browser() as organizer:
            self.sign_in_organizer(organizer)
            response = await organizer.post(
                "/api/organizer/invitations",
                json={"member_label": label},
                headers=csrf(organizer),
            )
        assert response.status_code == 201, response.text
        return response.json()["invitation_url"].rsplit("invite=", 1)[1]

    async def sign_in_with_invitation(
        self, browser: AsyncClient, token: str, subject: str
    ):
        self.login.subject = subject
        start = await browser.get("/auth/line", params={"invite": token})
        state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
        return await browser.get(
            "/auth/line/callback", params={"code": "local-code", "state": state}
        )

    async def accept(self, browser: AsyncClient, token: str, subject: str) -> None:
        """Open the link and sign in with LINE; the browser lands on consent."""
        callback = await self.sign_in_with_invitation(browser, token, subject)
        assert callback.headers["location"] == "/recipient/consent"

    async def can_accept(self, token: str, subject: str) -> bool:
        async with self.browser() as browser:
            callback = await self.sign_in_with_invitation(browser, token, subject)
        return callback.headers.get("location") == "/recipient/consent"

    async def joined(self, label: str, subject: str) -> None:
        """Someone who accepted and pressed 確認加入 straight away."""
        token = await self.invite(label)
        async with self.browser() as browser:
            await self.accept(browser, token, subject)
            opt_in = await browser.post("/api/recipient/opt-in", headers=csrf(browser))
        assert opt_in.status_code == 204

    async def roster_rows(self) -> list[dict]:
        async with self.browser() as organizer:
            self.sign_in_organizer(organizer)
            response = await organizer.get("/api/organizer/recipients")
        return response.json()["recipients"]

    async def roster(self) -> list[str]:
        return [row["display_name"] for row in await self.roster_rows()]

    async def withdraw(self, label: str) -> None:
        [recipient] = [
            r for r in await self.roster_rows() if r["display_name"] == label
        ]
        async with self.browser() as organizer:
            self.sign_in_organizer(organizer)
            response = await organizer.post(
                f"/api/organizer/recipients/{recipient['id']}/withdraw",
                headers=csrf(organizer),
            )
        assert response.status_code == 204

    async def tick(self) -> dict:
        return await self.gate.scheduled_tick(iso_utc(self.clock.now))


@pytest.mark.asyncio
@pytest.mark.parametrize("environment", ["staging", "local-test"])
async def test_an_invitee_who_waits_through_a_scheduler_tick_still_joins(environment):
    family = Family(environment)
    token = await family.invite("小妹")
    async with family.browser() as invitee:
        await family.accept(invitee, token, "line-invitee")

        family.clock.now += timedelta(minutes=2)
        await family.tick()
        opt_in = await invitee.post("/api/recipient/opt-in", headers=csrf(invitee))

    assert opt_in.status_code == 204
    assert await family.roster() == ["小妹"]


@pytest.mark.asyncio
async def test_withdrawing_someone_else_leaves_an_invitee_on_the_consent_page():
    family = Family("staging")
    await family.joined("媽媽", "line-mother")
    token = await family.invite("小妹")
    async with family.browser() as invitee:
        await family.accept(invitee, token, "line-invitee")

        await family.withdraw("媽媽")
        opt_in = await invitee.post("/api/recipient/opt-in", headers=csrf(invitee))

    assert opt_in.status_code == 204
    assert await family.roster() == ["小妹"]


@pytest.mark.asyncio
async def test_a_new_invitation_lets_a_pending_invitee_join_at_once():
    # 小妹 signed in at 20:00 and never pressed 確認加入; her sign-in has lapsed
    # by the next morning. The organizer's new link works straight away.
    family = Family("staging")
    first = await family.invite("妹妹")
    async with family.browser() as invitee:
        await family.accept(invitee, first, "line-invitee")

    family.clock.now += timedelta(hours=12)
    await family.joined("小妹", "line-invitee")

    assert await family.roster() == ["小妹"]


@pytest.mark.asyncio
async def test_a_new_invitation_does_not_take_over_someone_who_joined():
    family = Family("staging")
    await family.joined("媽媽", "line-mother")

    taken = await family.can_accept(await family.invite("別人"), "line-mother")

    assert not taken
    assert await family.roster() == ["媽媽"]


@pytest.mark.asyncio
async def test_an_invitee_who_never_confirms_is_erased_once_their_sign_in_lapses():
    # The sign-in from the invitation lasts four hours; after that the invitee
    # can no longer press 確認加入, so the row is erased. Joined family stays.
    family = Family("staging")
    await family.joined("媽媽", "line-mother")
    token = await family.invite("小妹")
    async with family.browser() as invitee:
        await family.accept(invitee, token, "line-invitee")

    family.clock.now += timedelta(hours=3, minutes=59)
    assert (await family.tick())["pending_invitees_erased"] == 0

    family.clock.now += timedelta(minutes=2)
    assert (await family.tick())["pending_invitees_erased"] == 1
    assert await family.roster() == ["媽媽"]
