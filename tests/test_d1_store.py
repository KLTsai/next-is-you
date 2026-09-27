from __future__ import annotations

from typing import Any

import pytest

from next_is_you.persistence import CloudflareD1Store, Statement


class Prepared:
    def __init__(self, sql: str, values: tuple[Any, ...] = ()) -> None:
        self.sql = sql
        self.values = values

    def bind(self, *values: Any) -> "Prepared":
        return Prepared(self.sql, values)

    async def run(self) -> dict[str, Any]:
        return {"meta": {"changes": 2}}

    async def all(self) -> dict[str, Any]:
        return {"results": [{"id": "v1", "state": "active"}]}


class D1Binding:
    def __init__(self) -> None:
        self.batched: list[Prepared] = []

    def prepare(self, sql: str) -> Prepared:
        return Prepared(sql)

    async def batch(self, statements: list[Prepared]) -> list[dict[str, Any]]:
        self.batched = statements
        return [{"meta": {"changes": 1}} for _ in statements]


@pytest.mark.asyncio
async def test_d1_store_uses_bound_prepared_statements_and_reads_results() -> None:
    binding = D1Binding()
    store = CloudflareD1Store(binding)

    assert await store.execute(Statement("UPDATE visits SET state = ?", ("active",))) == 2
    assert await store.fetch_all(Statement("SELECT id, state FROM visits WHERE id = ?", ("v1",))) == [
        {"id": "v1", "state": "active"}
    ]


@pytest.mark.asyncio
async def test_d1_store_batches_statements_and_reports_each_change_count() -> None:
    binding = D1Binding()
    store = CloudflareD1Store(binding)

    changes = await store.batch(
        [
            Statement("DELETE FROM visits WHERE id = ?", ("v1",)),
            Statement("DELETE FROM visits WHERE id = ?", ("v2",)),
        ]
    )

    assert changes == [1, 1]
    assert [item.values for item in binding.batched] == [("v1",), ("v2",)]
