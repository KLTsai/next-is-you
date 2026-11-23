"""Fail fast when a test needs what a fresh worktree lacks.

A new git worktree has tracked files only: no `node_modules/` and no `dist/`.
Tests that build the UI or start the local rehearsal then die deep inside a
subprocess ("Rehearsal exited ... vite: command not found"), and tests that
serve the built UI through `worker.create_app` get a bare 404. These checks
turn both into one clear, immediate failure. They fail rather than skip, so CI
can never pass by quietly not running these tests.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

NOT_BOOTSTRAPPED = (
    "This worktree is not bootstrapped: run `npm ci && npm run build` "
    "(and `uv sync --group dev`). See the Worktrees section of README.md."
)


def frontend_toolchain_missing(root: Path = ROOT) -> bool:
    """Whether `npm run build` and `npx vite` run from `root` would find no Vite.

    npm puts `node_modules/.bin` of the package directory and of every ancestor
    on PATH, so a worktree nested inside a bootstrapped checkout still builds.
    """
    return not any(
        (directory / "node_modules" / ".bin" / "vite").exists()
        for directory in (root, *root.parents)
    )


def built_ui_missing(root: Path = ROOT) -> bool:
    """Whether `worker.STATIC_ASSET_ROOT` (`<root>/dist`) has no built UI."""
    return not (root / "dist" / "index.html").is_file()


def require_frontend_toolchain(root: Path = ROOT) -> None:
    """Call before a test runs `npm run build`, `npx vite` or the rehearsal."""
    if frontend_toolchain_missing(root):
        pytest.fail(NOT_BOOTSTRAPPED, pytrace=False)


def require_built_ui(root: Path = ROOT) -> None:
    """Call before a test serves the repository's own `dist/`."""
    if built_ui_missing(root):
        pytest.fail(NOT_BOOTSTRAPPED, pytrace=False)
