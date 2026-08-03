#!/usr/bin/env bash
set -euo pipefail

env_file="${1:?usage: advance-source-pair.sh ENV_FILE PREFIX}"
prefix="${2:?usage: advance-source-pair.sh ENV_FILE PREFIX}"

if [[ ! "$prefix" =~ ^[A-Z][A-Z0-9_]*$ ]]; then
  echo "Invalid source prefix: $prefix" >&2
  exit 1
fi

setting() {
  local key="$1"
  local value
  value="$(sed -n "s/^${key}=//p" "$env_file")"
  if [[ -z "$value" ]]; then
    echo "Missing ${key} in ${env_file}" >&2
    exit 1
  fi
  printf '%s' "$value"
}

source_repository="$(setting "${prefix}_SOURCE_REPOSITORY")"
current_head="$(setting "${prefix}_HEAD_SHA")"
default_branch="$(gh api "repos/${source_repository}" --jq .default_branch)"
comparison="$(gh api "repos/${source_repository}/compare/${current_head}...${default_branch}")"
comparison_status="$(jq -r .status <<<"$comparison")"

case "$comparison_status" in
  identical)
    next_head=""
    ;;
  ahead)
    next_head="$(jq -r '.commits[0].sha // empty' <<<"$comparison")"
    ;;
  *)
    echo "Cannot advance ${source_repository} from ${current_head}: comparison is ${comparison_status}" >&2
    exit 1
    ;;
esac

if [[ -z "$next_head" ]]; then
  echo "No upstream changes"
  exit 0
fi

next_parent="$(gh api "repos/${source_repository}/commits/${next_head}" --jq '.parents[0].sha // empty')"
if [[ "$next_parent" != "$current_head" ]]; then
  echo "Expected ${next_head} to immediately follow ${current_head}, got parent ${next_parent}" >&2
  exit 1
fi

base_key="${prefix}_BASE_SHA"
head_key="${prefix}_HEAD_SHA"
grep -q "^${base_key}=" "$env_file"
grep -q "^${head_key}=" "$env_file"
sed -i.bak \
  -e "s/^${base_key}=.*/${base_key}=${current_head}/" \
  -e "s/^${head_key}=.*/${head_key}=${next_head}/" \
  "$env_file"
rm -f "${env_file}.bak"

if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
  {
    echo "source_repository=${source_repository}"
    echo "source_sha=${next_head}"
    echo "source_short_sha=${next_head:0:7}"
  } >> "$GITHUB_OUTPUT"
fi

echo "Advanced ${source_repository} from ${current_head} to ${next_head}"
