"""Deployment config checks for the version shown in run titles and summaries (#213)."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_promote_runs_are_titled_with_their_version():
    promote = (ROOT / ".github/workflows/promote.yml").read_text()
    assert re.search(
        r"^run-name: Promote \$\{\{ inputs\.version \}\} to production$", promote, re.M
    )


def test_ci_keeps_the_default_run_title():
    # docs/CI-CD.md finds a version's run by its release commit title.
    assert "run-name:" not in (ROOT / ".github/workflows/ci.yml").read_text()


def test_staging_summary_describes_the_commit_from_full_history():
    ci = (ROOT / ".github/workflows/ci.yml").read_text()
    job = ci.split("  deploy-staging:", 1)[1].split("  release-please:", 1)[0]
    assert "fetch-depth: 0" in job
    assert "git describe --tags --match 'v*'" in job
