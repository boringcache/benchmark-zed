#!/usr/bin/env bash
# Shared setup for every cache-matrix lane: check out a pinned Zed commit, install
# Zed's build dependencies and pinned toolchain, re-verify the release recipe, and
# mirror the bundle's RELEASE_VERSION. Every lane must be identical up to the cache
# strategy under test, so this lives in one place rather than being restated per job.
#
#   prepare-zed-lane.sh <sha> [expected-parent-sha]
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${repo_root}"

sha="${1:?expected a Zed commit sha}"
expected_parent="${2:-}"

git submodule sync --recursive
git -c protocol.version=2 submodule update --init --depth 2 --recommend-shallow --jobs 4 upstream
git -C upstream fetch --no-tags --depth 2 origin "${sha}"
git -C upstream checkout --detach "${sha}"
if [ -n "${expected_parent}" ]; then
  test "$(git -C upstream rev-parse HEAD^)" = "${expected_parent}"
fi
git -C upstream clean -fdx
test -z "$(git -C upstream status --porcelain=v1 --untracked-files=all)"

sudo apt-get update
sudo apt-get install -y \
  libxkbcommon-dev libxkbcommon-x11-dev libwayland-dev libvulkan-dev \
  libasound2-dev libfontconfig1-dev libfreetype6-dev \
  libglib2.0-dev libssl-dev pkg-config cmake \
  libx11-dev libx11-xcb-dev libxcb1-dev \
  libxcursor-dev libxinerama-dev libxi-dev libxrandr-dev \
  musl-tools clang curl ca-certificates

pinned="$(sed -n 's/^channel = "\(.*\)"$/\1/p' upstream/rust-toolchain.toml)"
test -n "${pinned}"

if ! command -v rustup >/dev/null 2>&1; then
  rustup_dir="$(mktemp -d)"
  rustup_init="${rustup_dir}/rustup-init"
  curl --proto '=https' --tlsv1.2 --retry 10 --retry-connrefused -fsSL \
    https://static.rust-lang.org/rustup/archive/1.28.2/x86_64-unknown-linux-gnu/rustup-init \
    -o "${rustup_init}"
  echo "20a06e644b0d9bd2fbdbfd52d42540bdde820ea7df86e92e533c073da0cdd43c  ${rustup_init}" \
    | sha256sum -c -
  chmod +x "${rustup_init}"
  "${rustup_init}" -y --default-toolchain "${pinned}" --profile minimal --no-modify-path
  rm "${rustup_init}"
  rmdir "${rustup_dir}"

  cargo_bin="${CARGO_HOME:-$HOME/.cargo}/bin"
  export PATH="${cargo_bin}:${PATH}"
  echo "${cargo_bin}" >> "${GITHUB_PATH:-/dev/null}"
fi

(cd upstream && rustup show active-toolchain)
rustup target add --toolchain "${pinned}" x86_64-unknown-linux-musl

./scripts/verify-zed-release-recipe.py upstream

version="$(cd upstream && script/get-crate-version zed)"
test -n "${version}"
echo "RELEASE_VERSION=${version}" >> "${GITHUB_ENV:-/dev/null}"

./scripts/free-runner-disk.sh
