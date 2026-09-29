"""System-wide Durable Object gate for scheduler and close actions."""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from typing import Any, Mapping, Sequence

from next_is_you.line_messaging import LinePushClient, LinePushHttpResponse
from next_is_you.persistence import (
    CloudflareD1Store,
    Statement,
    VisitRepository,
    visit_cutoff,
)
from next_is_you.domain import ClinicScope, ClinicSession, Hospital
from next_is_you.scheduler import HospitalReader, OutboxScheduler, TickPlan

try:
    from workers import DurableObject as _DurableObjectBase
except ModuleNotFoundError as error:
    if error.name != "js":
        raise

    class _DurableObjectBase:
        def __init__(self, ctx: Any, env: Any) -> None:
            self.ctx = ctx
            self.env = env


class SystemSendGate(_DurableObjectBase):
    """One SQLite-backed Durable Object serializes every send and close action."""

    def __init__(self, ctx: Any, env: Any) -> None:
        super().__init__(ctx, env)
        self._lock = asyncio.Lock()
        self._test_request_started = asyncio.Event()
        self._test_request_release = asyncio.Event()

    async def scheduled_tick(self, now: str | None = None) -> dict[str, Any]:
        tick_time = _datetime(now)
        async with self._lock:
            if await self._held():
                return {"held": True}
            if not await self._check_ledger():
                return {"held": True, "reason": "d1_ledger_mismatch"}
            clock = (
                (lambda: tick_time)
                if now is not None
                else lambda: datetime.now(timezone.utc)
            )
            scheduler = self._scheduler(clock)
            await scheduler.recover(tick_time)
            plan = await scheduler.prepare_tick(tick_time)
            await self._save_ledger()

        result = _plan_result(plan)
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
        return result

    async def stop_visit(self, visit_id: str, now: str | None = None) -> str | None:
        async with self._lock:
            timestamp = _datetime(now)
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

    async def add_visit_recipient(
        self, visit_id: str, recipient_id: str, now: datetime
    ) -> bool:
        async with self._lock:
            return await self._repository().add_recipient(visit_id, recipient_id, now)

    async def start_visit(
        self, visit_id: str, now: str | None = None
    ) -> dict[str, Any]:
        """Start only after the gate obtains a fresh trusted exact-scope sample."""
        timestamp = _datetime(now)
        async with self._lock:
            repository = self._repository()
            visit = await repository.get_visit(visit_id)
            if visit is None:
                return {"error": "visit_not_found"}
            if visit["state"] != "draft":
                return {"error": "invalid_lifecycle_state"}
            if timestamp >= visit_cutoff(date.fromisoformat(str(visit["visit_date"]))):
                return {"error": "invalid_lifecycle_state"}
            if not await self._check_ledger():
                return {"error": "scheduler_held"}
            # No production hospital reader is configured until NIY-004 supplies a
            # verified transport. The local reader exists only under NIY-006 test mode.
            if not _test_mode(self.env):
                await repository.set_source_read(
                    visit_id, "unavailable", "no_observation"
                )
                return {"error": "observation_unavailable"}
            try:
                scope = ClinicScope(
                    hospital=Hospital(str(visit["hospital"])),
                    visit_date=date.fromisoformat(str(visit["visit_date"])),
                    department_code=str(visit["department_code"]),
                    clinic_code=str(visit["clinic_code"]),
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
            observation = await _TestHospitalReader(self.ctx.storage).observe(
                scope, timestamp
            )
            if observation is None:
                await repository.set_source_read(
                    visit_id, "unavailable", "no_observation"
                )
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
            await repository.set_source_read(visit_id, "usable", "none")
            await self._save_ledger()
            return {"state": "active"}

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
        """Reopen a stopped logical series without resetting its alert history."""
        async with self._lock:
            repository = self._repository()
            if not await self._check_ledger():
                return False
            visit = await repository.get_visit(visit_id)
            if visit is None or visit["state"] != "stopped":
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
        if reconciled is not True:
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

    async def _held(self) -> bool:
        return (await self.ctx.storage.get("recovery_hold")) is True

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

    async def _request_ledger_matches(self, event_id: str) -> bool:
        stored_event_id = await self.ctx.storage.get("inflight_event_id")
        stored_digest = await self.ctx.storage.get("inflight_context_digest")
        if stored_event_id != event_id or not stored_digest:
            return False
        current_digest = await self._repository().scheduler_ledger_digest(
            exclude_event_id=event_id
        )
        return str(stored_digest) == current_digest

    async def _clear_request_context(self) -> None:
        await self.ctx.storage.put("inflight_event_id", "")
        await self.ctx.storage.put("inflight_context_digest", "")

    async def _save_ledger(self) -> None:
        digest = await self._repository().scheduler_ledger_digest()
        await self.ctx.storage.put("scheduler_ledger_digest", digest)

    def _repository(self) -> VisitRepository:
        binding = _field(self.env, "DB")
        if binding is None:
            raise RuntimeError("D1 binding is unavailable")
        return VisitRepository(CloudflareD1Store(binding))

    def _scheduler(self, clock) -> OutboxScheduler:
        test_mode = _test_mode(self.env)
        hospital: HospitalReader | None = (
            _TestHospitalReader(self.ctx.storage) if test_mode else None
        )
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
        self, current_number: int | None, trustworthy: bool = True
    ) -> bool:
        self._require_test_mode()
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
        if not _test_mode(self.env):
            raise RuntimeError("local scheduler test controls are disabled")


class _TestHospitalReader:
    def __init__(self, storage: Any) -> None:
        self._storage = storage

    async def observe(self, scope, now):
        from next_is_you.domain import QueueObservation

        current_number = await self._storage.get("test_current_number")
        trustworthy = await self._storage.get("test_trustworthy")
        if current_number is None or int(current_number) < 1:
            return None
        return QueueObservation(
            scope=scope,
            observed_at=now.isoformat(),
            current_number=int(current_number),
            trustworthy_current=trustworthy is True,
        )


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


def _test_mode(env: Any) -> bool:
    value = _field(env, "NIY006_LOCAL_TEST_MODE", "")
    return value is True or str(value) == "1"


def _field(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(key, default)
    return getattr(value, key, default) if value is not None else default


def _datetime(value: str | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("gate timestamps must be timezone-aware")
    return parsed.astimezone(timezone.utc)


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
