#!/usr/bin/env bash
set -euo pipefail

echo "::group::Disk before cleanup"
df -h / /home /mnt 2>/dev/null || true
echo "::endgroup::"

required_gb="${BORINGCACHE_MIN_FREE_DISK_GB:-45}"
available_kb="$(df -Pk / | awk 'NR == 2 { print $4 }')"
required_kb=$((required_gb * 1024 * 1024))
if (( available_kb >= required_kb )); then
  echo "Free disk is already at least ${required_gb}GiB; skipping cleanup."
  docker system df || true
  exit 0
fi

echo "Free disk below ${required_gb}GiB; reclaiming hosted-runner tool caches."

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
