from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from model_harness import __version__


ROOT = Path(__file__).resolve().parents[1]


class CliInstallationTests(unittest.TestCase):
    def _installed_console_script(self, name: str = "specialist-model-studio") -> Path:
        suffix = ".exe" if os.name == "nt" else ""
        return Path(sys.executable).parent / f"{name}{suffix}"

    def test_installed_console_scripts_report_package_version(self) -> None:
        for name in ("specialist-model-studio", "small-model-harness"):
            with self.subTest(name=name):
                console_script = self._installed_console_script(name)
                self.assertTrue(console_script.is_file())
                completed = subprocess.run(
                    [str(console_script), "--version"],
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=30,
                    check=False,
                )

                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertEqual(completed.stdout.strip(), f"{name} {__version__}")

    def test_cli_import_does_not_eagerly_load_training_stack(self) -> None:
        """Metadata/help commands must not pay the scientific runtime startup cost."""

        environment = dict(os.environ)
        environment.pop("PYTHONPATH", None)
        environment["PYTHONNOUSERSITE"] = "1"
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import json, sys; import model_harness.cli as cli; cli.build_parser(); "
                    "print(json.dumps({name: name in sys.modules for name in "
                    "['numpy', 'sklearn', 'joblib']}))"
                ),
            ],
            cwd=ROOT,
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(
            json.loads(completed.stdout),
            {"numpy": False, "sklearn": False, "joblib": False},
        )

    def test_recipe_manifests_do_not_eagerly_load_training_stack(self) -> None:
        """Recipe discovery must keep metadata separate from training runtimes."""

        environment = dict(os.environ)
        environment.pop("PYTHONPATH", None)
        environment["PYTHONNOUSERSITE"] = "1"
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import json, sys; "
                    "from model_harness.plugins import default_registry; "
                    "recipes = default_registry().recipe_manifests(); "
                    "print(json.dumps({'recipe_count': len(recipes), 'loaded': "
                    "{name: name in sys.modules for name in "
                    "['numpy', 'sklearn', 'joblib', 'onnxruntime']}}))"
                ),
            ],
            cwd=ROOT,
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertGreaterEqual(payload["recipe_count"], 3)
        self.assertEqual(
            payload["loaded"],
            {
                "numpy": False,
                "sklearn": False,
                "joblib": False,
                "onnxruntime": False,
            },
        )

    def test_installed_console_script_runs_outside_repository_cwd(self) -> None:
        """The CLI must come from the installed package, not cwd import leakage."""

        console_script = self._installed_console_script()
        self.assertTrue(
            console_script.is_file(),
            f"installed console script is missing: {console_script}",
        )
        environment = dict(os.environ)
        environment.pop("PYTHONPATH", None)
        environment["PYTHONNOUSERSITE"] = "1"
        with tempfile.TemporaryDirectory() as temporary:
            outside_cwd = Path(temporary).resolve()
            self.assertFalse(outside_cwd.is_relative_to(ROOT))
            completed = subprocess.run(
                [str(console_script), "list-recipes"],
                cwd=outside_cwd,
                env=environment,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=30,
                check=False,
            )
        self.assertEqual(
            completed.returncode,
            0,
            f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}",
        )
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["version"], __version__)
        self.assertTrue(
            {
                "digit-classification",
                "image-folder-classification",
                "tabular-regression",
            }.issubset(
                {str(item.get("plugin_id")) for item in payload["recipes"]}
            )
        )
        self.assertNotIn(str(ROOT), completed.stderr)


if __name__ == "__main__":
    unittest.main()
