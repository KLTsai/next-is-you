"""Require immutable, version-labelled references for external workflow actions."""

from __future__ import annotations

import re
import sys
from pathlib import Path


ACTION_REFERENCE = re.compile(
    r"^\s*(?:-\s+)?uses:\s*(?P<repository>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)"
    r"@(?P<revision>[^\s#]+)(?:\s+#\s*(?P<version>v\S+))?\s*$"
)
FULL_COMMIT = re.compile(r"[0-9a-f]{40}")


def main() -> int:
    workflow_dir = Path(".github/workflows")
    errors: list[str] = []
    checked = 0

    for workflow in sorted((*workflow_dir.glob("*.yml"), *workflow_dir.glob("*.yaml"))):
        for line_number, line in enumerate(workflow.read_text().splitlines(), start=1):
            if "uses:" not in line:
                continue
            match = ACTION_REFERENCE.fullmatch(line)
            if match is None:
                if re.match(r"^\s*(?:-\s+)?uses:\s*[^./]", line):
                    errors.append(f"{workflow}:{line_number}: could not validate action reference")
                continue
            checked += 1
            revision = match["revision"]
            version = match["version"]
            if not FULL_COMMIT.fullmatch(revision):
                errors.append(
                    f"{workflow}:{line_number}: {match['repository']} must use a full commit SHA"
                )
            if version is None:
                errors.append(
                    f"{workflow}:{line_number}: immutable action pin needs a version comment"
                )

    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    if checked == 0:
        print("No external workflow action references found", file=sys.stderr)
        return 1
    print(f"Validated {checked} immutable workflow action references.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
