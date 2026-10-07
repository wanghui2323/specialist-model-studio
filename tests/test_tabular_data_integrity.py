from __future__ import annotations

import csv
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import joblib
from fastapi.testclient import TestClient

from model_harness.data_adapters import TabularCsvAdapter
from model_harness.errors import ContractError
from model_harness.io_utils import read_json, write_json
from model_harness.recipes import tabular_classification, tabular_regression
from model_harness.recipes.tabular_classification_plugin import TabularClassificationPlugin
from model_harness.recipes.tabular_regression_plugin import TabularRegressionPlugin
from model_harness.runner import verify_run
from model_harness.sample_inference import SampleInference
from model_harness.server import create_app
from tests.contract_confirmation import contract_confirmation_payload
from tests.run_authorization import start_authorized_task_run


def csv_bytes(headers: list[str], rows: list[list[object]]) -> bytes:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(headers)
    writer.writerows(rows)
    return output.getvalue().encode("utf-8")


class TabularDataIntegrityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def import_rows(self, headers, rows, objective="regression", ignored=()):
        return TabularCsvAdapter().import_data(
            self.root / "datasets", csv_bytes(headers, rows), "data.csv",
            {"target_column": "target", "objective": objective, "ignored_columns": list(ignored)},
        )

    def contract(self, imported, objective="regression"):
        plugin = TabularRegressionPlugin() if objective == "regression" else TabularClassificationPlugin()
        contract = plugin.template()
        contract["dataset"].update(imported.contract_dataset)
        if objective == "regression":
            contract = plugin.prepare_contract_for_dataset(contract, imported.report)
        plugin.validate_contract(contract)
        return contract

    def test_trimmed_headers_preserve_every_value_and_ambiguous_headers_fail(self):
        imported = self.import_rows([" x ", " target "], [[i, i * 2] for i in range(40)])
        with Path(imported.contract_dataset["csv_path"]).open() as source:
            rows = list(csv.DictReader(source))
        self.assertEqual([row["x"] for row in rows], [str(i) for i in range(40)])
        self.assertEqual(imported.report["missing_counts"], {"x": 0})
        with self.assertRaisesRegex(ContractError, "表头不能重复"):
            self.import_rows(["x", " x ", "target"], [[i, i, i] for i in range(40)])

    def test_malformed_rows_and_entirely_missing_columns_fail_explicitly(self):
        for row in ([1], [1, 2, 3]):
            with self.subTest(row=row), self.assertRaisesRegex(ContractError, "字段数量"):
                self.import_rows(["x", "target"], [row])
        with self.assertRaisesRegex(ContractError, "全部为空"):
            self.import_rows(["x", "target"], [["", i] for i in range(40)])

    def test_numeric_labels_keep_categorical_semantics(self):
        imported = self.import_rows(["x", "target"], [[i, i % 2] for i in range(40)], "classification")
        self.assertEqual(imported.report["target_kind"], "categorical")
        self.assertEqual(imported.report["target_summary"], {"classes": ["0", "1"]})
        self.assertEqual(imported.report["class_counts"], {"0": 20, "1": 20})
        contract = self.contract(imported, "classification")
        self.assertEqual(contract["release_gates"], TabularClassificationPlugin().template()["release_gates"])

    def test_ignored_identifiers_and_numeric_spellings_do_not_hide_duplicates(self):
        rows = [[f"id-{i}-{j}", str(i) if j == 0 else f"{i}.0", str(i % 2)] for i in range(40) for j in range(5)]
        imported = self.import_rows(["id", "x", "target"], rows, "classification", ignored=["id"])
        self.assertEqual(imported.report["row_count"], 40)
        self.assertEqual(imported.report["duplicate_count"], 160)
        self.assertEqual(imported.report["rejected_count"], 160)
        self.assertEqual(imported.report["class_counts"], {"0": 20, "1": 20})
        context = tabular_classification.train(self.contract(imported, "classification"))
        partitions = [{tuple(context.X[i]) for i in indices} for indices in (context.train_idx, context.validation_idx, context.test_idx)]
        self.assertTrue(partitions[0].isdisjoint(partitions[1]))
        self.assertTrue(partitions[0].isdisjoint(partitions[2]))
        self.assertTrue(partitions[1].isdisjoint(partitions[2]))

    def test_deduplication_preserves_minimum_rows_and_per_class_requirements(self):
        rows = [[f"id-{i}-{j}", i, i % 2] for i in range(10) for j in range(10)]
        with self.assertRaisesRegex(ContractError, "去重后至少需要30"):
            self.import_rows(["id", "x", "target"], rows, "classification", ignored=["id"])
        with self.assertRaisesRegex(ContractError, "每个类别至少需要5"):
            self.import_rows(["x", "target"], [[i, "rare" if i < 4 else "common"] for i in range(40)], "classification")

    def test_cross_label_conflicts_block_after_ignoring_id(self):
        rows = [[f"id-{i}", i, i % 2] for i in range(40)] + [["extra", "0.0", "1"]]
        with self.assertRaisesRegex(ContractError, "标签冲突"):
            self.import_rows(["id", "x", "target"], rows, "classification", ignored=["id"])

    def test_class_counts_describe_imbalance_without_changing_class_weights(self):
        imported = self.import_rows(
            ["x", "target"], [[i, "rare" if i < 5 else "common"] for i in range(40)],
            "classification",
        )
        self.assertEqual(imported.report["class_counts"], {"common": 35, "rare": 5})
        contract = self.contract(imported, "classification")
        self.assertFalse(contract["recipe_options"]["class_weight_balanced"])
        report_path = Path(imported.contract_dataset["report_path"])
        report = read_json(report_path)
        report["class_counts"] = {"common": 20, "rare": 20}
        write_json(report_path, report)
        with self.assertRaisesRegex(ContractError, "类别数量与导入报告不一致"):
            TabularClassificationPlugin().validate_contract(contract)
        report.pop("class_counts")
        write_json(report_path, report)
        TabularClassificationPlugin().validate_contract(contract)

    def test_regression_repeated_inputs_with_noisy_targets_stay_in_one_split(self):
        imported = self.import_rows(["id", "x", "target"], [[f"id-{i}-{j}", i, i * 2 + j * 0.1] for i in range(30) for j in range(2)], ignored=["id"])
        context = tabular_regression.train(self.contract(imported))
        partitions = [{tuple(context.X[i]) for i in indices} for indices in (context.train_idx, context.validation_idx, context.test_idx)]
        self.assertTrue(partitions[0].isdisjoint(partitions[1]))
        self.assertTrue(partitions[0].isdisjoint(partitions[2]))
        self.assertTrue(partitions[1].isdisjoint(partitions[2]))
        self.assertEqual(imported.report["effective_feature_group_count"], 30)
        with self.assertRaisesRegex(ContractError, "至少需要10组"):
            self.import_rows(["x", "target"], [[i % 3, i] for i in range(40)])

    def test_high_cardinality_reports_expansion_and_blocks_only_large_matrices(self):
        imported = self.import_rows(["id", "target"], [[f"id-{i}", i] for i in range(2000)])
        self.assertEqual(imported.report["dense_matrix_bytes_estimate"], 32_000_000)
        self.assertTrue(any("可能是ID" in item["message"] for item in imported.report["risks"]))
        with self.assertRaisesRegex(ContractError, "256 MiB"):
            self.import_rows(["id", "target"], [[f"id-{i}", i] for i in range(6000)])

    def test_contract_cannot_bypass_inspected_features(self):
        imported = self.import_rows(["x", "z", "target"], [[i, i * 3, i * 2] for i in range(40)])
        contract = self.contract(imported)
        contract["dataset"]["feature_columns"] = ["x"]
        contract["dataset"]["numeric_columns"] = ["x"]
        with self.assertRaisesRegex(ContractError, "与导入时的字段检查不一致"):
            tabular_regression.train(contract)

    def test_legacy_imports_preserve_partitions_or_request_a_new_dataset_version(self):
        for repeated in (False, True):
            with self.subTest(repeated=repeated):
                rows = [[i % 20 if repeated else i, i * 2] for i in range(40)]
                imported = self.import_rows(["x", "target"], rows)
                contract = self.contract(imported)
                report_path = Path(contract["dataset"]["report_path"])
                report = read_json(report_path)
                # Previous imports contained all field bindings, but no split
                # or resource inspection metadata.
                for key in (
                    "duplicate_count", "duplicate_policy", "split_policy",
                    "effective_feature_group_count", "categorical_cardinalities",
                    "encoded_feature_count_estimate", "dense_matrix_bytes_estimate",
                    "dense_matrix_bytes_limit",
                ):
                    report.pop(key, None)
                write_json(report_path, report)
                if repeated:
                    with self.assertRaisesRegex(ContractError, "原合同下更改测试集"):
                        tabular_regression.train(contract)
                else:
                    context = tabular_regression.train(contract)
                    old_partitions = tabular_regression._split_indices(
                        len(rows), contract["dataset"]["split"], contract["dataset"]["random_seed"],
                    )
                    for actual, expected in zip(
                        (context.train_idx, context.validation_idx, context.test_idx),
                        old_partitions, strict=True,
                    ):
                        self.assertEqual(actual.tolist(), expected.tolist())

    def test_missing_values_work_through_confirm_train_verify_sample_and_export(self):
        for objective in ("regression", "classification"):
            with self.subTest(objective=objective):
                runs = self.root / objective / "runs"
                app = create_app(runs)
                # An independent signal prevents ambiguous feature/label pairs
                # when x or category is missing.
                rows = [[i, "" if i % 7 == 0 else i * 0.5,
                         "" if i % 11 == 0 else ("A" if i % 2 else "B"),
                         i * 2.0 if objective == "regression" else i % 2]
                        for i in range(60)]
                with TestClient(app) as client:
                    created = client.post("/tasks", json={
                        "name": "缺失值流程", "business_goal": "检查真实表格流程",
                        "capability_request": {"modality": "tabular", "objective": objective,
                            "target_kind": "numeric" if objective == "regression" else "binary", "target_column": "target"},
                    })
                    self.assertEqual(created.status_code, 201, created.text)
                    task_id = created.json()["task"]["task_id"]
                    uploaded = client.post(f"/tasks/{task_id}/dataset", content=csv_bytes(["signal", " x ", "category", "target"], rows), headers={"X-Filename": "data.csv", "X-Target-Column": "target", "Content-Type": "text/csv"})
                    self.assertEqual(uploaded.status_code, 201, uploaded.text)
                    confirmed = client.post(f"/tasks/{task_id}/confirm", json=contract_confirmation_payload(client, task_id))
                    self.assertEqual(confirmed.status_code, 200, confirmed.text)
                    started = start_authorized_task_run(client, task_id)
                    self.assertEqual(started.status_code, 202, started.text)
                    run_id = started.json()["task"]["current_run_id"]
                    app.state.run_service.wait(run_id, timeout=30)
                    task = client.get(f"/tasks/{task_id}").json()["task"]
                    self.assertEqual(task["status"], "completed", task)
                run_dir = runs / run_id
                verified = verify_run(run_dir, deep=True)
                self.assertTrue(verified["ok"], verified)
                artifact_dir = run_dir / "artifacts"
                bundle = joblib.load(artifact_dir / "model.joblib")
                expected = bundle["estimator"].predict([[99.0, None, None]])[0]
                # JSON null and blank CSV fields represent the same missing input.
                sample = {"signal": 99, "x": None, "category": ""}
                report = SampleInference(run_dir).run(sample)
                self.assertEqual(report["prediction"][0], expected)
                self.assertIn('"status": "passed"', json.dumps(report))
                external_csv = self.root / f"{objective}-sample.csv"
                external_csv.write_text("signal, x ,category\n99,,\n", encoding="utf-8")
                self.assertEqual(SampleInference(run_dir).run(external_csv)["prediction"][0], expected)
                # The generated inference script works with just its trusted
                # artifact and dependencies, and handles the same missing row.
                (artifact_dir / "one-row.csv").write_bytes(external_csv.read_bytes())
                result = subprocess.run([sys.executable, "inference_example.py"], cwd=artifact_dir, capture_output=True, text=True, check=False)
                self.assertEqual(result.returncode, 0, result.stderr)
                if objective == "classification":
                    self.assertEqual(result.stdout.strip(), str(expected))
                else:
                    self.assertAlmostEqual(float(result.stdout.strip()), float(expected))


if __name__ == "__main__":
    unittest.main()
