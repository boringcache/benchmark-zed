#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF' >&2
Usage: install-benchmark-cli.sh --artifact-dir DIR
EOF
  exit 1
}

artifact_dir=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --artifact-dir)
      artifact_dir="${2:-}"
      shift 2
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      ;;
  esac
done

if [[ -z "$artifact_dir" ]]; then
  usage
fi

artifact_path="${artifact_dir}/boringcache"
if [[ ! -f "$artifact_path" ]]; then
  echo "Missing boringcache artifact at ${artifact_path}" >&2
  ls -R "$artifact_dir" >&2 || true
  exit 1
fi

install_dir="${RUNNER_TEMP:-/tmp}/boringcache-cli/bin"
mkdir -p "$install_dir"
cp "$artifact_path" "${install_dir}/boringcache"
chmod +x "${install_dir}/boringcache"

echo "${install_dir}" >> "${GITHUB_PATH:?}"
echo "Installed custom benchmark CLI: ${install_dir}/boringcache"
"${install_dir}/boringcache" --version
