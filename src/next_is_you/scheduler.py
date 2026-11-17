"""Scheduled alert evaluation and durable outbox delivery."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable, Mapping, Protocol

from next_is_you.alerts import evaluate_alerts
from next_is_you.domain import (
    ClinicMatchQuery,
    ClinicScope,
    ClinicSession,
    Hospital,
    HospitalReader,
    MatchOutcome,
    ReadFailed,
    ReadSkipped,
)
from next_is_you.line_messaging import LinePushResult
from next_is_you.persistence import TAIPEI, VisitRepository, visit_cutoff

LINE_RETRY_WINDOW = timedelta(hours=24)
_MESSAGES = {
    "near": "候診進度已接近您的號碼，請留意現場叫號。",
    "unavailable": "目前無法取得診間候診進度，請留意現場叫號。",
}
# Reasons that mean a schedule read failed transiently; the sweep leaves such
# drafts untouched and retries on the next Taipei day.
_SWEEP_TRANSIENT_REASONS = frozenset(
    ("no_observation", "access_denied", "timeout", "schema_drift")
)


class LineSender(Protocol):
    async def push_text(
        self, recipient_id: str, text: str, *, retry_key: str
    ) -> LinePushResult: ...


Clock = Callable[[], datetime]


@dataclass(frozen=True, slots=True)
class TickPlan:
    visits_evaluated: int = 0
    events_created: int = 0
    event_ids: tuple[str, ...] = ()
    closed: int = 0
    drafts_rechecked: int = 0
    drafts_scope_mismatch: int = 0


@dataclass(frozen=True, slots=True)
class SendResult:
    outcome: str
    started: bool
    settled: bool = True


class OutboxScheduler:
    """Evaluate visits and send through an externally serialized system gate."""

    def __init__(
        self,
        repository: VisitRepository,
        hospital_reader: HospitalReader | None,
        line_sender: LineSender | None,
        clock: Clock,
    ) -> None:
        self._visits = repository
        self._hospital = hospital_reader
        self._line = line_sender
        self._clock = clock

    async def recover(self, now: datetime) -> int:
        """Classify persisted in-flight sends from a prior invocation as uncertain."""
        return await self._visits.recover_in_flight_events(now)

    async def prepare_tick(self, now: datetime) -> TickPlan:
        if now.tzinfo is None:
            raise ValueError("scheduler time must be timezone-aware")

        await self._visits.finalize_stopping(now)
        await self._visits.expire_due_visits(now)
        await self._visits.erase_settled_withdrawals()
        await self._visits.delete_expired(now)

        rechecked, mismatched = await self._preflight_sweep(now)

        if self._hospital is None or self._line is None:
            return TickPlan(
                drafts_rechecked=rechecked, drafts_scope_mismatch=mismatched
            )

        rows = await self._visits.active_schedule_rows()
        by_visit: dict[str, list[Mapping[str, Any]]] = {}
        for row in rows:
            by_visit.setdefault(str(row["id"]), []).append(row)

        evaluated = 0
        created = 0
        closed = 0
        event_ids: list[str] = []

        for visit_id, selected_rows in by_visit.items():
            visit = selected_rows[0]
            sample_time = self._clock()
            if sample_time.tzinfo is None:
                raise ValueError("scheduler clock must return an aware datetime")
            cutoff = visit_cutoff(
                datetime.fromisoformat(str(visit["visit_date"])).date()
            )
            if sample_time >= cutoff:
                closed += await self._visits.expire_due_visits(sample_time)
                continue

            scope = _scope(visit)
            try:
                observation = await self._hospital.observe(scope, sample_time)
            except TimeoutError:
                observation = None
                source_status, source_reason = "unavailable", "timeout"
            except Exception:
                observation = None
                source_status, source_reason = "invalid", "invalid_data"
            else:
                if isinstance(observation, ReadSkipped):
                    # Nothing was read: not a failed read, so no alert evaluation.
                    if observation.source_read is not None:
                        await self._visits.set_source_read(
                            visit_id, *observation.source_read
                        )
                    continue
                if isinstance(observation, ReadFailed):
                    source_status = observation.status
                    source_reason = observation.reason
                    observation = None
                else:
                    source_status, source_reason = _source_read_status(
                        observation, scope, sample_time
                    )
            await self._visits.set_source_read(visit_id, source_status, source_reason)
            recipients = tuple(str(row["recipient_id"]) for row in selected_rows)
            existing = await self._visits.event_kinds(visit_id)
            unavailable_already = frozenset(
                recipient for recipient, kind in existing if kind == "unavailable"
            )
            previous_observed_number = (
                int(visit["near_prev_observed_number"])
                if visit["near_prev_observed_number"] is not None
                else None
            )
            evaluation = evaluate_alerts(
                expected_scope=scope,
                patient_number=int(visit["patient_number"]),
                observation=observation,
                selected_recipients=recipients,
                previous_observed_number=previous_observed_number,
                near_counts=await self._visits.near_counts(visit_id),
                unavailable_already_sent=unavailable_already,
                previous_unusable_reads=int(visit["consecutive_unusable_reads"]),
            )
            observed_at = (
                _parse_time(observation.observed_at)
                if observation is not None
                else sample_time
            )
            if evaluation.usable_observation:
                assert (
                    observation is not None and observation.current_number is not None
                )
                new_events = [
                    {
                        "event_id": str(uuid.uuid4()),
                        "recipient_id": recipient_id,
                        "retry_key": str(uuid.uuid4()),
                        "payload_json": json.dumps(
                            {"text": _MESSAGES["near"]},
                            ensure_ascii=False,
                            separators=(",", ":"),
                        ),
                    }
                    for recipient_id in evaluation.near_recipients
                ]
                # Advance the previously observed number and persist its near
                # reminders in one transaction so a crash cannot lose or duplicate
                # a reminder on the next tick.
                created += await self._visits.commit_near_reminders(
                    visit_id,
                    observed_number=int(observation.current_number),
                    observed_at=observed_at,
                    now=sample_time,
                    new_events=new_events,
                )
            else:
                await self._visits.update_observation(
                    visit_id,
                    current_number=None,
                    observed_at=observed_at,
                    consecutive_unusable_reads=evaluation.consecutive_unusable_reads,
                )
                for recipient_id in evaluation.unavailable_recipients:
                    before = await self._visits.event_kinds(visit_id)
                    await self._visits.create_event_if_absent(
                        event_id=str(uuid.uuid4()),
                        visit_id=visit_id,
                        recipient_id=recipient_id,
                        event_kind="unavailable",
                        retry_key=str(uuid.uuid4()),
                        payload_json=json.dumps(
                            {"text": _MESSAGES["unavailable"]},
                            ensure_ascii=False,
                            separators=(",", ":"),
                        ),
                        now=sample_time,
                    )
                    after = await self._visits.event_kinds(visit_id)
                    if (recipient_id, "unavailable") not in before and (
                        recipient_id,
                        "unavailable",
                    ) in after:
                        created += 1
            evaluated += 1

            event_ids.extend(
                str(event["id"])
                for event in await self._visits.retryable_events(visit_id)
            )

        return TickPlan(
            visits_evaluated=evaluated,
            events_created=created,
            event_ids=tuple(event_ids),
            closed=closed,
            drafts_rechecked=rechecked,
            drafts_scope_mismatch=mismatched,
        )

    async def _preflight_sweep(self, now: datetime) -> tuple[int, int]:
        """Re-validate drafts in `[today+1, today+14]` once per Taipei day.

        Each draft is put to its hospital reader's `match_clinic` and the
        sweep branches only on the outcome: a match keeps the draft; a clinic
        that is not scheduled or was cancelled by the hospital flips
        `latest_source_read_*` to the organizer-attention signal. A transient
        read failure leaves the draft untouched and retries on the next Taipei
        day. Every draft in one sweep is matched with the same clock reading,
        which lets a reader share one source read across them.
        """
        matcher = getattr(self._hospital, "match_clinic", None)
        if matcher is None:
            return 0, 0
        today = now.astimezone(TAIPEI).date()
        drafts = await self._visits.drafts_due_for_preflight_sweep(today)
        if not drafts:
            return 0, 0
        rechecked = 0
        mismatched = 0
        for draft in drafts:
            try:
                query = ClinicMatchQuery(
                    hospital=Hospital(str(draft["hospital"])),
                    department_code=str(draft["department_code"]),
                    visit_date=datetime.fromisoformat(str(draft["visit_date"])).date(),
                    session=ClinicSession(str(draft["clinic_session"])),
                    clinic_code=str(draft["clinic_code"]),
                )
            except ValueError:
                continue
            try:
                match = await matcher(query, now)
            except Exception:
                # The sweep leaves the draft untouched on transport
                # exceptions; the next Taipei day retries.
                continue
            if match.outcome is MatchOutcome.UNAVAILABLE:
                if match.reason in _SWEEP_TRANSIENT_REASONS:
                    continue
                # Non-transient unavailable (visit_date_past from a race
                # across midnight, scope_mismatch, invalid data) is a real
                # mismatch and belongs on the draft as an organizer signal.
                await self._visits.set_source_read(
                    str(draft["id"]), "scope_mismatch", "scope_mismatch"
                )
                await self._visits.mark_preflight_checked(str(draft["id"]), today)
                rechecked += 1
                mismatched += 1
                continue
            if match.outcome is MatchOutcome.MATCHED:
                # The draft still matches; clear a prior scope_mismatch flag
                # so an earlier bad run does not linger as a false alarm.
                await self._visits.set_source_read(
                    str(draft["id"]), "unavailable", "no_observation"
                )
            else:
                # Not scheduled, cancelled by the hospital, or beyond what the
                # hospital has published: all keep today's attention signal.
                await self._visits.set_source_read(
                    str(draft["id"]), "scope_mismatch", "scope_mismatch"
                )
                mismatched += 1
            await self._visits.mark_preflight_checked(str(draft["id"]), today)
            rechecked += 1
        return rechecked, mismatched

    async def send_event(
        self,
        event_id: str,
        *,
        before_request: Callable[[str], Awaitable[None]] | None = None,
    ) -> SendResult:
        """Start one request after the caller acquires the system-wide gate."""
        if self._line is None:
            return SendResult("skipped", False)
        event = await self._visits.retryable_event(event_id)
        if event is None:
            return SendResult("skipped", False)

        send_time = self._clock()
        if send_time.tzinfo is None:
            raise ValueError("scheduler clock must return an aware datetime")
        cutoff = visit_cutoff(datetime.fromisoformat(str(event["visit_date"])).date())
        if send_time >= cutoff:
            await self._visits.expire_due_visits(send_time)
            return SendResult("skipped", False)
        first_request = event.get("first_request_at")
        if first_request is not None and send_time >= (
            _parse_time(str(first_request)) + LINE_RETRY_WINDOW
        ):
            return SendResult("unknown", False)

        attempt_count = await self._visits.begin_event_attempt(event_id, send_time)
        if attempt_count is None:
            return SendResult("skipped", False)
        if before_request is not None:
            await before_request(event_id)
        request_time = self._clock()
        if request_time.tzinfo is None:
            raise ValueError("scheduler clock must return an aware datetime")
        if request_time >= cutoff:
            await self._visits.expire_due_visits(request_time)
            await self._abort_before_request(event_id, attempt_count, event)
            return SendResult("skipped", False)
        if first_request is not None and request_time >= (
            _parse_time(str(first_request)) + LINE_RETRY_WINDOW
        ):
            await self._abort_before_request(event_id, attempt_count, event)
            return SendResult("unknown", False)
        try:
            payload = json.loads(str(event["payload_json"]))
            result = await self._line.push_text(
                str(event["line_subject"]),
                str(payload["text"]),
                retry_key=str(event["retry_key"]),
            )
            outcome = result.outcome
            error_code = (
                None
                if outcome == "accepted"
                else f"http_{result.status_code}"
                if result.status_code is not None
                else "transport_unknown"
            )
        except Exception:
            outcome = "unknown"
            error_code = "transport_exception"
        settled = self._clock()
        settled_ok = await self._visits.settle_event_attempt(
            event_id,
            attempt_count,
            outcome,
            settled,
            error_code,
        )
        return SendResult(outcome, True, settled_ok)

    async def _abort_before_request(
        self,
        event_id: str,
        attempt_count: int,
        event: Mapping[str, Any],
    ) -> None:
        if not await self._visits.abort_event_attempt(
            event_id,
            attempt_count,
            previous_outcome=str(event["outcome"]),
            previous_request_started_at=(
                str(event["request_started_at"])
                if event.get("request_started_at") is not None
                else None
            ),
            previous_first_request_at=(
                str(event["first_request_at"])
                if event.get("first_request_at") is not None
                else None
            ),
            previous_settled_at=(
                str(event["settled_at"])
                if event.get("settled_at") is not None
                else None
            ),
            previous_error_code=(
                str(event["error_code"])
                if event.get("error_code") is not None
                else None
            ),
        ):
            raise RuntimeError("prepared outbox attempt could not be rolled back")


def _scope(row: Mapping[str, Any]) -> ClinicScope:
    return ClinicScope(
        hospital=Hospital(str(row["hospital"])),
        visit_date=datetime.fromisoformat(str(row["visit_date"])).date(),
        department_code=str(row["department_code"]),
        clinic_code=str(row["clinic_code"]),
        session=ClinicSession(str(row["clinic_session"])),
        doctor_code=str(row["doctor_code"])
        if row.get("doctor_code") is not None
        else None,
        room_code=str(row["room_code"]) if row.get("room_code") is not None else None,
    )


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("stored timestamps must be timezone-aware")
    return parsed


def _source_read_status(
    observation, expected: ClinicScope, now: datetime
) -> tuple[str, str]:
    if observation is None:
        return "unavailable", "no_observation"
    try:
        observed_at = _parse_time(observation.observed_at)
        scope = observation.scope
        trustworthy = observation.trustworthy_current
        current_number = observation.current_number
    except (AttributeError, TypeError, ValueError):
        return "invalid", "invalid_data"
    if observed_at > now or now - observed_at > timedelta(minutes=2):
        return "stale", "stale_sample"
    if scope != expected:
        return "scope_mismatch", "scope_mismatch"
    if not trustworthy:
        return "untrusted", "untrusted_source"
    if (
        isinstance(current_number, bool)
        or not isinstance(current_number, int)
        or current_number < 1
    ):
        return "invalid", "invalid_data"
    return "usable", "none"
