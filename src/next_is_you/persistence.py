"""D1 persistence operations for the logical visit lifecycle."""

from __future__ import annotations

import hashlib
import json
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
    operation: str | None = None


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
        results = await self._binding.batch(
            [self._prepare(item) for item in statements]
        )
        if hasattr(results, "to_py"):
            results = results.to_py()
        return [
            int(_property(_property(item, "meta"), "changes", 0)) for item in results
        ]


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

    async def eligible_recipients(self) -> list[Mapping[str, Any]]:
        return await self._store.fetch_all(
            Statement(
                """SELECT id, display_name FROM recipients WHERE active = 1
                AND consented_at IS NOT NULL AND friendship_checked_at IS NOT NULL
                ORDER BY display_name, id"""
            )
        )

    async def selected_recipient_ids(self, visit_id: str) -> set[str]:
        rows = await self._store.fetch_all(
            Statement(
                "SELECT recipient_id FROM visit_recipients WHERE visit_id = ?",
                (visit_id,),
            )
        )
        return {str(row["recipient_id"]) for row in rows}

    async def event_is_in_flight_for_visit(self, event_id: str, visit_id: str) -> bool:
        rows = await self._store.fetch_all(
            Statement(
                """SELECT 1 FROM outbound_events
                WHERE id = ? AND visit_id = ? AND outcome = 'in_flight'""",
                (event_id, visit_id),
            )
        )
        return bool(rows)

    async def organizer_visits(self) -> list[Mapping[str, Any]]:
        return await self._store.fetch_all(
            Statement(
                """SELECT v.id, v.hospital, v.visit_date, v.department_code, v.clinic_code,
                v.clinic_session, v.patient_number, v.state, v.near_last_current_number, v.latest_observed_at,
                v.latest_source_read_status, v.latest_source_read_reason,
                vr.recipient_id, r.display_name,
                SUM(CASE WHEN e.outcome != 'superseded' THEN 1 ELSE 0 END) AS notification_count,
                SUM(CASE WHEN e.outcome = 'accepted' THEN 1 ELSE 0 END) AS accepted_count,
                SUM(CASE WHEN e.outcome IN ('failed', 'unknown') THEN 1 ELSE 0 END) AS issue_count
                FROM visits AS v
                LEFT JOIN visit_recipients AS vr ON vr.visit_id = v.id
                LEFT JOIN recipients AS r ON r.id = vr.recipient_id
                LEFT JOIN outbound_events AS e ON e.visit_id = v.id AND e.recipient_id = vr.recipient_id
                GROUP BY v.id, vr.recipient_id ORDER BY v.created_at DESC, v.id"""
            )
        )

    async def set_source_read(self, visit_id: str, status: str, reason: str) -> bool:
        statuses = {
            "usable",
            "unavailable",
            "stale",
            "untrusted",
            "scope_mismatch",
            "invalid",
        }
        reasons = {
            "none",
            "no_observation",
            "timeout",
            "stale_sample",
            "untrusted_source",
            "scope_mismatch",
            "empty_result",
            "schema_drift",
            "access_denied",
            "ambiguous_match",
            "invalid_data",
        }
        if status not in statuses or reason not in reasons:
            raise ValueError("invalid source-read metadata")
        return (
            await self._store.execute(
                Statement(
                    "UPDATE visits SET latest_source_read_status = ?, latest_source_read_reason = ? WHERE id = ?",
                    (status, reason, visit_id),
                )
            )
            == 1
        )

    async def create_organizer_draft(
        self,
        *,
        visit_id: str,
        hospital: str,
        visit_day: date,
        department_code: str,
        clinic_code: str,
        clinic_session: str,
        patient_number: int,
        recipient_ids: Sequence[str],
        now: datetime,
    ) -> bool:
        await self.create_draft(
            visit_id=visit_id,
            hospital=hospital,
            visit_day=visit_day,
            department_code=department_code,
            clinic_code=clinic_code,
            clinic_session=clinic_session,
            patient_number=patient_number,
            now=now,
        )
        for recipient_id in dict.fromkeys(recipient_ids):
            if not await self.add_recipient(visit_id, recipient_id, now):
                await self.delete_draft(visit_id)
                return False
        if not recipient_ids:
            await self.delete_draft(visit_id)
            return False
        return True

    async def update_draft(
        self,
        *,
        visit_id: str,
        hospital: str,
        visit_day: date,
        department_code: str,
        clinic_code: str,
        clinic_session: str,
        patient_number: int,
        recipient_ids: Sequence[str],
        now: datetime,
    ) -> bool:
        visit = await self.get_visit(visit_id)
        if visit is None or visit["state"] != "draft" or visit["roster_frozen"]:
            return False
        if not recipient_ids:
            return False
        wanted = list(dict.fromkeys(recipient_ids))
        placeholders = ",".join("?" for _ in wanted)
        eligible = await self._store.fetch_all(
            Statement(
                f"""SELECT id FROM recipients WHERE id IN ({placeholders}) AND active = 1
                AND consented_at IS NOT NULL AND friendship_checked_at IS NOT NULL""",
                tuple(wanted),
                "validate_draft_recipients",
            )
        )
        if {str(row["id"]) for row in eligible} != set(wanted):
            return False
        if not await self.correct_clinic(
            visit_id=visit_id,
            hospital=hospital,
            visit_day=visit_day,
            department_code=department_code,
            clinic_code=clinic_code,
            clinic_session=clinic_session,
            patient_number=patient_number,
            doctor_code=None,
            room_code=None,
        ):
            return False
        current_ids = await self.selected_recipient_ids(visit_id)
        for rid in current_ids - set(wanted):
            await self.remove_recipient(visit_id, rid)
        for rid in wanted:
            if rid not in current_ids and not await self.add_recipient(
                visit_id, rid, now
            ):
                return False
        return True

    async def scheduler_ledger_digest(
        self,
        *,
        exclude_event_id: str | None = None,
        allow_stopping_visit_id: str | None = None,
    ) -> str:
        """Fingerprint D1 state that can affect future sends or sent-event dedupe."""
        visit_rows = await self._store.fetch_all(
            Statement(
                """SELECT id, hospital, visit_date, department_code, clinic_code,
                    clinic_session, doctor_code, room_code, patient_number, state,
                    roster_frozen, consecutive_unusable_reads, near_last_current_number,
                    near_prev_observed_number, latest_observed_at, started_at,
                    stopped_at, delete_after
                FROM visits WHERE state != 'draft' ORDER BY id"""
            )
        )
        recipient_rows = await self._store.fetch_all(
            Statement(
                """SELECT vr.visit_id, r.id, r.line_subject, r.consented_at,
                    r.friendship_checked_at, r.active
                FROM visit_recipients AS vr
                JOIN visits AS v ON v.id = vr.visit_id
                JOIN recipients AS r ON r.id = vr.recipient_id
                WHERE v.state != 'draft'
                ORDER BY vr.visit_id, r.id"""
            )
        )
        event_sql = """SELECT id, visit_id, recipient_id, event_kind, retry_key,
                    payload_json, outcome, created_at, request_started_at, settled_at,
                    error_code, first_request_at, attempt_count
                FROM outbound_events"""
        event_statement = (
            Statement(f"{event_sql} WHERE id != ? ORDER BY id", (exclude_event_id,))
            if exclude_event_id is not None
            else Statement(f"{event_sql} ORDER BY id")
        )
        event_rows = await self._store.fetch_all(event_statement)
        visit_payload = []
        for row in visit_rows:
            item = dict(row)
            if item["id"] == allow_stopping_visit_id and item["state"] == "stopping":
                item["state"] = "active"
            visit_payload.append(item)
        payload = [
            visit_payload,
            [dict(row) for row in recipient_rows],
            [dict(row) for row in event_rows],
        ]
        encoded = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), default=str
        )
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    async def active_schedule_rows(self) -> list[Mapping[str, Any]]:
        """Return active visit and eligible recipient pairs for one serialized tick."""
        return await self._store.fetch_all(
            Statement(
                """SELECT v.*, r.id AS recipient_id, r.line_subject
                FROM visits AS v
                JOIN visit_recipients AS vr ON vr.visit_id = v.id
                JOIN recipients AS r ON r.id = vr.recipient_id
                WHERE v.state = 'active' AND r.active = 1
                    AND r.consented_at IS NOT NULL
                    AND r.friendship_checked_at IS NOT NULL
                ORDER BY v.id, r.id"""
            )
        )

    async def event_kinds(self, visit_id: str) -> set[tuple[str, str]]:
        rows = await self._store.fetch_all(
            Statement(
                "SELECT recipient_id, event_kind FROM outbound_events WHERE visit_id = ?",
                (visit_id,),
            )
        )
        return {(str(row["recipient_id"]), str(row["event_kind"])) for row in rows}

    async def near_counts(self, visit_id: str) -> dict[str, int]:
        """Near reminders created per recipient, counting every outcome.

        Superseded reminders still count, so the 20-per-visit-and-recipient cap
        bounds every created reminder regardless of whether it was delivered.
        """
        rows = await self._store.fetch_all(
            Statement(
                """SELECT recipient_id, COUNT(*) AS near_count
                FROM outbound_events
                WHERE visit_id = ? AND event_kind = 'near'
                GROUP BY recipient_id""",
                (visit_id,),
            )
        )
        return {str(row["recipient_id"]): int(row["near_count"]) for row in rows}

    async def retryable_events(self, visit_id: str) -> list[Mapping[str, Any]]:
        return await self._store.fetch_all(
            Statement(
                """SELECT e.*, r.line_subject
                FROM outbound_events AS e
                JOIN recipients AS r ON r.id = e.recipient_id
                JOIN visit_recipients AS vr
                    ON vr.visit_id = e.visit_id AND vr.recipient_id = e.recipient_id
                WHERE e.visit_id = ? AND e.outcome IN ('pending', 'unknown')
                    AND r.active = 1 AND r.consented_at IS NOT NULL
                    AND r.friendship_checked_at IS NOT NULL
                ORDER BY e.created_at, e.id""",
                (visit_id,),
            )
        )

    async def retryable_event(self, event_id: str) -> Mapping[str, Any] | None:
        rows = await self._store.fetch_all(
            Statement(
                """SELECT e.*, r.line_subject, v.visit_date, v.state AS visit_state
                FROM outbound_events AS e
                JOIN recipients AS r ON r.id = e.recipient_id
                JOIN visit_recipients AS vr
                    ON vr.visit_id = e.visit_id AND vr.recipient_id = e.recipient_id
                JOIN visits AS v ON v.id = e.visit_id
                WHERE e.id = ? AND e.outcome IN ('pending', 'unknown')
                    AND v.state = 'active' AND r.active = 1
                    AND r.consented_at IS NOT NULL
                    AND r.friendship_checked_at IS NOT NULL""",
                (event_id,),
            )
        )
        return rows[0] if rows else None

    async def create_event_if_absent(
        self,
        *,
        event_id: str,
        visit_id: str,
        recipient_id: str,
        event_kind: str,
        retry_key: str,
        payload_json: str,
        now: datetime,
    ) -> Mapping[str, Any]:
        await self._store.execute(
            Statement(
                """INSERT OR IGNORE INTO outbound_events (
                    id, visit_id, recipient_id, event_kind, retry_key,
                    payload_json, outcome, created_at
                ) SELECT ?, ?, ?, ?, ?, ?, 'pending', ?
                WHERE EXISTS (
                    SELECT 1 FROM visits AS v
                    JOIN visit_recipients AS vr ON vr.visit_id = v.id
                    JOIN recipients AS r ON r.id = vr.recipient_id
                    WHERE v.id = ? AND v.state = 'active'
                        AND r.id = ? AND r.active = 1
                        AND r.consented_at IS NOT NULL
                        AND r.friendship_checked_at IS NOT NULL
                )""",
                (
                    event_id,
                    visit_id,
                    recipient_id,
                    event_kind,
                    retry_key,
                    payload_json,
                    iso_utc(now),
                    visit_id,
                    recipient_id,
                ),
            )
        )
        rows = await self._store.fetch_all(
            Statement(
                """SELECT * FROM outbound_events
                WHERE visit_id = ? AND recipient_id = ? AND event_kind = ?""",
                (visit_id, recipient_id, event_kind),
            )
        )
        if not rows:
            raise RuntimeError("outbox event was not persisted for an active recipient")
        return rows[0]

    async def update_observation(
        self,
        visit_id: str,
        *,
        current_number: int | None,
        observed_at: datetime,
        consecutive_unusable_reads: int,
    ) -> bool:
        return (
            await self._store.execute(
                Statement(
                    """UPDATE visits SET near_last_current_number = ?,
                        latest_observed_at = ?, consecutive_unusable_reads = ?
                    WHERE id = ? AND state = 'active'""",
                    (
                        current_number,
                        iso_utc(observed_at),
                        consecutive_unusable_reads,
                        visit_id,
                    ),
                )
            )
            == 1
        )

    async def commit_near_reminders(
        self,
        visit_id: str,
        *,
        observed_number: int,
        observed_at: datetime,
        now: datetime,
        new_events: Sequence[Mapping[str, str]],
    ) -> int:
        """Record a usable scheduled read and its near reminders atomically.

        The previously observed number advances together with the near reminders
        it triggers, in one transaction, so a crash can neither leave the number
        advanced without its reminder (which would lose a reminder) nor leave a
        reminder without the number advanced (which would duplicate it on the next
        tick reading the same number). For each affected recipient an earlier
        unsent near reminder (still pending or unknown) is superseded first, so at
        most the latest reminder stays deliverable; accepted or in-flight
        reminders are left untouched. ``new_events`` entries carry ``event_id``,
        ``recipient_id``, ``retry_key`` and ``payload_json``. Returns the number
        of near reminders inserted.
        """
        statements: list[Statement] = []
        settled = iso_utc(now)
        created_at = iso_utc(now)
        for spec in new_events:
            statements.append(
                Statement(
                    """UPDATE outbound_events SET outcome = 'superseded',
                        settled_at = ?, error_code = 'superseded_by_newer_near'
                    WHERE visit_id = ? AND recipient_id = ? AND event_kind = 'near'
                        AND outcome IN ('pending', 'unknown')""",
                    (settled, visit_id, spec["recipient_id"]),
                )
            )
            statements.append(
                Statement(
                    """INSERT INTO outbound_events (
                        id, visit_id, recipient_id, event_kind, retry_key,
                        payload_json, outcome, created_at
                    ) SELECT ?, ?, ?, 'near', ?, ?, 'pending', ?
                    WHERE EXISTS (
                        SELECT 1 FROM visits AS v
                        JOIN visit_recipients AS vr ON vr.visit_id = v.id
                        JOIN recipients AS r ON r.id = vr.recipient_id
                        WHERE v.id = ? AND v.state = 'active'
                            AND r.id = ? AND r.active = 1
                            AND r.consented_at IS NOT NULL
                            AND r.friendship_checked_at IS NOT NULL
                    )""",
                    (
                        spec["event_id"],
                        visit_id,
                        spec["recipient_id"],
                        spec["retry_key"],
                        spec["payload_json"],
                        created_at,
                        visit_id,
                        spec["recipient_id"],
                    ),
                )
            )
        statements.append(
            Statement(
                """UPDATE visits SET near_prev_observed_number = ?,
                    near_last_current_number = ?, latest_observed_at = ?,
                    consecutive_unusable_reads = 0
                WHERE id = ? AND state = 'active'""",
                (observed_number, observed_number, iso_utc(observed_at), visit_id),
            )
        )
        await self._store.batch(statements)
        if not new_events:
            return 0
        # Count the reminders that actually persisted from their own ids, rather
        # than from batch change counts, whose result shape varies across the D1
        # binding and local test doubles.
        event_ids = [spec["event_id"] for spec in new_events]
        placeholders = ",".join("?" for _ in event_ids)
        persisted = await self._store.fetch_all(
            Statement(
                f"SELECT id FROM outbound_events WHERE id IN ({placeholders})",
                tuple(event_ids),
            )
        )
        return len(persisted)

    async def recover_in_flight_events(self, now: datetime) -> int:
        """After an invocation restart, fence old senders as unknown before reopening."""
        return await self._store.execute(
            Statement(
                """UPDATE outbound_events SET outcome = 'unknown', settled_at = ?,
                    error_code = 'invocation_restarted'
                WHERE outcome = 'in_flight'""",
                (iso_utc(now),),
            )
        )

    async def begin_event_attempt(self, event_id: str, now: datetime) -> int | None:
        changes = await self._store.execute(
            Statement(
                """UPDATE outbound_events SET outcome = 'in_flight',
                    request_started_at = ?, first_request_at = COALESCE(first_request_at, ?),
                    attempt_count = attempt_count + 1, settled_at = NULL, error_code = NULL
                WHERE id = ? AND outcome IN ('pending', 'unknown')
                    AND EXISTS (
                        SELECT 1 FROM visits AS v
                        JOIN visit_recipients AS vr ON vr.visit_id = v.id
                        JOIN recipients AS r ON r.id = vr.recipient_id
                        WHERE v.id = outbound_events.visit_id AND v.state = 'active'
                            AND vr.recipient_id = outbound_events.recipient_id
                            AND r.active = 1 AND r.consented_at IS NOT NULL
                    )""",
                (iso_utc(now), iso_utc(now), event_id),
            )
        )
        if changes != 1:
            return None
        rows = await self._store.fetch_all(
            Statement(
                "SELECT attempt_count FROM outbound_events WHERE id = ?", (event_id,)
            )
        )
        return int(rows[0]["attempt_count"]) if rows else None

    async def settle_event_attempt(
        self,
        event_id: str,
        attempt_count: int,
        outcome: str,
        now: datetime,
        error_code: str | None = None,
    ) -> bool:
        if outcome not in {"accepted", "failed", "unknown"}:
            raise ValueError("invalid settled outcome")
        return (
            await self._store.execute(
                Statement(
                    """UPDATE outbound_events SET outcome = ?, settled_at = ?, error_code = ?
                    WHERE id = ? AND attempt_count = ? AND outcome = 'in_flight'""",
                    (outcome, iso_utc(now), error_code, event_id, attempt_count),
                )
            )
            == 1
        )

    async def abort_event_attempt(
        self,
        event_id: str,
        attempt_count: int,
        *,
        previous_outcome: str,
        previous_request_started_at: str | None,
        previous_first_request_at: str | None,
        previous_settled_at: str | None,
        previous_error_code: str | None,
    ) -> bool:
        """Roll back a prepared send when its final pre-request checks fail."""
        if previous_outcome not in {"pending", "unknown"}:
            raise ValueError("invalid previous outbox outcome")
        return (
            await self._store.execute(
                Statement(
                    """UPDATE outbound_events SET outcome = ?, request_started_at = ?,
                        first_request_at = ?, settled_at = ?, error_code = ?,
                        attempt_count = attempt_count - 1
                    WHERE id = ? AND attempt_count = ? AND outcome = 'in_flight'""",
                    (
                        previous_outcome,
                        previous_request_started_at,
                        previous_first_request_at,
                        previous_settled_at,
                        previous_error_code,
                        event_id,
                        attempt_count,
                    ),
                )
            )
            == 1
        )

    async def erase_removed_recipient_events(
        self, visit_id: str, recipient_id: str
    ) -> bool:
        rows = await self._store.fetch_all(
            Statement(
                "SELECT 1 FROM outbound_events WHERE visit_id = ? AND recipient_id = ? AND outcome = 'in_flight'",
                (visit_id, recipient_id),
            )
        )
        if rows:
            return False
        await self._store.execute(
            Statement(
                "DELETE FROM outbound_events WHERE visit_id = ? AND recipient_id = ?",
                (visit_id, recipient_id),
            )
        )
        return True

    async def delete_draft(self, visit_id: str) -> bool:
        return (
            await self._store.execute(
                Statement(
                    "DELETE FROM visits WHERE id = ? AND state = 'draft'", (visit_id,)
                )
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
            (
                visit_id,
                iso_utc(now),
                visit_id,
                recipient_id,
                iso_utc(friendship_checked_at),
            )
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
                )
                AND EXISTS (
                    SELECT 1 FROM visit_recipients AS remaining
                    WHERE remaining.visit_id = visit_recipients.visit_id
                        AND remaining.recipient_id != visit_recipients.recipient_id
                )""",
                (visit_id, recipient_id, visit_id),
            )
        )
        return changes == 1

    async def update_clinic_code(self, visit_id: str, clinic_code: str) -> bool:
        """Rewrite a draft's clinic_code when pre-flight resolves to a new value.

        Used by the Start-time resolve step when a schedule-sourced draft's
        visit_date reaches today: the stored clinic_type (schedule's 診別)
        must become the today-side clinic_type so the visit-day reader's
        (room, doctor, clinic_type) matcher continues to work.
        """
        changes = await self._store.execute(
            Statement(
                "UPDATE visits SET clinic_code = ? WHERE id = ? AND state = 'draft'",
                (clinic_code, visit_id),
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
                )
                AND NOT EXISTS (
                    SELECT 1 FROM visit_recipients AS vr
                    JOIN recipients AS r ON r.id = vr.recipient_id
                    WHERE vr.visit_id = visits.id AND (r.active != 1
                        OR r.consented_at IS NULL OR r.friendship_checked_at IS NULL)
                )""",
                (iso_utc(now), visit_id),
            )
        )
        return changes == 1

    async def prepare_correction(self, visit_id: str) -> bool:
        """Reopen a stopped or expired series without resetting its identity or event caps."""
        changes = await self._store.execute(
            Statement(
                """UPDATE visits SET state = 'draft', stopped_at = NULL, delete_after = NULL
                WHERE id = ? AND state IN ('stopped', 'expired') AND roster_frozen = 1""",
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

    async def stop_while_event_is_in_flight(self, visit_id: str) -> bool:
        """Close a visit to new sends while one of its provider requests is pending."""
        return (
            await self._store.execute(
                Statement(
                    """UPDATE visits SET state = 'stopping'
                    WHERE id = ? AND state IN ('active', 'stopping')
                    AND EXISTS (
                        SELECT 1 FROM outbound_events AS e
                        WHERE e.visit_id = visits.id AND e.outcome = 'in_flight'
                    )""",
                    (visit_id,),
                )
            )
            == 1
        )

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

    async def drafts_due_for_preflight_sweep(
        self, today: date, hospitals: Sequence[str]
    ) -> list[Mapping[str, Any]]:
        """Drafts dated after today, of the given hospitals, not swept today.

        The caller names the hospitals that publish a clinic schedule; how far
        ahead any of them has published is the hospital reader's business.
        """
        if not hospitals:
            return []
        placeholders = ", ".join("?" for _ in hospitals)
        return await self._store.fetch_all(
            Statement(
                f"""SELECT id, hospital, visit_date, department_code, clinic_code,
                    clinic_session, doctor_code, room_code
                FROM visits
                WHERE state = 'draft'
                    AND visit_date > ?
                    AND hospital IN ({placeholders})
                    AND (preflight_last_checked_date IS NULL
                         OR preflight_last_checked_date != ?)
                ORDER BY hospital, department_code, visit_date, id""",
                (today.isoformat(), *hospitals, today.isoformat()),
            )
        )

    async def mark_preflight_checked(self, visit_id: str, today: date) -> bool:
        """Record that the sweep ran against this draft for today Taipei."""
        return (
            await self._store.execute(
                Statement(
                    """UPDATE visits SET preflight_last_checked_date = ?
                    WHERE id = ? AND state = 'draft'""",
                    (today.isoformat(), visit_id),
                )
            )
            == 1
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
            Statement(
                "UPDATE recipients SET active = 0 WHERE id = ? AND active = 1",
                (recipient_id,),
            )
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
