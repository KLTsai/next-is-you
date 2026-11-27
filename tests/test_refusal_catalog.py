"""The backend refusal catalog and the frontend text map must name the same codes.

A backend code without a frontend text shows the organizer a generic error; a
frontend text no backend code reaches is dead wording nobody can see. Both
directions fail here (#145, seam 3 of #144).

The catalog must also have a browser journey case for every Start refusal
(#146).

Fixture/mock evidence: reads the catalog module, the frontend text module and
the journey case list only, no network.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from next_is_you.refusal_catalog import (
    ATTENTION_REASONS,
    START_REFUSAL_CODES,
    RefusalCode,
)
from start_refusal_cases import START_REFUSAL_CASES

ROOT = Path(__file__).resolve().parent.parent

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


@pytest.mark.parametrize("code", sorted(RefusalCode))
def test_each_start_refusal_has_an_http_status(code):
    assert START_REFUSAL_CODES[code] in {409, 503, 404}


def test_every_start_refusal_has_exactly_one_browser_journey_case():
    """test_start_refusal_journeys.py runs one journey per case (#146)."""
    cases = sorted(case.code for case in START_REFUSAL_CASES)
    assert cases == sorted(START_REFUSAL_CODES), (
        f"codes without a case: {sorted(set(START_REFUSAL_CODES) - set(cases))}; "
        f"cases without a code: {sorted(set(cases) - set(START_REFUSAL_CODES))}"
    )
