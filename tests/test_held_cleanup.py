"""Issue #117: expired data is cleaned up while sends are held (fixture/mock)."""

from __future__ import annotations

import json

import pytest

from next_is_you.send_gate import SystemSendGate
from test_scheduler_outbox import (
    LocalContext,
    LocalD1,
    LocalDurableStorage,
    make_gate,
    seed,
)

# The seeded visit is on 2026-09-27; its Taipei cutoff is 2026-09-27T15:59Z.
STOPPED_AT = "2026-09-27T13:00:00Z"
AFTER_EVERY_DEADLINE = "2026-10-01T00:00:00Z"


def insert_expired_draft(database: LocalD1, visit_id: str = "draft") -> None:
    database.connection.execute(
        """INSERT INTO visits (
            id, hospital, visit_date, department_code, clinic_code,
            clinic_session, patient_number, state, created_at, draft_expires_at
        ) VALUES (?, 'ntuh-main', '2026-09-27', 'SYN', 'SYN-1',
            'afternoon', 90, 'draft', '2026-09-26T13:00:00Z',
            '2026-09-29T15:59:00Z')""",
        (visit_id,),
    )


def count(database: LocalD1, sql: str) -> int:
    return database.connection.execute(sql).fetchone()[0]


def visit_ids(database: LocalD1) -> set[str]:
    return {row[0] for row in database.connection.execute("SELECT id FROM visits")}


async def stopped_visit_and_expired_draft(
    database: LocalD1, storage: LocalDurableStorage
) -> None:
    """A stopped visit with a recipient, plus an expired draft, as a deployed
    environment could hold after a restore of rehearsal data."""
    rehearsal = make_gate(database, storage)
    await seed(rehearsal)
    assert await rehearsal.stop_visit("v1", STOPPED_AT) == "stopped"
    insert_expired_draft(database)


def deployed_gate(
    database: LocalD1, storage: LocalDurableStorage, environment: str = "staging"
) -> SystemSendGate:
    return SystemSendGate(
        LocalContext(storage),
        {
            "DB": database,
            "NIY_ENVIRONMENT": environment,
            "NIY006_LOCAL_TEST_MODE": "0",
        },
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("environment", ["staging", "production"])
async def test_send_hold_tick_deletes_expired_draft_and_stopped_visit(environment):
    database = LocalD1()
    storage = LocalDurableStorage()
    await stopped_visit_and_expired_draft(database, storage)
    gate = deployed_gate(database, storage, environment)

    result = await gate.scheduled_tick(AFTER_EVERY_DEADLINE)

    assert result["held"] is True
    assert visit_ids(database) == set()
    assert count(database, "SELECT COUNT(*) FROM visit_recipients") == 0
    # Held: nothing was sent, queued or read.
    assert count(database, "SELECT COUNT(*) FROM outbound_events") == 0
    assert "test_line_requests" not in storage.values
    assert (await gate.scheduler_status())["recovery_hold"] is False


@pytest.mark.asyncio
async def test_second_send_hold_tick_after_a_deletion_is_not_a_ledger_mismatch():
    database = LocalD1()
    storage = LocalDurableStorage()
    await stopped_visit_and_expired_draft(database, storage)
    gate = deployed_gate(database, storage)

    await gate.scheduled_tick(AFTER_EVERY_DEADLINE)
    second = await gate.scheduled_tick("2026-10-01T00:01:00Z")

    assert "reason" not in second
    assert (await gate.scheduler_status())["recovery_hold"] is False


async def set_by_hand(gate: SystemSendGate, _database: LocalD1) -> None:
    assert await gate.hold_for_reconciliation()


async def ledger_changed_outside_the_gate(
    gate: SystemSendGate, database: LocalD1
) -> None:
    # A restore brings the stopped visit back to active: it could send again.
    # (A change that leaves it stopped is outside the ledger, #170.)
    database.connection.execute("UPDATE visits SET state = 'active' WHERE id = 'v1'")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "enter_recovery_hold", [set_by_hand, ledger_changed_outside_the_gate]
)
@pytest.mark.parametrize("environment", ["staging", "local-test"])
async def test_recovery_hold_tick_deletes_only_expired_drafts(
    enter_recovery_hold, environment
):
    database = LocalD1()
    storage = LocalDurableStorage()
    await stopped_visit_and_expired_draft(database, storage)
    gate = (
        make_gate(database, storage)
        if environment == "local-test"
        else deployed_gate(database, storage)
    )
    await enter_recovery_hold(gate, database)

    result = await gate.scheduled_tick(AFTER_EVERY_DEADLINE)

    assert result["held"] is True
    assert visit_ids(database) == {"v1"}
    assert count(database, "SELECT COUNT(*) FROM visit_recipients") == 1
    assert count(database, "SELECT COUNT(*) FROM recipients") == 1
    assert (await gate.scheduler_status())["recovery_hold"] is True


@pytest.mark.asyncio
async def test_send_hold_tick_reports_and_logs_what_it_cleaned_up(capsys):
    database = LocalD1()
    storage = LocalDurableStorage()
    await stopped_visit_and_expired_draft(database, storage)
    # Still active although its visit day has passed: expires, then is deleted
    # in the same tick because its 48 hours ran out at 2026-09-29T15:59Z.
    await seed(make_gate(database, storage), visit_id="v2", recipient_id="r2")
    gate = deployed_gate(database, storage)
    capsys.readouterr()

    result = await gate.scheduled_tick(AFTER_EVERY_DEADLINE)

    assert result == {
        "held": True,
        "stops_finalized": 0,
        "visits_expired": 1,
        "withdrawals_erased": 0,
        "drafts_deleted": 1,
        "visits_deleted": 2,
    }
    logged = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert logged == [{"event": "scheduled_tick", **result}]
