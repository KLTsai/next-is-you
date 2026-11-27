"""Visits in a given state, reached the way the product reaches them.

A visit changes only through the repository and the visit lifecycle, so a test
never holds a visit the product could not have produced. Only the synthetic
recipient accounts are inserted directly.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Sequence

from next_is_you.persistence import Statement, VisitRepository
from next_is_you.visit_lifecycle import visit_cutoff

VISIT_DAY = date(2026, 9, 27)
SEEDED_AT = datetime(2026, 9, 27, 0, 0, tzinfo=timezone.utc)


async def add_recipient_account(repository: VisitRepository, recipient_id: str) -> None:
    """A synthetic recipient who has accepted and can be chosen for a visit."""
    seeded = SEEDED_AT.isoformat()
    await repository._store.execute(
        Statement(
            """INSERT OR IGNORE INTO recipients (id, line_subject, display_name,
            consented_at, friendship_checked_at, active, created_at)
            VALUES (?, ?, 'Synthetic recipient', ?, ?, 1, ?)""",
            (recipient_id, f"line-{recipient_id}", seeded, seeded, seeded),
        )
    )


async def add_draft(
    repository: VisitRepository,
    visit_id: str = "v1",
    *,
    recipient_ids: Sequence[str] = ("r1",),
    visit_day: date = VISIT_DAY,
    now: datetime = SEEDED_AT,
) -> None:
    await repository.create_draft(
        visit_id=visit_id,
        hospital="ntuh-main",
        visit_day=visit_day,
        department_code="SYN",
        clinic_code="SYN-1",
        clinic_session="afternoon",
        patient_number=85,
        now=now,
    )
    for recipient_id in recipient_ids:
        await add_recipient_account(repository, recipient_id)
        assert await repository.add_recipient(visit_id, recipient_id, now)


async def send_in_flight(
    repository: VisitRepository,
    visit_id: str = "v1",
    *,
    recipient_id: str = "r1",
    now: datetime = SEEDED_AT,
) -> str:
    """A reminder of a running visit whose LINE request has not settled."""
    event_id = f"{visit_id}-{recipient_id}-in-flight"
    assert "created" == await repository.create_reminder(
        event_id=event_id,
        visit_id=visit_id,
        recipient_id=recipient_id,
        event_kind="unavailable",
        retry_key=f"retry-{event_id}",
        payload_json="{}",
        now=now,
    )
    assert await repository.begin_event_attempt(event_id, now) == 1
    return event_id


async def move_draft_to(
    repository: VisitRepository,
    state: str,
    visit_id: str = "v1",
    *,
    recipient_id: str = "r1",
    visit_day: date = VISIT_DAY,
    now: datetime = SEEDED_AT,
) -> None:
    """Take a draft to `state`. `stopping` leaves one send in flight.

    `expired` ends every active visit whose day is over by `visit_day`'s cutoff,
    so reach it before another visit of that day is started.
    """
    lifecycle = repository.lifecycle
    if state == "draft":
        return
    assert await lifecycle.start(visit_id, now)
    if state == "stopping":
        await send_in_flight(repository, visit_id, recipient_id=recipient_id, now=now)
        assert await lifecycle.stop(visit_id, now) == "stopping"
    elif state == "stopped":
        assert await lifecycle.stop(visit_id, now) == "stopped"
    elif state == "expired":
        assert await lifecycle.end_day_over_visits(visit_cutoff(visit_day)) == 1
    else:
        assert state == "active", state
