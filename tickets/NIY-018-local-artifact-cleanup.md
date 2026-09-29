# NIY-018: Local rebuildable artifact cleanup

Status: Complete

## Goal

Clean only selected ignored, rebuildable local artifacts from this repository worktree after confirming no local process is using the affected state. This is local file organization only: it does not change product behavior, connect to hospitals, connect to LINE, connect to Cloudflare, deploy, push, or publish.

## Allowed cleanup scope

Delete only these ignored or rebuildable artifacts when they exist:

- `.venv/`
- `.venv-workers/`
- `node_modules/`
- `python_modules/`
- `dist/`
- `.pytest_cache/`
- all `__pycache__/` directories under the repository
- `.DS_Store`
- `frontend/.DS_Store`
- `research/.DS_Store`

Do not delete or rewrite any file, directory, cache, environment, database, fixture, migration, source file, ticket, research file, or configuration that is not listed above.

## Protected paths and files

The cleanup must preserve:

- `.wrangler/` and all local D1 state under it
- `research/private/` and all private or archived planning material
- tracked tests, fixtures, and migrations
- `wrangler.niy006.test.jsonc`
- `.env_template`
- the tracked `.gitignore`, including the `python_modules/` ignore rule
- local uncommitted `pylock.toml`, when present

The cleanup must not read `research/private/` contents and must not create `.env` or any other local secret file.

## Preconditions

- Confirm no Wrangler, dev server, test runner, Python process, Node process, Vite process, or other local process is using the worktree state targeted by this cleanup.
- If any such process is active, stop it safely before cleanup.
- If a process cannot be safely stopped, stop this ticket and report the blocker without deleting anything.
- If the target list found locally does not match the allowed cleanup scope above, stop and report the mismatch without expanding the cleanup scope.

## Acceptance criteria

- The listed rebuildable artifacts are absent after cleanup: `.venv/`, `.venv-workers/`, `node_modules/`, `python_modules/`, `dist/`, `.pytest_cache/`, every `__pycache__/`, and the root, `frontend/`, and `research/` `.DS_Store` files.
- Protected items still exist when they existed before cleanup, including `.wrangler/` local D1 state, `research/private/`, tracked tests, fixtures, migrations, `wrangler.niy006.test.jsonc`, `.env_template`, `.gitignore`, and `pylock.toml`.
- Tracked files are unchanged after cleanup.
- The tracked `.gitignore` remains unchanged after cleanup, and local uncommitted `pylock.toml` remains in its original local state when present.
- No `.env` file is created, no private research content is read, no live hospital, LINE, or Cloudflare request is made, and no deployment, push, or publication occurs.

## Completion record

The approved local cleanup is complete. Removed artifacts:

- `.venv/`, `.venv-workers/`, `node_modules/`, `python_modules/`, and `dist/`
- `.pytest_cache/` and all repository `__pycache__/` directories
- `.DS_Store`, `frontend/.DS_Store`, and `research/.DS_Store`

Preserved `.wrangler/` and its local D1 state, `research/private/`, tracked tests, fixtures and migrations, `.env_template`, and the local untracked `pylock.toml`.

## Related tickets

- [NIY-015: Repository structure review and disposition](NIY-015-repository-structure-review.md) records the repository cleanup decision that opened this ticket.
- [NIY-019: Ignore local Python module cache](NIY-019-ignore-python-modules.md) records the tracked ignore rule that keeps `python_modules/` local and reproducible.
