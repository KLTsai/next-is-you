#!/bin/sh
set -eu

cd "$(dirname "$0")/.."
state="${NIY_REHEARSAL_STATE:-.wrangler/manual-rehearsal}"
port="${NIY_REHEARSAL_PORT:-8787}"

npm run build
CI=1 uv run pywrangler d1 migrations apply next-is-you-niy006-local-test \
  --local --config wrangler.niy006.test.jsonc --persist-to "$state"

printf '\nLocal rehearsal: http://127.0.0.1:%s\nState: %s\nUI Stop closes a reminder; Ctrl-C stops this local process.\n\n' "$port" "$state"
exec uv run pywrangler dev --local --ip 127.0.0.1 \
  --config wrangler.niy006.test.jsonc --persist-to "$state" --port "$port" \
  --show-interactive-dev-session=false
