from __future__ import annotations

import pytest

from worktree_bootstrap import require_built_ui


@pytest.fixture
def built_ui() -> None:
    """Fails at once, with the bootstrap command, when dist/ has not been built."""
    require_built_ui()
