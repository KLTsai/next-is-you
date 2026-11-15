"""scripts/docs_only_push.sh decides whether a push changed only documentation."""

import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "docs_only_push.sh"
ZERO = "0" * 40


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def commit(repo: Path, files: dict[str, str]) -> str:
    for name, text in files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    git(repo, "add", "-A")
    git(
        repo,
        "-c",
        "user.name=t",
        "-c",
        "user.email=t@example.com",
        "commit",
        "-q",
        "-m",
        "c",
    )
    return git(repo, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    git(tmp_path, "init", "-q")
    return tmp_path


def run(repo: Path, before: str, after: str) -> str:
    result = subprocess.run(
        ["bash", str(SCRIPT)],
        cwd=repo,
        env={
            "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
            "BEFORE": before,
            "AFTER": after,
        },
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def test_markdown_files_only_is_docs_only(repo: Path) -> None:
    base = commit(repo, {"src/a.py": "1"})
    head = commit(repo, {"docs/CI-CD.md": "x", "GLOSSARY.md": "y"})
    assert run(repo, base, head) == "true"


def test_any_product_file_is_not_docs_only(repo: Path) -> None:
    base = commit(repo, {"src/a.py": "1"})
    head = commit(repo, {"docs/CI-CD.md": "x", "src/a.py": "2"})
    assert run(repo, base, head) == "false"


def test_workflow_and_migration_changes_are_not_docs_only(repo: Path) -> None:
    base = commit(repo, {"src/a.py": "1"})
    assert run(repo, base, commit(repo, {".github/workflows/ci.yml": "x"})) == "false"
    base = git(repo, "rev-parse", "HEAD")
    assert run(repo, base, commit(repo, {"migrations/0002.sql": "x"})) == "false"


def test_non_markdown_file_under_docs_is_not_docs_only(repo: Path) -> None:
    base = commit(repo, {"src/a.py": "1"})
    head = commit(repo, {"docs/diagram.py": "x"})
    assert run(repo, base, head) == "false"


def test_rename_from_a_product_file_to_markdown_is_not_docs_only(repo: Path) -> None:
    base = commit(repo, {"app.py": "print('a body long enough to be a rename')\n" * 5})
    git(repo, "mv", "app.py", "app.md")
    head = commit(repo, {})
    assert run(repo, base, head) == "false"


def test_unknown_range_is_not_docs_only(repo: Path) -> None:
    head = commit(repo, {"README.md": "x"})
    assert run(repo, ZERO, head) == "false"
    assert run(repo, "1" * 40, head) == "false"
