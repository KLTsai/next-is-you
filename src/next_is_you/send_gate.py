"""System-wide Durable Object gate for scheduler and close actions."""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
from typing import Any, Mapping, Sequence

from next_is_you.line_messaging import LinePushClient, LinePushHttpResponse
from next_is_you.persistence import (
    CloudflareD1Store,
    Statement,
    TAIPEI,
    VisitRepository,
    visit_cutoff,
)
from next_is_you.domain import (
    ClinicRoster,
    ClinicScope,
    ClinicSession,
    HospitalReader,
    MatchKind,
    MatchQuery,
    ReadFailed,
    ReadSkipped,
    RosterQuery,
    SourceCapability,
)
from next_is_you.hospital_registry import (
    ReaderDeps,
    RegistryHospitalReader,
    capability_of,
    require_registered,
)
from next_is_you.ntuh_reader import WorkersFetcher
from next_is_you.scheduler import LifecycleCounts, OutboxScheduler, TickPlan

try:
    from workers import DurableObject as _DurableObjectBase
except ModuleNotFoundError as error:
    if error.name != "js":
        raise

    class _DurableObjectBase:
        def __init__(self, ctx: Any, env: Any) -> None:
            self.ctx = ctx
            self.env = env


# ADR 0005: the alarm drives the tick. A visit that is running keeps the
# one-minute cadence the reader expects; otherwise lifecycle chores run on a
# slower alarm.
ACTIVE_ALARM_DELAY = timedelta(minutes=1)
IDLE_ALARM_DELAY = timedelta(minutes=5)


class SystemSendGate(_DurableObjectBase):
    """One SQLite-backed Durable Object serializes every send and close action."""

    def __init__(self, ctx: Any, env: Any) -> None:
        super().__init__(ctx, env)
        self._lock = asyncio.Lock()
        self._stop_transition_lock = asyncio.Lock()
        self._test_request_started = asyncio.Event()
        self._test_request_release = asyncio.Event()

    async def alarm(self, alarm_info: Any = None) -> None:
        await self.alarm_tick()

    async def alarm_tick(self, now: str | None = None) -> dict[str, Any]:
        """Run one tick from the Durable Object alarm (ADR 0005).

        The next alarm is set before the tick runs, so a tick that is cut
        short still leaves the chain in place. The slow alarm goes first, so
        even a failed running-visit check leaves one.
        """
        tick_time = _datetime(now)
        await self._set_alarm(tick_time + IDLE_ALARM_DELAY)
        if await self._repository().has_running_visit():
            await self._set_alarm(tick_time + ACTIVE_ALARM_DELAY)
        return await self.scheduled_tick(now)

    async def ensure_alarm(self, now: str | None = None) -> None:
        """Watchdog for the Cron (ADR 0005): restore a missing alarm, never tick.

        It touches only this object's alarm, so a Worker invocation cut short
        while calling it cannot leave D1 or a tick half done.
        """
        if await self.ctx.storage.getAlarm() is None:
            await self._set_alarm(_datetime(now))

    async def _set_alarm(self, at: datetime, *, only_if_earlier: bool = False) -> None:
        due = _epoch_ms(at)
        current = await self.ctx.storage.getAlarm() if only_if_earlier else None
        if current is None or current > due:
            await self.ctx.storage.setAlarm(due)

    async def scheduled_tick(self, now: str | None = None) -> dict[str, Any]:
        result = await self._scheduled_tick(_datetime(now), now is not None)
        print(json.dumps({"event": "scheduled_tick", **result}))
        return result

    async def _scheduled_tick(
        self, tick_time: datetime, fixed_clock: bool
    ) -> dict[str, Any]:
        async with self._lock:
            # A recovery hold freezes everything the ledger covers until the
            # captain reconciles; expired drafts are outside it and still go.
            if await self._recovery_held():
                return _held_result(await self._delete_expired_drafts(tick_time))
            if not await self._check_ledger():
                return {
                    **_held_result(await self._delete_expired_drafts(tick_time)),
                    "reason": "d1_ledger_mismatch",
                }
            clock = (
                (lambda: tick_time)
                if fixed_clock
                else lambda: datetime.now(timezone.utc)
            )
            scheduler = self._scheduler(clock)
            cleaned = await scheduler.run_lifecycle(tick_time)
            await self._save_ledger()
            if not local_test_mode(self.env):
                # Send hold: nothing below may read a hospital or call LINE.
                return _held_result(cleaned)
            plan = await scheduler.prepare_tick(tick_time)
            await self._save_ledger()

        result = {**_plan_result(plan), **asdict(cleaned)}
        for event_id in plan.event_ids:
            async with self._lock:
                if await self._held():
                    break
                if not await self._check_ledger():
                    break
                outcome = await scheduler.send_event(
                    event_id,
                    before_request=self._before_request,
                )
                if outcome.started:
                    result["requests_started"] += 1
                    result[outcome.outcome] += 1
                if not outcome.settled:
                    await self.ctx.storage.put("recovery_hold", True)
                    result["held"] = True
                    result["reason"] = "outbox_settlement_missing"
                    break
                if outcome.started:
                    if not await self._request_ledger_matches(event_id):
                        await self.ctx.storage.put("recovery_hold", True)
                        await self.ctx.storage.put(
                            "recovery_hold_reason", "d1_ledger_changed_during_send"
                        )
                        result["held"] = True
                        result["reason"] = "d1_ledger_changed_during_send"
                        break
                await self._clear_request_context()
                await self._save_ledger()
                if await self._repository().finalize_stopping(
                    datetime.now(timezone.utc)
                ):
                    await self._save_ledger()
        return result

    async def stop_visit(self, visit_id: str, now: str | None = None) -> str | None:
        timestamp = _datetime(now)
        async with self._stop_transition_lock:
            event_id = await self.ctx.storage.get("inflight_event_id")
            repository = self._repository()
            if event_id and await repository.event_is_in_flight_for_visit(
                str(event_id), visit_id
            ):
                if not await self._check_ledger():
                    return "scheduler_held"
                await self.ctx.storage.put("inflight_stop_visit_id", visit_id)
                if await repository.stop_while_event_is_in_flight(visit_id):
                    await self._save_ledger()
                    return "stopping"

        async with self._lock:
            repository = self._repository()
            await self._check_ledger()
            await repository.recover_in_flight_events(timestamp)
            visit = await repository.get_visit(visit_id)
            if visit is None:
                return None
            if visit["state"] not in {"active", "stopping", "stopped"}:
                return "invalid_lifecycle_state"
            state = await repository.stop(visit_id, timestamp)
            await self._save_ledger()
            return state

    async def update_draft(
        self,
        visit_id: str,
        *,
        hospital: str,
        visit_day: date,
        department_code: str,
        clinic_code: str,
        clinic_session: str,
        patient_number: int,
        recipient_ids: Sequence[str],
        now: datetime,
    ) -> bool:
        async with self._lock:
            return await self._repository().update_draft(
                visit_id=visit_id,
                hospital=hospital,
                visit_day=visit_day,
                department_code=department_code,
                clinic_code=clinic_code,
                clinic_session=clinic_session,
                patient_number=patient_number,
                recipient_ids=recipient_ids,
                now=now,
            )

    async def update_draft_rpc(self, request_json: str) -> bool:
        """Decode the primitive Worker RPC envelope before updating a draft."""
        request = json.loads(request_json)
        return await self.update_draft(
            visit_id=str(request["visit_id"]),
            hospital=str(request["hospital"]),
            visit_day=date.fromisoformat(str(request["visit_day"])),
            department_code=str(request["department_code"]),
            clinic_code=str(request["clinic_code"]),
            clinic_session=str(request["clinic_session"]),
            patient_number=int(request["patient_number"]),
            recipient_ids=tuple(str(value) for value in request["recipient_ids"]),
            now=_datetime(str(request["now"])),
        )

    async def add_visit_recipient(
        self, visit_id: str, recipient_id: str, now: datetime
    ) -> bool:
        async with self._lock:
            return await self._repository().add_recipient(visit_id, recipient_id, now)

    async def start_visit(
        self, visit_id: str, now: str | None = None
    ) -> dict[str, Any]:
        """Start only after the gate obtains a fresh trusted exact-scope sample.

        A visit_date in the past is refused first. Then the hospital's source
        capability decides the path. A full-schedule hospital is asked through
        `match_clinic` whether the draft is on its clinic schedule; the
        reader's answer (matched, not scheduled, cancelled, not yet published,
        unavailable) maps to the Start result, and a matched same-day draft
        gets the canonical clinic_code the reader returns. A current-number-only
        hospital has no schedule, so it skips that check and is refused on any
        day before the visit day, with nothing stored. Future-dated drafts that
        match transition to active without a live observation; the scheduler
        polls them on visit day. A started visit brings the next alarm within a
        minute, so the reader's cadence starts now (ADR 0005). While any other
        visit is active or stopping, Start is refused first with
        `another_visit_running` and stores nothing.
        """
        timestamp = _datetime(now)
        result = await self._start_visit(visit_id, timestamp)
        if result.get("state") == "active":
            await self._set_alarm(timestamp + ACTIVE_ALARM_DELAY, only_if_earlier=True)
        return result

    async def _start_visit(self, visit_id: str, timestamp: datetime) -> dict[str, Any]:
        async with self._lock:
            repository = self._repository()
            visit = await repository.get_visit(visit_id)
            if visit is None:
                return {"error": "visit_not_found"}
            if visit["state"] != "draft":
                return {"error": "invalid_lifecycle_state"}
            # One running visit at a time (#172): the tick is not split per
            # visit yet, so a second one would exceed the Free plan CPU limit.
            # Checked under the gate lock before anything is read or stored.
            if await repository.has_other_running_visit(visit_id):
                return {"error": "another_visit_running"}
            visit_date = date.fromisoformat(str(visit["visit_date"]))
            today = timestamp.astimezone(TAIPEI).date()
            if visit_date < today:
                await repository.set_source_read(
                    visit_id, "scope_mismatch", "scope_mismatch"
                )
                return {"error": "visit_date_past"}
            if timestamp >= visit_cutoff(visit_date):
                return {"error": "invalid_lifecycle_state"}
            if not await self._check_ledger():
                return {"error": "scheduler_held"}
            reader = self._hospital_reader()
            if reader is None:
                await repository.set_source_read(
                    visit_id, "unavailable", "no_observation"
                )
                return {"error": "observation_unavailable"}

            current_number_only = (
                isinstance(reader, RegistryHospitalReader)
                and capability_of(str(visit["hospital"]))
                is SourceCapability.CURRENT_NUMBER_ONLY
            )
            # Set once the hospital's own clinic schedule or roster has named
            # the visit's clinic, which is what lets Start wait for the first
            # number instead of refusing.
            clinic_identified = False
            substitute_doctor = False
            if current_number_only:
                # No clinic schedule exists to check against, so the hospital can
                # confirm the clinic only on the visit day. The backend decides
                # what today is; a refusal here changes nothing.
                if visit_date > today:
                    return {
                        "error": "start_on_visit_day_only",
                        "visit_date": visit_date.isoformat(),
                    }
                clinic_code = str(visit["clinic_code"])
            elif isinstance(reader, RegistryHospitalReader):
                preflight = await self._preflight_validate(
                    repository, visit_id, visit, visit_date, reader, timestamp
                )
                if "error" in preflight:
                    return preflight
                clinic_code = preflight["clinic_code"]
                clinic_identified = True
                substitute_doctor = bool(preflight.get("substitute_doctor"))
                if visit_date > today:
                    if not await repository.start(visit_id, timestamp):
                        return {"error": "ineligible_recipients"}
                    await repository.set_source_read(
                        visit_id, "unavailable", "no_observation"
                    )
                    await self._save_ledger()
                    return {"state": "active"}
            else:
                # Local-test stub readers have no live schedule; pre-flight is
                # skipped and the authoritative gate stays observe_for_start.
                clinic_code = str(visit["clinic_code"])

            try:
                scope = ClinicScope(
                    hospital=str(visit["hospital"]),
                    visit_date=visit_date,
                    department_code=str(visit["department_code"]),
                    clinic_code=clinic_code,
                    session=ClinicSession(str(visit["clinic_session"])),
                    doctor_code=str(visit["doctor_code"])
                    if visit.get("doctor_code")
                    else None,
                    room_code=str(visit["room_code"])
                    if visit.get("room_code")
                    else None,
                )
            except (ValueError, TypeError, KeyError):
                await repository.set_source_read(visit_id, "invalid", "invalid_data")
                return {"error": "observation_invalid"}
            observation = await reader.observe_for_start(scope, timestamp)
            if (
                clinic_identified
                and isinstance(observation, ReadSkipped)
                and observation.reason in {"clinic_not_started", "unobserved_situation"}
            ):
                # The card is identified; waiting for its first number is the
                # reader's job, so Start is accepted and the visit runs once the
                # clinic calls. A situation no one has observed yet sends nothing
                # and is recorded by the reader, so it does not refuse Start either.
                if not await repository.start(visit_id, timestamp):
                    return {"error": "ineligible_recipients"}
                await repository.set_source_read(
                    visit_id,
                    *(observation.source_read or ("unavailable", "no_observation")),
                )
                await self._save_ledger()
                return {"state": "active"}
            if isinstance(observation, (ReadSkipped, ReadFailed)):
                status, reason = (
                    (observation.status, observation.reason)
                    if isinstance(observation, ReadFailed)
                    else observation.source_read or ("unavailable", "no_observation")
                )
                await repository.set_source_read(visit_id, status, reason)
                if reason == "ambiguous_match":
                    return {"error": "clinic_ambiguous"}
                if current_number_only:
                    return {"error": _current_number_only_error(observation)}
                return {"error": _START_ERRORS[status]}
            if observation is None:
                await repository.set_source_read(
                    visit_id, "unavailable", "no_observation"
                )
                if current_number_only:
                    return {"error": "hospital_page_unreachable"}
                return {"error": "observation_unavailable"}
            try:
                observed_at = _datetime(observation.observed_at)
            except (AttributeError, TypeError, ValueError):
                await repository.set_source_read(visit_id, "invalid", "invalid_data")
                return {"error": "observation_invalid"}
            if observed_at > timestamp or timestamp - observed_at > timedelta(
                minutes=2
            ):
                await repository.set_source_read(visit_id, "stale", "stale_sample")
                return {"error": "observation_stale"}
            if observation.scope != scope:
                await repository.set_source_read(
                    visit_id, "scope_mismatch", "scope_mismatch"
                )
                return {"error": "observation_scope_mismatch"}
            if (
                not observation.trustworthy_current
                or isinstance(observation.current_number, bool)
                or not isinstance(observation.current_number, int)
                or observation.current_number < 1
            ):
                await repository.set_source_read(
                    visit_id, "untrusted", "untrusted_source"
                )
                return {"error": "observation_untrusted"}
            if not await repository.start(visit_id, timestamp):
                return {"error": "ineligible_recipients"}
            await repository.update_observation(
                visit_id,
                current_number=observation.current_number,
                observed_at=observed_at,
                consecutive_unusable_reads=0,
            )
            await repository.set_source_read(
                visit_id,
                "usable",
                "substitute_doctor"
                if observation.substitute_doctor or substitute_doctor
                else "none",
            )
            await self._save_ledger()
            return {"state": "active"}

    async def _preflight_validate(
        self,
        repository: VisitRepository,
        visit_id: str,
        visit: Mapping[str, Any],
        visit_date: date,
        reader: HospitalReader,
        timestamp: datetime,
    ) -> dict[str, Any]:
        """Pre-flight checks before Start admits a draft to monitoring.

        Returns `{"clinic_code": "..."}` on success (the clinic_code may have
        been rewritten by the resolve step), or `{"error": "..."}` with one
        of the Issue #58 error codes.
        """
        # `start_visit`, the only caller, has already refused a past visit date
        # with the same timestamp, so the visit day here is today or later.
        today = timestamp.astimezone(TAIPEI).date()

        try:
            hospital_enum = str(visit["hospital"])
            session_enum = ClinicSession(str(visit["clinic_session"]))
        except (ValueError, TypeError, KeyError):
            await repository.set_source_read(visit_id, "invalid", "invalid_data")
            return {"error": "observation_invalid"}

        clinic_code = str(visit["clinic_code"])

        match = await reader.match_clinic(
            MatchQuery(
                hospital=hospital_enum,
                department_code=str(visit["department_code"]),
                visit_date=visit_date,
                session=session_enum,
                clinic_code=clinic_code,
            ),
            timestamp,
        )
        if match.kind is MatchKind.NOT_YET_PUBLISHED:
            # Nothing to check against yet: the draft is valid and merely
            # early, so it is kept unchanged (ticket #101), matching the sweep.
            refusal: dict[str, Any] = {"error": "visit_date_out_of_schedule_window"}
            if match.schedule_end is not None:
                refusal["schedule_end"] = match.schedule_end.isoformat()
            if match.release_time is not None:
                refusal["release_time"] = match.release_time.isoformat()
            return refusal
        if match.kind in (MatchKind.NOT_SCHEDULED, MatchKind.CANCELLED):
            await repository.set_source_read(
                visit_id, "scope_mismatch", "scope_mismatch"
            )
            return {"error": "doctor_not_scheduled"}
        if match.kind is MatchKind.NOT_APPLICABLE:
            # Start has no schedule to consult for this hospital, so it cannot
            # admit the draft: fail closed like any unavailable schedule.
            await repository.set_source_read(visit_id, "unavailable", "no_observation")
            return {"error": "schedule_unavailable"}
        if match.kind is MatchKind.UNAVAILABLE:
            if match.reason == "visit_date_past":
                await repository.set_source_read(
                    visit_id, "scope_mismatch", "scope_mismatch"
                )
                return {"error": "visit_date_past"}
            if match.reason == "scope_mismatch":
                await repository.set_source_read(
                    visit_id, "scope_mismatch", "scope_mismatch"
                )
                return {"error": "observation_scope_mismatch"}
            if match.reason == "invalid_data":
                await repository.set_source_read(visit_id, "invalid", "invalid_data")
                return {"error": "observation_invalid"}
            if match.reason == "ambiguous_match":
                # Several of the day's cards fit, so no card is guessed.
                await repository.set_source_read(visit_id, "invalid", "ambiguous_match")
                return {"error": "clinic_ambiguous"}
            source_reason_map = {
                "no_observation": "no_observation",
                "schema_drift": "schema_drift",
                "schema": "schema_drift",
                "access_denied": "access_denied",
                "timeout": "timeout",
                "challenge": "access_denied",
                "denied": "access_denied",
            }
            source_reason = source_reason_map.get(match.reason, "no_observation")
            await repository.set_source_read(visit_id, "unavailable", source_reason)
            return {"error": "schedule_unavailable"}

        if (
            visit_date == today
            and match.clinic_code
            and match.clinic_code != clinic_code
        ):
            await repository.update_clinic_code(visit_id, match.clinic_code)
            clinic_code = match.clinic_code
        return {
            "clinic_code": clinic_code,
            "substitute_doctor": match.substitute_doctor,
        }

    async def correct_stopped_visit(
        self,
        visit_id: str,
        *,
        hospital: str,
        visit_day: date,
        department_code: str,
        clinic_code: str,
        clinic_session: str,
        patient_number: int,
        recipient_ids: tuple[str, ...],
    ) -> bool:
        """Reopen a stopped or expired logical series without resetting alert history."""
        async with self._lock:
            repository = self._repository()
            if not await self._check_ledger():
                return False
            visit = await repository.get_visit(visit_id)
            if visit is None or visit["state"] not in {"stopped", "expired"}:
                return False
            existing = await repository.selected_recipient_ids(visit_id)
            selected = set(recipient_ids)
            # First Start freezes additions. Corrections can narrow the roster while
            # retaining each selected recipient's prior event uniqueness rows.
            if not selected or not selected.issubset(existing):
                return False
            if not await repository.prepare_correction(visit_id):
                return False
            if not await repository.correct_clinic(
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
            for recipient_id in existing - selected:
                await repository.remove_recipient(visit_id, recipient_id)
                await repository.erase_removed_recipient_events(visit_id, recipient_id)
            await repository.set_source_read(visit_id, "unavailable", "no_observation")
            await self._save_ledger()
            return True

    async def correct_stopped_visit_rpc(self, request_json: str) -> bool:
        """Decode the primitive Worker RPC envelope before correcting a visit."""
        request = json.loads(request_json)
        return await self.correct_stopped_visit(
            visit_id=str(request["visit_id"]),
            hospital=str(request["hospital"]),
            visit_day=date.fromisoformat(str(request["visit_day"])),
            department_code=str(request["department_code"]),
            clinic_code=str(request["clinic_code"]),
            clinic_session=str(request["clinic_session"]),
            patient_number=int(request["patient_number"]),
            recipient_ids=tuple(str(value) for value in request["recipient_ids"]),
        )

    async def remove_visit_recipient(
        self, visit_id: str, recipient_id: str, now: str | None = None
    ) -> bool:
        async with self._lock:
            timestamp = _datetime(now)
            repository = self._repository()
            await self._check_ledger()
            await repository.recover_in_flight_events(timestamp)
            removed = await repository.remove_recipient(visit_id, recipient_id)
            if removed:
                await repository.erase_removed_recipient_events(visit_id, recipient_id)
            await self._save_ledger()
            return removed

    async def withdraw_recipient(
        self, recipient_id: str, now: str | None = None
    ) -> bool:
        async with self._lock:
            timestamp = _datetime(now)
            repository = self._repository()
            await self._check_ledger()
            await repository.recover_in_flight_events(timestamp)
            withdrawn = await repository.withdraw_recipient(recipient_id)
            await self._save_ledger()
            return withdrawn

    async def hold_for_reconciliation(self) -> bool:
        async with self._lock:
            timestamp = datetime.now(timezone.utc)
            await self._check_ledger()
            await self._repository().recover_in_flight_events(timestamp)
            await self._save_ledger()
            await self.ctx.storage.put("recovery_hold", True)
            return True

    async def resume_after_reconciliation(self, reconciled: bool) -> bool:
        if reconciled is not True or not local_test_mode(self.env):
            return False
        async with self._lock:
            if not await self._held():
                return False
            await self._save_ledger()
            await self._clear_request_context()
            await self.ctx.storage.put("recovery_hold", False)
            await self.ctx.storage.put("recovery_hold_reason", "")
            await self.ctx.storage.put(
                "reconciled_at", datetime.now(timezone.utc).isoformat()
            )
            return True

    async def correct_test_watch(
        self,
        visit_id: str,
        visit_day: str,
        patient_number: int,
        now: str,
    ) -> bool:
        self._require_test_mode()
        async with self._lock:
            timestamp = _datetime(now)
            repository = self._repository()
            if not await self._check_ledger():
                return False
            await repository.recover_in_flight_events(timestamp)
            if await repository.stop(visit_id, timestamp) != "stopped":
                return False
            if not await repository.prepare_correction(visit_id):
                return False
            if not await repository.correct_clinic(
                visit_id=visit_id,
                hospital="ntuh-main",
                visit_day=datetime.fromisoformat(visit_day).date(),
                department_code="SYN",
                clinic_code="SYN-2",
                clinic_session="afternoon",
                patient_number=patient_number,
                doctor_code="SYN-DOC-2",
                room_code="SYN-ROOM-2",
            ):
                return False
            started = await repository.start(visit_id, timestamp)
            await self._save_ledger()
            return started

    async def restore_test_state(self) -> bool:
        self._require_test_mode()
        store = CloudflareD1Store(_field(self.env, "DB"))
        await store.execute(Statement("DELETE FROM outbound_events"))
        return True

    async def recovery_held(self) -> bool:
        return await self._held()

    async def sending_interrupted(self) -> bool:
        # A send interruption is the recovery hold only. An environment that is
        # not live yet is held by configuration and is not an interruption.
        return await self._recovery_held()

    async def scheduler_status(self) -> dict[str, bool]:
        recovery_hold = (await self.ctx.storage.get("recovery_hold")) is True
        configuration_hold = not local_test_mode(self.env)
        return {
            "held": configuration_hold or recovery_hold,
            "configuration_hold": configuration_hold,
            "recovery_hold": recovery_hold,
            "hospital_reader_available": self._hospital_reader() is not None,
        }

    async def _delete_expired_drafts(self, now: datetime) -> LifecycleCounts:
        return LifecycleCounts(
            drafts_deleted=await self._repository().delete_expired_drafts(now)
        )

    async def _recovery_held(self) -> bool:
        return (await self.ctx.storage.get("recovery_hold")) is True

    async def _held(self) -> bool:
        # Issue #18 is a held service bootstrap. Only the synthetic local
        # rehearsal can send; a token or resume request cannot release production.
        return (
            not local_test_mode(self.env)
            or (await self.ctx.storage.get("recovery_hold")) is True
        )

    async def _check_ledger(self) -> bool:
        digest = await self._repository().scheduler_ledger_digest()
        stored = await self.ctx.storage.get("scheduler_ledger_digest")
        if stored is None:
            await self.ctx.storage.put("scheduler_ledger_digest", digest)
            return True
        if str(stored) != digest:
            await self.ctx.storage.put("recovery_hold", True)
            await self.ctx.storage.put("recovery_hold_reason", "d1_ledger_mismatch")
            return False
        return True

    async def _before_request(self, event_id: str) -> None:
        await self._save_ledger()
        digest = await self._repository().scheduler_ledger_digest(
            exclude_event_id=event_id
        )
        await self.ctx.storage.put("inflight_event_id", event_id)
        await self.ctx.storage.put("inflight_context_digest", digest)
        await self.ctx.storage.put("inflight_stop_visit_id", "")

    async def _request_ledger_matches(self, event_id: str) -> bool:
        stored_event_id = await self.ctx.storage.get("inflight_event_id")
        stored_digest = await self.ctx.storage.get("inflight_context_digest")
        if stored_event_id != event_id or not stored_digest:
            return False
        allowed_stopping_visit_id = await self.ctx.storage.get("inflight_stop_visit_id")
        current_digest = await self._repository().scheduler_ledger_digest(
            exclude_event_id=event_id,
            allow_stopping_visit_id=(
                str(allowed_stopping_visit_id) if allowed_stopping_visit_id else None
            ),
        )
        return str(stored_digest) == current_digest

    async def _clear_request_context(self) -> None:
        await self.ctx.storage.put("inflight_event_id", "")
        await self.ctx.storage.put("inflight_context_digest", "")
        await self.ctx.storage.put("inflight_stop_visit_id", "")

    async def _save_ledger(self) -> None:
        digest = await self._repository().scheduler_ledger_digest()
        await self.ctx.storage.put("scheduler_ledger_digest", digest)

    def _repository(self) -> VisitRepository:
        binding = _field(self.env, "DB")
        if binding is None:
            raise RuntimeError("D1 binding is unavailable")
        return VisitRepository(CloudflareD1Store(binding))

    def _hospital_reader(self) -> HospitalReader | None:
        """Production stays without a hospital reader until the Issue #22 pilot."""
        if not local_test_mode(self.env):
            return None
        if str(_field(self.env, "NTUH_READER_ENABLED", "")) == "1":
            return RegistryHospitalReader(
                ReaderDeps(storage=self.ctx.storage, fetch=self._ntuh_fetcher)
            )
        return _TestHospitalReader(self.ctx.storage)

    async def list_clinics(
        self, hospital: str, department_code: str, visit_date: str, now: str
    ) -> dict[str, Any]:
        """Serve the setup picker a department's clinics for a day, or why not.

        Held the same way reads are: with no reader (production before the Issue
        #22 pilot) the roster is simply unavailable, so the picker degrades to
        manual entry. Arguments and the result stay JSON-friendly for the gate's
        RPC boundary.
        """
        reader = self._hospital_reader()
        lister = getattr(reader, "list_clinics", None)
        if lister is None:
            return {"available": False, "reason": "no_observation", "clinics": []}
        try:
            query = RosterQuery(
                hospital=require_registered(hospital),
                department_code=department_code,
                visit_date=date.fromisoformat(visit_date),
            )
            when = _datetime(now)
        except (ValueError, TypeError):
            return {"available": False, "reason": "invalid_data", "clinics": []}
        roster: ClinicRoster = await lister(query, when)
        result: dict[str, Any] = {
            "available": roster.available,
            "reason": roster.reason,
            "clinics": [
                {
                    "session": option.session.value,
                    "room": option.room,
                    "doctor": option.doctor,
                    "clinic_type": option.clinic_type,
                    "clinic_code": option.clinic_code,
                    "label": option.label,
                    "details": [
                        {"label": name, "value": value}
                        for name, value in option.details
                    ],
                }
                for option in roster.clinics
            ],
        }
        # Optional fields, present only when the reader states them for a day
        # the hospital has not published yet.
        if roster.schedule_end is not None:
            result["schedule_end"] = roster.schedule_end.isoformat()
        if roster.release_time is not None:
            result["release_time"] = roster.release_time.isoformat()
        return result

    _ntuh_fetcher = WorkersFetcher()

    def _scheduler(self, clock) -> OutboxScheduler:
        test_mode = local_test_mode(self.env)
        hospital = self._hospital_reader()
        if test_mode:
            line = LinePushClient(
                "local-test-only-token",
                _TestLineTransport(self),
            )
        else:
            token = str(_field(self.env, "LINE_CHANNEL_ACCESS_TOKEN", ""))
            line = LinePushClient(token) if token else None
        return OutboxScheduler(
            self._repository(),
            hospital,
            line,
            clock,
        )

    async def set_test_observation(
        self,
        current_number: int | None,
        trustworthy: bool = True,
        progress: dict[str, Any] | None = None,
    ) -> bool:
        """Script the local synthetic observation, progress fields included.

        `progress` takes the observation's own progress fields by name:
        highest_called_number, current_flag, check_in_order, check_in_position,
        called_in_session, expected `[[number, kind, position]]` and numbers
        `[[number, state, position]]`.
        """
        self._require_test_mode()
        await self.ctx.storage.put("test_progress", json.dumps(progress or {}))
        await self.ctx.storage.put(
            "test_current_number", current_number if current_number is not None else -1
        )
        await self.ctx.storage.put("test_trustworthy", trustworthy)
        return True

    async def set_test_line_mode(self, mode: str) -> bool:
        self._require_test_mode()
        if mode not in {"accepted", "failed", "unknown", "wait", "crash_once"}:
            raise ValueError("unknown test LINE mode")
        self._test_request_started.clear()
        self._test_request_release.clear()
        await self.ctx.storage.put("test_line_mode", mode)
        return True

    async def wait_test_request_started(self) -> bool:
        self._require_test_mode()
        await self._test_request_started.wait()
        return True

    async def release_test_request(self) -> bool:
        self._require_test_mode()
        self._test_request_release.set()
        return True

    async def seed_pending_test_recipient(self, recipient_id: str, now: str) -> str:
        """Create a recipient who joined by invitation but has not consented yet."""
        self._require_test_mode()
        timestamp = _datetime(now).isoformat().replace("+00:00", "Z")
        subject = "U" + hashlib.sha256(recipient_id.encode()).hexdigest()[:32]
        store = CloudflareD1Store(_field(self.env, "DB"))
        await store.execute(
            Statement(
                """INSERT OR IGNORE INTO recipients (
                    id, line_subject, display_name, consented_at,
                    friendship_checked_at, active, created_at
                ) VALUES (?, ?, 'Synthetic joiner', NULL, ?, 0, ?)""",
                (recipient_id, subject, timestamp, timestamp),
            )
        )
        return subject

    async def seed_test_visit(
        self,
        visit_id: str,
        recipient_id: str,
        visit_day: str,
        patient_number: int,
        now: str,
    ) -> bool:
        self._require_test_mode()
        timestamp = _datetime(now)
        if not await self._check_ledger():
            return False
        store = CloudflareD1Store(_field(self.env, "DB"))
        await store.execute(
            Statement(
                """INSERT OR IGNORE INTO recipients (
                    id, line_subject, display_name, consented_at,
                    friendship_checked_at, active, created_at
                ) VALUES (?, ?, 'Synthetic recipient', ?, ?, 1, ?)""",
                (
                    recipient_id,
                    "U" + hashlib.sha256(recipient_id.encode()).hexdigest()[:32],
                    timestamp.isoformat().replace("+00:00", "Z"),
                    timestamp.isoformat().replace("+00:00", "Z"),
                    timestamp.isoformat().replace("+00:00", "Z"),
                ),
            )
        )
        repository = VisitRepository(store)
        day = datetime.fromisoformat(visit_day).date()
        await repository.create_draft(
            visit_id=visit_id,
            hospital="ntuh-main",
            visit_day=day,
            department_code="SYN",
            clinic_code="SYN-1",
            clinic_session="afternoon",
            patient_number=patient_number,
            now=timestamp,
            doctor_code="SYN-DOC",
            room_code="SYN-ROOM",
        )
        await repository.add_recipient(visit_id, recipient_id, timestamp)
        started = await repository.start(visit_id, timestamp)
        await self._save_ledger()
        return started

    async def test_snapshot(self) -> dict[str, Any]:
        self._require_test_mode()
        store = CloudflareD1Store(_field(self.env, "DB"))
        events = await store.fetch_all(
            Statement(
                """SELECT id, visit_id, recipient_id, event_kind, retry_key,
                    payload_json, outcome, attempt_count, first_request_at
                FROM outbound_events ORDER BY created_at, id"""
            )
        )
        return {
            "held": await self._held(),
            "events": [dict(row) for row in events],
            "line_requests": json.loads(
                await self.ctx.storage.get("test_line_requests") or "[]"
            ),
            "last_request_had_outbox": await self.ctx.storage.get(
                "test_last_request_had_outbox"
            ),
        }

    def _require_test_mode(self) -> None:
        if not local_test_mode(self.env):
            raise RuntimeError("local scheduler test controls are disabled")


_START_ERRORS = {
    "unavailable": "observation_unavailable",
    "stale": "observation_stale",
    "scope_mismatch": "observation_scope_mismatch",
    "untrusted": "observation_untrusted",
    "invalid": "observation_invalid",
}


def _current_number_only_error(observation: ReadSkipped | ReadFailed) -> str:
    """Split a refused Start read into "cannot find the clinic" and "unreachable".

    A skipped read means the hospital answered but the clinic is not open yet or
    is over; an empty or mismatched answer means the clinic is not shown. Any
    other unavailable read means the hospital page could not be read.
    """
    if isinstance(observation, ReadSkipped):
        if observation.reason in {"clinic_not_started", "clinic_ended"}:
            return "hospital_cannot_find_clinic"
        return "hospital_page_unreachable"
    if observation.reason in {"empty_result", "scope_mismatch", "ambiguous_match"}:
        return "hospital_cannot_find_clinic"
    if observation.status == "unavailable":
        return "hospital_page_unreachable"
    return _START_ERRORS.get(observation.status, "observation_unavailable")


class _TestHospitalReader:
    def __init__(self, storage: Any) -> None:
        self._storage = storage

    async def observe(self, scope, now):
        from next_is_you.domain import QueueObservation

        from next_is_you.domain import ExpectedCall, NumberStatus

        current_number = await self._storage.get("test_current_number")
        trustworthy = await self._storage.get("test_trustworthy")
        if current_number is None or int(current_number) < 1:
            return None
        progress = json.loads(await self._storage.get("test_progress") or "{}")
        return QueueObservation(
            scope=scope,
            observed_at=now.isoformat(),
            current_number=int(current_number),
            trustworthy_current=trustworthy is True,
            highest_called_number=progress.get("highest_called_number"),
            current_flag=progress.get("current_flag"),
            check_in_order=bool(progress.get("check_in_order", False)),
            check_in_position=progress.get("check_in_position"),
            expected=tuple(ExpectedCall(*e) for e in progress.get("expected", [])),
            numbers=tuple(NumberStatus(*n) for n in progress.get("numbers", [])),
            called_in_session=progress.get("called_in_session"),
        )

    async def observe_for_start(self, scope, now):
        # The test reader makes no distinction between Start and scheduled reads.
        return await self.observe(scope, now)

    async def list_clinics(self, query, now):
        # The stub has no schedule, so the picker falls back to manual entry.
        return ClinicRoster(False, (), "no_observation")


class _TestLineTransport:
    def __init__(self, gate: SystemSendGate) -> None:
        self._gate = gate

    async def post(self, url: str, *, headers: dict[str, str], body: str):
        self._gate._require_test_mode()
        store = CloudflareD1Store(_field(self._gate.env, "DB"))
        matches = await store.fetch_all(
            Statement(
                "SELECT outcome FROM outbound_events WHERE retry_key = ?",
                (headers["X-Line-Retry-Key"],),
            )
        )
        await self._gate.ctx.storage.put("test_last_request_had_outbox", bool(matches))
        history = json.loads(
            await self._gate.ctx.storage.get("test_line_requests") or "[]"
        )
        history.append(
            {
                "retry_key": headers["X-Line-Retry-Key"],
                "body": body,
                "outbox_persisted": bool(matches),
            }
        )
        await self._gate.ctx.storage.put(
            "test_line_requests", json.dumps(history, separators=(",", ":"))
        )
        mode = await self._gate.ctx.storage.get("test_line_mode") or "accepted"
        self._gate._test_request_started.set()
        if mode == "wait":
            await self._gate._test_request_release.wait()
        elif mode == "crash_once":
            await self._gate.ctx.storage.put("test_line_mode", "accepted")
            raise asyncio.CancelledError
        status = {
            "accepted": 200,
            "failed": 400,
            "unknown": 500,
            "wait": 200,
        }[mode]
        return LinePushHttpResponse(status_code=status, request_id="local-test-request")


def local_test_mode(env: Any) -> bool:
    value = _field(env, "NIY006_LOCAL_TEST_MODE", "")
    return str(_field(env, "NIY_ENVIRONMENT", "")) == "local-test" and str(value) == "1"


def _field(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(key, default)
    return getattr(value, key, default) if value is not None else default


def _epoch_ms(value: datetime) -> int:
    return int(value.timestamp() * 1000)


def _datetime(value: str | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("gate timestamps must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _held_result(cleaned: LifecycleCounts) -> dict[str, Any]:
    return {"held": True, **asdict(cleaned)}


def _plan_result(plan: TickPlan) -> dict[str, Any]:
    return {
        "held": False,
        "visits_evaluated": plan.visits_evaluated,
        "events_created": plan.events_created,
        "requests_started": 0,
        "accepted": 0,
        "failed": 0,
        "unknown": 0,
        "closed": plan.closed,
    }
