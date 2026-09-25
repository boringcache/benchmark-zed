# RunsOn comparison

The comparison uses the same pinned Zed source, build commands, Rust
toolchain, sccache version, and runner specifications for both providers.

| Case | RunsOn | BoringCache |
| --- | --- | --- |
| `target` | Magic Cache archive of Cargo dependencies and `target` | Cargo dependency archives and typed `target` archive, compiler cache disabled |
| `sccache-only` | Native sccache S3 backend; no archives | Native sccache WebDAV backend; no archives |
| `target-sccache` | Native sccache S3 plus the target case's archives | Native sccache WebDAV plus the target case's archives |

No workflow rewrites source or Rust sysroot timestamps. Each product supplies
its own freshness behavior. BoringCache's typed Cargo target archive can
restore timestamps for unchanged tracked repository sources; this does not
establish freshness for every external or generated input.

The target workflow builds the pinned base commit cold, then builds its
immediate successor on a fresh runner using the cold build's cache. There is
no intervening same-commit warm build. Both phases publish their cache state.
The other entry points retain their declared same-commit and rolling phases.

Cache namespaces include the run ID, run attempt, and case. Compiler cache
directories are never archived. An archive hit means the archive was restored;
compiler hits and misses are reported separately from native sccache statistics.
A successful build alone does not establish useful compiler cache reuse.

RunsOn comparisons share `zed-runs-on-rolling11` with
`cancel-in-progress: false` and `queue: max`. This keeps one comparison active
and allows pending runs to wait. Dispatches of older workflow revisions retain
their older queue policy.

Runs before this change used workflow timestamp preparation. Older default-
branch sccache comparisons archived a local sccache directory while BoringCache
used a native remote backend. Treat those as separate experiments, not matched
product comparisons. Historical artifacts remain unchanged.

References: [RunsOn caching](https://runs-on.com/docs/performance/caching/),
[RunsOn native sccache input](https://github.com/runs-on/action/blob/efac073ea2507ec18797de3a81704201ade11d9d/action.yml),
and [GitHub concurrency](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency).
