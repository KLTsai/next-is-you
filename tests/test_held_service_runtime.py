"""Genuine local bindings with fixture identity, never deployed/provider evidence."""

import json
import os
import signal
import ssl
import subprocess
import sys
import time
from contextlib import contextmanager
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from playwright.sync_api import expect, sync_playwright

from next_is_you.auth import SESSION_COOKIE_NAME, issue_session
from test_worker_startup import ROOT, _free_loopback_port, _process_output
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


@contextmanager
def held_worker(port, persist, environment):
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "pywrangler",
            "dev",
            "--local",
            "--config",
            str(CONFIG),
            "--persist-to",
            str(persist),
            "--port",
            str(port),
            "--local-protocol",
            "https",
            "--show-interactive-dev-session=false",
            "--var",
            "LINE_LOGIN_CHANNEL_ID:fixture-channel",
            "--var",
            "LINE_LOGIN_CHANNEL_SECRET:fixture-channel-secret",
            "--var",
            f"LINE_LOGIN_REDIRECT_URI:https://127.0.0.1:{port}/auth/line/callback",
            "--var",
            f"SESSION_SIGNING_SECRET:{SECRET}",
            "--var",
            "ORGANIZER_LINE_SUBJECTS:fixture-organizer",
        ],
        cwd=ROOT,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,
    )
    origin = f"https://127.0.0.1:{port}"
    try:
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise AssertionError(_process_output(process))
            try:
                if request(origin, "/api/healthz")[0] == 200:
                    break
            except (OSError, URLError):
                pass
            time.sleep(0.25)
        else:
            raise AssertionError("Held local Worker startup timed out")
        yield origin
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
        try:
            _process_output(process)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.communicate(timeout=10)


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
    port = _free_loopback_port()
    session = issue_session(
        "fixture-organizer", "organizer", SECRET, now=int(time.time())
    )
    with held_worker(port, persist, environment) as origin:
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
    with held_worker(port, persist, environment) as origin:
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
