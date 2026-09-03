#!/usr/bin/env bash
# Shared setup for every cache-matrix lane: check out a pinned Zed commit, install
# Zed's build dependencies and pinned toolchain, re-verify the release recipe, and
# mirror the bundle's RELEASE_VERSION. Every lane must be identical up to the cache
# strategy under test, so this lives in one place rather than being restated per job.
#
#   prepare-zed-lane.sh <sha> [expected-parent-sha]
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${repo_root}"

sha="${1:?expected a Zed commit sha}"
expected_parent="${2:-}"

git submodule sync --recursive
git -c protocol.version=2 submodule update --init --depth 2 --recommend-shallow --jobs 4 upstream
git -C upstream fetch --no-tags --depth 2 origin "${sha}"
git -C upstream checkout --detach "${sha}"
if [ -n "${expected_parent}" ]; then
  test "$(git -C upstream rev-parse HEAD^)" = "${expected_parent}"
fi
git -C upstream clean -fdx
test -z "$(git -C upstream status --porcelain=v1 --untracked-files=all)"

./scripts/install-zed-toolchain.sh

./scripts/verify-zed-release-recipe.py upstream

version="$(cd upstream && script/get-crate-version zed)"
test -n "${version}"
echo "RELEASE_VERSION=${version}" >> "${GITHUB_ENV:-/dev/null}"

./scripts/free-runner-disk.sh
