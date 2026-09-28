"""D1 persistence operations for the logical visit lifecycle."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Mapping, Protocol, Sequence
from zoneinfo import ZoneInfo

TAIPEI = ZoneInfo("Asia/Taipei")
UTC = timezone.utc


@dataclass(frozen=True, slots=True)
class Statement:
    sql: str
    values: tuple[Any, ...] = ()


class SqlStore(Protocol):
    async def execute(self, statement: Statement) -> int: ...

    async def fetch_all(self, statement: Statement) -> list[Mapping[str, Any]]: ...

    async def batch(self, statements: Sequence[Statement]) -> list[int]: ...


class CloudflareD1Store:
    """Small adapter around the Python Worker's D1 binding."""

    def __init__(self, binding: Any) -> None:
        self._binding = binding

    def _prepare(self, statement: Statement) -> Any:
        prepared = self._binding.prepare(statement.sql)
        return prepared.bind(*statement.values) if statement.values else prepared

    async def execute(self, statement: Statement) -> int:
        result = await self._prepare(statement).run()
        return int(_property(_property(result, "meta"), "changes", 0))

    async def fetch_all(self, statement: Statement) -> list[Mapping[str, Any]]:
        result = await self._prepare(statement).all()
        rows = _property(result, "results", [])
        if hasattr(rows, "to_py"):
            rows = rows.to_py()
        return list(rows)

    async def batch(self, statements: Sequence[Statement]) -> list[int]:
        results = await self._binding.batch([self._prepare(item) for item in statements])
        if hasattr(results, "to_py"):
            results = results.to_py()
        return [int(_property(_property(item, "meta"), "changes", 0)) for item in results]


def _property(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(key, default)
    return getattr(value, key, default)


def iso_utc(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware")
    return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def visit_cutoff(visit_day: date) -> datetime:
    """The product cutoff is 23:59 Asia/Taipei on the visit day."""
    return datetime.combine(visit_day, time(23, 59), TAIPEI)


def draft_expiry(visit_day: date) -> datetime:
    return visit_cutoff(visit_day) + timedelta(hours=48)


def terminal_expiry(stopped_at: datetime) -> datetime:
    if stopped_at.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware")
    return stopped_at + timedelta(hours=48)


class VisitRepository:
    """Owns durable transitions, not the external send-serialization gate."""

    def __init__(self, store: SqlStore) -> None:
        self._store = store

    async def get_visit(self, visit_id: str) -> Mapping[str, Any] | None:
        rows = await self._store.fetch_all(
            Statement("SELECT * FROM visits WHERE id = ?", (visit_id,))
        )
        return rows[0] if rows else None

    async def delete_draft(self, visit_id: str) -> bool:
        return (
            await self._store.execute(
                Statement("DELETE FROM visits WHERE id = ? AND state = 'draft'", (visit_id,))
            )
            == 1
        )

    async def create_draft(
        self,
        *,
        visit_id: str,
        hospital: str,
        visit_day: date,
        department_code: str,
        clinic_code: str,
        clinic_session: str,
        patient_number: int,
        now: datetime,
        doctor_code: str | None = None,
        room_code: str | None = None,
    ) -> None:
        await self._store.execute(
            Statement(
                """INSERT INTO visits (
                    id, hospital, visit_date, department_code, clinic_code,
                    clinic_session, doctor_code, room_code, patient_number,
                    state, roster_frozen, created_at, draft_expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'draft', 0, ?, ?)""",
                (
                    visit_id,
                    hospital,
                    visit_day.isoformat(),
                    department_code,
                    clinic_code,
                    clinic_session,
                    doctor_code,
                    room_code,
                    patient_number,
                    iso_utc(now),
                    iso_utc(draft_expiry(visit_day)),
                ),
            )
        )

    async def add_recipient(
        self,
        visit_id: str,
        recipient_id: str,
        now: datetime,
        *,
        friendship_checked_at: datetime | None = None,
    ) -> bool:
        friendship_clause = (
            "r.friendship_checked_at = ?"
            if friendship_checked_at is not None
            else "r.friendship_checked_at IS NOT NULL"
        )
        values: tuple[Any, ...] = (
            (visit_id, iso_utc(now), visit_id, recipient_id, iso_utc(friendship_checked_at))
            if friendship_checked_at is not None
            else (visit_id, iso_utc(now), visit_id, recipient_id)
        )
        changes = await self._store.execute(
            Statement(
                f"""INSERT INTO visit_recipients (visit_id, recipient_id, selected_at)
                SELECT ?, r.id, ? FROM recipients AS r
                JOIN visits AS v ON v.id = ?
                WHERE r.id = ? AND r.active = 1 AND r.consented_at IS NOT NULL
                    AND {friendship_clause}
                    AND v.state = 'draft' AND v.roster_frozen = 0""",
                values,
            )
        )
        return changes == 1

    async def remove_recipient(self, visit_id: str, recipient_id: str) -> bool:
        changes = await self._store.execute(
            Statement(
                """DELETE FROM visit_recipients
                WHERE visit_id = ? AND recipient_id = ?
                AND EXISTS (
                    SELECT 1 FROM visits
                    WHERE id = ? AND state IN ('draft', 'active', 'stopping', 'stopped', 'expired')
                )""",
                (visit_id, recipient_id, visit_id),
            )
        )
        return changes == 1

    async def start(self, visit_id: str, now: datetime) -> bool:
        """Start or resume a corrected series while atomically freezing its roster."""
        changes = await self._store.execute(
            Statement(
                """UPDATE visits
                SET state = 'active', roster_frozen = 1,
                    started_at = COALESCE(started_at, ?), stopped_at = NULL,
                    delete_after = NULL, draft_expires_at = NULL
                WHERE id = ? AND state = 'draft'
                AND EXISTS (
                    SELECT 1 FROM visit_recipients AS vr
                    JOIN recipients AS r ON r.id = vr.recipient_id
                    WHERE vr.visit_id = visits.id AND r.active = 1
                        AND r.consented_at IS NOT NULL
                        AND r.friendship_checked_at IS NOT NULL
                )""",
                (iso_utc(now), visit_id),
            )
        )
        return changes == 1

    async def prepare_correction(self, visit_id: str) -> bool:
        """Reopen a stopped series for correction without resetting its identity or event caps."""
        changes = await self._store.execute(
            Statement(
                """UPDATE visits SET state = 'draft', stopped_at = NULL, delete_after = NULL
                WHERE id = ? AND state = 'stopped' AND roster_frozen = 1""",
                (visit_id,),
            )
        )
        return changes == 1

    async def correct_clinic(
        self,
        *,
        visit_id: str,
        hospital: str,
        visit_day: date,
        department_code: str,
        clinic_code: str,
        clinic_session: str,
        patient_number: int,
        doctor_code: str | None,
        room_code: str | None,
    ) -> bool:
        changes = await self._store.execute(
            Statement(
                """UPDATE visits SET hospital = ?, visit_date = ?, department_code = ?,
                    clinic_code = ?, clinic_session = ?, patient_number = ?,
                    doctor_code = ?, room_code = ?, draft_expires_at = ?
                WHERE id = ? AND state = 'draft'""",
                (
                    hospital,
                    visit_day.isoformat(),
                    department_code,
                    clinic_code,
                    clinic_session,
                    patient_number,
                    doctor_code,
                    room_code,
                    iso_utc(draft_expiry(visit_day)),
                    visit_id,
                ),
            )
        )
        return changes == 1

    async def stop(self, visit_id: str, now: datetime) -> str | None:
        """Close the visit to new work, then finalize after in-flight sends settle.

        This database transition is not a replacement for the per-visit Durable
        Object serialization gate required to order Stop against LINE requests.
        """
        iso_utc(now)  # Validate before changing the visit state.
        await self._store.execute(
            Statement(
                "UPDATE visits SET state = 'stopping' WHERE id = ? AND state = 'active'",
                (visit_id,),
            )
        )
        await self._finalize_stopping(visit_id, now)
        rows = await self._store.fetch_all(
            Statement("SELECT state FROM visits WHERE id = ?", (visit_id,))
        )
        return str(rows[0]["state"]) if rows else None

    async def finalize_stopping(self, now: datetime) -> int:
        rows = await self._store.fetch_all(
            Statement("SELECT id FROM visits WHERE state = 'stopping'")
        )
        finalized = 0
        for row in rows:
            finalized += await self._finalize_stopping(str(row["id"]), now)
        return finalized

    async def _finalize_stopping(self, visit_id: str, now: datetime) -> int:
        return await self._store.execute(
            Statement(
                """UPDATE visits SET state = 'stopped', stopped_at = ?, delete_after = ?
                WHERE id = ? AND state = 'stopping'
                AND NOT EXISTS (
                    SELECT 1 FROM outbound_events
                    WHERE visit_id = visits.id AND outcome = 'in_flight'
                )""",
                (iso_utc(now), iso_utc(terminal_expiry(now)), visit_id),
            )
        )

    async def expire_due_visits(self, now: datetime) -> int:
        if now.tzinfo is None:
            raise ValueError("timestamps must be timezone-aware")
        local_now = now.astimezone(TAIPEI)
        today = local_now.date()
        today_is_due = local_now >= visit_cutoff(today)
        date_clause = "visit_date <= ?" if today_is_due else "visit_date < ?"
        rows = await self._store.fetch_all(
            Statement(
                f"SELECT id, visit_date FROM visits WHERE state = 'active' AND {date_clause}",
                (today.isoformat(),),
            )
        )
        expired = 0
        statements: list[Statement] = []
        for row in rows:
            visit_day = date.fromisoformat(str(row["visit_date"]))
            cutoff = visit_cutoff(visit_day)
            statements.append(
                Statement(
                    """UPDATE visits SET state = 'expired', stopped_at = ?, delete_after = ?
                    WHERE id = ? AND state = 'active'""",
                    (iso_utc(cutoff), iso_utc(terminal_expiry(cutoff)), str(row["id"])),
                )
            )
        if statements:
            expired = sum(await self._store.batch(statements))
        return expired

    async def withdraw_recipient(self, recipient_id: str) -> bool:
        changes = await self._store.execute(
            Statement("UPDATE recipients SET active = 0 WHERE id = ? AND active = 1", (recipient_id,))
        )
        await self.erase_settled_withdrawals()
        return changes == 1

    async def erase_settled_withdrawals(self) -> int:
        return await self._store.execute(
            Statement(
                """DELETE FROM recipients
                WHERE active = 0 AND NOT EXISTS (
                    SELECT 1 FROM outbound_events
                    WHERE recipient_id = recipients.id AND outcome = 'in_flight'
                )"""
            )
        )

    async def delete_expired(self, now: datetime) -> int:
        timestamp = iso_utc(now)
        return await self._store.execute(
            Statement(
                """DELETE FROM visits
                WHERE (state = 'draft' AND draft_expires_at <= ?)
                   OR (state IN ('stopped', 'expired') AND delete_after <= ?
                       AND NOT EXISTS (
                           SELECT 1 FROM outbound_events
                           WHERE visit_id = visits.id AND outcome = 'in_flight'
                       ))""",
                (timestamp, timestamp),
            )
        )
