"""Ticking acceptance boxes through `scripts/tick_acceptance.py`.

Evidence: fixture/mock. `gh` is replaced by an in-memory issue; nothing here
touches the network.
"""

from __future__ import annotations

import importlib.util
import io
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "tick_acceptance", ROOT / "scripts" / "tick_acceptance.py"
)
tick_acceptance = importlib.util.module_from_spec(_spec)
sys.modules["tick_acceptance"] = tick_acceptance
_spec.loader.exec_module(tick_acceptance)

BODY = """## Acceptance

- [ ] Fixture/mock: the calendar stays open.
- [x] Fixture/mock: a typed date survives. Evidence (fixture/mock): #191
- [ ] Local integration: the worker sends one reminder.
- [ ] Same text
- [ ] Same text
- [ ] Live provider: a wrapped criterion that
      continues here.
  - A nested note that is not part of the criterion.

```md
- [ ] Inside a fence, not a box.
```
"""


class FakeGh:
    """An issue held in memory, reached only through `gh` argument lists."""

    def __init__(self, body: str, *, fail_view: bool = False, store=None):
        self.body = body
        self.fail_view = fail_view
        self.store = store or (lambda written: written)
        self.calls: list[list[str]] = []
        self.views_before_edit: list[str] = []

    def __call__(self, args):
        args = list(args)
        self.calls.append(args)
        if args[:3] == ["gh", "issue", "view"]:
            if self.fail_view:
                return subprocess.CompletedProcess(args, 1, "", "not a git repository")
            return subprocess.CompletedProcess(
                args, 0, json.dumps({"body": self.body}), ""
            )
        if args[:3] == ["gh", "issue", "edit"]:
            path = args[args.index("--body-file") + 1]
            self.body = self.store(Path(path).read_bytes().decode("utf-8"))
            return subprocess.CompletedProcess(args, 0, "", "")
        raise AssertionError(f"unexpected gh call: {args}")

    def edits(self) -> list[list[str]]:
        return [c for c in self.calls if c[:3] == ["gh", "issue", "edit"]]


def run(fake: FakeGh, *argv: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = tick_acceptance.main(list(argv), run=fake, out=out, err=err)
    return code, out.getvalue(), err.getvalue()


TICK_FIRST = (
    "98",
    "--index",
    "1",
    "--label",
    "fixture/mock",
    "--evidence",
    "#200, `test_calendar`",
)


def test_dry_run_is_the_default_and_prints_the_diff():
    fake = FakeGh(BODY)
    code, out, err = run(fake, *TICK_FIRST)
    assert code == 0, err
    assert "-- [ ] Fixture/mock: the calendar stays open.\n" in out
    assert (
        "+- [x] Fixture/mock: the calendar stays open. "
        "Evidence (fixture/mock): #200, `test_calendar`\n"
    ) in out
    assert "Dry run" in out
    assert fake.edits() == []
    assert fake.body == BODY


def test_apply_writes_only_the_targeted_line_and_verifies():
    fake = FakeGh(BODY)
    code, out, err = run(fake, *TICK_FIRST, "--apply")
    assert code == 0, err
    assert "Wrote and verified #98" in out
    expected = BODY.replace(
        "- [ ] Fixture/mock: the calendar stays open.",
        "- [x] Fixture/mock: the calendar stays open. "
        "Evidence (fixture/mock): #200, `test_calendar`",
    )
    assert fake.body == expected
    assert len(fake.edits()) == 1
    # The issue is read again after writing.
    assert fake.calls[-1][:3] == ["gh", "issue", "view"]


def test_every_gh_call_names_the_repository():
    fake = FakeGh(BODY)
    run(fake, *TICK_FIRST, "--apply")
    assert fake.calls
    for call in fake.calls:
        assert call[call.index("-R") + 1] == "KLTsai/next-is-you"

    other = FakeGh(BODY)
    run(other, *TICK_FIRST, "--apply", "-R", "someone/fork")
    for call in other.calls:
        assert call[call.index("-R") + 1] == "someone/fork"


def test_tick_by_exact_text_and_several_boxes_at_once():
    fake = FakeGh(BODY)
    code, _, err = run(
        fake,
        "98",
        "--box",
        "Local integration: the worker sends one reminder.",
        "--index",
        "1",
        "--label",
        "Local Integration",
        "--evidence",
        "https://github.com/KLTsai/next-is-you/actions/runs/1",
        "--apply",
    )
    assert code == 0, err
    suffix = " Evidence (local integration): https://github.com/KLTsai/next-is-you/actions/runs/1"
    assert f"- [x] Fixture/mock: the calendar stays open.{suffix}\n" in fake.body
    assert (
        f"- [x] Local integration: the worker sends one reminder.{suffix}\n"
        in fake.body
    )


def test_untick_flips_only_the_mark():
    fake = FakeGh(BODY)
    code, _, err = run(fake, "98", "--index", "2", "--untick", "--apply")
    assert code == 0, err
    assert fake.body == BODY.replace(
        "- [x] Fixture/mock: a typed", "- [ ] Fixture/mock: a typed"
    )


def test_boxes_inside_code_fences_are_not_counted():
    fake = FakeGh(BODY)
    code, _, err = run(
        fake, "98", "--index", "7", "--label", "fixture/mock", "--evidence", "x"
    )
    assert code == 1
    assert "the body has 6 boxes" in err


def test_line_endings_are_kept():
    crlf = BODY.replace("\n", "\r\n")
    fake = FakeGh(crlf)
    code, _, err = run(fake, *TICK_FIRST, "--apply")
    assert code == 0, err
    assert fake.body.count("\r\n") == crlf.count("\r\n")


def refused(fake: FakeGh, *argv: str) -> str:
    code, _, err = run(fake, *argv)
    assert code == 1
    assert fake.edits() == []
    return err


def test_refuses_an_empty_fetched_body():
    # The retro: `gh issue view` printed nothing and that nothing was written back.
    assert "empty" in refused(FakeGh(""), *TICK_FIRST, "--apply")
    assert "empty" in refused(FakeGh("  \n"), *TICK_FIRST, "--apply")


def test_refuses_when_gh_cannot_read_the_issue():
    assert "failed" in refused(FakeGh(BODY, fail_view=True), *TICK_FIRST, "--apply")


def test_refuses_ambiguous_and_missing_text():
    err = refused(
        FakeGh(BODY),
        "98",
        "--box",
        "Same text",
        "--label",
        "fixture/mock",
        "--evidence",
        "x",
        "--apply",
    )
    assert "#4, #5" in err
    err = refused(
        FakeGh(BODY),
        "98",
        "--box",
        "the calendar",
        "--label",
        "fixture/mock",
        "--evidence",
        "x",
        "--apply",
    )
    assert "no box has exactly this text" in err


def test_refuses_a_box_number_out_of_range():
    assert "no box #9" in refused(
        FakeGh(BODY),
        "98",
        "--index",
        "9",
        "--label",
        "fixture/mock",
        "--evidence",
        "x",
        "--apply",
    )


def test_evidence_and_a_known_label_are_required():
    assert "--label is required" in refused(
        FakeGh(BODY), "98", "--index", "1", "--evidence", "x", "--apply"
    )
    assert "evidence is required" in refused(
        FakeGh(BODY), "98", "--index", "1", "--label", "fixture/mock", "--apply"
    )
    assert "evidence is required" in refused(
        FakeGh(BODY),
        "98",
        "--index",
        "1",
        "--label",
        "fixture/mock",
        "--evidence",
        "  ",
        "--apply",
    )
    assert "must be one of" in refused(
        FakeGh(BODY),
        "98",
        "--index",
        "1",
        "--label",
        "manual",
        "--evidence",
        "x",
        "--apply",
    )


def test_refuses_ticking_a_ticked_box_or_unticking_an_open_one():
    assert "already ticked" in refused(
        FakeGh(BODY),
        "98",
        "--index",
        "2",
        "--label",
        "fixture/mock",
        "--evidence",
        "x",
        "--apply",
    )
    assert "not ticked" in refused(
        FakeGh(BODY), "98", "--index", "1", "--untick", "--apply"
    )


def test_refuses_when_the_issue_changed_since_it_was_read():
    fake = FakeGh(BODY)
    original = fake.__call__
    views = {"n": 0}

    def racing(args):
        result = original(args)
        if list(args)[:3] == ["gh", "issue", "view"]:
            views["n"] += 1
            if views["n"] == 1:
                fake.body = BODY + "\nSomeone else edited this.\n"
        return result

    code, _, err = run(racing, *TICK_FIRST, "--apply")  # type: ignore[arg-type]
    assert code == 1
    assert "changed since it was read" in err
    assert fake.edits() == []


def test_reports_a_write_that_did_not_land():
    fake = FakeGh(BODY, store=lambda written: BODY)
    code, _, err = run(fake, *TICK_FIRST, "--apply")
    assert code == 1
    assert "does not hold the new body" in err


def test_safety_check_refuses_shorter_bodies_and_stray_changes():
    boxes = tick_acceptance.find_boxes(BODY)
    target = [boxes[0]]
    shorter = BODY.replace("## Acceptance\n", "")
    stray = BODY.replace("## Acceptance", "## Acceptance criteria").replace(
        "- [ ] Fixture/mock: the calendar", "- [x] Fixture/mock: the calendar"
    )
    for new, reason in ((shorter, "shorter"), (stray, "other than the targeted")):
        try:
            tick_acceptance.check_safe(BODY, new, target, untick=False)
        except tick_acceptance.Refusal as refusal:
            assert reason in str(refusal)
        else:
            raise AssertionError(f"accepted a body that should be refused: {reason}")


def test_a_wrapped_criterion_gets_its_evidence_after_its_last_line():
    fake = FakeGh(BODY)
    code, _, err = run(
        fake,
        "98",
        "--box",
        "Live provider: a wrapped criterion that continues here.",
        "--label",
        "live provider",
        "--evidence",
        "Staging run 2026-11-23",
        "--apply",
    )
    assert code == 0, err
    assert fake.body == BODY.replace(
        "- [ ] Live provider: a wrapped criterion that\n      continues here.\n",
        "- [x] Live provider: a wrapped criterion that\n"
        "      continues here. Evidence (live provider): Staging run 2026-11-23\n",
    )
