#!/usr/bin/env bash
# Run Zed's two Linux release Cargo invocations directly, outside the Cargo
# product, so the actions/cache control lane compiles exactly what the
# BoringCache lanes compile. Both sides read their commands and RUSTFLAGS from
# scripts/zed-release-recipe.env, which verify-zed-release-recipe.py gates
# against upstream's script/bundle-linux.
#
# Each phase reports how many Cargo units it actually compiled. The BoringCache
# lane reports the same figure as `compile_requests` in its adapter evidence, so
# the two lanes can be compared on rebuild set as well as wall time. That
# comparison is the one that separates "sccache costs us wrapper overhead" from
# "RUSTC_WRAPPER makes Cargo rebuild more than it needs to".
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

set -a
# shellcheck source=zed-release-recipe.env
. "${repo_root}/scripts/zed-release-recipe.env"
set +a

cd "${repo_root}/upstream"

run_phase() {
  local label="$1"
  local command="$2"
  local log units status

  log="$(mktemp)"
  local phase_started
  phase_started="$(date +%s)"
  echo "+ ${command}"

  set +e
  (
    set -o pipefail
    eval "${command}" 2>&1 | tee "${log}"
  )
  status=$?
  set -e

  if [ "${status}" -ne 0 ]; then
    rm -f "${log}"
    exit "${status}"
  fi

  units="$(grep -cE '^[[:space:]]*Compiling ' "${log}" || true)"
  echo "zed-benchmark: ${label}_compiled_units=${units}"
  echo "zed-benchmark: ${label}_seconds=$(( $(date +%s) - phase_started ))"
  if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
    echo "- \`${label}\`: ${units} Cargo units compiled" >> "${GITHUB_STEP_SUMMARY}"
  fi
  rm -f "${log}"
}

if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
  {
    echo "## Cargo rebuild set"
    echo
  } >> "${GITHUB_STEP_SUMMARY}"
fi

# Zed appends to RUSTFLAGS between phases rather than replacing it; mirror that
# accumulation so the musl link inherits the rpath flags too.
export RUSTFLAGS="${RUSTFLAGS:-} ${ZED_BASE_RUSTFLAGS}"
run_phase primary \
  "$("${repo_root}/scripts/select-zed-cargo-phase.py" primary --print)"

export RUSTFLAGS="${RUSTFLAGS:-} ${ZED_MUSL_RUSTFLAGS}"
musl_cc_var="CC_$(echo "${ZED_REMOTE_SERVER_TARGET}" | tr '-' '_')"
export "${musl_cc_var}"="${ZED_MUSL_CC}"
run_phase remote-server \
  "$("${repo_root}/scripts/select-zed-cargo-phase.py" remote-server --print)"
