"""Staging must not name any of Production's resources.

Staging is the captain's own test environment; Production reaches the
family. A Staging config that points at Production's Worker, D1 database or
LINE channel would touch the family's data while every other test stays
green, so this test compares the two deploy configs directly.

Secrets are not compared: their names match by design and their values are
not in the repository.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
STAGING_CONFIG = ROOT / "wrangler.staging.jsonc"
PRODUCTION_CONFIG = ROOT / "wrangler.production.jsonc"


def _strip_jsonc(text: str) -> str:
    """Removes // and /* */ comments and trailing commas outside strings."""
    out: list[str] = []
    i = 0
    in_string = False
    while i < len(text):
        char = text[i]
        if in_string:
            out.append(char)
            if char == "\\":
                out.append(text[i + 1])
                i += 1
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
            out.append(char)
        elif text.startswith("//", i):
            end = text.find("\n", i)
            i = len(text) if end == -1 else end
            continue
        elif text.startswith("/*", i):
            i = text.index("*/", i + 2) + 2
            continue
        elif char in "}]":
            while out and out[-1].isspace():
                out.pop()
            if out and out[-1] == ",":
                out.pop()
            out.append(char)
        else:
            out.append(char)
        i += 1
    return "".join(out)


def _load(path: Path) -> dict:
    return json.loads(_strip_jsonc(path.read_text(encoding="utf-8")))


@pytest.fixture(scope="module")
def staging() -> dict:
    return _load(STAGING_CONFIG)


@pytest.fixture(scope="module")
def production() -> dict:
    return _load(PRODUCTION_CONFIG)


def test_jsonc_reader_ignores_comments_and_trailing_commas() -> None:
    text = '{\n  // a "comment"\n  "url": "https://x/*y*/", /* note */\n  "list": [1, 2,],\n}\n'
    assert json.loads(_strip_jsonc(text)) == {"url": "https://x/*y*/", "list": [1, 2]}


def test_staging_worker_name_differs_from_production(
    staging: dict, production: dict
) -> None:
    assert staging["name"] != production["name"]


@pytest.mark.parametrize("field", ["database_name", "database_id"])
def test_staging_d1_databases_differ_from_production(
    staging: dict, production: dict, field: str
) -> None:
    staging_values = {db[field] for db in staging["d1_databases"]}
    production_values = {db[field] for db in production["d1_databases"]}
    assert staging_values, f"Staging names no D1 {field}"
    assert production_values, f"Production names no D1 {field}"
    shared = staging_values & production_values
    assert not shared, f"Staging names Production's D1 {field}: {sorted(shared)}"


def test_each_config_names_its_own_environment(staging: dict, production: dict) -> None:
    assert staging["vars"]["NIY_ENVIRONMENT"] == "staging"
    assert production["vars"]["NIY_ENVIRONMENT"] == "production"


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Staging still uses Production's LINE Login channel until its own LINE "
        "provider exists (ADR 0004, https://github.com/KLTsai/next-is-you/issues/129). "
        "Remove this xfail when #129 changes the channel."
    ),
)
def test_staging_line_login_channel_differs_from_production(
    staging: dict, production: dict
) -> None:
    assert (
        staging["vars"]["LINE_LOGIN_CHANNEL_ID"]
        != production["vars"]["LINE_LOGIN_CHANNEL_ID"]
    )
