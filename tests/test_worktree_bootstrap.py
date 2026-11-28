from __future__ import annotations

import pytest

from worktree_bootstrap import (
    NOT_BOOTSTRAPPED,
    require_built_ui,
    require_frontend_toolchain,
    require_wrangler,
)


def install_vite(directory):
    binaries = directory / "node_modules" / ".bin"
    binaries.mkdir(parents=True)
    (binaries / "vite").touch()


def test_worktree_without_node_modules_fails_with_the_bootstrap_command(tmp_path):
    with pytest.raises(pytest.fail.Exception) as failure:
        require_frontend_toolchain(tmp_path)

    assert str(failure.value) == NOT_BOOTSTRAPPED
    assert "npm ci && npm run build" in NOT_BOOTSTRAPPED
    assert "uv sync --group dev" in NOT_BOOTSTRAPPED


def test_worktree_with_installed_vite_passes(tmp_path):
    install_vite(tmp_path)

    require_frontend_toolchain(tmp_path)


def test_worktree_nested_in_a_bootstrapped_checkout_passes(tmp_path):
    # npm also finds binaries in an ancestor's node_modules/.bin.
    install_vite(tmp_path)
    nested = tmp_path / ".claude" / "worktrees" / "agent"
    nested.mkdir(parents=True)

    require_frontend_toolchain(nested)


def test_empty_node_modules_is_not_a_bootstrap(tmp_path):
    (tmp_path / "node_modules").mkdir()

    with pytest.raises(pytest.fail.Exception):
        require_frontend_toolchain(tmp_path)


def test_worktree_without_dist_fails_with_the_bootstrap_command(tmp_path):
    with pytest.raises(pytest.fail.Exception) as failure:
        require_built_ui(tmp_path)

    assert str(failure.value) == NOT_BOOTSTRAPPED


def test_worktree_with_built_ui_passes(tmp_path):
    (tmp_path / "dist").mkdir()
    (tmp_path / "dist" / "index.html").write_text("<!doctype html>")

    require_built_ui(tmp_path)


def install_wrangler(directory):
    binaries = directory / "node_modules" / ".bin"
    binaries.mkdir(parents=True)
    (binaries / "wrangler").touch()


def test_worktree_without_wrangler_fails_with_the_bootstrap_command(tmp_path):
    # Without a local wrangler, `npx wrangler` goes to the network and an
    # offline or cold-cache run dies with a misleading ENOTCACHED (#293).
    with pytest.raises(pytest.fail.Exception) as failure:
        require_wrangler(tmp_path)

    assert str(failure.value) == NOT_BOOTSTRAPPED
    assert "npm ci" in str(failure.value)


def test_node_modules_with_vite_but_no_wrangler_is_not_a_bootstrap(tmp_path):
    install_vite(tmp_path)

    with pytest.raises(pytest.fail.Exception):
        require_wrangler(tmp_path)


def test_worktree_with_installed_wrangler_passes(tmp_path):
    install_wrangler(tmp_path)

    require_wrangler(tmp_path)


def test_worktree_nested_in_a_checkout_with_wrangler_passes(tmp_path):
    install_wrangler(tmp_path)
    nested = tmp_path / ".claude" / "worktrees" / "agent"
    nested.mkdir(parents=True)

    require_wrangler(nested)
