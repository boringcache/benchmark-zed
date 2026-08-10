import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"


class SourceSyncTest(unittest.TestCase):
    def test_advances_exactly_one_upstream_commit(self):
        current = "a" * 40
        following = "b" * 40
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "benchmark-source.env"
            source.write_text(
                "ZED_SOURCE_REPOSITORY=zed-industries/zed\n"
                f"ZED_BASE_SHA={'0' * 40}\n"
                f"ZED_HEAD_SHA={current}\n"
            )
            bin_dir = root / "bin"
            bin_dir.mkdir()
            gh = bin_dir / "gh"
            gh.write_text(
                "#!/usr/bin/env bash\n"
                "case \"$*\" in\n"
                "  'api repos/zed-industries/zed --jq .default_branch') echo main ;;\n"
                f"  'api repos/zed-industries/zed/compare/{current}...main') "
                f"echo '{{\"status\":\"ahead\",\"commits\":[{{\"sha\":\"{following}\"}}]}}' ;;\n"
                f"  'api repos/zed-industries/zed/commits/{following} --jq .parents[0].sha // empty') echo {current} ;;\n"
                "  *) echo \"Unexpected gh call: $*\" >&2; exit 1 ;;\n"
                "esac\n"
            )
            gh.chmod(0o755)

            subprocess.run(
                [str(ROOT / "scripts/advance-source-pair.sh"), str(source), "ZED"],
                check=True,
                env={**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"},
            )
            settings = dict(line.split("=", 1) for line in source.read_text().splitlines())

        self.assertEqual(settings["ZED_BASE_SHA"], current)
        self.assertEqual(settings["ZED_HEAD_SHA"], following)


class CargoProductWorkflowTest(unittest.TestCase):
    def test_workflows_use_zeds_checked_in_rust_toolchain(self):
        workflow_text = "\n".join(
            (WORKFLOWS / name).read_text()
            for name in ["zed-cargo-product.yml", "zed-cargo-rolling-chain.yml"]
        )
        source = (ROOT / "benchmark-source.env").read_text()

        self.assertEqual(workflow_text.count("rustup show active-toolchain"), 3)
        self.assertNotIn("rustup toolchain install", workflow_text)
        self.assertNotIn("ZED_RUST_VERSION", source + workflow_text)

    def test_cargo_is_the_only_live_boringcache_rust_lifecycle(self):
        workflow_text = "\n".join(
            path.read_text() for path in sorted(WORKFLOWS.glob("*.yml"))
        )
        config = (ROOT / ".boringcache.toml").read_text()

        self.assertIn("[adapters.cargo]", config)
        self.assertNotIn("[adapters.sccache]", config)
        self.assertNotIn("mode: sccache", workflow_text)
        self.assertNotIn("uses: boringcache/one@", workflow_text)

    def test_weekly_fresh_workflow_owns_publish_and_consume(self):
        workflow = (WORKFLOWS / "zed-cargo-product.yml").read_text()

        self.assertNotIn("push:", workflow)
        self.assertNotIn("pull_request:", workflow)
        self.assertNotIn("workflow_dispatch:", workflow)
        self.assertIn("workflow_call:", workflow)
        self.assertIn("schedule:", workflow)
        self.assertIn('cron: "0 4 * * 5"', workflow)
        self.assertEqual(workflow.count("boringcache cargo \\"), 2)
        self.assertIn("--write", workflow)
        self.assertIn("--read-only", workflow)
        self.assertIn("cargo-freshness-v2.json", workflow)
        self.assertIn("--native-tool-evidence-json", workflow)

    def test_source_updates_run_the_persistent_rolling_chain(self):
        dispatcher = (WORKFLOWS / "zed-rust-cache-proof.yml").read_text()
        rolling = (WORKFLOWS / "zed-cargo-rolling-chain.yml").read_text()
        sync = (WORKFLOWS / "sync.yml").read_text()
        source = (ROOT / "benchmark-source.env").read_text()

        self.assertIn('- "benchmark-source.env"', dispatcher)
        self.assertIn("uses: ./.github/workflows/zed-cargo-rolling-chain.yml", dispatcher)
        self.assertNotIn("zed-cargo-product.yml", dispatcher)
        self.assertIn("ZED_ROLLING_CACHE_SCOPE=", source)
        self.assertIn('cron: "*/30 * * * *"', sync)
        self.assertIn("advance-source-pair.sh benchmark-source.env ZED", sync)
        self.assertIn("Require the previous rolling benchmark to be green", sync)
        self.assertIn("steps.previous.outputs.ready == 'true'", sync)
        self.assertIn("git add benchmark-source.env upstream", sync)
        self.assertIn("group: benchmark-zed-cargo-rolling-chain", rolling)

        settings = dict(line.split("=", 1) for line in source.splitlines())
        gitlink = subprocess.run(
            ["git", "ls-files", "-s", "upstream"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.split()[1]
        self.assertEqual(settings["ZED_HEAD_SHA"], gitlink)

    def test_canary_defaults_to_the_cargo_product(self):
        workflow = (WORKFLOWS / "canary-dispatch.yml").read_text()

        self.assertIn("uses: ./.github/workflows/zed-cargo-product.yml", workflow)
        self.assertNotIn("zed-sccache", workflow)


if __name__ == "__main__":
    unittest.main()
