from __future__ import annotations

import tempfile
import unittest
from copy import deepcopy

from model_harness.io_utils import read_json
from model_harness.runner import verify_run
from model_harness.service import RunService
from model_harness.templates import DIGIT_CLASSIFICATION_TEMPLATE


class RunEvidenceLifecycleTests(unittest.TestCase):
    def test_completed_run_auto_reports_and_test_driven_child_is_contaminated(self) -> None:
        contract = deepcopy(DIGIT_CLASSIFICATION_TEMPLATE)
        contract["model_selection"]["candidates"] = ["rbf_svm"]
        with tempfile.TemporaryDirectory() as temp_dir:
            with RunService(temp_dir, recover=False) as service:
                parent = service.submit(contract, run_id="evidence-parent")
                service.wait(parent.name, timeout=30)
                parent_result = service.result(parent.name)

                self.assertEqual(parent_result["run_status"], "completed")
                self.assertEqual(parent_result["integrity_status"], "passed")
                self.assertEqual(parent_result["metric_gate_status"], "passed")
                self.assertEqual(parent_result["evidence_status"], "sufficient")
                self.assertTrue(parent_result["release_ready"])
                self.assertTrue(
                    (parent / "evidence" / "evaluation_report.json").is_file()
                )

                strategy_document = service.strategies(parent.name)
                self.assertTrue(
                    strategy_document["evidence_provenance"]["uses_test_evidence"]
                )
                proposal = next(
                    item
                    for item in strategy_document["strategies"]
                    if item["strategy_id"] == "add-shift-augmentation"
                )
                self.assertTrue(
                    proposal["evidence_provenance"]["uses_test_evidence"]
                )

                child = service.apply_strategy(
                    parent.name,
                    "add-shift-augmentation",
                    child_run_id="evidence-child",
                )
                service.wait(child.name, timeout=30)
                child_result = service.result(child.name)
                child_contract = read_json(child / "task_contract.json")
                child_metrics = read_json(child / "artifacts" / "metrics.json")

                self.assertTrue(
                    child_contract["evidence_policy"]["test_contaminated"]
                )
                self.assertTrue(
                    child_contract["optimization_history"][0]["test_contaminated"]
                )
                self.assertTrue(child_metrics["test_contaminated"])
                self.assertEqual(child_result["run_status"], "completed")
                self.assertEqual(child_result["integrity_status"], "passed")
                self.assertEqual(
                    child_result["evidence_status"], "insufficient_evidence"
                )
                self.assertEqual(
                    child_result["evaluation_conclusion"],
                    "insufficient_evidence",
                )
                self.assertFalse(child_result["release_ready"])

                inference = service.inference_check(
                    parent.name,
                    {"features": [0.0] * 64},
                )
                self.assertEqual(inference["status"], "passed")
                bundle = service.build_artifact_bundle(
                    parent.name,
                    inference_check_id=inference["check_id"],
                )
                self.assertTrue(bundle["release_ready"])
                self.assertTrue(
                    service.artifact_bundle_path(
                        parent.name,
                        bundle["bundle_id"],
                    ).is_file()
                )
                self.assertEqual(
                    service.evidence_report(parent.name)["inference_checks"][0][
                        "check_id"
                    ],
                    inference["check_id"],
                )

    def test_quality_gate_failure_keeps_completed_integrity_passed_model(self) -> None:
        contract = deepcopy(DIGIT_CLASSIFICATION_TEMPLATE)
        contract["model_selection"]["candidates"] = ["rbf_svm"]
        contract["release_gates"].update(
            {
                "clean_test_accuracy_min": 1.0,
                "clean_test_macro_f1_min": 1.0,
                "clean_test_worst_class_recall_min": 1.0,
            }
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            with RunService(temp_dir, recover=False) as service:
                run_dir = service.submit(contract, run_id="quality-failed")
                service.wait(run_dir.name, timeout=30)
                result = service.result(run_dir.name)

                self.assertEqual(result["status"], "completed")
                self.assertEqual(result["run_status"], "completed")
                self.assertFalse(result["offline_gates_passed"])
                self.assertEqual(result["integrity_status"], "passed")
                self.assertEqual(result["metric_gate_status"], "failed")
                self.assertEqual(result["evidence_status"], "sufficient")
                self.assertEqual(result["evaluation_conclusion"], "quality_failed")
                self.assertFalse(result["release_ready"])
                self.assertTrue((run_dir / "artifacts" / "model.joblib").is_file())
                self.assertTrue((run_dir / "run_manifest.json").is_file())
                verification = verify_run(run_dir, deep=True)
                self.assertTrue(verification["ok"], verification["errors"])
                self.assertTrue(verification["deep_verified"])
                self.assertEqual(verification["integrity_status"], "passed")
                self.assertEqual(verification["metric_gate_status"], "failed")
                self.assertFalse(verification["release_ready"])
                self.assertEqual(
                    verification["quality_errors"],
                    ["one or more offline gates failed"],
                )


if __name__ == "__main__":
    unittest.main()
