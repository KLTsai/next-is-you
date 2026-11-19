"""The comparison that decides whether a Staging migration rehearsal passed.

Evidence: fixture/mock. Issue #111: a rehearsal passes only if the rehearsed
migration was applied and every row survived it.
"""

from __future__ import annotations

import copy
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "rehearsal_compare", ROOT / "scripts" / "migration-rehearsal" / "compare.py"
)
rehearsal_compare = importlib.util.module_from_spec(_spec)
sys.modules["rehearsal_compare"] = rehearsal_compare
_spec.loader.exec_module(rehearsal_compare)

REHEARSED = "0007_visits_hospital_unconstrained.sql"


def _snapshot(migrations: list[str]) -> list[dict]:
    return [
        {"results": [{"name": name} for name in migrations]},
        {"results": [{"id": "rehearsal-r-1"}]},
        {"results": []},
        {"results": [{"id": "rehearsal-v-active", "state": "active"}]},
        {
            "results": [
                {"visit_id": "rehearsal-v-active", "recipient_id": "rehearsal-r-1"}
            ]
        },
        {"results": [{"id": "rehearsal-e-near-01"}]},
        {"results": []},
    ]


BEFORE = _snapshot(["0006_preflight_sweep.sql"])
AFTER = _snapshot(["0006_preflight_sweep.sql", REHEARSED])


def test_every_row_kept_and_the_migration_applied_passes() -> None:
    assert rehearsal_compare.compare(BEFORE, AFTER, REHEARSED) == []


def test_a_snapshot_where_the_migration_never_applied_fails() -> None:
    problems = rehearsal_compare.compare(BEFORE, copy.deepcopy(BEFORE), REHEARSED)

    assert problems == [f"{REHEARSED} was not applied between the snapshots"]


def test_a_missing_child_row_fails() -> None:
    after = copy.deepcopy(AFTER)
    after[4]["results"] = []

    problems = rehearsal_compare.compare(BEFORE, after, REHEARSED)

    assert problems == ["visit_recipients: 1 row(s) missing or changed, -1 in count"]


def test_a_changed_value_fails() -> None:
    after = copy.deepcopy(AFTER)
    after[3]["results"][0]["state"] = "stopped"

    problems = rehearsal_compare.compare(BEFORE, after, REHEARSED)

    assert problems == ["visits: 1 row(s) missing or changed, +0 in count"]


def test_a_foreign_key_violation_fails() -> None:
    after = copy.deepcopy(AFTER)
    after[6]["results"] = [{"table": "visit_recipients", "parent": "visits"}]

    problems = rehearsal_compare.compare(BEFORE, after, REHEARSED)

    assert problems == [
        "foreign key violations after: [{'table': 'visit_recipients', 'parent': 'visits'}]"
    ]
