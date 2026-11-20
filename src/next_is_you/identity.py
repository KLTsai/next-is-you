"""Invitation and recipient identity persistence operations."""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from next_is_you.persistence import SqlStore, Statement, iso_utc


INVITATION_TTL = timedelta(hours=24)


@dataclass(frozen=True, slots=True)
class Invitation:
    token: str
    expires_at: datetime


def hash_invitation(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class IdentityRepository:
    def __init__(self, store: SqlStore) -> None:
        self._store = store

    async def create_invitation(
        self, organizer: str, member_label: str, now: datetime
    ) -> Invitation:
        token = secrets.token_urlsafe(32)
        expires_at = now + INVITATION_TTL
        await self._store.execute(
            Statement(
                "INSERT INTO invitations (token_hash, expires_at, created_by, created_at, member_label) VALUES (?, ?, ?, ?, ?)",
                (
                    hash_invitation(token),
                    iso_utc(expires_at),
                    organizer,
                    iso_utc(now),
                    member_label,
                ),
            )
        )
        return Invitation(token, expires_at)

    async def invitation_is_valid(self, token: str, now: datetime) -> bool:
        rows = await self._store.fetch_all(
            Statement(
                "SELECT 1 FROM invitations WHERE token_hash = ? AND used_at IS NULL AND expires_at > ?",
                (hash_invitation(token), iso_utc(now)),
            )
        )
        return bool(rows)

    async def accept_invitation(
        self,
        *,
        token_hash: str,
        line_subject: str,
        now: datetime,
        friendship_checked_at: datetime,
    ) -> bool:
        """Consume an invitation once and create a pending, non-opted-in identity.

        Someone still pending from an earlier invitation takes the new one: their
        row gets the new label and a fresh start, so an organizer is never
        blocked from inviting them again (#134). A recipient who has opted in,
        or a withdrawal not yet erased, still refuses the invitation.
        """
        iso_utc(now)  # Reject naive timestamps before issuing a one-time transition.
        consumed_at = (
            (
                now.astimezone(timezone.utc)
                + timedelta(microseconds=secrets.randbelow(1_000_000))
            )
            .isoformat(timespec="microseconds")
            .replace("+00:00", "Z")
        )
        recipient_id = secrets.token_urlsafe(18)
        token_digest = token_hash
        changes = await self._store.batch(
            (
                Statement(
                    """UPDATE invitations SET used_at = ? WHERE token_hash = ?
                    AND used_at IS NULL AND expires_at > ?
                    AND NOT EXISTS (
                        SELECT 1 FROM recipients WHERE line_subject = ?
                        AND NOT (active = 0 AND consented_at IS NULL)
                    )""",
                    (consumed_at, token_digest, iso_utc(now), line_subject),
                ),
                Statement(
                    """INSERT INTO recipients (
                        id, line_subject, display_name, consented_at,
                        friendship_checked_at, active, created_at
                    ) SELECT ?, ?, member_label, NULL, ?, 0, ? FROM invitations
                    WHERE token_hash = ? AND used_at = ?
                    ON CONFLICT (line_subject) DO UPDATE SET
                        display_name = excluded.display_name,
                        friendship_checked_at = excluded.friendship_checked_at,
                        created_at = excluded.created_at
                    WHERE recipients.active = 0 AND recipients.consented_at IS NULL""",
                    (
                        recipient_id,
                        line_subject,
                        iso_utc(friendship_checked_at),
                        iso_utc(now),
                        token_digest,
                        consumed_at,
                    ),
                ),
            )
        )
        return changes == [1, 1]

    async def set_friendship(
        self, line_subject: str, checked_at: datetime, is_friend: bool
    ) -> bool:
        rows = await self._store.execute(
            Statement(
                "UPDATE recipients SET friendship_checked_at = ? WHERE line_subject = ?",
                (iso_utc(checked_at) if is_friend else None, line_subject),
            )
        )
        return rows == 1 and is_friend

    async def opt_in(self, line_subject: str, now: datetime) -> bool:
        changed = await self._store.execute(
            Statement(
                """UPDATE recipients SET active = 1, consented_at = ?
                WHERE line_subject = ? AND active = 0 AND friendship_checked_at IS NOT NULL""",
                (iso_utc(now), line_subject),
            )
        )
        return changed == 1

    async def recipient_is_active(self, line_subject: str) -> bool:
        rows = await self._store.fetch_all(
            Statement(
                "SELECT 1 FROM recipients WHERE line_subject = ? AND active = 1 AND consented_at IS NOT NULL AND friendship_checked_at IS NOT NULL",
                (line_subject,),
            )
        )
        return bool(rows)

    async def recipient_is_pending(self, line_subject: str) -> bool:
        rows = await self._store.fetch_all(
            Statement(
                "SELECT 1 FROM recipients WHERE line_subject = ? AND active = 0",
                (line_subject,),
            )
        )
        return bool(rows)

    async def recipient_display_name(self, line_subject: str) -> str | None:
        rows = await self._store.fetch_all(
            Statement(
                "SELECT display_name FROM recipients WHERE line_subject = ?",
                (line_subject,),
            )
        )
        return str(rows[0]["display_name"]) if rows else None

    async def recipient_id(
        self, line_subject: str, *, active: bool | None = None
    ) -> str | None:
        predicate = "" if active is None else " AND active = ?"
        values = (line_subject,) if active is None else (line_subject, int(active))
        rows = await self._store.fetch_all(
            Statement(
                f"SELECT id FROM recipients WHERE line_subject = ?{predicate}", values
            )
        )
        return str(rows[0]["id"]) if rows else None

    async def recipient_subject(self, recipient_id: str) -> str | None:
        rows = await self._store.fetch_all(
            Statement(
                "SELECT line_subject FROM recipients WHERE id = ? AND active = 1 AND consented_at IS NOT NULL AND friendship_checked_at IS NOT NULL",
                (recipient_id,),
            )
        )
        return str(rows[0]["line_subject"]) if rows else None
