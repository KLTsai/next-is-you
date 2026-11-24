"""Start local Workers and servers for tests without racing other processes for a port.

Picking a port by binding ("127.0.0.1", 0), closing the socket and handing the
number to another process leaves a window in which anything else on the
machine can take it. Wrangler has the same window of its own: unless told
otherwise it probes its default inspector port (9229 and up) and closes it, so
two `wrangler dev` started together pick the same one and the second dies with
`Address already in use (socket "direct:1:default")` (#225).

So a local Worker is started with both ports set to 0, the OS assigns them at
bind time, and the origin is read back from wrangler's "Ready on" line. An
in-process server keeps the listening socket it was given.
"""

from __future__ import annotations

import os
import pty
import re
import signal
import socket
import subprocess
import threading
import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]

# Arguments for `wrangler dev` that let the OS assign both of its ports.
WRANGLER_PICKS_PORTS = ("--port", "0", "--inspector-port", "0")

_READY = re.compile(r"Ready on (http://127\.0\.0\.1:\d+)")
_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


@contextmanager
def local_worker(
    command: Sequence[str],
    *,
    env: dict[str, str],
    log_path: Path | None = None,
    timeout: float = 90,
) -> Iterator[str]:
    """Runs `command` in a terminal and yields the origin it serves once healthy.

    `command` must start `wrangler dev --ip 127.0.0.1` with the ports from
    `WRANGLER_PICKS_PORTS`, or with a fixed port. If it exits first, or is not
    healthy within `timeout` seconds, this fails with everything it printed.
    """
    master, terminal = pty.openpty()
    output: list[str] = []

    def read_terminal() -> None:
        try:
            while chunk := os.read(master, 65536):
                output.append(chunk.decode(errors="replace"))
        except OSError:
            pass  # The terminal closes after the foreground process exits.

    reader = threading.Thread(target=read_terminal)
    try:
        process = subprocess.Popen(
            list(command),
            cwd=ROOT,
            env=env,
            stdin=terminal,
            stdout=terminal,
            stderr=terminal,
            start_new_session=True,
        )
        os.close(terminal)
        reader.start()
        try:
            yield _wait_until_healthy(process, reader, output, timeout)
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGINT)
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=10)
    finally:
        reader.join(timeout=10)
        os.close(master)
        if log_path is not None:
            log_path.write_text("".join(output))
        assert not reader.is_alive(), "Local Worker left a terminal reader running"


def _wait_until_healthy(
    process: subprocess.Popen[bytes],
    reader: threading.Thread,
    output: list[str],
    timeout: float,
) -> str:
    deadline = time.monotonic() + timeout
    origin = None
    while time.monotonic() < deadline:
        if process.poll() is not None:
            # Its last words, usually the error, may still be in the terminal.
            reader.join(timeout=10)
            raise AssertionError(
                "Local Worker exited before serving:\n" + "".join(output)
            )
        if origin is None and (ready := _READY.search(_ANSI.sub("", "".join(output)))):
            origin = ready.group(1)
        if origin is not None:
            try:
                with urlopen(origin + "/api/healthz", timeout=1) as response:
                    if response.status == 200:
                        return origin
            except (OSError, URLError):
                pass
        time.sleep(0.25)
    raise AssertionError("Local Worker startup timed out:\n" + "".join(output))


@contextmanager
def loopback_listener() -> Iterator[tuple[socket.socket, str]]:
    """Yields a listening loopback socket for an in-process server, and its origin.

    The socket stays bound until the block ends, so no other process can take
    the port between choosing it and serving on it.
    """
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        yield listener, f"http://127.0.0.1:{listener.getsockname()[1]}"
