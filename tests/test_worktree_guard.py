"""scripts/worktree_guard.py blocks risky git commands in the shared main checkout.

Each test builds a synthetic repository with a linked worktree and feeds the
hook the same JSON Claude Code sends on stdin.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "worktree_guard.py"
SETTINGS = Path(__file__).resolve().parents[1] / ".claude" / "settings.json"


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def repos(tmp_path: Path) -> tuple[Path, Path]:
    main = tmp_path / "main"
    main.mkdir()
    git(main, "init", "-q", "-b", "main")
    (main / "a.txt").write_text("a\n")
    git(main, "add", "a.txt")
    git(
        main,
        "-c",
        "user.name=t",
        "-c",
        "user.email=t@example.com",
        "commit",
        "-qm",
        "c",
    )
    git(main, "branch", "feature")
    linked = tmp_path / "linked"
    git(main, "worktree", "add", "-q", "-b", "work", str(linked))
    return main, linked


def run(
    cwd: Path, command: str | None, *, raw: str | None = None
) -> subprocess.CompletedProcess:
    payload = raw
    if payload is None:
        payload = json.dumps(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "Bash",
                "tool_input": {"command": command},
                "cwd": str(cwd),
            }
        )
    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        input=payload,
        capture_output=True,
        text=True,
        check=False,
    )


BLOCKED = [
    "git checkout -b topic",
    "git checkout -B topic",
    "git checkout feature",
    "git checkout -",
    "git switch -c topic",
    "git switch -C topic",
    "git switch --create topic",
    "git switch feature",
    "git stash",
    "git stash pop",
    "git stash list",
    "git add -A",
    "git add --all",
    "git add .",
    "git add -Av",
    "git commit -a -m wip",
    "git commit -am wip",
    "git commit --all -m wip",
    "git reset --hard",
    "git reset --hard HEAD~1",
    "git status && git stash",
    "git status; git add -A",
    "git log | head; git checkout -b topic",
    "echo hi\ngit stash",
    "FOO=1 git stash",
    "git -c core.pager=cat stash",
    "git --no-pager stash",
]

ALLOWED = [
    "git status",
    "git checkout main",
    "git switch main",
    "git checkout -- a.txt",
    "git checkout a.txt",
    "git checkout feature -- a.txt",
    "git add a.txt",
    "git add src/app.py tests/test_app.py",
    "git commit -m 'add -a flag'",
    "git commit -m wip",
    "git commit -F msg.txt",
    "git reset --soft HEAD~1",
    "git reset a.txt",
    "git worktree add ../x -b x",
    "git pull --ff-only",
    "echo 'git stash'",
    "ls -la",
]


@pytest.mark.parametrize("command", BLOCKED)
def test_blocks_risky_commands_in_main_checkout(repos, command):
    main, _ = repos
    result = run(main, command)
    assert result.returncode == 2, result.stderr
    assert "EnterWorktree" in result.stderr
    assert "git add <path>" in result.stderr


@pytest.mark.parametrize("command", ALLOWED)
def test_allows_safe_commands_in_main_checkout(repos, command):
    main, _ = repos
    result = run(main, command)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("command", BLOCKED)
def test_allows_everything_in_linked_worktree(repos, command):
    _, linked = repos
    assert run(linked, command).returncode == 0


def test_git_dash_c_targets_main_checkout_from_linked_worktree(repos):
    main, linked = repos
    assert run(linked, f"git -C {main} stash").returncode == 2
    assert run(main, f"git -C {linked} stash").returncode == 0


def test_relative_git_dash_c_resolves_against_cwd(repos):
    main, linked = repos
    assert run(main.parent, "git -C main add -A").returncode == 2
    assert run(main.parent, "git -C linked add -A").returncode == 0


def test_cd_changes_the_evaluated_checkout(repos):
    main, linked = repos
    assert run(linked, f"cd {main} && git checkout -b topic").returncode == 2
    assert run(main, f"cd {linked} && git checkout -b topic").returncode == 0


def test_outside_any_repository_is_allowed(tmp_path):
    assert run(tmp_path, "git stash").returncode == 0


@pytest.mark.parametrize(
    "raw",
    ["", "not json", "{}", '{"tool_input": {}}', '{"tool_input": {"command": 5}}'],
)
def test_fails_open_on_bad_input(raw, tmp_path):
    assert run(tmp_path, None, raw=raw).returncode == 0


def test_fails_open_on_unbalanced_quotes(repos):
    main, _ = repos
    assert run(main, "git stash 'unterminated").returncode == 0


def test_settings_register_the_hook_for_bash():
    settings = json.loads(SETTINGS.read_text())
    (entry,) = settings["hooks"]["PreToolUse"]
    assert entry["matcher"] == "Bash"
    (hook,) = entry["hooks"]
    assert hook["type"] == "command"
    assert "$CLAUDE_PROJECT_DIR/scripts/worktree_guard.py" in hook["command"]


def run_settings_command(project_dir: Path, cwd: Path) -> int:
    (entry,) = json.loads(SETTINGS.read_text())["hooks"]["PreToolUse"]
    payload = json.dumps({"tool_input": {"command": "git stash"}, "cwd": str(cwd)})
    return subprocess.run(
        ["sh", "-c", entry["hooks"][0]["command"]],
        input=payload,
        env={
            "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
            "CLAUDE_PROJECT_DIR": str(project_dir),
        },
        capture_output=True,
        text=True,
        check=False,
    ).returncode


def test_settings_command_runs_the_guard(repos):
    main, _ = repos
    assert run_settings_command(SETTINGS.parents[1], main) == 2


def test_settings_command_allows_when_the_script_is_missing(repos, tmp_path):
    main, _ = repos
    assert run_settings_command(tmp_path / "missing", main) == 0
