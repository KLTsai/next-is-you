"""Deployment config test: live is a committed value, never a dashboard setting (#237).

Each environment's live state (GLOSSARY.md: Live) is `vars.NIY_LIVE` in its own
`wrangler.*.jsonc`, so it changes only through a pull request the captain
merges. Every deploy writes the committed value over whatever the dashboard
holds, and Cloudflare does not let a secret share a var's name. These checks
keep it that way: every config carries the value, nothing deploys it from
anywhere else, and the code reads it from that one name. A dashboard edit
between deploys is outside what a test can see; the pre-live checklist forbids it.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

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


def _deploy_surfaces() -> list[Path]:
    return [
        *sorted((ROOT / ".github" / "workflows").glob("*.yml")),
        *sorted((ROOT / "scripts").glob("*")),
        ROOT / "package.json",
        *sorted(ROOT.glob("*.md")),
        *sorted((ROOT / "docs").glob("*.md")),
    ]


def test_nothing_sets_live_as_a_secret_or_a_deploy_time_var() -> None:
    offenders = []
    for path in _deploy_surfaces():
        if not path.is_file():
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
            if re.search(rf"secret\s+put\s+{LIVE}\b|--var[\s=]+[\"']?{LIVE}\b", line):
                offenders.append(f"{path.relative_to(ROOT)}:{number + 1}: {line}")
    assert not offenders, "\n".join(offenders)


def test_deploys_take_vars_from_the_committed_config_only() -> None:
    for workflow in (ROOT / ".github" / "workflows").glob("*.yml"):
        for line in workflow.read_text(encoding="utf-8").splitlines():
            if "pywrangler deploy" in line:
                assert "--var" not in line, f"{workflow.name}: {line.strip()}"
                assert re.search(r"--config wrangler\.\w+\.jsonc", line), line
