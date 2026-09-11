from __future__ import annotations

import unittest

from model_harness.errors import ContractError
from model_harness.training_plan_compiler import GIB, compile_training_plan
from model_harness.training_plans import TrainingPlanRevision


class TrainingPlanCompilerTests(unittest.TestCase):
    def fixture(self) -> dict:
        return compile_training_plan(
            task_spec={
                "revision": 1,
                "capability_request": {
                    "modality": "image",
                    "objective": "classification",
                },
            },
            snapshot={
                "files": [
                    {"path": "train.py", "kind": "blob", "size_bytes": 1200},
                    {
                        "path": "model.safetensors",
                        "kind": "blob",
                        "size_bytes": 3 * GIB,
                    },
                ]
            },
            analysis={
                "analyzer_version": "fixture/1",
                "resolved_commit": "a" * 40,
                "training_entrypoints": [
                    {
                        "path": "train.py",
                        "evidence_refs": ["train.py:L1#sha256=" + "b" * 64],
                    }
                ],
                "frameworks": [{"name": "pytorch", "evidence_refs": []}],
                "task_candidates": [
                    {"task": "image-classification", "confidence": 0.9}
                ],
                "base_model_candidates": [
                    {"model_id": "fixture/base", "evidence_refs": []}
                ],
                "dependency_files": [
                    {"path": "requirements.txt", "kind": "pip-requirements"}
                ],
                "data_contract_candidates": [
                    {"name": "image-folder", "evidence_refs": []}
                ],
                "metrics": [
                    {
                        "name": "accuracy",
                        "evidence_refs": ["train.py:L8#sha256=" + "b" * 64],
                    }
                ],
                "artifacts": [{"name": "onnx-model", "evidence_refs": []}],
            },
            selected_entrypoint="train.py",
        )

    def test_compiles_source_evidence_and_resource_estimate(self) -> None:
        compiled = self.fixture()
        self.assertEqual(compiled["entrypoint"]["argv"], ["python", "train.py"])
        self.assertEqual(compiled["evaluation"]["metrics"], ["accuracy"])
        self.assertEqual(
            compiled["artifact_contract"]["required"],
            ["trained-model", "metrics.json"],
        )
        self.assertEqual(
            compiled["dataset_mapping"]["plan_basis"]["resource_estimate_basis"]["status"],
            "provisional",
        )
        self.assertIn(
            "external_base_model_weight_size_is_not_verified",
            compiled["dataset_mapping"]["plan_basis"]["resource_estimate_basis"]["limitations"],
        )
        self.assertEqual(
            compiled["dataset_mapping"]["plan_basis"]["resolved_commit"],
            "a" * 40,
        )
        self.assertGreaterEqual(compiled["resource_budget"]["ram_bytes"], 7 * GIB)
        plan = TrainingPlanRevision.create(
            training_plan_revision_id="plan_compiler_fixture",
            task_id="task_compiler_fixture",
            base_spec_revision=1,
            source_snapshot_id="snapshot_fixture",
            snapshot_digest="c" * 64,
            analysis_id="analysis_fixture",
            analysis_digest="d" * 64,
            revision=1,
            **compiled,
        )
        self.assertEqual(plan.to_dict()["evaluation"]["metrics"], ["accuracy"])

    def test_rejects_entrypoint_outside_snapshot(self) -> None:
        with self.assertRaisesRegex(ContractError, "immutable source snapshot"):
            compile_training_plan(
                task_spec={"capability_request": {}},
                snapshot={"files": []},
                analysis={},
                selected_entrypoint="missing.py",
            )

    def test_rejects_readme_weight_and_inference_only_as_training_entrypoints(self) -> None:
        snapshot = {
            "files": [
                {"path": "README.md", "kind": "blob", "size_bytes": 20},
                {"path": "model.safetensors", "kind": "blob", "size_bytes": 20},
                {"path": "predict.py", "kind": "blob", "size_bytes": 20},
            ]
        }
        cases = (
            ("README.md", {"training_entrypoints": [{"path": "README.md"}]}),
            ("model.safetensors", {"training_entrypoints": [{"path": "model.safetensors"}]}),
            ("predict.py", {"entrypoints": [{"kind": "inference", "path": "predict.py"}]}),
        )
        for entrypoint, analysis in cases:
            with self.subTest(entrypoint=entrypoint):
                with self.assertRaises(ContractError):
                    compile_training_plan(
                        task_spec={"capability_request": {}},
                        snapshot=snapshot,
                        analysis=analysis,
                        selected_entrypoint=entrypoint,
                    )

    def test_missing_metric_evidence_cannot_create_approvable_plan(self) -> None:
        with self.assertRaisesRegex(ContractError, "evaluation metric"):
            compile_training_plan(
                task_spec={"capability_request": {}},
                snapshot={
                    "files": [
                        {"path": "train.py", "kind": "blob", "size_bytes": 20}
                    ]
                },
                analysis={
                    "training_entrypoints": [{"path": "train.py"}],
                    "metrics": [],
                },
                selected_entrypoint="train.py",
            )

    def test_confirmed_task_spec_metric_is_authoritative_over_analyzer_candidate(self) -> None:
        compiled = compile_training_plan(
            task_spec={
                "revision": 3,
                "capability_request": {"primary_metric": "accuracy"},
            },
            snapshot={
                "files": [{"path": "train.py", "kind": "blob", "size_bytes": 20}]
            },
            analysis={
                "training_entrypoints": [{"path": "train.py"}],
                "metrics": [{"name": "macro-f1", "evidence_refs": ["train.py:L2"]}],
            },
            selected_entrypoint="train.py",
        )
        self.assertEqual(compiled["evaluation"]["metrics"], ["accuracy"])
        self.assertEqual(
            compiled["evaluation"]["gates"]["analyzer_metric_candidates"],
            ["macro-f1"],
        )
        self.assertIn(
            "task_spec_revision:3:primary_metric",
            compiled["evaluation"]["gates"]["evidence_refs"],
        )


if __name__ == "__main__":
    unittest.main()
