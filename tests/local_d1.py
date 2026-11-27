"""The local stand-in for the D1 database, shared by every test that needs one.

`LocalD1` is the D1 binding, the thing the Worker's environment holds as `DB`.
`LocalStore` is the product's own D1 adapter over it, for code that takes a
repository store. Both reach the same SQLite database through `connection`.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Sequence

from next_is_you.persistence import CloudflareD1Store

MIGRATIONS = sorted((Path(__file__).resolve().parents[1] / "migrations").glob("*.sql"))


class Prepared:
    def __init__(self, database: LocalD1, sql: str, values: tuple[Any, ...] = ()):
        self.database = database
        self.sql = sql
        self.values = values

    def bind(self, *values: Any) -> Prepared:
        return Prepared(self.database, self.sql, values)

    async def run(self) -> dict[str, Any]:
        cursor = self.database.connection.execute(self.sql, self.values)
        return {"meta": {"changes": cursor.rowcount}}

    async def all(self) -> dict[str, Any]:
        cursor = self.database.connection.execute(self.sql, self.values)
        return {"results": [dict(row) for row in cursor.fetchall()]}


class LocalD1:
    """An in-memory database with every migration applied and foreign keys on."""

    def __init__(self) -> None:
        # An in-process HTTP app may be served from another thread.
        self.connection = sqlite3.connect(
            ":memory:", isolation_level=None, check_same_thread=False
        )
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        for migration in MIGRATIONS:
            self.connection.executescript(migration.read_text(encoding="utf-8"))

    def prepare(self, sql: str) -> Prepared:
        return Prepared(self, sql)

    async def batch(self, statements: Sequence[Prepared]) -> list[dict[str, Any]]:
        self.connection.execute("BEGIN")
        try:
            results = [
                self.connection.execute(item.sql, item.values).rowcount
                for item in statements
            ]
        except Exception:
            self.connection.execute("ROLLBACK")
            raise
        self.connection.execute("COMMIT")
        return [{"meta": {"changes": changes}} for changes in results]


class LocalStore(CloudflareD1Store):
    """A repository store over its own local database."""

    def __init__(self, database: LocalD1 | None = None) -> None:
        self.database = database or LocalD1()
        super().__init__(self.database)

    @property
    def connection(self) -> sqlite3.Connection:
        return self.database.connection
