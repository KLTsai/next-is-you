"""Apply every tracked migration to a fresh SQLite database and validate order."""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = sorted((ROOT / "migrations").glob("*.sql"))
MIGRATION_NAME = re.compile(r"^(\d{4})_[a-z0-9_]+\.sql$")


def main() -> None:
    numbers = []
    for migration in MIGRATIONS:
        match = MIGRATION_NAME.fullmatch(migration.name)
        if match is None:
            raise SystemExit(f"invalid migration filename: {migration.name}")
        numbers.append(int(match.group(1)))
    if numbers != list(range(1, len(numbers) + 1)):
        raise SystemExit(f"migration sequence is not contiguous: {numbers}")

    connection = sqlite3.connect(":memory:")
    connection.execute("PRAGMA foreign_keys = ON")
    for migration in MIGRATIONS:
        connection.executescript(migration.read_text(encoding="utf-8"))
    violations = connection.execute("PRAGMA foreign_key_check").fetchall()
    if violations:
        raise SystemExit(f"migration foreign key check failed: {violations}")

    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    required = {
        "recipients",
        "visits",
        "visit_recipients",
        "outbound_events",
        "invitations",
    }
    if not required <= tables:
        raise SystemExit(
            f"migration schema is missing tables: {sorted(required - tables)}"
        )
    visit_columns = {row[1] for row in connection.execute("PRAGMA table_info(visits)")}
    if (
        not {
            "latest_source_read_status",
            "latest_source_read_reason",
            "near_prev_observed_number",
        }
        <= visit_columns
    ):
        raise SystemExit("expected migration columns are missing from visits")
    _check_near_reminder_rules(connection)
    _check_hospital_ids_are_open(connection)
    print(f"Applied {len(MIGRATIONS)} migrations; SQLite schema checks passed.")


def _check_near_reminder_rules(connection: sqlite3.Connection) -> None:
    """Confirm the repeat near reminder rules are enforced by stored constraints."""
    connection.execute(
        "INSERT INTO recipients (id, line_subject, display_name, consented_at, created_at) "
        "VALUES ('cm-r', 'cm-line', 'Check', '2026-09-27T00:00:00Z', '2026-09-27T00:00:00Z')"
    )
    connection.execute(
        "INSERT INTO visits (id, hospital, visit_date, department_code, clinic_code, "
        "clinic_session, patient_number, state, created_at) "
        "VALUES ('cm-v', 'ntuh-main', '2026-09-27', 'MED', 'MED-1', 'afternoon', 85, 'active', '2026-09-27T00:00:00Z')"
    )

    def insert_near(suffix: str) -> None:
        connection.execute(
            "INSERT INTO outbound_events (id, visit_id, recipient_id, event_kind, retry_key, "
            "payload_json, outcome, created_at) "
            "VALUES (?, 'cm-v', 'cm-r', 'near', ?, '{}', 'pending', '2026-09-27T00:01:00Z')",
            (f"cm-near-{suffix}", f"cm-near-key-{suffix}"),
        )

    for index in range(20):
        insert_near(str(index))
    try:
        insert_near("overflow")
    except sqlite3.IntegrityError:
        pass
    else:
        raise SystemExit("near reminder cap of 20 is not enforced by the schema")

    connection.execute(
        "UPDATE outbound_events SET outcome = 'superseded' WHERE id = 'cm-near-0'"
    )

    connection.execute(
        "INSERT INTO outbound_events (id, visit_id, recipient_id, event_kind, retry_key, "
        "payload_json, outcome, created_at) "
        "VALUES ('cm-u-1', 'cm-v', 'cm-r', 'unavailable', 'cm-u-key-1', '{}', 'pending', '2026-09-27T00:01:00Z')"
    )
    try:
        connection.execute(
            "INSERT INTO outbound_events (id, visit_id, recipient_id, event_kind, retry_key, "
            "payload_json, outcome, created_at) "
            "VALUES ('cm-u-2', 'cm-v', 'cm-r', 'unavailable', 'cm-u-key-2', '{}', 'pending', '2026-09-27T00:01:00Z')"
        )
    except sqlite3.IntegrityError:
        pass
    else:
        raise SystemExit("single unavailable warning is not enforced by the schema")

    connection.execute("DELETE FROM recipients WHERE id = 'cm-r'")
    if connection.execute("SELECT COUNT(*) FROM outbound_events").fetchone()[0] != 0:
        raise SystemExit("withdrawing a recipient did not cascade its events")


def _check_hospital_ids_are_open(connection: sqlite3.Connection) -> None:
    """Confirm the database does not enumerate hospitals (ADR 0002)."""
    sql = connection.execute(
        "SELECT sql FROM sqlite_master WHERE name = 'visits'"
    ).fetchone()[0]
    if "hospital IN" in sql:
        raise SystemExit("visits still enumerates hospitals in a CHECK constraint")
    connection.execute(
        "INSERT INTO visits (id, hospital, visit_date, department_code, clinic_code, "
        "clinic_session, patient_number, state, created_at) "
        "VALUES ('cm-third', 'synthetic-third', '2026-09-27', 'MED', 'MED-1', "
        "'morning', 1, 'draft', '2026-09-27T00:00:00Z')"
    )
    connection.execute("DELETE FROM visits WHERE id = 'cm-third'")


if __name__ == "__main__":
    main()
