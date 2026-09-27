from __future__ import annotations

import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import pytest

from next_is_you.persistence import Statement, VisitRepository, draft_expiry, iso_utc

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "migrations" / "0001_initial.sql"
UTC = timezone.utc


class SQLiteStore:
    """D1-shaped local test store; production queries still use prepared statements."""

    def __init__(self) -> None:
        self.connection = sqlite3.connect(":memory:", isolation_level=None)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(MIGRATION.read_text())

    async def execute(self, statement: Statement) -> int:
        return self.connection.execute(statement.sql, statement.values).rowcount

    async def fetch_all(self, statement: Statement) -> list[Mapping[str, Any]]:
        cursor = self.connection.execute(statement.sql, statement.values)
        return [dict(row) for row in cursor.fetchall()]

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

    async def close(self) -> None:
        self.connection.close()


def at(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


async def seeded_repository() -> tuple[SQLiteStore, VisitRepository]:
    store = SQLiteStore()
    store.connection.execute(
        """INSERT INTO recipients (id, line_subject, display_name, consented_at, created_at)
        VALUES ('r1', 'line-r1', 'Family A', '2026-09-27T00:00:00Z', '2026-09-27T00:00:00Z')"""
    )
    store.connection.execute(
        """INSERT INTO recipients (id, line_subject, display_name, consented_at, created_at)
        VALUES ('r2', 'line-r2', 'Family B', '2026-09-27T00:00:00Z', '2026-09-27T00:00:00Z')"""
    )
    return store, VisitRepository(store)


async def make_draft(repo: VisitRepository, visit_id: str = "v1") -> None:
    await repo.create_draft(
        visit_id=visit_id,
        hospital="ntuh-main",
        visit_day=date(2026, 9, 27),
        department_code="IM",
        clinic_code="IM-A",
        clinic_session="morning",
        patient_number=85,
        now=at("2026-09-27T00:00:00Z"),
    )


@pytest.mark.asyncio
async def test_draft_expiry_uses_taipei_end_of_day_plus_48_hours() -> None:
    assert iso_utc(draft_expiry(date(2026, 9, 27))) == "2026-09-29T15:59:00Z"


@pytest.mark.asyncio
async def test_first_start_freezes_roster_and_correction_preserves_event_cap() -> None:
    store, repo = await seeded_repository()
    await make_draft(repo)
    assert await repo.add_recipient("v1", "r1", at("2026-09-27T00:01:00Z"))
    assert await repo.start("v1", at("2026-09-27T00:02:00Z"))
    assert not await repo.add_recipient("v1", "r2", at("2026-09-27T00:03:00Z"))

    store.connection.execute(
        """INSERT INTO outbound_events (
            id, visit_id, recipient_id, event_kind, retry_key, payload_json, outcome, created_at
        ) VALUES ('e1', 'v1', 'r1', 'near', 'retry-1', '{}', 'accepted', '2026-09-27T00:04:00Z')"""
    )
    assert await repo.stop("v1", at("2026-09-27T01:00:00Z")) == "stopped"
    assert await repo.prepare_correction("v1")
    assert await repo.correct_clinic(
        visit_id="v1",
        hospital="ntuh-main",
        visit_day=date(2026, 9, 27),
        department_code="IM",
        clinic_code="IM-B",
        clinic_session="afternoon",
        patient_number=86,
        doctor_code="DOC-2",
        room_code="R-2",
    )
    assert await repo.start("v1", at("2026-09-27T02:00:00Z"))
    assert not await repo.add_recipient("v1", "r2", at("2026-09-27T02:01:00Z"))

    visit = dict(store.connection.execute("SELECT * FROM visits WHERE id = 'v1'").fetchone())
    events = store.connection.execute(
        "SELECT COUNT(*) FROM outbound_events WHERE visit_id = 'v1'"
    ).fetchone()[0]
    assert visit["state"] == "active"
    assert visit["roster_frozen"] == 1
    assert visit["clinic_code"] == "IM-B"
    assert visit["patient_number"] == 86
    assert events == 1
    await store.close()


@pytest.mark.asyncio
async def test_start_requires_an_active_selected_recipient() -> None:
    store, repo = await seeded_repository()
    await make_draft(repo)
    assert not await repo.start("v1", at("2026-09-27T00:02:00Z"))
    assert await repo.add_recipient("v1", "r1", at("2026-09-27T00:03:00Z"))
    assert await repo.withdraw_recipient("r1")
    assert not await repo.start("v1", at("2026-09-27T00:04:00Z"))
    await store.close()


@pytest.mark.asyncio
async def test_draft_can_be_resumed_by_reading_or_deleted_before_start() -> None:
    store, repo = await seeded_repository()
    await make_draft(repo)

    draft = await repo.get_visit("v1")
    assert draft is not None
    assert draft["state"] == "draft"
    assert not draft["roster_frozen"]
    assert await repo.delete_draft("v1")
    assert await repo.get_visit("v1") is None
    await store.close()


@pytest.mark.asyncio
async def test_removal_stops_future_membership_but_keeps_recent_event_audit() -> None:
    store, repo = await seeded_repository()
    await make_draft(repo)
    await repo.add_recipient("v1", "r1", at("2026-09-27T00:01:00Z"))
    await repo.start("v1", at("2026-09-27T00:02:00Z"))
    store.connection.execute(
        """INSERT INTO outbound_events (
            id, visit_id, recipient_id, event_kind, retry_key, payload_json, outcome, created_at
        ) VALUES ('e1', 'v1', 'r1', 'near', 'retry-1', '{}', 'accepted', '2026-09-27T00:04:00Z')"""
    )

    assert await repo.remove_recipient("v1", "r1")
    assert not await repo.add_recipient("v1", "r1", at("2026-09-27T00:05:00Z"))
    assert store.connection.execute("SELECT COUNT(*) FROM visit_recipients").fetchone()[0] == 0
    assert store.connection.execute("SELECT COUNT(*) FROM outbound_events").fetchone()[0] == 1
    await store.close()


@pytest.mark.asyncio
async def test_stop_waits_for_inflight_send_before_terminal_retention_clock() -> None:
    store, repo = await seeded_repository()
    await make_draft(repo)
    await repo.add_recipient("v1", "r1", at("2026-09-27T00:01:00Z"))
    await repo.start("v1", at("2026-09-27T00:02:00Z"))
    store.connection.execute(
        """INSERT INTO outbound_events (
            id, visit_id, recipient_id, event_kind, retry_key, payload_json, outcome, created_at
        ) VALUES ('e1', 'v1', 'r1', 'near', 'retry-1', '{}', 'in_flight', '2026-09-27T00:04:00Z')"""
    )

    assert await repo.stop("v1", at("2026-09-27T01:00:00Z")) == "stopping"
    assert await repo.start("v1", at("2026-09-27T01:01:00Z")) is False
    store.connection.execute("UPDATE outbound_events SET outcome = 'accepted' WHERE id = 'e1'")
    assert await repo.finalize_stopping(at("2026-09-27T01:02:00Z")) == 1
    visit = store.connection.execute("SELECT state, delete_after FROM visits WHERE id = 'v1'").fetchone()
    assert visit["state"] == "stopped"
    assert visit["delete_after"] == "2026-09-29T01:02:00Z"
    await store.close()


@pytest.mark.asyncio
async def test_cutoff_is_based_on_taipei_2359_and_retains_terminal_data_48_hours() -> None:
    store, repo = await seeded_repository()
    await make_draft(repo)
    await repo.add_recipient("v1", "r1", at("2026-09-27T00:01:00Z"))
    await repo.start("v1", at("2026-09-27T00:02:00Z"))

    assert await repo.expire_due_visits(at("2026-09-27T15:58:00Z")) == 0
    assert await repo.expire_due_visits(at("2026-09-27T16:00:00Z")) == 1
    visit = store.connection.execute(
        "SELECT state, stopped_at, delete_after FROM visits WHERE id = 'v1'"
    ).fetchone()
    assert visit["state"] == "expired"
    assert visit["stopped_at"] == "2026-09-27T15:59:00Z"
    assert visit["delete_after"] == "2026-09-29T15:59:00Z"

    assert await repo.delete_expired(at("2026-09-29T15:58:59Z")) == 0
    assert await repo.delete_expired(at("2026-09-29T15:59:00Z")) == 1
    assert not await repo.start("v1", at("2026-09-30T00:00:00Z"))
    await store.close()


@pytest.mark.asyncio
async def test_cleanup_does_not_delete_a_terminal_visit_with_an_inflight_event() -> None:
    store, repo = await seeded_repository()
    await make_draft(repo)
    await repo.add_recipient("v1", "r1", at("2026-09-27T00:01:00Z"))
    await repo.start("v1", at("2026-09-27T00:02:00Z"))
    store.connection.execute(
        """INSERT INTO outbound_events (
            id, visit_id, recipient_id, event_kind, retry_key, payload_json, outcome, created_at
        ) VALUES ('e1', 'v1', 'r1', 'near', 'retry-1', '{}', 'in_flight', '2026-09-27T00:04:00Z')"""
    )
    store.connection.execute(
        "UPDATE visits SET state = 'expired', delete_after = '2026-09-28T00:00:00Z' WHERE id = 'v1'"
    )

    assert await repo.delete_expired(at("2026-09-29T00:00:00Z")) == 0
    store.connection.execute("UPDATE outbound_events SET outcome = 'unknown' WHERE id = 'e1'")
    assert await repo.delete_expired(at("2026-09-29T00:00:00Z")) == 1
    assert store.connection.execute("SELECT COUNT(*) FROM outbound_events").fetchone()[0] == 0
    await store.close()


@pytest.mark.asyncio
async def test_withdrawal_disables_recipient_then_erases_after_inflight_send_settles() -> None:
    store, repo = await seeded_repository()
    await make_draft(repo)
    await repo.add_recipient("v1", "r1", at("2026-09-27T00:01:00Z"))
    await repo.start("v1", at("2026-09-27T00:02:00Z"))
    store.connection.execute(
        """INSERT INTO outbound_events (
            id, visit_id, recipient_id, event_kind, retry_key, payload_json, outcome, created_at
        ) VALUES ('e1', 'v1', 'r1', 'near', 'retry-1', '{}', 'in_flight', '2026-09-27T00:04:00Z')"""
    )

    assert await repo.withdraw_recipient("r1")
    assert store.connection.execute("SELECT active FROM recipients WHERE id = 'r1'").fetchone()[0] == 0
    assert store.connection.execute(
        "SELECT COUNT(*) FROM outbound_events WHERE recipient_id = 'r1'"
    ).fetchone()[0] == 1
    store.connection.execute("UPDATE outbound_events SET outcome = 'accepted' WHERE id = 'e1'")
    assert await repo.erase_settled_withdrawals() == 1
    assert store.connection.execute("SELECT COUNT(*) FROM recipients WHERE id = 'r1'").fetchone()[0] == 0
    assert store.connection.execute(
        "SELECT COUNT(*) FROM visit_recipients WHERE recipient_id = 'r1'"
    ).fetchone()[0] == 0
    assert store.connection.execute(
        "SELECT COUNT(*) FROM outbound_events WHERE recipient_id = 'r1'"
    ).fetchone()[0] == 0
    await store.close()
