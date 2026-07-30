#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
resolver="$repo_root/scripts/resolve-zed-cache-paths.sh"
workflow="$repo_root/.github/workflows/zed-sccache-actions-cache.yml"

expected_base="$(printf '%s\n' \
  "$HOME/.cargo/registry" \
  "$HOME/.cargo/git" \
  "$HOME/.cache/sccache")"
expected_with_target="${expected_base}"$'\n''upstream/target'
resolver_expression="./scripts/resolve-zed-cache-paths.sh \"\${{ inputs.cache_target }}\""
cache_path_expression="path: \${{ steps.cache_paths.outputs.paths }}"
# This is the literal workflow text whose use would change actions/cache's version hash.
# shellcheck disable=SC2088
tilde_cache_path="~/.cargo/registry"

[[ "$("$resolver" false)" == "$expected_base" ]]
[[ "$("$resolver" true)" == "$expected_with_target" ]]

if "$resolver" invalid >/dev/null 2>&1; then
  echo "Expected an invalid cache_target value to fail." >&2
  exit 1
fi

[[ "$(grep -Fc "$resolver_expression" "$workflow")" -eq 2 ]]
[[ "$(grep -Fc "$cache_path_expression" "$workflow")" -eq 4 ]]
if grep -Fq "$tilde_cache_path" "$workflow"; then
  echo "Workflow contains a cache path that bypasses the canonical resolver." >&2
  exit 1
fi

echo "Zed cache path resolution is consistent."
