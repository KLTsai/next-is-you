"""Tick (or untick) acceptance-criteria boxes in a GitHub issue body, safely.

Each ticked box gets its evidence appended to the same line:

    - [x] <criterion> Evidence (<label>): <pointer>

where <label> is one of the evidence labels from AGENTS.md and <pointer> is a
test name, a PR, a run link, a log excerpt or a screenshot.

The script dry-runs by default: it prints the unified diff and writes nothing.
`--apply` writes the new body through a temporary file and re-reads the issue
to confirm it landed. It refuses to write when the fetched body is empty, when
the new body is shorter than the old one, when any line other than the targeted
boxes would change, or when the issue changed since it was read.

Every `gh` call names the repository with `-R`, so the working directory never
decides which repository is read or written.

Usage:
    scripts/tick_acceptance.py 190 --index 2 --label fixture/mock \
        --evidence '#191, `test_last_part_of_a_date_can_be_typed`'
    scripts/tick_acceptance.py 190 --box 'Exact criterion text' ... --apply
    scripts/tick_acceptance.py 190 --index 2 --untick --apply
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from typing import Callable, Sequence, TextIO

DEFAULT_REPO = "KLTsai/next-is-you"

# The evidence labels named in AGENTS.md, in their canonical spelling.
LABELS = ("fixture/mock", "local integration", "live provider")

# A task-list item: indentation, bullet, box, then the criterion text.
BOX = re.compile(r"^(?P<lead>\s*[-*+]\s+\[)(?P<mark>[ xX])(?P<sep>\]\s+)(?P<text>.*)$")
FENCE = re.compile(r"^\s*(```|~~~)")
# A line that starts a new block: a list item, a heading or a quote.
NEW_BLOCK = re.compile(r"^\s*([-*+]|\d+[.)])(\s|$)|^\s*[#>]")

Runner = Callable[[Sequence[str]], subprocess.CompletedProcess]


class Refusal(Exception):
    """The script will not write; the message says why."""


@dataclass(frozen=True)
class Box:
    index: int  # 1-based position among the body's boxes
    line: int  # 0-based line number of the box
    last: int  # 0-based last line of the criterion (it may wrap)
    ticked: bool
    text: str  # the criterion, wrapped lines joined by single spaces


def split_lines(body: str) -> list[tuple[str, str]]:
    """Split into (content, line ending) pairs so endings survive untouched."""
    pairs = []
    for raw in body.splitlines(keepends=True):
        content = raw.rstrip("\r\n")
        pairs.append((content, raw[len(content) :]))
    return pairs


def find_boxes(body: str) -> list[Box]:
    lines = [content for content, _ in split_lines(body)]
    boxes: list[Box] = []
    in_fence = False
    for number, content in enumerate(lines):
        if FENCE.match(content):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        match = BOX.match(content)
        if match:
            last = number
            parts = [match["text"]]
            while (
                last + 1 < len(lines)
                and lines[last + 1].strip()
                and not NEW_BLOCK.match(lines[last + 1])
                and not FENCE.match(lines[last + 1])
            ):
                last += 1
                parts.append(lines[last])
            boxes.append(
                Box(
                    index=len(boxes) + 1,
                    line=number,
                    last=last,
                    ticked=match["mark"] != " ",
                    text=" ".join(" ".join(parts).split()),
                )
            )
    return boxes


def select(boxes: list[Box], indexes: Sequence[int], texts: Sequence[str]) -> list[Box]:
    if not boxes:
        raise Refusal("the issue body has no checkboxes")
    chosen: dict[int, Box] = {}
    for index in indexes:
        if not 1 <= index <= len(boxes):
            raise Refusal(f"no box #{index}: the body has {len(boxes)} boxes")
        chosen[index] = boxes[index - 1]
    for text in texts:
        wanted = " ".join(text.split())
        matches = [box for box in boxes if box.text == wanted]
        if not matches:
            raise Refusal(f"no box has exactly this text: {wanted!r}")
        if len(matches) > 1:
            numbers = ", ".join(f"#{box.index}" for box in matches)
            raise Refusal(
                f"{len(matches)} boxes ({numbers}) have this text; use --index"
            )
        chosen[matches[0].index] = matches[0]
    return [chosen[index] for index in sorted(chosen)]


def canonical_label(label: str) -> str:
    for known in LABELS:
        if label.strip().lower() == known:
            return known
    raise Refusal(f"evidence label must be one of: {', '.join(LABELS)}")


def evidence_suffix(label: str, evidence: str) -> str:
    pointer = " ".join(evidence.split())
    if not pointer:
        raise Refusal("evidence is required: name a test, a PR, a run link or a log")
    return f" Evidence ({canonical_label(label)}): {pointer}"


def rewrite(body: str, targets: list[Box], untick: bool, suffix: str) -> str:
    lines = split_lines(body)
    for box in targets:
        if untick and not box.ticked:
            raise Refusal(f"box #{box.index} is not ticked")
        if not untick and box.ticked:
            raise Refusal(f"box #{box.index} is already ticked")
        content, ending = lines[box.line]
        match = BOX.match(content)
        assert match is not None
        mark = " " if untick else "x"
        lines[box.line] = (
            f"{match['lead']}{mark}{match['sep']}{match['text']}",
            ending,
        )
        if not untick:
            content, ending = lines[box.last]
            lines[box.last] = (content.rstrip() + suffix, ending)
    return "".join(content + ending for content, ending in lines)


def check_safe(old: str, new: str, targets: list[Box], untick: bool) -> None:
    if not old.strip():
        raise Refusal("the fetched body is empty; refusing to write")
    if not untick and len(new) < len(old):
        raise Refusal("the new body is shorter than the old one; refusing to write")
    old_lines, new_lines = split_lines(old), split_lines(new)
    if len(old_lines) != len(new_lines):
        raise Refusal("the line count changed; refusing to write")
    allowed = {box.line for box in targets}
    if not untick:
        allowed |= {box.last for box in targets}
    changed = {n for n, (a, b) in enumerate(zip(old_lines, new_lines)) if a != b}
    if changed - allowed:
        raise Refusal("lines other than the targeted boxes changed; refusing to write")
    if changed != allowed:
        raise Refusal("a targeted box did not change; refusing to write")


def unified_diff(old: str, new: str, issue: int) -> str:
    return "".join(
        difflib.unified_diff(
            old.splitlines(keepends=True),
            new.splitlines(keepends=True),
            fromfile=f"#{issue} (current)",
            tofile=f"#{issue} (proposed)",
            n=0,
        )
    )


def same_body(a: str, b: str) -> bool:
    """GitHub may normalise line endings and the trailing newline."""

    def norm(s: str) -> str:
        return s.replace("\r\n", "\n").rstrip()

    return norm(a) == norm(b)


# GitHub access. Everything above is pure; everything below talks to `gh`.


def gh(run: Runner, *args: str) -> str:
    result = run(["gh", *args])
    if result.returncode != 0:
        raise Refusal(f"`gh {' '.join(args[:2])}` failed: {result.stderr.strip()}")
    return result.stdout


def fetch_body(run: Runner, repo: str, issue: int) -> str:
    out = gh(run, "issue", "view", str(issue), "-R", repo, "--json", "body")
    try:
        body = json.loads(out)["body"]
    except (ValueError, KeyError, TypeError):
        raise Refusal(f"could not read the body of #{issue} from gh output")
    if not isinstance(body, str) or not body.strip():
        raise Refusal(f"the fetched body of #{issue} is empty; refusing to write")
    return body


def write_body(run: Runner, repo: str, issue: int, body: str) -> None:
    fd, path = tempfile.mkstemp(prefix=f"issue-{issue}-", suffix=".md")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(body)
        gh(run, "issue", "edit", str(issue), "-R", repo, "--body-file", path)
    finally:
        os.unlink(path)


def default_run(args: Sequence[str]) -> subprocess.CompletedProcess:
    return subprocess.run(list(args), capture_output=True, text=True, encoding="utf-8")


def main(
    argv: Sequence[str] | None = None,
    run: Runner = default_run,
    out: TextIO = sys.stdout,
    err: TextIO = sys.stderr,
) -> int:
    parser = argparse.ArgumentParser(
        description="Tick acceptance-criteria boxes with evidence (dry run by default)."
    )
    parser.add_argument("issue", type=int)
    parser.add_argument("-R", "--repo", default=DEFAULT_REPO)
    parser.add_argument(
        "--index", type=int, action="append", default=[], help="1-based box number"
    )
    parser.add_argument(
        "--box", action="append", default=[], help="exact text after the checkbox"
    )
    parser.add_argument("--label", help=f"evidence label: {', '.join(LABELS)}")
    parser.add_argument("--evidence", help="test name, PR, run link or log excerpt")
    parser.add_argument("--untick", action="store_true")
    parser.add_argument("--apply", action="store_true", help="write (default: dry run)")
    args = parser.parse_args(argv)

    try:
        if not args.index and not args.box:
            raise Refusal("name at least one box with --index or --box")
        if args.untick:
            if args.label or args.evidence:
                raise Refusal("--untick takes no --label or --evidence")
            suffix = ""
        else:
            if not args.label:
                raise Refusal(f"--label is required: one of {', '.join(LABELS)}")
            suffix = evidence_suffix(args.label, args.evidence or "")

        old = fetch_body(run, args.repo, args.issue)
        targets = select(find_boxes(old), args.index, args.box)
        new = rewrite(old, targets, args.untick, suffix)
        check_safe(old, new, targets, args.untick)
        out.write(unified_diff(old, new, args.issue))

        if not args.apply:
            out.write(
                f"Dry run: #{args.issue} not changed. Rerun with --apply to write.\n"
            )
            return 0

        if fetch_body(run, args.repo, args.issue) != old:
            raise Refusal(f"#{args.issue} changed since it was read; rerun")
        write_body(run, args.repo, args.issue, new)
        if not same_body(fetch_body(run, args.repo, args.issue), new):
            raise Refusal(
                f"#{args.issue} does not hold the new body after writing; "
                "check its edit history"
            )
        out.write(f"Wrote and verified #{args.issue} in {args.repo}.\n")
        return 0
    except Refusal as refusal:
        err.write(f"tick_acceptance: {refusal}\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
