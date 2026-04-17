#!/usr/bin/env bash
set -euo pipefail

echo "::group::Disk before cleanup"
df -h / /home /mnt 2>/dev/null || true
echo "::endgroup::"

sudo rm -rf \
  /usr/local/lib/android \
  /usr/share/dotnet \
  /opt/ghc \
  /usr/local/share/boost \
  /opt/hostedtoolcache/CodeQL \
  || true

sudo docker system prune --all --force --volumes >/dev/null 2>&1 || true
sudo apt-get clean >/dev/null 2>&1 || true

rm -rf \
  "${HOME}/.cache/pip" \
  "${HOME}/.npm" \
  "${HOME}/.cache/yarn" \
  || true

echo "::group::Disk after cleanup"
df -h / /home /mnt 2>/dev/null || true
echo "::endgroup::"
