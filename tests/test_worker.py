import asyncio

from httpx import ASGITransport, AsyncClient

import worker
from worker import LineLoginSettings, app


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


def test_line_login_settings_require_an_https_callback_without_userinfo():
    values = {
        "line_login_channel_id": "local-channel",
        "line_login_channel_secret": "local-channel-secret",
        "line_login_redirect_uri": "https://family.example/auth/line/callback",
        "session_secret": "local-test-secret-with-at-least-32-bytes",
        "organizer_subjects": {"local-organizer"},
    }

    assert LineLoginSettings.from_mapping(values).ready
    assert not LineLoginSettings.from_mapping(
        values | {"line_login_redirect_uri": "http://family.example/callback"}
    ).ready
    assert not LineLoginSettings.from_mapping(
        values | {"line_login_redirect_uri": "https://user@family.example/callback"}
    ).ready


def test_api_routes_are_registered_before_the_static_fallback():
    route_paths = [getattr(route, "path", None) for route in app.routes]

    assert route_paths.index("/api/healthz") < route_paths.index("/{path:path}")


def test_local_worker_serves_ui_and_built_assets_from_its_origin(tmp_path, monkeypatch):
    (tmp_path / "index.html").write_text(
        '<script type="module" src="/assets/app.js"></script>', encoding="utf-8"
    )
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app.js").write_text(
        'fetch("/api/healthz")', encoding="utf-8"
    )
    monkeypatch.setattr(worker, "STATIC_ASSET_ROOT", tmp_path)

    async def request_local_app():
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://worker.local",
        ) as client:
            return (
                await client.get("/"),
                await client.get("/assets/app.js"),
                await client.get("/api/healthz"),
            )

    index, script, health = asyncio.run(request_local_app())

    assert index.status_code == 200
    assert '/assets/app.js' in index.text
    assert script.status_code == 200
    assert script.text == 'fetch("/api/healthz")'
    assert health.status_code == 200
    assert health.json() == {"status": "ok", "mode": "local-development"}
