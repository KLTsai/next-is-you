"""Local Workers started by tests get their ports without racing other processes.

Local integration: real `pywrangler dev` processes on this machine.
"""

from __future__ import annotations

import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from urllib.request import urlopen

import pytest

from local_worker import ROOT, WRANGLER_PICKS_PORTS, local_worker

WRANGLER_CONFIG = ROOT / "wrangler.niy006.test.jsonc"


def _wrangler_dev(config, persist_to):
    return [
        sys.executable,
        "-m",
        "pywrangler",
        "dev",
        "--local",
        "--ip",
        "127.0.0.1",
        "--config",
        str(config),
        "--persist-to",
        str(persist_to),
        "--show-interactive-dev-session=false",
        *WRANGLER_PICKS_PORTS,
    ]


def test_local_workers_started_at_once_all_serve(tmp_path):
    # Before #225 every wrangler probed the same default inspector port (9229)
    # and closed it, so of six started together one or two usually died with
    # `Address already in use (socket "direct:1:default")`.
    environment = {**os.environ, "CI": "1"}
    with ExitStack() as stack, ThreadPoolExecutor(max_workers=6) as pool:
        starts = [
            pool.submit(
                stack.enter_context,
                local_worker(
                    _wrangler_dev(WRANGLER_CONFIG, tmp_path / f"state{index}"),
                    env=environment,
                    log_path=tmp_path / f"worker{index}.log",
                ),
            )
            for index in range(6)
        ]
        origins = [start.result() for start in starts]
        assert len(set(origins)) == 6
        for origin in origins:
            with urlopen(origin + "/api/healthz", timeout=10) as response:
                assert json.loads(response.read())["status"] == "ok"


def test_local_worker_startup_failure_fails_at_once_with_wrangler_output(tmp_path):
    # A Python Worker without the python_workers flag: wrangler refuses it.
    broken = tmp_path / "wrangler.broken.jsonc"
    broken.write_text('{"name": "broken", "main": "src/worker.py"}')
    started = time.monotonic()
    with pytest.raises(AssertionError) as failure:
        with local_worker(
            _wrangler_dev(broken, tmp_path / "state"),
            env={**os.environ, "CI": "1"},
        ):
            pass
    assert time.monotonic() - started < 60
    message = str(failure.value)
    assert message.startswith("Local Worker exited before serving:")
    assert "The `python_workers` compatibility flag is required" in message
