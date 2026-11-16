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
        delivery_state, "_gh_json", lambda fact, endpoint: {"check_runs": runs}
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


# Production after a rollback. The deployment record GitHub keeps for the prod
# environment names the commit Promote was dispatched from (the head of main),
# not the commit it deployed, so production must be read from the Promote run.
V022 = "5c9f7471cf4fd3d83cb9fb11c88505b3e6380dc0"
V023 = "d52eef8d68409365adf24f154e0cd2cc454794c3"
TAGS = {"v0.2.2": V022, "v0.2.3": V023}


def fake_production(monkeypatch, *, promote_runs, deploy_job_names, deployment_sha):
    def fake_gh(fact, endpoint):
        if "workflows/promote.yml/runs" in endpoint:
            return {"workflow_runs": [{"id": run} for run in promote_runs]}
        if endpoint.endswith("/jobs"):
            return {"jobs": [{"name": name} for name in deploy_job_names]}
        if "deployments?environment=prod" in endpoint:
            return [{"id": 1, "sha": deployment_sha}]
        if endpoint.endswith("/deployments/1/statuses"):
            return [{"state": "success"}]
        raise AssertionError(f"unexpected endpoint {endpoint}")

    monkeypatch.setattr(delivery_state, "_gh_json", fake_gh)


def test_production_is_the_version_the_last_promote_deployed(monkeypatch):
    # v0.2.3 was promoted, then v0.2.2 was promoted as a rollback. Both Promote
    # runs were dispatched from main, so the deployment record says v0.2.3.
    fake_production(
        monkeypatch,
        promote_runs=[2, 1],
        deploy_job_names=[
            "Promote guard",
            "Require main",
            "Deploy v0.2.2 to production",
        ],
        deployment_sha=V023,
    )
    assert delivery_state._read_production_sha(TAGS) == V022


def test_production_falls_back_to_the_deployment_before_any_promote(monkeypatch):
    fake_production(
        monkeypatch, promote_runs=[], deploy_job_names=[], deployment_sha=V022
    )
    assert delivery_state._read_production_sha(TAGS) == V022
