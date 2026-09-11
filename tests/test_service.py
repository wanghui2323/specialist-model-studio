from __future__ import annotations

import tempfile
import unittest
from concurrent.futures import Future
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from model_harness.errors import ContractError
from model_harness.io_utils import read_json
from model_harness.runner import prepare_run, run_task
from model_harness.service import RunService
from model_harness.state import RunState
from model_harness.templates import DIGIT_CLASSIFICATION_TEMPLATE


class RunServiceTests(unittest.TestCase):
    def test_running_worker_keeps_cancel_requested_visible_until_it_stops(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir) / "running-cancel"
            worker_state = RunState(
                run_dir,
                "fixture-task",
                "running-cancel",
                "fixture-recipe",
            )
            worker_state.transition("queued")
            worker_state.transition("preflight")
            worker_state.transition("training")
            future: Future[Path] = Future()
            self.assertTrue(future.set_running_or_notify_cancel())
            with RunService(
                temp_dir,
                registry=object(),
                recover=False,
            ) as service:
                service._futures[run_dir.name] = future

                self.assertTrue(
                    service.cancel(
                        run_dir.name,
                        actor="system",
                        reason="disk reserve exhausted",
                        cancellation_kind="safety_stop",
                        scope="task_execution",
                    )
                )
                action = service.background_action(run_dir.name)

                self.assertEqual(action["status"], "cancel_requested")
                self.assertEqual(action["domain_status"], "training")
                self.assertTrue(action["running"])
                self.assertTrue(action["worker_running"])
                self.assertTrue(action["cancel_requested"])
                self.assertEqual(
                    action["cancel"],
                    {
                        "actor": "system",
                        "kind": "safety_stop",
                        "reason": "disk reserve exhausted",
                        "scope": "task_execution",
                        "requested_at_utc": action["cancel"]["requested_at_utc"],
                    },
                )
                self.assertEqual(action["last_event"]["type"], "run.cancel_requested")

                worker_state.event("training.worker_returned", {"ok": True})
                latest = RunState.load(run_dir)
                self.assertTrue(latest.cancel_requested)
                latest.cancel("requested by user")
                future.set_result(run_dir)
                settled = service.background_action(run_dir.name)

                self.assertEqual(settled["status"], "cancelled")
                self.assertFalse(settled["running"])
                self.assertFalse(settled["worker_running"])

    def test_workspace_owned_contract_rejects_direct_runner_and_service(self) -> None:
        contract = deepcopy(DIGIT_CLASSIFICATION_TEMPLATE)
        contract["task_id"] = "owned-task"
        with tempfile.TemporaryDirectory() as temp_dir:
            runs_dir = Path(temp_dir) / "runs"
            task_path = (
                runs_dir / "_workspace" / "tasks" / "owned-task" / "task.json"
            )
            task_path.parent.mkdir(parents=True)
            task_path.write_text('{"task_id":"owned-task"}\n', encoding="utf-8")

            with self.assertRaisesRegex(ContractError, "TrainingWorkspace"):
                run_task(contract, runs_dir, run_id="runner-bypass")
            with RunService(runs_dir, recover=False) as service:
                with self.assertRaisesRegex(ContractError, "TrainingWorkspace"):
                    service.submit(contract, run_id="service-bypass")
                self.assertEqual(service.list_runs(), [])

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

    def test_strategy_plugin_cannot_change_task_or_release_contract(self) -> None:
        contract = deepcopy(DIGIT_CLASSIFICATION_TEMPLATE)
        contract["model_selection"]["candidates"] = ["rbf_svm"]
        with tempfile.TemporaryDirectory() as temp_dir:
            with RunService(temp_dir, recover=False) as service:
                parent = service.submit(contract, run_id="parent-protected")
                service.wait(parent.name, timeout=30)
                malicious = deepcopy(contract)
                malicious["task_id"] = "stolen-task"
                malicious["release_gates"]["clean_test_accuracy_min"] = 0.0
                plugin = service.registry.get_recipe(str(contract["recipe"]))
                with patch.object(plugin, "apply_strategy", return_value=malicious):
                    with self.assertRaisesRegex(ContractError, "recipe_options"):
                        service.apply_strategy(
                            parent.name,
                            "add-shift-augmentation",
                            child_run_id="malicious-child",
                        )
                self.assertFalse((Path(temp_dir) / "malicious-child").exists())


if __name__ == "__main__":
    unittest.main()
