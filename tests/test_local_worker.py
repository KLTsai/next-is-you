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
from itertools import chain
from urllib.request import urlopen

import pytest

from local_worker import (
    ROOT,
    WRANGLER_PICKS_PORTS,
    local_worker,
    local_worker_on_known_port,
    loopback_listener,
    unused_loopback_port,
)

WRANGLER_CONFIG = ROOT / "wrangler.niy006.test.jsonc"


def _wrangler_dev(config, persist_to, ports=WRANGLER_PICKS_PORTS):
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
        *ports,
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


def test_local_worker_on_known_port_moves_on_when_that_port_is_taken(tmp_path):
    # A Worker that must know its port before it starts (an HTTPS callback
    # URL, say) gets a new port when another process took the chosen one.
    with loopback_listener() as (taken, _):
        held = taken.getsockname()[1]
        offered = chain([held], iter(unused_loopback_port, None))
        chosen = []

        def command(port):
            chosen.append(port)
            return _wrangler_dev(
                WRANGLER_CONFIG,
                tmp_path / "state",
                ("--port", str(port), "--inspector-port", "0"),
            )

        with local_worker_on_known_port(
            command,
            env={**os.environ, "CI": "1"},
            pick_port=lambda: next(offered),
        ) as origin:
            with urlopen(origin + "/api/healthz", timeout=10) as response:
                assert response.status == 200
    assert chosen[0] == held
    assert len(chosen) == 2
    assert origin == f"http://127.0.0.1:{chosen[1]}"
