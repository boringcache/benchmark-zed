# BoringCache Zed benchmark

This repository contains the BoringCache benchmark for Zed.

The release matrix compares one cold seed with target-only, sccache-only, and
combined Cargo plans on fresh runners. Each layer choice and both of Zed's Linux
release commands live in committed `.boringcache.toml` files under `plans/`.
The Action activates the selected plan inside the clean Zed checkout so the CLI
measures source freshness against Zed itself, while the workflow remains only a
lane/phase selector.
The GitHub workflow selects those plans and leaves cache identity, target
selection, and compiler-cache selection to the BoringCache CLI.

[`cargo-layer-source.env`](cargo-layer-source.env) pins the reviewed adjacent
source pair for that matrix independently of the continuously advancing rolling
source. Every matrix plan tag carries the pinned head identity, so a later
rolling sync cannot silently turn the cold seed into an older-cohort restore.

The root [`.boringcache.toml`](.boringcache.toml) owns the persistent rolling
chain. [`.github/workflows/zed-cargo-product.yml`](.github/workflows/zed-cargo-product.yml)
owns the independent release matrix.

The scheduled rolling chain selects one adjacent commit, benchmarks and
publishes it, and only then advances `benchmark-source.env` on `main`. The
source SHA stored inside the target snapshot must match the next run's base
SHA, so a stale target hit fails before Cargo rather than silently widening the
commit range. Scheduled and manual rolling runs share one concurrency group;
queued schedule ticks may collapse, but unbuilt source commits cannot be
skipped.
