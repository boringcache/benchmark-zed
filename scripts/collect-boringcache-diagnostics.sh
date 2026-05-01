#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF' >&2
Usage: collect-boringcache-diagnostics.sh \
  --output-dir DIR \
  --workspace WORKSPACE \
  --phase PHASE \
  [--tags TAGS] \
  [--cache-tag CACHE_TAG] \
  [--cli-source SOURCE] \
  [--cli-ref REF] \
  [--proxy-port PORT] \
  [--proxy-log-path PATH] \
  [--cache-root PATH] \
  [--cache-label LABEL]
EOF
  exit 1
}

output_dir=""
workspace=""
tags=""
phase=""
cache_tag=""
cli_source=""
cli_ref=""
proxy_port=""
proxy_log_path=""
cache_root=""
cache_label=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --output-dir)
      output_dir="${2:-}"
      shift 2
      ;;
    --workspace)
      workspace="${2:-}"
      shift 2
      ;;
    --tags)
      tags="${2:-}"
      shift 2
      ;;
    --phase)
      phase="${2:-}"
      shift 2
      ;;
    --cache-tag)
      cache_tag="${2:-}"
      shift 2
      ;;
    --cli-source)
      cli_source="${2:-}"
      shift 2
      ;;
    --cli-ref)
      cli_ref="${2:-}"
      shift 2
      ;;
    --proxy-port)
      proxy_port="${2:-}"
      shift 2
      ;;
    --proxy-log-path)
      proxy_log_path="${2:-}"
      shift 2
      ;;
    --cache-root)
      cache_root="${2:-}"
      shift 2
      ;;
    --cache-label)
      cache_label="${2:-}"
      shift 2
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      ;;
  esac
done

if [[ -z "$output_dir" || -z "$workspace" || -z "$phase" ]]; then
  usage
fi

if [[ -z "$proxy_log_path" && -n "$proxy_port" ]]; then
  proxy_log_path="/tmp/boringcache-proxy-${proxy_port}.log"
fi

if [[ -n "$cache_root" && -z "$cache_label" ]]; then
  cache_label="cache"
fi

mkdir -p "$output_dir"

{
  echo "run_id=${GITHUB_RUN_ID:-}"
  echo "run_attempt=${GITHUB_RUN_ATTEMPT:-}"
  echo "job=${GITHUB_JOB:-}"
  echo "phase=${phase}"
  echo "workspace=${workspace}"
  echo "cache_tag=${cache_tag}"
  echo "tags=${tags}"
  echo "cli_source=${cli_source}"
  echo "cli_ref=${cli_ref}"
  echo "proxy_port=${proxy_port}"
  echo "proxy_log_path=${proxy_log_path}"
  date -u +"timestamp=%Y-%m-%dT%H:%M:%SZ"
  if command -v boringcache >/dev/null 2>&1; then
    echo "boringcache_path=$(command -v boringcache)"
    echo "boringcache_version=$(boringcache --version 2>/dev/null | head -n1)"
  fi
  echo "--- uname ---"
  uname -a
} > "${output_dir}/metadata.txt"

if [[ -f "$HOME/.bazelrc" ]]; then
  cp "$HOME/.bazelrc" "${output_dir}/bazelrc.txt"
fi

if [[ -n "$cache_root" && -d "$cache_root" ]]; then
  du -sh "$cache_root" > "${output_dir}/${cache_label}-size.txt" || true
  find "$cache_root" -maxdepth 3 -mindepth 1 -type d \
    | head -n 200 > "${output_dir}/${cache_label}-tree.txt" || true
fi

if [[ -d "$HOME/.boringcache" ]]; then
  find "$HOME/.boringcache" -maxdepth 6 -type f | sort > "${output_dir}/boringcache-files.txt" || true
fi

request_metrics="${HOME}/.boringcache/logs/cache-registry-request-metrics.jsonl"
if [[ -f "$request_metrics" ]]; then
  cp "$request_metrics" "${output_dir}/cache-registry-request-metrics.jsonl"
fi

if [[ -n "$proxy_port" ]]; then
  proxy_status="${output_dir}/proxy-status-${phase}.json"
  proxy_status_stderr="${output_dir}/proxy-status-${phase}.stderr.txt"
  if ! curl -fsS "http://127.0.0.1:${proxy_port}/_boringcache/status" \
    -o "$proxy_status" 2> "$proxy_status_stderr"; then
    rm -f "$proxy_status"
  fi
fi

if [[ -n "$proxy_log_path" && -f "$proxy_log_path" ]]; then
  cp "$proxy_log_path" "${output_dir}/$(basename "$proxy_log_path")"
fi

if [[ -n "$tags" ]]; then
  remote_check_json="${output_dir}/remote-tag-check.json"
  remote_check_stderr="${output_dir}/remote-tag-check.stderr.txt"

  archive_tags=()
  proxy_tags=()
  IFS=',' read -r -a tag_list <<< "$tags"
  for raw_tag in "${tag_list[@]}"; do
    tag="${raw_tag//[[:space:]]/}"
    [[ -n "$tag" ]] || continue

    if [[ -n "$cache_tag" && "$tag" == "$cache_tag" ]]; then
      proxy_tags+=("$tag")
    elif [[ "$cache_label" == "sccache-cache" && "$tag" == *"-sccache-"* ]]; then
      proxy_tags+=("$tag")
    else
      archive_tags+=("$tag")
    fi
  done

  remote_check_tmp="$(mktemp -d)"
  remote_check_files=()
  remote_check_ok=1
  : > "$remote_check_stderr"

  if [[ ${#archive_tags[@]} -gt 0 ]]; then
    archive_tags_csv="$(IFS=,; echo "${archive_tags[*]}")"
    archive_json="${remote_check_tmp}/archive.json"
    if boringcache check "$workspace" "$archive_tags_csv" --no-git --json > "$archive_json" 2>> "$remote_check_stderr"; then
      remote_check_files+=("$archive_json")
    else
      remote_check_ok=0
    fi
  fi

  if [[ ${#proxy_tags[@]} -gt 0 ]]; then
    proxy_tags_csv="$(IFS=,; echo "${proxy_tags[*]}")"
    proxy_json="${remote_check_tmp}/proxy.json"
    if boringcache check "$workspace" "$proxy_tags_csv" --no-git --no-platform --exact --json > "$proxy_json" 2>> "$remote_check_stderr"; then
      remote_check_files+=("$proxy_json")
    else
      remote_check_ok=0
    fi
  fi

  if [[ "$remote_check_ok" == "1" && ${#remote_check_files[@]} -gt 0 ]]; then
    jq -s '
      def all_results: [.[].results[]?];
      {
        schema_version: (.[0].schema_version // 1),
        workspace: (.[0].workspace // ""),
        total: (all_results | length),
        hits: (all_results | map(select((.status // "") == "hit")) | length),
        pending: (all_results | map(select((.status // "") == "pending")) | length),
        misses: (all_results | map(select((.status // "") == "miss")) | length),
        results: all_results
      }
    ' "${remote_check_files[@]}" > "$remote_check_json"

    if ! jq -e '.results | type == "array"' "$remote_check_json" >/dev/null 2>&1; then
      mv "$remote_check_json" "${output_dir}/remote-tag-check.txt"
    fi
  else
    rm -f "$remote_check_json"
  fi
  rm -rf "$remote_check_tmp"
fi
