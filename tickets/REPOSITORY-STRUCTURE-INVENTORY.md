# Repository inventory and disposition proposal

## Scope and handling

This inventory uses tracked paths and repository references in the isolated task worktree, plus a Firstmate read-only scan report received on 2026-09-28. It records recommendations only. No existing content was deleted, moved, archived, renamed, or rewritten. Firstmate reports that ignored `research/private/` material is present in the primary checkout but absent from this task worktree. Its contents and exact file list were not inspected here.

The detailed cleanup review is tracked by [NIY-015](NIY-015-repository-structure-review.md). Runtime configuration recommendations are tracked separately by [NIY-009](NIY-009-runtime-configuration-secrets.md).

## Tracked top-level directories

| Area | Recommendation | Evidence and impact | Proposed owner |
| --- | --- | --- | --- |
| `frontend/` | Keep | `vite.config.ts` uses this as the Vite root; `frontend/src/` contains the UI entry point and stylesheet. `package.json` builds it into `dist/`. Removing it breaks the UI build and served assets. | UI maintainer |
| `src/` | Keep | Contains `src/worker.py` (the Wrangler `main` entry point) and the imported `src/next_is_you/` application package. `pyproject.toml` adds `src` to the test import path. | Application maintainer |
| `migrations/` | Keep | Both Wrangler configs set `migrations_dir` to this folder; schema and scheduler tests read these SQL files. Moving it requires coordinated config and test updates. | Persistence maintainer |
| `tests/` | Keep | `pyproject.toml` sets it as pytest's test root. The tests cover domain, routes, persistence, scheduling, and Worker behavior. | Application maintainer |
| `tests/fixtures/hospitals/` | Keep | `tests/test_hospital_adapters.py` reads the HTML and JSON samples. NIY-004 identifies them as synthetic source-shaped fixtures; they are test inputs, not patient records or verified live connectors. | Hospital-adapter maintainer |
| `tickets/` | Keep | `tickets/README.md` is the checked-in backlog index and the ticket files are the current local implementation authority. There is no external issue tracker in use. | Ticket owners; Captain for backlog policy |
| `research/` | Keep | Its tracked `README.md` links implementation tickets and identifies the boundary between implementation authority and supporting evidence. | Research/documentation owner |
| `research/private/` | Needs Captain decision | Firstmate reports ignored material in this directory in the primary checkout; it is absent from this task worktree. The tracked `research/README.md` identifies `research/private/mvp-spec-review-2026-09-27-v2.md` as the current spec and `research/private/README.md` as its supporting/archive index. That index points to supporting and archived material. No private contents, archive entries, or additional taxonomy are copied into this report. Retention and any archive decision stay with Captain. | Captain |

No tracked prototype directory or tracked archive directory was found. No archive recommendation is made for existing tracked content. Any additional untracked or ignored planning material requires a separate Captain inventory before disposition.

## Important root files and nested areas

| Area | Recommendation | Evidence and impact | Proposed owner |
| --- | --- | --- | --- |
| `wrangler.jsonc` and `wrangler.niy006.test.jsonc` | Keep | Both define the same Worker entry point, assets, D1, and Durable Object shape, but use distinct database names/IDs; the NIY-006 test config alone enables `NIY006_LOCAL_TEST_MODE`. Consolidating them could erase test isolation. | Worker/runtime owner |
| `package.json`, `package-lock.json`, `vite.config.ts` | Keep | Define npm commands, pinned frontend dependency resolution, and the Vite output at `dist/`. `npm run dev:local` builds before starting Uvicorn. | Frontend/runtime owner |
| `pyproject.toml`, `uv.lock` | Keep | Define Python version/dependencies, pytest paths, and locked Python dependencies. | Python application owner |
| `.env_template` and `.gitignore` | Keep | The template contains blank values; ignore rules cover `.env`, `.env.*`, and Wrangler `.dev.vars` files while the underscore-named template remains trackable. See the configuration gap below and NIY-009. | Runtime/security owner |
| `README.md` and `AGENTS.md` | Keep | The README documents the local Worker command; AGENTS.md establishes repository language and collaboration rules. Neither is a generated artifact. | Captain/documentation owner |
| `migrations/*.sql` | Keep | These are schema history consumed by Wrangler and tests. Rewriting or folding migrations can invalidate existing D1 databases. | Persistence maintainer |
| `tests/fixtures/hospitals/*` | Keep | Synthetic HTML/JSON files support deterministic adapter tests; deleting them removes the only fixture inputs for those shapes. | Hospital-adapter maintainer |
| Ticket status index | Needs Captain decision | `tickets/README.md` lists NIY-005 and NIY-006 as `Open`, but their ticket bodies say `Complete`. The disagreement makes the backlog status ambiguous. Existing status values were left unchanged. | Captain and ticket owners |
| CI workflow/configuration | Needs Captain decision | No tracked `.github/` workflow or other CI configuration appears in `git ls-files`; NIY-008 remains the ticket for CI and local acceptance. Decide CI ownership and provider within NIY-008. | NIY-008 owner; Captain for provider |

## Generated and ignored local outputs

The worktree contains ignored `dist/`, `node_modules/`, `.venv/`, `.venv-workers/`, `.pytest_cache/`, and Python `__pycache__/` directories. They are not part of the tracked inventory. `.gitignore`, Vite output settings, and the package/Python lockfiles establish their generated or reproducible roles. Firstmate's scan also reports ignored `.DS_Store` files; their paths were not inspected or recorded here.

| Area | Recommendation | Evidence and impact | Proposed owner |
| --- | --- | --- | --- |
| `dist/` | Keep | Vite writes built assets here; the local Worker fallback and Wrangler assets binding serve these files. It is reproducible but needed for the current local asset path. | Frontend/runtime owner |
| `node_modules/`, `.venv/`, `.venv-workers/` | Delete candidate | Ignored local dependency environments can be regenerated from `package-lock.json`, `uv.lock`, and `pyproject.toml`. Removing an environment interrupts any process using it and requires reinstalling dependencies. | Captain or worktree operator, after confirming no active process depends on it |
| `.pytest_cache/`, `src/**/__pycache__/`, `tests/**/__pycache__/` | Delete candidate | Ignored test/interpreter caches are reproducible and are not test fixtures. Removal affects no tracked source but may interrupt an active run if done concurrently. | Routine worktree cleanup owner, after confirming no active run |
| Ignored `.DS_Store` files | Delete candidate | Firstmate's read-only scan reports ignored macOS directory metadata files. They are not application inputs; this inventory did not inspect their locations. | Captain or worktree operator, after reviewing the reported locations |

These are cleanup candidates only. This task did not remove them. Do not clean a shared or active worktree without its owner's confirmation.

## Runtime configuration evidence

The application currently reads the following values from Worker bindings:

- `src/worker.py` builds `LineLoginSettings` from `LINE_LOGIN_CHANNEL_ID`, `LINE_LOGIN_CHANNEL_SECRET`, `LINE_LOGIN_REDIRECT_URI`, `SESSION_SIGNING_SECRET`, and `ORGANIZER_LINE_SUBJECTS` (`src/worker.py:505-520`).
- `src/next_is_you/send_gate.py` reads `LINE_CHANNEL_ACCESS_TOKEN` for production pushes and `NIY006_LOCAL_TEST_MODE` for the synthetic test path (`src/next_is_you/send_gate.py:229-247, 413-421`).
- `ASSETS`, `DB`, and `SEND_GATE` are platform bindings: they are read by the Worker and declared in the Wrangler configs, rather than being scalar `.env` values.
- `package.json` starts `uvicorn worker:app` without an env-file option. The app reads request-scoped Worker bindings and contains no process-environment or dotenv loader. Copying `.env_template` to `.env` therefore does not currently configure `npm run dev:local`.
- `.env_template` currently names only `LINE_CHANNEL_ACCESS_TOKEN` and `NIY006_LOCAL_TEST_MODE`, so it omits the five LINE Login/session settings above. `.gitignore` ignores `.env`, `.env.*`, `.dev.vars`, and `.dev.vars.*`; `.env_template` is tracked and is not matched by `.env.*`.
- No root `.env` file was present in the task worktree. No credentials were created or recorded.

Recommendation: implement the application-wide template and explicit local loading in NIY-009. Keep `LINE_LOGIN_CHANNEL_SECRET`, `SESSION_SIGNING_SECRET`, and `LINE_CHANNEL_ACCESS_TOKEN` in local-only `.env` for development and provision them as Cloudflare Worker secrets in production. Keep the test-mode switch isolated to the local test Wrangler config. Do not treat the local `.env` as a deployment mechanism.

## Captain decisions still open

- Decide whether the ignored local dependency environments and caches should be cleaned, and when it is safe to do so. They were left untouched.
- Decide whether the private spec/archive material present in the primary checkout should remain in place, be archived, or be handled another way. It is absent from this task worktree; no private source content was inspected or changed.
- Decide whether and when to remove the ignored `.DS_Store` files reported by Firstmate. Their locations were not inspected, and they were left untouched.
- Decide CI provider/ownership through NIY-008; no workflow was added here.
- Reconcile the NIY-005 and NIY-006 status mismatch between the ticket index and their ticket bodies. No existing statuses were changed.
- Review NIY-009's proposed local `.env` workflow and production secret boundary before implementation. No runtime values or secrets were changed.
