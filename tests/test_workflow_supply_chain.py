"""Deployment config checks for what the workflows trust (#214).

The deploy jobs hold the Cloudflare token, so every action is pinned to a commit
a tag move cannot change, Dependabot keeps those pins current without proposing
a release, and the Promote workflow grants its token nothing a job did not ask
for.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from pr_title_gate import title_type  # noqa: E402

WORKFLOW_DIR = ROOT / ".github" / "workflows"
WORKFLOWS = sorted([*WORKFLOW_DIR.glob("*.yml"), *WORKFLOW_DIR.glob("*.yaml")])
USES = re.compile(r"^[^#]*\buses:")
PINNED = re.compile(r"\s*(- )?uses: [\w./-]+@[0-9a-f]{40} # v\d+\.\d+\.\d+")


@pytest.mark.parametrize("workflow", WORKFLOWS, ids=lambda path: path.name)
def test_every_action_is_pinned_to_a_commit_that_names_its_version(
    workflow: Path,
) -> None:
    unpinned = [
        f"{workflow.name}:{number}: {line.strip()}"
        for number, line in enumerate(
            workflow.read_text(encoding="utf-8").splitlines(), start=1
        )
        if USES.match(line) and not PINNED.fullmatch(line)
    ]
    assert not unpinned


def test_dependabot_updates_only_actions_under_a_type_that_releases_nothing() -> None:
    config = yaml.safe_load(
        (ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8")
    )
    [update] = config["updates"]
    assert update["package-ecosystem"] == "github-actions"
    assert update["directory"] == "/"
    # Dependabot adds the colon after a prefix that ends in a letter.
    prefix = update["commit-message"]["prefix"]
    assert title_type(f"{prefix}: bump actions/checkout") in {"ci", "build"}


def test_promote_grants_nothing_a_job_did_not_declare() -> None:
    promote = yaml.safe_load((WORKFLOW_DIR / "promote.yml").read_text(encoding="utf-8"))
    assert promote["permissions"] == {}
    assert {name: job.get("permissions") for name, job in promote["jobs"].items()} == {
        "require-main": None,
        "guard": {"contents": "read", "checks": "read", "deployments": "read"},
        "deploy": {"contents": "write"},
    }
