import sqlite3
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "migrations" / "0001_initial.sql"


@pytest.fixture
def database():
    connection = sqlite3.connect(":memory:")
    connection.executescript(MIGRATION.read_text())
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


def test_schema_prevents_duplicate_alert_kind_per_recipient_visit(database):
    database.execute(
        "INSERT INTO recipients (id, line_subject, display_name, consented_at, created_at) "
        "VALUES ('r1', 'line-subject-1', 'Family A', '2026-09-27T09:00:00+08:00', '2026-09-27T09:00:00+08:00')"
    )
    database.execute(
        "INSERT INTO visits (id, hospital, visit_date, department_code, clinic_code, clinic_session, patient_number, state, created_at) "
        "VALUES ('v1', 'ntuh-main', '2026-09-27', 'MED', 'MED-101', 'afternoon', 85, 'active', '2026-09-27T09:00:00+08:00')"
    )
    event = (
        "e1",
        "v1",
        "r1",
        "near",
        "retry-1",
        '{"kind":"near"}',
        "pending",
        "2026-09-27T09:01:00+08:00",
    )
    database.execute(
        "INSERT INTO outbound_events (id, visit_id, recipient_id, event_kind, retry_key, payload_json, outcome, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        event,
    )

    with pytest.raises(sqlite3.IntegrityError):
        database.execute(
            "INSERT INTO outbound_events (id, visit_id, recipient_id, event_kind, retry_key, payload_json, outcome, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("e2", "v1", "r1", "near", "retry-2", '{"kind":"near"}', "pending", "2026-09-27T09:02:00+08:00"),
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
