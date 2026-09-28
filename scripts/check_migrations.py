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
    if not {"latest_source_read_status", "latest_source_read_reason"} <= visit_columns:
        raise SystemExit("source read migration columns are missing from visits")
    print(f"Applied {len(MIGRATIONS)} migrations; SQLite schema checks passed.")


if __name__ == "__main__":
    main()
