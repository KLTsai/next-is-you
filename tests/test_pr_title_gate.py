"""scripts/pr_title_gate.py rejects release-proposing titles on non-product changes."""

import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "pr_title_gate.py"
sys.path.insert(0, str(SCRIPT.parent))

import pr_title_gate  # noqa: E402

CI_ONLY = [".github/workflows/pr-title.yml", "scripts/pr_title_gate.py"]


@pytest.mark.parametrize(
    "title",
    ["feat(ci): add gate", "fix: typo", "perf: faster", "feat!: x", "fix(docs)!: y"],
)
def test_visible_type_on_non_product_paths_is_rejected(title):
    assert pr_title_gate.check(title, CI_ONLY) is not None


def test_fix_bang_on_docs_only_paths_is_rejected():
    message = pr_title_gate.check("fix!: reword", ["docs/CI-CD.md", "README.md"])
    assert message is not None
    assert "docs/CI-CD.md" in message
    assert "ci:" in message and "chore:" in message


@pytest.mark.parametrize("path", ["src/worker.py", "frontend/app.ts", "package.json"])
def test_feat_with_any_product_path_is_allowed(path):
    assert pr_title_gate.check("feat: thing", [*CI_ONLY, path]) is None


@pytest.mark.parametrize(
    "title",
    [
        "ci: add gate",
        "chore(main): release 0.4.0",
        "docs: x",
        "test: y",
        "Update thing",
        "",
    ],
)
def test_other_titles_are_allowed(title):
    assert pr_title_gate.check(title, CI_ONLY) is None


def test_markdown_anywhere_counts_as_non_product():
    assert pr_title_gate.check("feat: x", ["frontend/README.md"]) is not None


def test_directory_prefix_is_not_a_substring_match():
    assert pr_title_gate.check("feat: x", ["src/scripts/a.py"]) is None


def test_no_changed_paths_is_allowed():
    assert pr_title_gate.check("feat: x", []) is None


def run(title: str, paths: list[str]):
    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        input="\n".join(paths) + "\n",
        env={"TITLE": title},
        capture_output=True,
        text=True,
    )


def test_cli_exit_codes():
    bad = run("feat(ci): x", CI_ONLY)
    assert bad.returncode == 1 and "scripts/pr_title_gate.py" in bad.stderr
    assert run("ci: x", CI_ONLY).returncode == 0
