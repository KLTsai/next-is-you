#!/usr/bin/env bash
# Print "true" when every file changed between BEFORE and AFTER is a Markdown
# document, otherwise "false". An unknown range (new branch, forced push,
# missing commit) prints "false" so that staging deploys rather than silently
# skipping unreviewed work.
set -euo pipefail

before=${BEFORE:-}
after=${AFTER:-}

if [[ ! "$before" =~ ^[[:xdigit:]]{40,64}$ || "$before" =~ ^0+$ ]] ||
    ! git cat-file -e "${before}^{commit}" 2>/dev/null ||
    ! git cat-file -e "${after}^{commit}" 2>/dev/null; then
    echo false
    exit 0
fi

files="$(git diff --name-only "$before" "$after")"
if [[ -z "$files" ]]; then
    echo false
    exit 0
fi

while IFS= read -r file; do
    if [[ "$file" != *.md ]]; then
        echo false
        exit 0
    fi
done <<<"$files"
echo true
