import asyncio

from httpx import ASGITransport, AsyncClient

from worker import app


def test_local_worker_health_is_explicitly_non_production():
    async def request_health():
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            return await client.get("/api/healthz")

    response = asyncio.run(request_health())

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "mode": "local-development"}
