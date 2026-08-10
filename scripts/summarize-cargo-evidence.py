#!/usr/bin/env python3
"""Surface the Cargo product's rebuild set and sccache result into the run summary.

The actions/cache control lane reports how many Cargo units it compiled from
`run-zed-release-phases.sh`. The BoringCache lane reports the equivalent as
`compile_requests` inside the adapter's evidence JSON, alongside the sccache hit
rate. Printing both in the same shape is what makes the two lanes comparable on
rebuild set rather than only on wall time.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def summarize(label: str, evidence_path: Path) -> str:
    evidence = json.loads(evidence_path.read_text())
    phase = evidence.get("phases", {}).get("restore", {})
    mode = phase.get("mode_evidence", {})
    native = mode.get("native_tool", {})

    requests = native.get("compile_requests")
    executed = native.get("compile_requests_executed")
    hits = native.get("cache_hits")
    misses = native.get("cache_misses")
    rate = native.get("hit_rate")
    write_errors = native.get("cache_write_errors")
    elapsed = mode.get("elapsed_seconds")
    target_hit = mode.get("target_cache_hit")

    lines = [f"- `{label}`:"]
    if elapsed is not None:
        lines.append(f"  - elapsed: {elapsed:.0f}s")
    if target_hit is not None:
        lines.append(f"  - target snapshot restored: `{target_hit}`")
    if requests is not None:
        lines.append(
            f"  - Cargo units compiled: {executed if executed is not None else requests}"
            f" ({requests} compile requests)"
        )
    if hits is not None:
        lines.append(
            f"  - sccache: {hits} hits / {misses} misses"
            f" ({(rate or 0):.1f}% hit rate)"
        )
    if write_errors:
        lines.append(f"  - sccache write errors: {write_errors}")
    return "\n".join(lines)


def main() -> int:
    if len(sys.argv) < 2 or len(sys.argv) % 2 != 1:
        print(
            "Usage: summarize-cargo-evidence.py LABEL EVIDENCE_PATH [LABEL EVIDENCE_PATH ...]",
            file=sys.stderr,
        )
        return 2

    blocks = ["## Cargo rebuild set", ""]
    for index in range(1, len(sys.argv), 2):
        label = sys.argv[index]
        path = Path(sys.argv[index + 1])
        if not path.is_file():
            blocks.append(f"- `{label}`: evidence missing at {path}")
            continue
        try:
            blocks.append(summarize(label, path))
        except (json.JSONDecodeError, OSError) as error:
            blocks.append(f"- `{label}`: unreadable evidence ({error})")

    report = "\n".join(blocks)
    print(report)

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as handle:
            handle.write(report + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
