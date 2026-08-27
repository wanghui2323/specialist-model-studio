from __future__ import annotations

import sys
import unittest
from unittest import mock

from model_harness.cli import main


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


if __name__ == "__main__":
    unittest.main()
