#!/usr/bin/env python3
"""Fail the benchmark when it stops building what Zed's release job builds.

Zed compiles its Linux release inside `script/bundle-linux`, not in workflow
YAML, so this gate reads that script directly. It asserts three things:

  1. Upstream still uses the two Cargo invocations and RUSTFLAGS we mirror.
  2. The committed BoringCache plan matches upstream's first invocation.
  3. The phase selector reproduces both invocations exactly.

Without this the benchmark can silently drift into measuring a different build
than Zed's, which is exactly what happened with the unscoped
`cargo build --release` this replaces.
"""
from __future__ import annotations

import importlib.util
import re
import shlex
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class RecipeMismatch(RuntimeError):
    pass


def load_phase_selector():
    path = ROOT / "scripts/select-zed-cargo-phase.py"
    spec = importlib.util.spec_from_file_location("select_zed_cargo_phase", path)
    if not spec or not spec.loader:
        raise RecipeMismatch(f"Unable to load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_settings(path: Path) -> dict[str, str]:
    settings: dict[str, str] = {}
    for number, raw_line in enumerate(path.read_text().splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise RecipeMismatch(f"Invalid setting at {path}:{number}: {raw_line}")
        key, raw_value = line.split("=", 1)
        if not raw_value:
            settings[key] = ""
            continue
        values = shlex.split(raw_value)
        if len(values) != 1:
            raise RecipeMismatch(f"Expected one value for {key} at {path}:{number}")
        settings[key] = values[0]
    return settings


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RecipeMismatch(message)


def verify(upstream: Path) -> str:
    contract = read_settings(ROOT / "scripts/zed-release-recipe.env")
    benchmark_source = read_settings(ROOT / "benchmark-source.env")

    toolchain_path = upstream / "rust-toolchain.toml"
    bundle_path = upstream / contract["ZED_UPSTREAM_RELEASE_SCRIPT"]
    require(toolchain_path.is_file(), f"Missing {toolchain_path}")
    require(bundle_path.is_file(), f"Missing {bundle_path}")

    channel_match = re.search(
        r'^channel = "([^"]+)"$', toolchain_path.read_text(), re.MULTILINE
    )
    require(channel_match is not None, "Missing channel in upstream/rust-toolchain.toml")
    require(
        channel_match.group(1) == benchmark_source["ZED_RUST_VERSION"],
        "ZED_RUST_VERSION no longer matches upstream/rust-toolchain.toml",
    )

    bundle = bundle_path.read_text()

    # Zed derives both triples from rustc's host, so the benchmark's pinned
    # x86_64 triples are only correct while this derivation holds.
    for fragment in (
        "target_triple=${host_line#*: }",
        "musl_triple=${target_triple%-gnu}-musl",
        'remote_server_triple=${REMOTE_SERVER_TARGET:-"${musl_triple}"}',
    ):
        require(
            fragment in bundle,
            f"Zed's bundle-linux changed how it derives target triples: {fragment}",
        )
    require(
        contract["ZED_HOST_TARGET"].endswith("-unknown-linux-gnu"),
        "ZED_HOST_TARGET must be a -gnu triple to match Zed's host derivation",
    )
    require(
        contract["ZED_REMOTE_SERVER_TARGET"]
        == contract["ZED_HOST_TARGET"].removesuffix("-gnu") + "-musl",
        "ZED_REMOTE_SERVER_TARGET must be the musl sibling of ZED_HOST_TARGET",
    )

    for fragment in ("export ZED_BUNDLE=true", "export CC=${CC:-$(which clang)}"):
        require(fragment in bundle, f"Zed's bundle-linux no longer sets: {fragment}")

    base_flags = contract["ZED_BASE_RUSTFLAGS"].replace("$ORIGIN", r"\$ORIGIN")
    require(
        f'export RUSTFLAGS="${{RUSTFLAGS:-}} {base_flags}"' in bundle,
        "Zed's x86_64 release RUSTFLAGS changed; resync zed-release-recipe.env",
    )
    require(
        f'export RUSTFLAGS="${{RUSTFLAGS:-}} {contract["ZED_MUSL_RUSTFLAGS"]}"'
        in bundle,
        "Zed's musl remote_server RUSTFLAGS changed; resync zed-release-recipe.env",
    )
    require(
        f'export "$musl_cc_var"={contract["ZED_MUSL_CC"]}' in bundle,
        f"Zed's musl remote_server no longer uses {contract['ZED_MUSL_CC']}",
    )

    expected_builds = [
        'cargo build --release --target "${target_triple}" '
        f'--package {contract["ZED_PRIMARY_PACKAGE"]} '
        f'--package {contract["ZED_PRIMARY_COMPANION_PACKAGE"]}',
        'cargo build --release --target "${remote_server_triple}" '
        f'--package {contract["ZED_REMOTE_SERVER_PACKAGE"]}',
    ]
    actual_builds = [
        line.strip()
        for line in bundle.splitlines()
        if line.strip().startswith("cargo build ")
    ]
    require(
        actual_builds == expected_builds,
        "Zed's Linux release build commands changed; resync "
        "zed-release-recipe.env and .boringcache.toml",
    )

    phase_selector = load_phase_selector()
    expected_primary = phase_selector.cargo_command(contract, "primary")
    expected_remote = phase_selector.cargo_command(contract, "remote-server")

    # The selector must reproduce upstream once the shell variables resolve.
    resolved_primary = expected_builds[0].replace(
        '"${target_triple}"', contract["ZED_HOST_TARGET"]
    )
    resolved_remote = expected_builds[1].replace(
        '"${remote_server_triple}"', contract["ZED_REMOTE_SERVER_TARGET"]
    )
    require(
        expected_primary == shlex.split(resolved_primary),
        "The primary Cargo phase selector no longer matches Zed's release script",
    )
    require(
        expected_remote == shlex.split(resolved_remote),
        "The remote_server Cargo phase selector no longer matches Zed's release script",
    )

    command_match = re.search(
        r"^command\s*=\s*\[(?P<body>.*?)^\]$",
        (ROOT / ".boringcache.toml").read_text(),
        re.MULTILINE | re.DOTALL,
    )
    require(command_match is not None, "Missing BoringCache Cargo command")
    require(
        re.findall(r'"([^"]*)"', command_match.group("body")) == expected_primary,
        "The committed BoringCache Cargo plan no longer matches Zed's first "
        "Linux release command; resync .boringcache.toml",
    )

    for relative_path in (
        ".github/workflows/zed-cargo-product.yml",
        ".github/workflows/zed-cargo-rolling-chain.yml",
    ):
        workflow = (ROOT / relative_path).read_text()
        for fragment in (
            "./scripts/verify-zed-release-recipe.py",
            "./scripts/select-zed-cargo-phase.py remote-server",
            'ZED_BUNDLE: "true"',
            f'RUSTFLAGS: {contract["ZED_BASE_RUSTFLAGS"]}',
            contract["ZED_MUSL_RUSTFLAGS"],
            f'CC_{contract["ZED_REMOTE_SERVER_TARGET"].replace("-", "_")}: '
            f'{contract["ZED_MUSL_CC"]}',
        ):
            require(
                fragment in workflow,
                f"{relative_path} must carry Zed's release recipe: {fragment}",
            )

    return benchmark_source["ZED_HEAD_SHA"]


def main() -> int:
    upstream = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "upstream"
    try:
        source_sha = verify(upstream.resolve())
    except (KeyError, RecipeMismatch) as error:
        print(f"Zed release recipe mismatch: {error}", file=sys.stderr)
        return 1

    print(f"Verified Zed Linux release recipe at {source_sha}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
