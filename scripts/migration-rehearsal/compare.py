"""Compare two snapshots taken with snapshot.sql around a rehearsed migration.

Usage: python scripts/migration-rehearsal/compare.py before.json after.json

Each file is the output of `wrangler d1 execute ... --json --command "<snapshot.sql>"`.
Exits non-zero unless every table keeps every row unchanged, the foreign key
check is empty, and d1_migrations gained rows only at its end.
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


def compare(before: list[dict], after: list[dict]) -> list[str]:
    if len(before) != len(SECTIONS) or len(after) != len(SECTIONS):
        return [f"expected {len(SECTIONS)} result sets from snapshot.sql"]
    problems = []
    lines = []
    for name, old, new in zip(SECTIONS, before, after):
        old_rows, new_rows = old["results"], new["results"]
        lines.append(f"{name:18} before={len(old_rows):4} after={len(new_rows):4}")
        if name == "d1_migrations":
            if new_rows[: len(old_rows)] != old_rows:
                problems.append("d1_migrations lost or reordered earlier entries")
            added = [row["name"] for row in new_rows[len(old_rows) :]]
            lines[-1] += f" applied={added}"
        elif name == "foreign_key_check":
            if new_rows:
                problems.append(f"foreign key violations after: {new_rows}")
        elif old_rows != new_rows:
            missing = [row for row in old_rows if row not in new_rows]
            problems.append(
                f"{name}: {len(missing)} row(s) missing or changed, "
                f"{len(new_rows) - len(old_rows):+d} in count"
            )
    print("\n".join(lines))
    return problems


def main() -> None:
    before_path, after_path = (Path(arg) for arg in sys.argv[1:3])
    problems = compare(
        json.loads(before_path.read_text(encoding="utf-8")),
        json.loads(after_path.read_text(encoding="utf-8")),
    )
    if problems:
        raise SystemExit("\n".join(["Rehearsal FAILED:", *problems]))
    print("Rehearsal passed: every row unchanged, foreign key check empty.")


if __name__ == "__main__":
    main()
