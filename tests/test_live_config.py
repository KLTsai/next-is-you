"""Deployment config test: live is a committed value, never a dashboard setting (#237).

Each environment's live state (GLOSSARY.md: Live) is `vars.NIY_LIVE` in its own
`wrangler.*.jsonc`, so it changes only through a pull request the captain
merges. Every deploy writes the committed value over whatever the dashboard
holds, and Cloudflare does not let a secret share a var's name. These checks
keep it that way: every config carries the value, no workflow step sets it as
a secret or passes it at deploy time, and the code reads it from that one name.
A dashboard edit between deploys is outside what a test can see; the pre-live
checklist forbids it.
"""

from __future__ import annotations

import json
import re
import shlex
from pathlib import Path

import pytest
import yaml

from next_is_you.send_gate import committed_live

ROOT = Path(__file__).resolve().parents[1]
CONFIGS = sorted(ROOT.glob("wrangler*.jsonc"))
DEPLOYED = ("wrangler.staging.jsonc", "wrangler.production.jsonc")
LIVE = "NIY_LIVE"


def _vars(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")).get("vars", {})


def test_every_wrangler_config_is_checked() -> None:
    names = {path.name for path in CONFIGS}
    assert set(DEPLOYED) <= names
    assert "wrangler.niy006.test.jsonc" in names


@pytest.mark.parametrize("config", CONFIGS, ids=lambda path: path.name)
def test_each_config_commits_its_live_value(config: Path) -> None:
    variables = _vars(config)
    assert LIVE in variables, f"{config.name} must commit vars.{LIVE}"
    assert variables[LIVE] in {"true", "false"}, (
        f'{config.name}: vars.{LIVE} must be the string "true" or "false"'
    )


@pytest.mark.parametrize("config", CONFIGS, ids=lambda path: path.name)
def test_a_live_config_commits_its_own_line_official_account(config: Path) -> None:
    variables = _vars(config)
    if variables[LIVE] != "true":
        return
    basic_id = variables.get("LINE_BOT_BASIC_ID", "")
    assert re.fullmatch(r"@\w+", basic_id), (
        f"{config.name} is live, so it must commit LINE_BOT_BASIC_ID, the basic "
        "ID of its own Official Account (for example @123abcde)"
    )


def test_staging_and_production_never_name_the_same_official_account() -> None:
    accounts = [_vars(ROOT / name).get("LINE_BOT_BASIC_ID") for name in DEPLOYED]
    if all(accounts):
        assert accounts[0].casefold() != accounts[1].casefold()


def test_only_the_committed_value_is_live() -> None:
    assert committed_live({LIVE: "true"})
    for value in (None, "", "false", "1", "yes", "TRUE", " true", True):
        assert not committed_live({LIVE: value} if value is not None else {})


WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.yml"))


def job_steps(workflow: Path, job: str) -> list[dict]:
    return yaml.safe_load(workflow.read_text(encoding="utf-8"))["jobs"][job]["steps"]


def all_steps() -> list[tuple[str, dict]]:
    steps = []
    for workflow in WORKFLOWS:
        jobs = yaml.safe_load(workflow.read_text(encoding="utf-8"))["jobs"]
        for name, job in jobs.items():
            steps += [
                (f"{workflow.name} {name}", step) for step in job.get("steps", [])
            ]
    return steps


def argv(step: dict) -> list[str]:
    """The shell words of a step's run script, comments left out."""
    return shlex.split(str(step.get("run", "")), comments=True)


def runs(step: dict, *words: str) -> bool:
    """Whether the step's run script has these words in a row."""
    tokens = argv(step)
    return any(
        tokens[start : start + len(words)] == list(words)
        for start in range(len(tokens))
    )


def test_no_workflow_sets_live_as_a_secret() -> None:
    offenders = [
        where for where, step in all_steps() if runs(step, "secret", "put", LIVE)
    ]
    assert not offenders


def test_deploys_take_vars_from_the_committed_config_only() -> None:
    deploys = [
        (where, step)
        for where, step in all_steps()
        if runs(step, "pywrangler", "deploy")
    ]
    assert len(deploys) == len(DEPLOYED)
    configs = set()
    for where, step in deploys:
        tokens = argv(step)
        assert not [t for t in tokens if t.startswith("--var")], where
        assert "--config" in tokens, where
        configs.add(tokens[tokens.index("--config") + 1])
    assert configs == set(DEPLOYED)
