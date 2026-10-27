import sqlite3
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = sorted((ROOT / "migrations").glob("*.sql"))


@pytest.fixture
def database():
    connection = sqlite3.connect(":memory:")
    for migration in MIGRATIONS:
        connection.executescript(migration.read_text())
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def test_initial_schema_has_the_five_mvp_tables(database):
    tables = {
        row[0]
        for row in database.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }

    assert tables == {
        "recipients",
        "invitations",
        "visits",
        "visit_recipients",
        "outbound_events",
    }


def test_latest_source_read_fields_are_bounded_enums(database):
    columns = {row[1] for row in database.execute("PRAGMA table_info(visits)")}
    assert {"latest_source_read_status", "latest_source_read_reason"} <= columns
    database.execute(
        "INSERT INTO visits (id, hospital, visit_date, department_code, clinic_code, clinic_session, patient_number, state, created_at, latest_source_read_status, latest_source_read_reason) "
        "VALUES ('v1', 'ntuh-main', '2026-09-27', 'MED', 'MED-101', 'afternoon', 85, 'draft', '2026-09-27T09:00:00Z', 'usable', 'none')"
    )
    with pytest.raises(sqlite3.IntegrityError):
        database.execute(
            "UPDATE visits SET latest_source_read_reason = 'hospital says wait' WHERE id = 'v1'"
        )


def _seed_visit_recipient(database):
    database.execute(
        "INSERT INTO recipients (id, line_subject, display_name, consented_at, created_at) "
        "VALUES ('r1', 'line-subject-1', 'Family A', '2026-09-27T09:00:00+08:00', '2026-09-27T09:00:00+08:00')"
    )
    database.execute(
        "INSERT INTO visits (id, hospital, visit_date, department_code, clinic_code, clinic_session, patient_number, state, created_at) "
        "VALUES ('v1', 'ntuh-main', '2026-09-27', 'MED', 'MED-101', 'afternoon', 85, 'active', '2026-09-27T09:00:00+08:00')"
    )


def _insert_near(database, suffix):
    database.execute(
        "INSERT INTO outbound_events (id, visit_id, recipient_id, event_kind, retry_key, payload_json, outcome, created_at) "
        "VALUES (?, 'v1', 'r1', 'near', ?, '{\"kind\":\"near\"}', 'pending', '2026-09-27T09:01:00+08:00')",
        (f"near-{suffix}", f"retry-near-{suffix}"),
    )


def test_schema_caps_near_reminders_at_twenty_per_recipient_visit(database):
    _seed_visit_recipient(database)

    for suffix in range(20):
        _insert_near(database, suffix)
    assert (
        database.execute(
            "SELECT COUNT(*) FROM outbound_events WHERE event_kind = 'near'"
        ).fetchone()[0]
        == 20
    )

    with pytest.raises(sqlite3.IntegrityError):
        _insert_near(database, 20)


def test_schema_still_allows_one_unavailable_per_recipient_visit(database):
    _seed_visit_recipient(database)
    database.execute(
        "INSERT INTO outbound_events (id, visit_id, recipient_id, event_kind, retry_key, payload_json, outcome, created_at) "
        "VALUES ('u1', 'v1', 'r1', 'unavailable', 'retry-u1', '{}', 'pending', '2026-09-27T09:01:00+08:00')"
    )

    with pytest.raises(sqlite3.IntegrityError):
        database.execute(
            "INSERT INTO outbound_events (id, visit_id, recipient_id, event_kind, retry_key, payload_json, outcome, created_at) "
            "VALUES ('u2', 'v1', 'r1', 'unavailable', 'retry-u2', '{}', 'pending', '2026-09-27T09:02:00+08:00')"
        )


def test_schema_admits_the_superseded_outcome(database):
    _seed_visit_recipient(database)
    _insert_near(database, 0)
    database.execute(
        "UPDATE outbound_events SET outcome = 'superseded' WHERE id = 'near-0'"
    )
    assert (
        database.execute(
            "SELECT outcome FROM outbound_events WHERE id = 'near-0'"
        ).fetchone()[0]
        == "superseded"
    )


def test_withdrawing_recipient_cascades_identity_linked_events(database):
    database.execute(
        "INSERT INTO recipients (id, line_subject, display_name, consented_at, created_at) "
        "VALUES ('r1', 'line-subject-1', 'Family A', '2026-09-27T09:00:00+08:00', '2026-09-27T09:00:00+08:00')"
    )
    database.execute(
        "INSERT INTO visits (id, hospital, visit_date, department_code, clinic_code, clinic_session, patient_number, state, created_at) "
        "VALUES ('v1', 'ntuh-main', '2026-09-27', 'MED', 'MED-101', 'afternoon', 85, 'stopped', '2026-09-27T09:00:00+08:00')"
    )
    database.execute(
        "INSERT INTO visit_recipients (visit_id, recipient_id, selected_at) "
        "VALUES ('v1', 'r1', '2026-09-27T09:00:00+08:00')"
    )
    database.execute(
        "INSERT INTO outbound_events (id, visit_id, recipient_id, event_kind, retry_key, payload_json, outcome, created_at) "
        "VALUES ('e1', 'v1', 'r1', 'near', 'retry-1', '{\"kind\":\"near\"}', 'accepted', '2026-09-27T09:01:00+08:00')"
    )

    database.execute("DELETE FROM recipients WHERE id = 'r1'")

    assert database.execute("SELECT count(*) FROM visit_recipients").fetchone()[0] == 0
    assert database.execute("SELECT count(*) FROM outbound_events").fetchone()[0] == 0
