# CI gates and Cloudflare Free plan usage tracking

Research completed 2026-11-24. Scope: (A) how the seven CI gates in [`.github/workflows/ci.yml`](../.github/workflows/ci.yml) compare with first-party best practice for a small Python and TypeScript Worker app that squash-merges pull requests and versions with Release Please, and which additions have a concrete payoff here; (B) what Cloudflare provides to track Worker, Durable Object and D1 usage against the Workers Free plan limits, and the simplest monitoring that fits this project. Primary sources only: docs.github.com, github.com/rhysd/actionlint, github.com/googleapis/release-please (source read at `main` commit `ea20bc26`, 2026-11-03, package version 17.11.2), conventionalcommits.org, github.com/ossf/scorecard, developers.cloudflare.com (pages read 2026-11-24 through their `index.md` form) and one first-party Cloudflare blog post. Each claim is labelled **Source** (what the source says), **Observed** (read from this repository, its git history or the GitHub API on 2026-11-24) or **Inference** (my reasoning). **Unverified** marks anything no source settles. Nothing was deployed and no Cloudflare API was called. This is supporting evidence for [#203](https://github.com/KLTsai/next-is-you/issues/203), [#188](https://github.com/KLTsai/next-is-you/issues/188) and [#192](https://github.com/KLTsai/next-is-you/issues/192), not implementation authority; adopt anything from it through a GitHub issue first.

## Answer

- **Add checks as steps inside existing gate jobs, never as a new gate job.** `scripts/delivery_state.py` treats a commit as green only when every name in `GATES` has a successful check, and the Promote guard refuses a version whose checks are not all `success`. An eighth gate name would make every version tagged before it (today `v0.3.0`) read as "still running" forever, so Promote could no longer roll back to it. A non-gate check that must block merging belongs in its own workflow and in the ruleset, not in `GATES`.
- **actionlint: adopt, as a step in `Formatting and lint`.** The concrete payoff is `promote.yml`, whose bash and expressions run only when the captain promotes, so no pull request run exercises them today. actionlint type-checks `${{ }}` expressions, runs shellcheck on `run:` scripts and checks `needs:` and cron syntax. #203 records that agents could not validate workflow YAML locally in 4 sessions.
- **JSON schema check of `release-please-config.json`: low payoff, skip or fold into a test.** Release Please does not validate its config at runtime (ajv is used only in its tests), but its schema leaves per-package options open (no `additionalProperties: false`). So the misplaced `last-release-sha` inside `packages."."` that this repo carried and later removed as inert (`f7b6cb8`) would have passed the schema.
- **PR-title type check: adopt, in its own small workflow, not in `ci.yml`.** History shows six non-user-facing PRs typed `feat` or `fix` (#50, #51, #53, #61, #77, #78) that produced or inflated versions 0.2.0, 0.2.2 and 0.2.3. There have been none since squash-only merging (#127, 2026-11-15), and the check cannot catch the opposite mistake (`chore:` on product code). Re-running on title edits needs the `edited` type, and adding that to `ci.yml` would re-run all seven gates (about 12.5 minutes) on every title or body edit. Make the new check required in the ruleset next to `Summary`.
- **Pinning and permissions: mostly in place.** Third-party actions are SHA-pinned and `ci.yml` defaults to `contents: read`. The GitHub-owned `actions/*@v7` are tag-pinned. Pinning them too, with Dependabot `github-actions` version updates, is cheap and protects the deploy jobs that hold `CLOUDFLARE_API_TOKEN`. Add a top-level `permissions:` to `promote.yml`.
- **Secret scanning: turn on push protection (a setting, not a gate).** The repository is public, and the API reports secret scanning and push protection as `disabled`. Dependency review is a poor fit: GitHub's dependency graph does not list `uv.lock`, so it would see only the two npm dev dependencies.
- **Cloudflare usage: GraphQL Analytics is the only first-party source that counts usage against every Free limit.** Its datasets cover Worker requests and CPU quantiles (`workersInvocationsAdaptive`), Durable Object requests and CPU (`durableObjectsInvocationsAdaptiveGroups`, `durableObjectsPeriodicGroups`) and D1 rows read and written (`d1AnalyticsAdaptiveGroups`). Adaptive datasets keep at least 31 days on every plan, and the token needs Account Analytics Read. There is no Free-plan usage-threshold notification: "Usage Based Billing" alerts are for Pro and higher pay-as-you-go accounts.
- **What happens at a Free limit.** Worker requests get Error 1027 until 00:00 UTC. Durable Object operations "of that type will fail with an error", and D1 queries cannot run. No page says whether Cron Triggers or alarms keep running after the Worker request limit (**Unverified**).
- **Recommended monitoring: one stdlib script plus one scheduled workflow, separate from `npm run status`.** An hourly workflow with a read-only Analytics token queries today's UTC totals, projects them to the full day, writes a table to the run summary and fails above 50% of any limit, the #192 budget. A failed scheduled run emails the captain. It would not tell us the CPU of a single invocation (only quantiles), whether a tick was throttled, or which page caused the load; Workers Logs (already enabled) and `wrangler tail` stay for that.
- **Time-sensitive: Workers Logs pricing changes on 2026-12-01.** Free moves from 200,000 events a day with 3-day retention to 0.5 GB of ingestion a day with 7-day retention, and on Free ingestion stops at the cap until 00:00 UTC.

---

# Part A: CI gates

## A.1 What the pipeline does today

**Observed** (`.github/workflows/ci.yml`, `promote.yml`, `scripts/check_ci_diff.sh`, GitHub API):

| Gate (job name) | What it runs |
| --- | --- |
| Formatting and lint | `ruff format --check`, `ruff check` on `src tests scripts` |
| Type check | `tsc --noEmit` |
| Frontend tests | `node --test frontend/test/*.test.js` |
| Build | `vite build` |
| Migration check | `scripts/check_migrations.py` (risk header on new migrations, #133) |
| Backend and browser tests | `vite build`, Playwright install, `pytest -q` (9 to 12 minutes per #207) |
| Diff hygiene | `git diff --check`, rejects agent `Co-authored-by` trailers (#197), rejects em dashes on added lines (#200) |

- Triggers: `push` to `main` and `pull_request` with the default activity types. Top-level `permissions: contents: read`; `release-please` raises to `contents: write, pull-requests: write`; `staging-order` is `contents: read`.
- `Summary` needs all seven gates and is the only required status check in the ruleset "main: CI Summary before merge" (`required_status_checks: [Summary]`). `main` has no classic branch protection.
- Repository settings: `default_workflow_permissions: read`, `allowed_actions: all`, `sha_pinning_required: false`, squash title `PR_TITLE`, squash message `BLANK`, visibility public.
- `security_and_analysis`: `secret_scanning`, `secret_scanning_push_protection` and `dependabot_security_updates` are all `disabled`. `GET /vulnerability-alerts` returns 404 (Dependabot alerts off). No `.github/dependabot.yml`.
- Pinning: `astral-sh/setup-uv` and `googleapis/release-please-action` are pinned to full SHAs with a version comment; `actions/checkout`, `actions/setup-python` and `actions/setup-node` use `@v7`.
- `promote.yml` has no top-level `permissions:`. Its `guard` and `deploy` jobs set their own; `require-main` inherits the repository default (read).
- No `concurrency:` on `ci.yml` for pull requests, so every push to a PR branch runs a full pipeline even when a newer push supersedes it.

**Observed** (last 100 failed runs, `GET /actions/runs?status=failure`): since the seven-gate pipeline (2026-11-14) the PR gate failures were `Backend and browser tests` twice (#191 and #193 branches, 2026-11-22) and `Formatting and lint` once (a deliberate failure for #68). No observed failure came from workflow syntax. The earlier `deterministic-gates` failures on 2026-11-12 were a series of browser-test timing fixes pushed straight to `main`.

## A.2 How adding a gate interacts with `scripts/delivery_state.py`

**Observed.** `GATES` in `scripts/delivery_state.py` lists the seven job names. `_read_checks` returns `pending` when `len(latest) < len(GATES)`. The Promote guard (`_read_commit_facts`, then line 345) refuses a version whose checks are not `success` with "the checks on vX are still running". `tests/test_delivery_state.py` asserts that the `Summary` job's `needs` equal `GATES` in order, that `staging-order`, `deploy-staging` and `release-please` need every gate, and that no job in any workflow file reuses a gate name. `docs/CI-CD.md` and `README.md` say "seven" in four places.

**Inference.** A new gate job is therefore not just a YAML change:

1. `GATES`, the `Summary` `needs` and its `jq` name map, three `needs:` lists, the test fixture list and the docs all change together.
2. Every commit that predates the new gate has no check with the new name, and re-running its pipeline run replays that commit's old `ci.yml`, which does not have the job either. The guard would report every existing version, today `v0.3.0`, as "still running" forever. Rollback to a pre-change version, the documented way to undo a bad Promote, would stop working.
3. Removing or merging gates is the safe direction: an old commit still carries a superset of the names.

A new **step** in an existing gate job has none of these effects: the job name, and so the check name, stays the same. #207 already follows this rule by keeping one aggregate job named `Backend and browser tests` over the shards.

A check that is **not** a gate (its own workflow, a name not in `GATES`) is also safe: `_read_checks` ignores names outside `GATES`. It can still block merging through the ruleset's required checks. It must not reuse a gate name; the test above enforces that.

## A.3 actionlint

**Source** ([rhysd/actionlint README](https://github.com/rhysd/actionlint)): checks workflow syntax, a "strong type check for `${{ }}` expressions", action inputs and outputs, "shellcheck and pyflakes integrations" for `run:` scripts, script injection by untrusted inputs and hard-coded credentials, plus "glob syntax validation, dependencies check for `needs:`, runner label validation, cron syntax validation". The current version in the docs is v1.7.12.

**Source** ([actionlint usage](https://github.com/rhysd/actionlint/blob/main/docs/usage.md)): "Preparing `actionlint` executable with the download script is recommended" in CI; a pinned Docker tag `rhysd/actionlint:{version}` is the alternative; "shellcheck is pre-installed on Ubuntu worker"; a problem matcher (`.github/actionlint-matcher.json`) turns findings into annotations.

**Observed evidence for a payoff.**
- #203: "Workflow YAML: cannot be validated locally (`No module named 'yaml'` in 4 sessions); no `actionlint` or config schema check in CI."
- About 25 commits touch `.github/workflows/` (`git log -- .github/workflows`), most of them agent-written.
- `promote.yml` contains the longest inline bash in the repository (the Release publishing `case` and `awk`) and runs only on `workflow_dispatch` by the captain. A mistake there surfaces only during a production promotion. `ci.yml` is exercised by every PR run, so its errors are already found by running it.

**Recommendation.** Add actionlint as a step in `Formatting and lint`, with a pinned version, not `latest`. **Inference:** this costs seconds and needs no new job. It also gives agents a local command once the binary is installed, but no npm or uv package provides it, so `npm run check` would need a documented install step or the Docker image. Keep shellcheck on through actionlint; it is already on the runner.

**What it would not catch.** Logic errors such as a wrong `if:` that is well-typed; whether a job name matches `GATES` (the existing test covers that).

## A.4 JSON schema check of `.github/release-please-config.json`

**Source** ([release-please `schemas/config.json`](https://github.com/googleapis/release-please/blob/main/schemas/config.json), read at `ea20bc26`): the top level has `additionalProperties: false`. `packages` maps each path to `ReleaserConfigOptions`, whose definition has `properties` but no `additionalProperties` key, so unknown keys inside a package are allowed. `bootstrap-sha` and `last-release-sha` are top-level properties only.

**Source** (release-please source, GitHub code search): `ajv` appears in `package.json` and is used in `test/schemas.ts`; no file under `src/` imports it. **Inference:** Release Please does not validate the config at runtime, so a misspelled key is silently ignored. (Code search can miss files; **Unverified** beyond that search.)

**Observed.** The config carried `"last-release-sha"` inside `packages."."` from `f23ebf4` until `f7b6cb8` ("drop the inert last-release-sha"), whose message records that a dry run still considered all 103 commits. A schema check would have passed that config, because the per-package object is open. #203 also lists "`bootstrap-sha` placement" among the guesses that went wrong.

**Recommendation.** Low payoff. A schema check catches a top-level typo and wrong value types only; the observed mistake was a valid key in the wrong place. If it is wanted, a few lines in an existing pytest test can assert the specific rules that matter here (no `bootstrap-sha` or `last-release-sha` inside `packages`; `draft` and `force-tag-creation` stay `true`; the `docs` section stays hidden), with no new tool. Recording verified Release Please behaviour, decision 1 of #203, matters more than validation.

## A.5 PR-title type check

**Source** ([Conventional Commits 1.0.0](https://www.conventionalcommits.org/en/v1.0.0/)): `feat` "MUST be used when a commit adds a new feature to your application or library"; `fix` "MUST be used when a commit represents a bug fix for your application"; "Types other than `feat` and `fix` MAY be used". With a squash-based workflow, "lead maintainers can clean up the commit messages as they're merged". A commit that does not follow the spec "would simply be missed by tools that are based on the spec".

**Source** ([release-please README](https://github.com/googleapis/release-please)): "We **highly** recommend that you use squash-merges when merging pull requests." `fix` is a patch and `feat` a minor. The README names no linter for PR titles.

**Source** ([Events that trigger workflows, pull_request](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows)): "By default, a workflow only runs when a `pull_request` event's activity type is `opened`, `synchronize`, or `reopened`." ([Webhook payloads, pull_request](https://docs.github.com/en/webhooks/webhook-events-and-payloads)): `edited` means "The title or body of a pull request was edited, or the base branch of a pull request was changed."

**Source** ([Secure use reference](https://docs.github.com/en/actions/reference/security/secure-use)): untrusted input such as `github.event.pull_request.title` should be passed through an intermediate environment variable, not interpolated into the script.

**Observed evidence.** Merged PRs and their files (`gh pr list --state merged`), with `CHANGELOG.md`:

| PR | Title | Files | Effect |
| --- | --- | --- | --- |
| #50 | `feat(ci-cd): add release-please versioning ...` | workflows, config, docs | listed under Features of 0.2.0 (twice, merge commits) |
| #51 | `fix(ci-cd): match production deploy to the prod GitHub Environment` | workflow, docs | Bug Fixes of 0.2.0 |
| #53 | `fix(ci-cd): baseline release-please ...` | release-please config | Bug Fixes of 0.2.0 |
| #61 | `fix(tests): add container wait ...` | `tests/test_rehearsal.py` | would count as a patch |
| #77 | `fix: remove blank line` | `README.zh-TW.md` | alone produced 0.2.2 |
| #78 | `fix: rollback testing` | `README.zh-TW.md` | alone produced 0.2.3 |

#203 confirms that "a CI-only change typed `feat(ci-cd)` caused a wrong minor bump". Since squash-only merging began (#127, 2026-11-15), about 40 merged PRs have had a type consistent with their files: `ci:` on workflows, `test:` and `chore:` on scripts and tests. The opposite mistake does occur: #171, #173, #176, #184 and #194 change `src/` or `migrations/` and are typed `chore:`. That may be correct (not user-noticeable) or not; no file-based rule can judge it.

**Recommendation.** Worth adding, as a cheap guard against a mistake that has already produced three unwanted versions, while being honest that the post-#127 rate is zero:

- A separate workflow (for example `.github/workflows/pr-title.yml`) on `pull_request` with `types: [opened, edited, synchronize, reopened]`, one job with a name not in `GATES`, `permissions: contents: read`. The title goes in through `env:`.
- It fails when the title is not a Conventional Commit, which Release Please would skip silently (`docs/CI-CD.md`), or when the type is `feat`, `fix` or `perf` (or has `!`) and no changed path is product code. Product code would be `src/`, `frontend/`, `migrations/`, `wrangler.*.jsonc`, and the runtime dependency files `pyproject.toml`, `uv.lock`, `package.json`, `package-lock.json`. The rule could live in `scripts/` next to `is_docs_only` in `delivery_state.py`, with a unit test.
- Add its check to the ruleset's required checks next to `Summary`. Release PRs (`chore(main): release X.Y.Z`) pass by type.

**Why not a step in `Diff hygiene`.** Without `edited` the step would not re-run after a title fix, so a red check would stay until the next push. Adding `edited` to `ci.yml` would re-run all seven gates, about 12.5 minutes per #207, on every title or body edit. **Inference:** a separate workflow is the smaller change and leaves `GATES` alone (A.2).

**Inference, not a requirement.** commitlint is not needed: with squash title `PR_TITLE` and message `BLANK`, only the title reaches `main`, so branch commit messages do not matter to Release Please.

## A.6 Pinning, token permissions, dangerous workflows

**Source** ([Secure use reference](https://docs.github.com/en/actions/reference/security/secure-use)): "Pin references to actions to a commit SHA in your workflow files"; "If you'd like to specify a tag, then be sure that you trust the action's creators", because "a tag can be moved or deleted if a bad actor gains access to the repository storing the action". Make sure "the `GITHUB_TOKEN` is granted the minimum required permissions", defaulting to read-only contents and raising per job. "Dependabot version updates open pull requests to update actions to the latest version", and "Dependabot will not create alerts for actions pinned to SHA values". The page also introduces workflow dependency lockfiles as "the strongest protection available, and supersedes SHA pinning for repositories that adopt it".

**Source** ([Workflow dependency lockfiles](https://docs.github.com/en/actions/concepts/security/workflow-dependency-lockfiles)): `.github/workflows/actions.lock`, generated by the `gh actions-lock` CLI extension. Release status and plan availability are not stated (**Unverified**).

**Source** ([OpenSSF Scorecard checks](https://github.com/ossf/scorecard/blob/main/docs/checks.md)): Pinned-Dependencies treats a tag as pinned only "when that tag is backed by a published immutable release". Token-Permissions wants permissions "set as read-only at the top level" of each workflow. Dangerous-Workflow flags `pull_request_target` and `workflow_run` with untrusted checkout, and script injection. Dependency-Update-Tool checks for Dependabot or Renovate.

**Observed and assessment.**

| Practice | Status here | Payoff of changing |
| --- | --- | --- |
| Third-party actions SHA-pinned | Yes (`setup-uv`, `release-please-action`) | Already done |
| GitHub-owned actions SHA-pinned | No (`@v7`) | Low to medium. These run in `deploy-staging` and Promote `deploy`, which hold `CLOUDFLARE_API_TOKEN` and `contents: write`. GitHub's own guidance accepts tags from trusted creators. |
| Automated action updates | None; done by hand (`ab8a158`, `ded49ab` "use/pin published setup-uv") | Medium: a `.github/dependabot.yml` with only the `github-actions` ecosystem keeps SHA pins current. Its PRs need `ci:` or `build:` titles, which Dependabot can set with a commit-message prefix (**Unverified** detail). |
| Top-level read-only permissions | `ci.yml` yes; `promote.yml` no | Low (repository default is already read), but one line, and Scorecard counts it. |
| `pull_request_target` / `workflow_run` | None | Nothing to do |
| Untrusted input in `run:` | `inputs.version` goes through `env:`; `vars.*` and `job.status` are interpolated but are not attacker-controlled | Nothing to do; the new PR-title check must also use `env:` |
| `sha_pinning_required` repository setting | `false` | Optional once all actions are SHA-pinned (**Unverified**: no docs page read for this setting) |

## A.7 Dependency and secret scanning

**Source** ([About secret scanning](https://docs.github.com/en/code-security/secret-scanning/introduction/about-secret-scanning)): on public repositories "Secret scanning runs automatically for free"; "Partner secrets are reported directly to the provider and aren't displayed in your repository alerts". ([Enabling push protection](https://docs.github.com/en/code-security/secret-scanning/enabling-secret-scanning-features/enabling-push-protection-for-your-repository)): "secret scanning blocks contributors from pushing secrets to a repository", enabled under Settings, Advanced Security, Secret Protection. Whether push protection is free for public repositories is not stated on that page (**Unverified**, though the repository API exposes the toggle).

**Observed.** The repository is public, the API shows `secret_scanning` and `secret_scanning_push_protection` `disabled`, and the secrets at stake are the Cloudflare API token and LINE channel credentials (`docs/SECRETS.md`). Agents write most commits.

**Recommendation.** Enable secret scanning alerts and push protection in repository settings. It is a captain settings change, costs no CI time and adds no gate. **Inference:** payoff is protection against a rare but costly event; there is no observed leak.

**Source** ([About dependency review](https://docs.github.com/en/code-security/supply-chain-security/understanding-your-software-supply-chain/about-dependency-review)): the action "is available for all public repositories", needs the dependency graph, and "will fail if it discovers any vulnerable packages". ([Supported ecosystems](https://docs.github.com/en/code-security/supply-chain-security/understanding-your-software-supply-chain/dependency-graph-supported-package-ecosystems)): npm `package-lock.json` is supported; for Python only pip (`requirements.txt`, `pipfile.lock`) and Poetry (`poetry.lock`) are listed; `uv.lock` is not listed.

**Observed.** Runtime dependencies are Python only: `fastapi<0.142.0` and `tzdata` (`pyproject.toml`, locked in `uv.lock`). The npm side is two dev dependencies (`typescript`, `vite`). FastAPI is held below 0.142.0 on purpose because that version breaks Worker startup.

**Recommendation.** Skip dependency review: it cannot see the Python lockfile, which holds every runtime dependency. Dependabot alerts (a setting) are cheap to turn on, but expect noise from dev-only npm packages. Do not enable automatic dependency update PRs for Python. The FastAPI pin shows an upgrade can break the Worker in a way only a deploy reveals.

## A.8 Covered, missing, redundant

**Covered well.** Formatting and lint, types, unit and browser tests, build, migration risk headers, diff hygiene, least-privilege default token, SHA pins for third-party actions, Release Please after all gates, a delivery-state test that keeps job names and `GATES` in step.

**Missing, with a concrete payoff here.**
1. actionlint as a step (A.3), for `promote.yml` in particular.
2. PR-title check in its own required workflow (A.5).
3. Push protection and secret scanning toggles (A.7).
4. `concurrency` for pull request runs. **Source** ([Control workflow concurrency](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency)): `group: ${{ github.head_ref || github.run_id }}` with `cancel-in-progress: true` "cancels in-progress jobs or runs on `pull_request` events only", because `head_ref` is only defined on `pull_request`. **Observed:** #207 records queueing when three runs started together under the 20-job limit. **Inference:** this cuts superseded PR runs and never touches `main` pushes, whose order `staging-order` already handles.

**Redundant or over-built (not worth changing now).**
- `Build` runs `vite build`, and `Backend and browser tests` runs the same build before pytest, so a build failure already fails the browser gate. Merging the two would remove a gate name, which is the safe direction (A.2), but the separate gate gives a faster and clearer red. Keep it.
- `Type check`, `Frontend tests` and `Build` each run `npm ci` on their own runner. They run in parallel, so the cost is runner minutes, not wall time.
- A JSON schema check (A.4) and dependency review (A.7) would add machinery for little coverage.

**Cloudflare deploy-side gap, speculative.** **Source** ([Wrangler commands](https://developers.cloudflare.com/workers/wrangler/commands/workers/)): `wrangler deploy --dry-run` compiles "without actually deploying"; `wrangler versions upload` uploads a version that "is not deployed immediately". **Observed:** the first time the real Python Worker is uploaded is `Deploy staging`, after merge; `b8b6b7e` (#5) and the FastAPI pin are past startup-compatibility breaks. **Inference, Unverified:** whether a dry run or a version upload runs the Python snapshot and the 1 second startup check is not stated, so this does not justify a PR step yet.

---

# Part B: Cloudflare usage tracking on the Free plan

## B.1 The limits and what happens when one is exceeded

| Resource | Free limit | Reset | When exceeded | Source |
| --- | --- | --- | --- | --- |
| Worker requests | 100,000 a day, per account | 00:00 UTC | "Cloudflare returns Error 1027"; routes can fail open or fail closed | [Workers limits](https://developers.cloudflare.com/workers/platform/limits/) |
| Worker CPU | 10 ms per HTTP request and per Cron Trigger | per invocation | Error 1102, outcome `exceededCpu` (see the [2026-11-21 research](workers-free-cpu-limit-2026-11-21.md)) | [Workers limits](https://developers.cloudflare.com/workers/platform/limits/) |
| DO requests | 100,000 a day; "Includes HTTP requests, RPC sessions, WebSocket messages, and alarm invocations" | 00:00 UTC | "If you exceed any one of the free tier limits, further operations of that type will fail with an error." | [DO pricing](https://developers.cloudflare.com/durable-objects/platform/pricing/) |
| DO duration | 13,000 GB-s a day, billed on wall-clock time at 128 MB | 00:00 UTC | same | [DO pricing](https://developers.cloudflare.com/durable-objects/platform/pricing/) |
| DO SQLite rows | 5 million read, 100,000 written a day; 5 GB stored | 00:00 UTC | same | [DO pricing](https://developers.cloudflare.com/durable-objects/platform/pricing/) |
| D1 rows | 5 million read, 100,000 written a day; 5 GB stored, 500 MB per database | 00:00 UTC | "you will not be able to run queries against D1" | [D1 pricing](https://developers.cloudflare.com/d1/platform/pricing/), [D1 limits](https://developers.cloudflare.com/d1/platform/limits/) |
| D1 queries per invocation | 50 | per invocation | not stated | [D1 limits](https://developers.cloudflare.com/d1/platform/limits/) |

**Source** ([Static assets billing](https://developers.cloudflare.com/workers/static-assets/billing-and-limitations/)): "Requests to static assets are free and unlimited", but "When using run_worker_first, requests matching the specified patterns will always invoke your Worker script". **Observed:** `wrangler.staging.jsonc` sets `"run_worker_first": true`. **Inference:** every page and asset load counts as a Worker request here, which #192's budget already assumes.

**Unverified.** No page says whether Cron Triggers or Durable Object alarms still run after the Worker request limit is reached, or whether Cron invocations count toward the 100,000. #192 already records this gap.

## B.2 What Cloudflare provides to see usage

### GraphQL Analytics API

**Source** ([GraphQL limits](https://developers.cloudflare.com/analytics/graphql-api/limits/)): adaptive datasets "retain at least 31 days of data on every plan"; "Higher plans have access to a greater selection of datasets or fields"; availability is checked through "its `enabled` field in the Settings node". The default quota is "300 GraphQL queries over 5-minute window".

**Source** ([Querying Workers metrics](https://developers.cloudflare.com/analytics/graphql-api/tutorials/querying-workers-metrics/)): dataset `workersInvocationsAdaptive` with `sum { requests errors subrequests }`, `quantiles { cpuTimeP50 cpuTimeP99 }`, dimensions `datetime scriptName status`, sent to `https://api.cloudflare.com/client/v4/graphql`. "We can query up to one month of data for dates up to three months ago." ([Workers metrics](https://developers.cloudflare.com/workers/observability/metrics-and-analytics/)): invocation statuses map to GraphQL values `success`, `clientDisconnected`, `scriptThrewException`, `exceededResources`, `internalError`.

**Source** ([DO GraphQL analytics](https://developers.cloudflare.com/durable-objects/observability/graphql-analytics/)): datasets `durableObjectsInvocationsAdaptiveGroups` (`requests`, `responseBodySize`), `durableObjectsPeriodicGroups` (`cpuTime`, `memoryUsageBytes` quantiles), `durableObjectsStorageGroups` (`storedBytes`), `durableObjectsSubrequestsAdaptiveGroups`. "Use GraphQL introspection to discover the fields." The docs do not name a duration (GB-s) field or SQLite row fields for Durable Objects (**Unverified**; introspect `durableObjectsPeriodicGroups` before relying on one).

**Source** ([D1 metrics](https://developers.cloudflare.com/d1/observability/metrics-analytics/)): `d1AnalyticsAdaptiveGroups` with `readQueries`, `writeQueries`, `rowsRead`, `rowsWritten`; `d1StorageAdaptiveGroups` with `databaseSizeBytes`. "Metrics can be queried (and are retained) for the past 31 days." `wrangler d1 insights` needs "the **Account Analytics Read** permission".

**Source** ([API token auth](https://developers.cloudflare.com/analytics/graphql-api/getting-started/authentication/api-token-auth/)): token scope Account, Account Analytics, Read.

**Unverified.** No page states that these account-level datasets are enabled on a Free account. The limits page implies adaptive datasets exist "on every plan"; the Settings node answers it with one query.

### Dashboard Metrics

**Source** ([Workers metrics](https://developers.cloudflare.com/workers/observability/metrics-and-analytics/)): per-Worker charts for requests, subrequests, CPU time and wall time quantiles (reservoir sampling), duration, memory and invocation statuses; "Worker metrics can be inspected for up to three months in the past in maximum increments of one week"; "Worker metrics are powered by GraphQL". ([DO metrics](https://developers.cloudflare.com/durable-objects/observability/metrics-and-analytics/)): per-namespace analytics in the dashboard, default window 24 hours. ([D1 pricing](https://developers.cloudflare.com/d1/platform/pricing/)): "Metrics > Row Metrics" per database.

**Unverified.** I found no docs page that describes an account-wide "today against the Free limit" usage panel. Dashboard charts are per Worker or per database, so Staging and Production must be added by hand.

### Workers Logs and Workers Observability

**Source** ([Workers Logs](https://developers.cloudflare.com/workers/observability/logs/workers-logs/)): enabled with `observability.enabled = true`. Until 2026-12-01, Free gets 200,000 log events a day and 3-day retention. Invocation logs are tagged `$cloudflare.$metadata.type = "cf-worker-event"`; `head_sampling_rate` defaults to 1. The page also says "Use Monitors for alerts based on custom log queries, such as budget warnings." It does not say what happens on Free past 200,000 events (**Unverified**).

**Source** ([Workers limits, CPU](https://developers.cloudflare.com/workers/platform/limits/)): "CPU time and wall time appear in the invocation log."

**Source** ([Observability pricing](https://developers.cloudflare.com/observability/pricing/)): "This pricing takes effect on December 1, 2026." Free gets 0.5 GB of ingestion a day and seven days of retention. "On Free, Cloudflare stops ingesting new data when you reach the daily limit", resuming at 00:00 UTC. Workers Logs, Workers Traces and several other products share one allowance per account. The [launch post](https://blog.cloudflare.com/one-observability-platform) (2026-10-02) gives the same Free figures.

**Observed.** Both `wrangler.staging.jsonc` and `wrangler.production.jsonc` have `"observability": {"enabled": true}`. So invocation logs with CPU time per invocation are already being collected for both environments.

### Real-time logs (`wrangler tail`)

**Source** ([Real-time logs](https://developers.cloudflare.com/workers/observability/logs/real-time-logs/)): "Real-time logs does not store Workers Logs"; high-traffic Workers "may enter sampling mode"; "A maximum of 10 clients can view a Worker's logs at one time." The page does not mention CPU time, though the project's tail captures in `docs/HTTPS-SERVICE.md` show per-invocation CPU.

### Notifications and Monitors

**Source** ([Available notifications](https://developers.cloudflare.com/notifications/notification-available/)): the only usage alert is "Usage Based Billing", for "Professional plans or higher" and "Pay-as-you-go accounts only". No Workers, Durable Objects or D1 Free-quota notification is listed. **So there is no first-party Free-plan usage-threshold alert.**

**Source** ([Monitors](https://developers.cloudflare.com/notifications/monitors/)): "Monitors evaluate a SQL API query on a schedule" with a threshold and window; delivery by email, webhook or PagerDuty (Business zone and up); "The datasets available to monitors depend on your plan and permissions"; Log Explorer datasets run at most every 10 minutes. The [SQL API datasets page](https://developers.cloudflare.com/analytics/sql-api/datasets/) shows `logs.workersLogs` and `states.d1Storage` and says the catalog "is not a fixed list". The launch post calls the SQL API and custom alerts beta. **Unverified:** whether Monitors and `logs.workersLogs` are available on a Free account, and whether any dataset there counts Durable Object requests or D1 rows. Logs-based counts also inherit log sampling and the 0.5 GB cap.

## B.3 Fit with what the project has

**Observed.**
- `npm run status` (`scripts/delivery_state.py status`) reads only GitHub through `gh api`; it holds no Cloudflare credential, and its job is delivery state.
- `docs/HTTPS-SERVICE.md` records CPU through hand-run `wrangler tail` sessions (#162, #170). #188 and #192 put `wrangler tail` in their Staging acceptance criteria. #203 says tail wrappers "were built by hand twice" and that the output pipe blocked.
- #192 measured about 126,000 Worker requests a day at one point on 2026-11-22. That is over the 100,000 limit, and the quota is shared by Staging and Production in one account. #192 asks for a daily budget in which every limit stays under 50%.
- ADR 0005: the Durable Object alarm drives the tick, and a watchdog Cron runs every 5 minutes (`"*/5 * * * *"` in the Staging config).

**Assessment.**
- **Daily-limit risk (#192): GraphQL is the right tool.** It is the only first-party source that counts usage for every Free limit (Worker requests, DO requests and CPU, D1 rows) per day across both scripts. The dashboard needs manual reading, and there is no Free alert.
- **Per-invocation CPU (#188): Workers Logs is the right tool, not GraphQL.** GraphQL gives `cpuTimeP50` and `cpuTimeP99` per bucket, not each invocation. Workers Logs already records CPU per invocation and keeps it for 3 days (7 from 2026-12-01), so a measurement can be read after the fact in the dashboard Observability view instead of keeping a `wrangler tail` pipe open. Whether that satisfies #188's "under `wrangler tail`" wording is the captain's call.
- **Keep it out of `npm run status`.** Adding Cloudflare would give that script a second credential and a second failure mode in a command the captain relies on for release decisions.

## B.4 Recommendation

The simplest option with a real payoff, and no conflict with existing pieces:

1. **A read-only Cloudflare API token** with Account Analytics Read only, stored as a separate GitHub Actions secret. Do not reuse the deploy token `CLOUDFLARE_API_TOKEN`, which can write.
2. **One Python standard-library script** (for example `scripts/cloudflare_usage.py`, `urllib` only, so it runs with `python3` like `delivery_state.py`). It sends one GraphQL request for the current UTC day across both Workers and the D1 databases:
   - `workersInvocationsAdaptive`: `sum.requests` by `scriptName`, plus counts by `status` (to see `exceededResources`), and `cpuTimeP99`.
   - `durableObjectsInvocationsAdaptiveGroups`: `sum.requests`.
   - `durableObjectsPeriodicGroups`: `cpuTime`, plus whatever introspection shows for duration and rows.
   - `d1AnalyticsAdaptiveGroups`: `rowsRead`, `rowsWritten`.

   It prints used, projected to 24 hours, limit and percent for each Free limit. It exits non-zero when any projection exceeds 50%, the #192 budget line, or when a dataset is not enabled.
3. **One scheduled workflow** (for example `.github/workflows/usage.yml`), hourly, plus `workflow_dispatch`. It runs the script, writes the table to `$GITHUB_STEP_SUMMARY`, and fails on the threshold. Its job name is not a gate name, so `GATES`, `Summary` and Promote are untouched (A.2). An `npm run usage` alias lets the captain run the same check locally.

**Source** ([Events that trigger workflows, schedule](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows)): the shortest interval is 5 minutes; runs "can be delayed during periods of high loads" and "some queued jobs may be dropped"; "In a public repository, scheduled workflows are automatically disabled when no repository activity has occurred in 60 days"; "Notifications for scheduled workflows are sent to the user who last modified the cron syntax", so the captain should be the one who commits the cron line. **Inference:** on a day like 2026-11-22 (126,000 a day is about 5,250 an hour), the projection passes 50% at the first hourly run after the rate starts, while the limit itself would be reached about 19 hours later. That is enough warning for the captain to close a page or pause, but not a guarantee. Early in the UTC day the projection rests on few hours and will be noisy.

**What it would not tell us.**
- The CPU of any single invocation, or whether a given tick ran over 10 ms. P99 per bucket only; use Workers Logs for #188.
- Whether Cloudflare's undocumented CPU "flexibility" is being used up. No dataset exposes it.
- Which page, user or tab caused the load: requests are counted by script and status, not by caller.
- What happens to Cron and alarms after the request limit (**Unverified** at the source).
- Real-time state: GraphQL data may lag (no lag figure found, **Unverified**), and GitHub may delay or drop the schedule.
- Other quotas: the LINE Messaging API monthly message quota and the Workers Logs ingestion cap are separate and not covered.
- Whether the account-level datasets and a DO duration field are available on Free. Check that first with one Settings-node query and one introspection query, before building anything.

**Not recommended now.** A Cloudflare Monitor on `logs.workersLogs`: Free availability is unverified, it sees only logged Worker events (not DO requests or D1 rows), and from 2026-12-01 logging stops at the 0.5 GB daily cap, which is exactly when a runaway day would need it. Revisit if Cloudflare documents Monitors on analytics datasets for Free accounts.

## Doc claims that could not be verified

- Whether Cron Triggers or Durable Object alarms run after the Worker daily request limit, and whether Cron invocations count toward it.
- What Workers Logs does on Free past 200,000 events a day, before 2026-12-01.
- Which GraphQL fields hold DO duration (GB-s) and DO SQLite rows read and written; whether the account datasets are enabled on a Free account.
- Whether Monitors and the SQL API (beta) are available on Free, and which datasets they can read there.
- An account-wide dashboard view of Free usage against limits.
- The release status and plan availability of GitHub workflow dependency lockfiles; whether push protection is free on public repositories (the toggle is exposed in the repository API).
- Whether `wrangler deploy --dry-run` or `versions upload` exercises Python Worker startup.

## Index note

`research/README.md` has a "Delivery and operations research" section; this file belongs there. The README also does not list `CI-CD-main-policy-and-versioning.md`, `firstmate-and-matt-skills-workflow.md` or `line-rich-menu-progress-button.md`. #207 links `research/ci-test-wall-time-2026-11-23.md`, which is not on `main` as of 2026-11-24.
