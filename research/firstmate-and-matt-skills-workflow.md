# firstmate and Matt Pocock's skills: who owns which phase

Research completed 2026-11-18. Question: can firstmate (`kunchenguid/firstmate`) do the implementation for work that was defined with Matt Pocock's skills (`grilling` -> `to-spec` -> `to-tickets`), and where do the two workflows conflict? Primary sources only: the firstmate distro at a pinned commit, the installed Matt skill files, this repository's tracker docs and GitHub labels, and the local firstmate home's private preference file. Claims are labelled **Source** (what a file says), **Observed** (checked locally on 2026-11-18), or **Inference** (my reasoning). This is supporting evidence, not implementation authority.

| Source | Revision |
| --- | --- |
| `kunchenguid/firstmate` clone at `~/projects/firstmate` | `427056c4181c41074ad24f051f79919330df0fa5` (2026-11-12) |
| `mattpocock/skills` installed under `~/.agents/skills/` | `implement-spec` and `grilling` at commit `5863806d`; `to-spec` installed 2026-09-22, `to-tickets` and `implement` updated 2026-11-07 (from `~/.agents/.skill-lock.json`) |

**Decision recorded after this research (captain, 2026-11-18):** Option A. Grilling, spec, tickets and implementation all run in this repo's own session; firstmate is used for exploration only. The `status:*` labels below were retired in favor of the state labels in `docs/agents/issue-tracker.md`, so section 5's `status:ready-to-build` row now reads `ready-for-agent`.

**Observed:** the firstmate clone is current. Local `HEAD`, `origin/main`, and `git ls-remote origin refs/heads/main` all return `427056c`, and `git fetch --dry-run` reports nothing to fetch.

## Short answer

1. **Yes, firstmate implements.** Its main task shape, "ship", produces a PR from an isolated worktree, and it has already shipped ticket work for this repo (for example the Issue #20 hospital reader).
2. **firstmate does not know about Matt's skills.** No firstmate file mentions `grilling`, `to-spec`, `to-tickets`, `implement`, `ready-for-agent`, or the `status:*` labels. Any combination is your own convention, not a documented integration.
3. **The handoff point is plain:** an approved GitHub issue (output of `to-tickets`) becomes a firstmate ship request ("implement issue #N"). firstmate then owns the worktree, the `no-mistakes` pipeline, and the PR. You still own the merge.
4. **One blocker is your own rule, not firstmate's.** Your private firstmate preferences currently say "Firstmate does not build those tickets" for work defined with Matt's skills. Change that rule before you use firstmate for this.
5. **Do not run `/implement-spec` inside firstmate.** Both are orchestrators: each wants its own worktrees, branches, and review step. Pick one per spec.

## 1. firstmate's intended workflow

- **Source:** "You talk to a single agent - the first mate - and it runs the crew for you: spawning autonomous agents in a visible session backend, giving each a clean git worktree, supervising them to completion, and handing you finished PRs, approved local merges, or standalone investigation reports." (`firstmate/README.md:33`)
- **Source:** two task shapes: "ship tasks deliver authorized changes; scout tasks leave standalone investigation reports" (`README.md:47`). In `AGENTS.md:185-186`, "Ship is the default and produces a project change through the selected delivery mode". Scout covers "investigation, diagnosis, planning, reproduction, or audit work" and "never a PR".
- **Source:** the first mate itself never writes code. It delegates "coding, investigation, planning, bug reproduction, and audits to a crewmate" (`AGENTS.md:23`), and "Never write to a project" is hard rule 1 (`AGENTS.md:28-29`). VISION puts it this way: "even the smallest change is a worker's job" (`VISION.md:25`).
- **Source:** delivery modes per project: `no-mistakes`, `direct-PR`, `local-only` (`.agents/skills/project-management/SKILL.md:40-43`). The brief generator spells out the no-mistakes path as "implement -> /no-mistakes pipeline -> PR -> configured merge authority" (`bin/fm-brief.sh:44`). "When no-mistakes is selected, no-mistakes alone owns review, fixes, tests, documentation, push, PR, and CI" (`AGENTS.md:230`).
- **Source:** merge needs the captain's explicit word unless the project has `+yolo` (`AGENTS.md:33-34`, `AGENTS.md:241`).
- **Source:** planning happens only as a scout or as firstmate's own intake. firstmate has no spec or ticket-writing phase. Before dispatch it writes a per-task brief with `## Captain's intent` (the captain's ask, which the reviewer treats as acceptance criteria) and `## Firstmate spec` (build instructions only) (`AGENTS.md:391-392`, `bin/fm-brief.sh:4-16`).
- **Source:** a scout report "may recommend implementation but does not authorize it". Promotion to a ship needs separate authorization (`.agents/skills/scout-completion/SKILL.md:12-15`).
- **Source:** scope boundary: "firstmate is the command layer, not the workshop: validation belongs to no-mistakes, CI belongs to the forge, and merge policy belongs to the configured authority." (`VISION.md:71`)
- **Observed:** firstmate has already shipped ticket implementation for this repo. The brief `firstmate/data/next-is-you-issue20-ntuh-reader-20261022/brief.md` starts "Implement GitHub Issue #20 in KLTsai/next-is-you" and tells the worker to "Read the full Issue #20 body and its acceptance criteria first; they are authoritative for scope."

## 2. How firstmate tracks work: its own backlog, not GitHub labels

- **Source:** the durable queue is the `tasks-axi` backlog, by default `data/backlog.md` (`AGENTS.md:369`, `.tasks.toml`). The markdown adapter has `## In flight`, `## Queued`, and `## Done` sections (`docs/configuration.md:537`). "It tracks work items only, never agents" (`AGENTS.md:370`).
- **Source:** a decision is "a task held for the captain" through `bin/fm-captain-hold.sh hold` (`AGENTS.md:372`). A hold row carries `--kind captain` metadata (`docs/configuration.md:485`). "captain" is a hold kind, not a GitHub label (`docs/configuration.md:488`).
- **Source:** dispatch is gated on the backlog. The spawn "moves the work item to In flight and refuses rather than dispatching work this home has no item for" (`AGENTS.md:213`). It also refuses a "held, or dependency-blocked item" (`docs/configuration.md:494`). Teardown moves the item to Done (`AGENTS.md:375`).
- **Source:** for upstream issues, "put its canonical issue URL on the structured backlog row" (`.agents/skills/bearings/SKILL.md:204`). The surrounding section is about contribution follow-up.
- **Observed:** `git grep` over the whole firstmate repo finds no `status:ready-to-build`, `status:needs-captain-decision`, `status:done`, `ready-for-agent`, or any `gh issue create`/`--label` use in `bin/` or `.agents/`. firstmate does not create GitHub issues or manage GitHub labels.
- **Observed:** the `status:*` and `area:*` labels exist only in this repository's GitHub label list (`gh label list -R KLTsai/next-is-you`). No file in this repo documents them (`git grep` finds nothing). Their only written convention is your private firstmate preference file: "GitHub issues are the single record of what remains ... Keep labels in step when an investigation changes an issue's state, and never keep a parallel status in firstmate data for repo work." (`firstmate/data/captain.md:13`, local and gitignored)
- **Observed:** current label use (`gh issue list --state all`). Open issues carry only `status:*` and `area:*`. 25 closed issues still carry Matt's `ready-for-agent`. Some closed issues have `status:done` and others have no status label.

## 3. Integration with Matt's skills and the handoff point

- **Observed:** firstmate documents no integration with Matt's skills (see the grep above). Its only skill knowledge is how to send a harness skill command to a worker, such as `/<skill>` on Claude (`.agents/skills/harness-adapters/references/harness/claude.md:14`, `references/common/control-and-recovery.md:28`).
- **Source:** there is no "intake hook" that reads a spec. The intake is the captain's chat request. firstmate resolves the project, classifies ship or scout, resolves the delivery mode, files a backlog item, writes the brief, and spawns (`AGENTS.md:169-206`). So the handoff is a chat request that names the issue. The issue body becomes the authoritative scope through the brief, as in the Issue #20 brief above.
- **Source:** the standing-rules config point is `config/brief-include.md`. It "adds standing worker instructions to every ship and scout brief", appended as `# Home brief additions`, and every other brief section wins over it (`docs/configuration.md:1827-1834`). Use it for rules such as "read the issue with `gh-axi issue view --comments --full`, tick acceptance boxes with evidence, put `Closes #N` in the PR body". **Observed:** this home has no `config/brief-include.md` today.
- **Source:** firstmate fits dependency graphs. It dispatches independent work in parallel with "no concurrency cap" and serializes "only for a true semantic dependency" (`AGENTS.md:203-205`). It re-evaluates queued items "after every teardown and heartbeat" (`AGENTS.md:376`). This matches the `to-tickets` "frontier" idea. **Inference:** set each ticket's "Blocked by" as a dependency on the backlog row, so firstmate's dispatch gate enforces it.
- **Observed:** the blocking rule today is your own preference, not firstmate: "Work that needs discussion - new features, behavior changes, vague ideas - is defined and built in the project's own session using Matt Pocock's skills (`grill-with-docs`, `to-spec`, `to-tickets`, `implement` or `implement-spec`, then `no-mistakes`). Firstmate does not build those tickets." firstmate takes "concrete interrupts, bug fixes, docs, chores, and standalone investigations." (`firstmate/data/captain.md:19-27`) ADR and GLOSSARY edits are reserved for `domain-modeling` (`captain.md:14`).

## 4. What each Matt skill expects and produces

All four are `disable-model-invocation: true`, so the user (or something typing into the session) must run them as slash commands. Three of them need the tracker set up by `/setup-matt-pocock-skills`; here that is `docs/agents/issue-tracker.md`.

| Skill | Input | Output | Labels and closing |
| --- | --- | --- | --- |
| `to-spec` (`~/.agents/skills/to-spec/SKILL.md`) | The current conversation (usually after grilling). "Do NOT interview the user" (L7). Confirms test seams with the user (L15-17). | One issue: Problem, Solution, long User Stories, Implementation and Testing Decisions, Out of Scope (L21-75). | "Apply the `ready-for-agent` triage label" (L19). |
| `to-tickets` (`to-tickets/SKILL.md`) | A plan, spec, or issue reference (L17). | Tracer-bullet vertical slices with "Blocked by" edges, approved by the user first (L42-56). One issue per ticket in dependency order, as sub-issues of the spec (L63). Template: Parent, What to build, Acceptance criteria checkboxes, Blocked by (L84-103). | `ready-for-agent` "unless instructed otherwise" (L63). "Do NOT close or modify any parent issue" (L67). |
| `implement` (`implement/SKILL.md`) | A spec or ticket reference, fetched from the tracker (L7-9). | Code on the current branch: `tdd` at the agreed seams, typecheck, full suite at the end, then `code-review`, then commit (L11-17). | Does not close issues or open a PR. |
| `implement-spec` (`implement-spec/SKILL.md`) | A spec plus its tickets (L7). | The whole spec on one integration branch. One fresh subagent per ticket "each in its own worktree on its own branch", a merger subagent, then `code-review`, then a draft PR "marked as closing the spec and tickets" (L11, L27-40). | "resolve each ticket the way the issue tracker closes work" (L40). |

**Source:** the default triage vocabulary is `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`, written to `docs/agents/triage-labels.md` only when the `triage` skill is installed (`setup-matt-pocock-skills/SKILL.md:53-59`, L104). **Observed:** this repo has no `triage-labels.md`, and the `status:*` labels are a separate home-grown set.

## 5. Recommended combined workflow

| Phase | Owner | Evidence |
| --- | --- | --- |
| Shape the idea, decide terms and ADRs | You, in this repo's own session: `/grilling` or `/grill-with-docs` | `captain.md:14-15,23` |
| Write the spec issue | `/to-spec` | to-spec L19 |
| Split into tickets with blocking edges | `/to-tickets` (you approve the breakdown) | to-tickets L42-63 |
| Mark a ticket buildable | You: `status:ready-to-build` (repo label: "Scope is settled; can be dispatched now") | `gh label list` |
| Implement each ready ticket | **Option A (current rule):** this session runs `/implement` per ticket, then `/no-mistakes`. **Option B:** tell firstmate "implement issue #N", one ship task per ticket, no-mistakes mode. | `captain.md:23`; `AGENTS.md:185`, `captain.md:32-33` |
| Review, tests, PR, CI | `no-mistakes` (both options) | `AGENTS.md:230` |
| Tick acceptance boxes with evidence | The implementer, before anyone calls the PR mergeable | Your memory rule "update AC before ready to merge" |
| Merge | You | `AGENTS.md:33`; this repo's `AGENTS.md` "Working on main" |
| Close the issue, set `status:done` | `Closes #N` on merge, or `gh-axi issue close --reason completed` | `docs/agents/issue-tracker.md` |

**Inference: when to pick Option B.** Pick it when several tickets are on the frontier at once and you want them built in parallel, each in its own worktree and PR, while you do other things. Pick Option A when a ticket is still fuzzy, or when you want to steer the build yourself. Option B needs two changes first. Rewrite `captain.md:23-24` so firstmate may build `status:ready-to-build` tickets. And add a `config/brief-include.md` with the ticket rules (read the issue, use `tdd` at the spec's seams, tick acceptance boxes with evidence, `Closes #N`, do not touch ADR or GLOSSARY).

### Conflicts to settle

- **Two review layers.** `implement` and `implement-spec` both end with `code-review` (L15, L38). firstmate says "Never ... stack serial manual reviews" and gives review to no-mistakes (`AGENTS.md:230-231`). Under Option B, do not have the worker run `/implement`. Let the brief's issue scope plus no-mistakes do the job, and keep `tdd` as an optional brief rule.
- **Two orchestrators.** `implement-spec` creates its own subagent worktrees, an integration branch, and one draft PR for the whole spec (L27-40). firstmate gives each task "a genuine isolated task worktree" and one PR (`AGENTS.md:212`), and keeps the command structure flat ("depth is capped", `VISION.md:38`). Never run `implement-spec` inside a firstmate worker. Under Option B, firstmate is the orchestrator and you get one PR per ticket, not one integration branch.
- **Two status systems.** firstmate must have a local backlog row to dispatch (`AGENTS.md:213`). Your rule forbids a parallel status for repo work (`captain.md:13`). **Inference:** treat the backlog row as a dispatch pointer only, carrying the issue URL and its blockers, and keep GitHub labels as the truth.
- **Two label vocabularies.** Matt's skills apply `ready-for-agent`. The repo's workflow uses `status:ready-to-build`, which no file documents. Either pass "instead of `ready-for-agent`, apply `status:ready-to-build`" when running `to-tickets` (allowed by "unless instructed otherwise", L63), or document the `status:*` set in `docs/agents/` so every skill and worker can see it. Today it lives only in a private firstmate file.
- **Who closes issues.** `implement` never closes. `implement-spec` closes through its PR. firstmate has no closing behavior and records the merge (`AGENTS.md:246`). `to-tickets` forbids closing the parent (L67). **Inference:** let the PR's `Closes #N` close each ticket at merge, and close the spec issue by hand once all its tickets are closed.

## Sources

- firstmate at `427056c`: `README.md` L33, L47-48, L181-214; `VISION.md` L25, L38, L50-52, L71; `AGENTS.md` L23-34, L169-246, L369-386, L391-392; `.agents/skills/project-management/SKILL.md` L34-63; `.agents/skills/scout-completion/SKILL.md` L11-16; `.agents/skills/bearings/SKILL.md` L204-206; `.agents/skills/harness-adapters/references/harness/claude.md` L14; `docs/configuration.md` L478-537, L1827-1836; `bin/fm-brief.sh` L1-61, L780-830; `.tasks.toml`. Upstream: https://github.com/kunchenguid/firstmate
- Matt Pocock skills (https://github.com/mattpocock/skills): `~/.agents/skills/{to-spec,to-tickets,implement,implement-spec,grilling,grill-with-docs,setup-matt-pocock-skills}/SKILL.md`; install metadata in `~/.agents/.skill-lock.json`.
- This repo: `AGENTS.md`, `docs/agents/issue-tracker.md`, GitHub label list and issue label counts for `KLTsai/next-is-you` (read 2026-11-18).
- Local firstmate home (private, gitignored): `~/projects/firstmate/data/captain.md` L13-27, L29-34; `~/projects/firstmate/data/next-is-you-issue20-ntuh-reader-20261022/brief.md`.
