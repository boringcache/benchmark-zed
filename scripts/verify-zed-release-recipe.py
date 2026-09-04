#!/usr/bin/env python3
"""Verify that every committed Cargo layer plan matches Zed's Linux release."""

from __future__ import annotations

import re
import shlex
import sys
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LANES = {
    "cold": {"target": True, "compiler": "sccache"},
    "target-only": {"target": True, "compiler": "none"},
    "sccache-only": {"target": False, "compiler": "sccache"},
    "combined": {"target": True, "compiler": "sccache"},
}
PHASES = {
    "primary": ("x86_64-unknown-linux-gnu", ("zed", "cli")),
    "remote-server": ("x86_64-unknown-linux-musl", ("remote_server",)),
}


class RecipeMismatch(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RecipeMismatch(message)


def read_settings(path: Path) -> dict[str, str]:
    settings: dict[str, str] = {}
    for number, raw_line in enumerate(path.read_text().splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        require("=" in line, f"Invalid setting at {path}:{number}")
        key, raw_value = line.split("=", 1)
        values = shlex.split(raw_value)
        require(len(values) == 1, f"Expected one value for {key} at {path}:{number}")
        settings[key] = values[0]
    return settings


def expected_command(phase: str) -> list[str]:
    target, packages = PHASES[phase]
    command = [
        "cargo",
        "--config",
        ".cargo/bundle-config.toml",
        "build",
        "--release",
        "--target",
        target,
    ]
    for package in packages:
        command.extend(("--package", package))
    return command


def verify_upstream(upstream: Path, contract: dict[str, str]) -> None:
    toolchain_path = upstream / "rust-toolchain.toml"
    bundle_path = upstream / contract["ZED_UPSTREAM_RELEASE_SCRIPT"]
    require(toolchain_path.is_file(), f"Missing {toolchain_path}")
    require(bundle_path.is_file(), f"Missing {bundle_path}")

    channel_match = re.search(
        r'^channel = "([^"]+)"$', toolchain_path.read_text(), re.MULTILINE
    )
    require(channel_match is not None, "Missing channel in upstream/rust-toolchain.toml")

    bundle = bundle_path.read_text()
    for fragment in (
        "target_triple=${host_line#*: }",
        "musl_triple=${target_triple%-gnu}-musl",
        'remote_server_triple=${REMOTE_SERVER_TARGET:-"${musl_triple}"}',
        "export ZED_BUNDLE=true",
        "export CC=${CC:-$(which clang)}",
    ):
        require(fragment in bundle, f"Zed's bundle-linux changed: {fragment}")

    base_flags = contract["ZED_BASE_RUSTFLAGS"].replace("$ORIGIN", r"\$ORIGIN")
    require(
        f'export RUSTFLAGS="${{RUSTFLAGS:-}} {base_flags}"' in bundle,
        "Zed's primary release RUSTFLAGS changed",
    )
    require(
        f'export RUSTFLAGS="${{RUSTFLAGS:-}} {contract["ZED_MUSL_RUSTFLAGS"]}"'
        in bundle,
        "Zed's remote-server RUSTFLAGS changed",
    )
    require(
        f'export "$musl_cc_var"={contract["ZED_MUSL_CC"]}' in bundle,
        "Zed's remote-server compiler changed",
    )

    expected_builds = [
        'cargo --config .cargo/bundle-config.toml build --release --target "${target_triple}" '
        f'--package {contract["ZED_PRIMARY_PACKAGE"]} '
        f'--package {contract["ZED_PRIMARY_COMPANION_PACKAGE"]}',
        'cargo --config .cargo/bundle-config.toml build --release --target "${remote_server_triple}" '
        f'--package {contract["ZED_REMOTE_SERVER_PACKAGE"]}',
    ]
    actual_builds = [
        line.strip()
        for line in bundle.splitlines()
        if line.strip().startswith("cargo ") and " build " in line
    ]
    require(
        actual_builds == expected_builds,
        "Zed's Linux release commands changed; update the committed plans",
    )


def verify_plans() -> None:
    source = read_settings(ROOT / "cargo-layer-source.env")
    cohort = source["ZED_HEAD_SHA"][:7]
    target_tags: set[str] = set()
    compiler_tags: set[str] = set()
    dependency_tag_pairs: set[tuple[str, str]] = set()

    for lane, expected in LANES.items():
        for phase in PHASES:
            path = ROOT / "plans" / lane / phase / ".boringcache.toml"
            require(path.is_file(), f"Missing {path}")
            plan = tomllib.loads(path.read_text())
            entries = plan["profiles"]["cargo-product"]["entries"]
            cargo = plan["adapters"]["cargo"]

            require(
                cargo["compiler-cache"] == expected["compiler"],
                f"{path} has the wrong compiler-cache selector",
            )
            require(
                ("zed-target" in entries) is expected["target"],
                f"{path} has the wrong target-layer selector",
            )
            require(
                cargo["command"] == expected_command(phase),
                f"{path} does not match Zed's {phase} release command",
            )
            require(cargo["no-git"] is True, f"{path} must use stable reviewed tags")

            config_entries = plan["entries"]
            for entry in config_entries.values():
                require(
                    cohort in entry["tag"],
                    f"{path} does not carry the pinned layer-source identity",
                )
            target_tags.add(config_entries["zed-target"]["tag"])
            dependency_tag_pairs.add(
                (
                    config_entries["cargo-registry"]["tag"],
                    config_entries["cargo-git"]["tag"],
                )
            )
            if expected["compiler"] == "sccache":
                require(
                    "sccache" in plan["adapters"],
                    f"{path} must give sccache an independent identity",
                )
                compiler_tags.add(plan["adapters"]["sccache"]["tag"])
                require(
                    cohort in plan["adapters"]["sccache"]["tag"],
                    f"{path} compiler tag does not carry the pinned layer-source identity",
                )
            else:
                require(
                    "sccache" not in plan["adapters"],
                    f"{path} must not configure a disabled compiler layer",
                )

    require(len(target_tags) == 1, "Every target-bearing lane must share one seed tag")
    require(len(compiler_tags) == 1, "Every sccache lane must share one seed tag")
    require(
        len(dependency_tag_pairs) == 1,
        "Every lane must hold Cargo dependency transport constant",
    )


def verify_workflows() -> None:
    matrix_path = ROOT / ".github/workflows/zed-cargo-product.yml"
    rolling_path = ROOT / ".github/workflows/zed-cargo-rolling-chain.yml"
    matrix = matrix_path.read_text()
    rolling = rolling_path.read_text()
    all_workflows = matrix + rolling

    require("scope-boringcache-run" not in all_workflows, "Workflows must not rewrite tags")
    require("mode: sccache" not in all_workflows, "Cargo owns the composed lifecycle")
    require(
        "source cargo-layer-source.env" in matrix,
        "The layer matrix must not follow the moving rolling source",
    )
    stable_action = "boringcache/one@c62af42c5c1e29388ceeea77b6a7f1db51f641e7"
    require(
        all_workflows.count(stable_action) == 9,
        "Every Cargo lane must use released One 1.20.1",
    )
    require(
        all_workflows.count("CXX: clang++") == 2,
        "Every Zed release workflow must select clang++ for C++ dependencies",
    )
    for lane in LANES:
        for phase in PHASES:
            require(
                f"activate-cargo-plan.sh {lane} {phase}" in matrix,
                f"The matrix does not select plans/{lane}/{phase}",
            )
    require(
        matrix.count("working-directory: upstream") == 8,
        "Every matrix phase must run Cargo from the upstream Git checkout",
    )
    require(
        matrix.count("mode: cargo") == 8,
        "The four lanes must each run both Cargo release phases",
    )

    root_plan = tomllib.loads((ROOT / ".boringcache.toml").read_text())
    require(
        root_plan["adapters"]["cargo"]["compiler-cache"] == "sccache",
        "The rolling Cargo plan must select its compiler layer explicitly",
    )
    require(
        "sccache" in root_plan["adapters"],
        "The rolling plan must give sccache an independent identity",
    )
    require(
        root_plan["adapters"]["cargo"]["command"][0] == "cargo",
        "The rolling Cargo plan must execute Cargo directly",
    )


def verify(upstream: Path) -> str:
    contract = read_settings(ROOT / "scripts/zed-release-recipe.env")
    source = read_settings(ROOT / "cargo-layer-source.env")
    verify_upstream(upstream, contract)
    verify_plans()
    verify_workflows()
    return source["ZED_HEAD_SHA"]


def main() -> int:
    upstream = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "upstream"
    try:
        source_sha = verify(upstream.resolve())
    except (KeyError, OSError, RecipeMismatch, tomllib.TOMLDecodeError) as error:
        print(f"Zed release recipe mismatch: {error}", file=sys.stderr)
        return 1

    print(f"Verified Zed Cargo layer plans at {source_sha}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
