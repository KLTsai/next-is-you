from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
WRANGLER_CONFIG = ROOT / "wrangler.niy006.test.jsonc"


def _free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _process_output(process: subprocess.Popen[str]) -> str:
    output, _ = process.communicate(timeout=10)
    return output or ""


def test_wrangler_worker_starts_and_serves_health_endpoint(tmp_path) -> None:
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "index.html").write_text("<!doctype html>", encoding="utf-8")
    port = _free_loopback_port()
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
        ],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert migrations.returncode == 0, migrations.stdout + migrations.stderr
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
            "--show-interactive-dev-session=false",
        ],
        cwd=ROOT,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,
    )

    try:
        deadline = time.monotonic() + 90
        response_body = None
        while time.monotonic() < deadline:
            if process.poll() is not None:
                output = _process_output(process)
                raise AssertionError(
                    "Wrangler exited before serving the Worker:\n" + output
                )
            try:
                with urlopen(
                    f"http://127.0.0.1:{port}/api/healthz", timeout=1
                ) as response:
                    if response.status == 200:
                        response_body = response.read()
                        break
            except (OSError, URLError):
                pass
            time.sleep(0.25)
        else:
            output = _process_output(process)
            raise AssertionError(
                "Wrangler did not serve the Worker before the timeout:\n" + output
            )

        assert response_body == b'{"status":"ok","mode":"local-development"}'

        with urlopen(
            Request(
                f"http://127.0.0.1:{port}/__niy006_test/snapshot",
                data=b"{}",
                headers={"content-type": "application/json"},
                method="POST",
            ),
            timeout=10,
        ) as response:
            assert response.status == 200
            snapshot = json.loads(response.read())
        assert snapshot["events"] == []
        assert snapshot["line_requests"] == []

        with urlopen(
            f"http://127.0.0.1:{port}/cdn-cgi/local/scheduled", timeout=10
        ) as response:
            assert response.status == 200
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
        try:
            _process_output(process)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.communicate(timeout=10)
