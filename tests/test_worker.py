import asyncio
import logging
import subprocess
from urllib.parse import parse_qs, urlsplit

from httpx import ASGITransport, AsyncClient

import worker
from local_runtime import create_local_app, load_local_settings
from next_is_you.line_login import VerifiedLineIdentity
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
    assert "/assets/app.js" in index.text
    assert script.status_code == 200
    assert script.text == 'fetch("/api/healthz")'
    assert health.status_code == 200
    assert health.json() == {"status": "ok", "mode": "local-development"}


def test_local_settings_load_from_root_dotenv_format_without_test_mode(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "LINE_LOGIN_CHANNEL_ID=local-id\n"
        'LINE_LOGIN_CHANNEL_SECRET="local-secret"\n'
        "LINE_LOGIN_REDIRECT_URI=https://localhost/auth/line/callback\n"
        "SESSION_SIGNING_SECRET=local-session-signing-secret-with-32-bytes\n"
        "ORGANIZER_LINE_SUBJECTS=local-organizer, another-organizer\n"
        "NIY006_LOCAL_TEST_MODE=1\n",
        encoding="utf-8",
    )

    settings = load_local_settings(env_file)

    assert settings.channel_id == "local-id"
    assert settings.channel_secret == "local-secret"
    assert settings.redirect_uri == "https://localhost/auth/line/callback"
    assert settings.organizer_subjects == {"local-organizer", "another-organizer"}
    assert settings.ready


def test_local_app_without_dotenv_fails_closed_and_keeps_test_controls_disabled(
    monkeypatch, tmp_path
):
    monkeypatch.setattr("local_runtime.ROOT", tmp_path)
    app_without_env = create_local_app()

    assert app_without_env.state.line_login_settings is not None
    assert not app_without_env.state.line_login_settings.ready

    async def request_test_control():
        async with AsyncClient(
            transport=ASGITransport(app=app_without_env),
            base_url="http://worker.local",
        ) as client:
            return (
                await client.get("/auth/line"),
                await client.post("/__niy006_test/snapshot"),
            )

    login, test_control = asyncio.run(request_test_control())

    assert login.status_code == 503
    assert test_control.status_code == 404


def test_local_launch_uses_root_dotenv_settings_but_ignores_test_mode(
    monkeypatch, tmp_path
):
    monkeypatch.setattr("local_runtime.ROOT", tmp_path)
    (tmp_path / ".env").write_text(
        "LINE_LOGIN_CHANNEL_ID=local-id\n"
        "LINE_LOGIN_CHANNEL_SECRET=local-secret\n"
        "LINE_LOGIN_REDIRECT_URI=https://localhost/auth/line/callback\n"
        "SESSION_SIGNING_SECRET=local-session-signing-secret-with-32-bytes\n"
        "ORGANIZER_LINE_SUBJECTS=local-organizer\n"
        "NIY006_LOCAL_TEST_MODE=1\n",
        encoding="utf-8",
    )

    local_app = create_local_app()

    assert local_app.state.line_login_settings.ready
    assert local_app.state.send_gate is None

    async def request_test_control():
        async with AsyncClient(
            transport=ASGITransport(app=local_app),
            base_url="http://worker.local",
        ) as client:
            return await client.post("/__niy006_test/snapshot")

    response = asyncio.run(request_test_control())

    assert response.status_code == 404


def test_local_runtime_keeps_dotenv_values_server_side_and_uses_fake_oauth(
    monkeypatch, tmp_path, caplog
):
    values = {
        "LINE_LOGIN_CHANNEL_ID": "local-channel-id-marker",
        "LINE_LOGIN_CHANNEL_SECRET": "local-channel-secret-marker",
        "LINE_LOGIN_REDIRECT_URI": "https://redirect-uri-marker.invalid/auth/line/callback",
        "SESSION_SIGNING_SECRET": "local-session-secret-marker-with-32-bytes",
        "ORGANIZER_LINE_SUBJECTS": "local-organizer-marker",
        "LINE_CHANNEL_ACCESS_TOKEN": "local-push-token-marker",
        "NIY006_LOCAL_TEST_MODE": "1",
    }
    (tmp_path / ".env").write_text(
        "".join(f"{name}={value}\n" for name, value in values.items()),
        encoding="utf-8",
    )
    assets = tmp_path / "dist"
    assets.mkdir()
    (assets / "index.html").write_text(
        '<script type="module" src="/assets/app.js"></script>', encoding="utf-8"
    )
    (assets / "assets").mkdir()
    (assets / "assets" / "app.js").write_text('fetch("/api/healthz")', encoding="utf-8")
    monkeypatch.setattr("local_runtime.ROOT", tmp_path)
    monkeypatch.setattr(worker, "STATIC_ASSET_ROOT", assets)

    class FakeOAuth:
        calls = []

        async def verify_login(self, **kwargs):
            self.calls.append(kwargs)
            return VerifiedLineIdentity("not-an-organizer", "fake-user-token")

    fake_oauth = FakeOAuth()
    caplog.set_level(logging.DEBUG)
    local_app = create_local_app(line_client=fake_oauth)

    async def exercise_local_runtime():
        async with AsyncClient(
            transport=ASGITransport(app=local_app),
            base_url="https://localhost",
        ) as client:
            start = await client.get("/auth/line", follow_redirects=False)
            query = parse_qs(urlsplit(start.headers["location"]).query)
            callback = await client.get(
                "/auth/line/callback",
                params={"code": "fake-code", "state": query["state"][0]},
            )
            index = await client.get("/")
            script = await client.get("/assets/app.js")
            test_control = await client.post("/__niy006_test/snapshot")
            return start, callback, index, script, test_control

    start, callback, index, script, test_control = asyncio.run(exercise_local_runtime())

    assert start.status_code == 302
    assert callback.status_code == 403
    assert len(fake_oauth.calls) == 1
    oauth_call = fake_oauth.calls[0]
    assert oauth_call["code"] == "fake-code"
    assert oauth_call["redirect_uri"] == values["LINE_LOGIN_REDIRECT_URI"]
    assert oauth_call["channel_id"] == values["LINE_LOGIN_CHANNEL_ID"]
    assert oauth_call["channel_secret"] == values["LINE_LOGIN_CHANNEL_SECRET"]
    assert oauth_call["nonce"]
    assert local_app.state.send_gate is None
    assert test_control.status_code == 404
    for response_text in (start.text, callback.text, index.text, script.text):
        assert all(
            value not in response_text
            for name, value in values.items()
            if name != "NIY006_LOCAL_TEST_MODE"  # a one-character flag, not a secret
        )
    logged_names = [
        name
        for name, value in values.items()
        if name != "NIY006_LOCAL_TEST_MODE" and value in caplog.text
    ]
    assert not logged_names, f"configuration values were logged: {logged_names}"


def test_env_files_are_ignored_but_template_is_tracked():
    for path in (
        ".env",
        ".env.local",
        ".env.example",
        ".dev.vars",
        ".dev.vars.local",
    ):
        ignored = subprocess.run(["git", "check-ignore", "--quiet", path], check=False)
        assert ignored.returncode == 0, f"{path} should be ignored"

    tracked = subprocess.run(
        ["git", "ls-files", "--error-unmatch", ".env_template"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert tracked.returncode == 0
