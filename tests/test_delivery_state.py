"""What the captain sees from `npm run status`, fed recorded snapshots.

Evidence: fixture/mock. Facts are never fetched here; the live reading layer
is checked against the real repository instead.
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import sys
import textwrap
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


def test_a_pause_value_that_does_not_pause_is_reported():
    # The captain set the variable and believes staging is held. It is not:
    # only "true" pauses. Without this line the report reads as if the variable
    # were absent.
    code, out, _ = run_status("pause_value_does_not_pause")
    assert code == 0
    assert out == (
        "main        abc1234 - checks passed\n"
        "staging     abc1234 - same as main\n"
        "production  v0.2.1\n"
        "next        none - no release PR, nothing releasable\n"
        'not paused  STAGING_DEPLOY_PAUSED is "yes": only "true" pauses, '
        "so staging still deploys\n"
        "\n"
        "Next step: Set STAGING_DEPLOY_PAUSED to true to pause automatic staging "
        "deployment, or to false to leave it running.\n"
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
        "Next step: Wait for the checks on main to finish, then run status again.\n"
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


def test_staging_behind_only_by_documentation_asks_for_no_deploy():
    code, out, _ = run_status("staging_behind_docs_only")
    assert code == 0
    assert "staging     def5678 - differs from main, documentation only\n" in out
    assert out.endswith("Next step: Nothing to do.\n")


def test_published_release_tags_leave_out_drafts():
    listing = [
        {"tag_name": "v0.3.0", "draft": True},
        {"tag_name": "v0.2.1", "draft": False},
        {"tag_name": "untagged-abc", "draft": False},
    ]
    assert delivery_state.published_release_tags(listing) == frozenset({"v0.2.1"})


# ---------------------------------------------------------------------------
# Promote guard
# ---------------------------------------------------------------------------

PROMOTE = json.loads(
    (ROOT / "tests" / "fixtures" / "promote_snapshots.json").read_text()
)


def run_guard(name: str, version: str) -> tuple[int, str, str]:
    snapshot = delivery_state.Snapshot.from_dict(PROMOTE[name])
    out, err = io.StringIO(), io.StringIO()
    code = delivery_state.run_guard(lambda _version: snapshot, version, out, err)
    return code, out.getvalue(), err.getvalue()


def assert_refused(result, reason: str, action: str):
    code, out, err = result
    assert code == 1
    assert err == ""
    assert out == f"Refused: {reason}\nTo clear it: {action}\n"


def test_guard_accepts_a_green_version_staging_is_showing():
    code, out, err = run_guard("accept", "v0.3.0")
    assert (code, err) == (0, "")
    assert out == "Accepted: v0.3.0 at aaa1111000000000000000000000000000000000\n"


def test_guard_accepts_a_version_typed_without_the_v():
    code, out, _ = run_guard("accept", "0.3.0")
    assert code == 0
    assert out.startswith("Accepted: v0.3.0 at ")


def test_guard_refuses_an_unknown_version():
    assert_refused(
        run_guard("unknown_version", "v9.9.9"),
        "v9.9.9 is not a version.",
        "Enter an existing version. Versions are created by merging the release PR.",
    )


def test_guard_refuses_text_that_is_not_a_version():
    code, out, _ = run_guard("accept", "latest")
    assert code == 1
    assert out.startswith("Refused: latest is not a version.\n")


def test_guard_refuses_a_commit_not_on_main():
    assert_refused(
        run_guard("not_on_main", "v0.3.0"),
        "v0.3.0 is at aaa1111, which is not on main.",
        "Do not promote it. Merge the release PR on main to cut a new version.",
    )


def test_guard_refuses_red_checks_and_names_them():
    assert_refused(
        run_guard("checks_red", "v0.3.0"),
        "the checks on v0.3.0 (aaa1111) failed "
        "(Backend and browser tests, Type check).",
        "If the failure is not real, re-run that commit's pipeline run. "
        "Otherwise fix main and release a new version.",
    )


def test_guard_refuses_unfinished_checks():
    assert_refused(
        run_guard("checks_unfinished", "v0.3.0"),
        "the checks on v0.3.0 (aaa1111) are still running.",
        "Wait for them to finish, then run Promote again.",
    )


@pytest.mark.parametrize("name", ["staging_later", "staging_earlier"])
def test_guard_refuses_when_staging_shows_another_commit(name):
    shown = PROMOTE[name]["staging_sha"][:7]
    assert_refused(
        run_guard(name, "v0.3.0"),
        f"staging is showing {shown}, not v0.3.0 (aaa1111).",
        "Re-run the pipeline run of commit aaa1111 so staging shows it, "
        "check it, then run Promote again.",
    )


def test_guard_refuses_when_staging_has_never_deployed():
    code, out, _ = run_guard("staging_never_deployed", "v0.3.0")
    assert code == 1
    assert out.startswith(
        "Refused: staging is showing nothing, not v0.3.0 (aaa1111).\n"
    )


def test_guard_says_when_staging_deployment_is_paused():
    _, out, _ = run_guard("staging_paused_elsewhere", "v0.3.0")
    assert out == (
        "Refused: staging is showing bbb2222, not v0.3.0 (aaa1111).\n"
        "To clear it: Resume automatic staging deployment (unset "
        "STAGING_DEPLOY_PAUSED), re-run the pipeline run of commit aaa1111 "
        "so staging shows it, check it, then run Promote again.\n"
    )


def test_guard_accepts_re_promoting_the_version_in_production():
    code, out, _ = run_guard("repromote_production", "v0.3.1")
    assert code == 0
    assert out == "Accepted: v0.3.1 at bbb2222000000000000000000000000000000000\n"


def test_guard_accepts_rolling_back_to_an_earlier_version():
    code, out, _ = run_guard("rollback_earlier", "v0.3.0")
    assert code == 0
    assert out.startswith("Accepted: v0.3.0 at aaa1111")


def test_guard_accepts_rolling_back_to_a_version_made_before_this_design():
    code, out, _ = run_guard("rollback_pre_design", "v0.2.0")
    assert code == 0
    assert out == "Accepted: v0.2.0 at 1110000000000000000000000000000000000000\n"


def test_unreadable_fact_stops_the_guard_without_a_verdict():
    def reader(_version):
        raise delivery_state.FactUnreadable("version commit checks", "gh exited 1")

    out, err = io.StringIO(), io.StringIO()
    code = delivery_state.run_guard(reader, "v0.3.0", out, err)
    assert code == 2
    assert out.getvalue() == ""
    assert err.getvalue() == (
        "promote cannot be decided: could not read version commit checks "
        "(gh exited 1)\n"
    )


# ---------------------------------------------------------------------------
# Reading layer, with the GitHub calls replaced
# ---------------------------------------------------------------------------

GATES = [
    "Formatting and lint",
    "Type check",
    "Frontend tests",
    "Build",
    "Migration check",
    "Backend and browser tests",
    "Diff hygiene",
]


def check_run(name, status="completed", conclusion="success", run_id=1):
    return {"name": name, "status": status, "conclusion": conclusion, "id": run_id}


def green_gates():
    return [check_run(name, run_id=i + 10) for i, name in enumerate(GATES)]


def fake_checks(monkeypatch, runs):
    monkeypatch.setattr(
        delivery_state, "_gh_pages", lambda fact, endpoint: [{"check_runs": runs}]
    )
    return delivery_state._read_checks("checks", "abc")


def test_checks_ignore_the_promote_workflows_own_run(monkeypatch):
    runs = [*green_gates(), check_run("Promote guard", "in_progress", None, 99)]
    assert fake_checks(monkeypatch, runs) == ("success", ())


def test_checks_ignore_a_cancelled_staging_deploy(monkeypatch):
    runs = [*green_gates(), check_run("Deploy staging", conclusion="cancelled")]
    assert fake_checks(monkeypatch, runs) == ("success", ())


def test_checks_ignore_release_please_and_summary(monkeypatch):
    runs = [
        *green_gates(),
        check_run("Release Please", conclusion="failure"),
        check_run("Summary", conclusion="failure"),
    ]
    assert fake_checks(monkeypatch, runs) == ("success", ())


def test_a_failed_gate_is_named(monkeypatch):
    runs = green_gates()
    runs[1] = check_run("Type check", conclusion="failure", run_id=11)
    assert fake_checks(monkeypatch, runs) == ("failure", ("Type check",))


@pytest.mark.parametrize(
    "conclusion",
    ["skipped", "neutral", "stale", "startup_failure", "cancelled", "timed_out"],
)
def test_a_gate_that_finished_without_succeeding_is_not_green(monkeypatch, conclusion):
    # Green means every gate succeeded, not that none of them is known to fail.
    # The gate is named with how it ended, so the captain is not sent looking
    # for a red job that is not there.
    runs = green_gates()
    runs[4] = check_run("Migration check", conclusion=conclusion, run_id=14)
    assert fake_checks(monkeypatch, runs) == (
        "failure",
        (f"Migration check: {conclusion}",),
    )


def test_checks_are_read_across_every_page(monkeypatch):
    gates = green_gates()
    pages = [{"check_runs": gates[:6]}, {"check_runs": gates[6:]}]
    seen = []

    def fake_run(fact, args):
        seen.append(args)
        return json.dumps(pages)

    monkeypatch.setattr(delivery_state, "_run", fake_run)
    assert delivery_state._read_checks("checks", "abc") == ("success", ())
    assert "--paginate" in seen[0]


def test_a_missing_or_unfinished_gate_is_pending(monkeypatch):
    assert fake_checks(monkeypatch, green_gates()[:-1]) == ("pending", ())
    runs = green_gates()
    runs[0] = check_run("Formatting and lint", "in_progress", None, 10)
    assert fake_checks(monkeypatch, runs) == ("pending", ())


def test_a_rerun_gate_counts_by_its_latest_run(monkeypatch):
    runs = [
        *green_gates(),
        check_run("Build", conclusion="failure", run_id=1),
    ]
    assert fake_checks(monkeypatch, runs) == ("success", ())


# The pause variable. ci.yml skips Deploy staging on
# `vars.STAGING_DEPLOY_PAUSED != 'true'`, and Actions compares strings ignoring
# letter case and nothing else. Status and the guard must call the same values
# paused, or they report a pause while staging keeps deploying.
@pytest.mark.parametrize(
    ("value", "paused"),
    [
        ("true", True),
        ("TRUE", True),
        ("True", True),
        ("", False),
        ("false", False),
        ("yes", False),
        ("1", False),
        (" true", False),
        ("true\n", False),
    ],
)
def test_only_the_value_true_pauses_as_in_the_workflow(monkeypatch, value, paused):
    monkeypatch.setenv("STAGING_DEPLOY_PAUSED", value)
    assert delivery_state._read_paused() is paused


# A value that is set but neither pauses nor says "do not pause" is most likely
# a mistake: the captain typed it to pause. An absent variable reaches a
# workflow as an empty value, which is nobody's mistake.
@pytest.mark.parametrize(
    ("value", "ignored"),
    [
        ("yes", "yes"),
        ("1", "1"),
        (" true", " true"),
        ("true\n", "true\n"),
        ("true", None),
        ("TRUE", None),
        ("false", None),
        ("False", None),
        ("", None),
    ],
)
def test_a_set_value_that_is_neither_true_nor_false_is_ignored(
    monkeypatch, value, ignored
):
    monkeypatch.setenv("STAGING_DEPLOY_PAUSED", value)
    read = delivery_state._read_pause_value()
    assert delivery_state.ignored_pause_value(read) == ignored


def fake_variable_reply(monkeypatch, *, returncode, stdout="", stderr=""):
    monkeypatch.delenv("STAGING_DEPLOY_PAUSED", raising=False)
    monkeypatch.setattr(
        delivery_state.subprocess,
        "run",
        lambda *args, **kwargs: delivery_state.subprocess.CompletedProcess(
            args, returncode, stdout=stdout, stderr=stderr
        ),
    )


def test_the_repository_variable_is_read_with_the_value_it_holds(monkeypatch):
    fake_variable_reply(
        monkeypatch,
        returncode=0,
        stdout='{"name": "STAGING_DEPLOY_PAUSED", "value": "true "}',
    )
    assert delivery_state._read_pause_value() == "true "
    assert delivery_state._read_paused() is False


def test_an_absent_repository_variable_holds_no_value(monkeypatch):
    fake_variable_reply(monkeypatch, returncode=1, stderr="gh: Not Found (HTTP 404)")
    assert delivery_state._read_pause_value() == ""
    assert delivery_state._read_paused() is False


def run_pause_warning(tmp_path, value: str | None) -> tuple[int, str, str]:
    """Run the pause warning the way the pipeline run does, on this value.

    Returns the exit code, what the step printed and what it added to the run
    summary. None is a variable that does not exist.
    """
    summary = tmp_path / "summary.md"
    summary.write_text("")
    env = {k: v for k, v in os.environ.items() if k != "STAGING_DEPLOY_PAUSED"}
    if value is not None:
        env["STAGING_DEPLOY_PAUSED"] = value
    done = subprocess.run(
        [sys.executable, "scripts/delivery_state.py", "pause-warning"],
        cwd=ROOT,
        env={**env, "GITHUB_STEP_SUMMARY": str(summary)},
        capture_output=True,
        text=True,
    )
    assert done.stderr == ""
    return done.returncode, done.stdout, summary.read_text()


def test_the_pipeline_run_warns_about_a_pause_value_that_does_not_pause(tmp_path):
    # GitHub shows a line in this form as a warning on the run page.
    code, printed, summary = run_pause_warning(tmp_path, "yes")
    text = (
        'STAGING_DEPLOY_PAUSED is "yes": only "true" pauses, so staging still deploys'
    )
    assert code == 0
    assert printed == f"::warning title=Staging deployment is not paused::{text}\n"
    assert summary == f"### Staging deployment is not paused\n\n{text}\n"


def test_the_warning_shows_a_stray_line_break_and_stays_one_line(tmp_path):
    # A line break would end the warning early, and "%" starts an escape in it.
    code, printed, _ = run_pause_warning(tmp_path, "true\n100%")
    assert code == 0
    assert printed == (
        "::warning title=Staging deployment is not paused::"
        'STAGING_DEPLOY_PAUSED is "true\\n100%25": only "true" pauses, '
        "so staging still deploys\n"
    )


@pytest.mark.parametrize("value", ["true", "TRUE", "false", "False", "", None])
def test_the_pipeline_run_says_nothing_about_a_value_that_is_understood(
    tmp_path, value
):
    assert run_pause_warning(tmp_path, value) == (0, "", "")


def test_the_workflows_apply_the_pause_rule_the_module_reads():
    ci = (ROOT / ".github/workflows/ci.yml").read_text()
    # ci.yml reads the variable in two places and decides in one: the Deploy
    # staging condition. The other hands the raw value to the module's warning.
    assert ci.count("vars.STAGING_DEPLOY_PAUSED") == 2
    assert "&& vars.STAGING_DEPLOY_PAUSED != 'true' }}" in ci
    assert (
        "        env:\n"
        "          STAGING_DEPLOY_PAUSED: ${{ vars.STAGING_DEPLOY_PAUSED }}\n"
        "        run: python3 scripts/delivery_state.py pause-warning\n"
    ) in ci
    # Promote hands the guard the raw value, so the module applies the rule.
    promote = (ROOT / ".github/workflows/promote.yml").read_text()
    assert "STAGING_DEPLOY_PAUSED: ${{ vars.STAGING_DEPLOY_PAUSED }}\n" in promote


def test_production_is_the_promoted_version_after_a_rollback():
    code, out, _ = run_status("rolled_back")
    assert code == 0
    assert "production  v0.2.1\n" in out
    # v0.3.0 is published and newer than production: it is not pending.
    assert "tagged" not in out


def test_latest_deployment_sha_is_read_for_the_environment(monkeypatch):
    seen = []

    def fake(fact, endpoint):
        seen.append(endpoint)
        if "/statuses" in endpoint:
            return [{"state": "success"}]
        return [{"id": 1, "sha": "aaa"}]

    monkeypatch.setattr(delivery_state, "_gh_json", fake)
    assert delivery_state._latest_deployment_sha("production", "prod") == "aaa"
    assert "environment=prod&" in seen[0]


def test_staging_deployment_stops_at_the_first_success(monkeypatch):
    calls = []

    def fake(fact, endpoint):
        calls.append(endpoint)
        if "/statuses" in endpoint:
            return [{"state": "success"}]
        return [{"id": 1, "sha": "aaa"}, {"id": 2, "sha": "bbb"}]

    monkeypatch.setattr(delivery_state, "_gh_json", fake)
    assert delivery_state._read_staging_sha() == "aaa"
    assert len(calls) == 2


def test_releases_are_read_across_every_page(monkeypatch):
    pages = [
        [{"tag_name": "v0.1.0", "draft": False}],
        [{"tag_name": "v0.2.0", "draft": False}],
    ]
    monkeypatch.setattr(delivery_state, "_run", lambda fact, args: json.dumps(pages))
    assert delivery_state._read_releases() == frozenset({"v0.1.0", "v0.2.0"})


@pytest.mark.parametrize(
    ("files", "expected"),
    [
        ([{"filename": "a.md"}], True),
        ([{"filename": "docs/a.md"}, {"filename": "b.md"}], True),
        ([{"filename": "a.py"}], False),
        ([], False),
        # A rename from a product file to Markdown still removes a product file.
        ([{"filename": "a.md", "previous_filename": "a.py"}], False),
        ([{"filename": "a.md", "previous_filename": "old.md"}], True),
    ],
)
def test_staging_gap_docs_only_reads_both_sides_of_a_rename(
    monkeypatch, files, expected
):
    monkeypatch.setattr(
        delivery_state,
        "_gh_json",
        lambda fact, endpoint: {"status": "ahead", "files": files},
    )
    assert delivery_state._read_staging_gap_docs_only("s", "m") is expected


# Production after Promote. The deployment record GitHub keeps for the prod
# environment names the commit Promote was dispatched from (the head of main),
# not the commit it deployed, so production is read from the Promote runs: the
# run whose Deploy Worker step finished last.
V022 = "5c9f7471cf4fd3d83cb9fb11c88505b3e6380dc0"
V023 = "d52eef8d68409365adf24f154e0cd2cc454794c3"
TAGS = {"v0.2.2": V022, "v0.2.3": V023}


def deploy_job(tag, finished, *, worker="success", later="success", name=None):
    """A Promote deploy job as the Actions API returns it."""
    return {
        "name": name or f"Deploy {tag} to production",
        "steps": [
            {
                "name": "Apply production migrations",
                "conclusion": "success",
                "completed_at": finished,
            },
            {
                "name": "Deploy Worker",
                "conclusion": worker,
                "completed_at": finished if worker else None,
            },
            {
                "name": "Publish the GitHub Release",
                "conclusion": later,
                "completed_at": finished,
            },
        ],
    }


def refused_run():
    """A Promote run whose guard refused: the deploy job never started."""
    return [
        {"name": "Promote guard", "steps": []},
        {"name": "Deploy ${{ needs.guard.outputs.tag }} to production", "steps": []},
    ]


def fake_production(monkeypatch, *, runs, deployment_sha=None):
    """runs: newest created first, each a list of jobs."""

    def fake_gh(fact, endpoint):
        if "workflows/promote.yml/runs" in endpoint:
            return {"workflow_runs": [{"id": i} for i in range(len(runs), 0, -1)]}
        if endpoint.endswith("/jobs"):
            run_id = int(endpoint.split("/runs/")[1].split("/")[0])
            return {"jobs": runs[len(runs) - run_id]}
        if "deployments?environment=prod" in endpoint:
            return [{"id": 1, "sha": deployment_sha}] if deployment_sha else []
        if endpoint.endswith("/deployments/1/statuses"):
            return [{"state": "success"}]
        raise AssertionError(f"unexpected endpoint {endpoint}")

    monkeypatch.setattr(delivery_state, "_gh_json", fake_gh)


def test_production_is_the_version_the_last_promote_deployed(monkeypatch):
    # v0.2.3 was promoted, then v0.2.2 as a rollback. Both runs were dispatched
    # from main, so the deployment record says v0.2.3.
    fake_production(
        monkeypatch,
        runs=[
            [deploy_job("v0.2.2", "2026-11-16T06:32:00Z")],
            [deploy_job("v0.2.3", "2026-11-16T06:20:00Z")],
        ],
        deployment_sha=V023,
    )
    assert delivery_state._read_production_sha(TAGS) == V022


def test_a_promote_that_deployed_then_failed_a_later_step_still_counts(monkeypatch):
    # The Worker deployed, then publishing the Release failed: production runs
    # v0.2.2 even though the run concluded as failed.
    fake_production(
        monkeypatch,
        runs=[
            [deploy_job("v0.2.2", "2026-11-16T06:32:00Z", later="failure")],
            [deploy_job("v0.2.3", "2026-11-16T06:20:00Z")],
        ],
        deployment_sha=V023,
    )
    assert delivery_state._read_production_sha(TAGS) == V022


def test_a_failed_deploy_step_is_not_a_deployment(monkeypatch):
    fake_production(
        monkeypatch,
        runs=[
            [
                deploy_job(
                    "v0.2.2", "2026-11-16T06:32:00Z", worker="failure", later="skipped"
                )
            ],
            [deploy_job("v0.2.3", "2026-11-16T06:20:00Z")],
        ],
    )
    assert delivery_state._read_production_sha(TAGS) == V023


def test_a_refused_promote_is_not_a_deployment(monkeypatch):
    fake_production(
        monkeypatch,
        runs=[refused_run(), [deploy_job("v0.2.3", "2026-11-16T06:20:00Z")]],
    )
    assert delivery_state._read_production_sha(TAGS) == V023


def test_a_rerun_of_an_older_run_is_judged_by_when_it_deployed(monkeypatch):
    # The v0.2.3 run was created last but re-run before the v0.2.2 run
    # finished deploying, so v0.2.2 is what deployed last.
    fake_production(
        monkeypatch,
        runs=[
            [deploy_job("v0.2.3", "2026-11-16T06:20:00Z")],
            [deploy_job("v0.2.2", "2026-11-16T06:32:00Z")],
        ],
    )
    assert delivery_state._read_production_sha(TAGS) == V022


def test_a_deploy_job_that_cannot_be_read_is_named_not_guessed(monkeypatch):
    # Someone renamed the job: the Worker deployed but the version is unknown.
    fake_production(
        monkeypatch,
        runs=[[deploy_job("v0.2.2", "2026-11-16T06:32:00Z", name="Ship it")]],
        deployment_sha=V023,
    )
    with pytest.raises(delivery_state.FactUnreadable) as error:
        delivery_state._read_production_sha(TAGS)
    assert error.value.fact == "production version"


def test_a_deployed_version_with_no_tag_is_named_not_guessed(monkeypatch):
    fake_production(
        monkeypatch,
        runs=[[deploy_job("v9.9.9", "2026-11-16T06:32:00Z")]],
        deployment_sha=V023,
    )
    with pytest.raises(delivery_state.FactUnreadable) as error:
        delivery_state._read_production_sha(TAGS)
    assert error.value.fact == "production version"


def test_production_falls_back_to_the_deployment_when_no_promote_deployed(monkeypatch):
    fake_production(monkeypatch, runs=[], deployment_sha=V022)
    assert delivery_state._read_production_sha(TAGS) == V022
    fake_production(monkeypatch, runs=[refused_run()], deployment_sha=V022)
    assert delivery_state._read_production_sha(TAGS) == V022


def test_the_workflow_job_name_is_what_the_module_parses():
    workflow = (ROOT / ".github/workflows/promote.yml").read_text()
    names = re.findall(
        r"^\s+name: (Deploy \$\{\{ needs\.guard\.outputs\.tag \}\} to production)$",
        workflow,
        re.M,
    )
    assert len(names) == 1, "promote.yml must name its deploy job exactly once"
    rendered = names[0].replace("${{ needs.guard.outputs.tag }}", "v1.2.3")
    assert delivery_state.DEPLOY_JOB_NAME.fullmatch(rendered)["tag"] == "v1.2.3"
    assert f"- name: {delivery_state.DEPLOY_STEP_NAME}\n" in workflow


# GitHub answering in a shape the reader does not expect (an error object, a
# renamed field) is a fact that cannot be read. It is named like any other,
# never a traceback: a traceback exits 1, which Promote reads as "refused".
UNEXPECTED_SHAPES = {
    "main commit": (lambda: delivery_state._read_main(), "{}"),
    "checks": (
        lambda: delivery_state._read_checks("checks", "abc"),
        '[{"message": "Not Found"}]',
    ),
    "checks listing": (
        lambda: delivery_state._read_checks("checks listing", "abc"),
        "{}",
    ),
    "version commit checks": (lambda: delivery_state._read_commit_facts("abc"), "{}"),
    "staging deployment": (lambda: delivery_state._read_staging_sha(), "[{}]"),
    "production version": (lambda: delivery_state._read_production_sha({}), "{}"),
    "version tags": (lambda: delivery_state._read_tags(), "no tab on this line\n"),
    "published releases": (lambda: delivery_state._read_releases(), "[[{}]]"),
    "release PR": (lambda: delivery_state._read_release_pr(), "[{}]"),
}


@pytest.mark.parametrize("fact", sorted(UNEXPECTED_SHAPES))
def test_a_response_in_an_unexpected_shape_names_the_fact(monkeypatch, fact):
    read, response = UNEXPECTED_SHAPES[fact]
    monkeypatch.setattr(delivery_state, "_run", lambda fact, args: response)
    with pytest.raises(delivery_state.FactUnreadable) as error:
        read()
    assert error.value.fact == fact
    assert error.value.detail.startswith("unexpected response: ")


def test_a_version_commit_compared_in_an_unexpected_shape_names_the_fact(monkeypatch):
    def fake_run(fact, args):
        return '[{"check_runs": []}]' if "check-runs" in args[-1] else "{}"

    monkeypatch.setattr(delivery_state, "_run", fake_run)
    with pytest.raises(delivery_state.FactUnreadable) as error:
        delivery_state._read_commit_facts("abc")
    assert error.value.fact == "version commit"


@pytest.mark.parametrize("compare", [{}, {"status": "ahead", "files": [{}]}, []])
def test_an_unclear_staging_gap_is_not_documentation_only(monkeypatch, compare):
    # Whether the gap is documentation only is a note on the report, so an
    # unclear answer says "differs from main" rather than stopping the report.
    monkeypatch.setattr(delivery_state, "_gh_json", lambda fact, endpoint: compare)
    assert delivery_state._read_staging_gap_docs_only("s", "m") is False


def test_an_unparseable_pause_variable_names_the_fact(monkeypatch):
    monkeypatch.delenv("STAGING_DEPLOY_PAUSED", raising=False)
    monkeypatch.setattr(
        delivery_state.subprocess,
        "run",
        lambda *args, **kwargs: delivery_state.subprocess.CompletedProcess(
            args, 0, stdout="<html>", stderr=""
        ),
    )
    with pytest.raises(delivery_state.FactUnreadable) as error:
        delivery_state._read_paused()
    assert error.value.fact == "pause variable STAGING_DEPLOY_PAUSED"


def test_an_unexpected_shape_stops_the_guard_as_unknown_not_refused(monkeypatch):
    monkeypatch.setattr(delivery_state, "_run", lambda fact, args: "{}")
    out, err = io.StringIO(), io.StringIO()
    code = delivery_state.run_guard(
        delivery_state.read_guard_snapshot, "v0.3.0", out, err
    )
    assert code == 2
    assert out.getvalue() == ""
    assert err.getvalue() == (
        "promote cannot be decided: could not read main commit "
        "(unexpected response: KeyError('sha'))\n"
    )


def test_an_unexpected_shape_stops_status_without_a_report(monkeypatch):
    monkeypatch.setattr(delivery_state, "_run", lambda fact, args: "{}")
    out, err = io.StringIO(), io.StringIO()
    code = delivery_state.run_status(delivery_state.read_snapshot, out, err)
    assert code == 1
    assert out.getvalue() == ""
    assert err.getvalue().startswith(
        "status cannot be reported: could not read main commit ("
    )


def test_an_unexpected_head_of_main_stops_staging_order(monkeypatch):
    monkeypatch.setenv("AFTER", NEW)
    monkeypatch.setenv("RUN_ATTEMPT", "1")
    monkeypatch.setattr(delivery_state, "_run", lambda fact, args: "{}")
    out, err = io.StringIO(), io.StringIO()
    assert delivery_state.run_staging_order(out, err) == 1
    assert "head of main" in err.getvalue()
    assert "deploy=" not in out.getvalue()


def workflow_jobs(path: Path) -> dict[str, tuple[str, list[str]]]:
    """Each job in a workflow file as id -> (check name, the job ids it needs).

    Read as text: the project has no YAML parser. A job without a `name` goes
    by its id, which is what GitHub calls its check.
    """
    body = path.read_text().split("\njobs:\n", 1)[1]
    jobs = {}
    for block in re.split(r"(?m)^(?=  [\w-]+:\n)", body):
        job = re.match(r"  ([\w-]+):\n", block)
        if not job:
            continue
        name = re.search(r"(?m)^    name: (.+)$", block)
        needs = re.search(r"(?m)^    needs:\n((?:      - .+\n)+)", block)
        jobs[job[1]] = (
            # Quotes and a trailing comment are YAML, not part of the name.
            re.sub(r"\s+#.*$", "", name[1]).strip("\"'") if name else job[1],
            re.findall(r"      - (.+)", needs[1]) if needs else [],
        )
    return jobs


def ci_jobs() -> dict[str, tuple[str, list[str]]]:
    return workflow_jobs(ROOT / ".github/workflows/ci.yml")


def test_the_gate_names_are_the_jobs_the_workflow_gates_on():
    # A check is matched to a gate by its job's display name. Rename a gate in
    # ci.yml alone and its check reads as missing: status says "checks still
    # running" forever and Promote always refuses.
    jobs = ci_jobs()
    gate_ids = jobs["summary"][1]
    assert [jobs[job][0] for job in gate_ids] == list(delivery_state.GATES)


@pytest.mark.parametrize("job", ["staging-order", "deploy-staging", "release-please"])
def test_nothing_deploys_or_releases_without_every_gate(job):
    jobs = ci_jobs()
    assert set(jobs["summary"][1]) <= set(jobs[job][1])


def jobs_carrying_a_gate_name(workflows: Path) -> dict[str, list[str]]:
    """Each gate name -> every job, in any workflow file, whose check has it."""
    holders: dict[str, list[str]] = {gate: [] for gate in delivery_state.GATES}
    for path in sorted([*workflows.glob("*.yml"), *workflows.glob("*.yaml")]):
        jobs = workflow_jobs(path)
        assert jobs, f"no jobs could be read from {path.name}"
        for job, (name, _) in jobs.items():
            if name in holders:
                holders[name].append(f"{path.name}: {job}")
    return holders


def test_each_gate_name_belongs_to_one_job_across_the_workflows():
    # A check is matched to a gate by its name alone, and the newest check of
    # a name wins. A second job carrying a gate's name, in any workflow, would
    # be read as that gate: a green one finishing later hides the failed gate.
    jobs = ci_jobs()
    assert jobs_carrying_a_gate_name(ROOT / ".github/workflows") == {
        jobs[job][0]: [f"ci.yml: {job}"] for job in jobs["summary"][1]
    }


@pytest.mark.parametrize(
    ("file", "job", "holder"),
    [
        ("docs.yml", "  site:\n    name: Build\n", "docs.yml: site"),
        ("docs.yml", "  Build:\n    runs-on: ubuntu-latest\n", "docs.yml: Build"),
        ("promote.yml", "  again:\n    name: Build\n", "promote.yml: again"),
        ("ci.yml", '  again:\n    name: "Build"  # twice\n', "ci.yml: again"),
    ],
    ids=["another workflow", "a job id", "the Promote workflow", "CI itself, quoted"],
)
def test_a_second_job_carrying_a_gate_name_is_found(tmp_path, file, job, holder):
    workflows = tmp_path / "workflows"
    shutil.copytree(ROOT / ".github/workflows", workflows)
    target = workflows / file
    text = target.read_text() if target.exists() else "name: Docs\non: push\n\njobs:\n"
    target.write_text(text + job)
    found = jobs_carrying_a_gate_name(workflows)["Build"]
    assert sorted(found) == sorted(["ci.yml: build", holder])


def run_gate_summary(tmp_path, results: dict[str, str]) -> tuple[int, str]:
    """Run the Summary job's script as ci.yml has it, on these gate results."""
    if not shutil.which("jq"):
        pytest.skip("the Summary job's script needs jq")
    workflow = (ROOT / ".github/workflows/ci.yml").read_text()
    step = re.search(
        r"      - name: Write the gate summary\n(?:.*\n)*?        run: \|\n"
        r"((?:(?:          .*)?\n)+)",
        workflow,
    )
    summary = tmp_path / "summary.md"
    needs = {job: {"result": result, "outputs": {}} for job, result in results.items()}
    done = subprocess.run(
        ["bash", "-c", textwrap.dedent(step[1])],
        env={
            **os.environ,
            "NEEDS": json.dumps(needs),
            "GITHUB_STEP_SUMMARY": str(summary),
        },
        capture_output=True,
        text=True,
    )
    return done.returncode, summary.read_text()


def test_the_run_summary_lists_every_gate_by_its_name(tmp_path):
    gate_ids = ci_jobs()["summary"][1]
    code, summary = run_gate_summary(tmp_path, dict.fromkeys(gate_ids, "success"))
    assert code == 0
    assert summary == (
        "## Gates\n\n| Gate | Outcome |\n| --- | --- |\n"
        + "".join(f"| {name} | success |\n" for name in delivery_state.GATES)
    )


def test_the_run_summary_names_the_gate_that_did_not_succeed(tmp_path):
    results = dict.fromkeys(ci_jobs()["summary"][1], "success")
    results["typecheck"] = "failure"
    results["migrations"] = "skipped"
    code, summary = run_gate_summary(tmp_path, results)
    assert code == 1
    assert "| Type check | failure |\n" in summary
    assert "| Migration check | skipped |\n" in summary


# Staging after two pushes in quick succession. Each push's Deploy staging waits
# for its own gates, so the older commit can finish its gates last and deploy
# over the newer one. A push run deploys only while its commit is still the head
# of main. An explicit re-run deploys the commit it ran for, which is how the
# captain returns staging to a version.
OLD = "ec87b04" + "0" * 33
NEW = "b094f90" + "0" * 33


def test_the_head_of_main_deploys():
    deploy, reason = delivery_state.staging_deploy_decision(NEW, 1, NEW)
    assert deploy
    assert "head of main" in reason


def test_a_commit_main_has_moved_past_is_skipped_and_says_why():
    deploy, reason = delivery_state.staging_deploy_decision(OLD, 1, NEW)
    assert not deploy
    assert OLD[:7] in reason and NEW[:7] in reason


def test_a_rerun_of_an_older_run_deploys_that_commit():
    deploy, reason = delivery_state.staging_deploy_decision(OLD, 2, NEW)
    assert deploy
    assert "re-run" in reason


def run_staging_order(monkeypatch, *, sha, attempt, head):
    monkeypatch.setenv("AFTER", sha)
    monkeypatch.setenv("RUN_ATTEMPT", str(attempt))
    monkeypatch.setattr(
        delivery_state,
        "_gh_json",
        lambda fact, endpoint: {"sha": head},
    )
    out, err = io.StringIO(), io.StringIO()
    code = delivery_state.run_staging_order(out, err)
    return code, out.getvalue(), err.getvalue()


def test_the_command_prints_the_job_output_and_the_reason(monkeypatch):
    code, out, _ = run_staging_order(monkeypatch, sha=OLD, attempt=1, head=NEW)
    assert code == 0
    assert out.splitlines()[0] == "deploy=false"
    code, out, _ = run_staging_order(monkeypatch, sha=NEW, attempt=1, head=NEW)
    assert out.splitlines()[0] == "deploy=true"


def test_an_unreadable_head_of_main_names_the_fact_and_fails(monkeypatch):
    def broken(fact, endpoint):
        raise delivery_state.FactUnreadable("head of main", "gh exited 1")

    monkeypatch.setenv("AFTER", NEW)
    monkeypatch.setenv("RUN_ATTEMPT", "1")
    monkeypatch.setattr(delivery_state, "_gh_json", broken)
    out, err = io.StringIO(), io.StringIO()
    assert delivery_state.run_staging_order(out, err) == 1
    assert "head of main" in err.getvalue()
    assert "deploy=" not in out.getvalue()
