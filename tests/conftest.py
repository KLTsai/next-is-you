from __future__ import annotations

from pathlib import Path

import pytest

from screens import SCREENS
from worktree_bootstrap import require_built_ui


@pytest.fixture
def built_ui() -> None:
    """Fails at once, with the bootstrap command, when dist/ has not been built."""
    require_built_ui()


# A module that drives Chromium or starts a local Worker is a browser module.
# Its tests need `dist/`, Node and Playwright, and take most of the suite's
# time, so `npm test` leaves them out and `npm run test:all` runs them. The
# markers come from the module source, so a new test in such a module, or a
# new module that uses them, is marked without editing this file.
BROWSER_MODULE_MARKERS = ("sync_playwright", "pywrangler")


def _is_browser_module(path: Path, cache: dict[Path, bool]) -> bool:
    if path not in cache:
        source = path.read_text(encoding="utf-8")
        cache[path] = any(marker in source for marker in BROWSER_MODULE_MARKERS)
    return cache[path]


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    cache: dict[Path, bool] = {}
    for item in items:
        if _is_browser_module(item.path, cache):
            item.add_marker(pytest.mark.browser)


@pytest.fixture(params=SCREENS)
def screen(request: pytest.FixtureRequest) -> dict:
    """Context options of one screen an organizer page is tested on."""
    return SCREENS[request.param]
