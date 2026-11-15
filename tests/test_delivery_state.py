"""What the captain sees from `npm run status`, fed recorded snapshots.

Evidence: fixture/mock. Facts are never fetched here; the live reading layer
is checked against the real repository instead.
"""

from __future__ import annotations

import importlib.util
import io
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "delivery_state", ROOT / "scripts" / "delivery_state.py"
)
delivery_state = importlib.util.module_from_spec(_spec)
sys.modules["delivery_state"] = delivery_state
_spec.loader.exec_module(delivery_state)

SNAPSHOTS = json.loads(
    (ROOT / "tests" / "fixtures" / "delivery_snapshots.json").read_text()
)


def run_status(name: str) -> tuple[int, str, str]:
    snapshot = delivery_state.Snapshot.from_dict(SNAPSHOTS[name])
    out, err = io.StringIO(), io.StringIO()
    code = delivery_state.run_status(lambda: snapshot, out, err)
    return code, out.getvalue(), err.getvalue()


def test_nothing_pending():
    code, out, err = run_status("nothing_pending")
    assert (code, err) == (0, "")
    assert out == (
        "main        abc1234 - checks passed\n"
        "staging     abc1234 - same as main\n"
        "production  v0.2.1\n"
        "next        none - no release PR, nothing releasable\n"
        "\n"
        "Next step: Nothing to do.\n"
    )


def test_release_pr_open():
    code, out, _ = run_status("release_pr_open")
    assert code == 0
    assert out == (
        "main        abc1234 - checks passed\n"
        "staging     abc1234 - same as main\n"
        "production  v0.2.1\n"
        "next        v0.2.2 - release PR #75, 3 changes\n"
        "\n"
        "Next step: Merge release PR #75 to cut v0.2.2, "
        "or leave it open to collect more changes.\n"
    )


def test_version_tagged_and_not_yet_promoted():
    code, out, _ = run_status("tagged_not_promoted")
    assert code == 0
    assert out == (
        "main        abc1234 - checks passed\n"
        "staging     abc1234 - same as main\n"
        "production  v0.2.1\n"
        "next        none - no release PR, nothing releasable\n"
        "tagged      v0.3.0 - tagged, not yet a Release\n"
        "\n"
        "Next step: Check v0.3.0 on staging, then promote it.\n"
    )


def test_tagged_version_not_on_staging():
    _, out, _ = run_status("tagged_staging_elsewhere")
    assert "tagged      v0.3.0 - tagged, not yet a Release\n" in out
    assert out.endswith(
        "Next step: Put v0.3.0 on staging (staging shows fff9999), "
        "check it, then promote it.\n"
    )


def test_staging_behind_main():
    code, out, _ = run_status("staging_behind_main")
    assert code == 0
    assert out == (
        "main        abc1234 - checks passed\n"
        "staging     def5678 - differs from main\n"
        "production  v0.2.1\n"
        "next        none - no release PR, nothing releasable\n"
        "\n"
        "Next step: Staging is not showing main. "
        "Deploy main to staging, then run status again.\n"
    )


def test_staging_never_deployed():
    _, out, _ = run_status("staging_never_deployed")
    assert "staging     none - nothing deployed\n" in out
    assert "production  none\n" in out


def test_staging_paused_is_reported():
    _, out, _ = run_status("staging_paused")
    assert "paused      automatic staging deployment is paused\n" in out
    assert out.endswith(
        "Next step: Automatic staging deployment is paused. "
        "Resume it when you finish checking.\n"
    )


def test_checks_on_main_red():
    code, out, _ = run_status("main_checks_red")
    assert code == 0
    assert out == (
        "main        abc1234 - checks failed (lint, backend)\n"
        "staging     def5678 - differs from main\n"
        "production  v0.2.1\n"
        "next        v0.2.2 - release PR #75, 1 change\n"
        "\n"
        "Next step: Fix main: checks failed (lint, backend). "
        "Do not promote until they pass.\n"
    )


def test_checks_on_main_still_running():
    _, out, _ = run_status("main_checks_running")
    assert "main        abc1234 - checks still running\n" in out
    assert out.endswith(
        "Next step: Wait for the checks on main to finish, "
        "then run status again.\n"
    )


def test_unreadable_fact_names_itself_and_prints_no_report():
    def reader():
        raise delivery_state.FactUnreadable("release PR", "gh exited 1")

    out, err = io.StringIO(), io.StringIO()
    code = delivery_state.run_status(reader, out, err)
    assert code != 0
    assert out.getvalue() == ""
    assert err.getvalue() == (
        "status cannot be reported: could not read release PR (gh exited 1)\n"
    )


@pytest.mark.parametrize("name", sorted(SNAPSHOTS))
def test_every_report_ends_in_exactly_one_next_step(name):
    _, out, _ = run_status(name)
    assert out.count("Next step:") == 1
    assert out.rstrip().splitlines()[-1].startswith("Next step:")
