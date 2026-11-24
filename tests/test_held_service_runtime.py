"""Genuine local bindings with fixture identity, never deployed/provider evidence."""

import json
import os
import ssl
import subprocess
import sys
import time
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from playwright.sync_api import expect, sync_playwright

from local_worker import ROOT, local_worker, local_worker_on_known_port
from next_is_you.auth import SESSION_COOKIE_NAME, issue_session
from worktree_bootstrap import require_frontend_toolchain


CONFIG = ROOT / "wrangler.production.example.jsonc"
SECRET = "fixture-session-signing-secret-at-least-32-bytes"


def request(origin, path, *, session=None, body=None, method="GET"):
    headers = {}
    if session is not None:
        headers = {
            "cookie": f"{SESSION_COOKIE_NAME}={session.value}",
            "x-csrf-token": session.csrf_token,
        }
    if body is not None:
        headers["content-type"] = "application/json"
    # Wrangler's local HTTPS certificate is self-signed. This exception is
    # confined to loopback test requests and must never be used remotely.
    assert origin.startswith("https://127.0.0.1:")
    req = Request(
        origin + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers=headers,
        method=method,
    )
    try:
        with urlopen(
            req, context=ssl._create_unverified_context(), timeout=10
        ) as response:
            return response.status, response.read()
    except HTTPError as error:
        return error.code, error.read()


def held_command(persist):
    def command(port):
        return [
            sys.executable,
            "-m",
            "pywrangler",
            "dev",
            "--local",
            "--ip",
            "127.0.0.1",
            "--config",
            str(CONFIG),
            "--persist-to",
            str(persist),
            "--port",
            str(port),
            "--inspector-port",
            "0",
            "--local-protocol",
            "https",
            "--show-interactive-dev-session=false",
            "--var",
            "LINE_LOGIN_CHANNEL_ID:fixture-channel",
            "--var",
            "LINE_LOGIN_CHANNEL_SECRET:fixture-channel-secret",
            "--var",
            # The Worker only trusts a callback on the origin it serves.
            f"LINE_LOGIN_REDIRECT_URI:https://127.0.0.1:{port}/auth/line/callback",
            "--var",
            f"SESSION_SIGNING_SECRET:{SECRET}",
            "--var",
            "ORGANIZER_LINE_SUBJECTS:fixture-organizer",
        ]

    return command


def test_held_native_configuration_and_recovery_hold_persist_across_restart(tmp_path):
    environment = {
        **os.environ,
        "CI": "1",
        "CLOUDFLARE_LOAD_DEV_VARS_FROM_DOT_ENV": "false",
    }
    require_frontend_toolchain()
    subprocess.run(
        ["npm", "run", "build"],
        cwd=ROOT,
        env=environment,
        check=True,
        capture_output=True,
    )
    persist = tmp_path / "state"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pywrangler",
            "d1",
            "migrations",
            "apply",
            "next-is-you-production",
            "--local",
            "--config",
            str(CONFIG),
            "--persist-to",
            str(persist),
        ],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    session = issue_session(
        "fixture-organizer", "organizer", SECRET, now=int(time.time())
    )
    command = held_command(persist)
    with local_worker_on_known_port(command, env=environment) as origin:
        assert json.loads(request(origin, "/api/healthz")[1])["mode"] == "held-service"
        assert request(origin, "/api/organizer/scheduler/status")[0] == 401
        assert (
            request(origin, "/__niy006_test/organizer-session", method="POST")[0] == 404
        )
        status, before = request(
            origin, "/api/organizer/scheduler/status", session=session
        )
        assert status == 200
        assert json.loads(before) == {
            "held": True,
            "configuration_hold": True,
            "recovery_hold": False,
            "hospital_reader_available": False,
        }
        # Invitation persistence exercises real local D1 without inventing
        # consent or using any production synthetic control endpoint.
        assert (
            request(
                origin,
                "/api/organizer/invitations",
                session=session,
                body={},
                method="POST",
            )[0]
            == 201
        )
        assert (
            request(
                origin,
                "/api/organizer/scheduler/recovery-hold",
                session=session,
                method="POST",
            )[0]
            == 204
        )
        assert (
            request(
                origin,
                "/api/organizer/scheduler/resume",
                session=session,
                body={"reconciled": True},
                method="POST",
            )[0]
            == 409
        )
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            context = browser.new_context(ignore_https_errors=True)
            context.route(
                "**/*",
                lambda route: (
                    route.continue_()
                    if route.request.url.startswith(origin + "/")
                    else route.abort()
                ),
            )
            page = context.new_page()
            page.goto(origin)
            expect(page.get_by_role("link", name="使用 LINE Login")).to_be_visible()
            expect(page.get_by_role("button", name="本機合成測試登入")).to_have_count(0)
            expect(page.locator("#service-status")).to_have_text("服務正常")
            context.close()
            browser.close()
    # The restart keeps the origin the session and callback were issued for.
    with local_worker(command(urlsplit(origin).port), env=environment) as origin:
        status, after = request(
            origin, "/api/organizer/scheduler/status", session=session
        )
        assert status == 200
        assert json.loads(after)["recovery_hold"] is True
        assert json.loads(after)["held"] is True
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pywrangler",
            "d1",
            "execute",
            "next-is-you-production",
            "--local",
            "--config",
            str(CONFIG),
            "--persist-to",
            str(persist),
            "--command",
            "SELECT COUNT(*) AS total FROM invitations",
            "--json",
        ],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    # pywrangler writes its command banner before Wrangler's JSON output.
    payload = result.stdout[result.stdout.index("[\n") :]
    assert json.loads(payload)[0]["results"] == [{"total": 1}]
