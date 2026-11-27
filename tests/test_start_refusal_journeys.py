"""The organizer presses Start for every Start refusal (#146).

Local integration (browser) evidence: the built page, the real Worker app and
send gate over SQLite, synthetic hospitals labelled "僅供測試" with scripted
answers, and the local-test fake LINE sender. No request leaves the local test
server. It is not evidence about any real hospital or about LINE.
"""

from __future__ import annotations

import asyncio

import pytest
from playwright.sync_api import Page, expect

from next_is_you import hospital_registry
from start_refusal_cases import (
    DRAFT_ID,
    RECIPIENT_ID,
    START_REFUSAL_CASES,
    StartRefusalCase,
    seed_draft,
)
from test_local_acceptance_hospital_fallbacks import Journey, run_in_browser

# These journeys serve the built UI from dist/ through create_app.
pytestmark = pytest.mark.usefixtures("built_ui")


@pytest.mark.parametrize("case", START_REFUSAL_CASES, ids=lambda case: case.code)
def test_refused_start_shows_its_text_on_the_draft_card(
    monkeypatch, screen: dict, case: StartRefusalCase
) -> None:
    monkeypatch.setitem(hospital_registry.HOSPITAL_REGISTRY, *case.hospital)
    journey = Journey()
    journey.now = case.now
    asyncio.run(seed_draft(journey, DRAFT_ID, case))
    case.arrange(journey, case)
    saved = journey.stored_visit(DRAFT_ID)

    def steps(page: Page) -> None:
        page.get_by_role("button", name="展開草稿").click()
        card = page.locator(f'article[aria-labelledby="visit-{DRAFT_ID}"]')
        start = card.locator(f'[data-start="{DRAFT_ID}"]')
        expect(start).to_be_enabled()
        case.before_press(journey)
        with page.expect_response(f"**/api/organizer/visits/{DRAFT_ID}/start") as sent:
            start.tap() if screen.get("has_touch") else start.click()
        assert sent.value.json()["error"]["code"] == case.code
        expect(card.get_by_role("alert")).to_have_text(case.text)
        # The card is still a draft, ready to be started again.
        expect(card.locator(".state")).to_contain_text("草稿")
        expect(start).to_be_enabled()

    run_in_browser(journey, steps, screen)

    assert journey.stored_visit(DRAFT_ID) == saved
    assert (saved["state"], saved["recipients"]) == ("draft", [RECIPIENT_ID])
    assert journey.outbound_events() == 0
    assert asyncio.run(journey.line_requests()) == []
