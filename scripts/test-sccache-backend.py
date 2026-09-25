#!/usr/bin/env python3
"""Exercise the setup and evidence checks with sccache backend descriptions."""

import contextlib
import io
import json
import runpy
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
PROJECT = "zed"
CASES = (
    ("s3, name: benchmark-cache, prefix: /cache/sccache/run/", True),
    ("S3, name: benchmark-cache, prefix: /cache/sccache/run/", True),
    ("Local disk: /tmp/S3/sccache", False),
    ("WebDAV, url: https://cache.example/s3", False),
    (None, False),
    (123, False),
)


class SccacheBackendTest(unittest.TestCase):
    def test_workflow_checks_the_backend_name(self):
        workflow = (ROOT / f".github/workflows/{PROJECT}-runs-on-phase.yml").read_text()
        step = workflow.split("- name: Scope RunsOn direct S3 compiler cache", 1)[1]
        source = textwrap.dedent(step.split("python3 - <<'PY'\n", 1)[1].split("          PY", 1)[0])
        for location, accepted in CASES:
            with self.subTest(location=location), patch("subprocess.check_output", return_value=json.dumps({"cache_location": location}).encode()), contextlib.redirect_stdout(io.StringIO()):
                if accepted:
                    exec(compile(source, "workflow-sccache-check", "exec"), {})  # noqa: S102 - repository workflow code
                else:
                    with self.assertRaises(SystemExit):
                        exec(compile(source, "workflow-sccache-check", "exec"), {})  # noqa: S102 - repository workflow code

    def test_evidence_accepts_s3_and_rejects_other_backends(self):
        script = ROOT / f"scripts/collect-{PROJECT}-cache-evidence.py"
        collector = runpy.run_path(str(script))
        for location, accepted in CASES:
            with self.subTest(location=location), tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / "evidence.json"
                argv = [str(script), "--provider", "runs-on-cache", "--cache-variant", "sccache-only", "--output", str(output)]
                with patch("sys.argv", argv), patch.dict(collector["main"].__globals__, read_json=lambda _, location=location: {"cache_location": location, "stats": {}}), contextlib.redirect_stdout(io.StringIO()):
                    if accepted:
                        collector["main"]()
                        evidence = json.loads(output.read_text())
                        self.assertEqual(evidence["compiler_backend"], location)
                        self.assertIsNone(evidence["target_restore_hit"])
                    else:
                        with self.assertRaises(ValueError):
                            collector["main"]()
                        self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
