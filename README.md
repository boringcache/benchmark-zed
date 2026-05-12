# benchmark-zed

Public Zed Rust `sccache` benchmark runner for BoringCache vs GitHub Actions cache.

This repo exists separately from [`boringcache/benchmarks`](https://github.com/boringcache/benchmarks) so the benchmark keeps:

- one pinned upstream source commit
- isolated GitHub Actions cache usage
- one per-repo BoringCache workspace name: `boringcache/benchmark-zed`
- independent workflow history plus upstream-sync-driven benchmark runs and manual dispatches

## Source Model

- Upstream source lives in the pinned `upstream/` submodule.

Pinned upstream source:

- see committed `upstream/` submodule on `main`

## What It Measures

Fresh lane runs a no-prior-cache cold build plus one warm rerun for each backend:

- `cold`
- `warm1`

Rolling lane records the upstream commit build as-is after each upstream sync against the prior rolling cache and intentionally skips `warm1`.

The story this benchmark is meant to show is:

- speed on fresh cold and warm paths
- commit-build behavior on normal upstream syncs in the rolling lane
- storage footprint in each backend
- cache reuse through native `sccache` remote cache behavior
- the product-managed `boringcache/one@v1` Rust `sccache` flow rather than benchmark-local proxy wiring
- whether BoringCache can pair native `sccache` proxy hits with archived Cargo dependency state cleanly

## Token Model

This repo uses split BoringCache tokens as the standard CI shape:

- `BORINGCACHE_RESTORE_TOKEN` for read-only restore and proxy access
- `BORINGCACHE_SAVE_TOKEN` for trusted write paths
- `BORINGCACHE_API_TOKEN` only where a single bearer variable is still required for compatibility
