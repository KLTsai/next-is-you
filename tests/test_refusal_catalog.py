"""The backend refusal catalog and the frontend text map must name the same codes.

A backend code without a frontend text shows the organizer a generic error; a
frontend text no backend code reaches is dead wording nobody can see. Both
directions fail here (#145, seam 3 of #144).

The catalog must also have a browser journey case for every Start refusal, and
hold every code the send gate can return (#146).

Fixture/mock evidence: reads the catalog module, the frontend text module, the
journey case list and the send gate source only, no network.
"""

import json
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

from gate_refusal_codes import gate_refusal_codes
from next_is_you.refusal_catalog import ATTENTION_REASONS, START_REFUSAL_CODES
from start_refusal_cases import START_REFUSAL_CASES

ROOT = Path(__file__).resolve().parent.parent
SEND_GATE = ROOT / "src" / "next_is_you" / "send_gate.py"

# Texts kept while no backend code reaches them. Each entry names the issue
# that removes it: either the code becomes real or the text goes.
KNOWN_UNREACHED_TEXTS = {"clinic_combo_mismatch"}  # #149 makes it real.


def frontend_text_codes() -> set[str]:
    node = shutil.which("node")
    assert node, "node is required to read the frontend text map"
    script = (
        "import { REFUSAL_TEXTS } from './frontend/src/refusal-texts.js';"
        "console.log(JSON.stringify(Object.keys(REFUSAL_TEXTS)));"
    )
    result = subprocess.run(
        [node, "--input-type=module", "-e", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    codes = json.loads(result.stdout)
    assert codes, "the frontend text map is empty; the comparison would pass vacuously"
    return set(codes)


def backend_codes() -> set[str]:
    codes = set(START_REFUSAL_CODES) | set(ATTENTION_REASONS)
    assert codes, "the backend catalog is empty; the comparison would pass vacuously"
    return codes


def test_every_backend_code_has_a_frontend_text():
    missing = backend_codes() - frontend_text_codes()
    assert not missing, f"backend codes without a frontend text: {sorted(missing)}"


def test_every_frontend_text_has_a_backend_code_or_a_listed_exception():
    unreached = frontend_text_codes() - backend_codes() - KNOWN_UNREACHED_TEXTS
    assert not unreached, f"frontend texts no backend code reaches: {sorted(unreached)}"


def test_listed_exceptions_are_still_unreached_texts():
    """An exception that became a real code, or lost its text, must be removed."""
    texts = frontend_text_codes()
    stale = {
        code
        for code in KNOWN_UNREACHED_TEXTS
        if code in backend_codes() or code not in texts
    }
    assert not stale, f"exceptions to remove from the list: {sorted(stale)}"


def test_catalog_has_no_overlap_between_refusals_and_attention_reasons():
    assert not set(START_REFUSAL_CODES) & set(ATTENTION_REASONS)


@pytest.mark.parametrize("code", sorted(START_REFUSAL_CODES))
def test_each_start_refusal_has_an_http_status(code):
    assert START_REFUSAL_CODES[code] in {409, 503, 404}


def test_every_start_refusal_has_exactly_one_browser_journey_case():
    """test_start_refusal_journeys.py runs one journey per case (#146)."""
    cases = sorted(case.code for case in START_REFUSAL_CASES)
    assert cases == sorted(START_REFUSAL_CODES), (
        f"codes without a case: {sorted(set(START_REFUSAL_CODES) - set(cases))}; "
        f"cases without a code: {sorted(set(cases) - set(START_REFUSAL_CODES))}"
    )


def stand_in_gate(
    start: str = 'return {"error": "known"}',
    stop: str = "return None",
    module: str = "",
) -> str:
    """A gate with the real one's Start and Stop functions around one answer each."""
    return f"""
_ERRORS = {{"stale": "from_table"}}
{module}

def _named(status):
    if status:
        return "from_function"
    return _ERRORS.get(status, "from_default")


class Gate:
    async def start_visit(self, status):
        result = await self._start_visit(status)
        if result.get("state") == "active":
            print({{"event": "started", "error": type(status).__name__}})
        return result

    async def _start_visit(self, status):
{textwrap.indent(start, " " * 8)}

    async def _preflight_validate(self, status):
        return {{"clinic_code": status}}

    async def stop_visit(self, repository, status):
{textwrap.indent(stop, " " * 8)}
"""


@pytest.mark.parametrize(
    "gate,codes",
    [
        (stand_in_gate(start='return {"error": "added"}'), {"added"}),
        (stand_in_gate(start='return {"error": _ERRORS[status]}'), {"from_table"}),
        (
            stand_in_gate(start='return {"error": _named(status)}'),
            {"from_function", "from_table", "from_default"},
        ),
        (
            stand_in_gate(
                start='refusal = {"error": "first"}\n'
                'refusal["error"] = "second"\n'
                'refusal["detail"] = status\n'
                "return refusal"
            ),
            {"first", "second"},
        ),
        (
            stand_in_gate(
                start="preflight = await self._preflight_validate(status)\n"
                'if "error" in preflight:\n'
                "    return preflight\n"
                'return {"state": preflight["clinic_code"]}'
            ),
            set(),
        ),
        (stand_in_gate(stop='return "added"'), {"known", "added"}),
        (stand_in_gate(stop='return "stopping"'), {"known"}),
        (
            stand_in_gate(stop="state = await repository.stop(status)\nreturn state"),
            {"known"},
        ),
    ],
    ids=[
        "start_literal",
        "table",
        "helper",
        "built_in_steps",
        "passed_on",
        "stop_literal",
        "stop_state",
        "stop_repository_state",
    ],
)
def test_gate_code_collector_reads_every_way_the_gate_answers(gate, codes):
    assert gate_refusal_codes(gate) == codes


@pytest.mark.parametrize(
    "gate",
    [
        stand_in_gate(start='return {"error": status}'),
        stand_in_gate(start='return {"error": f"{status}_refused"}'),
        stand_in_gate(start='return dict(error="new")'),
        stand_in_gate(start='return {status: "new"}'),
        stand_in_gate(start="return await self._another_check(status)"),
        stand_in_gate(start="return imported_check(status)"),
        stand_in_gate(start="answer = imported_check(status)\nreturn answer"),
        stand_in_gate(start='answer = {}\nanswer.update(error="new")\nreturn answer'),
        stand_in_gate(
            start='answer = {}\nanswer.setdefault("error", "new")\nreturn answer'
        ),
        stand_in_gate(start='answer = {}\nanswer[status] = "new"\nreturn answer'),
        stand_in_gate(
            start='answer = {}\ncode = answer["error"] = "new"\nreturn answer'
        ),
        stand_in_gate(start="answer = {}\nimported_fill(answer)\nreturn answer"),
        stand_in_gate(
            start='return {"error": _ERRORS[status]}',
            module='_ERRORS["late"] = "new"',
        ),
        stand_in_gate(stop="return self._refusal(status)"),
        stand_in_gate(stop='state = "new"\nreturn state'),
        stand_in_gate(stop="return status"),
    ],
    ids=[
        "variable",
        "composed_text",
        "dict_call",
        "variable_key",
        "unlisted_method",
        "imported_function",
        "imported_answer",
        "update",
        "setdefault",
        "variable_subscript",
        "chained_assignment",
        "filled_elsewhere",
        "table_changed_later",
        "stop_call",
        "stop_state_variable_holds_a_code",
        "stop_other_variable",
    ],
)
def test_gate_code_collector_fails_on_an_answer_it_cannot_read(gate):
    with pytest.raises(AssertionError, match="cannot read"):
        gate_refusal_codes(gate)


def test_every_code_the_send_gate_can_return_is_in_the_catalog():
    """The worker answers a gate code it does not know as `service_unavailable`."""
    codes = gate_refusal_codes(SEND_GATE.read_text(encoding="utf-8"))
    assert codes, "no gate code collected; the comparison would pass vacuously"
    missing = codes - set(START_REFUSAL_CODES)
    assert not missing, f"send gate codes not in the catalog: {sorted(missing)}"
