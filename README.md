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
- the immutable `boringcache/one` Rust `sccache` flow rather than benchmark-local proxy wiring
- whether BoringCache can pair native `sccache` proxy hits with archived Cargo dependency state cleanly

Both BoringCache consumers restore Cargo registry and git dependency archives
alongside the remote `sccache` population, matching the state restored by the
Actions/cache control. The opt-in target consumer additionally restores
`target/` concurrently. It runs Deno's content-keyed mtime-cache algorithm
before the seed build and again after restore, preserving Cargo's source
freshness contract across fresh checkouts: unchanged files regain their seed
mtimes, while changed files keep a new mtime and rebuild normally. Without
this ledger, a large target archive can restore successfully while Cargo still
rejects most of it because the fresh checkout is newer than its fingerprints.

The vendored implementation in `scripts/deno-mtime-cache-action.js` retains
Deno's MIT copyright header. `scripts/run-mtime-cache.js` only adapts it to the
nested Zed checkout used by this benchmark.

## Cargo Product Proof

The canary-only Cargo proof uses one product boundary for the complete Rust
lifecycle. An exact immutable CLI runs `boringcache cargo --write` on the pinned
base commit, then a fresh runner runs `boringcache cargo --read-only` on the
adjacent head commit. The CLI owns target transport, source freshness, Cargo
registry and Git state, and the sccache proxy in both jobs; the workflow only
checks the signed `archive-chunks-v1` result and Cargo/native-tool evidence.

This proof does not run the benchmark's Deno-derived mtime helper. It requires
the CLI freshness descriptor to preserve unchanged source mtimes, keep changed
sources new, make Cargo report both fresh and rebuilt artifacts, and exercise
sccache without read errors or timeouts. Suppressed cache writes in the
read-only rolling job are diagnostic counters, not remote-storage failures.

## Token Model

This repo uses split BoringCache tokens as the standard CI shape:

- `BORINGCACHE_RESTORE_TOKEN` for read-only restore and proxy access
- `BORINGCACHE_SAVE_TOKEN` for trusted write paths
