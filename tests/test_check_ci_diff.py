"""scripts/check_ci_diff.sh rejects agent co-author trailers on new commits.

Agents never sign commits as co-authors. The check covers only the commits a
push or pull request adds, so older history on the default branch stays green.
"""

import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_ci_diff.sh"
PATH = "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin"


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def commit(repo: Path, message: str) -> str:
    path = repo / "notes.txt"
    path.write_text(path.read_text() + "x\n" if path.exists() else "x\n")
    git(repo, "add", "notes.txt")
    git(
        repo,
        "-c",
        "user.name=t",
        "-c",
        "user.email=t@example.com",
        "commit",
        "-qm",
        message,
    )
    return git(repo, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    git(tmp_path, "init", "-q", "-b", "main")
    return tmp_path


def run_push(repo: Path, before: str, after: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(SCRIPT)],
        cwd=repo,
        env={
            "PATH": PATH,
            "GITHUB_EVENT_NAME": "push",
            "PUSH_BEFORE_SHA": before,
            "PUSH_AFTER_SHA": after,
        },
        capture_output=True,
        text=True,
        check=False,
    )


def run_pull_request(repo: Path, base: str, head: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(SCRIPT)],
        cwd=repo,
        env={
            "PATH": PATH,
            "GITHUB_EVENT_NAME": "pull_request",
            "PR_BASE_SHA": base,
            "PR_HEAD_SHA": head,
        },
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize(
    "trailer",
    [
        "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>",
        "co-authored-by: claude <someone@example.com>",
        "CO-AUTHORED-BY: Bot <NOREPLY@ANTHROPIC.COM>",
    ],
)
def test_push_with_agent_trailer_fails(repo, trailer):
    before = commit(repo, "docs: base")
    after = commit(repo, f"docs: change\n\nBody.\n\n{trailer}")
    result = run_push(repo, before, after)
    assert result.returncode == 1
    assert after in result.stderr
    assert "Co-authored-by" in result.stderr


def test_push_with_human_trailer_passes(repo):
    before = commit(repo, "docs: base")
    after = commit(repo, "docs: change\n\nCo-authored-by: Pat <pat@example.com>")
    result = run_push(repo, before, after)
    assert result.returncode == 0, result.stderr


def test_older_agent_trailer_outside_range_passes(repo):
    commit(repo, "docs: old\n\nCo-Authored-By: Claude <noreply@anthropic.com>")
    before = commit(repo, "docs: base")
    after = commit(repo, "docs: clean change")
    result = run_push(repo, before, after)
    assert result.returncode == 0, result.stderr


def test_pull_request_checks_only_head_side_commits(repo):
    base_root = commit(repo, "docs: base")
    git(repo, "checkout", "-qb", "topic")
    head = commit(repo, "docs: topic\n\nCo-Authored-By: Claude <noreply@anthropic.com>")
    git(repo, "checkout", "-q", "main")
    main_head = commit(
        repo, "docs: main moves\n\nCo-Authored-By: Claude <noreply@anthropic.com>"
    )
    assert run_pull_request(repo, main_head, head).returncode == 1

    git(repo, "checkout", "-q", "topic")
    git(repo, "reset", "-q", "--hard", base_root)
    clean_head = commit(repo, "docs: topic clean")
    result = run_pull_request(repo, main_head, clean_head)
    assert result.returncode == 0, result.stderr
