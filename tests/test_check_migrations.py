"""The migration check that CI runs, fed the real migrations plus a synthetic next one.

Evidence: fixture/mock. Issue #111: every migration from 0008 on carries a risk
header, and statements that can lose or change stored rows need a matching class.
"""

from __future__ import annotations

import importlib.util
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "check_migrations", ROOT / "scripts" / "check_migrations.py"
)
check_migrations = importlib.util.module_from_spec(_spec)
sys.modules["check_migrations"] = check_migrations
_spec.loader.exec_module(check_migrations)

ADD_COLUMN = "ALTER TABLE recipients ADD COLUMN nickname TEXT;\n"


def _migrations_with_next(tmp_path: Path, text: str) -> Path:
    directory = tmp_path / "migrations"
    shutil.copytree(ROOT / "migrations", directory)
    (directory / "0008_synthetic_next.sql").write_text(text, encoding="utf-8")
    return directory


def _header(risk: str) -> str:
    return (
        f"-- Risk: {risk}\n"
        "-- Data at risk: none\n"
        "-- Compatibility: previous code runs on the new schema; new code runs on the old schema\n"
    )


def test_the_repository_migrations_pass() -> None:
    check_migrations.main(ROOT / "migrations")


def test_a_new_migration_without_a_risk_header_fails(tmp_path: Path) -> None:
    directory = _migrations_with_next(tmp_path, ADD_COLUMN)

    with pytest.raises(
        SystemExit, match="0008_synthetic_next.sql: missing risk header"
    ):
        check_migrations.main(directory)


def test_an_unknown_risk_class_fails(tmp_path: Path) -> None:
    directory = _migrations_with_next(tmp_path, _header("low") + ADD_COLUMN)

    with pytest.raises(
        SystemExit, match="0008_synthetic_next.sql: unknown risk class 'low'"
    ):
        check_migrations.main(directory)


RISKY_STATEMENTS = {
    "drop table": (
        "CREATE TABLE scratch (id TEXT);\nDROP TABLE scratch;\n",
        ("destructive", "rebuild"),
    ),
    "drop column": (
        "ALTER TABLE recipients ADD COLUMN scratch TEXT;\n"
        "ALTER TABLE recipients DROP COLUMN scratch;\n",
        ("destructive", "rebuild"),
    ),
    "rename": (
        "CREATE TABLE scratch (id TEXT);\nALTER TABLE scratch RENAME TO scratch_two;\n",
        ("incompatible", "destructive", "rebuild"),
    ),
    "update": (
        "UPDATE recipients SET display_name = display_name;\n",
        ("data-dependent", "destructive", "rebuild"),
    ),
    "delete": (
        "DELETE FROM invitations WHERE 0;\n",
        ("data-dependent", "destructive", "rebuild"),
    ),
    "insert select": (
        "CREATE TABLE scratch (id TEXT);\n"
        "INSERT INTO scratch (id) SELECT id FROM recipients;\n",
        ("data-dependent", "destructive", "rebuild"),
    ),
}


@pytest.mark.parametrize("statement", sorted(RISKY_STATEMENTS))
def test_a_risky_statement_under_a_lower_class_fails(
    tmp_path: Path, statement: str
) -> None:
    sql, _allowed = RISKY_STATEMENTS[statement]
    directory = _migrations_with_next(tmp_path, _header("additive") + sql)

    with pytest.raises(
        SystemExit, match=f"0008_synthetic_next.sql: {statement} needs risk class"
    ):
        check_migrations.main(directory)


@pytest.mark.parametrize("statement", sorted(RISKY_STATEMENTS))
def test_a_risky_statement_under_a_matching_class_passes(
    tmp_path: Path, statement: str
) -> None:
    sql, allowed = RISKY_STATEMENTS[statement]
    for risk in allowed:
        directory = _migrations_with_next(tmp_path / risk, _header(risk) + sql)
        check_migrations.main(directory)


def test_a_cascade_clause_is_not_mistaken_for_a_delete(tmp_path: Path) -> None:
    sql = (
        "CREATE TABLE notes (\n"
        "    recipient_id TEXT NOT NULL REFERENCES recipients(id) ON DELETE CASCADE ON UPDATE CASCADE\n"
        ");\n"
        "-- A comment that says DROP TABLE or DELETE FROM is not a statement.\n"
    )
    directory = _migrations_with_next(tmp_path, _header("additive") + sql)

    check_migrations.main(directory)


def test_a_new_migration_with_a_risk_header_passes(tmp_path: Path) -> None:
    directory = _migrations_with_next(tmp_path, _header("additive") + ADD_COLUMN)

    check_migrations.main(directory)
