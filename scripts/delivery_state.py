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
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Callable, Iterator, TextIO

# Repository variable that pauses automatic staging deployment when its value
# is "true" (see pauses_staging). Absent means not paused.
PAUSE_VARIABLE = "STAGING_DEPLOY_PAUSED"

VERSION_TAG = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")

# The names of the CI gate jobs (the `name:` of each job in ci.yml). A commit's
# checks are exactly these and nothing else.
GATES = (
    "Formatting and lint",
    "Type check",
    "Frontend tests",
    "Build",
    "Migration check",
    "Backend and browser tests",
    "Diff hygiene",
)


def is_docs_only(paths: list[str]) -> bool:
    """Whether a change touching exactly these paths is documentation only.

    The one definition of the rule. Pass both sides of a rename. An empty
    change is not documentation only.
    """
    return bool(paths) and all(path.endswith(".md") for path in paths)


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
    # Commit of the latest successful production deployment. Production is the
    # version at this commit, which is not the newest Release after a rollback.
    production_sha: str | None = None
    # Facts about the commits of the versions the guard was asked about.
    commits: dict[str, CommitFacts] = field(default_factory=dict)
    # What the pause variable holds when that is neither true nor false. It
    # does not pause, and whoever set it most likely believes it does.
    ignored_pause_value: str | None = None

    @classmethod
    def from_dict(cls, data: dict) -> Snapshot:
        pr = data["release_pr"]
        return cls(
            staging_gap_docs_only=data.get("staging_gap_docs_only", False),
            production_sha=data.get("production_sha"),
            ignored_pause_value=data.get("ignored_pause_value"),
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


def ignored_pause_text(value: str) -> str:
    """What to tell the captain about a pause value that does not pause.

    The value is shown as a JSON string so a stray space or line break in it
    can be seen.
    """
    return (
        f'{PAUSE_VARIABLE} is {json.dumps(value)}: only "true" pauses, '
        "so staging still deploys"
    )


def build_report(snapshot: Snapshot) -> Report:
    main = snapshot.main
    releases = sorted(snapshot.releases, key=_version_key)
    # What production runs is what was last deployed to it. Without a usable
    # deployment record, fall back to the newest published Release.
    deployed = sorted(
        (
            tag
            for tag in releases
            if snapshot.production_sha
            and snapshot.tags.get(tag) == snapshot.production_sha
        ),
        key=_version_key,
    )
    if deployed:
        production = deployed[-1]
    else:
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
    if snapshot.ignored_pause_value is not None:
        lines.append(
            _row("not paused", ignored_pause_text(snapshot.ignored_pause_value))
        )
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
    if snapshot.ignored_pause_value is not None:
        return (
            f"Set {PAUSE_VARIABLE} to true to pause automatic staging deployment, "
            "or to false to leave it running."
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


# What indexing into a response raises when it is not in the expected shape.
_SHAPE_ERRORS = (KeyError, IndexError, TypeError, ValueError, AttributeError)


@contextmanager
def _reading(fact: str) -> Iterator[None]:
    """Name the fact when a response is not in the shape its reader expects.

    GitHub answering with an error object or a renamed field would otherwise
    surface as a traceback, and a traceback exits 1, which reads as "refused".
    Use as a decorator when a reader has one fact, as a block otherwise.
    """
    try:
        yield
    except _SHAPE_ERRORS as error:
        raise FactUnreadable(fact, f"unexpected response: {error!r}") from error


def _gh(fact: str, args: list[str]):
    out = _run(fact, ["gh", "api", *args])
    try:
        return json.loads(out)
    except json.JSONDecodeError as error:
        raise FactUnreadable(fact, f"unparseable response: {error}") from error


def _gh_json(fact: str, endpoint: str):
    return _gh(fact, [endpoint])


def _gh_pages(fact: str, endpoint: str) -> list:
    """Every page of a listing, as one JSON value per page."""
    pages = _gh(fact, ["--paginate", "--slurp", endpoint])
    if not isinstance(pages, list):
        raise FactUnreadable(fact, "unexpected response: not a list of pages")
    return pages


def _read_checks(fact: str, sha: str) -> tuple[str, tuple[str, ...]]:
    with _reading(fact):
        pages = _gh_pages(
            fact, f"repos/{{owner}}/{{repo}}/commits/{sha}/check-runs?per_page=100"
        )
        runs = [run for page in pages for run in page["check_runs"]]
        # Only the gates count. Other runs on the same commit (the Promote guard
        # itself, a staging deployment, Release Please, the Summary) say nothing
        # about whether the commit is good.
        latest: dict[str, dict] = {}
        for run in runs:
            name = run["name"]
            if name in GATES and (name not in latest or run["id"] > latest[name]["id"]):
                latest[name] = run
        # Green means every gate succeeded. A gate that finished any other way
        # (skipped, neutral, cancelled, ...) did not vouch for the commit, and
        # is named with how it ended because no job of it is red.
        ended = {
            name: latest[name]["conclusion"]
            for name in GATES
            if name in latest and latest[name]["status"] == "completed"
        }
        failed = tuple(
            name if conclusion == "failure" else f"{name}: {conclusion}"
            for name, conclusion in ended.items()
            if conclusion != "success"
        )
        if failed:
            return "failure", failed
        if len(latest) < len(GATES) or any(
            run["status"] != "completed" for run in latest.values()
        ):
            return "pending", ()
        return "success", ()


@_reading("main commit")
def _read_main() -> MainState:
    sha = _gh_json("main commit", "repos/{owner}/{repo}/commits/main")["sha"]
    checks, failed = _read_checks("main commit checks", sha)
    return MainState(sha, checks, failed)


@_reading("version commit")
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

    The same rule (is_docs_only) as the push that skips the staging deployment.
    It is read from the API here because a local clone may not hold either
    commit. Anything unclear answers False.
    """
    if staging_sha is None or staging_sha == main_sha:
        return False
    fact = "staging gap"
    compare = _gh_json(
        fact, f"repos/{{owner}}/{{repo}}/compare/{staging_sha}...{main_sha}"
    )
    try:
        files = compare.get("files", [])
        if compare["status"] != "ahead" or len(files) >= 300:
            return False
        paths = [
            path
            for f in files
            for path in (f["filename"], f.get("previous_filename"))
            if path
        ]
    except _SHAPE_ERRORS:
        return False
    return is_docs_only(paths)


def docs_only_push(before: str, after: str) -> bool:
    """Whether a push from `before` to `after` changed only documentation.

    An unknown range (new branch, forced push, missing commit) answers False so
    that staging deploys rather than silently skipping unreviewed work.
    """
    if not re.fullmatch(r"[0-9a-fA-F]{40,64}", before) or set(before) == {"0"}:
        return False
    for sha in (before, after):
        if subprocess.run(
            ["git", "cat-file", "-e", f"{sha}^{{commit}}"], capture_output=True
        ).returncode:
            return False
    diff = subprocess.run(
        ["git", "diff", "--no-renames", "--name-only", before, after],
        capture_output=True,
        text=True,
    )
    return diff.returncode == 0 and is_docs_only(diff.stdout.splitlines())


# What promote.yml calls its deploy job and the step that puts the Worker in
# production. tests/test_delivery_state.py fails if the workflow stops matching.
DEPLOY_JOB_NAME = re.compile(r"Deploy (?P<tag>\S+) to production")
DEPLOY_STEP_NAME = "Deploy Worker"


def _latest_deployment_sha(fact: str, environment: str) -> str | None:
    """The commit of the newest successful deployment to an environment."""
    with _reading(fact):
        deployments = _gh_json(
            fact,
            f"repos/{{owner}}/{{repo}}/deployments?environment={environment}&per_page=10",
        )
        # Newest first, so the first success is the answer.
        for deployment in deployments:
            statuses = _gh_json(
                fact,
                f"repos/{{owner}}/{{repo}}/deployments/{deployment['id']}/statuses",
            )
            if statuses and statuses[0]["state"] == "success":
                return deployment["sha"]
        return None


def _read_staging_sha() -> str | None:
    return _latest_deployment_sha("staging deployment", "staging")


@_reading("production version")
def _read_production_sha(tags: dict[str, str]) -> str | None:
    """The commit in production.

    The deployment record GitHub keeps for the prod environment names the commit
    Promote was dispatched from, which is the head of main, not the commit it
    deployed. After a rollback that is the wrong version. So production is the
    version named by the Promote run whose Deploy Worker step finished last. A
    run counts once that step succeeded, even if a later step failed, and runs
    are ordered by when the step finished, not by when the run was created, so
    re-running an older run is judged by when it deployed.

    The deployment record is used only when no Promote has deployed at all. A
    deployment whose version cannot be read is an error, never a guess.
    """
    fact = "production version"
    runs = _gh_json(
        fact,
        "repos/{owner}/{repo}/actions/workflows/promote.yml/runs?per_page=10",
    )["workflow_runs"]
    deployed: list[tuple[str, str]] = []  # (finished, job name)
    for run in runs:
        jobs = _gh_json(
            fact, f"repos/{{owner}}/{{repo}}/actions/runs/{run['id']}/jobs"
        )["jobs"]
        for job in jobs:
            for step in job.get("steps", []):
                if (
                    step["name"] == DEPLOY_STEP_NAME
                    and step.get("conclusion") == "success"
                ):
                    deployed.append((step.get("completed_at") or "", job["name"]))
    if deployed:
        _, name = max(deployed)
        match = DEPLOY_JOB_NAME.fullmatch(name)
        if not match:
            raise FactUnreadable(
                fact, f"cannot read the version from the deploy job name {name!r}"
            )
        if match["tag"] not in tags:
            raise FactUnreadable(fact, f"{match['tag']} is not a known tag")
        return tags[match["tag"]]
    return _latest_deployment_sha("production deployment", "prod")


def pauses_staging(value: str) -> bool:
    """Whether this value of the pause variable pauses staging deployment.

    The rule ci.yml applies with `vars.STAGING_DEPLOY_PAUSED != 'true'`, where
    Actions compares strings ignoring letter case and nothing else. Saying
    "paused" for any other value would report a pause while staging deploys.
    tests/test_delivery_state.py fails if the workflow stops matching.
    """
    return value.lower() == "true"


def ignored_pause_value(value: str) -> str | None:
    """The value, when it is set but is neither true nor false.

    Such a value does not pause, and it was most likely typed to pause: "yes",
    "1", "true" with a stray space. An empty value is an absent variable, which
    is how a workflow hands over a variable that does not exist.
    """
    return value if value and value.lower() not in {"true", "false"} else None


def _read_pause_value() -> str:
    """What the pause variable holds. Empty when it does not exist."""
    fact = f"pause variable {PAUSE_VARIABLE}"
    # A workflow cannot read repository variables through the API with its own
    # token, so it passes the variable in through the environment instead.
    if PAUSE_VARIABLE in os.environ:
        return os.environ[PAUSE_VARIABLE]
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
            return ""
        raise FactUnreadable(fact, result.stderr.strip() or "gh failed")
    with _reading(fact):
        value = json.loads(result.stdout).get("value", "")
        if not isinstance(value, str):
            raise TypeError(f"value is {value!r}, not a string")
        return value


def _read_paused() -> bool:
    return pauses_staging(_read_pause_value())


@_reading("version tags")
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


@_reading("published releases")
def _read_releases() -> frozenset[str]:
    pages = _gh_pages(
        "published releases", "repos/{owner}/{repo}/releases?per_page=100"
    )
    return published_release_tags([r for page in pages for r in page])


@_reading("release PR")
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
    tags = _read_tags()
    pause_value = _read_pause_value()
    return Snapshot(
        main=main,
        staging_sha=staging_sha,
        production_sha=_read_production_sha(tags),
        staging_paused=pauses_staging(pause_value),
        ignored_pause_value=ignored_pause_value(pause_value),
        tags=tags,
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


def staging_deploy_decision(
    sha: str, run_attempt: int, main_head: str
) -> tuple[bool, str]:
    """Whether a push run should deploy its commit to staging.

    Each push to main runs its own Deploy staging after its own gates, so two
    pushes close together can finish their gates out of order and the older
    commit would deploy over the newer one. A first-attempt run therefore
    deploys only while its commit is still the head of main. A re-run is the
    captain returning staging to a version on purpose, so it always deploys the
    commit it ran for.
    """
    if run_attempt > 1:
        return True, f"re-run: deploying {sha[:7]} as requested"
    if sha == main_head:
        return True, f"{sha[:7]} is the head of main"
    return (
        False,
        f"superseded: main is already at {main_head[:7]}, "
        f"so {sha[:7]} does not deploy over it",
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


def run_staging_order(out: TextIO, err: TextIO) -> int:
    """Print deploy=true or deploy=false for the job output, then the reason."""
    sha = os.environ.get("AFTER", "")
    attempt = int(os.environ.get("RUN_ATTEMPT", "1") or "1")
    try:
        with _reading("head of main"):
            head = _gh_json("head of main", "repos/{owner}/{repo}/commits/main")["sha"]
    except FactUnreadable as error:
        err.write(
            "staging order cannot be decided: "
            f"could not read {error.fact} ({error.detail})\n"
        )
        return 1
    deploy, reason = staging_deploy_decision(sha, attempt, head)
    out.write(f"deploy={'true' if deploy else 'false'}\n{reason}\n")
    return 0


def run_pause_warning(out: TextIO) -> int:
    """Say on the run page that the pause variable holds a value that does not pause.

    Printed as a workflow command, which GitHub shows as a warning on the page
    of the run, and added to the run summary. It reports and decides nothing:
    the Deploy staging condition in ci.yml decides, and this always exits 0.
    """
    value = ignored_pause_value(os.environ.get(PAUSE_VARIABLE, ""))
    if value is None:
        return 0
    title = "Staging deployment is not paused"
    text = ignored_pause_text(value)
    # "%" starts an escape in a workflow command. The value itself cannot break
    # the line: it is shown as a JSON string.
    out.write(f"::warning title={title}::{text.replace('%', '%25')}\n")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as file:
            file.write(f"### {title}\n\n{text}\n")
    return 0


def main(argv: list[str]) -> int:
    if argv == ["status"]:
        return run_status(read_snapshot, sys.stdout, sys.stderr)
    if len(argv) == 2 and argv[0] == "guard":
        return run_guard(read_guard_snapshot, argv[1], sys.stdout, sys.stderr)
    if argv == ["staging-order"]:
        return run_staging_order(sys.stdout, sys.stderr)
    if argv == ["pause-warning"]:
        return run_pause_warning(sys.stdout)
    if argv == ["docs-only-push"]:
        before, after = os.environ.get("BEFORE", ""), os.environ.get("AFTER", "")
        sys.stdout.write("true\n" if docs_only_push(before, after) else "false\n")
        return 0
    sys.stderr.write(
        "usage: delivery_state.py status | guard <version> | docs-only-push"
        " | staging-order | pause-warning\n"
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
