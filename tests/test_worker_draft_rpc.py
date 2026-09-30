from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import time
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
WRANGLER_CONFIG = ROOT / "wrangler.niy006.test.jsonc"


def _free_loopback_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _request(url: str, *, method: str = "GET", body=None, headers=None):
    data = (
        None
        if body is None
        else body.encode()
        if isinstance(body, str)
        else json.dumps(body).encode()
    )
    request = Request(url, data=data, headers=headers or {}, method=method)
    try:
        with urlopen(request, timeout=10) as response:
            return response.status, response.read(), response.headers
    except HTTPError as error:
        return error.code, error.read(), error.headers


def test_wrangler_draft_save_crosses_real_worker_durable_object_binding(tmp_path):
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "index.html").write_text("<!doctype html>", encoding="utf-8")
    persist = tmp_path / "wrangler-state"
    persist.mkdir()
    environment = os.environ.copy()
    environment["CI"] = "1"
    migrations = subprocess.run(
        [
            sys.executable,
            "-m",
            "pywrangler",
            "d1",
            "migrations",
            "apply",
            "next-is-you-niy006-local-test",
            "--local",
            "--config",
            str(WRANGLER_CONFIG),
            "--persist-to",
            str(persist),
        ],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert migrations.returncode == 0, migrations.stdout + migrations.stderr

    seed_recipient = subprocess.run(
        [
            sys.executable,
            "-m",
            "pywrangler",
            "d1",
            "execute",
            "next-is-you-niy006-local-test",
            "--local",
            "--config",
            str(WRANGLER_CONFIG),
            "--persist-to",
            str(persist),
            "--command",
            "INSERT INTO recipients (id, line_subject, display_name, consented_at, friendship_checked_at, created_at) VALUES ('niy024-local-recipient', 'niy024-local-subject', 'Synthetic recipient', '2026-09-29T00:00:00Z', '2026-09-29T00:00:00Z', '2026-09-29T00:00:00Z')",
        ],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert seed_recipient.returncode == 0, seed_recipient.stdout + seed_recipient.stderr

    port = _free_loopback_port()
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "pywrangler",
            "dev",
            "--local",
            "--config",
            str(WRANGLER_CONFIG),
            "--assets",
            str(assets),
            "--port",
            str(port),
            "--persist-to",
            str(persist),
            "--show-interactive-dev-session=false",
        ],
        cwd=ROOT,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,
    )
    base_url = f"http://127.0.0.1:{port}"
    try:
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            if process.poll() is not None:
                output, _ = process.communicate(timeout=10)
                raise AssertionError(
                    "Wrangler exited before serving the Worker:\n" + output
                )
            try:
                status, body, _ = _request(base_url + "/api/healthz")
                if status == 200:
                    assert json.loads(body) == {
                        "status": "ok",
                        "mode": "local-development",
                    }
                    break
            except (OSError, URLError):
                pass
            time.sleep(0.25)
        else:
            output, _ = process.communicate(timeout=10)
            raise AssertionError(
                "Wrangler did not serve the Worker before timeout:\n" + output
            )

        status, _, login_headers = _request(
            base_url + "/__niy006_test/organizer-session",
            method="POST",
            body={},
            headers={"content-type": "application/json"},
        )
        assert status == 200
        cookies = SimpleCookie()
        for set_cookie in login_headers.get_all("Set-Cookie", []):
            cookies.load(set_cookie)
        session = cookies["__Host-ny_session"].value
        csrf = cookies["__Host-ny_csrf"].value
        authorized = {
            "cookie": f"__Host-ny_session={session}; __Host-ny_csrf={csrf}",
            "x-csrf-token": csrf,
            "content-type": "application/json",
        }
        draft = {
            "hospital": "ntuh-main",
            "date": "2099-09-29",
            "department_code": "SYN",
            "clinic_code": "SYN-1",
            "session": "morning",
            "patient_number": 85,
            "recipient_ids": ["niy024-local-recipient"],
        }
        status, body, _ = _request(
            base_url + "/api/organizer/visits",
            method="POST",
            body=draft,
            headers=authorized,
        )
        assert status == 201, body.decode()
        visit_id = json.loads(body)["id"]
        edited = {
            **draft,
            "date": "2099-09-30",
            "clinic_code": "SYN-2",
            "session": "evening",
            "patient_number": 86,
        }
        status, body, _ = _request(
            base_url + f"/api/organizer/visits/{visit_id}",
            method="PATCH",
            body=edited,
            headers=authorized,
        )

        assert status == 200, body.decode()
        assert json.loads(body) == {"id": visit_id, "state": "draft"}
        status, body, _ = _request(
            base_url + "/api/organizer/visits", headers=authorized
        )
        assert status == 200
        saved = next(
            item for item in json.loads(body)["visits"] if item["id"] == visit_id
        )
        assert (saved["date"], saved["clinic_code"], saved["session"]) == (
            "2099-09-30",
            "SYN-2",
            "evening",
        )

        status, body, _ = _request(
            base_url + "/__niy006_test/seed",
            method="POST",
            body={
                "visit_id": "niy024-local-active",
                "recipient_id": "niy024-local-recipient",
                "visit_day": "2099-10-01",
                "patient_number": 85,
                "now": "2026-09-29T00:00:00Z",
            },
            headers={"content-type": "application/json"},
        )
        assert status == 201, body.decode()

        cases = [
            ("unauthorized", {}, draft, 401, None),
            (
                "invalid-csrf",
                {"cookie": f"__Host-ny_session={session}; __Host-ny_csrf={csrf}"},
                draft,
                403,
                None,
            ),
            ("invalid-json", authorized, "{", 400, "invalid_request"),
            ("missing-fields", authorized, {}, 400, "invalid_request"),
            (
                "invalid-lifecycle",
                authorized,
                edited,
                409,
                "invalid_lifecycle_state",
                "niy024-local-active",
            ),
        ]
        for case_data in cases:
            (
                case,
                request_headers,
                request_body,
                expected_status,
                error_code,
                *target,
            ) = case_data
            target_id = target[0] if target else visit_id
            status, response_body, _ = _request(
                base_url + f"/api/organizer/visits/{target_id}",
                method="PATCH",
                body=request_body,
                headers=request_headers,
            )
            assert status == expected_status, f"{case}: {response_body.decode()}"
            if error_code:
                assert json.loads(response_body) == {"error": {"code": error_code}}

    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
        try:
            process.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.communicate(timeout=10)
