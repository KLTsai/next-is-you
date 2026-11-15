"""Delivery state: where main, staging and production are, and what to do next.

Layout, top to bottom:

1. Core. Pure functions from a Snapshot of facts to a report and one next step
   (`status`), and to a verdict on one version (`guard`, the promote guard).
2. Fact reading. The only code that talks to GitHub and Git. A fact that cannot
   be read raises FactUnreadable, naming itself.
3. Command line. `status` and `guard <version>`.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
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
class CommitFacts:
    """What the promote guard needs to know about one version's commit."""

    on_main: bool
    checks: str  # "success", "failure" or "pending"
    failed: tuple[str, ...] = ()


@dataclass(frozen=True)
class Snapshot:
    main: MainState
    staging_sha: str | None  # latest successful staging deployment, if any
    staging_paused: bool
    tags: dict[str, str]  # "vX.Y.Z" -> commit
    releases: frozenset[str]  # published (not draft) "vX.Y.Z" releases
    release_pr: ReleasePR | None
    # Whether every commit between staging and main touched only documentation.
    staging_gap_docs_only: bool = False
    # Facts about the commits of the versions the guard was asked about.
    commits: dict[str, CommitFacts] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> Snapshot:
        pr = data["release_pr"]
        return cls(
            staging_gap_docs_only=data.get("staging_gap_docs_only", False),
            commits={
                sha: CommitFacts(
                    on_main=facts["on_main"],
                    checks=facts["checks"],
                    failed=tuple(facts["failed"]),
                )
                for sha, facts in data.get("commits", {}).items()
            },
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
    elif snapshot.staging_gap_docs_only:
        staging_text = (
            f"{_short(snapshot.staging_sha)} - differs from main, documentation only"
        )
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
    # Documentation-only pushes never deploy staging, so a gap made only of
    # them is expected and asks for nothing.
    if not staging_is_main and not snapshot.staging_gap_docs_only:
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


@dataclass(frozen=True)
class Verdict:
    version: str
    commit: str | None = None  # set when accepted
    reason: str | None = None  # set when refused
    action: str | None = None  # set when refused

    @property
    def accepted(self) -> bool:
        return self.reason is None

    def render(self) -> str:
        if self.accepted:
            return f"Accepted: {self.version} at {self.commit}\n"
        return f"Refused: {self.reason}\nTo clear it: {self.action}\n"


def normalize_version(text: str) -> str:
    """Accept "0.3.0" as well as "v0.3.0"; anything else is returned as typed."""
    stripped = text.strip()
    return f"v{stripped}" if re.fullmatch(r"\d+\.\d+\.\d+", stripped) else stripped


def promote_guard(snapshot: Snapshot, version: str) -> Verdict:
    """Decide whether a version may be promoted. One refusal reason at a time.

    Promoting an earlier version is rollback and the version already in
    production is a retry, so neither is special: every version faces the same
    four questions, in this order.
    """
    version = normalize_version(version)
    commit = snapshot.tags.get(version)
    if commit is None:
        return Verdict(
            version,
            reason=f"{version} is not a version.",
            action=(
                "Enter an existing version. "
                "Versions are created by merging the release PR."
            ),
        )
    facts = snapshot.commits[commit]
    short = _short(commit)
    if not facts.on_main:
        return Verdict(
            version,
            reason=f"{version} is at {short}, which is not on main.",
            action="Do not promote it. Merge the release PR on main to cut a new version.",
        )
    if facts.checks == "failure":
        failed = ", ".join(facts.failed)
        detail = f"failed ({failed})" if failed else "failed"
        return Verdict(
            version,
            reason=f"the checks on {version} ({short}) {detail}.",
            action=(
                "If the failure is not real, re-run that commit's pipeline run. "
                "Otherwise fix main and release a new version."
            ),
        )
    if facts.checks != "success":
        return Verdict(
            version,
            reason=f"the checks on {version} ({short}) are still running.",
            action="Wait for them to finish, then run Promote again.",
        )
    if snapshot.staging_sha != commit:
        shown = _short(snapshot.staging_sha) if snapshot.staging_sha else "nothing"
        rerun = (
            f"re-run the pipeline run of commit {short} so staging shows it, "
            "check it, then run Promote again."
        )
        if snapshot.staging_paused:
            rerun = (
                f"Resume automatic staging deployment (unset {PAUSE_VARIABLE}), "
                + rerun
            )
        else:
            rerun = rerun[0].upper() + rerun[1:]
        return Verdict(
            version,
            reason=f"staging is showing {shown}, not {version} ({short}).",
            action=rerun,
        )
    return Verdict(version, commit=commit)


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


def _read_checks(fact: str, sha: str) -> tuple[str, tuple[str, ...]]:
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
        return "failure", failed
    if not runs or any(run["status"] != "completed" for run in runs):
        return "pending", ()
    return "success", ()


def _read_main() -> MainState:
    sha = _gh_json("main commit", "repos/{owner}/{repo}/commits/main")["sha"]
    checks, failed = _read_checks("main commit checks", sha)
    return MainState(sha, checks, failed)


def _read_commit_facts(sha: str) -> CommitFacts:
    fact = "version commit"
    # main is ahead of (or is) a commit that is on main.
    compare = _gh_json(
        fact, f"repos/{{owner}}/{{repo}}/compare/{sha}...main?per_page=1"
    )
    checks, failed = _read_checks("version commit checks", sha)
    return CommitFacts(compare["status"] in {"ahead", "identical"}, checks, failed)


def _read_staging_gap_docs_only(staging_sha: str | None, main_sha: str) -> bool:
    """Whether every commit between staging and main changed only Markdown.

    The same rule as scripts/docs_only_push.sh, which decides the push that
    skips the staging deployment. It is read from the API here because a local
    clone may not hold either commit. Anything unclear answers False.
    """
    if staging_sha is None or staging_sha == main_sha:
        return False
    fact = "staging gap"
    compare = _gh_json(
        fact, f"repos/{{owner}}/{{repo}}/compare/{staging_sha}...{main_sha}"
    )
    files = compare.get("files", [])
    if compare["status"] != "ahead" or not files or len(files) >= 300:
        return False
    return all(f["filename"].endswith(".md") for f in files)


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


def _is_truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes"}


def _read_paused() -> bool:
    fact = f"pause variable {PAUSE_VARIABLE}"
    # A workflow cannot read repository variables through the API with its own
    # token, so it passes the variable in through the environment instead.
    if PAUSE_VARIABLE in os.environ:
        return _is_truthy(os.environ[PAUSE_VARIABLE])
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
    return _is_truthy(json.loads(result.stdout).get("value", ""))


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


def published_release_tags(listing: list[dict]) -> frozenset[str]:
    """Tags of published Releases. A draft is a tag that is not yet a Release."""
    return frozenset(
        r["tag_name"]
        for r in listing
        if not r["draft"] and VERSION_TAG.fullmatch(r["tag_name"])
    )


def _read_releases() -> frozenset[str]:
    return published_release_tags(
        _gh_json("published releases", "repos/{owner}/{repo}/releases?per_page=100")
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
    main = _read_main()
    staging_sha = _read_staging_sha()
    return Snapshot(
        main=main,
        staging_sha=staging_sha,
        staging_paused=_read_paused(),
        tags=_read_tags(),
        releases=_read_releases(),
        release_pr=_read_release_pr(),
        staging_gap_docs_only=_read_staging_gap_docs_only(staging_sha, main.sha),
    )


def read_guard_snapshot(version: str) -> Snapshot:
    """The facts the promote guard needs. Reads nothing about the release PR."""
    main = _read_main()
    tags = _read_tags()
    commit = tags.get(normalize_version(version))
    return Snapshot(
        main=main,
        staging_sha=_read_staging_sha(),
        staging_paused=_read_paused(),
        tags=tags,
        releases=_read_releases(),
        release_pr=None,
        commits={commit: _read_commit_facts(commit)} if commit else {},
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


def run_guard(
    reader: Callable[[str], Snapshot], version: str, out: TextIO, err: TextIO
) -> int:
    """Exit 0 when the version may be promoted, 1 when refused, 2 when unknown."""
    try:
        snapshot = reader(version)
    except FactUnreadable as error:
        err.write(
            f"promote cannot be decided: could not read {error.fact} ({error.detail})\n"
        )
        return 2
    verdict = promote_guard(snapshot, version)
    out.write(verdict.render())
    return 0 if verdict.accepted else 1


def main(argv: list[str]) -> int:
    if argv == ["status"]:
        return run_status(read_snapshot, sys.stdout, sys.stderr)
    if len(argv) == 2 and argv[0] == "guard":
        return run_guard(read_guard_snapshot, argv[1], sys.stdout, sys.stderr)
    sys.stderr.write("usage: delivery_state.py status | guard <version>\n")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
