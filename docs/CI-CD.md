# CI / CD

This repository has three independent gates. Each answers a different question
and fails in a different way.

| Gate | Triggered by | Question it answers | On failure |
| --- | --- | --- | --- |
| CI (`.github/workflows/ci.yml`) | `push` and `pull_request` | Does this change build, lint, type-check and pass the test suite? | Blocks merge |
| Release Please (`.github/workflows/release-please.yml`) | `push` to `main` | What would the next release look like? | Release PR is not updated |
| Production deploy (`.github/workflows/production-deploy.yml`) | `push` tag `v*.*.*` | Should this exact version be deployed to Cloudflare? | Deployment is held |

CI stays the same as before. The two new workflows cover versioning and
deployment.

## Everyday flow

1. Write code on a feature branch; open a PR.
2. CI runs on the PR. When it is green and reviewed, merge to `main`.
3. On every merge to `main`, Release Please updates (or opens) a single PR
   titled `chore(main): release X.Y.Z`. It bumps `package.json`, rewrites
   `CHANGELOG.md`, and refreshes `.github/.release-please-manifest.json`.
4. When you want to publish a release, merge that Release PR. Release Please
   creates a Git tag `vX.Y.Z` and a GitHub Release.
5. The tag triggers the production deploy workflow, which waits in the
   `production` GitHub Environment for your manual approval.
6. Approve. The workflow applies pending D1 migrations against the remote
   database, then deploys the Worker.
7. The GitHub Release page records the deploy status; the Cloudflare dashboard
   shows the new deployment under Workers & Pages.

Nothing else about the trunk-based workflow changes.

## What counts as a releasable change

Release Please reads the merge commit messages between the previous tag and
`main`. Follow Conventional Commits:

- `feat: ...` triggers a minor bump (`0.1.0` -> `0.2.0`)
- `fix:` and `perf:` trigger a patch bump (`0.1.0` -> `0.1.1`)
- A `!` suffix (`feat!: ...`) or `BREAKING CHANGE:` footer triggers a major
  bump (`0.1.0` -> `1.0.0`)
- `docs:` is shown in the changelog but does not bump the version on its own
- `chore:`, `refactor:`, `test:`, `build:`, `ci:`, `style:` are hidden from the
  changelog and do not trigger a release

If a window has no `feat`, `fix` or `perf`, no Release PR is opened. That is
expected.

## Required GitHub configuration

### `production` environment

Set in **Settings -> Environments -> production**:

- **Required reviewers**: at least one maintainer. The deploy job pauses until
  one of them approves.
- **Deployment branches and tags**: only tags matching `v*.*.*` may deploy.
- **Environment secrets**:
  - `CLOUDFLARE_API_TOKEN`: scoped token with
    `Account - Workers Scripts - Edit`, `Account - D1 - Edit`,
    `Account - Account Settings - Read`, limited to the project account.
  - `CLOUDFLARE_ACCOUNT_ID`: the Cloudflare account id.

### Repository settings

- Enable "Require status checks to pass before merging" on `main` with the
  existing `deterministic-gates` CI job as the required check.
- Enable "Require a pull request before merging" so Release Please can produce
  its own PR instead of pushing directly.

## Cloudflare-side rules

### D1 migrations must be forward-only

The deploy workflow applies migrations *before* the Worker is deployed. A
rollback of the Worker does not reverse the migration. Every migration must
therefore be designed so the previous Worker version keeps working against the
new schema. The usual pattern is:

1. Release N adds the new column or table, writes to both old and new, reads
   from old.
2. Release N+1 switches reads to the new location.
3. Release N+2 removes the old location (only after N and N+1 are stable).

Never drop or rename a column in the same migration that stops writing to it.

### Durable Object class changes

The Worker owns `SystemSendGate`. Cloudflare tracks every known DO class per
Worker. Any change to that set must be declared in the `migrations` array in
`wrangler.production.jsonc`:

- Add a new DO class:
  `{ "tag": "vN", "new_sqlite_classes": ["NewClass"] }`
- Rename an existing class:
  `{ "tag": "vN", "renamed_classes": [{ "from": "OldClass", "to": "NewClass" }] }`
- Delete a class:
  `{ "tag": "vN", "deleted_classes": ["GoneClass"] }`

Renaming without declaring the rename deletes the old class's stored data.
This is not reversible.

### Secrets never pass through GitHub Actions

Application secrets (LINE channel secret, organizer allowlist, signing
secret, any future API keys) live only in Cloudflare. Set them from the
maintainer's machine:

```sh
uv run python -m pywrangler secret put <NAME> --config wrangler.production.jsonc
```

List current names (values are never returned):

```sh
uv run python -m pywrangler secret list --config wrangler.production.jsonc
```

The inventory of names and their purpose is maintained in `docs/SECRETS.md`.

Only two GitHub secrets exist (both inside the `production` environment):
`CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID`. Nothing else should be
added.

## Rollback

### Option A: re-run a prior tag (recommended)

1. Open **Actions -> Production deploy**.
2. Find the run for the tag you want to go back to (`v0.3.1` for example).
3. Click **Re-run all jobs** and approve the environment prompt.

This replays the full deploy, including migrations. Because migrations are
forward-only, re-running an older tag will not undo schema changes; only the
Worker is swapped back.

### Option B: emergency Worker rollback (fastest, local)

From the maintainer's machine:

```sh
uv run python -m pywrangler rollback --config wrangler.production.jsonc
```

This rolls the Worker back to the previous Cloudflare deployment without
touching the database. Use only when a tag re-run is too slow.

### What rollback cannot do

- It does not revert D1 schema. If a release broke on a migration, you must
  write a forward migration that repairs the schema.
- It does not revert Durable Object state.
- It does not restore secrets you have overwritten with `pywrangler secret
  put`.

Treat the pre-live checklist (`docs/PRE-LIVE-CHECKLIST.md`) and the hospital /
LINE integration gates as the real safety net; CI/CD can only verify what the
test suite verifies.

## Local Wrangler configuration

The committed `wrangler.production.jsonc` is the canonical production
configuration. The historical `.wrangler.production.jsonc` (gitignored) is
kept as a local backup during the transition. Keep them in sync, or retire
the gitignored copy once you are comfortable with the committed one.

## Operational calendar

- **First release**: merge the first Release PR to tag `v0.1.1` (or higher,
  depending on commit types). Approve the deploy. Verify the Worker and D1
  in the Cloudflare dashboard. Re-run `docs/PRE-LIVE-CHECKLIST.md` for any
  gate affected by the change.
- **Routine releases**: merge Release PR when a batch of changes is ready.
  There is no cadence requirement; releases are user-driven.
- **Hotfix path**: push a `fix:` commit to `main`, let Release Please open or
  update the Release PR, merge it, approve the deploy. The hotfix flows
  through the same gates as every other release.
