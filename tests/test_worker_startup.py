from __future__ import annotations

import json
import os
import subprocess
import sys
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from local_worker import ROOT, local_worker, wrangler_dev


WRANGLER_CONFIG = ROOT / "wrangler.niy006.test.jsonc"


@pytest.mark.parametrize("production", [False, True])
def test_wrangler_worker_starts_and_serves_health_endpoint(
    tmp_path, production
) -> None:
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "index.html").write_text("<!doctype html>", encoding="utf-8")
    persist_to = tmp_path / "wrangler-state"
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
            str(persist_to),
        ],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert migrations.returncode == 0, migrations.stdout + migrations.stderr
    with local_worker(
        wrangler_dev(
            WRANGLER_CONFIG,
            persist_to,
            "--assets",
            str(assets),
            *(["--var", "NIY_ENVIRONMENT:production"] if production else []),
        ),
        env=environment,
    ) as origin:
        with urlopen(origin + "/api/healthz", timeout=10) as response:
            response_body = response.read()
        assert json.loads(response_body) == {
            "status": "ok",
            "mode": "held-service" if production else "local-test",
        }

        if production:
            for operation in ("organizer-session", "seed", "snapshot", "observation"):
                with pytest.raises(HTTPError) as denied:
                    urlopen(
                        Request(
                            f"{origin}/__niy006_test/{operation}",
                            data=b"{}",
                            headers={"content-type": "application/json"},
                            method="POST",
                        ),
                        timeout=10,
                    )
                assert denied.value.code == 404
            with pytest.raises(HTTPError) as unavailable:
                urlopen(f"{origin}/auth/line", timeout=10)
            assert unavailable.value.code == 503
            with urlopen(f"{origin}/", timeout=10) as response:
                assert response.read() == b"<!doctype html>"
            with urlopen(f"{origin}/cdn-cgi/local/scheduled", timeout=10) as response:
                assert response.status == 200
            return

        with urlopen(
            Request(
                f"{origin}/__niy006_test/snapshot",
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

        with urlopen(f"{origin}/cdn-cgi/local/scheduled", timeout=10) as response:
            assert response.status == 200
