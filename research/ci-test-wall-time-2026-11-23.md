# Cutting CI wall time for the backend and browser test job

Research completed 2026-11-23. Scope: how to shorten the "Backend and browser tests" job in [`.github/workflows/ci.yml`](../.github/workflows/ci.yml), which sets the wall time of the whole CI run. It compares matrix sharding, pytest-xdist, cheaper fixtures, caching, affected-test selection and a browser/non-browser job split against this repository's test code. Primary sources only: the pytest-split, pytest-xdist, pytest-testmon, coverage.py, Playwright Python, Vite and GitHub Actions documentation, all read 2026-11-23. Each claim is labelled **Source** (what a document says), **Measured** (what I ran or read from this repository's CI) or **Inference** (my reasoning). **Unconfirmed** marks anything no source settles. Nothing was committed or pushed. This is supporting evidence, not implementation authority; adopt anything from it through a GitHub issue first.

Measurements used:

- **Measured (CI)**, from the GitHub API step timestamps of the last 11 `ci.yml` runs on 2026-11-23: the `uv run pytest -q` step took 9 min 19 s to 12 min 23 s. Everything before it (checkout, uv sync, npm ci, build, Playwright install) took 25 to 45 s, of which `playwright install --with-deps chromium` was about 20 s. The latest PR run reported 1033 passed in 704.94 s.
- **Measured (local)**, macOS, 10 cores, a temporary worktree of `origin/main` at `efa2eb5`, removed afterwards: `pytest -q -m browser --durations=60` ran 181 browser tests in 402 s wall, 156 s user CPU and 33 s system CPU. The 852 non-browser tests take about 14 s ([PR #201](https://github.com/KLTsai/next-is-you/pull/201)).
- **Measured (local)**: one rehearsal start, phase by phase: `npm run build` 0.3 s (warm), `pywrangler d1 migrations apply` 2.2 s, `pywrangler dev` to a 200 on `/api/healthz` 4.3 s. About 7 s per start.
- CI runs the suite 1.4 to 1.8 times slower than this machine (705 s versus about 416 s for the same 1033 tests).

## Verdict

**Recommended: shard the test job across 4 GitHub-hosted runners with pytest-split, behind one aggregating job that keeps the name "Backend and browser tests".** Fold the non-browser tests into the shards instead of giving them their own job.

- **Why this fits this repository.** Each shard is its own virtual machine, so every piece of shared state that broke pytest-xdist in PR #201 is separated without changing a test: the repository `dist/`, the files pywrangler writes in the project root, ports and CPU. Standard runners are free and unlimited for public repositories, and the Free plan allows 20 concurrent jobs. The current run uses 8.
- **Expected wall time.** **Inference**: the pytest step costs about 10.5 min of CI time today. Four balanced shards give about 2.6 min of tests each. Add about 0.5 to 0.8 min of per-shard setup, plus a few seconds where a shard repeats a module fixture (one Vite build, one rehearsal start of about 7 s locally, one Chromium launch). The job should finish in about **3.5 to 4 min** instead of 12.5. Six shards would give about 3 min. Beyond that, setup dominates and the 22 s single tests set the floor.
- **Effort.** Small. Add `pytest-split` to the dev group, commit a `.test_durations` file, add a 4-leg matrix job with `fail-fast: false`, add the aggregating job, and point `Summary` at it. No test or product code changes.
- **Risks.**
  - Matrix legs get their own check names. [`scripts/delivery_state.py`](../scripts/delivery_state.py) `GATES` requires a check named exactly "Backend and browser tests", and reports a commit as pending until it sees one. Renaming the job, or turning it into a bare matrix, would leave the Promote guard pending for every commit. The aggregating job avoids that.
  - The durations file goes stale. Tests missing from it are assigned the average time, so balance degrades gracefully; refresh it when shards drift apart.
  - **Unconfirmed**: the docs I read do not say how `needs.<job>.result` summarizes a matrix with mixed results. Check it in the implementing PR with one deliberately failing leg.
- **Worth doing next, separately.** Have `tests/test_rehearsal.py` share one rehearsal Worker per module, as `tests/test_organizer_page.py` already does. Each of its 14 tests starts its own server (about 7 s locally) and its own Chromium. That is about 100 s of the local run and probably 140 to 180 s of CI time. This shortens the local `npm run check` too, which sharding does not. The cost is a test-only reset path or per-test synthetic data, because several tests assume an empty dataset.
- **Not recommended.** pytest-xdist on one runner, pytest-testmon for PRs, caching Playwright browsers, and a separate non-browser job. The reasons are below.

## 1. What the browser tests share, and how often they start things

All **Measured** from the source on `origin/main` (`efa2eb5`) unless labelled.

Which tests are browser tests: [`tests/conftest.py`](../tests/conftest.py) marks every test in a module whose source contains `sync_playwright` or `pywrangler`. That gives 181 tests in 10 modules: `test_organizer_page.py` 148, `test_rehearsal.py` 14, `test_background_repaint.py` 8, and 1 or 2 each in the other seven.

How often a server and browser start:

| Module | Browser | Server |
| --- | --- | --- |
| `test_organizer_page.py` (148 tests: 37 tests x 2 backends x 2 screens) | One Chromium per module (`organizer_browser`, module scope). A new context per test. | Module-scoped `organizer_service`, parametrized `fake` and `rehearsal`: one `npx vite build` into a `tmp_path_factory` directory, and one rehearsal Worker for the whole module. |
| `test_rehearsal.py` (14) | `chromium.launch()` inside each test. | `rehearsal(tmp_path, port)` inside each test: one `npm run dev:rehearsal` per test, and two or three in the restart test. |
| `test_member_label_typing.py` (2) | Per test. | One rehearsal per test. |
| `test_worker_startup.py`, `test_worker_draft_rpc.py`, `test_held_service_runtime.py` | None or per test. | `pywrangler d1 migrations apply` plus `pywrangler dev`, per test, with `--persist-to` under `tmp_path`. |
| `test_local_acceptance*.py` | Per test. | In-process uvicorn on a thread. |

The phone screen (390 x 844, `is_mobile`, `has_touch`) is already in `SCREENS` in `test_organizer_page.py` on `origin/main`, which is why that module has 148 tests. A further viewport change elsewhere would add tests in the same way; sharding absorbs them, because pytest-split gives unknown tests the average duration.

The slowest single tests (local `--durations=60`): `test_held_native_configuration_and_recovery_hold_persist_across_restart` 22.5 s, `test_rehearsal_ui_retains_drafts_and_deduplicates_after_process_restart` 22.5 s, `test_rehearsal_member_label_typed_by_the_organizer_is_not_cleared` 11.2 s. The other `test_rehearsal.py` tests take 7.4 to 9.1 s each, and about 7 s of that is starting the rehearsal. The organizer page's rehearsal setup is 8.4 s, paid once. Its tests take 1.5 to 3.7 s each with the rehearsal backend and about 2.2 s with the fake one, on the phone screen.

Shared state that makes one machine unsafe for parallel runs:

1. **The repository `dist/`.** [`scripts/manual-rehearsal.sh`](../scripts/manual-rehearsal.sh) runs `npm run build` (that is, `vite build`) before every rehearsal, and [`wrangler.niy006.test.jsonc`](../wrangler.niy006.test.jsonc) serves `./dist/` as its assets. **Source** ([Vite build options](https://vite.dev/config/build-options)): "By default, Vite will empty the `outDir` on build if it is inside project root." **Inference**: a second rehearsal starting empties `dist/` while the first one is serving it. This matches the "503 from concurrent rehearsal servers and UI builds" seen with xdist in PR #201. `test_local_acceptance.py` and other tests that serve the repository `dist/` in-process are exposed to the same deletion.
2. **Files pywrangler writes in the project root.** After one run, the worktree held `python_modules/`, `pylock.toml`, `.venv-workers/` and `.wrangler/tmp/`, all git-ignored. **Inference**: every `pywrangler dev` or `migrations apply` reads and may rewrite them. Concurrent starts race on them. **Unconfirmed**: whether pywrangler rewrites them on every start or only when they are stale.
3. **Port choice.** Every server test binds port 0, reads the port number, closes the socket, then passes the number to a child process. **Inference**: under parallel load, two workers can be handed the same port before either child binds it.
4. **CPU.** Each rehearsal is a Node process plus workerd running Pyodide, next to Chromium. **Source** ([runner specs](https://docs.github.com/en/actions/reference/runners/github-hosted-runners)): `ubuntu-latest` for public repositories has 4 CPUs and 16 GB RAM. **Source** ([Playwright CI](https://playwright.dev/python/docs/ci)): Playwright's own runner defaults to one worker per core and warns that more "will cause unnecessary timeouts and failures". The "Playwright contexts disposed" failures in PR #201 are consistent with timeouts under contention or a server dying under a test. **Inference**, not reproduced.

Per-test isolation that already holds: each rehearsal or wrangler test gives `--persist-to` (local D1 and Durable Object state) a directory under its own `tmp_path`. `test_organizer_page.py` builds its fake-backend UI into its own temporary directory. Browser contexts are isolated by design. **Source** ([Playwright browser contexts](https://playwright.dev/python/docs/browser-contexts)): contexts are "fast and cheap to create and are completely isolated, even when running in a single browser."

## 2. Option: matrix sharding across runners (recommended)

**Source** ([pytest-split](https://jerry-git.github.io/pytest-split/)): `pytest --store-durations` writes `.test_durations`, which "should be stored in the repo". `--splits N --group i` runs one group. A test with no stored duration is given the average time, and re-storing is recommended after major suite changes. The `least_duration` algorithm "assigns each test to the group with the smallest current duration" (rated "Better"). The default, `duration_based_chunks`, keeps contiguous ranges (rated "Good"). The [README](https://github.com/jerry-git/pytest-split) presents it as an alternative where "pytest-xdist ... is not suitable for all use cases", and links a [GitHub Actions demo](https://github.com/jerry-git/pytest-split-gh-actions-demo).

**Source** ([GitHub Actions matrix](https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/run-job-variations); [workflow syntax](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax)): a matrix creates one job per combination. `fail-fast` "defaults to `true`": "GitHub will cancel all in-progress and queued jobs in the matrix if any job in the matrix fails." `max-parallel` defaults to as many as runners allow. A job that needs a failed or skipped job is skipped unless its `if` uses an expression such as `always()`. **Source** ([contexts](https://docs.github.com/en/actions/reference/workflows-and-actions/contexts)): `needs.<job_id>.result` is `success`, `failure`, `cancelled` or `skipped`. **Source** ([Actions limits](https://docs.github.com/en/actions/reference/limits)): Free plan, 20 concurrent standard-runner jobs, and a matrix can generate at most 256 jobs. **Source** ([runner specs](https://docs.github.com/en/actions/reference/runners/github-hosted-runners)): "Use of the standard GitHub-hosted runners is free and unlimited on public repositories."

How it fits this repository:

- **Required checks.** **Measured**: the `main` ruleset requires one check, `Summary`, and `Summary` lists its `needs`. Legs named `Backend and browser tests (1)` and so on would not match the `GATES` tuple in `scripts/delivery_state.py`. `_read_checks` would then return "pending" for every commit, because fewer than seven gates are seen. `tests/test_delivery_state.py` also pins the Summary table's names. Keep one job with `name: Backend and browser tests`, give it `needs: [the matrix job]` and `if: always()`, and make it fail unless the matrix result is `success`. Then `GATES`, `Summary`, `staging-order`, `deploy-staging` and `release-please` keep working unchanged, apart from `needs` lists. **Inference.**
- **Set `fail-fast: false`.** The workflow's own comment says each gate reports its own result. With the default, one red shard cancels the others and hides their failures.
- **Repeated module fixtures.** If a module's tests land in several shards, each of those shards pays the module fixture again. For `test_organizer_page.py` that is one Vite build, about 7 s of rehearsal start and one Chromium launch, on each of the two backends. `least_duration` spreads tests more evenly but splits modules more often. `duration_based_chunks` keeps contiguous ranges, so a module is cut at most at the group edges. **Inference**: at about 8 s per extra start, either is fine; start with `least_duration` and compare shard times.
- **Durations file.** Generate it once with `--store-durations` and commit it. Local durations are a usable proxy, because what matters is the ratio between tests. Shards stay correct with a stale file; they only become uneven.
- **Shards never share a machine,** so the shared `dist/`, pywrangler files and port race in section 1 do not matter across shards. Inside one shard the tests run one at a time, as today.
- **Optional:** upload each shard's JUnit XML or `--durations` output as an artifact, so the durations file can be refreshed from real CI timings.

## 3. Option: make the tests xdist-safe

**Source** ([pytest-xdist how-to](https://pytest-xdist.readthedocs.io/en/stable/how-to.html)): the `worker_id` fixture and the `PYTEST_XDIST_WORKER` variable name the worker (`"gw2"`). Session-scoped fixtures run once per worker. Running one only once needs a file lock, for which the docs give an example. **Source** ([distribution](https://pytest-xdist.readthedocs.io/en/stable/distribution.html)): `--dist loadscope` groups by module or class, `loadfile` by file, `loadgroup` by `xdist_group` mark. **Source** ([Playwright test runners](https://playwright.dev/python/docs/test-runners)): `--numprocesses auto` is supported, with "If set too high, you may notice unexpected behavior."

What it would take here: each rehearsal would need its own build output. That means passing `--assets <tmp>/dist` to `pywrangler dev`, as `test_worker_startup.py` already does, instead of `npm run build` into the repository. Tests that serve the repository `dist/` would need it built once, before any worker starts. The pywrangler project-root files would need generating once before the workers start, or proof that concurrent starts leave them alone. Ports would need a retry or a reservation that holds until the child process binds.

**Measured** (PR #201, local, 10 cores): `-n auto` cut the run to about 170 s, but two runs had 35 and 46 failures. **Inference**: on a 4-CPU runner, with workerd and Chromium per worker, the speed-up would be smaller, and the failures from timeouts would be more likely. Larger runners would help, but **Source** ([Actions billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions)): "Larger runners are billed for public repositories" and require a paid plan, so they fall outside free minutes. Sharding gets the parallelism without fixing any of this. xdist could later run inside each shard (`-n 2`) once the tests are safe, but that is not needed to reach about 4 min.

## 4. Option: lower the cost per test

- **Share the rehearsal Worker in `test_rehearsal.py`.** **Measured**: a rehearsal start is about 7 s locally, and each of the module's 14 tests starts at least one, plus its own Chromium. `test_organizer_page.py` shows the pattern: one server per module, each page seeds its own visits, and active visits are stopped in teardown. **Inference**: about 100 s off the local run and about 140 to 180 s off CI's total. It helps local `npm run check` (about 7 min today), which sharding does not. The cost is an isolation design. Tests such as "empty dashboard" assume a fresh dataset, and the restart test must keep its own server. The worker's test controls (`/__niy006_test/{operation}` in `src/worker.py`) have `seed`, `observation`, `stop` and session operations, but no reset. Restart tests keep a dedicated server either way.
- **Share one Chromium across modules.** Launching per test is a smaller cost, under a second each. **Source** ([Playwright test runners](https://playwright.dev/python/docs/test-runners)): pytest-playwright makes `browser` session-scoped and `context`/`page` function-scoped, which is the shape to copy.
- **Fixed sleeps.** **Measured**: 29 `wait_for_timeout` or `time.sleep` calls in `tests/`. Most are 10 to 300 ms poll steps. The larger ones (`test_member_label_typing.py` 2.5 s, `test_background_repaint.py` 0.5 to 1.5 s) wait across a repaint interval to show that something stays put, so they carry meaning. **Inference**: replacing them saves a few seconds at most. Not worth it for wall time.
- **User CPU is a third of wall time** (156 s of 402 s locally). **Inference**: the suite mostly waits on servers, polling and timers, not on computation. That is why splitting it across machines scales almost linearly.

## 5. Option: caching

- **Source** ([Playwright CI](https://playwright.dev/python/docs/ci)): "Caching browser binaries is not recommended", because restoring takes about as long as downloading, and on Linux the system dependencies "are not cacheable". **Measured**: the install step takes about 20 s.
- **Source** ([setup-uv](https://github.com/astral-sh/setup-uv)): `enable-cache` defaults to `auto`, which is on for GitHub-hosted runners except on release, tag push, `pull_request_target` and `workflow_run` events. **Measured**: `ci.yml` already uses `setup-node` with `cache: npm`, and `uv sync` plus `npm ci` took about 1 s each in the latest run.
- **Inference**: at most about 20 s to gain, and Playwright advises against the largest piece. Not worth changing. Each shard pays the 20 s install, which the estimate above already includes.

## 6. Option: run only affected tests on PRs (pytest-testmon)

**Source** ([testmon.org](https://testmon.org/)): testmon uses Coverage.py to record which code each test runs and selects tests whose code changed. It cannot see static files "such as txt, xml" or external services. **Source** ([Determining affected tests](https://testmon.org/blog/determining-affected-tests/)): its limits "are pretty much the same as limits of coverage.py". **Source** ([coverage.py subprocesses](https://coverage.readthedocs.io/en/latest/subprocess.html)): subprocesses are not measured unless coverage is started in them. **Source** ([testmon in CI](https://testmon.org/blog/testmon-in-ci/)): the author recommends a hosted dependency database over sharing or caching `.testmondata` between runners.

**Inference**, for this repository: the browser tests exercise code that coverage in the pytest process never sees. That includes the Worker's Python running inside workerd/Pyodide under `pywrangler dev`, the TypeScript frontend built by Vite, the migrations SQL and the wrangler config. A frontend or migration change could deselect exactly the browser tests that prove it. The repository's rules ask for labelled proof per change, so a gate that can skip the relevant test silently is a poor fit. Not recommended for the required gate. At most it could be a local convenience.

## 7. Option: separate jobs for browser and non-browser tests

**Measured**: non-browser pytest is about 14 to 16 s locally. **Inference**: taking it off the critical path saves under 30 s of CI time, while adding a gate name to `GATES`, `Summary` and the deploy `needs`. Once the browser tests are sharded, the shards absorb the non-browser tests too: pytest-split balances them like any other test. A separate job adds nothing.

## Sources

- pytest-split documentation: https://jerry-git.github.io/pytest-split/
- pytest-split README: https://github.com/jerry-git/pytest-split
- pytest-split GitHub Actions demo: https://github.com/jerry-git/pytest-split-gh-actions-demo
- pytest-xdist, how-to: https://pytest-xdist.readthedocs.io/en/stable/how-to.html
- pytest-xdist, distribution modes: https://pytest-xdist.readthedocs.io/en/stable/distribution.html
- pytest-testmon home: https://testmon.org/
- pytest-testmon, Determining affected tests: https://testmon.org/blog/determining-affected-tests/
- pytest-testmon, CI environments and testmon: https://testmon.org/blog/testmon-in-ci/
- coverage.py, measuring subprocesses: https://coverage.readthedocs.io/en/latest/subprocess.html
- Playwright Python, test runners: https://playwright.dev/python/docs/test-runners
- Playwright Python, continuous integration: https://playwright.dev/python/docs/ci
- Playwright Python, browser contexts: https://playwright.dev/python/docs/browser-contexts
- Vite, build options: https://vite.dev/config/build-options
- GitHub Actions, GitHub-hosted runners: https://docs.github.com/en/actions/reference/runners/github-hosted-runners
- GitHub Actions, larger runners: https://docs.github.com/en/actions/reference/runners/larger-runners
- GitHub Actions billing: https://docs.github.com/en/billing/concepts/product-billing/github-actions
- GitHub Actions, limits: https://docs.github.com/en/actions/reference/limits
- GitHub Actions, running variations of jobs (matrix): https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/run-job-variations
- GitHub Actions, workflow syntax: https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax
- GitHub Actions, contexts: https://docs.github.com/en/actions/reference/workflows-and-actions/contexts
- GitHub Actions, dependency caching: https://docs.github.com/en/actions/reference/workflows-and-actions/dependency-caching
- setup-uv: https://github.com/astral-sh/setup-uv
- This repository: PR #201 (xdist trial and per-module timings): https://github.com/KLTsai/next-is-you/pull/201
