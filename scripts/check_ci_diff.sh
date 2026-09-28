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
        ;;
    *)
        fail "unsupported event '$event_name'"
        ;;
esac

printf 'Checking diff whitespace for %s\n' "$range_spec"
git diff --check "${diff_args[@]}"
