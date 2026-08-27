import json
import os
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
LANES = {
    "cold": ("sccache", True),
    "target-only": ("none", True),
    "sccache-only": ("sccache", False),
    "combined": ("sccache", True),
}


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

            output = root / "github-output"
            subprocess.run(
                [str(ROOT / "scripts/advance-source-pair.sh"), str(source), "ZED"],
                check=True,
                env={
                    **os.environ,
                    "PATH": f"{bin_dir}:{os.environ['PATH']}",
                    "GITHUB_OUTPUT": str(output),
                },
            )
            settings = dict(line.split("=", 1) for line in source.read_text().splitlines())
            outputs = dict(line.split("=", 1) for line in output.read_text().splitlines())

        self.assertEqual(settings["ZED_BASE_SHA"], current)
        self.assertEqual(settings["ZED_HEAD_SHA"], following)
        self.assertEqual(outputs["updated"], "true")
        self.assertEqual(outputs["base_sha"], current)
        self.assertEqual(outputs["head_sha"], following)

    def test_rolling_workflow_advances_main_only_after_the_benchmark(self):
        sync = (WORKFLOWS / "sync.yml").read_text()
        rolling = (WORKFLOWS / "zed-cargo-rolling-chain.yml").read_text()
        manual = (WORKFLOWS / "zed-cargo-rolling-manual.yml").read_text()

        self.assertIn("group: benchmark-zed-cargo-rolling-chain", sync)
        self.assertIn("group: benchmark-zed-cargo-rolling-chain", manual)
        self.assertIn("uses: ./.github/workflows/zed-cargo-rolling-chain.yml", sync)
        self.assertIn("needs: [source, benchmark]", sync)
        self.assertIn("needs.benchmark.result == 'success'", sync)
        self.assertNotIn("gh workflow run", sync)
        self.assertIn("workflow_call:", rolling)
        self.assertNotIn("workflow_dispatch:", rolling)
        self.assertNotIn("push:", rolling)
        self.assertIn('test "$INPUT_BASE_SHA" = "$ZED_HEAD_SHA"', rolling)

class CargoLayerPlanTest(unittest.TestCase):
    def test_each_layer_choice_is_a_committed_cli_plan(self):
        target_tags = set()
        compiler_tags = set()

        for lane, (compiler, includes_target) in LANES.items():
            for phase in ("primary", "remote-server"):
                path = ROOT / "plans" / lane / phase / ".boringcache.toml"
                plan = tomllib.loads(path.read_text())
                profile = plan["profiles"]["cargo-product"]["entries"]
                cargo = plan["adapters"]["cargo"]

                self.assertEqual(cargo["compiler-cache"], compiler)
                self.assertEqual("zed-target" in profile, includes_target)
                self.assertEqual(cargo["profiles"], ["cargo-product"])
                self.assertNotIn("--manifest-path", cargo["command"])
                target_tags.add(plan["entries"]["zed-target"]["tag"])

                if compiler == "sccache":
                    self.assertIn("sccache", plan["adapters"])
                    compiler_tags.add(plan["adapters"]["sccache"]["tag"])
                else:
                    self.assertNotIn("sccache", plan["adapters"])

        self.assertEqual(len(target_tags), 1)
        self.assertEqual(len(compiler_tags), 1)

    def test_action_selects_plans_but_does_not_plan_layers(self):
        matrix = (WORKFLOWS / "zed-cargo-product.yml").read_text()
        rolling = (WORKFLOWS / "zed-cargo-rolling-chain.yml").read_text()
        workflow_text = matrix + rolling

        self.assertNotIn("scope-boringcache-run", workflow_text)
        self.assertNotIn("mode: sccache", workflow_text)
        self.assertNotIn("sed -i", workflow_text)
        self.assertNotIn("fail-on-cache-miss", matrix)
        self.assertNotIn("cache_scope:", rolling)
        self.assertEqual(matrix.count("mode: cargo"), 8)
        self.assertIn("inputs.cli_version", matrix)
        self.assertIn("Action default", matrix)

        for lane in LANES:
            for phase in ("primary", "remote-server"):
                self.assertIn(
                    f"activate-cargo-plan.sh {lane} {phase}",
                    matrix,
                )
        self.assertEqual(matrix.count("working-directory: upstream"), 8)

    def test_rolling_plan_owns_its_stable_compiler_identity(self):
        plan = tomllib.loads((ROOT / ".boringcache.toml").read_text())

        self.assertEqual(plan["adapters"]["cargo"]["compiler-cache"], "sccache")
        self.assertIn("sccache", plan["adapters"])
        self.assertEqual(
            plan["adapters"]["sccache"]["tag"],
            "zed-cargo-rolling-main-sccache",
        )
        self.assertEqual(
            plan["entries"]["zed-target"]["tag"],
            "zed-cargo-rolling-main-target-v2",
        )
        self.assertEqual(
            plan["adapters"]["cargo"]["command"],
            [
                "cargo",
                "build",
                "--release",
                "--locked",
                "--message-format=json-render-diagnostics",
            ],
        )

    def test_source_pair_matches_the_pinned_submodule(self):
        source = dict(
            line.split("=", 1)
            for line in (ROOT / "benchmark-source.env").read_text().splitlines()
        )
        head = subprocess.run(
            ["git", "-C", "upstream", "rev-parse", "HEAD"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

        self.assertEqual(source["ZED_HEAD_SHA"], head)

    def test_layer_matrix_owns_a_fixed_source_cohort(self):
        source = dict(
            line.split("=", 1)
            for line in (ROOT / "cargo-layer-source.env").read_text().splitlines()
        )
        cohort = source["ZED_HEAD_SHA"][:7]
        matrix = (WORKFLOWS / "zed-cargo-product.yml").read_text()

        self.assertNotEqual(source["ZED_BASE_SHA"], source["ZED_HEAD_SHA"])
        self.assertIn("source cargo-layer-source.env", matrix)
        self.assertNotIn("source benchmark-source.env", matrix)
        for path in sorted((ROOT / "plans").glob("*/*/.boringcache.toml")):
            plan = tomllib.loads(path.read_text())
            for entry in plan["entries"].values():
                self.assertIn(cohort, entry["tag"])
            sccache = plan["adapters"].get("sccache")
            if sccache:
                self.assertIn(cohort, sccache["tag"])

    def test_release_recipe_and_layer_contract(self):
        subprocess.run(
            [sys.executable, str(ROOT / "scripts/verify-zed-release-recipe.py"), "upstream"],
            cwd=ROOT,
            check=True,
        )

    def test_native_hit_rate_is_already_a_percentage(self):
        evidence = {
            "phases": {
                "restore": {
                    "mode_evidence": {
                        "elapsed_seconds": 12.4,
                        "target_cache_hit": True,
                        "native_tool": {
                            "compile_requests": 101,
                            "compile_requests_executed": 100,
                            "cache_hits": 96,
                            "cache_misses": 4,
                            "hit_rate": 96.0,
                        },
                    }
                }
            }
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "evidence.json"
            path.write_text(json.dumps(evidence))
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/summarize-cargo-evidence.py"),
                    "combined",
                    str(path),
                ],
                check=True,
                text=True,
                capture_output=True,
            )

        self.assertIn("96.0% hit rate", result.stdout)
        self.assertNotIn("9600", result.stdout)

    def test_report_handles_a_disabled_compiler_cache(self):
        evidence = {
            "phases": {
                "restore": {
                    "mode_evidence": {
                        "elapsed_seconds": 12.4,
                        "target_cache_hit": True,
                        "native_tool": None,
                        "cargo_cache": {"compiler_cache": "none"},
                    }
                }
            }
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "evidence.json"
            path.write_text(json.dumps(evidence))
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/summarize-cargo-evidence.py"),
                    "target-only",
                    str(path),
                ],
                check=True,
                text=True,
                capture_output=True,
            )

        self.assertIn("target snapshot restored: `True`", result.stdout)
        self.assertIn("compiler cache: disabled", result.stdout)


if __name__ == "__main__":
    unittest.main()
