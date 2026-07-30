#!/usr/bin/env bash
set -euo pipefail

cache_target="${1:-false}"

case "$cache_target" in
  true | false) ;;
  *)
    echo "cache_target must be true or false" >&2
    exit 1
    ;;
esac

printf '%s\n' \
  "$HOME/.cargo/registry" \
  "$HOME/.cargo/git" \
  "$HOME/.cache/sccache"

if [[ "$cache_target" == "true" ]]; then
  printf '%s\n' "upstream/target"
fi
