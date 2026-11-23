"""Claude Code PreToolUse hook: keep the shared main checkout safe.

Several agent sessions run at once on one machine. In the primary worktree
(the main checkout), switching branches, stashing, sweeping adds, and hard
resets reach other sessions' uncommitted work. This hook blocks those git
commands there and lets everything else through, including every command in a
linked worktree.

Input is the hook JSON on stdin (``tool_input.command`` and ``cwd``). Exit 2
blocks the command and shows stderr to the agent. Any parse or git error
exits 0, so the guard never blocks work it cannot understand.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys

MAIN_BRANCH = "main"
SEPARATORS = {"&&", "||", ";", "|", "&", "(", ")", "|&", ";;"}

# git global options that take the next token as their value.
GIT_VALUE_OPTIONS = {"-c", "--exec-path", "--namespace", "--config-env"}
# git global options that point git somewhere this hook cannot reason about.
GIT_LOCATION_OPTIONS = {"--git-dir", "--work-tree"}

# git commit short options that take a value.
COMMIT_SHORT_VALUE = set("mFCcSt")
COMMIT_LONG_VALUE = {
    "--message",
    "--file",
    "--reuse-message",
    "--reedit-message",
    "--fixup",
    "--squash",
    "--author",
    "--date",
    "--template",
    "--cleanup",
    "--trailer",
    "--pathspec-from-file",
}


def is_primary_worktree(path: str) -> bool:
    if not os.path.isdir(path):
        return False
    result = subprocess.run(
        [
            "git",
            "-C",
            path,
            "rev-parse",
            "--path-format=absolute",
            "--git-dir",
            "--git-common-dir",
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0:
        return False
    lines = result.stdout.splitlines()
    if len(lines) != 2:
        return False
    git_dir, common_dir = (os.path.realpath(line) for line in lines)
    return git_dir == common_dir


def resolves_to_commit(path: str, name: str) -> bool:
    for ref in (f"{name}^{{commit}}", f"refs/remotes/origin/{name}^{{commit}}"):
        result = subprocess.run(
            ["git", "-C", path, "rev-parse", "--verify", "--quiet", ref],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return True
    return False


def split_segments(command: str) -> list[list[str]]:
    lexer = shlex.shlex(
        command.replace("\n", " ; "), posix=True, punctuation_chars=True
    )
    lexer.whitespace_split = True
    segments: list[list[str]] = [[]]
    for token in lexer:
        if token in SEPARATORS:
            segments.append([])
        else:
            segments[-1].append(token)
    return [segment for segment in segments if segment]


def strip_prefix(words: list[str]) -> list[str]:
    """Drop leading environment assignments and simple command wrappers."""
    index = 0
    while index < len(words):
        word = words[index]
        if (
            "=" in word
            and not word.startswith("-")
            and word.split("=", 1)[0].isidentifier()
        ):
            index += 1
        elif word in {"command", "exec", "time", "nohup"}:
            index += 1
        else:
            break
    return words[index:]


def checkout_reason(path: str, args: list[str]) -> str | None:
    targets: list[str] = []
    for arg in args:
        if arg == "--":
            return None  # Restores paths; the branch stays put.
        if arg in {"-b", "-B", "--orphan", "-d", "--detach"}:
            return "creating or leaving a branch with git checkout"
        if arg.startswith("-") and arg != "-":
            continue
        targets.append(arg)
    if not targets:
        return None
    target = targets[0]
    if target == MAIN_BRANCH:
        return None
    if target == "-" or resolves_to_commit(path, target):
        return f"switching the main checkout to '{target}'"
    return None


def switch_reason(args: list[str]) -> str | None:
    for arg in args:
        if arg in {
            "-c",
            "-C",
            "--create",
            "--force-create",
            "--orphan",
            "-d",
            "--detach",
        }:
            return "creating or leaving a branch with git switch"
        if arg.startswith(("--create=", "--force-create=", "--orphan=")):
            return "creating a branch with git switch"
    targets = [arg for arg in args if arg == "-" or not arg.startswith("-")]
    if targets and targets[0] != MAIN_BRANCH:
        return f"switching the main checkout to '{targets[0]}'"
    return None


def add_reason(args: list[str]) -> str | None:
    for arg in args:
        if arg == "--":
            continue
        if arg in {"--all", ".", "./", ":/"}:
            return f"staging everything with git add {arg}"
        if arg.startswith("-") and not arg.startswith("--") and "A" in arg[1:]:
            return "staging everything with git add -A"
    return None


def commit_reason(args: list[str]) -> str | None:
    skip = False
    for arg in args:
        if skip:
            skip = False
            continue
        if arg == "--":
            return None
        if arg == "--all":
            return "committing every tracked change with git commit --all"
        if arg.startswith("--"):
            if arg in COMMIT_LONG_VALUE:
                skip = True
            continue
        if arg.startswith("-") and len(arg) > 1:
            for position, char in enumerate(arg[1:], start=1):
                if char == "a":
                    return "committing every tracked change with git commit -a"
                if char in COMMIT_SHORT_VALUE:
                    skip = position == len(arg) - 1
                    break
    return None


def git_reason(path: str, subcommand: str, args: list[str]) -> str | None:
    if subcommand == "stash":
        return "git stash, whose stack every session shares"
    if subcommand == "checkout":
        return checkout_reason(path, args)
    if subcommand == "switch":
        return switch_reason(args)
    if subcommand == "add":
        return add_reason(args)
    if subcommand == "commit":
        return commit_reason(args)
    if subcommand == "reset" and "--hard" in args:
        return "git reset --hard"
    return None


def segment_reason(cwd: str, words: list[str]) -> str | None:
    words = strip_prefix(words)
    if not words or os.path.basename(words[0]) != "git":
        return None
    path = cwd
    index = 1
    while index < len(words):
        word = words[index]
        if word == "-C" and index + 1 < len(words):
            path = os.path.join(path, os.path.expanduser(words[index + 1]))
            index += 2
        elif word in GIT_VALUE_OPTIONS:
            index += 2
        elif (
            word in GIT_LOCATION_OPTIONS
            or word.split("=", 1)[0] in GIT_LOCATION_OPTIONS
        ):
            return None
        elif word.startswith("-"):
            index += 1
        else:
            break
    if index >= len(words):
        return None
    reason = git_reason(path, words[index], words[index + 1 :])
    if reason and is_primary_worktree(path):
        return reason
    return None


def find_violation(command: str, cwd: str) -> str | None:
    for words in split_segments(command):
        if words[0] == "cd" and len(words) == 2:
            cwd = os.path.join(cwd, os.path.expanduser(words[1]))
            continue
        reason = segment_reason(cwd, words)
        if reason:
            return reason
    return None


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        command = payload["tool_input"]["command"]
        cwd = payload.get("cwd") or os.getcwd()
        if not isinstance(command, str) or not isinstance(cwd, str):
            return 0
        reason = find_violation(command, cwd)
    except Exception:
        return 0
    if reason is None:
        return 0
    print(
        f"Blocked in the shared main checkout: {reason}. Other sessions work here "
        "at the same time. Move to your own worktree first (EnterWorktree, or "
        "`git worktree add`), and stage files by name with `git add <path>`.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
