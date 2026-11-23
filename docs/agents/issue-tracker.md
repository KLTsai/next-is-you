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

## Ticking acceptance boxes

Tick boxes with `scripts/tick_acceptance.py`, never by rewriting the body with `issue edit --body-file` by hand. It names the box by `--index N` or exact `--box "text"`, requires `--label` (fixture/mock, local integration, live provider) and `--evidence` (a test name, a PR, a run link), and appends ` Evidence (<label>): <evidence>` to the criterion. It dry-runs and prints the diff by default; rerun with `--apply` to write. It refuses an empty fetched body, a shorter body, or any change outside the targeted boxes, then re-reads the issue to verify. Tick the boxes before saying a PR is ready to merge.

```sh
python3 scripts/tick_acceptance.py <issue> --index 2 --label 'local integration' --evidence '#<pr>, `test_name`'
```

## Labels

Every open issue carries exactly one state label and at least one `area:*` label.

| State label | Meaning | Next step |
|---|---|---|
| `needs-grilling` | Holds decisions the captain has not made yet. | `/grill-with-docs`. Its output is decisions plus `ready-for-agent` work, not code. |
| `ready-for-agent` | Scope, non-goals and blocking edges are written, and every acceptance criterion is checkable and names its evidence label. | `/implement` (one session per ticket), then `/no-mistakes`. |
| `blocked` | Waits on the issues named under "Blocked by". | Nothing until they close. |
| `future-direction` | Deliberately parked. | Not worked on before the live pilot. |

`area:*` labels name the part of the product. `autorelease: *` labels belong to Release Please; do not apply them by hand.

## Workflow and definition of done

- Decisions come first: anything unclear goes through `/grill-with-docs` before an issue is marked `ready-for-agent`. Exploration tools (firstmate, free-form notes) may feed a grilling session but never produce `ready-for-agent` issues directly.
- Work that spans several sessions goes `/to-spec` then `/to-tickets`. Small, fully decided work goes straight to `/implement`. All of it is built in this repository's own session (see `research/firstmate-and-matt-skills-workflow.md`, Option A).
- Each acceptance criterion names its evidence label (fixture/mock, local integration, live provider) and is ticked only with a pointer to the evidence: a test name, a PR, a log excerpt or a screenshot.
- A merged PR does not by itself finish an issue. Close it only when every criterion is ticked with evidence; reopen it if `Closes #N` closed it early.
- When issues are merged into another, comment on each one first with where it went and which decisions moved, list the source issues in the new issue, then close the old ones as not planned.

## Pull requests as a triage surface

**PRs as a request surface: no.**

## When a skill says "publish to the issue tracker"

Create a GitHub issue using `gh-axi issue create` and a body file, within the authorized task scope.

## When a skill says "fetch the relevant ticket"

Read the referenced GitHub issue with `gh-axi issue view <number> --comments --full`.

## Historical local records

Historical tickets live under `docs/archive/tickets/`. Their statuses are frozen evidence, not an active backlog. GitHub Issues owns active scope, status, and acceptance. Preserve adopted decisions from the archive and carry consequential unfinished work into the relevant active issue. Runtime setup belongs in `README.md` and live gates in `docs/PRE-LIVE-CHECKLIST.md`.
