# NIY-019: Ignore local Python module cache

Status: Complete

## Goal

Track the repository ignore rule for `python_modules/` so the local rebuildable artifact listed in [NIY-018](NIY-018-local-artifact-cleanup.md) stays out of version control while remaining safely reproducible from tracked project dependency inputs.

## Scope

- Add `python_modules/` to the tracked root `.gitignore`.
- Preserve the `.gitignore` final newline.
- Do not commit `pylock.toml`; when present, it remains a protected local uncommitted file for NIY-018 cleanup.
- Do not delete local artifacts, inspect `research/private/`, create `.env`, contact hospitals, LINE, or Cloudflare, deploy, push, or publish.

## Acceptance criteria

- `git check-ignore python_modules/` confirms `python_modules/` is ignored by `.gitignore`.
- `.gitignore` has a final newline and no unrelated ignore-rule churn.
- `pylock.toml` is not staged or committed.
- `git diff --check` passes.

## Related tickets

- [NIY-018: Local rebuildable artifact cleanup](NIY-018-local-artifact-cleanup.md) owns the later local-only cleanup operation.
