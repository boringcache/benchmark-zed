# benchmark-zed

Zed correctness and rolling-reuse proof for the first-class BoringCache Cargo
adapter.

The benchmark has one BoringCache product boundary:

```console
boringcache cargo build --release --locked
```

The released CLI owns Cargo registry and Git dependency state, the typed Cargo
target snapshot, transported source freshness, native sccache, restore, native
evidence, and publication. Workflows own only source preparation, the pinned
toolchain, timing, and verification.

## Primary proof

`.github/workflows/zed-cargo-product.yml` is the automatic and manually
dispatchable benchmark. It publishes the pinned base commit with
`boringcache cargo --write`, then consumes that state on a fresh runner at the
adjacent head with `boringcache cargo --read-only`.

The proof fails unless:

- the target snapshot is authenticated and server-signed;
- `cargo-freshness-v2.json` is present;
- unchanged and changed source identities are both handled correctly;
- Cargo reports both reused and rebuilt artifacts for the adjacent commit; and
- native sccache reports requests without cache read errors or timeouts.

`.github/workflows/zed-cargo-rolling-chain.yml` advances an existing signed
Cargo target through one adjacent commit with the same CLI-owned lifecycle. It
also records target accumulation only when the storage layout is comparable.

Historical `mode: sccache`, raw Cargo, Actions/cache, and benchmark-local mtime
runner implementations remain available in Git and GitHub Actions history, but
are not live workflow surfaces.

## Source and tokens

The pinned Zed checkout lives in the `upstream/` submodule. The sync workflow
updates that gitlink; the Cargo product workflow runs automatically when it
changes.

CI uses split tokens:

- `BORINGCACHE_RESTORE_TOKEN` for restore and read-only proxy access;
- `BORINGCACHE_SAVE_TOKEN` for trusted publication.
