#!/usr/bin/env bash
set -euo pipefail

benchmark=""
strategy=""
lane="fresh"
project_repo=""
project_ref=""
cold_seconds=""
warm1_seconds=""
cache_storage_bytes="0"
cache_storage_source=""
bytes_uploaded=""
bytes_downloaded=""
hit_behavior_note=""
cli_version="${BENCHMARK_CLI_VERSION:-}"
action_ref="${BENCHMARK_ACTION_REF:-}"
action_sha="${BENCHMARK_ACTION_SHA:-}"
web_revision="${BENCHMARK_WEB_REVISION:-}"
api_url="${BENCHMARK_API_URL:-${BORINGCACHE_API_URL:-https://api.boringcache.com}}"
output_dir="benchmark-results"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --benchmark)
      benchmark="$2"
      shift 2
      ;;
    --strategy)
      strategy="$2"
      shift 2
      ;;
    --lane)
      lane="$2"
      shift 2
      ;;
    --project-repo)
      project_repo="$2"
      shift 2
      ;;
    --project-ref)
      project_ref="$2"
      shift 2
      ;;
    --cold-seconds)
      cold_seconds="$2"
      shift 2
      ;;
    --warm1-seconds)
      warm1_seconds="$2"
      shift 2
      ;;
    --cache-storage-bytes)
      cache_storage_bytes="$2"
      shift 2
      ;;
    --cache-storage-source)
      cache_storage_source="$2"
      shift 2
      ;;
    --bytes-uploaded)
      bytes_uploaded="$2"
      shift 2
      ;;
    --bytes-downloaded)
      bytes_downloaded="$2"
      shift 2
      ;;
    --hit-behavior-note)
      hit_behavior_note="$2"
      shift 2
      ;;
    --cli-version)
      cli_version="$2"
      shift 2
      ;;
    --action-ref)
      action_ref="$2"
      shift 2
      ;;
    --action-sha)
      action_sha="$2"
      shift 2
      ;;
    --web-revision)
      web_revision="$2"
      shift 2
      ;;
    --api-url)
      api_url="$2"
      shift 2
      ;;
    --output-dir)
      output_dir="$2"
      shift 2
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 1
      ;;
  esac
done

if [[ -z "$benchmark" || -z "$strategy" || -z "$project_repo" || -z "$project_ref" || -z "$cold_seconds" ]]; then
  echo "Missing required arguments" >&2
  exit 1
fi

case "$lane" in
  fresh|rolling)
    ;;
  *)
    echo "Unsupported lane: $lane" >&2
    exit 1
    ;;
esac

if [[ -z "$cache_storage_source" ]]; then
  cache_storage_source="unspecified"
fi

if ! [[ "$cache_storage_bytes" =~ ^[0-9]+$ ]]; then
  cache_storage_bytes="0"
fi

json_num_or_null() {
  local v="$1"
  if [[ -z "$v" ]]; then
    echo "null"
  else
    echo "$v"
  fi
}

json_string_or_null() {
  local v="$1"
  if [[ -z "$v" ]]; then
    echo "null"
  else
    jq -Rn --arg value "$v" '$value'
  fi
}

health_url_for_api_base() {
  local base="${1%/}"
  case "$base" in
    */v1|*/v2)
      printf '%s/v2/health\n' "${base%/*}"
      ;;
    *)
      printf '%s/v2/health\n' "$base"
      ;;
  esac
}

collect_default_product_refs() {
  if [[ -z "$cli_version" && "$strategy" == "boringcache" ]] && command -v boringcache >/dev/null 2>&1; then
    local version_output
    version_output="$(boringcache --version 2>/dev/null | head -n 1 || true)"
    if [[ "$version_output" =~ ([0-9]+\.[0-9]+\.[0-9]+) ]]; then
      cli_version="v${BASH_REMATCH[1]}"
    else
      cli_version="$version_output"
    fi
  fi

  if [[ -z "$action_ref" && "$strategy" == "boringcache" ]]; then
    action_ref="boringcache/one@v1"
  fi

  if [[ -z "$action_sha" && "$action_ref" =~ ^([^@]+)@(.+)$ ]]; then
    local action_repo="${BASH_REMATCH[1]}"
    local action_ref_name="${BASH_REMATCH[2]}"
    if [[ "$action_ref_name" =~ ^[0-9a-f]{40}$ ]]; then
      action_sha="$action_ref_name"
    elif command -v git >/dev/null 2>&1; then
      local remote_url="https://github.com/${action_repo}.git"
      local resolved refspec
      for refspec in "refs/tags/${action_ref_name}^{}" "refs/tags/${action_ref_name}" "refs/heads/${action_ref_name}"; do
        resolved="$(git ls-remote "$remote_url" "$refspec" 2>/dev/null | awk 'NR == 1 { print $1 }' || true)"
        if [[ "$resolved" =~ ^[0-9a-f]{40}$ ]]; then
          action_sha="$resolved"
          break
        fi
      done
    fi
  fi

  if [[ -z "$web_revision" && -n "$api_url" ]] && command -v curl >/dev/null 2>&1 && command -v jq >/dev/null 2>&1; then
    local health_url health_json
    health_url="$(health_url_for_api_base "$api_url")"
    health_json="$(curl -fsS --max-time 5 -A "BoringCacheBenchmark/1.0" "$health_url" 2>/dev/null || true)"
    if [[ -n "$health_json" ]]; then
      web_revision="$(printf '%s' "$health_json" | jq -r '.revision // empty' 2>/dev/null || true)"
    fi
  fi
}

if [[ -n "$bytes_uploaded" ]] && ! [[ "$bytes_uploaded" =~ ^[0-9]+$ ]]; then
  bytes_uploaded=""
fi
if [[ -n "$bytes_downloaded" ]] && ! [[ "$bytes_downloaded" =~ ^[0-9]+$ ]]; then
  bytes_downloaded=""
fi
collect_default_product_refs

warm_count=0
warm_total=0
if [[ -n "$warm1_seconds" ]]; then
  warm_count=$((warm_count + 1))
  warm_total=$((warm_total + warm1_seconds))
fi

pct_vs_cold() {
  local value="$1"
  awk -v cold="$cold_seconds" -v v="$value" 'BEGIN { if (cold <= 0) { print "0.00" } else { printf "%.2f", ((cold - v) / cold) * 100 } }'
}

if [[ $warm_count -gt 0 ]]; then
  warm_avg=$(awk -v total="$warm_total" -v count="$warm_count" 'BEGIN { printf "%.2f", total / count }')
  warm_improvement_pct=$(pct_vs_cold "$warm_avg")
else
  warm_avg="null"
  warm_improvement_pct="null"
fi

cache_storage_mib=$(awk -v bytes="$cache_storage_bytes" 'BEGIN { printf "%.2f", bytes / 1048576 }')

lane_label() {
  case "$1" in
    rolling) echo "Rolling historical" ;;
    *) echo "Fresh isolated" ;;
  esac
}

first_build_label() {
  case "$1" in
    rolling) echo "First build after upstream sync" ;;
    *) echo "Cold build" ;;
  esac
}

comparison_header_label() {
  case "$1" in
    rolling) echo "vs First build" ;;
    *) echo "vs Cold" ;;
  esac
}

mkdir -p "$output_dir"
json_path="$output_dir/${benchmark}-${strategy}-${lane}.json"
md_path="$output_dir/${benchmark}-${strategy}-${lane}.md"
generated_at="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
lane_label_value="$(lane_label "$lane")"
first_build_label_value="$(first_build_label "$lane")"
comparison_header_label_value="$(comparison_header_label "$lane")"

cat > "$json_path" <<JSON
{
  "benchmark": "$benchmark",
  "strategy": "$strategy",
  "lane": "$lane",
  "lane_label": "$lane_label_value",
  "first_build_label": "$first_build_label_value",
  "project": {
    "repo": "$project_repo",
    "ref": "$project_ref"
  },
  "product_refs": {
    "cli_version": $(json_string_or_null "$cli_version"),
    "action_ref": $(json_string_or_null "$action_ref"),
    "action_sha": $(json_string_or_null "$action_sha"),
    "web_revision": $(json_string_or_null "$web_revision"),
    "api_url": $(json_string_or_null "$api_url")
  },
  "generated_at": "$generated_at",
  "runs": {
    "cold_seconds": $(json_num_or_null "$cold_seconds"),
    "warm1_seconds": $(json_num_or_null "$warm1_seconds")
  },
  "speed": {
    "warm_average_seconds": $warm_avg,
    "warm_vs_cold_improvement_pct": $warm_improvement_pct
  },
  "cache": {
    "storage_bytes": $cache_storage_bytes,
    "storage_mib": $cache_storage_mib,
    "storage_source": "$cache_storage_source"
  },
  "transfer": {
    "bytes_uploaded": $(json_num_or_null "$bytes_uploaded"),
    "bytes_downloaded": $(json_num_or_null "$bytes_downloaded")
  },
  "hit_behavior": {
    "warm_rerun_succeeded": $([[ -n "$warm1_seconds" ]] && echo true || echo false),
    "note": $(json_string_or_null "$hit_behavior_note")
  }
}
JSON

{
  echo "## ${benchmark} (${strategy}, ${lane_label_value})"
  echo ""
  echo "| Phase | Time | ${comparison_header_label_value} |"
  echo "|-------|------|---------|"
  echo "| ${first_build_label_value} | ${cold_seconds}s | — |"

  if [[ -n "$warm1_seconds" ]]; then
    echo "| Warm #1 | ${warm1_seconds}s | -$(pct_vs_cold "$warm1_seconds")% |"
  fi

  echo ""
  echo "| Metric | Value |"
  echo "|--------|-------|"
  echo "| Lane | ${lane_label_value} |"
  echo "| Project | \`${project_repo}\` |"
  echo "| Commit | \`${project_ref}\` |"
  if [[ -n "$cli_version" ]]; then
    echo "| CLI version | \`${cli_version}\` |"
  fi
  if [[ -n "$action_ref" ]]; then
    echo "| Action ref | \`${action_ref}\` |"
  fi
  if [[ -n "$action_sha" ]]; then
    echo "| Action SHA | \`${action_sha}\` |"
  fi
  if [[ -n "$web_revision" ]]; then
    echo "| Web revision | \`${web_revision}\` |"
  fi

  if [[ "$warm_avg" != "null" ]]; then
    echo "| Warm avg | ${warm_avg}s (${warm_improvement_pct}% faster) |"
  fi

  if [[ "$cache_storage_bytes" != "0" ]]; then
    echo "| Cache storage | ${cache_storage_mib} MiB |"
    echo "| Storage source | ${cache_storage_source} |"
  fi

  if [[ -n "$bytes_uploaded" ]]; then
    echo "| Bytes uploaded | ${bytes_uploaded} |"
  fi
  if [[ -n "$bytes_downloaded" ]]; then
    echo "| Bytes downloaded | ${bytes_downloaded} |"
  fi
  if [[ -n "$hit_behavior_note" ]]; then
    echo "| Note | ${hit_behavior_note} |"
  fi
} > "$md_path"

if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
  echo "json_path=$json_path" >> "$GITHUB_OUTPUT"
  echo "md_path=$md_path" >> "$GITHUB_OUTPUT"
fi
