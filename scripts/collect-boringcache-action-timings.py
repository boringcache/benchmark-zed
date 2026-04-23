#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path


BENCHMARK_CONFIGS = {
    "zed-sccache": {
        "phases": [
            {
                "name": "seed",
                "job_prefixes": ["sccache Seed (BoringCache"],
                "configure_step": "Configure boringcache/one for Rust sccache benchmark",
                "post_step": "Post Configure boringcache/one for Rust sccache benchmark",
            },
            {
                "name": "warm1",
                "job_prefixes": [
                    "sccache Warm rerun (BoringCache)",
                    "sccache Scenario (warm1) (BoringCache)",
                ],
                "configure_step": "Configure boringcache/one for Rust sccache benchmark",
                "post_step": "Post Configure boringcache/one for Rust sccache benchmark",
            },
        ],
    },
    "grpc-bazel": {
        "phases": [
            {
                "name": "seed",
                "job_prefixes": ["Bazel Seed (BoringCache"],
                "configure_step": "Configure boringcache/one",
                "post_step": "Post Configure boringcache/one",
            },
            {
                "name": "warm1",
                "job_prefixes": [
                    "Bazel Warm rerun (BoringCache)",
                    "Bazel Scenario (warm1) (BoringCache)",
                ],
                "configure_step": "Configure boringcache/one",
                "post_step": "Post Configure boringcache/one",
            },
        ],
    },
}

ARCHIVE_CREATED_RE = re.compile(
    r"Archive created in (?P<seconds>[\d.]+)(?P<unit>ms|s): "
    r"(?P<src>[\d.]+) (?P<src_unit>[kMGT]?B) → "
    r"(?P<dst>[\d.]+) (?P<dst_unit>[kMGT]?B)",
    re.IGNORECASE,
)
CREATE_ARCHIVE_DONE_RE = re.compile(
    r"(?P<key>\S+) \[3/6\] Creating archive \(done in (?P<seconds>[\d.]+)(?P<unit>ms|s)\)"
)
UPLOAD_ARCHIVE_SKIPPED_RE = re.compile(r"(?P<key>\S+) \[5/6\] Uploading archive skipped", re.IGNORECASE)
UPLOAD_ARCHIVE_DONE_RE = re.compile(
    r"(?P<key>\S+) \[5/6\] Uploading archive \(done in (?P<seconds>[\d.]+)(?P<unit>ms|s)\)",
    re.IGNORECASE,
)
UPLOADED_SUMMARY_RE = re.compile(
    r"info:\s+Uploaded (?P<src>[\d.]+) (?P<src_unit>[kMGT]?B) → "
    r"(?P<dst>[\d.]+) (?P<dst_unit>[kMGT]?B).* @ (?P<rate>[\d.]+) MB/s",
    re.IGNORECASE,
)
COMPLETED_SAVING_RE = re.compile(
    r"Completed saving (?P<key>\S+) "
    r"\((?P<files>[^,]+) files, (?P<src>[\d.]+) (?P<src_unit>[kMGT]?B)\) in "
    r"(?P<total>[\d.]+)(?P<total_unit>ms|s) "
    r"\(archive: (?P<archive>[\d.]+)(?P<archive_unit>ms|s), "
    r"upload: (?P<upload>[\d.]+)(?P<upload_unit>ms|s)\)",
    re.IGNORECASE,
)
COMPLETED_SAVING_SUMMARY_RE = re.compile(
    r"Completed Saving (?P<key>\S+) "
    r"\((?P<total>[\d.]+)(?P<total_unit>ms|s), (?P<src>[\d.]+) (?P<src_unit>[kMGT]?B), (?P<files>[^)]+)\)",
    re.IGNORECASE,
)
EXTRACTING_ARCHIVE_RE = re.compile(
    r"Extracting archive \((?P<size>[\d.]+) (?P<size_unit>[kMGT]?B)\) to ",
    re.IGNORECASE,
)
COMPLETED_RESTORE_RE = re.compile(
    r"Completed Restoring cache \[(?P<key>[^\]]+)\] "
    r"\((?P<total>[\d.]+)(?P<unit>ms|s), (?P<size>[\d.]+) (?P<size_unit>[kMGT]?B), (?P<files>[^)]+)\)",
    re.IGNORECASE,
)

SIZE_MULTIPLIERS = {
    "B": 1,
    "kB": 1_000,
    "MB": 1_000_000,
    "GB": 1_000_000_000,
    "TB": 1_000_000_000_000,
}
LOG_LINE_RE = re.compile(
    r"(?P<timestamp>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z)\s(?P<message>.*)$"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--benchmark", required=True)
    parser.add_argument("--run-id", default=os.environ.get("GITHUB_RUN_ID"))
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY"))
    parser.add_argument("--output-dir", required=True)
    return parser.parse_args()


def run_gh(*args: str) -> str:
    return subprocess.check_output(["gh", *args], text=True, encoding="utf-8", errors="replace")


def parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def step_seconds(step: dict) -> int | None:
    started = step.get("startedAt")
    completed = step.get("completedAt")
    if not started or not completed:
        return None
    delta = parse_timestamp(completed) - parse_timestamp(started)
    return int(delta.total_seconds())


def duration_seconds(value: str, unit: str) -> float:
    scalar = float(value)
    if unit == "ms":
        return scalar / 1000.0
    return scalar


def size_bytes(value: str, unit: str) -> int:
    normalized_unit = "kB" if unit == "KB" else unit
    return int(round(float(value) * SIZE_MULTIPLIERS[normalized_unit]))


def round_float(value: float | None) -> float | None:
    if value is None:
        return None
    return round(value, 3)


def format_seconds(value: float | int | None) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, int) or abs(value - round(value)) < 0.0005:
        return f"{int(round(value))}s"
    return f"{value:.1f}s"


def format_bytes(value: int | None) -> str:
    if value in (None, 0):
        return "0 B" if value == 0 else "n/a"
    thresholds = [
        (1_000_000_000_000, "TB"),
        (1_000_000_000, "GB"),
        (1_000_000, "MB"),
        (1_000, "kB"),
    ]
    for threshold, unit in thresholds:
        if value >= threshold:
            return f"{value / threshold:.2f} {unit}"
    return f"{value} B"


def safe_diff(left: float | int | None, right: float | int | None) -> float | None:
    if left is None or right is None:
        return None
    diff = float(left) - float(right)
    if diff < 0 and abs(diff) < 0.25:
        return 0.0
    return round_float(diff)


def find_job(jobs: list[dict], prefixes: list[str]) -> dict | None:
    for prefix in prefixes:
        for job in jobs:
            if job.get("name", "").startswith(prefix):
                return job
    return None


def find_step_duration(job: dict, step_name: str) -> int | None:
    for step in job.get("steps", []):
        if step.get("name") == step_name:
            return step_seconds(step)
    return None


def ensure_save_entry(entries: dict[str, dict], key: str) -> dict:
    entry = entries.setdefault(
        key,
        {
            "key": key,
            "files": None,
            "source_bytes": None,
            "compressed_bytes": None,
            "total_seconds": None,
            "archive_seconds": None,
            "upload_seconds": None,
            "other_seconds": None,
            "upload_rate_mb_per_s": None,
            "uploaded": None,
            "upload_skipped": False,
        },
    )
    return entry


def parse_job_log(log_text: str) -> tuple[list[dict], list[dict]]:
    records: list[tuple[datetime, str]] = []
    for raw_line in log_text.splitlines():
        match = LOG_LINE_RE.search(raw_line)
        if match is None:
            continue
        records.append((parse_timestamp(match.group("timestamp")), match.group("message").strip()))

    save_entries: dict[str, dict] = {}
    restore_entries: list[dict] = []
    pending_archive: dict | None = None
    last_upload_key: str | None = None
    pending_extract_timestamp: datetime | None = None
    pending_extract_bytes: int | None = None

    for timestamp, message in records:
        match = ARCHIVE_CREATED_RE.search(message)
        if match:
            pending_archive = {
                "source_bytes": size_bytes(match.group("src"), match.group("src_unit")),
                "compressed_bytes": size_bytes(match.group("dst"), match.group("dst_unit")),
                "archive_seconds": duration_seconds(match.group("seconds"), match.group("unit")),
            }
            continue

        match = CREATE_ARCHIVE_DONE_RE.search(message)
        if match:
            entry = ensure_save_entry(save_entries, match.group("key"))
            if pending_archive:
                entry["source_bytes"] = pending_archive["source_bytes"]
                entry["compressed_bytes"] = pending_archive["compressed_bytes"]
                entry["archive_seconds"] = pending_archive["archive_seconds"]
                pending_archive = None
            continue

        match = UPLOAD_ARCHIVE_SKIPPED_RE.search(message)
        if match:
            entry = ensure_save_entry(save_entries, match.group("key"))
            entry["uploaded"] = False
            entry["upload_skipped"] = True
            continue

        match = UPLOAD_ARCHIVE_DONE_RE.search(message)
        if match:
            last_upload_key = match.group("key")
            continue

        match = UPLOADED_SUMMARY_RE.search(message)
        if match and last_upload_key:
            entry = ensure_save_entry(save_entries, last_upload_key)
            if entry.get("source_bytes") is None:
                entry["source_bytes"] = size_bytes(match.group("src"), match.group("src_unit"))
            if entry.get("compressed_bytes") is None:
                entry["compressed_bytes"] = size_bytes(match.group("dst"), match.group("dst_unit"))
            entry["upload_rate_mb_per_s"] = round_float(float(match.group("rate")))
            last_upload_key = None
            continue

        match = COMPLETED_SAVING_RE.search(message)
        if match:
            entry = ensure_save_entry(save_entries, match.group("key"))
            entry["files"] = match.group("files")
            entry["source_bytes"] = size_bytes(match.group("src"), match.group("src_unit"))
            entry["total_seconds"] = duration_seconds(match.group("total"), match.group("total_unit"))
            entry["archive_seconds"] = duration_seconds(match.group("archive"), match.group("archive_unit"))
            entry["upload_seconds"] = duration_seconds(match.group("upload"), match.group("upload_unit"))
            entry["other_seconds"] = safe_diff(
                entry["total_seconds"],
                (entry["archive_seconds"] or 0.0) + (entry["upload_seconds"] or 0.0),
            )
            if entry.get("compressed_bytes") and entry["upload_seconds"] and entry["upload_seconds"] > 0:
                computed_rate = (entry["compressed_bytes"] / 1_000_000) / entry["upload_seconds"]
                entry["upload_rate_mb_per_s"] = round_float(entry.get("upload_rate_mb_per_s") or computed_rate)
            if entry["upload_seconds"] == 0:
                entry["uploaded"] = False
            elif entry["uploaded"] is None:
                entry["uploaded"] = True
            continue

        match = COMPLETED_SAVING_SUMMARY_RE.search(message)
        if match:
            entry = ensure_save_entry(save_entries, match.group("key"))
            entry["files"] = match.group("files")
            entry["source_bytes"] = size_bytes(match.group("src"), match.group("src_unit"))
            entry["total_seconds"] = duration_seconds(match.group("total"), match.group("total_unit"))
            if entry.get("upload_seconds") is None and entry.get("upload_skipped"):
                entry["upload_seconds"] = 0.0
            entry["other_seconds"] = safe_diff(
                entry["total_seconds"],
                (entry["archive_seconds"] or 0.0) + (entry["upload_seconds"] or 0.0),
            )
            if entry["uploaded"] is None:
                entry["uploaded"] = bool(entry.get("upload_seconds"))
            continue

        match = EXTRACTING_ARCHIVE_RE.search(message)
        if match:
            pending_extract_timestamp = timestamp
            pending_extract_bytes = size_bytes(match.group("size"), match.group("size_unit"))
            continue

        match = COMPLETED_RESTORE_RE.search(message)
        if match:
            total_seconds = duration_seconds(match.group("total"), match.group("unit"))
            extract_seconds = None
            pre_extract_seconds = None
            if pending_extract_timestamp is not None:
                extract_seconds = round_float((timestamp - pending_extract_timestamp).total_seconds())
                pre_extract_seconds = safe_diff(total_seconds, extract_seconds)
            restore_entries.append(
                {
                    "key": match.group("key"),
                    "files": match.group("files"),
                    "compressed_bytes": size_bytes(match.group("size"), match.group("size_unit")),
                    "total_seconds": round_float(total_seconds),
                    "extract_seconds": extract_seconds,
                    "download_and_overhead_seconds": pre_extract_seconds,
                    "extract_size_bytes": pending_extract_bytes,
                }
            )
            pending_extract_timestamp = None
            pending_extract_bytes = None
            continue

    normalized_save_entries: list[dict] = []
    for entry in sorted(save_entries.values(), key=lambda item: item["key"]):
        if entry.get("compressed_bytes") and entry.get("upload_seconds") and entry["upload_seconds"] > 0 and entry.get("upload_rate_mb_per_s") is None:
            entry["upload_rate_mb_per_s"] = round_float((entry["compressed_bytes"] / 1_000_000) / entry["upload_seconds"])
        if entry["uploaded"] is None:
            entry["uploaded"] = bool(entry.get("upload_seconds"))
        for key in ("total_seconds", "archive_seconds", "upload_seconds", "other_seconds"):
            entry[key] = round_float(entry[key])
        normalized_save_entries.append(entry)

    normalized_restore_entries = sorted(restore_entries, key=lambda item: item["key"])
    return normalized_save_entries, normalized_restore_entries


def aggregate_save(entries: list[dict], post_step_seconds: int | None) -> dict:
    total_seconds = round_float(sum(entry["total_seconds"] or 0.0 for entry in entries))
    archive_seconds = round_float(sum(entry["archive_seconds"] or 0.0 for entry in entries))
    upload_seconds = round_float(sum(entry["upload_seconds"] or 0.0 for entry in entries))
    other_seconds = round_float(sum(entry["other_seconds"] or 0.0 for entry in entries))
    compressed_bytes = sum(entry["compressed_bytes"] or 0 for entry in entries)
    source_bytes = sum(entry["source_bytes"] or 0 for entry in entries)
    uploaded_entry_count = sum(1 for entry in entries if entry["uploaded"])
    skipped_entry_count = sum(1 for entry in entries if entry["upload_skipped"])
    aggregate_rate = None
    if upload_seconds and upload_seconds > 0 and compressed_bytes > 0:
        aggregate_rate = round_float((compressed_bytes / 1_000_000) / upload_seconds)
    return {
        "entry_count": len(entries),
        "uploaded_entry_count": uploaded_entry_count,
        "skipped_entry_count": skipped_entry_count,
        "source_bytes": source_bytes,
        "compressed_bytes": compressed_bytes,
        "total_seconds": total_seconds,
        "archive_seconds": archive_seconds,
        "upload_seconds": upload_seconds,
        "other_seconds": other_seconds,
        "post_step_seconds": post_step_seconds,
        "post_step_non_save_seconds": safe_diff(post_step_seconds, total_seconds),
        "upload_rate_mb_per_s": aggregate_rate,
        "entries": entries,
    }


def aggregate_restore(entries: list[dict], configure_step_seconds: int | None) -> dict:
    total_seconds = round_float(sum(entry["total_seconds"] or 0.0 for entry in entries))
    extract_seconds = round_float(sum(entry["extract_seconds"] or 0.0 for entry in entries if entry["extract_seconds"] is not None))
    download_and_overhead_seconds = round_float(
        sum(entry["download_and_overhead_seconds"] or 0.0 for entry in entries if entry["download_and_overhead_seconds"] is not None)
    )
    compressed_bytes = sum(entry["compressed_bytes"] or 0 for entry in entries)
    return {
        "entry_count": len(entries),
        "compressed_bytes": compressed_bytes,
        "total_seconds": total_seconds,
        "extract_seconds": extract_seconds,
        "download_and_overhead_seconds": download_and_overhead_seconds,
        "configure_step_seconds": configure_step_seconds,
        "configure_step_non_restore_seconds": safe_diff(configure_step_seconds, total_seconds),
        "entries": entries,
    }


def phase_payload(job: dict | None, phase_config: dict, repo: str) -> dict:
    if job is None:
        return {
            "job_found": False,
            "job_name": None,
            "job_id": None,
            "configure_step_seconds": None,
            "post_step_seconds": None,
            "archive_restore": aggregate_restore([], None),
            "archive_save": aggregate_save([], None),
        }

    configure_step_seconds = find_step_duration(job, phase_config["configure_step"])
    post_step_seconds = find_step_duration(job, phase_config["post_step"])
    log_text = run_gh("run", "view", "--job", str(job["databaseId"]), "--repo", repo, "--log")
    save_entries, restore_entries = parse_job_log(log_text)
    return {
        "job_found": True,
        "job_name": job["name"],
        "job_id": job["databaseId"],
        "configure_step_seconds": configure_step_seconds,
        "post_step_seconds": post_step_seconds,
        "archive_restore": aggregate_restore(restore_entries, configure_step_seconds),
        "archive_save": aggregate_save(save_entries, post_step_seconds),
    }


def render_summary_table(report: dict) -> list[str]:
    lines = [
        "| Phase | Configure step | Restore total | Restore outside extract | Post step | Save total | Save upload | Save archive | Post-step non-save |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for phase_name, phase in report["phases"].items():
        restore = phase["archive_restore"]
        save = phase["archive_save"]
        lines.append(
            "| {phase} | {configure} | {restore_total} | {restore_other} | {post_step} | {save_total} | {save_upload} | {save_archive} | {post_other} |".format(
                phase=phase_name,
                configure=format_seconds(phase["configure_step_seconds"]),
                restore_total=format_seconds(restore["total_seconds"]),
                restore_other=format_seconds(restore["download_and_overhead_seconds"]),
                post_step=format_seconds(phase["post_step_seconds"]),
                save_total=format_seconds(save["total_seconds"]),
                save_upload=format_seconds(save["upload_seconds"]),
                save_archive=format_seconds(save["archive_seconds"]),
                post_other=format_seconds(save["post_step_non_save_seconds"]),
            )
        )
    return lines


def render_detail_tables(report: dict) -> list[str]:
    lines: list[str] = []
    save_rows: list[str] = []
    restore_rows: list[str] = []

    for phase_name, phase in report["phases"].items():
        for entry in phase["archive_save"]["entries"]:
            save_rows.append(
                "| {phase} | `{key}` | {source} | {compressed} | {total} | {archive} | {upload} | {other} | {uploaded} | {rate} |".format(
                    phase=phase_name,
                    key=entry["key"],
                    source=format_bytes(entry["source_bytes"]),
                    compressed=format_bytes(entry["compressed_bytes"]),
                    total=format_seconds(entry["total_seconds"]),
                    archive=format_seconds(entry["archive_seconds"]),
                    upload=format_seconds(entry["upload_seconds"]),
                    other=format_seconds(entry["other_seconds"]),
                    uploaded="yes" if entry["uploaded"] else "no",
                    rate=f"{entry['upload_rate_mb_per_s']:.1f} MB/s" if entry["upload_rate_mb_per_s"] is not None else "n/a",
                )
            )
        for entry in phase["archive_restore"]["entries"]:
            restore_rows.append(
                "| {phase} | `{key}` | {compressed} | {total} | {extract} | {other} |".format(
                    phase=phase_name,
                    key=entry["key"],
                    compressed=format_bytes(entry["compressed_bytes"]),
                    total=format_seconds(entry["total_seconds"]),
                    extract=format_seconds(entry["extract_seconds"]),
                    other=format_seconds(entry["download_and_overhead_seconds"]),
                )
            )

    if save_rows:
        lines.extend(
            [
                "",
                "### Save entries",
                "",
                "| Phase | Entry | Source bytes | Archive bytes | Total | Archive | Upload | Other | Uploaded | Rate |",
                "|---|---|---|---|---|---|---|---|---|---|",
                *save_rows,
            ]
        )

    if restore_rows:
        lines.extend(
            [
                "",
                "### Restore entries",
                "",
                "| Phase | Entry | Archive bytes | Total | Extract | Download + overhead |",
                "|---|---|---|---|---|---|",
                *restore_rows,
            ]
        )

    return lines


def main() -> int:
    args = parse_args()
    if not args.run_id or not args.repo:
        raise SystemExit("Missing --run-id/--repo and GITHUB_RUN_ID/GITHUB_REPOSITORY are unset")

    config = BENCHMARK_CONFIGS.get(args.benchmark)
    if config is None:
        raise SystemExit(f"Unsupported benchmark for action timing report: {args.benchmark}")

    jobs_payload = json.loads(run_gh("run", "view", str(args.run_id), "--repo", args.repo, "--json", "jobs"))
    jobs = jobs_payload.get("jobs", [])

    phases: dict[str, dict] = {}
    for phase_config in config["phases"]:
        job = find_job(jobs, phase_config["job_prefixes"])
        phases[phase_config["name"]] = phase_payload(job, phase_config, args.repo)

    report = {
        "benchmark": args.benchmark,
        "repository": args.repo,
        "run_id": int(args.run_id),
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "phases": phases,
    }

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"{args.benchmark}-boringcache-action-timings.json"
    md_path = output_dir / f"{args.benchmark}-boringcache-action-timings.md"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")

    lines = [
        f"## {args.benchmark} BoringCache action timings",
        "",
        f"- Run: `{args.run_id}`",
        f"- Repository: `{args.repo}`",
        "",
        *render_summary_table(report),
        *render_detail_tables(report),
        "",
    ]
    md_path.write_text("\n".join(lines))

    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a", encoding="utf-8") as handle:
            handle.write(f"json_path={json_path}\n")
            handle.write(f"md_path={md_path}\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
