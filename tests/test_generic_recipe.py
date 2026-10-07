from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

from model_harness.errors import ContractError, RunCancelled
from model_harness.generic_data import create_generic_dataset
from model_harness.generic_protocol import validate_execution_spec
from model_harness.generic_recipe import GenericIsolatedRecipePlugin, read_stage_json
from model_harness.io_utils import read_json, sha256_file, write_json
from model_harness.isolated_execution import ExecutionBundle
from model_harness.material_inspection import MaterialInspectionStore
from model_harness.plugin_api import RunExecutionContext
from model_harness.plugins import PluginRegistry
from model_harness.runner import execute_run, prepare_run, verify_run


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


class EvidenceExecutor:
    """Fixture stage results; never executes generated source on the host."""
    def __init__(self):
        self.calls = []
        self.result_overrides = {}
        self.statuses = {}
        self.metric = 0.9
        self.additional_outputs = {}
        self.evidences = {}

    def run_stage(self, bundle, stage, *, expected_bundle_digest, isolated_root, input_files, cancel_event):
        self.calls.append({"stage": stage, "inputs": dict(input_files), "config": read_json(input_files["config.json"])})
        execution_id = "stage-" + uuid4().hex
        output = isolated_root / execution_id / "output"
        output.mkdir(parents=True)
        if stage == "train":
            (output / "weights").mkdir()
            write_json(output / "weights" / "projection.json", {"weights": [2, -1], "bias": 0.5})
            result = {"selected_model": "candidate-2", "validation_candidates": {"candidate-1": {"vector_agreement": 0.5}, "candidate-2": {"vector_agreement": 0.9}},
                      "split_counts": {"train": 30, "validation": 10, "test": 999999}, "model_files": ["weights/projection.json"]}
            name = "train_result.json"
        elif stage == "evaluate":
            result = {"metrics": {"vector_agreement": self.metric}, "sample_count": 20, "failure_samples": [], "all_passed": True}
            name = "evaluate_result.json"
        elif stage == "qualify":
            result, name = {"checks": {"parameter_update": True, "prediction_reload": True}}, "qualification.json"
        else:
            result, name = {"prediction": [2.5, -0.5]}, "infer_result.json"
        result.update(self.result_overrides.get(stage, {}))
        write_json(output / name, result)
        for relative, content in self.additional_outputs.get(stage, {}).items():
            target = output / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(content, bytes):
                target.write_bytes(content)
            else:
                write_json(target, content)
        evidence = {"execution_id": execution_id, "job_directory": execution_id, "stage": stage, "bundle_sha256": bundle.digest,
                    "status": self.statuses.get(stage, "completed"), "executed": True, "exit_code": 0, "container_removed": True,
                    "runtime": {"runtime": "unit-fixture", "version": "fixture-only"}, "image_reference": bundle.image,
                    "image": {"id": "sha256:" + "b" * 64, "os": "linux", "architecture": "arm64"},
                    "inputs": [{"path": key, "sha256": sha256_file(path), "bytes": path.stat().st_size} for key, path in input_files.items()],
                    "artifacts": [{"path": path.relative_to(output).as_posix(), "sha256": sha256_file(path), "bytes": path.stat().st_size} for path in output.rglob("*") if path.is_file()]}
        evidence["evidence_sha256"] = digest(evidence)
        self.evidences[stage] = evidence
        return evidence


class GenericRecipeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.owner = "task-unknown-vector"
        self.task_dir = self.root / "workspace" / "tasks" / self.owner
        write_json(self.task_dir / "task.json", {"task_id": self.owner, "current_spec_revision": 1})
        materials = MaterialInspectionStore(self.root / "workspace")
        data = "left,right,target\n" + "".join(f"{i},{i + 2},{2 * i - 0.5}\n" for i in range(60))
        receipt, _ = materials.upload(self.owner, data.encode(), "unseen.csv", "test-material")
        mapping = [{"material_id": receipt["material_id"], "inspection_sha256": receipt["inspection_sha256"], "split": split, "csv_rows": {"start": start, "stop": stop}}
                   for split, start, stop in [("train", 0, 30), ("validation", 30, 40), ("test", 40, 60)]]
        dataset = create_generic_dataset(self.task_dir, materials, self.owner, mapping)
        self.executor = EvidenceExecutor()
        self.plugin = GenericIsolatedRecipePlugin(self.executor)
        bundle = ExecutionBundle.create(files={"unseen.py": "# Fixture source is never run on the host\n"},
            stages={name: ["python", "/workspace/source/unseen.py", name] for name in ("qualify", "train", "evaluate", "predict")}, image="python@sha256:" + "a" * 64)
        spec = validate_execution_spec({"bundle": bundle.to_dict(), "description": "User-defined vector objective", "capability": {"family": "unseen_vector_projection", "training_route": "from_scratch"},
            "config": {"learning_rate": 0.02}, "data_mapping": mapping,
            "evaluation": {"primary_metric": "vector_agreement", "gates": {"vector_agreement": {"operator": "gte", "threshold": 0.8}}, "minimum_test_samples": 20, "test_unit": "independent row"},
            "artifacts": [{"path": "weights/projection.json", "role": "model", "export": True}], "inference": {"extensions": [".json"], "max_bytes": 2048}})
        self.contract = self.plugin.template()
        self.contract.update(task_id=self.owner, business_goal="Learn an unlisted vector transform", dataset=dataset.contract_dataset, execution_spec=spec)
        self.registry = PluginRegistry(include_builtins=False)
        self.registry.register_recipe(self.plugin)

    def context(self, name="manual"):
        return RunExecutionContext(self.owner, name, self.root / "runs" / name, self.root / "isolated")

    def run_fixture(self):
        run_dir = prepare_run(self.contract, self.root / "runs", registry=self.registry)
        execute_run(run_dir, registry=self.registry)
        return run_dir

    def test_runner_keeps_one_real_run_and_separates_train_test_and_prediction_inputs(self):
        run_dir = self.run_fixture()
        state, manifest = read_json(run_dir / "run_state.json"), read_json(run_dir / "run_manifest.json")
        self.assertEqual(state["status"], "completed")
        self.assertEqual(state["run_id"], manifest["run_id"])
        self.assertEqual(manifest["dependencies"], {})
        self.assertIsNone(manifest["python"])
        self.assertEqual(manifest["execution_environment"]["image"]["os"], "linux")
        self.assertTrue(verify_run(run_dir, deep=True, registry=self.registry)["ok"])
        calls = {item["stage"]: item for item in self.executor.calls}
        self.assertEqual(set(calls["train"]["inputs"]), {"train/unseen.csv", "validation/unseen.csv", "config.json"})
        self.assertEqual(set(calls["evaluate"]["inputs"]), {"test/unseen.csv", "model/weights/projection.json", "config.json"})
        self.assertEqual(calls["train"]["config"], {"learning_rate": 0.02})
        metrics = read_json(run_dir / "artifacts" / "metrics.json")
        self.assertEqual(metrics["split_counts"]["test"], 20, "the train stage cannot claim final-test sample counts")
        self.assertEqual(metrics["clean_test"], {"vector_agreement": 0.9})
        self.assertTrue(read_json(run_dir / "evidence" / "evaluation_report.json")["release_ready"])
        model = read_json(run_dir / "artifacts" / "generic_model.json")
        paths = {item["path"] for item in model["artifacts"]}
        self.assertTrue({"weights/projection.json", "generic_execution.json", "source/unseen.py", "config.json"} <= paths)
        portable = read_json(run_dir / "artifacts" / "generic_execution.json")
        self.assertNotIn("data_mapping", portable)
        self.assertNotIn("capability", portable)
        self.assertNotIn(str(self.root), json.dumps(portable))
        new_input = self.root / "fresh.json"
        write_json(new_input, {"left": 5, "right": 1})
        prediction = self.plugin.predict(self.contract, model_dir=run_dir / "artifacts", input_files={"new_input.json": new_input},
            context=RunExecutionContext(self.owner, state["run_id"], run_dir, self.root / "isolated"))
        self.assertEqual(prediction["prediction"], [2.5, -0.5])
        self.assertEqual(set(self.executor.calls[-1]["inputs"]), {"model/weights/projection.json", "new_input.json", "config.json"})

    def test_named_evaluation_artifacts_use_their_own_evidence_and_never_enter_prediction(self):
        self.contract["execution_spec"]["artifacts"].extend([
            {"path": "reports/evaluation.json", "role": "report", "export": True, "stage": "evaluate"},
            {"path": "private/test_labels.json", "role": "raw_data", "export": False, "stage": "evaluate"},
        ])
        self.executor.additional_outputs = {
            "train": {"reports/evaluation.json": {"wrong_stage": "not the final-test report"}},
            "evaluate": {"reports/evaluation.json": {"observed_final_test_count": 20, "vector_agreement": .9},
                         "private/test_labels.json": {"labels": ["private-label-value"]}},
        }
        run_dir = self.run_fixture()
        manifest = read_json(run_dir / "artifacts/generic_model.json")
        records = {row["path"]: row for row in manifest["artifacts"]}
        model = records["weights/projection.json"]
        report = records["reports/evaluation.json"]
        labels = records["private/test_labels.json"]
        self.assertEqual(model["stage"], "train")
        self.assertEqual(report["stage"], "evaluate")
        self.assertEqual(report["source_execution_id"], self.executor.evidences["evaluate"]["execution_id"])
        self.assertEqual(report["source_execution_sha256"], self.executor.evidences["evaluate"]["evidence_sha256"])
        expected = next(row for row in self.executor.evidences["evaluate"]["artifacts"] if row["path"] == "reports/evaluation.json")
        wrong_stage = next(row for row in self.executor.evidences["train"]["artifacts"] if row["path"] == "reports/evaluation.json")
        self.assertEqual(sha256_file(run_dir / "artifacts/reports/evaluation.json"), expected["sha256"])
        self.assertNotEqual(report["sha256"], wrong_stage["sha256"])
        self.assertFalse(labels["export"])
        self.assertEqual(labels["role"], "raw_data")
        self.assertEqual(manifest["model_files"], ["weights/projection.json"])
        self.assertTrue(verify_run(run_dir, deep=True, registry=self.registry)["ok"])
        fresh = self.root / "fresh-stage-input.json"
        write_json(fresh, {"left": 5, "right": 1})
        state = read_json(run_dir / "run_state.json")
        self.plugin.predict(self.contract, model_dir=run_dir / "artifacts", input_files={"new_input.json": fresh},
            context=RunExecutionContext(self.owner, state["run_id"], run_dir, self.root / "isolated"))
        mounted = set(self.executor.calls[-1]["inputs"])
        self.assertEqual(mounted, {"model/weights/projection.json", "new_input.json", "config.json"})
        self.assertFalse(any("test_labels" in path or "evaluation.json" in path for path in mounted))

    def test_evaluation_declaration_cannot_be_claimed_as_selected_model_even_if_train_writes_it(self):
        self.contract["execution_spec"]["artifacts"].append({"path": "reports/extra.json", "role": "report", "export": False, "stage": "evaluate"})
        self.executor.additional_outputs = {"train": {"reports/extra.json": {"not_a_checkpoint": True}}}
        self.executor.result_overrides["train"] = {"model_files": ["reports/extra.json"]}
        with self.assertRaisesRegex(ContractError, "train-stage"):
            self.plugin.train_with_context(self.contract, self.context())
        self.assertEqual([call["stage"] for call in self.executor.calls], ["train"])

    def test_evaluation_artifact_cannot_fall_back_to_train_or_changed_bytes(self):
        self.contract["execution_spec"]["artifacts"].append({"path": "reports/extra.json", "role": "report", "export": False, "stage": "evaluate"})
        self.executor.additional_outputs = {"train": {"reports/extra.json": {"wrong": True}}}
        training = self.plugin.train_with_context(self.contract, self.context())
        evaluation = self.plugin.evaluate(training, self.contract)
        with self.assertRaisesRegex(ContractError, "not uniquely declared"):
            self.plugin.package(training, evaluation, self.contract, self.root / "bad-package")
        self.executor.additional_outputs["evaluate"] = {"reports/extra.json": {"genuine": True}}
        evaluation = self.plugin.evaluate(training, self.contract)
        produced = training.context.isolated_root / evaluation.stage_evidence["job_directory"] / "output/reports/extra.json"
        produced.write_text("changed after final evaluation")
        with self.assertRaisesRegex(ContractError, "changed after execution"):
            self.plugin.package(training, evaluation, self.contract, self.root / "changed-package")

    def test_host_computes_gates_instead_of_trusting_worker_success_flags(self):
        self.executor.metric = 0.1
        run_dir = self.run_fixture()
        self.assertEqual(read_json(run_dir / "run_state.json")["status"], "completed")
        gates = read_json(run_dir / "artifacts" / "metrics.json")["gate_checks"]
        self.assertFalse(gates["vector_agreement"])
        self.assertFalse(gates["all_offline_gates_passed"])
        self.assertEqual(read_json(run_dir / "evidence" / "evaluation_report.json")["conclusion"], "quality_failed")

    def test_qualification_uses_train_validation_and_exact_executor_json_evidence(self):
        context = self.context()
        evidence = self.plugin.qualify(self.contract, context)
        self.assertTrue(read_stage_json(context, evidence, "qualification.json")["checks"]["parameter_update"])
        self.assertNotIn("test/unseen.csv", self.executor.calls[-1]["inputs"])
        path = context.isolated_root / evidence["execution_id"] / "output" / "qualification.json"
        path.write_text("{}")
        with self.assertRaisesRegex(ContractError, "changed"):
            read_stage_json(context, evidence, "qualification.json")

    def test_changed_dataset_or_model_prevents_next_stage(self):
        training = self.plugin.train_with_context(self.contract, self.context())
        model = training.context.isolated_root / training.stage_evidence["execution_id"] / "output" / training.model_files[0]
        model.write_text("tampered")
        with self.assertRaisesRegex(ContractError, "changed"):
            self.plugin.evaluate(training, self.contract)
        self.assertEqual(len(self.executor.calls), 1)
        train_file = Path(self.contract["dataset"]["root"]) / "train" / "unseen.csv"
        train_file.chmod(0o600)
        train_file.write_text("tampered")
        with self.assertRaises(ContractError):
            self.plugin.train_with_context(self.contract, self.context("second"))
        self.assertEqual(len(self.executor.calls), 1)

    def test_invalid_worker_model_paths_metrics_and_stage_failures_never_complete_a_run(self):
        for stage, override in [("train", {"model_files": ["../escaped.json"]}), ("evaluate", {"metrics": {"unrelated": 1}}), ("evaluate", {"metrics": {"vector_agreement": True}})]:
            with self.subTest(stage=stage, override=override):
                self.executor.result_overrides = {stage: override}
                run_dir = prepare_run(self.contract, self.root / "runs", registry=self.registry)
                with self.assertRaises(ContractError):
                    execute_run(run_dir, registry=self.registry)
                self.assertEqual(read_json(run_dir / "run_state.json")["status"], "failed")
                self.assertFalse((run_dir / "run_manifest.json").exists())
        self.executor.result_overrides = {}
        self.executor.statuses = {"train": "cancelled"}
        run_dir = self.run_fixture()
        self.assertEqual(read_json(run_dir / "run_state.json")["status"], "cancelled")

    def test_no_host_model_loading_and_no_training_data_as_new_input(self):
        with self.assertRaisesRegex(ContractError, "RunExecutionContext"):
            self.plugin.train(self.contract)
        run_dir = self.run_fixture()
        state = read_json(run_dir / "run_state.json")
        context = RunExecutionContext(self.owner, state["run_id"], run_dir, self.root / "isolated")
        with self.assertRaisesRegex(ContractError, "new input"):
            self.plugin.predict(self.contract, model_dir=run_dir / "artifacts", input_files={"new_input.json": Path(self.contract["dataset"]["root"]) / "test" / "unseen.csv"}, context=context)
        foreign = deepcopy(self.contract)
        foreign["execution_spec"]["config"]["input_path"] = "/Users/private/data.csv"
        with self.assertRaisesRegex(ContractError, "host paths"):
            self.plugin.validate_contract(foreign)

    def test_public_base_assets_are_verified_mounted_and_included_for_portable_reload(self):
        base_root = self.root / "public-model-asset"
        base_root.mkdir()
        base_path = base_root / "base_weights.json"
        write_json(base_path, {"base_projection": [1, 2, 3]})
        asset_id = "asset-123456789abcdef123456789"
        self.contract["execution_spec"]["asset_ids"] = [asset_id]
        asset = {"asset_id": asset_id, "task_id": self.owner,
            "files": [{"path": "base_weights.json", "bytes": base_path.stat().st_size, "sha256": sha256_file(base_path)}]}
        self.contract["execution_assets"] = [{**asset, "manifest_sha256": digest(asset), "root": str(base_root)}]
        run_dir = self.run_fixture()
        relative = f"assets/{asset_id}/base_weights.json"
        self.assertTrue(all(relative in call["inputs"] for call in self.executor.calls))
        self.assertEqual(sha256_file(run_dir / "artifacts" / relative), sha256_file(base_path))
        portable = read_json(run_dir / "artifacts" / "generic_execution.json")
        self.assertEqual(portable["base_assets"][0]["asset_id"], asset_id)
        self.assertNotIn(str(base_root), json.dumps(portable))
        model = read_json(run_dir / "artifacts" / "generic_model.json")
        self.assertTrue(next(row for row in model["artifacts"] if row["path"] == relative)["export"])
        base_path.write_text("tampered")
        with self.assertRaisesRegex(ContractError, "asset file integrity"):
            self.plugin.train_with_context(self.contract, self.context("tampered-asset"))

    def test_resealing_changed_model_metadata_does_not_override_the_run_manifest(self):
        run_dir = self.run_fixture()
        state = read_json(run_dir / "run_state.json")
        manifest = read_json(run_dir / "artifacts" / "generic_model.json")
        manifest["selected_model"] = "different-model"
        manifest["model_sha256"] = digest({key: value for key, value in manifest.items() if key != "model_sha256"})
        write_json(run_dir / "artifacts" / "generic_model.json", manifest)
        new_input = self.root / "new-input.json"
        write_json(new_input, {"left": 1, "right": 2})
        with self.assertRaisesRegex(ContractError, "canonical Run"):
            self.plugin.predict(self.contract, model_dir=run_dir / "artifacts", input_files={"new_input.json": new_input}, context=RunExecutionContext(self.owner, state["run_id"], run_dir, self.root / "isolated"))


if __name__ == "__main__":
    unittest.main()
