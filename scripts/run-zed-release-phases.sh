#!/usr/bin/env bash
# Run Zed's two Linux release Cargo invocations directly, outside the Cargo
# product, so the actions/cache control lane compiles exactly what the
# BoringCache lanes compile. Both sides read their commands and RUSTFLAGS from
# scripts/zed-release-recipe.env, which verify-zed-release-recipe.py gates
# against upstream's script/bundle-linux.
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

set -a
# shellcheck source=zed-release-recipe.env
. "${repo_root}/scripts/zed-release-recipe.env"
set +a

cd "${repo_root}/upstream"

# Zed appends to RUSTFLAGS between phases rather than replacing it; mirror that
# accumulation so the musl link inherits the rpath flags too.
export RUSTFLAGS="${RUSTFLAGS:-} ${ZED_BASE_RUSTFLAGS}"
primary_command="$("${repo_root}/scripts/select-zed-cargo-phase.py" primary --print)"
echo "+ ${primary_command}"
eval "${primary_command}"

export RUSTFLAGS="${RUSTFLAGS:-} ${ZED_MUSL_RUSTFLAGS}"
musl_cc_var="CC_$(echo "${ZED_REMOTE_SERVER_TARGET}" | tr '-' '_')"
export "${musl_cc_var}"="${ZED_MUSL_CC}"
remote_command="$("${repo_root}/scripts/select-zed-cargo-phase.py" remote-server --print)"
echo "+ ${remote_command}"
eval "${remote_command}"
