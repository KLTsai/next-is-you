# Issue tracker: GitHub

Issues and specs for this repo live as GitHub issues in `KLTsai/next-is-you`. Use `gh-axi` for GitHub operations.

## Conventions

Commands below match the installed `gh-axi issue --help`. Pass `-R KLTsai/next-is-you` explicitly. Use a body file for multi-line text; do not interpolate issue or comment bodies into shell code.

- Create an issue: `gh-axi issue create -R KLTsai/next-is-you --title "..." --body-file <path>`.
- Read an issue and its comments: `gh-axi issue view <number> -R KLTsai/next-is-you --comments --full`.
- List issues: `gh-axi issue list -R KLTsai/next-is-you --state open --limit 100`. Add supported `--label`, `--assignee`, or `--state` filters as needed. Increase `--limit` or use `gh-axi api GET /repos/KLTsai/next-is-you/issues --paginate` when needed; API issue listings also include pull requests, so exclude those entries.
- Comment: `gh-axi issue comment <number> -R KLTsai/next-is-you --body-file <path>`.
- Apply or remove labels: `gh-axi issue edit <number> -R KLTsai/next-is-you --add-label "..."` or `--remove-label "..."`.
- Close completed work: `gh-axi issue close <number> -R KLTsai/next-is-you --reason completed`. For discontinued work, use `--reason not_planned`. Post a detailed closing explanation with `issue comment --body-file` first when needed.

Record concrete scope, observable acceptance, dependencies, and non-goals before implementation. Preserve adopted decisions and link historical evidence. Do not bulk-create new issues for every retired local ticket.

## Pull requests as a triage surface

**PRs as a request surface: no.**

## When a skill says "publish to the issue tracker"

Create a GitHub issue using `gh-axi issue create` and a body file, within the authorized task scope.

## When a skill says "fetch the relevant ticket"

Read the referenced GitHub issue with `gh-axi issue view <number> --comments --full`.

## Historical local records

Historical tickets live under `docs/archive/tickets/`. Their statuses are frozen evidence, not an active backlog. GitHub Issues owns active scope, status, and acceptance. Preserve adopted decisions from the archive and carry consequential unfinished work into the relevant active issue. Runtime setup belongs in `README.md` and live gates in `docs/PRE-LIVE-CHECKLIST.md`.
