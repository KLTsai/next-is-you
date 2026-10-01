# NIY-015: Repository structure review and disposition

Status: Complete

## Goal

Review the documented repository inventory and decide whether any cleanup, consolidation, or archival work should be scheduled, without changing existing content before Captain review.

## Acceptance criteria

- Review [the repository inventory and disposition proposal](REPOSITORY-STRUCTURE-INVENTORY.md), including its tracked paths, source/import relationships, build and test configuration, migrations, tickets, research, fixtures, generated outputs, and private or planning references.
- Captain records a keep, archive, consolidate, or delete decision for each proposed cleanup candidate and any private/planning material requiring a retention decision.
- Any approved cleanup is handled by a separate ticket naming exact paths, tracking/privacy impact, ownership, and a recovery plan. No content is moved, renamed, archived, or deleted until that decision is recorded.
- Keep this ticket limited to repository organization; do not change application behavior, requirements, or secrets.

## Captain decision update

Captain selected route A for local rebuildable artifact cleanup. This withdraws any prior conclusion to keep all local environments, generated caches, and `.DS_Store` files by default. Those ignored and reproducible local artifacts are now scoped for cleanup in [NIY-018](NIY-018-local-artifact-cleanup.md).

The original retention boundaries remain unchanged for research private data and archived planning material. `research/private/` and its private/archive index contents are not inspected, copied, deleted, rewritten, or moved by the local artifact cleanup route. Tracked tests, fixtures, migrations, runtime templates, and Wrangler test configuration remain repository content unless a separate ticket says otherwise.

The approved local cleanup is complete under [NIY-018](NIY-018-local-artifact-cleanup.md). The selected generated environments and caches and the specified `.DS_Store` files were removed. `.wrangler/` and local D1 state, `research/private/`, tracked tests, fixtures and migrations, `.env_template`, and the local untracked `pylock.toml` were preserved.

## Related tickets

- [NIY-009: Runtime configuration and secrets management](NIY-009-runtime-configuration-secrets.md) owns the runtime configuration and local secrets workflow.
- [NIY-018: Local rebuildable artifact cleanup](NIY-018-local-artifact-cleanup.md) owns the exact local cleanup scope selected from this review.
