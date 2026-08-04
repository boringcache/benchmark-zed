#!/usr/bin/env bash
set -euo pipefail

project_dir="${1:?usage: resolve-cargo-target-tag.sh PROJECT_DIR PLAN_FILE CARGO_ARGS...}"
plan_file="${2:?usage: resolve-cargo-target-tag.sh PROJECT_DIR PLAN_FILE CARGO_ARGS...}"
shift 2

if [[ "$#" -eq 0 ]]; then
  echo "Cargo arguments are required" >&2
  exit 1
fi

(
  cd "$project_dir"
  boringcache cargo --dry-run --json "$@"
) > "$plan_file"

jq -er '
  [.archive_entries[]? | select(.kind == "cargo-target") | .tag] as $tags
  | if ($tags | length) == 1 then
      $tags[0]
    else
      error("expected exactly one cargo-target archive entry, found \($tags | length)")
    end
' "$plan_file"
