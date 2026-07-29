#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
scope="${1:-}"

if [[ ! "$scope" =~ ^[a-z0-9][a-z0-9._-]+$ ]]; then
  echo "Expected a lowercase benchmark cache scope, got: ${scope:-<empty>}" >&2
  exit 1
fi

config_path="${repo_root}/.boringcache.toml"
for tag_mapping in \
  "zed-sccache-local:${scope}-sccache" \
  "zed-cargo-registry-local:${scope}-cargo-registry" \
  "zed-cargo-git-local:${scope}-cargo-git" \
  "zed-target-local:${scope}-target"; do
  old_tag="${tag_mapping%%:*}"
  new_tag="${tag_mapping#*:}"
  if ! grep -Fq "tag = \"${old_tag}\"" "$config_path"; then
    echo "Missing expected local tag in ${config_path}: ${old_tag}" >&2
    exit 1
  fi
  next_config="${config_path}.next"
  sed "s/tag = \"${old_tag}\"/tag = \"${new_tag}\"/" "$config_path" > "$next_config"
  mv "$next_config" "$config_path"
done

echo "Scoped BoringCache sccache, Cargo dependency, and target tags to ${scope}."
