"""Migration 0008 adds the visit-day card reasons without losing a stored reminder (#135).

Local integration: the real migration files run against an in-memory SQLite copy
that already holds synthetic visits in every lifecycle state.
"""

import sqlite3
from pathlib import Path

import pytest

MIGRATIONS = sorted((Path(__file__).resolve().parents[1] / "migrations").glob("*.sql"))
BEFORE = [m for m in MIGRATIONS if m.name < "0008_"]
REBUILD = next(m for m in MIGRATIONS if m.name.startswith("0008_"))
STATES = ["draft", "active", "stopping", "stopped", "expired"]


def _apply(connection, files):
    for migration in files:
        connection.executescript(migration.read_text(encoding="utf-8"))


def _insert_visit(connection, visit_id, reason, state="draft"):
    connection.execute(
        "INSERT INTO visits (id, hospital, visit_date, department_code, "
        "clinic_code, clinic_session, patient_number, state, created_at, "
        "latest_source_read_status, latest_source_read_reason) "
        "VALUES (?, 'ntuh-main', '2026-11-20', 'OPH', ?, 'morning', 1, ?, "
        "'2026-11-01T00:00:00Z', 'unavailable', ?)",
        (visit_id, f"C-{visit_id}", state, reason),
    )


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


def test_the_new_reasons_are_refused_before_and_stored_after(populated):
    for reason in ("card_not_found", "substitute_doctor"):
        with pytest.raises(sqlite3.IntegrityError):
            _insert_visit(populated, f"before-{reason}", reason)
    populated.executescript(REBUILD.read_text())
    for reason in ("card_not_found", "substitute_doctor"):
        _insert_visit(populated, f"after-{reason}", reason)
    with pytest.raises(sqlite3.IntegrityError):
        _insert_visit(populated, "bogus", "not_a_reason")


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


def test_the_staging_rehearsal_seed_survives_the_rebuild():
    # The seed docs/CI-CD.md has Staging load before 0008: it must load on a
    # database at 0007, and every row must come through the rebuild unchanged.
    seed = REBUILD.parents[1] / "scripts" / "migration-rehearsal" / "0008_seed.sql"
    connection = sqlite3.connect(":memory:")
    connection.execute("PRAGMA foreign_keys = ON")
    _apply(connection, BEFORE)
    connection.executescript(seed.read_text(encoding="utf-8"))
    before = _rows(connection)
    reasons = {
        row[0]
        for row in connection.execute("SELECT latest_source_read_reason FROM visits")
    }

    connection.executescript(REBUILD.read_text(encoding="utf-8"))

    assert _rows(connection) == before
    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    assert reasons == {
        "none",
        "no_observation",
        "timeout",
        "stale_sample",
        "untrusted_source",
        "scope_mismatch",
        "empty_result",
        "schema_drift",
        "access_denied",
        "ambiguous_match",
        "invalid_data",
    }
