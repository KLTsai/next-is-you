"""Staging must not name any of Production's resources.

Staging is the captain's own test environment; Production reaches the
family. A Staging config that points at Production's Worker, D1 database or
LINE channel would touch the family's data while every other test stays
green, so this test compares the two deploy configs directly.

The comparison fails closed: every value in Staging must differ from
Production unless its field is on a reviewed allowlist. A binding added to
either config later is checked without anyone listing its fields here first.

Secrets are not compared: their names match by design and their values are
not in the repository.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
STAGING_CONFIG = ROOT / "wrangler.staging.jsonc"
PRODUCTION_CONFIG = ROOT / "wrangler.production.jsonc"


@dataclass(frozen=True)
class SharedValue:
    staging_path: str
    production_path: str
    value: object


Segments = tuple[str, ...]
LIST_ENTRY = "[]"

# Reviewed fields that are meant to match between Staging and Production.
# Every other value must differ, so a field added later fails this test until
# it is reviewed here. Each pattern names one field exactly: `[]` stands for
# any list entry and `*` for any one key.
ALLOWLIST = (
    "$schema",
    "main",
    "compatibility_date",
    "compatibility_flags[]",
    "assets.directory",
    "assets.binding",
    "assets.run_worker_first",
    "*[].binding",
    "queues.producers[].binding",
    "d1_databases[].migrations_dir",
    "durable_objects.bindings[].name",
    "durable_objects.bindings[].class_name",
    "exports.*.type",
    "exports.*.storage",
    "triggers.crons[]",
    "observability.enabled",
    "workers_dev",
    "preview_urls",
    "keep_vars",
    "vars.NIY006_LOCAL_TEST_MODE",
    "vars.NIY_LIVE",
)


def _is_list_entry(segment: str) -> bool:
    return segment.startswith("[")


def _compile(allowlist: tuple[str, ...]) -> tuple[re.Pattern[str], ...]:
    return tuple(
        re.compile(re.escape(field).replace(r"\*", r"[^.\[]+")) for field in allowlist
    )


def _leaves(node: object, path: Segments = ()) -> Iterator[tuple[Segments, object]]:
    if isinstance(node, dict):
        for key, child in node.items():
            yield from _leaves(child, (*path, key))
    elif isinstance(node, list):
        for index, child in enumerate(node):
            yield from _leaves(child, (*path, f"[{index}]"))
    else:
        yield path, node


def _shape(path: Segments) -> Segments:
    # A list index says where an entry sits, not which resource it names, so
    # entries of a list are compared as a set whatever their order.
    return tuple(LIST_ENTRY if _is_list_entry(s) else s for s in path)


def _render(path: Segments) -> str:
    return "".join(
        s if _is_list_entry(s) or not i else f".{s}" for i, s in enumerate(path)
    )


def _is_identifier(value: object) -> bool:
    return isinstance(value, str)


def _same(staging_value: object, production_value: object) -> bool:
    # Hostnames and many resource names are case-insensitive, so strings are
    # compared without case. A number names the same thing as a string with
    # the same text, such as a channel ID written either way in `vars`.
    if _is_identifier(staging_value) or _is_identifier(production_value):
        return str(staging_value).casefold() == str(production_value).casefold()
    return staging_value == production_value


def shared_values(
    staging: dict, production: dict, allowlist: tuple[str, ...] = ALLOWLIST
) -> list[SharedValue]:
    """Every value Staging shares with Production outside the allowlist.

    A match is allowed only when both paths are allowlisted, so a resource
    identifier cannot hide by moving into an allowlisted field on one side.
    """
    patterns = _compile(allowlist)

    def allowlisted(path: Segments) -> bool:
        shape = _render(_shape(path))
        return any(pattern.fullmatch(shape) for pattern in patterns)

    production_leaves = list(_leaves(production))
    findings = []
    for staging_path, staging_value in _leaves(staging):
        for production_path, production_value in production_leaves:
            if not _same(staging_value, production_value):
                continue
            if allowlisted(staging_path) and allowlisted(production_path):
                continue
            # A string names a resource wherever it sits, so a shared string
            # counts under any two paths. A flag or number only counts at the
            # same path, where it means the same setting.
            if (
                _is_identifier(staging_value)
                or _is_identifier(production_value)
                or _shape(staging_path) == _shape(production_path)
            ):
                findings.append(
                    SharedValue(
                        _render(staging_path), _render(production_path), staging_value
                    )
                )
    return findings


def _load(path: Path) -> dict:
    # The configs are plain JSON today. A comment or trailing comma added
    # later fails here with a JSONDecodeError instead of passing silently.
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def staging() -> dict:
    return _load(STAGING_CONFIG)


@pytest.fixture(scope="module")
def production() -> dict:
    return _load(PRODUCTION_CONFIG)


# Staging still uses Production's LINE Login channel until #129 gives it its
# own LINE provider. The real configs must share exactly this value and no
# other, so the gap cannot outlive #129: once the channels differ, both this
# test and the strict xfail below fail until the gap is removed.
LINE_CHANNEL_GAP = "vars.LINE_LOGIN_CHANNEL_ID"


def test_staging_shares_no_value_with_production(
    staging: dict, production: dict
) -> None:
    findings = shared_values(staging, production)
    unexpected = [f for f in findings if f.staging_path != LINE_CHANNEL_GAP]
    assert not unexpected, "Staging shares Production's values:\n" + "\n".join(
        f"  staging {f.staging_path} = production {f.production_path} = {f.value!r}"
        for f in unexpected
    )
    assert [f.staging_path for f in findings] == [LINE_CHANNEL_GAP], (
        "Staging no longer shares Production's LINE Login channel (#129). "
        "Remove LINE_CHANNEL_GAP and the strict xfail on the channel test."
    )


def test_each_config_names_its_own_environment(staging: dict, production: dict) -> None:
    assert staging["vars"]["NIY_ENVIRONMENT"] == "staging"
    assert production["vars"]["NIY_ENVIRONMENT"] == "production"


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
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


def test_rule_names_a_shared_d1_database_id() -> None:
    staging = {"d1_databases": [{"database_id": "prod-db-id"}]}
    production = {"d1_databases": [{"database_id": "prod-db-id"}]}

    findings = shared_values(staging, production)

    assert [f.staging_path for f in findings] == ["d1_databases[0].database_id"]
    assert findings[0].value == "prod-db-id"


def test_rule_matches_list_entries_regardless_of_order() -> None:
    staging = {"kv_namespaces": [{"id": "staging-kv"}, {"id": "prod-kv"}]}
    production = {"kv_namespaces": [{"id": "prod-kv"}, {"id": "other-prod-kv"}]}

    findings = shared_values(staging, production)

    assert findings == [
        SharedValue("kv_namespaces[1].id", "kv_namespaces[0].id", "prod-kv")
    ]


def test_rule_finds_a_shared_identifier_under_a_different_field() -> None:
    staging = {"queues": {"producers": [{"queue": "prod-queue"}]}}
    production = {"queues": {"consumers": [{"queue": "prod-queue"}]}}

    findings = shared_values(staging, production)

    assert findings == [
        SharedValue(
            "queues.producers[0].queue", "queues.consumers[0].queue", "prod-queue"
        )
    ]


def _synthetic_config(environment: str) -> dict:
    """A config whose only shared values sit at allowlisted paths."""
    return {
        "$schema": "node_modules/wrangler/config-schema.json",
        "name": f"worker-{environment}",
        "main": "src/worker.py",
        "compatibility_date": "2026-09-25",
        "compatibility_flags": ["python_workers"],
        "assets": {
            "directory": "./dist/",
            "binding": "ASSETS",
            "run_worker_first": True,
        },
        "d1_databases": [
            {
                "binding": "DB",
                "database_name": f"db-{environment}",
                "database_id": f"db-id-{environment}",
                "migrations_dir": "migrations",
            }
        ],
        "durable_objects": {
            "bindings": [{"name": "SEND_GATE", "class_name": "SystemSendGate"}]
        },
        "exports": {"SystemSendGate": {"type": "durable-object", "storage": "sqlite"}},
        "triggers": {"crons": ["*/5 * * * *"]},
        "observability": {"enabled": True},
        "workers_dev": True,
        "preview_urls": False,
        "keep_vars": True,
        "vars": {"NIY_ENVIRONMENT": environment, "NIY006_LOCAL_TEST_MODE": "0"},
    }


def test_rule_passes_a_pair_that_shares_only_allowlisted_values() -> None:
    assert (
        shared_values(_synthetic_config("staging"), _synthetic_config("production"))
        == []
    )


def test_rule_fails_closed_on_a_new_field_that_is_not_allowlisted() -> None:
    staging = _synthetic_config("staging")
    production = _synthetic_config("production")
    staging["limits"] = {"cpu_ms": 50}
    production["limits"] = {"cpu_ms": 50}

    findings = shared_values(staging, production)

    assert findings == [SharedValue("limits.cpu_ms", "limits.cpu_ms", 50)]


SHARED_RESOURCES = [
    pytest.param(
        "kv_namespaces",
        [{"binding": "CACHE", "id": "prod-kv-id"}],
        "kv_namespaces[0].id",
        id="kv namespace id",
    ),
    pytest.param(
        "r2_buckets",
        [{"binding": "FILES", "bucket_name": "prod-bucket"}],
        "r2_buckets[0].bucket_name",
        id="r2 bucket name",
    ),
    pytest.param(
        "queues",
        {"producers": [{"binding": "JOBS", "queue": "prod-queue"}]},
        "queues.producers[0].queue",
        id="queue producer",
    ),
    pytest.param(
        "queues",
        {"consumers": [{"queue": "prod-queue"}]},
        "queues.consumers[0].queue",
        id="queue consumer",
    ),
    pytest.param(
        "routes",
        [{"pattern": "family.example.com/*", "zone_name": "example.com"}],
        "routes[0].pattern",
        id="route pattern",
    ),
    pytest.param(
        "routes",
        [{"pattern": "family.example.com", "custom_domain": True}],
        "routes[0].pattern",
        id="custom domain",
    ),
    pytest.param(
        "services",
        [{"binding": "AUTH", "service": "prod-auth-worker"}],
        "services[0].service",
        id="service binding",
    ),
]


@pytest.mark.parametrize(("config_key", "resource", "shared_path"), SHARED_RESOURCES)
def test_rule_names_a_shared_production_resource(
    config_key: str, resource: object, shared_path: str
) -> None:
    staging = _synthetic_config("staging")
    production = _synthetic_config("production")
    staging[config_key] = resource
    production[config_key] = resource

    findings = shared_values(staging, production)

    assert shared_path in {f.staging_path for f in findings}


def test_rule_checks_new_fields_inside_an_allowlisted_block() -> None:
    staging = _synthetic_config("staging")
    production = _synthetic_config("production")
    staging["observability"]["logs"] = {"destinations": ["prod-sink"]}
    production["observability"]["logs"] = {"destinations": ["prod-sink"]}

    findings = shared_values(staging, production)

    assert [f.staging_path for f in findings] == ["observability.logs.destinations[0]"]


def test_rule_ignores_case_when_comparing_identifiers() -> None:
    staging = {"routes": ["Family.Example.com/*"]}
    production = {"routes": ["family.example.com/*"]}

    findings = shared_values(staging, production)

    assert [f.staging_path for f in findings] == ["routes[0]"]


def test_rule_matches_a_number_and_a_string_with_the_same_text() -> None:
    staging = {"vars": {"CHANNEL": 2011753957}}
    production = {"vars": {"CHANNEL": "2011753957"}}

    findings = shared_values(staging, production)

    assert [f.staging_path for f in findings] == ["vars.CHANNEL"]
