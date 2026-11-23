"""scripts/check_ci_diff.sh rejects agent co-author trailers and em dashes.

Agents never sign commits as co-authors, and nobody writes the em dash
(U+2014). Each check covers only the commits or lines a push or pull request
adds, so older history on the default branch stays green.
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


# Built from its code point so this file never adds the character it forbids.
EM_DASH = chr(0x2014)


def commit_files(repo: Path, files: dict[str, str]) -> str:
    for name, content in files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        git(repo, "add", name)
    git(
        repo,
        "-c",
        "user.name=t",
        "-c",
        "user.email=t@example.com",
        "commit",
        "-qm",
        "docs: edit",
    )
    return git(repo, "rev-parse", "HEAD")


def test_added_em_dash_fails_with_its_location(repo):
    before = commit_files(repo, {"docs/guide.md": "one\ntwo\n"})
    after = commit_files(repo, {"docs/guide.md": f"one\ntwo {EM_DASH} three\n"})
    result = run_push(repo, before, after)
    assert result.returncode == 1
    assert f"docs/guide.md:2: two {EM_DASH} three" in result.stderr
    assert "U+2014" in result.stderr
    assert "1 added line(s)" in result.stderr


def test_em_dash_already_on_the_branch_passes(repo):
    before = commit_files(repo, {"notes.md": f"old {EM_DASH} line\n"})
    after = commit_files(repo, {"notes.md": f"old {EM_DASH} line\nnew - line\n"})
    result = run_push(repo, before, after)
    assert result.returncode == 0, result.stderr


def test_removing_an_em_dash_passes(repo):
    before = commit_files(repo, {"notes.md": f"old {EM_DASH} line\n"})
    after = commit_files(repo, {"notes.md": "old - line\n"})
    result = run_push(repo, before, after)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "generated",
    [
        "CHANGELOG.md",
        "packages/app/CHANGELOG.md",
        "package-lock.json",
        "uv.lock",
        ".github/.release-please-manifest.json",
    ],
)
def test_em_dash_in_generated_files_passes(repo, generated):
    before = commit_files(repo, {"README.md": "base\n"})
    after = commit_files(repo, {generated: f"generated {EM_DASH} text\n"})
    result = run_push(repo, before, after)
    assert result.returncode == 0, result.stderr


def test_pull_request_checks_only_head_side_lines(repo):
    base_root = commit_files(repo, {"README.md": "base\n"})
    git(repo, "checkout", "-qb", "topic")
    clean_head = commit_files(repo, {"docs/a.md": "topic - text\n"})
    git(repo, "checkout", "-q", "main")
    main_head = commit_files(repo, {"docs/b.md": f"main {EM_DASH} moves\n"})
    result = run_pull_request(repo, main_head, clean_head)
    assert result.returncode == 0, result.stderr

    git(repo, "checkout", "-q", "topic")
    git(repo, "reset", "-q", "--hard", base_root)
    dirty_head = commit_files(repo, {"docs/a.md": f"topic {EM_DASH} text\n"})
    result = run_pull_request(repo, main_head, dirty_head)
    assert result.returncode == 1
    assert "docs/a.md:1:" in result.stderr
    assert "docs/b.md" not in result.stderr
