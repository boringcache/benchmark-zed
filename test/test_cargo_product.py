from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"


class CargoProductWorkflowTest(unittest.TestCase):
    def test_cargo_is_the_only_live_boringcache_rust_lifecycle(self):
        workflow_text = "\n".join(
            path.read_text() for path in sorted(WORKFLOWS.glob("*.yml"))
        )
        config = (ROOT / ".boringcache.toml").read_text()

        self.assertIn("[adapters.cargo]", config)
        self.assertNotIn("[adapters.sccache]", config)
        self.assertNotIn("mode: sccache", workflow_text)
        self.assertNotIn("uses: boringcache/one@", workflow_text)

    def test_primary_workflow_owns_publish_and_consume(self):
        workflow = (WORKFLOWS / "zed-cargo-product.yml").read_text()

        self.assertIn("push:", workflow)
        self.assertIn("pull_request:", workflow)
        self.assertIn("schedule:", workflow)
        self.assertIn("workflow_dispatch:", workflow)
        self.assertEqual(workflow.count("boringcache cargo \\"), 2)
        self.assertIn("--write", workflow)
        self.assertIn("--read-only", workflow)
        self.assertIn("cargo-freshness-v2.json", workflow)
        self.assertIn("--native-tool-evidence-json", workflow)

    def test_canary_defaults_to_the_cargo_product(self):
        workflow = (WORKFLOWS / "canary-dispatch.yml").read_text()

        self.assertIn("uses: ./.github/workflows/zed-cargo-product.yml", workflow)
        self.assertNotIn("zed-sccache", workflow)


if __name__ == "__main__":
    unittest.main()
