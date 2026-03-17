#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--benchmark", required=True)
    parser.add_argument("--strategy", required=True)
    parser.add_argument("--phase-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    return parser.parse_args()


def parse_env_file(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        data[key] = value
    return data


def parse_int(value: str | None) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except ValueError:
        return None


def phase_sort_key(phase: str) -> tuple[int, str]:
    order = {"warm1": 0, "warm2": 1, "stale": 2}
    return (order.get(phase, 100), phase)


def main() -> int:
    args = parse_args()
    phase_dir = Path(args.phase_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    phases: dict[str, dict[str, int | None]] = {}
    for env_path in sorted(phase_dir.glob("*.env"), key=lambda item: phase_sort_key(item.stem)):
        data = parse_env_file(env_path)
        phase = data.get("phase", env_path.stem)
        reported_seconds = parse_int(data.get("seconds"))
        restore_seconds = parse_int(data.get("restore_seconds"))
        proxy_ready_seconds = parse_int(data.get("proxy_ready_seconds"))
        build_seconds = parse_int(data.get("build_seconds"))
        end_to_end_seconds = parse_int(data.get("end_to_end_seconds"))
        if end_to_end_seconds is None:
            end_to_end_seconds = reported_seconds

        component_values = [restore_seconds, proxy_ready_seconds, build_seconds]
        if end_to_end_seconds is not None and all(value is not None for value in component_values):
            unattributed_seconds = end_to_end_seconds - sum(int(value) for value in component_values)
        else:
            unattributed_seconds = None

        phases[phase] = {
            "reported_seconds": reported_seconds,
            "end_to_end_seconds": end_to_end_seconds,
            "restore_seconds": restore_seconds,
            "proxy_ready_seconds": proxy_ready_seconds,
            "build_seconds": build_seconds,
            "unattributed_seconds": unattributed_seconds,
        }

    json_path = output_dir / f"{args.benchmark}-{args.strategy}-phase-breakdown.json"
    md_path = output_dir / f"{args.benchmark}-{args.strategy}-phase-breakdown.md"

    payload = {
        "benchmark": args.benchmark,
        "strategy": args.strategy,
        "phases": phases,
    }
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")

    def render_cell(value: int | None, *, suffix: str = "s") -> str:
        if value is None:
            return "n/a"
        return f"{value}{suffix}"

    lines = [
        f"## {args.benchmark} ({args.strategy}) phase timing breakdown",
        "",
        "| Phase | Reported total | End-to-end | Restore | Proxy ready | Build | Unattributed |",
        "|---|---|---|---|---|---|---|",
    ]
    for phase in sorted(phases, key=phase_sort_key):
        payload = phases[phase]
        lines.append(
            "| {phase} | {reported} | {end_to_end} | {restore} | {proxy} | {build} | {unattributed} |".format(
                phase=phase,
                reported=render_cell(payload["reported_seconds"]),
                end_to_end=render_cell(payload["end_to_end_seconds"]),
                restore=render_cell(payload["restore_seconds"]),
                proxy=render_cell(payload["proxy_ready_seconds"]),
                build=render_cell(payload["build_seconds"]),
                unattributed=render_cell(payload["unattributed_seconds"]),
            )
        )
    md_path.write_text("\n".join(lines) + "\n")

    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a", encoding="utf-8") as handle:
            handle.write(f"json_path={json_path}\n")
            handle.write(f"md_path={md_path}\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
