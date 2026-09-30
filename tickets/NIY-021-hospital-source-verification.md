# NIY-021: Verify official progress sources for NTUH and Shin Kong

Status: Complete (research documented 2026-09-30; live source readiness remains unverified)

## Goal

Establish whether the public official web sources for NTUH Main and Taipei Shin Kong expose enough current, matchable queue information for a later live adapter. Existing official links in NIY-016 do not by themselves prove a direct query route, readable data, or freshness.

## Captain-confirmed scope

- Verify the official public web progress sources for NTUH Main and Taipei Shin Kong.
- Determine whether the pages expose enough information to identify the clinic session and current displayed queue progress, and whether the information can be read from the public web flow.
- Review other apps' publicly observable lookup flows or published documentation as leads for how these hospitals' progress is presented. Do not treat a third-party app as an authoritative hospital source or reproduce undocumented access behavior.
- This is research only. It does not authorize an automated poller, a production connector, LINE testing, secret setup, or deployment.

## Proposed evidence method

These details are research recommendations, not additional product requirements made by the captain:

- Record the exact official URL and the verified access path. Describe request details only when directly observed.
- Record exposed fields, access barriers, and any freshness indicator.
- Prefer at least two timestamped observations during an active clinic session before making a freshness claim. If that evidence is unavailable, report freshness as unknown.
- Give each hospital a separate usable, unusable, or unverified conclusion, with its evidence and limits.

## Scope

- Verify the official public page or query flow for each hospital and identify the observable queue fields and session information.
- Compare any relevant third-party app flow or documentation with the official source, labeling it separately and using it only as a research lead.
- Record missing or ambiguous fields, access restrictions, and any evidence relevant to freshness.
- Assess each hospital separately for use by a future adapter; do not treat a generic registration portal as a verified progress source.

## Acceptance criteria

- The report gives the official source URL and verified access path for each hospital, or states why it could not be verified.
- It lists the fields available to identify the clinic session and displayed queue progress, and calls out missing or ambiguous fields.
- Freshness is marked unknown unless supported by timestamped observations from an active public clinic session; a single page load or fixture is not evidence of a refresh cadence.
- Access restrictions, instability, and remaining questions are recorded, with a separate usable, unusable, or unverified conclusion for each hospital.
- Research uses only official public pages and low-impact manual inspection. It stores no patient-specific information and does not create an automated poller or scraper.
- No production adapter changes, real LINE calls, secrets setup, or deployment are included.

## Dependencies

NIY-004 and NIY-016.

## Out of scope

- Implementing a live hospital connector or selecting a production polling interval. Those require a separate implementation decision based on this ticket's evidence.
- Real patient data, authenticated patient portals, LINE testing, secrets management, and Cloudflare deployment.

## Outcome

The research is documented in [NIY-021 findings summary](../research/NIY-021-findings-summary.md). The official NTUH and Shin Kong progress entry points were manually rechecked for reachability on 2026-09-30. NTUH's page-level update indicator did not verify current clinic-number freshness; Shin Kong's observed department had no clinic-progress row and no documented clinic-progress refresh interval. Both sources therefore remain unverified for a live adapter. This closes the research ticket only; any adapter work remains subject to the follow-up evidence gate in the findings summary.
