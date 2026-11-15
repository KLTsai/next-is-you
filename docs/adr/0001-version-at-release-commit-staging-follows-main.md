---
status: accepted
---

# A version is born at the release commit, and staging follows main

Issue #55 made the `vX.Y.Z` tag mean "accepted in production": only promotion created it, and a commit reached staging through a manually dispatched candidate deployment recorded as `candidate-vX.Y.Z-<commit>`. Two weeks of use showed that this tied version identity to production acceptance. Release Please lost its changelog boundary whenever a merged release PR had not yet been promoted, one version number came to cover commits made after its release commit, and the captain had to paste commit SHAs and pick tags to move anything forward.

We decided on 2026-11-15 that merging the release PR creates the `vX.Y.Z` tag, so a version is exactly one commit; that staging deploys automatically from every green push to `main` and is identified by commit, not by version; and that the captain's manual Promote, given a version, deploys it to production and publishes the GitHub Release. "In production" is stated by the published Release, not by the tag. Issue #66 carries the scope and acceptance.

## Considered options

- **Keep the tag at promotion (#55).** Rejected: the missing-boundary stall is structural, and guarding it needed a script, a documentation section, and a manual label change after every release.
- **No version until production, staging identified by commit only, no release PR.** Rejected: it removes the changelog and the one place where the captain decides what a release contains.
- **Require a pull request for every change, enforced by a ruleset.** Rejected: rulesets need a paid plan for a private personal repository, and the sources in `research/CI-CD-main-policy-and-versioning.md` do not support mandatory review of a sole maintainer's own documentation changes.

## Consequences

- A version rejected on staging keeps its tag and its `CHANGELOG.md` section and never gets a Release. Its fix ships as the next version, so version numbers can skip in production.
- What the captain checked and what Promote deploys can differ if anything product-changing merges after the release PR. Promote therefore refuses unless the latest successful staging deployment is the version's commit.
- A commit on `main` reaches staging, and its migrations reach the staging database, without a captain decision. Staging shares the production LINE Login channel, so changes to code, migrations, workflows, or deployment configuration must arrive through a pull request the captain merges.
- Nothing on the hosting plan enforces who may merge the release PR or run Promote. That they are the captain's alone is a written rule in `AGENTS.md`, not a control.
