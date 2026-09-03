#!/usr/bin/env bash
set -euo pipefail

env_file="${1:?usage: advance-source-pair.sh ENV_FILE PREFIX [REQUIRED_CHECK]}"
prefix="${2:?usage: advance-source-pair.sh ENV_FILE PREFIX [REQUIRED_CHECK]}"
required_check="${3:-}"

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
    next_head=""
    ;;
  *)
    echo "Cannot advance ${source_repository} from ${current_head}: comparison is ${comparison_status}" >&2
    exit 1
    ;;
esac

required_check_status() {
  local commit="$1"
  local check_runs

  check_runs="$(gh api "repos/${source_repository}/commits/${commit}/check-runs?filter=latest&per_page=100")"
  if jq -e --arg name "$required_check" \
    'any(.check_runs[]; .name == $name and .conclusion == "success")' \
    <<<"$check_runs" >/dev/null; then
    printf 'success'
  elif jq -e --arg name "$required_check" \
    'any(.check_runs[]; .name == $name and .status != "completed")' \
    <<<"$check_runs" >/dev/null; then
    printf 'pending'
  elif jq -e --arg name "$required_check" \
    'any(.check_runs[]; .name == $name)' \
    <<<"$check_runs" >/dev/null; then
    printf 'failed'
  else
    printf 'missing'
  fi
}

source_distance=0
skipped_source_count=0
skipped_source_shas=""
previous_source="$current_head"
if [[ "$comparison_status" == "ahead" ]]; then
  while IFS=$'\t' read -r candidate candidate_parent; do
    if [[ "$candidate_parent" != "$previous_source" ]]; then
      echo "Expected ${candidate} to follow ${previous_source}, got parent ${candidate_parent}" >&2
      exit 1
    fi
    previous_source="$candidate"
    source_distance=$((source_distance + 1))
    if [[ -z "$required_check" ]]; then
      next_head="$candidate"
      break
    fi

    check_status="$(required_check_status "$candidate")"
    case "$check_status" in
      success)
        next_head="$candidate"
        break
        ;;
      failed)
        skipped_source_count=$((skipped_source_count + 1))
        skipped_source_shas="${skipped_source_shas:+${skipped_source_shas},}${candidate}"
        echo "Skipping ${candidate}: upstream ${required_check} did not pass"
        ;;
      pending|missing)
        echo "Waiting for ${candidate}: upstream ${required_check} is ${check_status}"
        break
        ;;
    esac
  done < <(jq -r '.commits[] | [.sha, (.parents[0].sha // "")] | @tsv' <<<"$comparison")
fi

if [[ -z "$next_head" ]]; then
  if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
    echo "updated=false" >> "$GITHUB_OUTPUT"
  fi
  echo "No upstream changes"
  exit 0
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
    echo "updated=true"
    echo "source_repository=${source_repository}"
    echo "source_sha=${next_head}"
    echo "source_short_sha=${next_head:0:7}"
    echo "base_sha=${current_head}"
    echo "head_sha=${next_head}"
    echo "source_distance=${source_distance}"
    echo "skipped_source_count=${skipped_source_count}"
    echo "skipped_source_shas=${skipped_source_shas}"
  } >> "$GITHUB_OUTPUT"
fi

echo "Advanced ${source_repository} from ${current_head} to ${next_head} across ${source_distance} commit(s)"
