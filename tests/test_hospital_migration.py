"""Migration 0007 drops the hospital CHECK without losing a stored reminder (#107).

Local integration: the real migration files run against an in-memory SQLite copy
that already holds synthetic visits in every lifecycle state.
"""

import sqlite3
from pathlib import Path

import pytest

MIGRATIONS = sorted((Path(__file__).resolve().parents[1] / "migrations").glob("*.sql"))
BEFORE = [m for m in MIGRATIONS if not m.name.startswith("0007_")]
REBUILD = next(m for m in MIGRATIONS if m.name.startswith("0007_"))
STATES = ["draft", "active", "stopping", "stopped", "expired"]
INSERT_THIRD = (
    "INSERT INTO visits (id, hospital, visit_date, department_code, "
    "clinic_code, clinic_session, patient_number, state, created_at) "
    "VALUES ('x', 'synthetic-third', '2026-11-20', 'OPH', 'C', "
    "'morning', 1, 'draft', '2026-11-01T00:00:00Z')"
)


def _apply(connection, files):
    for migration in files:
        connection.executescript(migration.read_text(encoding="utf-8"))


def _shape(connection):
    tables = {
        name: [
            tuple(row[1:3]) for row in connection.execute(f"PRAGMA table_info({name})")
        ]
        for (name,) in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    objects = set(
        connection.execute(
            "SELECT type, name, tbl_name FROM sqlite_master "
            "WHERE type IN ('index', 'trigger') AND name NOT LIKE 'sqlite_%'"
        )
    )
    return tables, objects


@pytest.fixture
def populated():
    connection = sqlite3.connect(":memory:")
    connection.execute("PRAGMA foreign_keys = ON")
    _apply(connection, BEFORE)
    connection.execute(
        "INSERT INTO recipients (id, line_subject, display_name, consented_at, "
        "created_at) VALUES ('r1', 'line-1', 'Family', '2026-11-01T00:00:00Z', "
        "'2026-11-01T00:00:00Z')"
    )
    for index, state in enumerate(STATES):
        connection.execute(
            "INSERT INTO visits (id, hospital, visit_date, department_code, "
            "clinic_code, clinic_session, patient_number, state, created_at, "
            "latest_source_read_status, latest_source_read_reason, "
            "near_prev_observed_number, preflight_last_checked_date) "
            "VALUES (?, 'ntuh-main', '2026-11-20', 'OPH', ?, 'afternoon', ?, ?, "
            "'2026-11-01T00:00:00Z', 'stale', 'timeout', 42, '2026-11-02')",
            (f"v-{state}", f"C-{index}", 10 + index, state),
        )
        connection.execute(
            "INSERT INTO visit_recipients VALUES (?, 'r1', '2026-11-01T00:00:00Z')",
            (f"v-{state}",),
        )
        connection.execute(
            "INSERT INTO outbound_events (id, visit_id, recipient_id, event_kind, "
            "retry_key, payload_json, outcome, created_at, attempt_count) "
            "VALUES (?, ?, 'r1', 'near', ?, '{}', 'accepted', "
            "'2026-11-01T00:00:00Z', 2)",
            (f"e-{state}", f"v-{state}", f"k-{state}"),
        )
    connection.commit()
    return connection


def _rows(connection):
    return {
        table: connection.execute(f"SELECT * FROM {table} ORDER BY 1, 2").fetchall()
        for table in ("recipients", "visits", "visit_recipients", "outbound_events")
    }


def test_every_row_survives_the_rebuild(populated):
    before = _rows(populated)
    populated.executescript(REBUILD.read_text())
    assert _rows(populated) == before
    assert len(before["visits"]) == 5 and len(before["outbound_events"]) == 5
    assert populated.execute("PRAGMA foreign_key_check").fetchall() == []


def test_columns_indexes_and_triggers_survive(populated):
    before = _shape(populated)
    populated.executescript(REBUILD.read_text())
    assert _shape(populated) == before


def test_dependent_foreign_keys_still_point_at_visits(populated):
    populated.executescript(REBUILD.read_text())
    for table in ("visit_recipients", "outbound_events"):
        targets = {
            row[2] for row in populated.execute(f"PRAGMA foreign_key_list({table})")
        }
        assert targets == {"visits", "recipients"}
    populated.execute("DELETE FROM visits WHERE id = 'v-draft'")
    assert populated.execute(
        "SELECT COUNT(*) FROM outbound_events WHERE visit_id = 'v-draft'"
    ).fetchone() == (0,)


def test_one_active_visit_per_appointment_still_holds(populated):
    populated.executescript(REBUILD.read_text())
    with pytest.raises(sqlite3.IntegrityError):
        populated.execute(
            "INSERT INTO visits (id, hospital, visit_date, department_code, "
            "clinic_code, clinic_session, patient_number, state, created_at) "
            "VALUES ('dup', 'ntuh-main', '2026-11-20', 'OPH', 'C-1', 'afternoon', "
            "11, 'active', '2026-11-01T00:00:00Z')"
        )


def test_a_hospital_id_outside_the_old_list_can_be_stored(populated):
    before = sqlite3.connect(":memory:")
    _apply(before, BEFORE)
    with pytest.raises(sqlite3.IntegrityError):
        before.execute(INSERT_THIRD)
    populated.executescript(REBUILD.read_text())
    populated.execute(INSERT_THIRD)
