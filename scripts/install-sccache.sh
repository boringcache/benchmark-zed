#!/usr/bin/env bash
set -euo pipefail

version="0.14.0"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --version)
      version="${2:?--version requires a value}"
      shift 2
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 1
      ;;
  esac
done

normalized_version="${version#v}"
requested_tag="v${normalized_version}"
install_dir="${HOME}/.local/bin"
binary_path="${install_dir}/sccache"

if command -v sccache >/dev/null 2>&1; then
  existing_version="$(sccache --version 2>/dev/null | awk 'NR==1 {print $2}')"
  if [[ "$existing_version" == "$normalized_version" ]]; then
    echo "Using existing sccache ${normalized_version} from PATH"
    exit 0
  fi
fi

os="$(uname -s | tr '[:upper:]' '[:lower:]')"
arch="$(uname -m)"
asset_name=""

case "${os}/${arch}" in
  linux/x86_64)
    asset_name="sccache-${requested_tag}-x86_64-unknown-linux-musl"
    ;;
  linux/aarch64|linux/arm64)
    asset_name="sccache-${requested_tag}-aarch64-unknown-linux-musl"
    ;;
  darwin/arm64)
    asset_name="sccache-${requested_tag}-aarch64-apple-darwin"
    ;;
  *)
    echo "Unsupported platform for benchmark sccache installer: ${os}/${arch}" >&2
    exit 1
    ;;
esac

archive_ext=".tar.gz"
url="https://github.com/mozilla/sccache/releases/download/${requested_tag}/${asset_name}${archive_ext}"
temp_dir="$(mktemp -d)"
archive_path="${temp_dir}/sccache${archive_ext}"

cleanup() {
  rm -rf "${temp_dir}"
}
trap cleanup EXIT

curl -sS --fail --location --output "${archive_path}" "${url}"
tar -xzf "${archive_path}" -C "${temp_dir}"

mkdir -p "${install_dir}"
cp "${temp_dir}/${asset_name}/sccache" "${binary_path}"
chmod +x "${binary_path}"

if [[ -n "${GITHUB_PATH:-}" ]]; then
  echo "${install_dir}" >> "${GITHUB_PATH}"
else
  export PATH="${install_dir}:${PATH}"
fi

echo "Installed sccache ${normalized_version}"
"${binary_path}" --version
