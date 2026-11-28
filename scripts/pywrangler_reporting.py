"""`pywrangler`, reporting what `npx` printed when its wrangler check fails.

Before `dev`, pywrangler runs `npx --yes wrangler --version`, captures the
output and, when the command fails, logs only "Failed to get wrangler version",
so the reason npm gave is lost (#273). Run this instead of `pywrangler`; it takes
the same arguments.
"""

from __future__ import annotations

import sys

from pywrangler import utils
from pywrangler.cli import app

_VERSION_CHECK = [*utils.WRANGLER_COMMAND, "--version"]
_run_command = utils.run_command


def _run_command_reporting_a_failed_check(command, *args, **kwargs):
    result = _run_command(command, *args, **kwargs)
    if command == _VERSION_CHECK and result.returncode != 0:
        print(
            f"`{' '.join(command)}` exited {result.returncode} and printed:\n"
            f"{result.stdout}",
            file=sys.stderr,
            flush=True,
        )
    return result


if __name__ == "__main__":
    # pywrangler looks `run_command` up in its module when it makes the check.
    utils.run_command = _run_command_reporting_a_failed_check
    app()
