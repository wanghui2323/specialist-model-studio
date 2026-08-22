from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GATES_PATH = ROOT / "acceptance" / "v0.7-gates.json"
SCHEMA_PATH = ROOT / "acceptance" / "report.schema.json"
EXTERNAL_SCHEMA_PATH = ROOT / "acceptance" / "external-evidence.schema.json"
SCRIPT_PATH = ROOT / "scripts" / "verify_v07_beta.py"


def load_script():
    specification = importlib.util.spec_from_file_location(
        "verify_v07_beta",
        SCRIPT_PATH,
    )
    if specification is None or specification.loader is None:
        raise RuntimeError("cannot import verify_v07_beta.py")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


class AcceptanceContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.gates = json.loads(GATES_PATH.read_text(encoding="utf-8"))
        cls.schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        cls.external_schema = json.loads(
            EXTERNAL_SCHEMA_PATH.read_text(encoding="utf-8")
        )
        cls.runner = load_script()

    def test_gate_contract_contains_unique_required_L0_to_L5_gates(self) -> None:
        levels = self.gates["levels"]
        self.assertEqual(
            [item["level_id"] for item in levels],
            ["L0", "L1", "L2", "L3", "L4", "L5"],
        )
        gate_ids = [
            gate["gate_id"] for level in levels for gate in level["gates"]
        ]
        self.assertEqual(len(gate_ids), len(set(gate_ids)))
        local_optional = [
            gate
            for level in levels
            for gate in level["gates"]
            if not gate["required"]
        ]
        self.assertEqual(
            [gate["gate_id"] for gate in local_optional],
            ["L5-release-chain"],
        )
        self.assertTrue(local_optional[0]["required_for_github_release"])
        self.assertTrue(
            all(
                gate["required"]
                for level in levels
                for gate in level["gates"]
                if gate["gate_id"] != "L5-release-chain"
            )
        )
        for level in levels:
            self.assertTrue(level["gates"])
            self.assertTrue(
                all(
                    gate["gate_id"].startswith(f"{level['level_id']}-")
                    for gate in level["gates"]
                )
            )

    def test_schema_and_config_forbid_skipped_status(self) -> None:
        self.assertEqual(
            set(self.gates["allowed_gate_statuses"]),
            {"passed", "failed", "blocked"},
        )
        status_enum = self.schema["$defs"]["status"]["enum"]
        self.assertEqual(set(status_enum), {"passed", "failed", "blocked"})
        self.assertNotIn("skipped", status_enum)
        self.assertNotIn(
            "skipped",
            json.dumps(self.external_schema, ensure_ascii=False),
        )

    def test_official_hf_live_scenario_is_commit_pinned_and_allowlisted(self) -> None:
        scenario = self.gates["live_scenarios"][
            "official_huggingface_fixed_commit"
        ]
        self.assertEqual(scenario["client"], "official_huggingface_hub")
        self.assertRegex(scenario["commit"], r"^[0-9a-f]{40}$")
        self.assertNotIn(scenario["commit"], {"main", "master", "latest"})
        self.assertTrue(scenario["moving_revision_forbidden"])
        self.assertEqual(
            scenario["runner_script"],
            "scripts/run_hf_real_scenario.py",
        )
        self.assertEqual(scenario["repo_id"], "pyronear/mobilenet_v3_small")
        self.assertEqual(scenario["dataset_total_images"], 100)
        self.assertGreaterEqual(scenario["minimum_test_samples"], 20)
        self.assertEqual(
            set(scenario["required_outputs"]),
            {"evaluation_report", "new_sample_inference", "artifact_bundle", "restart"},
        )
        scenario_source = (ROOT / scenario["runner_script"]).read_text(
            encoding="utf-8"
        )
        self.assertIn(f'DEFAULT_REPO = "{scenario["repo_id"]}"', scenario_source)
        self.assertIn(f'DEFAULT_COMMIT = "{scenario["commit"]}"', scenario_source)

    def test_browser_producer_uses_real_visibility_and_fixed_playwright(self) -> None:
        browser_source = (
            ROOT / "acceptance" / "browser" / "collect-browser.mjs"
        ).read_text(encoding="utf-8")
        browser_package = json.loads(
            (ROOT / "acceptance" / "browser" / "package.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(
            browser_package["dependencies"]["playwright-core"],
            "1.62.1",
        )
        self.assertIn(".isVisible()", browser_source)
        self.assertIn("const endUrl = page.url()", browser_source)
        self.assertNotIn(
            "!document.querySelector('[data-context-panel=\"capability\"]')?.hidden",
            browser_source,
        )

    def test_local_beta_and_github_release_are_separate_fail_closed_states(self) -> None:
        levels = self.runner.instantiate_levels(self.gates)
        for level in levels:
            for gate in level["gates"]:
                if gate["required"]:
                    self.runner.set_gate(
                        levels,
                        gate["gate_id"],
                        "passed",
                        "local fixture passed",
                    )
        local_only = self.runner.summarize_levels(
            levels,
            github_released=self.runner.github_release_gate_passed(levels),
        )
        self.assertTrue(local_only["local_beta_verified"])
        self.assertFalse(local_only["github_released"])
        self.assertEqual(local_only["release_state"], "local_beta_verified")

        self.runner.set_gate(
            levels,
            "L5-release-chain",
            "passed",
            "release fixture passed",
        )
        released = self.runner.summarize_levels(
            levels,
            github_released=self.runner.github_release_gate_passed(levels),
        )
        self.assertTrue(released["local_beta_verified"])
        self.assertTrue(released["github_released"])
        self.assertEqual(released["release_state"], "github_released")

    def test_blocked_or_failed_required_gate_prevents_local_beta_pass(self) -> None:
        levels = self.runner.instantiate_levels(self.gates)
        initial = self.runner.summarize_levels(levels)
        self.assertFalse(initial["local_beta_verified"])
        self.assertEqual(
            initial["required_gate_counts"]["blocked"],
            initial["required_gate_counts"]["total"],
        )

        for level in levels:
            for gate in level["gates"]:
                self.runner.set_gate(
                    levels,
                    gate["gate_id"],
                    "passed",
                    "fixture evidence passed",
                )
        passed = self.runner.summarize_levels(levels)
        self.assertTrue(passed["local_beta_verified"])
        self.assertFalse(passed["github_released"])
        self.assertEqual(passed["release_state"], "local_beta_verified")

        self.runner.set_gate(
            levels,
            "L3-task-contract-lineage",
            "blocked",
            "product integration missing",
            blockers=["l3_product_integration_missing"],
        )
        blocked = self.runner.summarize_levels(levels)
        self.assertFalse(blocked["local_beta_verified"])
        self.assertIn("L3-task-contract-lineage", blocked["blocking_gate_ids"])

        self.runner.set_gate(
            levels,
            "L3-task-contract-lineage",
            "failed",
            "lineage assertion failed",
            blockers=["lineage_assertion_failed"],
        )
        failed = self.runner.summarize_levels(levels)
        self.assertFalse(failed["local_beta_verified"])
        self.assertIn("L3-task-contract-lineage", failed["failed_gate_ids"])

    def test_illegal_skipped_status_cannot_be_aggregated(self) -> None:
        levels = self.runner.instantiate_levels(self.gates)
        levels[0]["gates"][0]["status"] = "skipped"
        with self.assertRaisesRegex(ValueError, "invalid required gate status"):
            self.runner.summarize_levels(levels)

    def test_preexisting_external_evidence_without_fresh_challenge_is_rejected(self) -> None:
        source_commit = "a" * 40
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "external.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": "0.2",
                        "source_commit": source_commit,
                        "generated_at_utc": "2026-08-22T00:00:00+00:00",
                    }
                ),
                encoding="utf-8",
            )
            evidence, blockers = self.runner._read_external_evidence(
                path,
                source_commit=source_commit,
                expected_challenge=None,
                expected_command=None,
            )
            self.assertIsNone(evidence)
            self.assertIn("external_evidence_not_challenge_bound", blockers)
            browser = self.runner.probe_browser_evidence(
                evidence,
                blockers,
                width=1440,
                height=900,
            )
            self.assertEqual(browser[0], "failed")
            self.assertIn("external_evidence_not_challenge_bound", browser[2])

    def test_hand_authored_process_restart_dictionary_cannot_pass(self) -> None:
        hand_authored = {
            "process_restart": {
                "before_pid": 100,
                "after_pid": 101,
            }
        }
        failed = self.runner.probe_process_restart_evidence(
            hand_authored,
            [],
        )
        self.assertEqual(failed[0], "failed")
        self.assertIn("controlled_evidence_object_required", failed[2])

    def test_hf_real_report_requires_training_evaluation_inference_and_bundle(self) -> None:
        contract = self.gates["live_scenarios"][
            "official_huggingface_fixed_commit"
        ]
        sha = "d" * 64
        report = {
            "status": "passed",
            "scenario": "official_huggingface_commit_pinned_image_training",
            "scenario_evidence": {
                "repository": contract["repo_id"],
                "requested_commit": contract["commit"],
                "resolved_commit": contract["commit"],
                "license": "apache-2.0",
                "asset_id": "asset-fixture",
                "asset_manifest_sha256": sha,
                "asset_files": [
                    {"path": "model.onnx", "size_bytes": 10, "sha256": sha}
                ],
                "dataset": {
                    "dataset_id": "dataset-fixture",
                    "fingerprint_sha256": sha,
                    "total_images": 100,
                    "class_count": 2,
                },
                "task_id": "task-fixture",
                "run_id": "run-fixture",
                "run": {
                    "status": "completed",
                    "release_ready": True,
                    "total_duration_ms": 1.0,
                    "feature_source": "huggingface_onnx_plus_rgb_gradient_v1",
                },
                "evaluation": {
                    "report_id": "evaluation-fixture",
                    "conclusion": "release_ready",
                    "test_sample_count": 20,
                },
                "new_sample_inference": {
                    "check_id": "sample-fixture",
                    "status": "passed",
                    "sample_sha256": sha,
                },
                "artifact_bundle": {
                    "bundle_id": "bundle-fixture",
                    "sha256": sha,
                    "download_sha256": sha,
                    "privacy_boundary": {"raw_data_included": False},
                },
                "run_manifest_sha256": sha,
            },
            "restart": {"passed": True, "assertions": {"same_task_id": True}},
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            scenario_dir = root / "scenario"
            scenario_dir.mkdir()
            report_path = scenario_dir / "report.json"
            report_path.write_text(json.dumps(report), encoding="utf-8")
            passed = self.runner.probe_huggingface_real_report(
                root,
                "passed",
                contract,
            )
            self.assertEqual(passed[0], "passed")

            report["scenario_evidence"]["resolved_commit"] = "e" * 40
            report_path.write_text(json.dumps(report), encoding="utf-8")
            failed = self.runner.probe_huggingface_real_report(
                root,
                "passed",
                contract,
            )
            self.assertEqual(failed[0], "failed")
            self.assertFalse(failed[1]["assertions"]["resolved_commit_matches"])

    def test_report_shape_rejects_derived_status_or_gate_drift(self) -> None:
        levels = self.runner.instantiate_levels(self.gates)
        report = {
            "schema_version": "0.1",
            "acceptance_id": "acceptance-20260822T000000Z-deadbeef",
            "iteration": "v0.7-local-usable-beta",
            "started_at_utc": "2026-08-22T00:00:00+00:00",
            "finished_at_utc": "2026-08-22T00:01:00+00:00",
            "source": {
                "git_commit": None,
                "git_branch": None,
                "worktree_clean": False,
                "versions": {
                    "pyproject": None,
                    "server": None,
                    "python_package": None,
                    "node_adapter": None,
                    "normalized": {},
                },
            },
            "isolation": {
                "temporary_runtime_created": True,
                "project_runs_reused": False,
                "runtime_path_persisted": False,
            },
            "external_evidence": {
                "status": "not_collected",
                "path": "runs/acceptance/fixture/controlled-external-evidence/external-evidence.json",
                "sha256": None,
                "producer_id": None,
                "producer_version": None,
                "producer_run_id": None,
                "source_commit": None,
                "command_id": "controlled_external_evidence",
                "blockers": ["controlled_external_evidence_not_collected"],
            },
            "commands": {},
            "levels": levels,
            "summary": self.runner.summarize_levels(levels),
        }
        self.runner.validate_report_shape(report, self.gates)

        wrong_status = deepcopy(report)
        wrong_status["levels"][0]["status"] = "passed"
        with self.assertRaisesRegex(ValueError, "level status"):
            self.runner.validate_report_shape(wrong_status, self.gates)

        missing_gate = deepcopy(report)
        missing_gate["levels"][0]["gates"].pop()
        with self.assertRaisesRegex(ValueError, "gates do not match"):
            self.runner.validate_report_shape(missing_gate, self.gates)

        weakened_gate = deepcopy(report)
        weakened_gate["levels"][0]["gates"][0]["required"] = False
        weakened_gate["summary"] = self.runner.summarize_levels(
            weakened_gate["levels"]
        )
        with self.assertRaisesRegex(ValueError, "required flags"):
            self.runner.validate_report_shape(weakened_gate, self.gates)

        weakened_release_gate = deepcopy(report)
        release_gate = next(
            gate
            for level in weakened_release_gate["levels"]
            for gate in level["gates"]
            if gate["gate_id"] == "L5-release-chain"
        )
        release_gate["required_for_github_release"] = False
        with self.assertRaisesRegex(ValueError, "GitHub release flags"):
            self.runner.validate_report_shape(weakened_release_gate, self.gates)

    def test_python_and_semver_beta_versions_normalize_identically(self) -> None:
        self.assertEqual(
            self.runner.normalize_version("0.7.0b1"),
            "0.7.0-beta.1",
        )
        self.assertEqual(
            self.runner.normalize_version("0.7.0-beta.1"),
            "0.7.0-beta.1",
        )


if __name__ == "__main__":
    unittest.main()
