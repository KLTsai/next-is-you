"""Compare two snapshots taken with snapshot.sql around a rehearsed migration.

Usage:
    python scripts/migration-rehearsal/compare.py before.json after.json <migration file name>

Each file is the output of `d1 execute ... --json --command "<snapshot.sql>"`
(see docs/CI-CD.md, Staging rehearsal). Exits non-zero unless the named
migration was applied between the two snapshots, every other table keeps every
row unchanged, and the foreign key check is empty.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

SECTIONS = (
    "d1_migrations",
    "recipients",
    "invitations",
    "visits",
    "visit_recipients",
    "outbound_events",
    "foreign_key_check",
)


def compare(before: list[dict], after: list[dict], migration: str) -> list[str]:
    if len(before) != len(SECTIONS) or len(after) != len(SECTIONS):
        return [f"expected {len(SECTIONS)} result sets from snapshot.sql"]
    problems = []
    for name, old, new in zip(SECTIONS, before, after):
        old_rows, new_rows = old["results"], new["results"]
        print(f"{name:18} before={len(old_rows):4} after={len(new_rows):4}")
        if name == "d1_migrations":
            if new_rows[: len(old_rows)] != old_rows:
                problems.append("d1_migrations lost or reordered earlier entries")
            added = [row["name"] for row in new_rows[len(old_rows) :]]
            if migration not in added:
                problems.append(f"{migration} was not applied between the snapshots")
        elif name == "foreign_key_check":
            if new_rows:
                problems.append(f"foreign key violations after: {new_rows}")
        elif old_rows != new_rows:
            missing = [row for row in old_rows if row not in new_rows]
            problems.append(
                f"{name}: {len(missing)} row(s) missing or changed, "
                f"{len(new_rows) - len(old_rows):+d} in count"
            )
    return problems


def main() -> None:
    if len(sys.argv) != 4:
        raise SystemExit(__doc__)
    before_path, after_path, migration = sys.argv[1:4]
    problems = compare(
        json.loads(Path(before_path).read_text(encoding="utf-8")),
        json.loads(Path(after_path).read_text(encoding="utf-8")),
        migration,
    )
    if problems:
        raise SystemExit("\n".join(["Rehearsal FAILED:", *problems]))
    print(
        f"Rehearsal passed: {migration} applied, every row unchanged, no foreign key violation."
    )


if __name__ == "__main__":
    main()
