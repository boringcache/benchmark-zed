#!/usr/bin/env bash
# Fail before Cargo when a restored target belongs to a different source commit.
# A missing target is the intentional cold bootstrap for a new target cohort.
set -euo pipefail

base_sha="${BORINGCACHE_ZED_BASE_SHA:?expected the source represented by the restored target}"
head_sha="${BORINGCACHE_ZED_HEAD_SHA:?expected the source Cargo is about to build}"
marker="target/.boringcache-zed-source-sha"

if [[ -f "$marker" ]]; then
  restored_sha="$(tr -d '\n' < "$marker")"
  if [[ "$restored_sha" == "$head_sha" ]]; then
    echo "Zed target already represents ${head_sha}; verifying an idempotent retry."
  elif [[ "$restored_sha" != "$base_sha" ]]; then
    echo "Restored Zed target represents ${restored_sha}, expected ${base_sha}." >&2
    exit 1
  fi
elif [[ -n "$(find target -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null)" ]]; then
  echo "Restored Zed target has no source identity marker; refusing a stale replay." >&2
  exit 1
else
  echo "No prior Zed target snapshot; seeding the rolling target cohort."
fi

cargo build --release --locked --message-format=json-render-diagnostics

mkdir -p target
printf '%s\n' "$head_sha" > "${marker}.tmp"
mv "${marker}.tmp" "$marker"
