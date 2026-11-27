"""One browser journey case for every Start refusal (#146).

`test_start_refusal_journeys.py` presses Start once per case, and
`test_refusal_catalog.py` fails when this list and the backend catalog differ,
so a new Start refusal code needs a case here. A case states what makes the real
backend answer with its code and the text the organizer must then read.

`journey` is the in-process harness of
`test_local_acceptance_hospital_fallbacks.py`. This module does not import it,
so the catalog test runs without the browser tooling.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from typing import Any, Callable

from next_is_you.domain import (
    ClinicMatch,
    ClinicScope,
    MatchKind,
    QueueObservation,
    ReadFailed,
)
from next_is_you.hospital_registry import HospitalEntry
from next_is_you.persistence import VisitRepository
from synthetic_hospital import (
    FULL_SCHEDULE_ID,
    SCRIPTED_SCHEDULE_NAME,
    SYNTHETIC_ID,
    Result,
    SyntheticSource,
    scripted_schedule_entry,
    synthetic_entry,
)

DRAFT_ID = "draft-under-test"
RUNNING_ID = "visit-already-running"
RECIPIENT_ID = "selected-family"
CLINIC_CODE = "A-12"

YESTERDAY = date(2026, 9, 26)
TODAY = date(2026, 9, 27)
TOMORROW = date(2026, 9, 28)
UNPUBLISHED_DAY = date(2026, 10, 20)
# 21:01 in Taipei on TODAY.
NOW = datetime.fromisoformat("2026-09-27T13:01:00+00:00")
# 23:59 in Taipei on TODAY, when the day's visits close.
CUTOFF = datetime.fromisoformat("2026-09-27T15:59:00+00:00")

MATCHED = ClinicMatch(MatchKind.MATCHED, clinic_code=CLINIC_CODE)


def usable_read(scope: ClinicScope, now: datetime) -> QueueObservation:
    return QueueObservation(scope, now.isoformat(), 70, trustworthy_current=True)


def full_schedule_registration(
    match: ClinicMatch = MATCHED,
    read: Callable[[ClinicScope, datetime], Result] = usable_read,
) -> tuple[str, HospitalEntry]:
    return FULL_SCHEDULE_ID, scripted_schedule_entry(match, read)


def current_number_only_registration(
    outcome: int | None | Exception,
) -> tuple[str, HospitalEntry]:
    return SYNTHETIC_ID, synthetic_entry(SyntheticSource(outcome))


async def seed_draft(journey: Any, visit_id: str, case: StartRefusalCase) -> None:
    visits = VisitRepository(journey.database)
    await visits.create_draft(
        visit_id=visit_id,
        hospital=case.hospital[0],
        visit_day=case.visit_day,
        department_code="OPH",
        clinic_code=CLINIC_CODE,
        clinic_session="afternoon",
        patient_number=85,
        now=case.now,
    )
    assert await visits.add_recipient(visit_id, RECIPIENT_ID, case.now)


def another_visit_is_running(journey: Any, case: StartRefusalCase) -> None:
    async def run_another() -> None:
        await seed_draft(journey, RUNNING_ID, case)
        assert await VisitRepository(journey.database).start(RUNNING_ID, case.now)

    asyncio.run(run_another())


@dataclass(frozen=True, kw_only=True)
class StartRefusalCase:
    code: str
    text: str
    # The hospital's registry id and entry, registered for this case only.
    hospital: tuple[str, HospitalEntry] = full_schedule_registration()
    visit_day: date = TOMORROW
    now: datetime = NOW
    # What else is true before the page is opened.
    arrange: Callable[[Any, StartRefusalCase], None] = lambda journey, case: None
    # What changes after the page is open, just before Start is pressed.
    before_press: Callable[[Any], None] = lambda journey: None


START_REFUSAL_CASES: tuple[StartRefusalCase, ...] = (
    StartRefusalCase(
        code="service_unavailable",
        text="目前無法使用提醒服務。",
        # Not before the page opens: signing in needs the gate too.
        before_press=lambda journey: journey.unbind_gate(),
    ),
    StartRefusalCase(
        code="visit_not_found",
        text="找不到這筆提醒，請重新載入。",
        # A visit deleted for real leaves no card once the page reloads the
        # list, so only the gate loses it and the card stays to show the text.
        arrange=lambda journey, case: journey.hide_visits_from_gate(),
    ),
    StartRefusalCase(
        code="invalid_lifecycle_state",
        text="提醒狀態已變更，請重新載入。",
        visit_day=TODAY,
        now=CUTOFF,
    ),
    StartRefusalCase(
        code="another_visit_running",
        # The second sentence is the link to the running visit's card.
        text="目前已有一個看診在監控中，請先停止它再開始這一個。 前往監控中的看診",
        arrange=another_visit_is_running,
    ),
    StartRefusalCase(
        code="ineligible_recipients",
        text="通知對象已無法接收提醒，請重新選擇。",
        arrange=lambda journey, case: journey.deactivate_recipient(),
    ),
    StartRefusalCase(
        code="scheduler_held",
        text="排程暫停中，提醒維持草稿。",
        arrange=lambda journey, case: journey.diverge_send_record(),
    ),
    StartRefusalCase(
        code="visit_date_past",
        text="看診日期已過，請選擇今天或之後的日期。",
        visit_day=YESTERDAY,
    ),
    # The clinic schedule's answers.
    StartRefusalCase(
        code="clinic_ambiguous",
        text="院方今天有多個門診符合，系統不猜，不會發提醒。請重新選擇門診。",
        hospital=full_schedule_registration(
            ClinicMatch(MatchKind.UNAVAILABLE, reason="ambiguous_match")
        ),
    ),
    StartRefusalCase(
        code="doctor_not_scheduled",
        text="所選醫師在那天並沒有看診，請重新選擇醫師或日期。",
        hospital=full_schedule_registration(ClinicMatch(MatchKind.NOT_SCHEDULED)),
    ),
    StartRefusalCase(
        code="schedule_unavailable",
        text="暫時無法驗證醫師排班（院方頁回應異常），請稍後再試。",
        hospital=full_schedule_registration(
            ClinicMatch(MatchKind.UNAVAILABLE, reason="timeout")
        ),
    ),
    StartRefusalCase(
        code="visit_date_out_of_schedule_window",
        text=(
            f"{SCRIPTED_SCHEDULE_NAME} 目前只公布到 10/11 的門診表。"
            "10/20 的門診表預計 10/13 00:00 公布，公布後系統會自動核對你存的草稿。"
        ),
        hospital=full_schedule_registration(
            ClinicMatch(
                MatchKind.NOT_YET_PUBLISHED,
                schedule_end=date(2026, 10, 11),
                release_time=datetime.fromisoformat("2026-10-13T00:00:00+08:00"),
            )
        ),
        visit_day=UNPUBLISHED_DAY,
    ),
    # The visit-day clinic read of a full-schedule hospital.
    StartRefusalCase(
        code="observation_unavailable",
        text="目前沒有可用的可信院方觀察，提醒維持草稿。",
        hospital=full_schedule_registration(
            read=lambda scope, now: ReadFailed("unavailable", "timeout")
        ),
        visit_day=TODAY,
    ),
    StartRefusalCase(
        code="observation_stale",
        text="院方觀察已過期，提醒維持草稿。",
        hospital=full_schedule_registration(
            read=lambda scope, now: usable_read(scope, now - timedelta(minutes=3))
        ),
        visit_day=TODAY,
    ),
    StartRefusalCase(
        code="observation_scope_mismatch",
        text="院方觀察與所選診次不符，提醒維持草稿。",
        hospital=full_schedule_registration(
            read=lambda scope, now: usable_read(replace(scope, clinic_code="B-34"), now)
        ),
        visit_day=TODAY,
    ),
    StartRefusalCase(
        code="observation_untrusted",
        text="院方資料尚未通過可信度檢查，提醒維持草稿。",
        hospital=full_schedule_registration(
            read=lambda scope, now: replace(
                usable_read(scope, now), trustworthy_current=False
            )
        ),
        visit_day=TODAY,
    ),
    StartRefusalCase(
        code="observation_invalid",
        text="院方資料無效，提醒維持草稿。",
        hospital=full_schedule_registration(
            read=lambda scope, now: replace(
                usable_read(scope, now), observed_at="not a time"
            )
        ),
        visit_day=TODAY,
    ),
    # A hospital that publishes only the current number.
    StartRefusalCase(
        code="start_on_visit_day_only",
        text="這家醫院沒有公布門診表，9/28 看診當天才能開始。",
        hospital=current_number_only_registration(7),
    ),
    StartRefusalCase(
        code="hospital_cannot_find_clinic",
        text="院方目前查不到這個診。如果還沒開診，請開診後再試；否則請核對診間代碼。",
        hospital=current_number_only_registration(None),
        visit_day=TODAY,
    ),
    StartRefusalCase(
        code="hospital_page_unreachable",
        text="暫時讀不到院方資料，請稍後再試。",
        hospital=current_number_only_registration(TimeoutError()),
        visit_day=TODAY,
    ),
)
