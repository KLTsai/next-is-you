# CI/CD: main branch policy and versioning before production

Research completed 2026-11-15. Scope: (A) whether every change must go through a pull request, and (B) how versions should be managed between release-PR merge and production with Release Please. Primary sources only: official docs, first-party articles, and source code read at a pinned commit. Each claim is labelled **Source** (what the source says), **Observed** (measured in this repository on 2026-11-15), or **Inference** (my reasoning). This is supporting evidence, not implementation authority; adopt anything from it through a GitHub issue first.

Pinned source revisions used below:

| Source | Revision |
| --- | --- |
| `googleapis/release-please` | `ea20bc261acd75149f0be90890bb9c90e681eea7` (package version 17.11.2) |
| `googleapis/release-please-action` | `0b6b3fc0186a2f7118bfd88fab9ea481e1839504` (5.0.0), plus tags `v4.2.0`, `v4.4.0`, `v4.4.1`, `v5.0.0` |
| `github/docs` (source of docs.github.com) | `d59b2631959db46d71ca5f7748ec04311c6d0870` |

## Summary of answers

**A. PR for everything vs direct push**

1. No primary source says every change needs a pull request. trunkbaseddevelopment.com, DORA, and Martin Fowler's site all treat direct commits to trunk as legitimate, conditional on a fast, trustworthy build that runs before and after the push. Ship / Show / Ask names "I updated documentation" and "I fixed an unremarkable bug" as changes to push straight to mainline.
2. What the sources do require is not the PR but the safety net: every commit to main triggers a build, a broken main is fixed or reverted immediately, and review happens somewhere (before, during, or after integration). DORA found heavyweight external approval hurts delivery performance with no evidence of lower change-fail rates.
3. For AI coding agents the first-party guidance points the other way: Anthropic's Claude Code docs and GitHub's Copilot cloud agent docs both put a branch rule and a human merge approval in front of agent work. Inference: captain may Ship low-risk changes directly; agents (`fm/*`) should always go through a PR.
4. GitHub cannot enforce any of this for this repository today. Protected branches and rulesets for private repositories need GitHub Pro (personal account) or a paid organization plan. Merge queue is not available to personal-account repositories at all. On Pro, a ruleset can require a PR with zero approvals, status checks, and linear history, and the admin bypass can be set to "For pull requests only".
5. Cheap CI for docs-only changes must not be done with workflow-level `paths-ignore` if the check ever becomes required: a skipped workflow leaves the check "Pending" and blocks the merge. The documented alternative is to keep the workflow running and skip at job level, because a skipped job reports "Success".
6. The release PR's CI is held because it is created with `GITHUB_TOKEN`. GitHub documents two fixes: a GitHub App installation token or a personal access token. Release Please's own README says the same.

**B. Versioning before production**

1. Release Please finds the previous release by the manifest version, first through the Releases API and then by falling back to plain Git tags. Its intended flow is tag plus GitHub Release at release-PR merge; deployment follows the release. `skip-github-release` is documented as only for setups that already tag releases by other means.
2. `force-tag-creation` exists. It was added in release-please 17.2.0 (2026-01-20) for exactly this symptom: a release that exists as a draft without a Git tag makes the next release PR cover the whole history. The action pinned in this repository bundles release-please 16.18.0 and does not have it; `release-please-action` v4.4.1 and later do.
3. **Observed, new:** the pinned action SHA is `v4.2.0`, not `v4.1.3` as the workflow comment says. And the current design has a second stall beyond the missing tag: with `skip-github-release: true` nothing ever flips the merged release PR from `autorelease: pending` to `autorelease: tagged`. PR #65 (0.2.1) is still `pending` after promotion, and the last Release Please run aborted on it. The next releasable push will abort again until that label is changed by hand.
4. SemVer versions identify an immutable released artifact and its API compatibility, not a deployment. Staging iterations do not need version numbers. GitHub and Cloudflare both identify "what is running where" by deployment record, commit SHA, and Worker version ID.
5. Tagging at release-PR merge does not create more version numbers. The number is already consumed when the release PR merge writes it to `package.json` and the manifest. The count of versions is set by how often the release PR is merged, and by which commit types are releasable (here a lone `docs:` commit is).
6. **Inference:** the evidence favors tagging at release-PR merge and letting promotion publish the GitHub Release (Design A below). It removes both stalls, keeps "GitHub Release means accepted in production", and matches the tool's documented flow.

---

## A. PR for everything vs direct push to main

### A1. trunkbaseddevelopment.com

**Source** ([home page](https://trunkbaseddevelopment.com/)):

- "You can either do a direct to trunk commit/push (v small teams) or a Pull-Request workflow as long as those feature branches are short-lived and the product of a single dev-workstation."
- "Very small teams may commit direct to the trunk."
- "The dividing line between small team Trunk-Based Development and scaled Trunk-Based Development is a subject to team size and commit rate consideration. The precise moment a dev team is no longer 'small' and has transitioned to 'scaled' is subject to practitioner debate. Regardless, teams perform a full 'pre integrate' build (compile, unit tests, integration tests) on their dev workstations before committing/pushing for others (or bots) to see."

**Source** ([Committing straight to the trunk](https://trunkbaseddevelopment.com/committing-straight-to-the-trunk/)):

- "Some teams will choose to commit/push straight to the trunk. Most likely it is because they are a small team with each team member knowing what the others are up to. Their build is probably fast and relatively exhaustive, and they may well seldom experience a build breakage."
- "These days teams doing this practice without AI coding agents are likely to be much smaller (say less than 16)".
- On agents, the page has a section "AI coding agents committing straight to the trunk". It says agentic teams "need more: a commit queue, a fast local build with Test Impact Analysis, and agents that talk to each other before touching shared code", and that when the PR is removed "Review moves, it doesn't disappear": before the commit one agent reviews another's patch and "objective CI checks gate the queue"; after the commit "humans read what landed, at their own pace, and act on it with follow-up commits or reverts rather than approvals."
- "A lack of tests is the hole, and agents committing at" volume expose it.

**Source** ([Short-lived feature branches](https://trunkbaseddevelopment.com/short-lived-feature-branches/)):

- Branches "should only last a couple of days"; one developer per branch, and "With agentic coding: the unit is one developer and their coding agents."
- Team size cut-off for people-only teams: "is now up to 15 people. With 16 or more, the team is more productive with short-lived feature branches". The page adds that with agents these numbers no longer hold, because "people were a fair proxy for the rate of commits. They are not any more", and tells the reader to count concurrent writers (humans and agents).
- It notes that a pull request may be kept for "segregation-of-duties reasons, even when the integration itself could be direct", and that for small agent-heavy teams "committing straight to the trunk with a commit queue and AI-led review is the natural fit, as long as the tests" are in place.
- Agent sessions in worktrees are each a short-lived feature branch: "Keep each agent's change small, review and integrate them one at a time (re-syncing the others with main/trunk as each lands)".

**Inference.** By headcount this is a "very small team" where direct commits are in scope. By commit rate (several agents in parallel) the site's own agent sections say a queue plus independent review is needed before removing the PR. This repository has neither a commit queue nor AI-led review as a gate, so the site's condition for agents pushing directly is not met; its condition for the captain pushing directly (fast, exhaustive build, run before push, revert on break) can be.

### A2. DORA

**Source** ([Trunk-based development](https://dora.dev/capabilities/trunk-based-development/)):

- "In trunk-based development, developers push code directly into trunk."
- Teams perform better when they "Have three or fewer active branches in the application's code repository", "Merge branches to trunk at least once a day", and "Don't have code freezes and don't have integration phases."
- Listed pitfall, "An overly heavy code-review process": "Many organizations have a heavyweight code review process that requires multiple approvals before changes can be merged into trunk. When code review is laborious and takes hours or days, developers avoid working in small batches and instead batch up many changes."
- Listed pitfall, "Performing code reviews asynchronously": "If your team practices pair programming, then the code has already been reviewed by a second person. If further reviews are required, they should be performed synchronously".

**Source** ([Streamlining change approval](https://dora.dev/capabilities/streamlining-change-approval/)):

- "Traditionally, these goals have been met through a heavyweight process involving approval by people external to the team proposing the change: a change advisory board (CAB) or a senior manager. However, DORA's research shows that these approaches have a negative impact on software delivery performance. Further, no evidence was found to support the hypothesis that a more formal, external review process was associated with lower change fail rates."
- The recommended replacement is peer review at check-in time "supplemented by automation to detect, prevent, and correct bad changes early in the software delivery life cycle".
- Segregation of duties is described as a regulatory requirement: "changes must be approved by someone other than the author".

**Source** ([Continuous integration](https://dora.dev/capabilities/continuous-integration/)): "Each commit should trigger a build of the software", tests give feedback in a few minutes, and "An agreement that when the build breaks, fixing it should take priority over any other work." The page does not discuss code review.

**Inference.** DORA's evidence is against heavy approval, not against review. With one human there is no second approver, so a mandatory-approval rule cannot add independent review to the captain's own changes; it only adds latency. It does add independent review to agent changes, because the author (agent) and the approver (captain) differ.

### A3. Martin Fowler's site

**Source** ([Ship / Show / Ask, Rouan Wilsenach, 08 September 2021](https://martinfowler.com/articles/ship-show-ask.html)):

- Ship: "You want to make a change, so you make it directly on your mainline." Works great when: "I added a feature using an established pattern", "I fixed an unremarkable bug", "I updated documentation", "I improved my code based on your feedback".
- Show: "You make your change on a branch, you open a Pull Request, then you merge it without waiting for anyone. You'll want to wait for your automated checks (tests, code coverage, preview environments, etc.), but you don't wait for anyone's feedback".
- Ask: "We make our changes on a branch, we open a Pull Request, and we wait for feedback before merging."
- The rules: "Code review, or 'Approval', should not be a requirement for a Pull Request to be merged. People get to merge their own Pull Requests." Prerequisites: "all the great Continuous Integration and Continuous Delivery techniques that help keep the mainline releasable", and short-lived branches rebased often.
- "A junior engineer might often 'Show' and 'Ask'. A senior engineer might 'Ship' a lot".

**Source** ([Continuous Integration, Martin Fowler, revised 18 January 2024](https://martinfowler.com/articles/continuousIntegration.html)):

- "The pre-integration code review can be problematic for Continuous Integration because it usually adds significant friction to the integration process. Instead of an automated process that can be done within minutes, we have to find someone to do the code review, schedule their time, and wait for feedback".
- "The Ship / Show / Ask process encourages teams to use a blocking code review only when necessary, recognizing that post-integration review is often a better bet as it doesn't interfere with integration frequency."
- Practices: "Everyone Pushes Commits To the Mainline Every Day", "Every Push to Mainline Should Trigger a Build", "Fix Broken Builds Immediately". "The one prerequisite for a developer committing to the mainline is that they can correctly build their code."

**Inference.** The captain's eight direct docs commits are squarely "Ship" by this taxonomy, provided CI ran on each push (it does: `.github/workflows/ci.yml` triggers on every `push`). Ship / Show / Ask also maps cleanly onto trust level: the captain Ships or Shows; agents, as the less-trusted author, Ask.

### A4. GitHub plans, rulesets, bypass, merge queue

**Source: plan gating** (docs source, `data/reusables/gated-features/`; rendered at the top of [About protected branches](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches) and [About rulesets](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/about-rulesets)):

- Protected branches "are available in public repositories with GitHub Free and GitHub Free for organizations. Protected branches are also available in public and private repositories with GitHub Pro, GitHub Team, GitHub Enterprise Cloud, and GitHub Enterprise Server."
- "Rulesets are available in public repositories with GitHub Free and GitHub Free for organizations, and in public and private repositories with GitHub Pro, GitHub Team, and GitHub Enterprise Cloud." Push rulesets (file path or size restrictions) need GitHub Team.
- This matches the 403 "Upgrade to GitHub Pro or make this repository public" the repository returns today.

**Source: what a ruleset can require** ([Available rules for rulesets](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets)):

- Require a pull request before merging: "You can require that all changes to the target branch be associated with a pull request. The pull request doesn't necessarily have to be approved, but it must be opened." Sub-options include required approvals, dismissing stale approvals, approval of the most recent push by someone else, and "require a merge type of merge, squash, or rebase".
- Require status checks: "all required status checks must pass before collaborators can merge changes into the branch or tag", with strict (branch must be up to date) and loose variants.
- Require linear history: "prevents collaborators from pushing merge commits to the targeted branches or tags. This means that any pull requests merged into the branch or tag must use a squash merge or a rebase merge."
- Also: block force pushes, restrict deletions, require signed commits, require merge queue.

**Source: bypass** ([Creating rulesets for a repository](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/creating-rulesets-for-a-repository)):

- Eligible for bypass: "Repository admins, organization owners, and enterprise owners", "The maintain or write role, or custom repository roles based on the write role", teams, GitHub Apps, Dependabot.
- "Optionally, to grant bypass to an actor without allowing them to push directly to a repository, to the right of 'Always allow,' click ..., then click **For pull requests only**. The selected actor is now required to open a pull request to make changes to a repository, creating a clear trail of their changes in the pull request and audit log. The actor can then choose to bypass any branch protections and merge that pull request."
- For classic branch protection instead: "By default, the restrictions of a branch protection rule don't apply to people with admin permissions to the repository", unless "Do not allow bypassing the above settings" is enabled; and "Actors may only be added to bypass lists when the repository belongs to an organization." ([About protected branches](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches))

**Source: merge queue** ([Managing a merge queue](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/configuring-pull-request-merges/managing-a-merge-queue)): "Pull request merge queues are available in any public repository owned by an organization, or in private repositories owned by organizations using GitHub Enterprise Cloud." Personal-account repositories are not listed on any plan.

**Inference.**

- On Free and private, the policy can only be a convention plus CI on push. Upgrading the personal account to Pro unlocks rulesets; making the repository public also would, but that is a product decision outside this research.
- A Pro ruleset that fits the sources above: require a PR (0 approvals), require the CI status check, require linear history, block force pushes, with "Repository admin" on the bypass list. "Always allow" lets the captain Ship directly; "For pull requests only" forces even the captain through a PR while still allowing a self-merge. Agents get no bypass. This needs agents to act under an identity that is not a repository admin (a fine-grained PAT or GitHub App with contents and pull-request write only); if agents push with the captain's own credentials, an admin bypass applies to them too.
- Merge queue is not an option here without moving the repository to an organization (and, for private, Enterprise Cloud). The "strict" required status check (branch must be up to date) is the available substitute for serializing parallel agent PRs.

### A5. Path filters and required status checks

**Source** ([Workflow syntax, `on.<push|pull_request|pull_request_target>.<paths|paths-ignore>`](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#onpushpull_requestpull_request_targetpathspaths-ignore)): "If a workflow is skipped due to path filtering, branch filtering, or a commit message, then checks associated with that workflow will remain in a 'Pending' state. A pull request that requires those checks to be successful will be blocked from merging." Changed files are computed with "two-dot diffs for pushes and three-dot diffs for pull requests".

**Source** ([Troubleshooting required status checks, "Handling skipped but required checks"](https://docs.github.com/en/pull-requests/how-tos/merge-and-close-pull-requests/troubleshooting-required-status-checks)):

| Situation | Documented result | Documented advice |
| --- | --- | --- |
| Workflow skipped by path filtering, branch filtering, or commit message | "Associated checks stay in a 'Pending' state and block merging" | "Avoid requiring workflows that can be skipped." |
| Job skipped by a conditional | "The job reports 'Success'" | Use job conditions |
| Job depends on a failed job | "The dependent job is skipped and may not block merging" | "Use `always()` with `needs` for required checks that depend on other jobs." |

The same page adds: "You should not use path or branch filtering to skip workflow runs if the workflow is required to pass before merging", and the general note is "A job that is skipped will report its status as 'Success'. It will not prevent a pull request from merging, even if it is a required check."

**Inference: cheap CI for docs-only changes.** Do not add `paths-ignore` to `ci.yml`. Keep the workflow triggering on every push and PR, add a small first job that computes whether anything outside docs changed, and gate the expensive job with `if:`. For a required check, the safest shape is one always-running final job (for example `ci-result`, with `if: always()` and `needs:` on the others) that fails if any needed job failed and is the only required check; that covers both the "skipped reports Success" and the "dependent job skipped" rows. While the repository is on Free there are no required checks, so today `paths-ignore` would work, but it would have to be undone the day a ruleset is added. GitHub does not ship an official changed-files action; the detection step would be a `git diff --name-only` script (this repo already has `scripts/check_ci_diff.sh` reading the same before/after SHAs).

### A6. Why the release PR's CI does not really run

**Source** ([GITHUB_TOKEN, "When `GITHUB_TOKEN` triggers workflow runs"](https://docs.github.com/en/actions/concepts/security/github_token)):

- "When you use the repository's `GITHUB_TOKEN` to perform tasks, events triggered by the `GITHUB_TOKEN` will not create a new workflow run, with the following exceptions": `workflow_dispatch` and `repository_dispatch`, and "`pull_request` events with the `opened`, `synchronize`, or `reopened` activity types: when a workflow using `GITHUB_TOKEN` creates or updates a pull request, the resulting `pull_request` event creates workflow runs in an **approval-required** state. The pull request displays a banner in the merge box, and a user with write access to the repository can start the runs by selecting **Approve workflows to run**."
- "For example, if a workflow run pushes code using the repository's `GITHUB_TOKEN`, a new workflow will not run even when the repository contains a workflow configured to run when `push` events occur."
- "If you need workflow runs from workflow-created pull requests to execute without requiring approval, use a GitHub App installation access token or a personal access token instead of `GITHUB_TOKEN` when creating or updating the pull request."

**Source** ([release-please-action README, "Other Actions on Release Please PRs"](https://github.com/googleapis/release-please-action/blob/0b6b3fc0186a2f7118bfd88fab9ea481e1839504/README.md#other-actions-on-release-please-prs)): "all resources created by `release-please` (release tag or release pull request) will not trigger future GitHub actions workflows, and workflows normally triggered by `release.created` events will also not run." and "You will want to configure a GitHub Actions secret with a Personal Access Token if you want GitHub Actions CI checks to run on Release Please PRs." The action takes it through its `token` input.

**Inference.** This matches `docs/CI-CD.md` step 3 (runs are created but held for approval). The release branch push itself produces no `push` run, so the PR-event run is the only CI signal and it waits for a click. Options, in order of robustness: (1) a GitHub App installation token passed as `token:` (scoped to this repository, not tied to a person, short-lived); (2) a fine-grained PAT with contents and pull-requests write (simplest, but a long-lived personal credential that expires); (3) keep `GITHUB_TOKEN` and click "Approve workflows to run" each time. A side effect of (1) and (2): tags and releases created with that token also start triggering workflows, which matters if a deploy is ever hung off a tag or release event.

### A7. First-party guidance on AI coding agents and PRs

**Source: Anthropic** ([Claude Code best practices](https://code.claude.com/docs/en/best-practices)):

- In the table contrasting what Claude decides with what is enforced, the row "Who has the last word" reads: non-deterministic "Claude's summary of what it did"; deterministic "Branch protection, a person who approves the merge".
- For unattended runs, question 3: "What's it allowed to touch? Permission rules, `dontAsk`, the sandbox, a worktree, the one branch it may push to." Question 5: "Where does the result go, and who signs off? A PR, a comment, or a summary, and then a person approving the merge, the deploy, or anything else you can't take back."
- "Before you leave a cloud scheduled task running, protect `main` with a GitHub branch rule the task can't bypass."
- Parallel sessions: "give each its own checkout so the edits can't collide", and "A second session is also the easiest independent reviewer you can get."

**Source: Anthropic** ([Scheduled tasks, repositories and branch permissions](https://code.claude.com/docs/en/routines#repositories-and-branch-permissions)): "Claude pushes its work to a branch prefixed with `claude/` unless your prompt directs it to push to another branch. To control which branches a run can push to, use branch protection rules or rulesets on GitHub. ... GitHub applies them to the GitHub access you connected, so a rule that access can bypass doesn't block a run's push."

**Source: GitHub** ([Risks and mitigations for Copilot cloud agent](https://docs.github.com/en/copilot/concepts/security-governance-and-network-settings/risks-and-mitigations)): the agent "only has the ability to push to a single branch" (a new `copilot/` branch), "Draft pull requests created by Copilot cloud agent must be reviewed and merged by a human", it "cannot approve or merge a pull request", and "By default, workflows are not triggered until Copilot cloud agent's code is reviewed and a user with write access to the repository clicks the **Approve and run workflows** button."

**Inference.** Both vendors design agent work as: own branch, PR, human merges. Neither says a human's own low-risk change needs the same. The second Anthropic quote is the practical catch for a solo owner: a rule the agent's credentials can bypass is not a control, which is the same point as the bypass-identity note in A4.

### A-conclusion (inference)

A two-lane policy is consistent with every source above:

| Lane | Who | Which changes | Mechanism |
| --- | --- | --- | --- |
| Ship | Captain only | Docs, comments, config with no runtime effect, unremarkable fixes following an established pattern | Direct push to `main`; CI runs on the push; revert on red |
| Show | Captain | Anything the captain wants a record or a preview of | PR, merge when CI is green, no waiting |
| Ask | Agents (`fm/*`), always; captain when unsure | Features, behavior changes, migrations, workflow and release config | PR, captain reviews and merges |

"A PR for every change" is not what these sources describe as modern practice; "every change is integrated quickly, verified automatically, and reviewed by someone other than its author somewhere" is. Until the plan changes this is a convention, so it belongs in the agent instructions rather than being assumed enforced.

---

## B. Versioning before production with Release Please

### B1. How Release Please finds the previous release, and what the options do

**Source: boundary lookup** ([`src/manifest.ts` L545-L616](https://github.com/googleapis/release-please/blob/ea20bc261acd75149f0be90890bb9c90e681eea7/src/manifest.ts#L545-L616), [`backfillReleasesFromTags` L852-L912](https://github.com/googleapis/release-please/blob/ea20bc261acd75149f0be90890bb9c90e681eea7/src/manifest.ts#L852-L912)):

1. It iterates GitHub Releases (`this.github.releaseIterator`), parses each release's tag name, and accepts the one whose version equals the manifest's version for that path (`expectedVersion.toString() === tagName.version.toString()`).
2. If fewer releases than paths were found, it logs `Expected N releases, only found M` and calls `backfillReleasesFromTags`, which builds the expected tag name from the manifest version (`includeVInTag`, component, separator) and looks it up in all Git tags (`this.github.tagIterator()`).
3. If neither exists, the path needs bootstrap and the commit walk has no stopping point.

So `docs/CI-CD.md` is right that a plain tag is enough. The same fallback exists in 16.18.0, the version this repository actually runs (`git show v16.18.0:src/manifest.ts`, lines 587 and 831).

**Source: the merged-pending guard** ([`createPullRequests`, L925-L941](https://github.com/googleapis/release-please/blob/ea20bc261acd75149f0be90890bb9c90e681eea7/src/manifest.ts#L925-L941)): before opening any release PR it looks for merged PRs that still carry the pending label and, if it finds one, logs "There are untagged, merged release PRs outstanding - aborting" and returns. The label is flipped only inside `createReleases` ([L1305-L1322](https://github.com/googleapis/release-please/blob/ea20bc261acd75149f0be90890bb9c90e681eea7/src/manifest.ts#L1305-L1322): `removeIssueLabels(this.labels)` then `addIssueLabels(this.releaseLabels)`), and the action calls `createReleases` only when `skip-github-release` is not set ([`release-please-action` `src/index.ts` L141-L151](https://github.com/googleapis/release-please-action/blob/0b6b3fc0186a2f7118bfd88fab9ea481e1839504/src/index.ts#L141-L151)).

**Observed in this repository (2026-11-15):**

- PR #52 (0.2.0) carries `autorelease: tagged` only because the captain relabelled it by hand on 2026-11-14 (issue events: `unlabeled autorelease: pending` then `labeled autorelease: tagged`, both by the owner).
- PR #65 (0.2.1) is merged and still `autorelease: pending`, although `v0.2.1` now exists.
- The most recent Release Please run (run 43612540894, on `cc19421`, started 15:52 UTC, five minutes before promotion created `v0.2.1`) ended with `Found pull request #65` and `There are untagged, merged release PRs outstanding - aborting`.
- **Inference:** creating `v0.2.1` fixed the boundary but not this guard. The next push with a releasable commit will abort the same way until PR #65 is relabelled `autorelease: tagged`. `docs/CI-CD.md` currently says the labels do not restore the boundary, which is true, but they are a separate blocker that promotion does not clear. In the current design this manual relabel is needed after every release.

**Source: options** ([`docs/manifest-releaser.md`](https://github.com/googleapis/release-please/blob/ea20bc261acd75149f0be90890bb9c90e681eea7/docs/manifest-releaser.md), [`docs/customizing.md`](https://github.com/googleapis/release-please/blob/ea20bc261acd75149f0be90890bb9c90e681eea7/docs/customizing.md#versioning-strategies), [`schemas/config.json`](https://github.com/googleapis/release-please/blob/ea20bc261acd75149f0be90890bb9c90e681eea7/schemas/config.json)):

| Option | What the source says |
| --- | --- |
| `skip-github-release` | "Skip creating GitHub Releases. Absence defaults to false and Releases will be created. Release-Please still requires releases to be tagged, so this option should only be used if you have existing infrastructure to tag these releases." Action README: "If `true`, do not attempt to create releases. This is useful if splitting release tagging from PR creation." |
| `draft` | "when `manifest-release` creates GitHub Releases per package, create those as 'Draft' releases (which can later be manually published)." CLI help adds: "no tag is created but tag_name and target_commitish are associated with the release for future tag creation upon 'un-drafting' the release." |
| `force-tag-creation` | "Force the creation of a Git tag for the release. This is particularly useful when `draft` is enabled. By default, GitHub does not create a Git tag for draft releases until they are published. This 'lazy tag creation' behavior causes release-please to fail to find the previous release when running subsequent `release-pr` commands, potentially generating incorrect changelogs that include the entire commit history. Setting `force-tag-creation` to true ensures the tag is created immediately, allowing release-please to correctly identify the previous release. Absence defaults to false." |
| `prerelease` | Creates the GitHub Release as a "Prerelease" when the version is pre-major or has a prerelease part. "Works together with the 'prerelease' versioning strategy, which creates a prerelease-version (like 1.0.0-alpha.1) only if this setting is set to true." In code: `config.prerelease && (!!release.tag.version.preRelease \|\| release.tag.version.major === 0)`. |
| `prerelease-type` | "setting the type of prerelease in case of prerelease strategy" (for example `beta`). |
| `versioning` | Strategies in `src/versioning-strategies/`: `default`, `always-bump-patch`, `always-bump-minor`, `always-bump-major`, `service-pack`, `prerelease`, plus Java snapshot and dependency-manifest variants. `prerelease`: "Bumping prerelease number (eg. 1.2.0-beta01 to 1.2.0-beta02) or if prerelease type is set, using that in the prerelease part (eg. 1.2.1 to 1.3.0-beta)." |
| `last-release-sha` | "you can manually set the commit sha release-please will use from which to gather commits for the current release. This can be useful when you've accidentally merged a bad release PR." Top-level only, "never ignored: remove/change it once a good release PR is merged". |

**Source: `force-tag-creation` provenance.**

- It exists. Added in release-please **17.2.0 (2026-01-20)**: "add --force-tag option to explicitly create git tags for releases. (#2627)" ([CHANGELOG](https://github.com/googleapis/release-please/blob/ea20bc261acd75149f0be90890bb9c90e681eea7/CHANGELOG.md), [PR #2627](https://github.com/googleapis/release-please/pull/2627), which closes [issue #1650 "Using `draft: true` causes `release-pr` to fail to find the previous release"](https://github.com/googleapis/release-please/issues/1650)).
- Implementation ([`src/github-api.ts` L676-L708](https://github.com/googleapis/release-please/blob/ea20bc261acd75149f0be90890bb9c90e681eea7/src/github-api.ts#L676-L708)): when `forceTag` is set, `createRelease` first calls `git.createRef` for `refs/tags/<tag>` at the release SHA (a lightweight tag; a 422 "already exists" is ignored), then creates the release with `draft` and `prerelease` as configured.
- Availability in the action, measured from each tag's `package-lock.json` and `dist/index.js`: `v4.2.0` bundles 16.18.0 (absent); `v4.4.0` bundles 17.1.3 (absent); **`v4.4.1` bundles 17.3.0 (present)**; `v5.0.0` bundles 17.6.0 (present, and moves to the node24 runtime). The option is read from the config file, not from an action input.
- **Observed:** this repository's workflow pins `a02a34c4d625f9be7cb89156071d8567266a2445` with the comment `# v4.1.3`. `git ls-remote --tags` shows that SHA is `v4.2.0`; `v4.1.3` is `7987652d64b4581673a76e33ad5e98e3dd56832f`. The run log also warns that the action targets the deprecated Node.js 20.

**Source: what maintainers say about "merged but not yet released".** I found no maintainer document that describes a deploy-then-tag flow. What exists:

- The `skip-github-release` doc line quoted above, which makes tagging by other infrastructure a precondition.
- In issue #1650, contributors `cdata` and `plaflamme` agree "the tag should be created even if the release is marked as a draft"; maintainer `chingor13` earlier said the draft feature "was community contributed and this needs a design". The eventual resolution is `force-tag-creation`.
- The README troubleshooting steps tell users to remove a stale `autorelease: pending` label and re-run when a release PR is not appearing ([README, "Release Please bot does not create a release PR. Why?"](https://github.com/googleapis/release-please/blob/ea20bc261acd75149f0be90890bb9c90e681eea7/README.md)).

### B2. The intended Release Please flow

**Source** ([release-please README](https://github.com/googleapis/release-please/blob/ea20bc261acd75149f0be90890bb9c90e681eea7/README.md)):

- "These Release PRs are kept up-to-date as additional work is merged. When you're ready to tag a release, simply merge the release PR."
- "When the Release PR is merged, release-please takes the following steps: 1. Updates your changelog file ... 2. Tags the commit with the version number 3. Creates a GitHub Release based on the tag".
- Labels: "`autorelease: pending` is the initial state of the Release PR before it is merged", "`autorelease: tagged` means that the Release PR has been merged and the release has been tagged in GitHub", and "`autorelease: published` means that a GitHub release has been published based on the Release PR (_release-please does not automatically add this tag, but we recommend it as a convention for publication tooling_)."

**Source** ([`docs/design.md`](https://github.com/googleapis/release-please/blob/ea20bc261acd75149f0be90890bb9c90e681eea7/docs/design.md)): a component "could be a library to publish to a package manager or an application that is deployed to a server", and the lifecycle is: commit lands, release PR opens, "A maintainer reviews/merges the release pull request", then "`release-please` creates a new GitHub release".

**Source** ([action README, "Automating publication to npm"](https://github.com/googleapis/release-please-action/blob/0b6b3fc0186a2f7118bfd88fab9ea481e1839504/README.md#automating-publication-to-npm)): the documented way to act on a release is in the same workflow, gated on `steps.release.outputs.release_created`, after the tag and release exist.

**Inference.** In the tool's model, merging the release PR is the release decision; tag and release are created then, and publication or deployment follows. The `autorelease: published` convention shows the maintainers do distinguish "tagged" from "published" and expect downstream tooling to mark the second step. This repository's design inverts the order (deploy, then tag), which is why it keeps hitting guards that assume the tag appears at merge.

### B3. SemVer: what a version identifies

**Source** ([semver.org 2.0.0](https://semver.org/)):

- Item 3: "Once a versioned package has been released, the contents of that version MUST NOT be modified. Any modifications MUST be released as a new version."
- Item 9: "A pre-release version MAY be denoted by appending a hyphen and a series of dot separated identifiers immediately following the patch version. ... Pre-release versions have a lower precedence than the associated normal version. A pre-release version indicates that the version is unstable and might not satisfy the intended compatibility requirements as denoted by its associated normal version."
- Item 10: "Build metadata MAY be denoted by appending a plus sign and a series of dot separated identifiers immediately following the patch or pre-release version. ... Build metadata MUST be ignored when determining version precedence. Thus two versions that differ only in the build metadata, have the same precedence."
- Item 1: "Software using Semantic Versioning MUST declare a public API."
- FAQ, on a mistaken release: "it is unacceptable to modify versioned releases."

**Inference.**

- SemVer speaks only about a versioned, released package and its API contract. It has no concept of environment or deployment. "Which commit is on staging" is outside what a SemVer number is for.
- The current tag `candidate-v0.2.0-<sha12>` is not a SemVer string, which is fine: it is a deployment record. If a SemVer-shaped identifier for a candidate were ever wanted, build metadata is the fitting slot (`0.2.0+sha.25ad42053ce1`): same precedence as `0.2.0`, carries the commit. A pre-release (`0.2.0-rc.1`) would be the wrong slot unless candidates are really published for others to consume, because it asserts a distinct, lower-precedence version.
- Item 3 bears on a real case here: `candidate-v0.2.0-01e9bd58fa92` and `candidate-v0.2.0-25ad42053ce1` are two different commits both carrying `package.json` version 0.2.0. Because nothing had been released as 0.2.0 yet, SemVer was not violated, but the number alone did not identify the content. Under tag-at-merge, the fix after a failed candidate becomes 0.2.1 and each version maps to exactly one commit.
- A "skipped" version (tagged, never promoted) costs nothing in SemVer terms; the spec constrains ordering and immutability, not density.

### B4. Identifying what runs in staging and production

**Source: GitHub** ([Deployment environments](https://docs.github.com/en/actions/concepts/workflows-and-actions/deployment-environments), [Viewing deployment history](https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/view-deployment-history)): "When a workflow references an environment, the environment will appear in the repository's deployments." The deployments page shows "Currently active deployments across various environments", the "Associated commits that triggered the deployment", the deployment URL, and workflow logs. GitHub's own record of what is in an environment is therefore a deployment object keyed by commit SHA and ref, not a version number.

**Source: GitHub plan gating for environments** (`data/reusables/gated-features/environments.md`, rendered on the environments pages): "For access to environments, environment secrets, and deployment branches in private or internal repositories, you must use GitHub Pro, GitHub Team, or GitHub Enterprise." and on Free, Pro, or Team "other deployment protection rules, such as a wait timer or required reviewers, are only available for public repositories."

**Observed:** this private Free repository nevertheless has `staging` and `prod` environments with `branch_policy` protection rules and deployment records (`gh api repos/.../environments`, `.../deployments`). I could not reconcile this with the gating sentence; see "Unverified".

**Observed:** the deployment records are `prod` at ref `candidate-v0.2.1-cc19421aa597`, and `staging` at ref `main`. For Candidate deploy the record's SHA is the workflow's `GITHUB_SHA` (the head of `main` at dispatch), not `inputs.commit`. They matched on both runs so far only because the requested commit was the head. The candidate tag message has the same issue: `git tag --annotate ... --message "Staging candidate for ${GITHUB_SHA}"` in `.github/workflows/candidate-deploy.yml` names the dispatch SHA, not the checked-out commit. Deploying an older `main` commit to staging would make both the GitHub deployment record and the tag message name the wrong commit (the tag itself would still point at the right one).

**Source: Cloudflare** ([Versions and deployments](https://developers.cloudflare.com/workers/configuration/versions-and-deployments/), [Rollbacks](https://developers.cloudflare.com/workers/configuration/versions-and-deployments/rollbacks/), [Gradual deployments](https://developers.cloudflare.com/workers/configuration/versions-and-deployments/gradual-deployments/), [Version metadata binding](https://developers.cloudflare.com/workers/runtime-apis/bindings/version-metadata/), [Wrangler commands](https://developers.cloudflare.com/workers/wrangler/commands/workers/)):

- A version is the Worker's code and configuration at a point in time, with a unique ID; "A deployment determines which version(s) of your Worker are actively serving traffic." With `wrangler deploy`, "Workers creates a version and sets its deployment to 100% of traffic."
- "You can optionally attach a message and tag to a version when you upload it." `wrangler deploy --tag`: "A tag for this Worker version"; `--message`: "A descriptive message for this Worker version and deployment."
- The version metadata binding exposes "Worker version ID, version tag and timestamp of when the version was created", intended for "downstream observability systems".
- Rollback: "A rollback creates a new deployment set to 100% of traffic for the selected version." "Resources connected to your Worker will not be changed during a rollback." "You can only roll back to the 100 most recently published versions." Rollback is blocked across a Durable Object class lifecycle change. State in KV, R2, Durable Objects, and D1 is not tracked with versions.
- Gradual deployments split traffic between two versions by percentage using `wrangler versions upload` and `wrangler versions deploy`; "Use wrangler deploy to apply a pending Durable Object migration."

**Inference.** Both platforms answer "what is running there" with a deployment record that points at an immutable build: GitHub by commit SHA, Cloudflare by version ID. Neither needs a SemVer number, and Cloudflare's version tag is a free-form label. The cheap way to tie the three together is to pass the commit to Cloudflare at deploy time, for example `--tag "$(git rev-parse --short=12 HEAD)" --message "vX.Y.Z"`, and optionally expose it through the version metadata binding. Then staging is identified by SHA everywhere, and the SemVer number stays a property of the release. I did not verify that `pywrangler deploy` forwards `--tag` and `--message` unchanged.

### B5. Would tagging at release-PR merge pile up version numbers?

**Inference from B1-B3:** no.

- The version number is minted when the release PR merges: that commit writes `package.json`, `CHANGELOG.md`, and the manifest. This happens today regardless of tagging. A tag only makes the already-minted number visible to Git and to Release Please.
- Release Please does not create a version per commit. The release PR accumulates commits ("kept up-to-date as additional work is merged") and one version is minted per merge of that PR. The captain controls the cadence by choosing when to merge it.
- What does inflate numbers in this repository is configuration, not tagging: `docs` has a visible changelog section, so a lone `docs:` commit opens a release PR (recorded in `docs/CI-CD.md`). Hiding the `docs` section, or simply not merging a docs-only release PR until a `feat` or `fix` joins it, controls that.
- The one case where tag-at-merge adds a number is a candidate that fails on staging: the fix ships as the next patch instead of reusing the number. By SemVer item 3 that is the more correct outcome, and the gap in published releases is harmless.

### B6. Three comparable designs

Common to all three: `main` is the only branch, Candidate deploy and Promote stay manual, staging iterations are identified by commit SHA, and the GitHub Release remains the statement "accepted in production".

**Design A - tag at release-PR merge, promote publishes the Release.**

- Release Please runs without `skip-github-release`, with `"draft": true` and `"force-tag-creation": true` in the config. At release-PR merge it creates the `vX.Y.Z` tag and a draft GitHub Release with the changelog notes, and flips the PR to `autorelease: tagged`.
- Candidate deploy takes the tagged commit (or any `main` commit, as now). Promote deploys to production and then publishes the draft (`gh release edit vX.Y.Z --draft=false`) instead of creating tag and release.
- What the sources imply: this is the documented flow (B2) with the documented remedy for the tag gap (B1). Both stalls disappear because the boundary tag and the label flip happen at merge, by the tool. Release notes come from `CHANGELOG.md` rather than `--generate-notes`. A version that fails staging stays as a tag with an unpublished draft; the fix is the next patch (B3, B5).
- Costs and risks: requires `release-please-action` v4.4.1 or later (v5.0.0 also clears the Node 20 deprecation). The `vX.Y.Z` tag no longer means "in production"; the published Release does. The `prod` environment policy and Promote's tag checks need to change if promotion starts from `vX.Y.Z` instead of `candidate-v*`. Draft releases are visible only to people with write access, which is the desired property here. Not tested in this repository.

**Design A' - same boundary, no draft: a plain tag at merge, promote creates the Release.**

- Keep `skip-github-release: true`. Add the "existing infrastructure to tag" that its documentation requires: a step after Release Please (or in Candidate deploy) that creates `vX.Y.Z` when the manifest version has no tag, and relabels the merged release PR `autorelease: tagged`. Promote keeps creating the GitHub Release, and stops creating the tag.
- What the sources imply: satisfies the documented precondition of `skip-github-release`, works on the currently pinned 16.18.0 (tag fallback, B1), and keeps "no Release object exists until production". But it re-implements by hand two things `createReleases` already does (tag and label), which is the kind of custom machinery that drifts from upstream. Promote's current "skip release if tag exists" logic would have to change to "skip if release exists".

**Design B - keep tag-at-promote (current).**

- What the sources imply: it runs against the documented contract of `skip-github-release` for the whole window between merge and promotion, and needs three compensations: `npm run check:release`, the rule "a merged release PR must be promoted", and a manual `autorelease: tagged` relabel after every promotion (currently undocumented and pending for PR #65). It also allows one version number to cover several commits before release (0.2.0 did).
- Its one advantage: `vX.Y.Z` in Git strictly means "was promoted to production". Design A keeps that meaning on the published Release instead.

**Design C - no version until production, SHA-only candidates.**

- Drop the release PR as a gate: candidates are plain `main` commits identified by SHA; the version and changelog are produced at or after promotion.
- What the sources imply: closest to B4 (deployments are identified by SHA) and to continuous delivery as DORA and Fowler describe it. But Release Please is built around a release PR that writes the version into the tree before tagging (B2), so the production commit would not contain its own version unless a version-bump commit is promoted without having been the tested candidate, or the tool is replaced. It is a larger change than the problem warrants.

| | A: tag at merge, draft Release | A': plain tag at merge | B: tag at promote (current) | C: SHA-only until production |
| --- | --- | --- | --- | --- |
| Changelog boundary always present | Yes | Yes | No, gap until promotion | Depends on replacement tooling |
| `autorelease` label handled by the tool | Yes | No, scripted | No, manual | Not applicable |
| Matches Release Please documented flow | Yes | Partly | No | No |
| One version = one commit | Yes | Yes | Not before promotion | Yes |
| "Release" means production-accepted | Published Release | Release | Tag and Release | Tag and Release |
| Custom machinery to maintain | Least | Tag and label step | `check:release`, manual relabel | Most |
| Required upgrade | Action v4.4.1+ | None | None | New release tooling |

### B-conclusion (inference)

For a solo captain with parallel agents, the evidence favors **Design A**. The deciding points: the tool's source assumes the tag appears at merge and enforces that assumption in two places (B1); `force-tag-creation` was added upstream for this exact failure; and staging does not need a version at all (B3, B4), so there is no reason to withhold the tag to keep staging "unversioned". With agents merging PRs in parallel, a release pipeline that stalls silently until a human relabels a PR is the more expensive failure than a version tag that precedes production by a few hours. Design A' is the fallback if the action upgrade or draft behavior turns out to be a problem.

Independent of the design chosen, three things observed here need attention: PR #65 still carries `autorelease: pending`; the action pin comment says `v4.1.3` while the SHA is `v4.2.0`; and Candidate deploy records `GITHUB_SHA` rather than the deployed commit in its tag message and GitHub deployment record.

---

## Unverified / could not confirm

- **Environments on a private Free repository.** The docs say environments, environment secrets, and deployment branch policies in private repositories need Pro, Team, or Enterprise. This repository has both environments with branch policies and successful deployments. I did not determine whether the docs are stale, whether the policies are actually enforced on Free, or whether the account has a different entitlement.
- **Bypass list on a personal-account repository.** The ruleset docs list "Repository admins" as eligible for bypass and describe "For pull requests only", but do not state separately what the bypass picker offers for a repository owned by a personal account (which has no teams or custom roles). Classic branch protection explicitly limits bypass lists to organization repositories; I found no equivalent sentence for rulesets and could not test it (the API returns 403 on this plan).
- **Direct push under a required-status-check rule.** The docs say required checks must pass "before collaborators can make changes to a branch". I did not find a first-party statement on whether a commit that already has a green check from another branch can then be pushed straight to the protected branch without a PR, so I did not rely on it.
- **Design A end to end.** `draft: true` with `force-tag-creation: true` was verified by reading source and docs only, not by running it. In particular I did not verify that publishing the draft later behaves cleanly with the pre-existing lightweight tag, or how it interacts with GitHub's immutable releases feature mentioned in issue #1650.
- **Whether draft releases are returned to `releaseIterator`.** Not checked; Design A does not depend on it because the tag fallback covers it.
- **Maintainer recommendation for deploy-before-tag.** I found no release-please maintainer document or issue comment that endorses or describes tagging after deployment. The absence is from the docs directory, README, and issue #1650 at the pinned commit; I did not read the full issue tracker.
- **`pywrangler` flag passthrough.** `--tag` and `--message` are documented for `wrangler deploy`; I did not verify that `python -m pywrangler deploy` forwards them.
- **Quotes from trunkbaseddevelopment.com agent sections.** These were read from the live pages on 2026-11-15. The site is edited continuously and has no version identifier, so the wording may change.
- **DORA primary data.** The DORA capability pages state the findings but do not link the specific report year on the page; I cited the capability pages, not the underlying State of DevOps reports.
- **Cloudflare version metadata and tag details.** The exact field names and the gradual-deployment limits were taken from page summaries, not checked against Wrangler source.
