"""Local Workers started by tests get their ports without racing other processes.

Local integration: real `pywrangler dev` processes on this machine.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from itertools import chain
from urllib.request import urlopen

import pytest

from worktree_bootstrap import require_wrangler
from local_worker import (
    ROOT,
    local_worker,
    local_worker_on_known_port,
    loopback_listener,
    unused_loopback_port,
    wrangler_dev,
)

WRANGLER_CONFIG = ROOT / "wrangler.niy006.test.jsonc"


def test_local_workers_started_at_once_all_serve(tmp_path):
    require_wrangler()
    # Before #225 every wrangler probed the same default inspector port (9229)
    # and closed it, so of six started together one or two usually died with
    # `Address already in use (socket "direct:1:default")`.
    # Each start runs `npx --yes wrangler`. With nothing to resolve it from
    # but node_modules (no registry, an empty npm cache), six starts cannot
    # resolve or install it at the same time (#273).
    npm_cache = tmp_path / "npm-cache"
    environment = {
        **os.environ,
        "CI": "1",
        "npm_config_offline": "true",
        "npm_config_cache": str(npm_cache),
    }
    # Every `pywrangler dev` first syncs .venv-workers. Six syncing at once on
    # a fresh checkout race to create it, and the losers wait at uv's
    # "replace it? [y/n]" prompt. Sync once up front so only the ports race.
    sync = subprocess.run(
        [sys.executable, "-m", "pywrangler", "sync"],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
    )
    assert sync.returncode == 0, sync.stdout + sync.stderr
    with ExitStack() as stack, ThreadPoolExecutor(max_workers=6) as pool:
        starts = [
            pool.submit(
                stack.enter_context,
                local_worker(
                    wrangler_dev(WRANGLER_CONFIG, tmp_path / f"state{index}"),
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
    assert not (npm_cache / "_npx").exists()


def test_local_worker_reports_what_npx_printed_when_the_wrangler_check_fails(
    tmp_path,
):
    # Fixture: an `npx` that fails the way npm does, ahead of the real one.
    npx = tmp_path / "bin" / "npx"
    npx.parent.mkdir()
    npx.write_text(
        '#!/bin/sh\necho "npm error code ESYNTHETIC"\n'
        'echo "npm error synthetic reason for $*" >&2\nexit 7\n'
    )
    npx.chmod(0o755)
    path = os.pathsep.join([str(npx.parent), os.environ["PATH"]])
    with pytest.raises(AssertionError) as failure:
        with local_worker(
            wrangler_dev(WRANGLER_CONFIG, tmp_path / "state"),
            env={**os.environ, "CI": "1", "PATH": path},
        ):
            pass
    message = str(failure.value)
    assert "`npx --yes wrangler --version` exited 7 and printed:" in message
    assert "npm error code ESYNTHETIC" in message
    assert "npm error synthetic reason for --yes wrangler --version" in message
    assert "Failed to get wrangler version" in message


def test_local_worker_startup_failure_fails_at_once_with_wrangler_output(tmp_path):
    require_wrangler()
    # A Python Worker without the python_workers flag: wrangler refuses it.
    broken = tmp_path / "wrangler.broken.jsonc"
    broken.write_text('{"name": "broken", "main": "src/worker.py"}')
    started = time.monotonic()
    with pytest.raises(AssertionError) as failure:
        with local_worker(
            wrangler_dev(broken, tmp_path / "state"),
            env={**os.environ, "CI": "1"},
        ):
            pass
    assert time.monotonic() - started < 60
    message = str(failure.value)
    assert message.startswith("Local Worker exited before serving:")
    assert "The `python_workers` compatibility flag is required" in message


def test_local_worker_on_known_port_moves_on_when_that_port_is_taken(tmp_path):
    require_wrangler()
    # A Worker that must know its port before it starts (an HTTPS callback
    # URL, say) gets a new port when another process took the chosen one.
    with loopback_listener() as (taken, _):
        held = taken.getsockname()[1]
        offered = chain([held], iter(unused_loopback_port, None))
        chosen = []

        def command(port):
            chosen.append(port)
            return wrangler_dev(
                WRANGLER_CONFIG,
                tmp_path / "state",
                ports=("--port", str(port), "--inspector-port", "0"),
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


def test_local_worker_that_cannot_start_reports_why(tmp_path):
    with pytest.raises(FileNotFoundError):
        with local_worker([str(tmp_path / "no-such-wrangler")], env=dict(os.environ)):
            pass
