"""Reject a visible Conventional Commit type on a pull request that no user can notice.

Squash merge makes the pull request title the one commit on main, so a `feat`,
`fix` or `perf` title on a change that only touches CI, scripts, tests or docs
makes Release Please propose a version for nothing. This check reads the title
from the TITLE environment variable and the changed paths from stdin, one per
line, and exits 1 with the paths and the allowed types when the title is
visible but every path is non-product.
"""

from __future__ import annotations

import os
import re
import sys

VISIBLE_TYPES = ("feat", "fix", "perf")
ALLOWED_TYPES = ("ci", "chore", "test", "build", "refactor", "style", "docs")
NON_PRODUCT_DIRS = (".github/", "scripts/", "tests/", "docs/", "research/")

TITLE_TYPE = re.compile(r"^(?P<type>[A-Za-z]+)(\([^)]*\))?!?:")


def title_type(title: str) -> str | None:
    match = TITLE_TYPE.match(title.strip())
    return match.group("type").lower() if match else None


def is_non_product(path: str) -> bool:
    return path.startswith(NON_PRODUCT_DIRS) or path.endswith(".md")


def check(title: str, paths: list[str]) -> str | None:
    """Return a failure message, or None when the title is acceptable."""
    paths = [p for p in paths if p]
    if title_type(title) not in VISIBLE_TYPES:
        return None
    if not paths or not all(is_non_product(p) for p in paths):
        return None
    listed = "\n".join(f"  {p}" for p in paths)
    return (
        f"The title {title!r} uses a type that proposes a release, but every "
        f"changed path is CI, scripts, tests or docs:\n{listed}\n"
        "Rename the pull request with one of: "
        + ", ".join(f"{t}:" for t in ALLOWED_TYPES)
        + "\nReserve feat, fix and perf for changes a user of the product can notice."
    )


def main() -> int:
    failure = check(os.environ.get("TITLE", ""), sys.stdin.read().splitlines())
    if failure:
        print(failure, file=sys.stderr)
        return 1
    print("The pull request title type matches what the change touches.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
