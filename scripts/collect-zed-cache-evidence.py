#!/usr/bin/env python3
"""Record target and compiler cache reuse as separate observations."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def read_json(path: str) -> dict[str, Any]:
    value = json.loads(Path(path).read_text())
    if not isinstance(value, dict):
        raise TypeError(f"Expected a JSON object in {path}")
    return value


def total(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, dict):
        counts = value.get("counts")
        if isinstance(counts, dict) and all(isinstance(item, int) for item in counts.values()):
            return sum(counts.values())
    return None


def magic_compiler(stats: dict[str, Any]) -> dict[str, Any]:
    values = stats.get("stats") or {}
    names = {
        "compile_requests": "compile_requests",
        "compile_requests_executed": "requests_executed",
        "cache_hits": "cache_hits",
        "cache_misses": "cache_misses",
        "non_cacheable_calls": "requests_not_cacheable",
        "cache_errors": "cache_errors",
        "cache_read_errors": "cache_read_errors",
        "cache_write_errors": "cache_write_errors",
        "cache_timeouts": "cache_timeouts",
    }
    return {"tool": "sccache", "status": "measured", **{name: total(values.get(field)) for name, field in names.items()}}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", required=True, choices=("runs-on-cache", "boringcache"))
    parser.add_argument("--cache-variant", required=True)
    parser.add_argument("--action-evidence", default="")
    parser.add_argument("--magic-hit", default="")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    if args.provider == "boringcache":
        evidence = read_json(args.action_evidence)
        restore = (evidence.get("phases") or {}).get("restore") or {}
        mode = restore.get("mode_evidence") or {}
        payload = {
            "schema_version": 1,
            "provider": args.provider,
            "cache_variant": args.cache_variant,
            "target_restore_hit": mode.get("target_cache_hit") if args.cache_variant != "sccache-only" else None,
            "dependency_archive_hit": None,
            "compiler_backend": "BoringCache WebDAV" if args.cache_variant != "target" else None,
            "compiler_sessions": [] if args.cache_variant == "target" else [{"session": "build", "action_cache_hit": restore.get("cache_hit"), "compiler_cache_entry_hit": mode.get("compiler_cache_hit"), "compiler": mode.get("native_tool")}],
        }
    else:
        sessions = []
        location = None
        if args.cache_variant != "target":
            stats = read_json("benchmark-results/magic-sccache.json")
            location = stats.get("cache_location")
            if not isinstance(location, str) or "S3" not in location:
                raise ValueError(f"RunsOn sccache did not select S3: {location!r}")
            sessions = [{"session": "build", "compiler": magic_compiler(stats)}]
        payload = {
            "schema_version": 1,
            "provider": args.provider,
            "cache_variant": args.cache_variant,
            "target_restore_hit": args.magic_hit == "true" if args.magic_hit and args.cache_variant != "sccache-only" else None,
            "dependency_archive_hit": args.magic_hit == "true" if args.magic_hit and args.cache_variant == "sccache-only" else None,
            "compiler_backend": location,
            "compiler_sessions": sessions,
        }

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(output)


if __name__ == "__main__":
    main()
