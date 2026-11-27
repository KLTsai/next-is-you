"""The visit lifecycle module: every allowed and refused transition (#251).

Fixture/mock evidence: the lifecycle over a local database, with a fixed clock.
Each refused transition is checked against every row the product stores.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from local_d1 import LocalStore
from next_is_you import visit_lifecycle
from next_is_you.persistence import VisitRepository
from visit_states import SEEDED_AT, add_draft, move_draft_to, send_in_flight

STATES = ("draft", "active", "stopping", "stopped", "expired")
NOW = datetime(2026, 9, 27, 1, 0, tzinfo=timezone.utc)
# 23:59 Asia/Taipei on the seeded visit day, and 48 hours after it.
CUTOFF = datetime(2026, 9, 27, 15, 59, tzinfo=timezone.utc)
DUE = datetime(2026, 9, 29, 15, 59, tzinfo=timezone.utc)
SECOND = timedelta(seconds=1)


def others(*allowed: str) -> list[str]:
    return [state for state in STATES if state not in allowed]


async def visit_in(
    state: str, *, recipient_ids: tuple[str, ...] = ("r1",)
) -> tuple[LocalStore, VisitRepository]:
    store = LocalStore()
    repository = VisitRepository(store)
    await add_draft(repository, recipient_ids=recipient_ids)
    await move_draft_to(repository, state)
    return store, repository


def stored(store: LocalStore) -> list[list[tuple]]:
    """Every row a transition could write."""
    return [
        [tuple(row) for row in store.connection.execute(f"SELECT * FROM {table}")]
        for table in ("visits", "visit_recipients", "outbound_events", "recipients")
    ]


def visit(store: LocalStore) -> dict:
    row = store.connection.execute("SELECT * FROM visits WHERE id = 'v1'").fetchone()
    return dict(row) if row is not None else {}


def ended(store: LocalStore) -> tuple[str, str | None, str | None]:
    row = visit(store)
    return row["state"], row["stopped_at"], row["delete_after"]


def settle(store: LocalStore) -> None:
    """The LINE request in flight is answered."""
    store.connection.execute(
        "UPDATE outbound_events SET outcome = 'accepted' WHERE outcome = 'in_flight'"
    )


def test_the_states_are_the_ones_the_product_stores() -> None:
    assert visit_lifecycle.STATES == STATES


# Start


@pytest.mark.asyncio
async def test_start_runs_a_draft_and_freezes_its_recipients() -> None:
    store, repository = await visit_in("draft")

    assert visit_lifecycle.can_start("draft")
    assert await repository.lifecycle.start("v1", NOW)

    row = visit(store)
    assert row["state"] == "active"
    assert row["roster_frozen"] == 1
    assert row["started_at"] == "2026-09-27T01:00:00Z"
    assert row["draft_expires_at"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("state", others("draft"))
async def test_start_is_refused_outside_draft_and_writes_nothing(state: str) -> None:
    store, repository = await visit_in(state)
    before = stored(store)

    assert not visit_lifecycle.can_start(state)
    assert not await repository.lifecycle.start("v1", NOW)

    assert stored(store) == before


@pytest.mark.asyncio
async def test_start_is_refused_without_a_recipient_and_writes_nothing() -> None:
    store, repository = await visit_in("draft", recipient_ids=())
    before = stored(store)

    assert not await repository.lifecycle.start("v1", SEEDED_AT)

    assert stored(store) == before


# Stop


@pytest.mark.asyncio
async def test_stop_ends_a_running_visit_with_no_send_in_flight() -> None:
    store, repository = await visit_in("active")

    assert visit_lifecycle.can_stop("active")
    assert await repository.lifecycle.stop("v1", NOW) == "stopped"

    assert ended(store) == ("stopped", "2026-09-27T01:00:00Z", "2026-09-29T01:00:00Z")


@pytest.mark.asyncio
async def test_stop_with_a_send_in_flight_waits_in_stopping() -> None:
    store, repository = await visit_in("active")
    await send_in_flight(repository)

    assert await repository.lifecycle.stop("v1", NOW) == "stopping"

    assert ended(store) == ("stopping", None, None)


@pytest.mark.asyncio
async def test_stop_again_on_a_stopping_visit_ends_it_once_the_send_settled() -> None:
    store, repository = await visit_in("stopping")
    settle(store)

    assert visit_lifecycle.can_stop("stopping")
    assert await repository.lifecycle.stop("v1", NOW) == "stopped"

    assert ended(store) == ("stopped", "2026-09-27T01:00:00Z", "2026-09-29T01:00:00Z")


@pytest.mark.asyncio
async def test_stop_again_with_the_send_still_in_flight_writes_nothing() -> None:
    store, repository = await visit_in("stopping")
    before = stored(store)

    assert await repository.lifecycle.stop("v1", NOW) == "stopping"

    assert stored(store) == before


@pytest.mark.asyncio
async def test_a_repeated_stop_answers_stopped_and_writes_nothing() -> None:
    store, repository = await visit_in("stopped")
    before = stored(store)

    assert visit_lifecycle.can_stop("stopped")
    assert await repository.lifecycle.stop("v1", NOW) == "stopped"

    assert stored(store) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["draft", "expired"])
async def test_stop_is_refused_and_writes_nothing(state: str) -> None:
    store, repository = await visit_in(state)
    before = stored(store)

    assert not visit_lifecycle.can_stop(state)
    assert await repository.lifecycle.stop("v1", NOW) == state

    assert stored(store) == before


@pytest.mark.asyncio
async def test_stop_of_an_unknown_visit_answers_nothing() -> None:
    _, repository = await visit_in("active")

    assert await repository.lifecycle.stop("missing", NOW) is None


@pytest.mark.asyncio
async def test_stop_rejects_a_naive_time_and_writes_nothing() -> None:
    store, repository = await visit_in("active")
    before = stored(store)

    with pytest.raises(ValueError, match="timezone-aware"):
        await repository.lifecycle.stop("v1", datetime(2026, 9, 27, 1, 0))

    assert stored(store) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["active", "stopping"])
async def test_stop_during_a_send_closes_the_visit_to_new_sends(state: str) -> None:
    store, repository = await visit_in(state)
    if state == "active":
        await send_in_flight(repository)

    assert await repository.lifecycle.request_stop_during_send("v1")

    assert ended(store) == ("stopping", None, None)


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["draft", "active", "stopped", "expired"])
async def test_stop_during_a_send_is_refused_without_one_and_writes_nothing(
    state: str,
) -> None:
    store, repository = await visit_in(state)
    before = stored(store)

    assert not await repository.lifecycle.request_stop_during_send("v1")

    assert stored(store) == before


# Finalizing a stop


@pytest.mark.asyncio
async def test_finalizing_a_stop_ends_the_visit_once_its_send_settles() -> None:
    store, repository = await visit_in("stopping")
    settle(store)

    assert await repository.lifecycle.finalize_stops(NOW) == 1

    assert ended(store) == ("stopped", "2026-09-27T01:00:00Z", "2026-09-29T01:00:00Z")


@pytest.mark.asyncio
async def test_finalizing_a_stop_waits_for_the_send_and_writes_nothing() -> None:
    store, repository = await visit_in("stopping")
    before = stored(store)

    assert await repository.lifecycle.finalize_stops(NOW) == 0

    assert stored(store) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("state", others("stopping"))
async def test_finalizing_leaves_a_visit_that_is_not_stopping(state: str) -> None:
    store, repository = await visit_in(state)
    before = stored(store)

    assert await repository.lifecycle.finalize_stops(NOW) == 0

    assert stored(store) == before


# The day-over end


@pytest.mark.asyncio
async def test_the_day_over_end_starts_at_the_cutoff() -> None:
    store, repository = await visit_in("active")
    before = stored(store)
    assert await repository.lifecycle.end_day_over_visits(CUTOFF - SECOND) == 0
    assert stored(store) == before

    assert await repository.lifecycle.end_day_over_visits(CUTOFF) == 1

    assert ended(store) == ("expired", "2026-09-27T15:59:00Z", "2026-09-29T15:59:00Z")


@pytest.mark.asyncio
async def test_a_day_over_end_found_late_counts_from_the_visit_days_cutoff() -> None:
    store, repository = await visit_in("active")

    late = CUTOFF + timedelta(days=1)
    assert await repository.lifecycle.end_day_over_visits(late) == 1

    assert ended(store) == ("expired", "2026-09-27T15:59:00Z", "2026-09-29T15:59:00Z")


@pytest.mark.asyncio
@pytest.mark.parametrize("state", others("active"))
async def test_the_day_over_end_leaves_a_visit_that_is_not_active(state: str) -> None:
    store, repository = await visit_in(state)
    before = stored(store)

    assert await repository.lifecycle.end_day_over_visits(CUTOFF) == 0

    assert stored(store) == before


@pytest.mark.asyncio
async def test_the_day_over_end_rejects_a_naive_time_and_writes_nothing() -> None:
    store, repository = await visit_in("active")
    before = stored(store)

    with pytest.raises(ValueError, match="timezone-aware"):
        await repository.lifecycle.end_day_over_visits(datetime(2026, 9, 28, 0, 0))

    assert stored(store) == before


# Reopening for correction


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["stopped", "expired"])
async def test_an_ended_visit_reopens_as_a_draft_for_correction(state: str) -> None:
    store, repository = await visit_in(state)

    assert visit_lifecycle.can_reopen_for_correction(state)
    assert await repository.lifecycle.reopen_for_correction("v1")

    assert ended(store) == ("draft", None, None)
    assert visit(store)["roster_frozen"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("state", others("stopped", "expired"))
async def test_reopening_is_refused_before_the_end_and_writes_nothing(
    state: str,
) -> None:
    store, repository = await visit_in(state)
    before = stored(store)

    assert not visit_lifecycle.can_reopen_for_correction(state)
    assert not await repository.lifecycle.reopen_for_correction("v1")

    assert stored(store) == before


# Removing a recipient


@pytest.mark.asyncio
@pytest.mark.parametrize("state", STATES)
async def test_a_recipient_can_be_removed_while_another_remains(state: str) -> None:
    _, repository = await visit_in(state, recipient_ids=("r1", "r2"))

    assert visit_lifecycle.can_remove_recipient(state)
    assert await repository.lifecycle.remove_recipient("v1", "r2")

    assert await repository.selected_recipient_ids("v1") == {"r1"}


@pytest.mark.asyncio
@pytest.mark.parametrize("state", STATES)
async def test_removing_the_last_recipient_is_refused_and_writes_nothing(
    state: str,
) -> None:
    store, repository = await visit_in(state)
    before = stored(store)

    assert not await repository.lifecycle.remove_recipient("v1", "r1")

    assert stored(store) == before


@pytest.mark.asyncio
async def test_removing_someone_not_on_the_visit_writes_nothing() -> None:
    store, repository = await visit_in("active", recipient_ids=("r1", "r2"))
    before = stored(store)

    assert not await repository.lifecycle.remove_recipient("v1", "stranger")

    assert stored(store) == before


@pytest.mark.asyncio
async def test_a_refused_removal_state_writes_nothing(monkeypatch) -> None:
    store, repository = await visit_in("active", recipient_ids=("r1", "r2"))
    before = stored(store)
    monkeypatch.setattr(visit_lifecycle, "RECIPIENT_REMOVAL_FROM", ("draft",))

    assert not await repository.lifecycle.remove_recipient("v1", "r2")

    assert stored(store) == before


# The 48-hour deletion


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["stopped", "expired"])
async def test_an_ended_visit_is_deleted_once_its_48_hours_run_out(state: str) -> None:
    store, repository = await visit_in(state)
    due = datetime.fromisoformat(visit(store)["delete_after"])
    before = stored(store)
    assert await repository.lifecycle.delete_expired_visits(due - SECOND) == 0
    assert stored(store) == before

    assert await repository.lifecycle.delete_expired_visits(due) == 1

    assert await repository.get_visit("v1") is None


@pytest.mark.asyncio
async def test_an_ended_visit_with_a_send_in_flight_is_kept() -> None:
    store, repository = await visit_in("active")
    await send_in_flight(repository)
    assert await repository.lifecycle.end_day_over_visits(CUTOFF) == 1
    before = stored(store)

    assert await repository.lifecycle.delete_expired_visits(DUE) == 0
    assert stored(store) == before

    settle(store)
    assert await repository.lifecycle.delete_expired_visits(DUE) == 1
    assert stored(store)[:3] == [[], [], []]


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["draft", "active", "stopping"])
async def test_the_ended_deletion_never_takes_a_visit_that_has_not_ended(
    state: str,
) -> None:
    store, repository = await visit_in(state)
    before = stored(store)

    assert (
        await repository.lifecycle.delete_expired_visits(DUE + timedelta(days=30)) == 0
    )

    assert stored(store) == before


@pytest.mark.asyncio
async def test_a_draft_is_deleted_once_its_deletion_time_passes() -> None:
    store, repository = await visit_in("draft")
    before = stored(store)
    assert await repository.lifecycle.delete_expired_drafts(DUE - SECOND) == 0
    assert stored(store) == before

    assert await repository.lifecycle.delete_expired_drafts(DUE) == 1

    assert await repository.get_visit("v1") is None


@pytest.mark.asyncio
@pytest.mark.parametrize("state", others("draft"))
async def test_the_draft_deletion_never_takes_a_started_visit(state: str) -> None:
    store, repository = await visit_in(state)
    before = stored(store)

    assert (
        await repository.lifecycle.delete_expired_drafts(DUE + timedelta(days=30)) == 0
    )

    assert stored(store) == before


@pytest.mark.asyncio
async def test_a_stop_rule_without_active_leaves_a_running_visit(monkeypatch) -> None:
    store, repository = await visit_in("active")
    before = stored(store)
    monkeypatch.setattr(visit_lifecycle, "STOP_ACCEPTS", ("stopping", "stopped"))

    assert await repository.lifecycle.stop("v1", NOW) == "active"

    assert stored(store) == before


@pytest.mark.asyncio
async def test_stop_during_a_send_is_refused_once_a_stopping_visits_send_settled() -> (
    None
):
    store, repository = await visit_in("stopping")
    settle(store)
    before = stored(store)

    assert not await repository.lifecycle.request_stop_during_send("v1")

    assert stored(store) == before
