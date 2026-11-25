"""A rollback never makes a live environment not live again (#237).

Fixture/mock of the guard over a real, throwaway git history: the first live
commit is the first commit on main whose config sets `NIY_LIVE` to "true",
and anything older is refused, by the promote guard and by both deploy jobs.
"""

from __future__ import annotations

import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from test_delivery_state import delivery_state  # noqa: E402
from test_live_config import job_steps, runs  # noqa: E402

CONFIGS = {
    "staging": "wrangler.staging.jsonc",
    "production": "wrangler.production.jsonc",
}


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def commit(repo: Path, message: str, *, staging: str, production: str) -> str:
    for environment, live in (("staging", staging), ("production", production)):
        config = {"name": f"next-is-you-{environment}", "vars": {"NIY_LIVE": live}}
        (repo / CONFIGS[environment]).write_text(json.dumps(config, indent=1) + "\n")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "--allow-empty", "-m", message)
    return git(repo, "rev-parse", "HEAD")


def publish(repo: Path) -> None:
    """Give the repo an origin holding main and its tags, as a workflow clone has."""
    origin = repo.parent / "origin.git"
    subprocess.run(
        ["git", "init", "-q", "--bare", str(origin)], check=True, capture_output=True
    )
    git(repo, "remote", "add", "origin", str(origin))
    git(repo, "push", "-q", "origin", "main", "--tags")


@pytest.fixture
def history(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """v0.1.0 and v0.2.0 not live; staging goes live, then production, then v0.3.0."""
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "fixture@example.invalid")
    git(repo, "config", "user.name", "fixture")
    (repo / "README.md").write_text("fixture\n")
    commits = {}
    commits["v0.1.0"] = commit(repo, "first", staging="false", production="false")
    git(repo, "tag", "v0.1.0")
    commits["v0.2.0"] = commit(repo, "second", staging="false", production="false")
    git(repo, "tag", "v0.2.0")
    (repo / "README.md").write_text("an unrelated change\n")
    git(repo, "commit", "-qam", "unrelated")
    commits["unrelated"] = git(repo, "rev-parse", "HEAD")
    commits["staging live"] = commit(
        repo, "staging live", staging="true", production="false"
    )
    commits["production live"] = commit(
        repo, "production live", staging="true", production="true"
    )
    (repo / "README.md").write_text("after\n")
    git(repo, "commit", "-qam", "release")
    commits["v0.3.0"] = git(repo, "rev-parse", "HEAD")
    git(repo, "tag", "v0.3.0")
    publish(repo)
    monkeypatch.chdir(repo)
    monkeypatch.setenv("LIVE_MAIN_REF", "main")
    return commits


def live_check(environment: str, sha: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = delivery_state.run_live_check(environment, sha, out, err)
    return code, out.getvalue(), err.getvalue()


def test_staging_refuses_a_commit_older_than_its_first_live_commit(history):
    live = history["staging live"][:7]
    code, out, err = live_check("staging", history["unrelated"])
    assert (code, err) == (1, "")
    assert out == (
        f"Refused: staging is live since {live}, and "
        f"{history['unrelated'][:7]} is older. Deploying it would make staging "
        "not live again, and going live cannot be undone.\n"
        f"To clear it: Deploy {live} or a newer commit of main.\n"
    )


@pytest.mark.parametrize("name", ["staging live", "production live", "v0.3.0"])
def test_staging_accepts_its_first_live_commit_and_anything_newer(history, name):
    code, out, _ = live_check("staging", history[name])
    assert code == 0
    assert out.startswith("Accepted: ")


def test_production_refuses_a_version_older_than_its_first_live_version(history):
    code, out, _ = live_check("production", history["v0.2.0"])
    assert code == 1
    assert out == (
        "Refused: production is live since v0.3.0, and "
        f"{history['v0.2.0'][:7]} is older. Deploying it would make production "
        "not live again, and going live cannot be undone.\n"
        "To clear it: Choose v0.3.0 or a newer version.\n"
    )


def test_staging_live_first_does_not_hold_back_production(history):
    # Staging went live one commit before production did.
    code, _, _ = live_check("production", history["staging live"])
    assert code == 1
    code, _, _ = live_check("staging", history["staging live"])
    assert code == 0


def test_production_is_not_held_before_any_version_carries_its_live_config(
    history,
):
    # The live config is on main but no version has it yet, so production has
    # never run a live version and a rollback cannot make it not live.
    git(Path.cwd(), "tag", "-d", "v0.3.0")
    git(Path.cwd(), "push", "-q", "origin", ":refs/tags/v0.3.0")
    code, out, _ = live_check("production", history["v0.1.0"])
    assert code == 0
    assert out.startswith("Accepted: ")


def test_an_environment_that_was_never_live_accepts_anything(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "fixture@example.invalid")
    git(repo, "config", "user.name", "fixture")
    first = commit(repo, "first", staging="false", production="false")
    commit(repo, "second", staging="false", production="false")
    publish(repo)
    monkeypatch.chdir(repo)
    monkeypatch.setenv("LIVE_MAIN_REF", "main")
    for environment in CONFIGS:
        code, out, _ = live_check(environment, first)
        assert code == 0
        assert out.startswith("Accepted: ")


def test_staging_is_decided_from_the_clone_alone(history):
    # Staging's floor is a commit, not a version tag, so an unreachable origin
    # does not stop its check.
    git(Path.cwd(), "remote", "set-url", "origin", "/nonexistent/origin.git")
    assert live_check("staging", history["unrelated"])[0] == 1
    assert live_check("staging", history["v0.3.0"])[0] == 0
    assert live_check("production", history["v0.3.0"])[0] == 2


def test_an_unreadable_commit_stops_the_check_without_a_verdict(history):
    code, out, err = live_check("staging", "0" * 40)
    assert code == 2
    assert out == ""
    assert err.startswith("live check cannot be decided: could not read ")


def test_the_guard_snapshot_marks_a_version_before_production_went_live(
    history, monkeypatch
):
    floor = delivery_state.read_live_floor("production", delivery_state._read_tags)
    assert floor == delivery_state.LiveFloor(
        "production", history["production live"], "v0.3.0"
    )
    assert delivery_state.before_live(floor, history["v0.2.0"])
    assert not delivery_state.before_live(floor, history["v0.3.0"])


DEPLOY_JOBS = {
    "production": ("promote.yml", "deploy"),
    "staging": ("ci.yml", "deploy-staging"),
}
DEPLOYED_REFS = {
    "production": "${{ needs.guard.outputs.commit }}",
    "staging": "${{ github.sha }}",
}


def checked_out_ref(steps: list[dict], before: int) -> str | None:
    """The ref of the last checkout before this step: the code it runs."""
    checkouts = [
        step.get("with", {}).get("ref")
        for step in steps[:before]
        if str(step.get("uses", "")).startswith("actions/checkout@")
    ]
    assert checkouts
    return checkouts[-1]


@pytest.mark.parametrize("environment", DEPLOY_JOBS)
def test_every_deploy_runs_the_live_check_before_deploying(environment):
    workflow, job = DEPLOY_JOBS[environment]
    steps = job_steps(ROOT / ".github" / "workflows" / workflow, job)
    checks = [
        index
        for index, step in enumerate(steps)
        if runs(step, "scripts/delivery_state.py", "live-check", environment)
    ]
    changes = [
        index
        for index, step in enumerate(steps)
        if runs(step, "d1", "migrations", "apply") or runs(step, "pywrangler", "deploy")
    ]
    assert len(checks) == 1
    assert len(changes) == 2
    assert checks[0] < min(changes)
    # Without pipefail, piping the check into tee would hide a refusal.
    assert steps[checks[0]].get("shell") == "bash"
    # The check runs this run's own script: a promoted version from before
    # #237 has no live-check, and an old copy would apply an old floor rule.
    assert checked_out_ref(steps, checks[0]) == "${{ github.sha }}"
    for change in changes:
        assert checked_out_ref(steps, change) == DEPLOYED_REFS[environment]
