#!/usr/bin/env bash
# Print "true" when every file changed between BEFORE and AFTER is a Markdown
# document, otherwise "false". The rule lives in scripts/delivery_state.py so
# that the push decision and the status report cannot disagree.
set -euo pipefail

exec python3 "$(dirname "${BASH_SOURCE[0]}")/delivery_state.py" docs-only-push
