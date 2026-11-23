#!/usr/bin/env bash
set -euo pipefail

fail() {
    printf 'diff check cannot compare event range: %s\n' "$1" >&2
    exit 1
}

require_sha() {
    local name="$1"
    local value="$2"
    [[ "$value" =~ ^[[:xdigit:]]{40,64}$ ]] || fail "missing or invalid $name"
    git cat-file -e "${value}^{commit}" 2>/dev/null || fail "$name commit is unavailable"
}

event_name=${GITHUB_EVENT_NAME:-}
case "$event_name" in
    pull_request)
        left=${PR_BASE_SHA:-}
        right=${PR_HEAD_SHA:-}
        require_sha PR_BASE_SHA "$left"
        require_sha PR_HEAD_SHA "$right"
        git merge-base "$left" "$right" >/dev/null || fail "pull request merge base is unavailable"
        range_spec="$left...$right"
        diff_args=("$range_spec")
        log_range="$left..$right"
        ;;
    push)
        left=${PUSH_BEFORE_SHA:-}
        right=${PUSH_AFTER_SHA:-}
        require_sha PUSH_AFTER_SHA "$right"
        if [[ "$left" =~ ^0{40,64}$ ]]; then
            default_branch=${DEFAULT_BRANCH:-}
            [[ -n "$default_branch" ]] || fail "default branch is missing for new branch push"
            git check-ref-format "refs/heads/$default_branch" >/dev/null || fail "default branch name is invalid"
            left="refs/remotes/origin/$default_branch"
            git rev-parse --verify "${left}^{commit}" >/dev/null 2>&1 || fail "default branch commit is unavailable"
            git merge-base "$left" "$right" >/dev/null || fail "new branch merge base is unavailable"
            range_spec="$left...$right"
            diff_args=("$range_spec")
        else
            require_sha PUSH_BEFORE_SHA "$left"
            range_spec="$left..$right"
            diff_args=("$range_spec")
        fi
        log_range="$left..$right"
        ;;
    *)
        fail "unsupported event '$event_name'"
        ;;
esac

printf 'Checking diff whitespace for %s\n' "$range_spec"
git diff --check "${diff_args[@]}"

# Agents never sign commits as co-authors. Only commits new to this range are
# checked, so history already on the default branch stays as it is.
printf 'Checking commit trailers for %s\n' "$log_range"
agent_pattern='^[[:space:]]*co-authored-by:.*(claude|noreply@anthropic\.com)'
commits=$(git rev-list "$log_range")
offenders=0
for sha in $commits; do
    message=$(git log -1 --format=%B "$sha")
    if grep -Eiq "$agent_pattern" <<<"$message"; then
        printf '%s has an agent Co-authored-by trailer: %s\n' "$sha" "$(git log -1 --format=%s "$sha")" >&2
        offenders=$((offenders + 1))
    fi
done
if ((offenders > 0)); then
    printf 'Remove the agent Co-authored-by trailer from %d commit(s) and push again.\n' "$offenders" >&2
    exit 1
fi
