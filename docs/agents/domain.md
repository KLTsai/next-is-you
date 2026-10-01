# Domain Docs

How the engineering skills should consume this repo's domain documentation when exploring the codebase.

## Before exploring, read these

- Root `CONTEXT.md`, when present.
- ADRs in `docs/adr/` that touch the area being changed.

If either is absent, proceed silently. Do not suggest creating it upfront. The `/domain-modeling` skill, reached via `/grill-with-docs` and `/improve-codebase-architecture`, creates domain records lazily when terms or decisions are actually resolved.

## File structure

This is a single-context product with a Python backend and a Vite frontend, not a large monorepo.

```text
/
|-- CONTEXT.md       # Created lazily
|-- docs/adr/        # Created lazily
|-- src/next_is_you/
|-- frontend/
|-- migrations/
`-- tests/
```

Do not create `CONTEXT-MAP.md` or multiple contexts just for setup.

## Use the glossary's vocabulary

When an issue title, refactor proposal, hypothesis, or test name uses a domain concept, use the term defined in `CONTEXT.md`. Avoid synonyms the glossary explicitly rejects.

If a concept is missing, reconsider whether it belongs to this product; otherwise note the gap for `/domain-modeling`.

## Flag ADR conflicts

Surface any proposed conflict with an existing ADR explicitly, with the ADR identifier and reason to revisit it. Never silently override an accepted decision.

## Existing authoritative evidence

- `src/next_is_you/` implements the domain and `migrations/` records schema history.
- `docs/PRE-LIVE-CHECKLIST.md` owns live-provider gates.
- `research/NIY-021-findings-summary.md` records hospital-source evidence and its limits.
- `docs/archive/tickets/` preserves historical accepted decisions; GitHub Issues owns active scope and acceptance.

Historical completion or a passing fixture does not establish live LINE delivery, hospital freshness, or deployed storage behavior.
