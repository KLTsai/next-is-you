# NIY-025: Collapse and expand the saved-drafts section

Status: Implemented (local acceptance passed; pipeline pending)

## Goal

Make the saved drafts shown below notification setup easier to scan by providing a clear, accessible collapse/expand control while keeping the section discoverable.

## Scope

- Add a clearly labeled, keyboard-accessible collapse/expand affordance for the saved-drafts section below setup.
- Keep the section heading and control discoverable in both collapsed and expanded states, with an accurate expanded/collapsed state exposed to assistive technology.
- Preserve draft data and selection/correction behavior when toggling the section.

## Acceptance criteria

- Local browser acceptance shows the saved-drafts section below setup with a visible control whose label and state make the action clear.
- Mouse, keyboard, and assistive-technology interaction can collapse and expand the section; focus behavior remains usable and no draft data is removed.
- With multiple synthetic drafts, expanding exposes the same drafts, selecting a draft still opens the correct correction flow, and collapsing/re-expanding preserves that selection and saved values.
- Automated UI/accessibility coverage verifies discoverability, state semantics, keyboard operation, and the unchanged draft selection/correction journey.

## Dependencies

NIY-007 for the settings UI and NIY-020 for the existing draft/correction journey.

## Out of scope

- API, persistence, draft lifecycle, notification, or correction-data semantics.
- Changes to setup fields, authorization, provider integrations, responsive layout beyond this section's control, deployment, or real patient data.
