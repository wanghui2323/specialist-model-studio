from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from model_harness.cli import (
    STUDIO_SOURCE_ROOT_ENV,
    _resolve_studio_source_root,
    main,
)


def _complete_source_checkout(root: Path) -> Path:
    for relative in (
        "pyproject.toml",
        "scripts/start_conversation_harness.sh",
        "integrations/deepseek-harness/package.json",
        "acceptance/dsh-runtime/package.json",
    ):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("test\n", encoding="utf-8")
    return root


class StudioStartCliTest(unittest.TestCase):
    @mock.patch("model_harness.cli.subprocess.run")
    def test_start_forwards_product_and_internal_runtime_configuration(
        self,
        run: mock.Mock,
    ) -> None:
        run.return_value.returncode = 0

        result = main(
            [
                "start",
                "--runs-dir",
                "selected-runs",
                "--host",
                "127.0.0.1",
                "--port",
                "8812",
                "--agent-host",
                "127.0.0.1",
                "--agent-port",
                "3096",
            ]
        )

        self.assertEqual(result, 0)
        invocation = run.call_args
        self.assertEqual(invocation.args[0][0], "bash")
        self.assertTrue(invocation.args[0][1].endswith("start_conversation_harness.sh"))
        self.assertFalse(invocation.kwargs["check"])
        environment = invocation.kwargs["env"]
        self.assertEqual(environment["SPECIALIST_MODEL_STUDIO_PUBLIC_START"], "1")
        self.assertTrue(Path(environment[STUDIO_SOURCE_ROOT_ENV]).is_absolute())
        self.assertEqual(environment["MODEL_HARNESS_PYTHON"], sys.executable)
        self.assertEqual(environment["MODEL_HARNESS_RUNS_DIR"], "selected-runs")
        self.assertEqual(environment["MODEL_HARNESS_PORT"], "8812")
        self.assertEqual(environment["MODEL_HARNESS_AGENT_PORT"], "3096")

    @mock.patch("model_harness.cli.subprocess.run")
    def test_start_propagates_fail_closed_launcher_status(self, run: mock.Mock) -> None:
        run.return_value.returncode = 7

        self.assertEqual(main(["start"]), 7)

    @mock.patch("model_harness.cli.subprocess.run", side_effect=KeyboardInterrupt)
    def test_start_handles_interactive_stop_without_a_traceback(
        self,
        _run: mock.Mock,
    ) -> None:
        self.assertEqual(main(["start"]), 130)

    def test_explicit_source_root_is_canonical_and_has_priority(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            selected = _complete_source_checkout(Path(temp_dir) / "selected")
            with mock.patch.dict(
                os.environ,
                {STUDIO_SOURCE_ROOT_ENV: str(selected)},
                clear=False,
            ), mock.patch("model_harness.cli.__file__", "/missing/model_harness/cli.py"), mock.patch(
                "model_harness.cli.sys.prefix", "/missing/.venv"
            ):
                self.assertEqual(_resolve_studio_source_root(), selected.resolve())

    def test_invalid_explicit_source_root_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            incomplete = Path(temp_dir) / "incomplete"
            incomplete.mkdir()
            with mock.patch.dict(
                os.environ,
                {STUDIO_SOURCE_ROOT_ENV: str(incomplete)},
                clear=False,
            ):
                with self.assertRaisesRegex(
                    RuntimeError,
                    "does not identify a complete",
                ):
                    _resolve_studio_source_root()

    def test_non_editable_wheel_in_checkout_venv_uses_prefix_parent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            checkout = _complete_source_checkout(Path(temp_dir) / "release")
            installed_cli = (
                checkout
                / ".venv/lib/python3.12/site-packages/model_harness/cli.py"
            )
            with mock.patch.dict(
                os.environ,
                {STUDIO_SOURCE_ROOT_ENV: ""},
                clear=False,
            ), mock.patch(
                "model_harness.cli.__file__",
                str(installed_cli),
            ), mock.patch(
                "model_harness.cli.sys.prefix",
                str(checkout / ".venv"),
            ):
                self.assertEqual(_resolve_studio_source_root(), checkout.resolve())


if __name__ == "__main__":
    unittest.main()
