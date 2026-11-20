from __future__ import annotations

import asyncio
import sqlite3
from dataclasses import fields
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import parse_qs, urlparse

from httpx import ASGITransport, AsyncClient

from next_is_you.auth import CSRF_COOKIE_NAME, SESSION_COOKIE_NAME, issue_session
from next_is_you.identity import IdentityRepository
from next_is_you.line_login import VerifiedLineIdentity
from next_is_you.line_messaging import FriendshipResult
from next_is_you.persistence import Statement, VisitRepository
from worker import create_app


SECRET = "local-test-secret-with-at-least-32-bytes"
MIGRATIONS = sorted((Path(__file__).resolve().parents[1] / "migrations").glob("*.sql"))


class SQLiteStore:
    def __init__(self) -> None:
        self.connection = sqlite3.connect(":memory:", isolation_level=None)
        self.connection.row_factory = sqlite3.Row
        for migration in MIGRATIONS:
            self.connection.executescript(migration.read_text())

    async def execute(self, statement: Statement) -> int:
        return self.connection.execute(statement.sql, statement.values).rowcount

    async def fetch_all(self, statement: Statement) -> list[Mapping[str, Any]]:
        return [
            dict(row)
            for row in self.connection.execute(statement.sql, statement.values)
        ]

    async def batch(self, statements: Sequence[Statement]) -> list[int]:
        self.connection.execute("BEGIN")
        try:
            results = [
                self.connection.execute(item.sql, item.values).rowcount
                for item in statements
            ]
        except Exception:
            self.connection.execute("ROLLBACK")
            raise
        self.connection.execute("COMMIT")
        return results


class FakeOAuth:
    async def verify_login(self, **_kwargs):
        return VerifiedLineIdentity("line-recipient", "transient-user-token")


class FakeFriendship:
    def __init__(self, result: bool | None = True) -> None:
        self.result = result
        self.tokens: list[str] = []

    async def check_friendship(self, user_access_token: str) -> FriendshipResult:
        self.tokens.append(user_access_token)
        return FriendshipResult(self.result)


class FakeSendGate:
    def __init__(self, visits: VisitRepository) -> None:
        self.visits = visits
        self.held = False

    async def add_visit_recipient(
        self, visit_id: str, recipient_id: str, now: datetime
    ) -> bool:
        return await self.visits.add_recipient(visit_id, recipient_id, now)

    async def withdraw_recipient(self, recipient_id: str, _now: str) -> bool:
        return await self.visits.withdraw_recipient(recipient_id)

    async def hold_for_reconciliation(self) -> bool:
        self.held = True
        return True

    async def resume_after_reconciliation(self, reconciled: bool) -> bool:
        if not reconciled or not self.held:
            return False
        self.held = False
        return True


def run(coroutine):
    return asyncio.run(coroutine)


def make_app(store: SQLiteStore, friendship: FakeFriendship):
    visit_repository = VisitRepository(store)
    return create_app(
        settings={
            "line_login_channel_id": "local-channel",
            "line_login_channel_secret": "local-channel-secret",
            "line_login_redirect_uri": "https://family.example/auth/line/callback",
            "session_secret": SECRET,
            "organizer_subjects": {"line-organizer"},
        },
        line_client=FakeOAuth(),
        friendship_client=friendship,
        identity_repository=IdentityRepository(store),
        visit_repository=visit_repository,
        send_gate=FakeSendGate(visit_repository),
        clock=lambda: 1_000,
    )


def set_session(client: AsyncClient, subject: str, role: str, now: int = 1_000) -> None:
    session = issue_session(subject, role, SECRET, now=now)
    client.cookies.set(
        SESSION_COOKIE_NAME, session.value, domain="family.example", path="/"
    )
    client.cookies.set(
        CSRF_COOKIE_NAME, session.csrf_token, domain="family.example", path="/"
    )


def csrf(client: AsyncClient) -> dict[str, str]:
    return {"x-csrf-token": client.cookies[CSRF_COOKIE_NAME]}


def test_invitation_enrollment_checks_friendship_then_requires_explicit_consent():
    async def scenario():
        store = SQLiteStore()
        friendship = FakeFriendship(True)
        identity_repo = IdentityRepository(store)
        invite = await identity_repo.create_invitation(
            "line-organizer", "媽媽", datetime.fromtimestamp(1_000, timezone.utc)
        )
        app = make_app(store, friendship)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="https://family.example"
        ) as http:
            start = await http.get("/auth/line", params={"invite": invite.token})
            params = parse_qs(urlparse(start.headers["location"]).query)
            assert params["scope"] == ["openid profile"]
            callback = await http.get(
                "/auth/line/callback",
                params={"code": "local-code", "state": params["state"][0]},
            )
            row = store.connection.execute(
                "SELECT * FROM recipients WHERE line_subject = 'line-recipient'"
            ).fetchone()
            assert callback.status_code == 303
            assert callback.headers["location"] == "/recipient/consent"
            assert friendship.tokens == ["transient-user-token"]
            assert row["active"] == 0
            assert row["display_name"] == "媽媽"
            assert row["consented_at"] is None
            assert row["friendship_checked_at"] is not None
            assert "transient-user-token" not in repr(dict(row))
            saved_invite = store.connection.execute(
                "SELECT token_hash FROM invitations"
            ).fetchone()[0]
            assert saved_invite == invite_hash(invite.token)
            assert saved_invite != invite.token
            reused = await http.get("/auth/line", params={"invite": invite.token})
            assert reused.status_code == 410

            opt_in = await http.post("/api/recipient/opt-in", headers=csrf(http))
            assert opt_in.status_code == 204
            opted_in = store.connection.execute(
                "SELECT active, consented_at FROM recipients WHERE line_subject = 'line-recipient'"
            ).fetchone()
            assert opted_in["active"] == 1
            assert opted_in["consented_at"] is not None

            denied = await http.post("/api/organizer/invitations", headers=csrf(http))
            assert denied.status_code == 403

        assert "transient-user-token" not in repr(
            store.connection.execute("SELECT * FROM recipients").fetchone()
        )

    run(scenario())


def test_failed_or_unknown_friendship_check_does_not_consume_invitation():
    async def scenario():
        for status in (False, None):
            store = SQLiteStore()
            identity_repo = IdentityRepository(store)
            invitation = await identity_repo.create_invitation(
                "line-organizer",
                "",
                datetime.fromtimestamp(1_000, timezone.utc),
            )
            friendship = FakeFriendship(status)
            app = make_app(store, friendship)
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="https://family.example"
            ) as http:
                start = await http.get(
                    "/auth/line", params={"invite": invitation.token}
                )
                state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
                callback = await http.get(
                    "/auth/line/callback", params={"code": "local-code", "state": state}
                )

            assert callback.status_code == (409 if status is False else 503)
            row = store.connection.execute(
                "SELECT used_at FROM invitations WHERE token_hash = ?",
                (invite_hash(invitation.token),),
            ).fetchone()
            assert row["used_at"] is None
            assert (
                store.connection.execute("SELECT COUNT(*) FROM recipients").fetchone()[
                    0
                ]
                == 0
            )

    run(scenario())


def test_recipient_flow_requests_profile_scope_while_organizer_flow_is_unchanged():
    async def scenario():
        store = SQLiteStore()
        friendship = FakeFriendship(True)
        identity_repo = IdentityRepository(store)
        invite = await identity_repo.create_invitation(
            "line-organizer", "媽媽", datetime.fromtimestamp(1_000, timezone.utc)
        )
        app = make_app(store, friendship)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="https://family.example"
        ) as http:
            recipient_start = await http.get(
                "/auth/line", params={"invite": invite.token}
            )
            recipient_params = parse_qs(
                urlparse(recipient_start.headers["location"]).query
            )
            assert recipient_params["scope"] == ["openid profile"]

            organizer_start = await http.get("/auth/line")
            organizer_params = parse_qs(
                urlparse(organizer_start.headers["location"]).query
            )
            assert organizer_params["scope"] == ["openid"]

        assert not hasattr(VerifiedLineIdentity, "display_name")
        assert not hasattr(VerifiedLineIdentity, "picture_url")
        assert {f.name for f in fields(VerifiedLineIdentity)} == {
            "subject",
            "user_access_token",
        }

    run(scenario())


def test_server_side_roles_and_selection_require_active_enrollment_and_consent():
    async def scenario():
        store = SQLiteStore()
        friendship = FakeFriendship(True)
        app = make_app(store, friendship)
        identity_repo = IdentityRepository(store)
        invitation = await identity_repo.create_invitation(
            "line-organizer", "Family", datetime.fromtimestamp(900, timezone.utc)
        )
        await identity_repo.accept_invitation(
            token_hash=invite_hash(invitation.token),
            line_subject="line-recipient",
            now=datetime.fromtimestamp(900, timezone.utc),
            friendship_checked_at=datetime.fromtimestamp(900, timezone.utc),
        )
        visits = VisitRepository(store)
        await visits.create_draft(
            visit_id="visit-1",
            hospital="ntuh-main",
            visit_day=date(2026, 9, 28),
            department_code="MED",
            clinic_code="MED-A",
            clinic_session="morning",
            patient_number=45,
            now=datetime.fromtimestamp(1_000, timezone.utc),
        )
        recipient_id = await identity_repo.recipient_id("line-recipient")
        assert recipient_id

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="https://family.example"
        ) as recipient:
            set_session(recipient, "line-recipient", "recipient")
            forbidden = await recipient.post(
                f"/api/visits/visit-1/recipients/{recipient_id}",
                headers=csrf(recipient),
            )
            assert forbidden.status_code == 403

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="https://family.example"
        ) as organizer:
            set_session(organizer, "line-organizer", "organizer")
            not_yet_eligible = await organizer.post(
                f"/api/visits/visit-1/recipients/{recipient_id}",
                headers=csrf(organizer),
            )
            assert not_yet_eligible.status_code == 409

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="https://family.example"
        ) as recipient:
            set_session(recipient, "line-recipient", "recipient")
            opted_in = await recipient.post(
                "/api/recipient/opt-in", headers=csrf(recipient)
            )
            assert opted_in.status_code == 204

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="https://family.example"
        ) as organizer:
            set_session(organizer, "line-organizer", "organizer")
            selected = await organizer.post(
                f"/api/visits/visit-1/recipients/{recipient_id}",
                headers=csrf(organizer),
            )
            assert selected.status_code == 204
            assert friendship.tokens == []
            assert (
                store.connection.execute(
                    "SELECT COUNT(*) FROM visit_recipients WHERE visit_id = 'visit-1'"
                ).fetchone()[0]
                == 1
            )

    run(scenario())


def test_organizer_allowlist_and_csrf_are_rechecked_for_each_mutation():
    async def scenario():
        store = SQLiteStore()
        app = make_app(store, FakeFriendship())
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="https://family.example"
        ) as client:
            set_session(client, "not-allowlisted", "organizer")
            denied = await client.post(
                "/api/organizer/invitations", headers=csrf(client)
            )
            assert denied.status_code == 403

            set_session(client, "line-organizer", "organizer")
            missing_csrf = await client.post("/api/organizer/invitations")
            assert missing_csrf.status_code == 403
            empty_body = await client.post(
                "/api/organizer/invitations", headers=csrf(client)
            )
            malformed_body = await client.post(
                "/api/organizer/invitations", headers=csrf(client), content=b"{"
            )
            assert empty_body.status_code == 422
            assert malformed_body.status_code == 422
            created = await client.post(
                "/api/organizer/invitations",
                headers=csrf(client),
                json={"member_label": "爸爸"},
            )

        assert created.status_code == 201
        assert (
            store.connection.execute("SELECT member_label FROM invitations").fetchone()[
                0
            ]
            == "爸爸"
        )
        assert created.json()["invitation_url"].startswith(
            "https://family.example/auth/line?invite="
        )
        assert (
            store.connection.execute("SELECT COUNT(*) FROM invitations").fetchone()[0]
            == 1
        )

    run(scenario())


def test_scheduler_recovery_controls_require_organizer_csrf_and_explicit_resume():
    async def scenario():
        store = SQLiteStore()
        app = make_app(store, FakeFriendship())
        gate = app.state.send_gate
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="https://family.example"
        ) as client:
            set_session(client, "line-organizer", "organizer")

            denied = await client.post("/api/organizer/scheduler/recovery-hold")
            assert denied.status_code == 403
            assert gate.held is False

            held = await client.post(
                "/api/organizer/scheduler/recovery-hold", headers=csrf(client)
            )
            assert held.status_code == 204
            assert gate.held is True

            missing_confirmation = await client.post(
                "/api/organizer/scheduler/resume", headers=csrf(client), json={}
            )
            assert missing_confirmation.status_code == 400
            assert gate.held is True

            wrong_csrf = await client.post(
                "/api/organizer/scheduler/resume",
                headers={"x-csrf-token": "wrong"},
                json={"reconciled": True},
            )
            assert wrong_csrf.status_code == 403
            assert gate.held is True

            resumed = await client.post(
                "/api/organizer/scheduler/resume",
                headers=csrf(client),
                json={"reconciled": True},
            )
            assert resumed.status_code == 204
            assert gate.held is False

            already_running = await client.post(
                "/api/organizer/scheduler/resume",
                headers=csrf(client),
                json={"reconciled": True},
            )
            assert already_running.status_code == 409

    run(scenario())


def test_withdrawal_revokes_recipient_session_authority():
    async def scenario():
        store = SQLiteStore()
        app = make_app(store, FakeFriendship())
        identity_repo = IdentityRepository(store)
        invitation = await identity_repo.create_invitation(
            "line-organizer", "Family", datetime.fromtimestamp(900, timezone.utc)
        )
        await identity_repo.accept_invitation(
            token_hash=invite_hash(invitation.token),
            line_subject="line-recipient",
            now=datetime.fromtimestamp(900, timezone.utc),
            friendship_checked_at=datetime.fromtimestamp(900, timezone.utc),
        )
        await identity_repo.opt_in(
            "line-recipient", datetime.fromtimestamp(1_000, timezone.utc)
        )

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="https://family.example"
        ) as client:
            set_session(client, "line-recipient", "recipient")
            withdrawn = await client.post(
                "/api/recipient/withdraw", headers=csrf(client)
            )
            denied = await client.post("/api/recipient/opt-in", headers=csrf(client))

        assert withdrawn.status_code == 204
        assert denied.status_code == 403
        assert (
            store.connection.execute("SELECT COUNT(*) FROM recipients").fetchone()[0]
            == 0
        )

    run(scenario())


def test_organizer_can_withdraw_recipient_from_roster_and_block_future_sends():
    async def scenario():
        store = SQLiteStore()
        app = make_app(store, FakeFriendship())
        identity_repo = IdentityRepository(store)
        invitation = await identity_repo.create_invitation(
            "line-organizer", "Family", datetime.fromtimestamp(900, timezone.utc)
        )
        await identity_repo.accept_invitation(
            token_hash=invite_hash(invitation.token),
            line_subject="line-recipient",
            now=datetime.fromtimestamp(900, timezone.utc),
            friendship_checked_at=datetime.fromtimestamp(900, timezone.utc),
        )
        await identity_repo.opt_in(
            "line-recipient", datetime.fromtimestamp(1_000, timezone.utc)
        )
        recipient_id = await identity_repo.recipient_id("line-recipient")
        assert recipient_id
        visits = VisitRepository(store)
        await visits.create_draft(
            visit_id="visit-1",
            hospital="ntuh-main",
            visit_day=date(2026, 9, 28),
            department_code="MED",
            clinic_code="MED-A",
            clinic_session="morning",
            patient_number=45,
            now=datetime.fromtimestamp(1_000, timezone.utc),
        )

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="https://family.example"
        ) as client:
            set_session(client, "not-allowlisted", "organizer")
            denied = await client.post(
                f"/api/organizer/recipients/{recipient_id}/withdraw",
                headers=csrf(client),
            )
            assert denied.status_code == 403

            set_session(client, "line-organizer", "organizer")
            missing_csrf = await client.post(
                f"/api/organizer/recipients/{recipient_id}/withdraw"
            )
            assert missing_csrf.status_code == 403

            withdrawn = await client.post(
                f"/api/organizer/recipients/{recipient_id}/withdraw",
                headers=csrf(client),
            )
            assert withdrawn.status_code == 204

            already_withdrawn = await client.post(
                f"/api/organizer/recipients/{recipient_id}/withdraw",
                headers=csrf(client),
            )
            assert already_withdrawn.status_code == 404

            roster = await client.get("/api/organizer/recipients")
            assert roster.json() == {"recipients": []}

            blocked = await client.post(
                f"/api/visits/visit-1/recipients/{recipient_id}",
                headers=csrf(client),
            )
            assert blocked.status_code == 409

        assert (
            store.connection.execute("SELECT COUNT(*) FROM recipients").fetchone()[0]
            == 0
        )

    run(scenario())


def invite_hash(token: str) -> str:
    from next_is_you.identity import hash_invitation

    return hash_invitation(token)
