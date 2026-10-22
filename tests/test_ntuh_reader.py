"""NTUH reader behavior against fixture pages only; nothing here reaches the network."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path

import pytest

from next_is_you.domain import (
    ClinicScope,
    ClinicSession,
    Hospital,
    QueueObservation,
    ReadFailed,
    ReadSkipped,
)
from next_is_you.ntuh_reader import (
    FetchedPage,
    NtuhProgressReader,
    parse_clinic_key,
    parse_progress_list,
    parse_retry_after,
    progress_list_url,
)
from next_is_you.persistence import CloudflareD1Store, Statement, VisitRepository
from test_scheduler_outbox import (
    LocalContext,
    LocalD1,
    LocalDurableStorage,
)
from next_is_you.send_gate import SystemSendGate

PAGE = (
    Path(__file__).parent / "fixtures" / "hospitals" / "ntuh_oph_progress_list.html"
).read_text(encoding="utf-8")
DAY = datetime(2026, 10, 22).date()
CLINIC = "11/Hsiao-Sang Chu/Dr. Appt."


def taipei(hour: int, minute: int, second: int = 0) -> datetime:
    return datetime(
        2026, 10, 22, hour, minute, second, tzinfo=timezone(timedelta(hours=8))
    )


def scope(
    clinic_code: str = CLINIC,
    *,
    session: ClinicSession = ClinicSession.AFTERNOON,
    department: str = "OPH",
    hospital: Hospital = Hospital.NTUH_MAIN,
) -> ClinicScope:
    return ClinicScope(hospital, DAY, department, clinic_code, session)


def page_with(current: str) -> str:
    return PAGE.replace("<td>025</td>", f"<td>{current}</td>")


class FakeSource:
    """Scripted fetcher; an exception instance in the script is raised."""

    def __init__(self, *script) -> None:
        self.script = list(script)
        self.urls: list[str] = []

    async def __call__(self, url: str) -> FetchedPage:
        self.urls.append(url)
        item = self.script.pop(0) if len(self.script) > 1 else self.script[0]
        if isinstance(item, Exception):
            raise item
        return item if isinstance(item, FetchedPage) else FetchedPage(200, item)


def reader(source: FakeSource, state: LocalDurableStorage | None = None):
    return NtuhProgressReader(state or LocalDurableStorage(), source)


def test_parser_reads_rows_and_ignores_expected_call_number_and_page_time() -> None:
    status, rows = parse_progress_list(PAGE)
    assert status == "ok"
    target = [row for row in rows if row.doctor == "Hsiao-Sang Chu"]
    assert [(r.room, r.clinic_type, r.current) for r in target] == [
        ("11", "Dr. Appt.", "025")
    ]
    assert not hasattr(target[0], "expected")


@pytest.mark.parametrize(
    "html",
    [
        "<html><body>maintenance</body></html>",
        "<table><tr><th>Room</th><th>Doctor</th></tr></table>",
        "<table><tr><th>Room</th><th>Doctor</th><th>Clinic Type</th></tr></table>",
    ],
)
def test_parser_fails_closed_on_unrecognized_pages(html: str) -> None:
    assert parse_progress_list(html) == ("schema", [])


@pytest.mark.parametrize(
    ("html", "status"),
    [("<p>Please complete the CAPTCHA</p>", "challenge"), ("Access Denied", "denied")],
)
def test_parser_detects_challenge_and_denial(html: str, status: str) -> None:
    assert parse_progress_list(html)[0] == status


def test_clinic_key_requires_room_doctor_and_type() -> None:
    assert parse_clinic_key(CLINIC) is not None
    assert parse_clinic_key("11/Hsiao-Sang Chu") is None
    assert parse_clinic_key("11//Dr. Appt.") is None


def test_request_url_is_the_observed_branch_list_without_department_or_session() -> (
    None
):
    expected = "https://reg.ntuh.gov.tw/WebReg/WebReg/ClinicCurrentLightNo?vHospCode=T0"
    assert progress_list_url() == expected


@pytest.mark.asyncio
async def test_exact_match_returns_fresh_usable_observation_stamped_with_fetch_time():
    source = FakeSource(PAGE)
    observation = await reader(source).observe(scope(), taipei(15, 0))
    assert isinstance(observation, QueueObservation)
    assert observation.current_number == 25
    assert observation.trustworthy_current
    assert observation.is_comparable_to(scope())
    assert observation.observed_at == taipei(15, 0).isoformat()
    assert observation.source_updated_at is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "clinic",
    [
        "11/Synthetic Doctor C/Dr. Appt.",
        "12/Hsiao-Sang Chu/Dr. Appt.",
        "11/Hsiao-Sang Chu/General Clinic",
    ],
)
async def test_any_identity_field_mismatch_never_matches(clinic: str) -> None:
    result = await reader(FakeSource(PAGE)).observe(scope(clinic), taipei(15, 0))
    assert result == ReadFailed("unavailable", "empty_result")


@pytest.mark.asyncio
async def test_current_is_never_inferred_from_neighbors_or_expected_call() -> None:
    result = await reader(FakeSource(PAGE)).observe(
        scope("08/Synthetic Doctor B/General Clinic"), taipei(15, 0)
    )
    assert result == ReadFailed("unavailable", "no_observation")


@pytest.mark.asyncio
@pytest.mark.parametrize("current", ["000", "abc", "²"])
async def test_zero_or_garbled_light_is_invalid_not_zero(current: str) -> None:
    result = await reader(FakeSource(page_with(current))).observe(
        scope(), taipei(15, 0)
    )
    assert result == ReadFailed("invalid", "invalid_data")


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["observe", "observe_for_start"])
async def test_non_ascii_numeric_light_fails_closed_for_each_read_path(method):
    result = await getattr(reader(FakeSource(page_with("²"))), method)(
        scope(), taipei(15, 0)
    )
    assert result == ReadFailed("invalid", "invalid_data")


@pytest.mark.asyncio
async def test_duplicate_exact_rows_are_ambiguous() -> None:
    row = "<tr><td>11</td><td>Hsiao-Sang Chu</td><td>Dr. Appt.</td><td>026</td><td></td></tr>"
    page = PAGE.replace("</table>", row + "</table>")
    result = await reader(FakeSource(page)).observe(scope(), taipei(15, 0))
    assert result == ReadFailed("invalid", "ambiguous_match")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad",
    [
        scope(department="MED"),
        scope(session=ClinicSession.EVENING),
        scope(hospital=Hospital.SHIN_KONG_TAIPEI),
        scope("not-a-composite-code"),
    ],
)
async def test_unsupported_scope_is_rejected_without_a_request(bad) -> None:
    source = FakeSource(PAGE)
    result = await reader(source).observe(bad, taipei(15, 0))
    assert result == ReadFailed("scope_mismatch", "scope_mismatch")
    assert source.urls == []


@pytest.mark.asyncio
async def test_morning_scope_is_unsupported_for_scheduled_and_start_reads() -> None:
    source = FakeSource(PAGE)
    r = reader(source)
    morning = scope(session=ClinicSession.MORNING)
    expected = ReadFailed("scope_mismatch", "scope_mismatch")

    assert await r.observe(morning, taipei(9, 0)) == expected
    assert await r.observe_for_start(morning, taipei(9, 0)) == expected
    assert source.urls == []


@pytest.mark.asyncio
async def test_reads_only_inside_session_window_plus_buffer() -> None:
    source = FakeSource(PAGE)
    r = reader(source)
    assert await r.observe(scope(), taipei(13, 19)) == ReadSkipped("before_session")
    assert source.urls == []
    assert isinstance(await r.observe(scope(), taipei(13, 20)), QueueObservation)
    assert await r.observe(scope(), taipei(16, 40)) == ReadSkipped("session_ended")
    other_day = ClinicScope(
        Hospital.NTUH_MAIN,
        DAY + timedelta(days=1),
        "OPH",
        CLINIC,
        ClinicSession.AFTERNOON,
    )
    assert await r.observe(other_day, taipei(15, 0)) == ReadSkipped("before_session")
    assert len(source.urls) == 1


@pytest.mark.asyncio
async def test_cadence_skips_ticks_inside_two_minutes_and_reads_at_two() -> None:
    source = FakeSource(PAGE)
    r = reader(source)
    assert isinstance(await r.observe(scope(), taipei(15, 0)), QueueObservation)
    assert await r.observe(scope(), taipei(15, 1)) == ReadSkipped("not_due")
    assert await r.observe(scope(), taipei(15, 1, 59)) == ReadSkipped("not_due")
    assert isinstance(await r.observe(scope(), taipei(15, 2)), QueueObservation)
    assert len(source.urls) == 2


@pytest.mark.asyncio
async def test_visits_in_the_same_tick_share_one_read() -> None:
    source = FakeSource(PAGE)
    r = reader(source)
    first = await r.observe(scope(), taipei(15, 0))
    second = await r.observe(
        scope("07/Synthetic Doctor A/General Clinic"), taipei(15, 0, 1)
    )
    assert first.current_number == 25 and second.current_number == 12
    assert len(source.urls) == 1


@pytest.mark.asyncio
async def test_start_reuses_a_fresh_read_but_reads_once_it_is_older_than_two_minutes():
    source = FakeSource(PAGE)
    r = reader(source)
    await r.observe(scope(), taipei(15, 0))
    assert isinstance(
        await r.observe_for_start(scope(), taipei(15, 1)), QueueObservation
    )
    assert len(source.urls) == 1
    assert isinstance(
        await r.observe_for_start(scope(), taipei(15, 2, 1)), QueueObservation
    )
    assert len(source.urls) == 2


@pytest.mark.asyncio
async def test_state_survives_a_new_reader_instance() -> None:
    state = LocalDurableStorage()
    source = FakeSource(PAGE)
    await reader(source, state).observe(scope(), taipei(15, 0))
    assert await reader(source, state).observe(scope(), taipei(15, 1)) == ReadSkipped(
        "not_due"
    )
    assert len(source.urls) == 1


@pytest.mark.asyncio
async def test_transient_failures_back_off_one_two_then_four_minutes_capped() -> None:
    source = FakeSource(FetchedPage(503, ""))
    r = reader(source)
    reads = []
    for minute in range(0, 14):
        result = await r.observe(scope(), taipei(15, minute))
        if result != ReadSkipped("not_due"):
            reads.append(minute)
            assert result == ReadFailed("unavailable", "no_observation")
    assert reads == [0, 1, 3, 7, 11]
    assert len(source.urls) == 5


@pytest.mark.asyncio
async def test_timeout_is_transient_and_recovers_to_normal_cadence() -> None:
    source = FakeSource(TimeoutError(), PAGE)
    r = reader(source)
    assert await r.observe(scope(), taipei(15, 0)) == ReadFailed(
        "unavailable", "timeout"
    )
    assert await r.observe(scope(), taipei(15, 0, 30)) == ReadFailed(
        "unavailable", "timeout"
    )
    assert isinstance(await r.observe(scope(), taipei(15, 1)), QueueObservation)
    assert await r.observe(scope(), taipei(15, 2)) == ReadSkipped("not_due")
    assert isinstance(await r.observe(scope(), taipei(15, 3)), QueueObservation)


@pytest.mark.asyncio
async def test_rate_limit_retry_after_extends_the_wait_within_a_cap() -> None:
    source = FakeSource(FetchedPage(429, "", retry_after=300), PAGE)
    r = reader(source)
    assert isinstance(await r.observe(scope(), taipei(15, 0)), ReadFailed)
    assert await r.observe(scope(), taipei(15, 4, 59)) == ReadSkipped("not_due")
    assert isinstance(await r.observe(scope(), taipei(15, 5)), QueueObservation)


@pytest.mark.asyncio
async def test_http_date_retry_after_extends_the_wait_within_a_cap() -> None:
    now = taipei(15, 0)
    assert parse_retry_after("300", now=now) == 300
    retry_at = taipei(15, 5).astimezone(timezone.utc)
    header = format_datetime(retry_at, usegmt=True)
    retry_after = parse_retry_after(header, now=now)
    assert retry_after == 300

    source = FakeSource(FetchedPage(503, "", retry_after=retry_after), PAGE)
    r = reader(source)
    assert isinstance(await r.observe(scope(), now), ReadFailed)
    assert await r.observe(scope(), taipei(15, 4, 59)) == ReadSkipped("not_due")
    assert isinstance(await r.observe(scope(), taipei(15, 5)), QueueObservation)


@pytest.mark.asyncio
async def test_start_does_not_hammer_the_source_during_backoff() -> None:
    source = FakeSource(FetchedPage(500, ""), PAGE)
    r = reader(source)
    await r.observe(scope(), taipei(15, 0))
    assert await r.observe_for_start(scope(), taipei(15, 0, 40)) == ReadFailed(
        "unavailable", "no_observation"
    )
    assert len(source.urls) == 1
    assert isinstance(
        await r.observe_for_start(scope(), taipei(15, 1)), QueueObservation
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "page",
    [
        FetchedPage(403, "Forbidden"),
        FetchedPage(401, ""),
        FetchedPage(302, ""),
        FetchedPage(200, "<p>Please complete the CAPTCHA to continue</p>"),
        FetchedPage(200, "<h1>Access Denied</h1>"),
    ],
)
async def test_challenge_or_denial_stops_reading_the_source(page: FetchedPage) -> None:
    source = FakeSource(page, PAGE)
    r = reader(source)
    denied = ReadFailed("unavailable", "access_denied")
    assert await r.observe(scope(), taipei(15, 0)) == denied
    for minute in (1, 3, 10, 30):
        assert await r.observe(scope(), taipei(15, minute)) == denied
        assert await r.observe_for_start(scope(), taipei(15, minute)) == denied
    assert len(source.urls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "page", [FetchedPage(200, "<html>moved</html>"), FetchedPage(404, "")]
)
async def test_schema_change_fails_closed(page: FetchedPage) -> None:
    result = await reader(FakeSource(page)).observe(scope(), taipei(15, 0))
    assert result == ReadFailed("invalid", "schema_drift")


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["observe", "observe_for_start"])
async def test_short_row_after_session_end_is_schema_drift_not_clinic_end(method):
    malformed = PAGE.replace(
        "<tr><td>11</td><td>Hsiao-Sang Chu</td><td>Dr. Appt.</td><td>025</td><td>017</td></tr>",
        "<tr><td>11</td><td>Hsiao-Sang Chu</td><td>Dr. Appt.</td></tr>",
    )
    source = FakeSource(malformed)
    result = await getattr(reader(source), method)(scope(), taipei(16, 31))
    assert result == ReadFailed("invalid", "schema_drift")
    assert len(source.urls) == 1


@pytest.mark.asyncio
async def test_row_gone_inside_the_session_is_an_unusable_read_not_the_end() -> None:
    gone = PAGE.replace("Hsiao-Sang Chu", "Someone Else")
    result = await reader(FakeSource(gone)).observe(scope(), taipei(16, 29))
    assert result == ReadFailed("unavailable", "empty_result")


@pytest.mark.asyncio
async def test_row_gone_after_session_end_stops_reading_for_good() -> None:
    gone = PAGE.replace("Hsiao-Sang Chu", "Someone Else")
    source = FakeSource(gone)
    r = reader(source)
    assert await r.observe(scope(), taipei(16, 31)) == ReadSkipped("session_ended")
    assert await r.observe(scope(), taipei(16, 33)) == ReadSkipped("session_ended")
    assert len(source.urls) == 1


@pytest.mark.asyncio
async def test_blank_number_with_row_present_after_end_is_not_the_end_of_clinic():
    blank = page_with("")
    source = FakeSource(blank)
    result = await reader(source).observe(scope(), taipei(16, 31))
    assert result == ReadFailed("unavailable", "no_observation")


# Scheduler and gate wiring


async def gate_with_visit(source: FakeSource, *, enabled: bool = True):
    database = LocalD1()
    env = {
        "DB": database,
        "NIY006_LOCAL_TEST_MODE": "1",
        "NIY_ENVIRONMENT": "local-test",
    }
    if enabled:
        env["NTUH_READER_ENABLED"] = "1"
    gate = SystemSendGate(LocalContext(LocalDurableStorage()), env)
    gate._ntuh_fetcher = source
    return database, gate


def counts(database: LocalD1, visit_id: str) -> tuple[str, str, int]:
    row = database.connection.execute(
        "SELECT latest_source_read_status, latest_source_read_reason,"
        " consecutive_unusable_reads FROM visits WHERE id = ?",
        (visit_id,),
    ).fetchone()
    return tuple(row)


async def seed_ntuh(database: LocalD1, gate, visit_id: str, patient: int = 28):
    now = taipei(14, 0)
    store = CloudflareD1Store(database)
    await store.execute(
        Statement(
            """INSERT OR IGNORE INTO recipients (id, line_subject, display_name,
            consented_at, friendship_checked_at, active, created_at) VALUES
            ('r1', 'U' || lower(hex(zeroblob(16))), 'Synthetic one', ?, ?, 1, ?)""",
            (now.isoformat(),) * 3,
        )
    )
    repository = VisitRepository(store)
    await repository.create_draft(
        visit_id=visit_id,
        hospital="ntuh-main",
        visit_day=DAY,
        department_code="OPH",
        clinic_code=CLINIC,
        clinic_session="afternoon",
        patient_number=patient,
        now=now,
    )
    assert await repository.add_recipient(visit_id, "r1", now)
    return repository


@pytest.mark.asyncio
async def test_start_activates_on_fresh_exact_positive_read() -> None:
    source = FakeSource(PAGE)
    database, gate = await gate_with_visit(source)
    repository = await seed_ntuh(database, gate, "d1")
    started = await gate.start_visit("d1", taipei(15, 0).isoformat())
    assert started == {"state": "active"}
    visit = await repository.get_visit("d1")
    assert visit["state"] == "active"
    assert counts(database, "d1")[:2] == ("usable", "none")
    assert source.urls == [progress_list_url()]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("page", "error", "status", "reason"),
    [
        (
            FetchedPage(503, ""),
            "observation_unavailable",
            "unavailable",
            "no_observation",
        ),
        (
            FetchedPage(403, ""),
            "observation_unavailable",
            "unavailable",
            "access_denied",
        ),
        (FetchedPage(200, "<html/>"), "observation_invalid", "invalid", "schema_drift"),
        (page_with(""), "observation_unavailable", "unavailable", "no_observation"),
        (page_with("000"), "observation_invalid", "invalid", "invalid_data"),
    ],
)
async def test_start_stays_draft_with_the_source_reason(page, error, status, reason):
    database, gate = await gate_with_visit(FakeSource(page))
    repository = await seed_ntuh(database, gate, "d1")
    assert await gate.start_visit("d1", taipei(15, 0).isoformat()) == {"error": error}
    assert (await repository.get_visit("d1"))["state"] == "draft"
    assert counts(database, "d1")[:2] == (status, reason)


@pytest.mark.asyncio
async def test_start_outside_the_window_stays_draft_without_a_request() -> None:
    source = FakeSource(PAGE)
    database, gate = await gate_with_visit(source)
    repository = await seed_ntuh(database, gate, "d1")
    assert await gate.start_visit("d1", taipei(9, 0).isoformat()) == {
        "error": "observation_unavailable"
    }
    assert source.urls == []
    assert (await repository.get_visit("d1"))["state"] == "draft"


@pytest.mark.asyncio
async def test_reader_is_off_without_the_explicit_flag() -> None:
    source = FakeSource(PAGE)
    database, gate = await gate_with_visit(source, enabled=False)
    await seed_ntuh(database, gate, "d1")
    assert await gate.start_visit("d1", taipei(15, 0).isoformat()) == {
        "error": "observation_unavailable"
    }
    assert source.urls == []


@pytest.mark.asyncio
async def test_production_hold_disables_start_and_reader_status_even_if_enabled() -> None:
    source = FakeSource(PAGE)
    database = LocalD1()
    env = {
        "DB": database,
        "NIY_ENVIRONMENT": "production",
        "NTUH_READER_ENABLED": "1",
    }
    gate = SystemSendGate(LocalContext(LocalDurableStorage()), env)
    gate._ntuh_fetcher = source
    repository = await seed_ntuh(database, gate, "d1")

    assert await gate.start_visit("d1", taipei(15, 0).isoformat()) == {
        "error": "observation_unavailable"
    }
    assert (await repository.get_visit("d1"))["state"] == "draft"
    assert source.urls == []
    status = await gate.scheduler_status()
    assert status["held"]
    assert not status["hospital_reader_available"]


async def active_visit(database, gate, visit_id="d1", patient=28):
    repository = await seed_ntuh(database, gate, visit_id, patient)
    assert await repository.start(visit_id, taipei(14, 59))
    assert await repository.update_observation(
        visit_id,
        current_number=25,
        observed_at=taipei(14, 59),
        consecutive_unusable_reads=0,
    )
    assert await repository.set_source_read(visit_id, "usable", "none")


@pytest.mark.asyncio
async def test_scheduled_checks_create_near_alert_from_fresh_exact_read() -> None:
    source = FakeSource(PAGE, page_with("026"))
    database, gate = await gate_with_visit(source)
    await active_visit(database, gate)
    result = await gate.scheduled_tick(taipei(15, 2).isoformat())
    assert result["events_created"] == 1
    again = await gate.scheduled_tick(taipei(15, 4).isoformat())
    assert again["events_created"] == 0
    assert counts(database, "d1")[:2] == ("usable", "none")
    snapshot = await gate.test_snapshot()
    assert [event["event_kind"] for event in snapshot["events"]] == ["near"]
    assert snapshot["line_requests"]


@pytest.mark.asyncio
async def test_skipped_ticks_never_count_as_failed_reads() -> None:
    source = FakeSource(PAGE)
    database, gate = await gate_with_visit(source)
    await active_visit(database, gate)
    await gate.scheduled_tick(taipei(15, 0).isoformat())
    unusable_reads = counts(database, "d1")[2]
    await gate.scheduled_tick(taipei(15, 1).isoformat())
    await gate.scheduled_tick(taipei(15, 1, 30).isoformat())
    assert counts(database, "d1")[2] == unusable_reads
    assert len(source.urls) == 1


@pytest.mark.asyncio
async def test_three_failed_reads_inside_the_window_send_the_existing_unavailable_alert():
    source = FakeSource(FetchedPage(503, ""))
    database, gate = await gate_with_visit(source)
    await active_visit(database, gate)
    created = 0
    for minute in (2, 3, 5):  # reads follow the 1 then 2 minute backoff
        created += (await gate.scheduled_tick(taipei(15, minute).isoformat()))[
            "events_created"
        ]
    assert created == 1
    kinds = [e["event_kind"] for e in (await gate.test_snapshot())["events"]]
    assert kinds == ["unavailable"]


@pytest.mark.asyncio
async def test_clinic_end_stops_reads_and_sends_no_unavailable_alert() -> None:
    gone = PAGE.replace("Hsiao-Sang Chu", "Someone Else")
    source = FakeSource(gone)
    database, gate = await gate_with_visit(source)
    await active_visit(database, gate)
    for minute in (31, 33, 35, 40, 50):
        result = await gate.scheduled_tick(taipei(16, minute).isoformat())
        assert result["events_created"] == 0
    assert len(source.urls) == 1
    assert (await gate.test_snapshot())["events"] == []


@pytest.mark.asyncio
async def test_challenge_stops_the_source_and_keeps_the_visit_unavailable() -> None:
    source = FakeSource(PAGE, FetchedPage(403, ""), PAGE)
    database, gate = await gate_with_visit(source)
    await active_visit(database, gate)
    for minute in (2, 3, 4, 10):
        await gate.scheduled_tick(taipei(15, minute).isoformat())
    assert counts(database, "d1")[:2] == ("unavailable", "access_denied")
    assert len(source.urls) == 2
