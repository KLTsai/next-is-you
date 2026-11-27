"""The visit lifecycle: a visit's states and its transitions between them.

Every state a visit can be in, and every set of states an action accepts, is
defined here. A caller asks one of the `can_...` questions or takes a transition;
it names no state set of its own. Each transition is guarded SQL built from these
rules, so the database refuses a visit in the wrong state in the same statement
that would change it.

The transitions do not order themselves against sends: whoever changes a started
visit does it inside the send gate's guarded write on the send record (ADR 0007).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from next_is_you.storage import TAIPEI, SqlStore, Statement, iso_utc

DRAFT = "draft"
ACTIVE = "active"
STOPPING = "stopping"
STOPPED = "stopped"
EXPIRED = "expired"
STATES = (DRAFT, ACTIVE, STOPPING, STOPPED, EXPIRED)

# A running visit holds the one running slot and keeps the tick coming.
RUNNING_STATES = (ACTIVE, STOPPING)
ENDED_STATES = (STOPPED, EXPIRED)

# The states each action is accepted in.
START_FROM = (DRAFT,)
# A Stop on a stopped visit changes nothing and is answered with its state.
STOP_ACCEPTS = (ACTIVE, STOPPING, STOPPED)
RECIPIENT_REMOVAL_FROM = STATES
CORRECTION_REOPENS_FROM = ENDED_STATES

# How long a visit's data is kept after it ends, or a draft after its day ends.
RETENTION = timedelta(hours=48)


@dataclass(frozen=True, slots=True)
class _Ending:
    """One way a visit ends: from which state, into which, and whether it waits."""

    from_state: str
    to_state: str
    waits_for_sends: bool


_FINALIZED_STOP = _Ending(STOPPING, STOPPED, waits_for_sends=True)
_DAY_OVER = _Ending(ACTIVE, EXPIRED, waits_for_sends=False)

_NO_SEND_IN_FLIGHT = """NOT EXISTS (
    SELECT 1 FROM outbound_events
    WHERE visit_id = visits.id AND outcome = 'in_flight'
)"""


def can_start(state: str) -> bool:
    return state in START_FROM


def can_stop(state: str) -> bool:
    return state in STOP_ACCEPTS


def _stoppable(states: tuple[str, ...]) -> tuple[str, ...]:
    """Those of `states` a Stop is accepted in."""
    return tuple(state for state in states if can_stop(state))


def can_remove_recipient(state: str) -> bool:
    return state in RECIPIENT_REMOVAL_FROM


def can_reopen_for_correction(state: str) -> bool:
    return state in CORRECTION_REOPENS_FROM


def can_correct(state: str) -> bool:
    """Whether the organizer can load a visit's details to correct them."""
    return state == DRAFT or can_reopen_for_correction(state)


def sql_states(states: tuple[str, ...]) -> str:
    """The list for an SQL `state IN`. Takes only this module's state names."""
    return "(" + ", ".join(f"'{state}'" for state in states) + ")"


def visit_cutoff(visit_day: date) -> datetime:
    """The product cutoff is 23:59 Asia/Taipei on the visit day."""
    return datetime.combine(visit_day, time(23, 59), TAIPEI)


def draft_expiry(visit_day: date) -> datetime:
    return visit_cutoff(visit_day) + RETENTION


def terminal_expiry(ended_at: datetime) -> datetime:
    if ended_at.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware")
    return ended_at + RETENTION


class VisitLifecycle:
    """Durable transitions of a visit's state."""

    def __init__(self, store: SqlStore) -> None:
        self._store = store

    async def start(self, visit_id: str, now: datetime) -> bool:
        """Start or resume a corrected series while atomically freezing its roster."""
        changes = await self._store.execute(
            Statement(
                f"""UPDATE visits
                SET state = '{ACTIVE}', roster_frozen = 1,
                    started_at = COALESCE(started_at, ?), stopped_at = NULL,
                    delete_after = NULL, draft_expires_at = NULL
                WHERE id = ? AND state IN {sql_states(START_FROM)}
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

    async def stop(self, visit_id: str, now: datetime) -> str | None:
        """Close the visit to new work, then end it once in-flight sends settle.

        Answers the visit's state afterwards, or None for an unknown visit. This
        does not replace the send gate's ordering of Stop against LINE requests.
        """
        iso_utc(now)  # Validate before changing the visit state.
        await self._store.execute(
            Statement(
                f"""UPDATE visits SET state = '{STOPPING}'
                WHERE id = ? AND state IN {sql_states(_stoppable((ACTIVE,)))}""",
                (visit_id,),
            )
        )
        await self._store.execute(self._end(_FINALIZED_STOP, visit_id, now))
        rows = await self._store.fetch_all(
            Statement("SELECT state FROM visits WHERE id = ?", (visit_id,))
        )
        return str(rows[0]["state"]) if rows else None

    async def request_stop_during_send(self, visit_id: str) -> bool:
        """Close a visit to new sends while one of its LINE requests is pending."""
        changes = await self._store.execute(
            Statement(
                f"""UPDATE visits SET state = '{STOPPING}'
                WHERE id = ? AND state IN {sql_states(_stoppable(RUNNING_STATES))}
                AND EXISTS (
                    SELECT 1 FROM outbound_events
                    WHERE visit_id = visits.id AND outcome = 'in_flight'
                )""",
                (visit_id,),
            )
        )
        return changes == 1

    async def finalize_stops(self, now: datetime) -> int:
        """End every stopping visit whose sends have settled."""
        rows = await self._store.fetch_all(
            Statement(f"SELECT id FROM visits WHERE state = '{STOPPING}'")
        )
        finalized = 0
        for row in rows:
            finalized += await self._store.execute(
                self._end(_FINALIZED_STOP, str(row["id"]), now)
            )
        return finalized

    async def end_day_over_visits(self, now: datetime) -> int:
        """End every active visit whose day is over, as of that day's cutoff."""
        if now.tzinfo is None:
            raise ValueError("timestamps must be timezone-aware")
        local_now = now.astimezone(TAIPEI)
        today = local_now.date()
        today_is_over = local_now >= visit_cutoff(today)
        date_clause = "visit_date <= ?" if today_is_over else "visit_date < ?"
        rows = await self._store.fetch_all(
            Statement(
                f"""SELECT id, visit_date FROM visits
                WHERE state = '{_DAY_OVER.from_state}' AND {date_clause}""",
                (today.isoformat(),),
            )
        )
        if not rows:
            return 0
        statements = [
            self._end(
                _DAY_OVER,
                str(row["id"]),
                visit_cutoff(date.fromisoformat(str(row["visit_date"]))),
            )
            for row in rows
        ]
        return sum(await self._store.batch(statements))

    async def reopen_for_correction(self, visit_id: str) -> bool:
        """The organizer's way back to draft, keeping identity and event caps."""
        changes = await self._store.execute(
            Statement(
                f"""UPDATE visits
                SET state = '{DRAFT}', stopped_at = NULL, delete_after = NULL
                WHERE id = ? AND state IN {sql_states(CORRECTION_REOPENS_FROM)}
                    AND roster_frozen = 1""",
                (visit_id,),
            )
        )
        return changes == 1

    async def remove_recipient(self, visit_id: str, recipient_id: str) -> bool:
        """Take a recipient off a visit; the last one cannot be removed."""
        changes = await self._store.execute(
            Statement(
                f"""DELETE FROM visit_recipients
                WHERE visit_id = ? AND recipient_id = ?
                AND EXISTS (
                    SELECT 1 FROM visits
                    WHERE id = ? AND state IN {sql_states(RECIPIENT_REMOVAL_FROM)}
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

    async def delete_expired_drafts(self, now: datetime) -> int:
        """Drafts past their expiry; a reopened one's messages are deleted too."""
        return await self._store.execute(
            Statement(
                f"""DELETE FROM visits
                WHERE state = '{DRAFT}' AND draft_expires_at <= ?""",
                (iso_utc(now),),
            )
        )

    async def delete_expired_visits(self, now: datetime) -> int:
        """Ended visits whose 48 hours have run out."""
        return await self._store.execute(
            Statement(
                f"""DELETE FROM visits
                WHERE state IN {sql_states(ENDED_STATES)} AND delete_after <= ?
                AND {_NO_SEND_IN_FLIGHT}""",
                (iso_utc(now),),
            )
        )

    def _end(self, ending: _Ending, visit_id: str, ended_at: datetime) -> Statement:
        """The end step: the only statement that ends a visit.

        It sets the state, the ended clock and the 48-hour deletion time. What
        every end must also do belongs here.
        """
        waiting = f" AND {_NO_SEND_IN_FLIGHT}" if ending.waits_for_sends else ""
        return Statement(
            f"""UPDATE visits
            SET state = '{ending.to_state}', stopped_at = ?, delete_after = ?
            WHERE id = ? AND state = '{ending.from_state}'{waiting}""",
            (iso_utc(ended_at), iso_utc(terminal_expiry(ended_at)), visit_id),
        )
