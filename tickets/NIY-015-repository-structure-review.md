# NIY-015: Repository structure review and disposition

Status: Open

## Goal

Review the documented repository inventory and decide whether any cleanup, consolidation, or archival work should be scheduled, without changing existing content before Captain review.

## Acceptance criteria

- Review [the repository inventory and disposition proposal](REPOSITORY-STRUCTURE-INVENTORY.md), including its tracked paths, source/import relationships, build and test configuration, migrations, tickets, research, fixtures, generated outputs, and private or planning references.
- Captain records a keep, archive, consolidate, or delete decision for each proposed cleanup candidate and any private/planning material requiring a retention decision.
- Any approved cleanup is handled by a separate ticket naming exact paths, tracking/privacy impact, ownership, and a recovery plan. No content is moved, renamed, archived, or deleted until that decision is recorded.
- Keep this ticket limited to repository organization; do not change application behavior, requirements, or secrets.

## Related tickets

- [NIY-009: Runtime configuration and secrets management](NIY-009-runtime-configuration-secrets.md) owns the runtime configuration and local secrets workflow.
