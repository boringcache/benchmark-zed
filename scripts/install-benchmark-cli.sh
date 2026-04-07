#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF' >&2
Usage: install-benchmark-cli.sh (--artifact-dir DIR | --release-tag TAG)
EOF
  exit 1
}

default_asset_name() {
  local os arch
  os="$(uname -s)"
  arch="$(uname -m)"
  case "${os}:${arch}" in
    Linux:x86_64) printf 'boringcache-linux-amd64\n' ;;
    Linux:aarch64|Linux:arm64) printf 'boringcache-linux-arm64\n' ;;
    Darwin:x86_64|Darwin:arm64) printf 'boringcache-macos-universal\n' ;;
    *) printf 'boringcache-linux-amd64\n' ;;
  esac
}

artifact_dir=""
release_tag=""
asset_name="${BORINGCACHE_CLI_ASSET_NAME:-$(default_asset_name)}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --artifact-dir)
      artifact_dir="${2:-}"
      shift 2
      ;;
    --release-tag)
      release_tag="${2:-}"
      shift 2
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      ;;
  esac
done

if [[ -n "$artifact_dir" && -n "$release_tag" ]]; then
  echo "Choose either --artifact-dir or --release-tag, not both." >&2
  exit 1
fi

if [[ -z "$artifact_dir" && -z "$release_tag" ]]; then
  usage
fi

install_dir="${RUNNER_TEMP:-/tmp}/boringcache-cli/bin"
mkdir -p "$install_dir"

if [[ -n "$artifact_dir" ]]; then
  artifact_path="${artifact_dir}/boringcache"
  if [[ ! -f "$artifact_path" ]]; then
    echo "Missing boringcache artifact at ${artifact_path}" >&2
    ls -R "$artifact_dir" >&2 || true
    exit 1
  fi
  cp "$artifact_path" "${install_dir}/boringcache"
  echo "Installed custom benchmark CLI: ${install_dir}/boringcache"
else
  download_url="https://github.com/boringcache/cli/releases/download/${release_tag}/${asset_name}"
  curl -fsSL "$download_url" -o "${install_dir}/boringcache"
  echo "Installed released benchmark CLI ${release_tag}: ${install_dir}/boringcache"
fi

chmod +x "${install_dir}/boringcache"

if [[ -n "${GITHUB_PATH:-}" ]]; then
  echo "${install_dir}" >> "${GITHUB_PATH}"
else
  export PATH="${install_dir}:$PATH"
  echo "GITHUB_PATH is not set; prepended ${install_dir} to PATH for this shell only."
fi
"${install_dir}/boringcache" --version
