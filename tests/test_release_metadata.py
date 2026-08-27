from __future__ import annotations

import importlib.metadata
import json
import os
import subprocess
import sys
import tomllib
import unittest
from pathlib import Path

from model_harness import __version__


ROOT = Path(__file__).resolve().parents[1]


class ReleaseMetadataTests(unittest.TestCase):
    def test_package_disables_onnx_telemetry_unless_operator_overrides_it(self) -> None:
        environment = dict(os.environ)
        environment.pop("ORT_DISABLE_TELEMETRY", None)
        disabled = subprocess.run(
            [
                sys.executable,
                "-c",
                "import os, model_harness; print(os.environ['ORT_DISABLE_TELEMETRY'])",
            ],
            cwd=ROOT,
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10,
            check=False,
        )
        self.assertEqual(disabled.returncode, 0, disabled.stderr)
        self.assertEqual(disabled.stdout.strip(), "1")

        environment["ORT_DISABLE_TELEMETRY"] = "0"
        overridden = subprocess.run(
            [
                sys.executable,
                "-c",
                "import os, model_harness; print(os.environ['ORT_DISABLE_TELEMETRY'])",
            ],
            cwd=ROOT,
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10,
            check=False,
        )
        self.assertEqual(overridden.returncode, 0, overridden.stderr)
        self.assertEqual(overridden.stdout.strip(), "0")

    def test_package_cli_and_runtime_versions_have_one_source_of_truth(self) -> None:
        metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        project = metadata["project"]

        self.assertEqual(project["version"], "1.0.0rc1")
        self.assertEqual(__version__, project["version"])
        self.assertEqual(
            importlib.metadata.version("specialist-model-studio"),
            project["version"],
        )
        self.assertEqual(
            project["scripts"]["specialist-model-studio"],
            "model_harness.cli:main",
        )
        self.assertEqual(
            project["scripts"]["small-model-harness"],
            "model_harness.cli:main",
        )

    def test_readme_describes_the_unreleased_source_rc_and_product_start(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")

        self.assertIn("`v1.0-conversation-native`", readme)
        self.assertIn("`unreleased_rc`", readme)
        self.assertIn("uv run specialist-model-studio start", readme)
        self.assertIn("uv run specialist-model-studio serve", readme)
        self.assertIn("agent_required` 为 `false", readme)
        self.assertIn("只允许静态分析", readme)
        self.assertIn("源码 RC", readme)
        self.assertIn("wheel", readme)
        self.assertIn("不表示生产就绪", readme)

    def test_v10_gate_contract_separates_source_rc_from_public_release(self) -> None:
        gates = json.loads(
            (ROOT / "acceptance" / "v1.0-gates.json").read_text(encoding="utf-8")
        )

        self.assertEqual(gates["expected_package_version"], "1.0.0rc1")
        self.assertEqual(gates["expected_api_version"], "1.0.0-rc.1")
        self.assertEqual(gates["iteration"], "v1.0-conversation-native")
        self.assertEqual(gates["distribution_kind"], "source_checkout_rc")
        self.assertEqual(gates["wheel_scope"], "backend_only")
        self.assertEqual(gates["expected_product_name"], "Specialist Model Studio")
        self.assertEqual(gates["expected_distribution_name"], "specialist-model-studio")
        self.assertEqual(gates["canonical_console_script"], "specialist-model-studio")
        self.assertEqual(gates["compatibility_console_scripts"], ["small-model-harness"])
        self.assertIn("remote detached clone", gates["aggregation_contract"]["public_rc_condition"])
        level_ids = {item["level_id"] for item in gates["levels"]}
        self.assertEqual(level_ids, {"L0", "L1", "L2", "L3", "L4", "L5", "L6", "release"})
        release_gate = next(
            item for item in gates["levels"] if item["level_id"] == "release"
        )
        self.assertTrue(release_gate["required_for_github_release"])
        self.assertFalse(release_gate["required"])

    def test_local_environment_files_are_ignored_except_for_example(self) -> None:
        patterns = set(
            (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        )

        self.assertIn(".env", patterns)
        self.assertIn(".env.*", patterns)
        self.assertIn("!.env.example", patterns)


if __name__ == "__main__":
    unittest.main()
