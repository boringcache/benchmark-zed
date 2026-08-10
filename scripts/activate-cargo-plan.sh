#!/usr/bin/env bash
# Expose one committed CLI plan at the upstream checkout where Cargo freshness
# must be measured. The symlink is Git-ignored runtime plumbing; the selected
# plan remains immutable repository data under plans/.
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
lane="${1:?expected a Cargo layer lane}"
phase="${2:?expected a Cargo release phase}"
plan="${repo_root}/plans/${lane}/${phase}/.boringcache.toml"
upstream="${repo_root}/upstream"

test -f "${plan}"
test -d "${upstream}/.git" || test -f "${upstream}/.git"

exclude="$(git -C "${upstream}" rev-parse --absolute-git-dir)/info/exclude"
if ! grep -Fqx '/.boringcache.toml' "${exclude}" 2>/dev/null; then
  echo '/.boringcache.toml' >> "${exclude}"
fi

ln -sfn "../plans/${lane}/${phase}/.boringcache.toml" \
  "${upstream}/.boringcache.toml"
test -f "${upstream}/.boringcache.toml"
test -z "$(git -C "${upstream}" status --porcelain=v1 --untracked-files=all)"
echo "Activated the ${lane}/${phase} Cargo plan in the upstream checkout."
