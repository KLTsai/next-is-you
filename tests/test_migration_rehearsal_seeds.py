"""Each Staging rehearsal seed clears earlier rehearsal rows before seeding (#210).

Local integration: the real migration and seed files run against an in-memory
SQLite copy with foreign keys on, as on D1.
"""

import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = sorted((ROOT / "migrations").glob("*.sql"))
SEEDS = ROOT / "scripts" / "migration-rehearsal"
TABLES = ("recipients", "visits", "visit_recipients", "outbound_events")


def _database():
    connection = sqlite3.connect(":memory:")
    connection.execute("PRAGMA foreign_keys = ON")
    for migration in MIGRATIONS:
        connection.executescript(migration.read_text(encoding="utf-8"))
    return connection


def _seed(connection, name):
    connection.executescript((SEEDS / f"{name}_seed.sql").read_text(encoding="utf-8"))


def _rows(connection):
    return {
        table: sorted(connection.execute(f"SELECT * FROM {table}").fetchall(), key=repr)
        for table in TABLES
    }


def _insert_real_rows(connection):
    # A user's rows: a recipient, their visit, the link and one reminder.
    connection.execute(
        "INSERT INTO recipients (id, line_subject, display_name, consented_at, "
        "friendship_checked_at, active, created_at) VALUES ('family-1', "
        "'line-family-1', 'Family', '2026-11-01T00:00:00Z', NULL, 1, "
        "'2026-11-01T00:00:00Z')"
    )
    connection.execute(
        "INSERT INTO visits (id, hospital, visit_date, department_code, "
        "clinic_code, clinic_session, patient_number, state, created_at, "
        "draft_expires_at) VALUES ('visit-1', 'ntuh-main', '2027-06-01', 'MED', "
        "'MED-1', 'morning', 7, 'draft', '2026-11-01T00:00:00Z', "
        "'2027-06-01T00:00:00Z')"
    )
    connection.execute(
        "INSERT INTO visit_recipients (visit_id, recipient_id, selected_at) "
        "VALUES ('visit-1', 'family-1', '2026-11-01T00:01:00Z')"
    )
    connection.execute(
        "INSERT INTO outbound_events (id, visit_id, recipient_id, event_kind, "
        "retry_key, payload_json, outcome, created_at, attempt_count) VALUES "
        "('event-1', 'visit-1', 'family-1', 'near', 'key-1', '{}', 'pending', "
        "'2026-11-01T00:02:00Z', 0)"
    )
    connection.commit()


def _rows_seeded_alone(name):
    connection = _database()
    _seed(connection, name)
    return _rows(connection)


def test_each_seed_replaces_earlier_rehearsal_rows_and_keeps_real_ones():
    connection = _database()
    _insert_real_rows(connection)
    real = _rows(connection)

    # Every seed in order, then an older one over a newer one's rows, as when
    # a migration is rehearsed again after a later rehearsal.
    names = sorted(
        seed.name.removesuffix("_seed.sql") for seed in SEEDS.glob("*_seed.sql")
    )
    for name in [*names, names[-2]]:
        _seed(connection, name)
        seeded = _rows_seeded_alone(name)
        assert _rows(connection) == {
            table: sorted(real[table] + seeded[table], key=repr) for table in TABLES
        }, name
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
