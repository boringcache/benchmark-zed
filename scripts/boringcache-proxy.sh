#!/usr/bin/env bash
set -euo pipefail

PID_FILE="/tmp/boringcache-proxy.pid"

usage() {
  cat <<'EOF' >&2
Usage:
  boringcache-proxy.sh start --workspace WORKSPACE --tag TAG --port PORT [--command COMMAND] [--host HOST] [--no-git] [--no-platform] [--verbose]
  boringcache-proxy.sh wait --port PORT [--pid PID] [--timeout-ms 300000]
  boringcache-proxy.sh stop [--pid PID]
EOF
  exit 1
}

command="${1:-}"
if [[ -z "$command" ]]; then
  usage
fi
shift

workspace=""
tag=""
proxy_command="cache-registry"
host="127.0.0.1"
port=""
timeout_ms="300000"
pid=""
no_git=0
no_platform=0
verbose=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --workspace)
      workspace="${2:-}"
      shift 2
      ;;
    --tag)
      tag="${2:-}"
      shift 2
      ;;
    --command)
      proxy_command="${2:-}"
      shift 2
      ;;
    --host)
      host="${2:-}"
      shift 2
      ;;
    --port)
      port="${2:-}"
      shift 2
      ;;
    --timeout-ms)
      timeout_ms="${2:-}"
      shift 2
      ;;
    --pid)
      pid="${2:-}"
      shift 2
      ;;
    --no-git)
      no_git=1
      shift
      ;;
    --no-platform)
      no_platform=1
      shift
      ;;
    --verbose)
      verbose=1
      shift
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      ;;
  esac
done

proxy_log_path() {
  local proxy_port="$1"
  echo "/tmp/boringcache-proxy-${proxy_port}.log"
}

is_process_alive() {
  local check_pid="$1"
  [[ -n "$check_pid" ]] && kill -0 "$check_pid" >/dev/null 2>&1
}

read_proxy_logs() {
  local log_path="$1"
  if [[ -f "$log_path" ]]; then
    cat "$log_path"
  fi
}

load_pid_from_file() {
  if [[ -z "$pid" && -f "$PID_FILE" ]]; then
    pid="$(tr -d '[:space:]' < "$PID_FILE")"
  fi
}

start_proxy() {
  if [[ -z "$workspace" || -z "$tag" || -z "$port" ]]; then
    usage
  fi

  local log_path
  log_path="$(proxy_log_path "$port")"
  : > "$log_path"

  local -a args
  args=("$proxy_command" "$workspace" "$tag")
  if [[ "$no_git" -eq 1 ]]; then
    args+=(--no-git)
  fi
  if [[ "$no_platform" -eq 1 ]]; then
    args+=(--no-platform)
  fi
  args+=(--host "$host" --port "$port")
  if [[ "$verbose" -eq 1 ]]; then
    args+=(--verbose)
  fi

  boringcache "${args[@]}" > "$log_path" 2>&1 &
  local child_pid=$!
  echo "$child_pid" > "$PID_FILE"

  echo "pid=$child_pid"
  echo "port=$port"
  echo "log_path=$log_path"
}

wait_for_proxy() {
  if [[ -z "$port" ]]; then
    usage
  fi

  load_pid_from_file

  local timeout_s
  timeout_s=$(( (timeout_ms + 999) / 1000 ))
  local started_at
  started_at="$(date +%s)"
  local last_log_at="$started_at"
  local log_path
  log_path="$(proxy_log_path "$port")"

  while true; do
    local now
    now="$(date +%s)"
    local elapsed_s
    elapsed_s=$(( now - started_at ))

    if [[ -n "$pid" && "$pid" =~ ^[0-9]+$ ]] && ! is_process_alive "$pid"; then
      local logs
      logs="$(read_proxy_logs "$log_path")"
      if [[ -n "$logs" ]]; then
        echo "Registry proxy exited before becoming ready:" >&2
        echo "$logs" >&2
      else
        echo "Registry proxy exited before becoming ready" >&2
      fi
      exit 1
    fi

    local code
    code="$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:${port}/v2/" || true)"
    if [[ "$code" == "200" || "$code" == "401" ]]; then
      printf 'Registry proxy is ready (%ss)\n' "$elapsed_s"
      return 0
    fi

    if (( elapsed_s >= timeout_s )); then
      local logs
      logs="$(read_proxy_logs "$log_path")"
      if [[ -n "$logs" ]]; then
        echo "Registry proxy did not become ready within ${timeout_ms}ms:" >&2
        echo "$logs" >&2
      else
        echo "Registry proxy did not become ready within ${timeout_ms}ms" >&2
      fi
      exit 1
    fi

    if (( now - last_log_at >= 10 )); then
      echo "Waiting for proxy readiness... (${elapsed_s}s)"
      last_log_at="$now"
    fi

    sleep 0.5
  done
}

stop_proxy() {
  load_pid_from_file

  if [[ -z "$pid" || ! "$pid" =~ ^[0-9]+$ || "$pid" -le 0 ]]; then
    echo "No proxy PID to stop"
    return 0
  fi

  if ! is_process_alive "$pid"; then
    echo "Registry proxy (PID: $pid) already exited"
    rm -f "$PID_FILE"
    return 0
  fi

  echo "Stopping registry proxy (PID: $pid)..."
  if ! kill -TERM "$pid" >/dev/null 2>&1; then
    echo "Registry proxy (PID: $pid) already exited"
    rm -f "$PID_FILE"
    return 0
  fi

  local started_at
  started_at="$(date +%s)"
  local last_log_at="$started_at"
  while is_process_alive "$pid"; do
    local now
    now="$(date +%s)"
    if (( now - last_log_at >= 30 )); then
      echo "Waiting for registry proxy to flush and exit... ($(( now - started_at ))s elapsed)"
      last_log_at="$now"
    fi
    sleep 1
  done

  echo "Registry proxy exited gracefully after $(( $(date +%s) - started_at ))s"
  rm -f "$PID_FILE"
}

case "$command" in
  start)
    start_proxy
    ;;
  wait)
    wait_for_proxy
    ;;
  stop)
    stop_proxy
    ;;
  *)
    usage
    ;;
esac
