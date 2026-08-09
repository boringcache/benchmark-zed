#!/usr/bin/env python3
"""Point the committed BoringCache Cargo plan at one of Zed's release phases.

Zed's `script/bundle-linux` compiles the Linux release in two separate Cargo
invocations. The benchmark runs the same two invocations through the Cargo
product, so the plan is rewritten between phases instead of being duplicated.
"""
from __future__ import annotations

import json
import re
import shlex
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

PHASES = ("primary", "remote-server")


def read_settings(path: Path) -> dict[str, str]:
    settings: dict[str, str] = {}
    for number, raw_line in enumerate(path.read_text().splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"Invalid setting at {path}:{number}: {raw_line}")
        key, raw_value = line.split("=", 1)
        if not raw_value:
            settings[key] = ""
            continue
        values = shlex.split(raw_value)
        if len(values) != 1:
            raise ValueError(f"Expected one value for {key} at {path}:{number}")
        settings[key] = values[0]
    return settings


def cargo_command(settings: dict[str, str], phase: str) -> list[str]:
    """Return Zed's exact Cargo invocation for the requested release phase."""
    if phase == "primary":
        return [
            "cargo",
            "build",
            "--release",
            "--target",
            settings["ZED_HOST_TARGET"],
            "--package",
            settings["ZED_PRIMARY_PACKAGE"],
            "--package",
            settings["ZED_PRIMARY_COMPANION_PACKAGE"],
        ]
    if phase == "remote-server":
        return [
            "cargo",
            "build",
            "--release",
            "--target",
            settings["ZED_REMOTE_SERVER_TARGET"],
            "--package",
            settings["ZED_REMOTE_SERVER_PACKAGE"],
        ]
    raise ValueError(f"Unknown Zed Cargo phase: {phase}")


def render_command(command: list[str]) -> str:
    lines = ["command = ["]
    for value in command:
        lines.append(f"  {json.dumps(value)},")
    lines.append("]")
    return "\n".join(lines)


def replace_command(config_path: Path, command: list[str]) -> None:
    original = config_path.read_text()
    updated, replacements = re.subn(
        r"^command\s*=\s*\[.*?^\]$",
        render_command(command),
        original,
        count=1,
        flags=re.MULTILINE | re.DOTALL,
    )
    if replacements != 1:
        raise ValueError(f"Expected one Cargo command in {config_path}")
    config_path.write_text(updated)


def main() -> int:
    argv = sys.argv[1:]
    # --print emits the invocation instead of rewriting the plan, so the
    # actions/cache control lane builds from this same contract rather than
    # keeping its own copy of Zed's commands.
    printing = "--print" in argv
    if printing:
        argv.remove("--print")
    if len(argv) not in (1, 2):
        print(
            f"Usage: select-zed-cargo-phase.py {'|'.join(PHASES)} "
            "[--print] [.boringcache.toml]",
            file=sys.stderr,
        )
        return 2
    config_path = Path(argv[1]) if len(argv) == 2 else ROOT / ".boringcache.toml"
    try:
        settings = read_settings(ROOT / "scripts/zed-release-recipe.env")
        command = cargo_command(settings, argv[0])
        if printing:
            print(shlex.join(command))
            return 0
        replace_command(config_path, command)
    except (KeyError, OSError, ValueError) as error:
        print(f"Unable to select Zed Cargo phase: {error}", file=sys.stderr)
        return 1
    print(f"Selected Zed's {argv[0]} Linux release Cargo command.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
