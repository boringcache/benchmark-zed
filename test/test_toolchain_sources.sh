#!/usr/bin/env bash
# Run in a disposable Ubuntu 24.04 container with this repository mounted at /repo:
# docker run --rm -v "$PWD:/repo:ro" ubuntu:24.04 bash /repo/test/test_toolchain_sources.sh
set -euo pipefail

test -f /.dockerenv
test -s /etc/apt/sources.list.d/ubuntu.sources

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
test_root="$(mktemp -d)"
broken_source=/etc/apt/sources.list.d/zed-test-unavailable.list
test ! -e "$broken_source"
trap 'rm -rf "$test_root"; rm -f "$broken_source"' EXIT
mkdir -p "$test_root/scripts" "$test_root/upstream" "$test_root/bin"
mkdir "$test_root/unavailable"
cp "$repo_root/scripts/install-zed-toolchain.sh" "$test_root/scripts/"
printf '[toolchain]\nchannel = "1.95.0"\n' > "$test_root/upstream/rust-toolchain.toml"
printf 'deb file:%s/unavailable stable main\n' "$test_root" > "$broken_source"

if apt-get -o Acquire::Retries=0 update --error-on=any > "$test_root/unscoped.log" 2>&1; then
  echo "Expected the unavailable repository to fail an unscoped update" >&2
  exit 1
fi
grep -Fq 'does not have a Release file' "$test_root/unscoped.log"

cat > "$test_root/bin/sudo" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
if [[ "$*" == *' install '* ]]; then
  exec "$@" --simulate
fi
exec "$@"
SH
cat > "$test_root/bin/rustup" <<'SH'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$RUSTUP_CALLS"
SH
chmod +x "$test_root/bin/sudo" "$test_root/bin/rustup"
export PATH="$test_root/bin:$PATH"
export RUSTUP_CALLS="$test_root/rustup.log"

if ! bash "$test_root/scripts/install-zed-toolchain.sh" > "$test_root/scoped.log" 2>&1; then
  cat "$test_root/scoped.log" >&2
  exit 1
fi
if grep -Fq "$test_root/unavailable" "$test_root/scoped.log"; then
  echo "Zed dependency installation contacted an unrelated repository" >&2
  exit 1
fi
grep -Fq 'Inst libxkbcommon-dev' "$test_root/scoped.log"
grep -Fxq 'target add --toolchain 1.95.0 x86_64-unknown-linux-musl' "$RUSTUP_CALLS"
test -f "$broken_source"
echo "Zed dependencies resolve despite an unavailable unrelated repository."
