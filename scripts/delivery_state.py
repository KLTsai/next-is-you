"""Delivery state: where main, staging and production are, and what to do next.

Layout, top to bottom:

1. Core. Pure functions from a Snapshot of facts to a report and one next step.
   The promote guard (ticket #73) is meant to be a second entry point over this
   same Snapshot and rules, so it belongs in this section.
2. Fact reading. The only code that talks to GitHub and Git. A fact that cannot
   be read raises FactUnreadable, naming itself.
3. Command line. `status` is the only command today.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from dataclasses import dataclass
from typing import Callable, TextIO

# Repository variable that pauses automatic staging deployment. It does not
# exist while the candidate flow is in place, and absent means not paused.
PAUSE_VARIABLE = "STAGING_DEPLOY_PAUSED"

VERSION_TAG = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")


class FactUnreadable(Exception):
    """A fact the report needs could not be read."""

    def __init__(self, fact: str, detail: str) -> None:
        super().__init__(f"{fact}: {detail}")
        self.fact = fact
        self.detail = detail


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MainState:
    sha: str
    checks: str  # "success", "failure" or "pending"
    failed: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReleasePR:
    number: int
    version: str  # without the leading "v"
    changes: int


@dataclass(frozen=True)
class Snapshot:
    main: MainState
    staging_sha: str | None  # latest successful staging deployment, if any
    staging_paused: bool
    tags: dict[str, str]  # "vX.Y.Z" -> commit
    releases: frozenset[str]  # published (not draft) "vX.Y.Z" releases
    release_pr: ReleasePR | None

    @classmethod
    def from_dict(cls, data: dict) -> Snapshot:
        pr = data["release_pr"]
        return cls(
            main=MainState(
                sha=data["main"]["sha"],
                checks=data["main"]["checks"],
                failed=tuple(data["main"]["failed"]),
            ),
            staging_sha=data["staging_sha"],
            staging_paused=data["staging_paused"],
            tags=dict(data["tags"]),
            releases=frozenset(data["releases"]),
            release_pr=ReleasePR(**pr) if pr else None,
        )


@dataclass(frozen=True)
class Report:
    lines: tuple[str, ...]
    next_step: str

    def render(self) -> str:
        return "\n".join([*self.lines, "", f"Next step: {self.next_step}"]) + "\n"


def _version_key(tag: str) -> tuple[int, int, int]:
    match = VERSION_TAG.fullmatch(tag)
    assert match is not None, tag
    return int(match[1]), int(match[2]), int(match[3])


def _short(sha: str) -> str:
    return sha[:7]


def _row(label: str, value: str) -> str:
    return f"{label:<11} {value}"


def build_report(snapshot: Snapshot) -> Report:
    main = snapshot.main
    releases = sorted(snapshot.releases, key=_version_key)
    production = releases[-1] if releases else None
    unreleased = sorted(
        (tag for tag in snapshot.tags if tag not in snapshot.releases),
        key=_version_key,
    )
    # A tag older than what is in production was passed over, not pending.
    pending = [
        tag
        for tag in unreleased
        if production is None or _version_key(tag) > _version_key(production)
    ]
    staging_is_main = snapshot.staging_sha == main.sha

    if main.checks == "success":
        main_text = "checks passed"
    elif main.checks == "failure":
        failed = ", ".join(main.failed)
        main_text = f"checks failed ({failed})" if failed else "checks failed"
    else:
        main_text = "checks still running"

    if snapshot.staging_sha is None:
        staging_text = "none - nothing deployed"
    elif staging_is_main:
        staging_text = f"{_short(main.sha)} - same as main"
    else:
        staging_text = f"{_short(snapshot.staging_sha)} - differs from main"

    pr = snapshot.release_pr
    if pr is None:
        next_text = "none - no release PR, nothing releasable"
    else:
        noun = "change" if pr.changes == 1 else "changes"
        next_text = f"v{pr.version} - release PR #{pr.number}, {pr.changes} {noun}"

    lines = [
        _row("main", f"{_short(main.sha)} - {main_text}"),
        _row("staging", staging_text),
        _row("production", production or "none"),
        _row("next", next_text),
    ]
    if snapshot.staging_paused:
        lines.append(_row("paused", "automatic staging deployment is paused"))
    for tag in unreleased:
        lines.append(_row("tagged", f"{tag} - tagged, not yet a Release"))

    return Report(tuple(lines), _next_step(snapshot, pending, staging_is_main))


def _next_step(snapshot: Snapshot, pending: list[str], staging_is_main: bool) -> str:
    main = snapshot.main
    if main.checks == "failure":
        failed = ", ".join(main.failed)
        detail = f"checks failed ({failed})" if failed else "checks failed"
        return f"Fix main: {detail}. Do not promote until they pass."
    if main.checks != "success":
        return "Wait for the checks on main to finish, then run status again."
    if pending:
        tag = pending[-1]
        if snapshot.staging_sha == snapshot.tags[tag]:
            return f"Check {tag} on staging, then promote it."
        shown = snapshot.staging_sha
        where = f"staging shows {_short(shown)}" if shown else "staging shows nothing"
        return f"Put {tag} on staging ({where}), check it, then promote it."
    if snapshot.staging_paused:
        return (
            "Automatic staging deployment is paused. "
            "Resume it when you finish checking."
        )
    if not staging_is_main:
        return (
            "Staging is not showing main. "
            "Deploy main to staging, then run status again."
        )
    if snapshot.release_pr is not None:
        pr = snapshot.release_pr
        return (
            f"Merge release PR #{pr.number} to cut v{pr.version}, "
            "or leave it open to collect more changes."
        )
    return "Nothing to do."


# ---------------------------------------------------------------------------
# Fact reading (the only part that talks to GitHub and Git)
# ---------------------------------------------------------------------------


def _run(fact: str, args: list[str]) -> str:
    try:
        result = subprocess.run(args, capture_output=True, text=True, check=False)
    except OSError as error:
        raise FactUnreadable(fact, f"cannot run {args[0]}: {error}") from error
    if result.returncode != 0:
        detail = result.stderr.strip() or f"{args[0]} exited {result.returncode}"
        raise FactUnreadable(fact, detail)
    return result.stdout


def _gh_json(fact: str, endpoint: str):
    out = _run(fact, ["gh", "api", endpoint])
    try:
        return json.loads(out)
    except json.JSONDecodeError as error:
        raise FactUnreadable(fact, f"unparseable response: {error}") from error


def _read_main() -> MainState:
    fact = "main commit checks"
    sha = _gh_json("main commit", "repos/{owner}/{repo}/commits/main")["sha"]
    runs = _gh_json(
        fact, f"repos/{{owner}}/{{repo}}/commits/{sha}/check-runs?per_page=100"
    )["check_runs"]
    failed = tuple(
        run["name"]
        for run in runs
        if run["status"] == "completed"
        and run["conclusion"]
        in {"failure", "cancelled", "timed_out", "action_required"}
    )
    if failed:
        return MainState(sha, "failure", failed)
    if not runs or any(run["status"] != "completed" for run in runs):
        return MainState(sha, "pending")
    return MainState(sha, "success")


def _read_staging_sha() -> str | None:
    fact = "staging deployment"
    deployments = _gh_json(
        fact, "repos/{owner}/{repo}/deployments?environment=staging&per_page=20"
    )
    for deployment in deployments:
        statuses = _gh_json(
            fact, f"repos/{{owner}}/{{repo}}/deployments/{deployment['id']}/statuses"
        )
        if statuses and statuses[0]["state"] == "success":
            return deployment["sha"]
    return None


def _read_paused() -> bool:
    fact = f"pause variable {PAUSE_VARIABLE}"
    try:
        result = subprocess.run(
            [
                "gh",
                "api",
                f"repos/{{owner}}/{{repo}}/actions/variables/{PAUSE_VARIABLE}",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as error:
        raise FactUnreadable(fact, f"cannot run gh: {error}") from error
    if result.returncode != 0:
        if "404" in result.stderr:
            return False
        raise FactUnreadable(fact, result.stderr.strip() or "gh failed")
    return json.loads(result.stdout).get("value", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }


def _read_tags() -> dict[str, str]:
    out = _run("version tags", ["git", "ls-remote", "--tags", "origin", "refs/tags/v*"])
    tags: dict[str, str] = {}
    for line in out.splitlines():
        sha, ref = line.split("\t")
        name = ref.removeprefix("refs/tags/").removesuffix("^{}")
        if not VERSION_TAG.fullmatch(name):
            continue
        # The peeled line (^{}) is the commit an annotated tag points at, and
        # comes after the tag object line, so it wins.
        if ref.endswith("^{}") or name not in tags:
            tags[name] = sha
    return tags


def _read_releases() -> frozenset[str]:
    releases = _gh_json(
        "published releases", "repos/{owner}/{repo}/releases?per_page=100"
    )
    return frozenset(
        r["tag_name"]
        for r in releases
        if not r["draft"] and VERSION_TAG.fullmatch(r["tag_name"])
    )


def _read_release_pr() -> ReleasePR | None:
    fact = "release PR"
    out = _run(
        fact,
        [
            "gh",
            "pr",
            "list",
            "--state",
            "open",
            "--label",
            "autorelease: pending",
            "--json",
            "number,title,body",
        ],
    )
    prs = json.loads(out)
    if not prs:
        return None
    pr = prs[0]
    match = re.search(r"release (\d+\.\d+\.\d+)", pr["title"])
    if match is None:
        raise FactUnreadable(fact, f"no version in title {pr['title']!r}")
    # Release Please lists each change as a top-level "* " bullet.
    changes = sum(1 for line in pr["body"].splitlines() if line.startswith("* "))
    return ReleasePR(pr["number"], match[1], changes)


def read_snapshot() -> Snapshot:
    return Snapshot(
        main=_read_main(),
        staging_sha=_read_staging_sha(),
        staging_paused=_read_paused(),
        tags=_read_tags(),
        releases=_read_releases(),
        release_pr=_read_release_pr(),
    )


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------


def run_status(reader: Callable[[], Snapshot], out: TextIO, err: TextIO) -> int:
    try:
        snapshot = reader()
    except FactUnreadable as error:
        err.write(
            f"status cannot be reported: could not read {error.fact} ({error.detail})\n"
        )
        return 1
    out.write(build_report(snapshot).render())
    return 0


def main(argv: list[str]) -> int:
    if argv != ["status"]:
        sys.stderr.write("usage: delivery_state.py status\n")
        return 2
    return run_status(read_snapshot, sys.stdout, sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
