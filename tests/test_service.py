from __future__ import annotations

import tempfile
import unittest
from copy import deepcopy

from model_harness.io_utils import read_json
from model_harness.runner import prepare_run
from model_harness.service import RunService
from model_harness.templates import DIGIT_CLASSIFICATION_TEMPLATE


class RunServiceTests(unittest.TestCase):
    def test_startup_marks_stale_run_interrupted_and_resume_creates_child(self) -> None:
        contract = deepcopy(DIGIT_CLASSIFICATION_TEMPLATE)
        contract["model_selection"]["candidates"] = ["rbf_svm"]
        with tempfile.TemporaryDirectory() as temp_dir:
            stale = prepare_run(contract, temp_dir, run_id="stale")
            with RunService(temp_dir, recover=True) as service:
                self.assertEqual(service.recovered_runs, ["stale"])
                self.assertEqual(service.status("stale")["status"], "interrupted")
                child = service.resume("stale", child_run_id="resumed")
                service.wait(child.name, timeout=30)
                child_state = service.status(child.name)

            self.assertEqual(child_state["status"], "completed")
            self.assertEqual(child_state["parent_run_id"], stale.name)

    def test_approved_strategy_creates_completed_child_run(self) -> None:
        contract = deepcopy(DIGIT_CLASSIFICATION_TEMPLATE)
        contract["model_selection"]["candidates"] = ["rbf_svm"]
        with tempfile.TemporaryDirectory() as temp_dir:
            with RunService(temp_dir, recover=False) as service:
                parent = service.submit(contract, run_id="parent")
                service.wait(parent.name, timeout=30)
                proposals = service.strategies(parent.name)["strategies"]
                self.assertIn(
                    "add-shift-augmentation",
                    {item["strategy_id"] for item in proposals},
                )

                child = service.apply_strategy(
                    parent.name,
                    "add-shift-augmentation",
                    child_run_id="child",
                )
                service.wait(child.name, timeout=30)
                child_state = service.status(child.name)

            self.assertEqual(child_state["status"], "completed")
            self.assertEqual(child_state["parent_run_id"], "parent")
            child_contract = read_json(child / "task_contract.json")
            self.assertIn(
                "shift_left_right",
                child_contract["recipe_options"]["augmentations"],
            )
            self.assertEqual(
                child_contract["optimization_history"][0]["strategy_id"],
                "add-shift-augmentation",
            )
            metrics = read_json(child / "artifacts" / "metrics.json")
            self.assertGreater(
                metrics["training"]["final_fit_count"],
                sum(metrics["split_counts"][key] for key in ("train", "validation")),
            )


if __name__ == "__main__":
    unittest.main()
