from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from model_harness.io_utils import read_json
from model_harness.runner import run_task, verify_run


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "examples" / "digit-classification" / "task_contract.json"


class IntegrationTests(unittest.TestCase):
    def test_reference_recipe_runs_and_verifies(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = run_task(CONTRACT, temp_dir, "integration")
            state = read_json(run_dir / "run_state.json")
            self.assertEqual(state["status"], "completed")
            self.assertTrue(state["offline_gates_passed"])

            result = verify_run(run_dir, deep=True)
            self.assertTrue(result["ok"], result["errors"])
            self.assertTrue(result["deep_verified"])
            self.assertEqual(result["artifact_count"], 6)

            metrics = read_json(run_dir / "artifacts" / "metrics.json")
            self.assertEqual(metrics["selected_model"], "rbf_svm")
            self.assertGreaterEqual(metrics["clean_test"]["accuracy"], 0.96)
            self.assertLess(
                metrics["stress_tests"]["shift_right_one_pixel"]["accuracy"],
                metrics["clean_test"]["accuracy"],
            )

            report = (run_dir / "artifacts" / "learning_report.md").read_text(
                encoding="utf-8"
            )
            self.assertIn("人还需要决定什么", report)
            self.assertIn("不能直接上线", report)


if __name__ == "__main__":
    unittest.main()
