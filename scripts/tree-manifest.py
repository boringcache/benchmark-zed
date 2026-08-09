#!/usr/bin/env python3
"""Emit or compare a byte-exact manifest of a restored Cargo target tree.

Cargo decides what to rebuild from file content and mtime, so "the cache
restored" and "the cache restored *exactly*" are different claims. This records
everything Cargo's freshness check can observe -- content digest, size, mode,
nanosecond mtime, symlink target, and hard-link topology -- so a post-build
manifest and a post-restore manifest can be compared entry by entry.

  emit    <root> <out.json> [--no-digest]
  compare <a.json> <b.json>

Comparing a seed's post-build manifest against the next run's post-restore
manifest answers whether a rebuild was caused by real source changes or by the
transport losing fidelity.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path


def digest_file(path: Path) -> str:
    sha = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            sha.update(chunk)
    return sha.hexdigest()


def emit(root: Path, out: Path, want_digest: bool) -> int:
    entries: dict[str, dict] = {}
    inodes: dict[tuple[int, int], list[str]] = {}
    files = dirs = links = 0

    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames.sort()
        filenames.sort()
        for name in [*dirnames, *filenames]:
            full = Path(dirpath) / name
            rel = str(full.relative_to(root))
            try:
                st = full.lstat()
            except OSError as error:
                entries[rel] = {"error": str(error)}
                continue

            record: dict = {
                "mode": oct(st.st_mode),
                "mtime_ns": st.st_mtime_ns,
            }
            if os.path.islink(full):
                links += 1
                record["kind"] = "symlink"
                record["target"] = os.readlink(full)
            elif full.is_dir():
                dirs += 1
                record["kind"] = "dir"
            else:
                files += 1
                record["kind"] = "file"
                record["size"] = st.st_size
                record["nlink"] = st.st_nlink
                if st.st_nlink > 1:
                    inodes.setdefault((st.st_dev, st.st_ino), []).append(rel)
                if want_digest:
                    try:
                        record["sha256"] = digest_file(full)
                    except OSError as error:
                        record["sha256_error"] = str(error)
            entries[rel] = record

    # Hard-link groups are recorded as sorted path sets so topology is compared
    # without depending on inode numbers, which never survive a restore.
    hardlinks = sorted(sorted(paths) for paths in inodes.values() if len(paths) > 1)

    manifest = {
        "schema": "zed_tree_manifest.v1",
        "root": str(root),
        "counts": {
            "entries": len(entries),
            "files": files,
            "dirs": dirs,
            "symlinks": links,
            "hardlink_groups": len(hardlinks),
        },
        "digested": want_digest,
        "hardlinks": hardlinks,
        "entries": entries,
    }
    out.write_text(json.dumps(manifest, sort_keys=True))
    print(
        f"Manifest: {len(entries)} entries "
        f"({files} files, {dirs} dirs, {links} symlinks, "
        f"{len(hardlinks)} hard-link groups) -> {out}"
    )
    return 0


def compare(a_path: Path, b_path: Path) -> int:
    a = json.loads(a_path.read_text())
    b = json.loads(b_path.read_text())
    a_entries, b_entries = a["entries"], b["entries"]

    missing = sorted(set(a_entries) - set(b_entries))
    added = sorted(set(b_entries) - set(a_entries))
    differing: dict[str, list[str]] = {}

    for rel in sorted(set(a_entries) & set(b_entries)):
        left, right = a_entries[rel], b_entries[rel]
        fields = [key for key in set(left) | set(right) if left.get(key) != right.get(key)]
        if fields:
            differing[rel] = sorted(fields)

    hardlinks_match = a.get("hardlinks") == b.get("hardlinks")
    identical = not missing and not added and not differing and hardlinks_match

    lines = [
        "## Target tree identity",
        "",
        f"- baseline: `{a_path.name}` ({a['counts']['entries']} entries)",
        f"- restored: `{b_path.name}` ({b['counts']['entries']} entries)",
        f"- content digests compared: `{a.get('digested') and b.get('digested')}`",
        f"- missing after restore: {len(missing)}",
        f"- unexpected after restore: {len(added)}",
        f"- differing entries: {len(differing)}",
        f"- hard-link topology preserved: `{hardlinks_match}`",
        f"- **identical: `{identical}`**",
    ]

    if differing:
        field_counts: dict[str, int] = {}
        for fields in differing.values():
            for field in fields:
                field_counts[field] = field_counts.get(field, 0) + 1
        lines.append("")
        lines.append("Differing fields by frequency:")
        for field, count in sorted(field_counts.items(), key=lambda item: -item[1]):
            lines.append(f"  - `{field}`: {count}")
        lines.append("")
        lines.append("First 20 differing paths:")
        for rel in list(differing)[:20]:
            lines.append(f"  - `{rel}` ({', '.join(differing[rel])})")
    for label, paths in (("missing", missing), ("unexpected", added)):
        if paths:
            lines.append("")
            lines.append(f"First 20 {label} paths:")
            for rel in paths[:20]:
                lines.append(f"  - `{rel}`")

    report = "\n".join(lines)
    print(report)
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as handle:
            handle.write(report + "\n")
    return 0 if identical else 1


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2
    action = sys.argv[1]
    if action == "emit" and len(sys.argv) >= 4:
        return emit(
            Path(sys.argv[2]).resolve(),
            Path(sys.argv[3]),
            "--no-digest" not in sys.argv,
        )
    if action == "compare" and len(sys.argv) == 4:
        return compare(Path(sys.argv[2]), Path(sys.argv[3]))
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
