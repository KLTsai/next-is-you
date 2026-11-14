#!/usr/bin/env bash
set -euo pipefail

# Release Please decides where the next changelog starts by looking for a tag
# named after the version it currently believes is released. Only "Promote
# candidate to production" creates that tag, so a release PR that was merged but
# never promoted leaves the version ahead of every tag. Release Please then has
# no boundary and every proposal it opens carries the whole history.
# docs/CI-CD.md records the two weeks this cost.

remote=${1:-origin}

fail() {
    printf 'check:release cannot run: %s\n' "$1" >&2
    exit 2
}

command -v node >/dev/null 2>&1 || fail 'node is not on PATH'

package_version="$(node -p "require('./package.json').version")"
manifest_version="$(node -p "require('./.github/.release-please-manifest.json')['.']")"

[[ "$package_version" =~ ^[0-9]+\.[0-9]+\.[0-9]+([.-].*)?$ ]] ||
    fail "package.json holds no usable SemVer version: ${package_version}"

# Release Please reads the manifest, the promotion workflow reads package.json.
# A mismatch means this check would answer for the wrong version.
if [[ "$package_version" != "$manifest_version" ]]; then
    fail "package.json (${package_version}) and the release manifest (${manifest_version}) disagree"
fi

tag="v${package_version}"

if git ls-remote --exit-code --tags "$remote" "refs/tags/${tag}" >/dev/null 2>&1; then
    printf 'OK: %s is tagged on %s. Release Please has its commit boundary.\n' "$tag" "$remote"
    exit 0
fi

cat >&2 <<EOF
Not released: ${tag} has no tag on ${remote}.

The version is already ${package_version}, so Release Please is looking for
${tag} and will not find it. Until that tag exists it scans the whole history,
and every release PR it opens carries every commit in the repository.

To finish the release: run "Candidate deploy" on the commit you want, check the
staging URL, then run "Promote candidate to production" from the candidate tag
it recorded.

Do not create ${tag} by hand. Promotion skips creating the GitHub Release when
the tag already exists, which leaves a tag with no release behind it.
EOF
exit 1
