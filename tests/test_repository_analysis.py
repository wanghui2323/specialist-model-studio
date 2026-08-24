from __future__ import annotations

import hashlib
import runpy
import subprocess
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from model_harness.model_sources import (
    RemoteSourceFile,
    SourceDocument,
    SourceSnapshot,
    tree_manifest_sha256,
)
from model_harness.repository_analysis import (
    RepositoryAnalysisError,
    StaticRepositoryAnalyzer,
)


COMMIT = "a" * 40


def _snapshot(
    documents: dict[str, str],
    *,
    extra_files: tuple[str, ...] = (),
    license_name: str = "apache-2.0",
    license_status: str = "known",
) -> SourceSnapshot:
    encoded = {path: content.encode("utf-8") for path, content in documents.items()}
    paths = tuple(sorted(set(encoded) | set(extra_files)))
    files = tuple(
        RemoteSourceFile(
            path=path,
            kind="blob",
            mode="100644",
            size_bytes=len(encoded[path]) if path in encoded else 128,
            remote_digest=hashlib.sha1(path.encode("utf-8")).hexdigest(),
        )
        for path in paths
    )
    selected_documents = tuple(
        SourceDocument.from_bytes(path, encoded[path]) for path in sorted(encoded)
    )
    return SourceSnapshot(
        schema_version="0.1",
        snapshot_id="snapshot_fixture",
        task_id="task_fixture",
        resolution_id="resolution_fixture",
        provider="github",
        repository="owner/trainer",
        requested_revision="main",
        resolved_commit=COMMIT,
        license=license_name,
        license_status=license_status,
        files=files,
        documents=selected_documents,
        tree_manifest_sha256=tree_manifest_sha256(files),
        execution_policy="never_execute_in_l1",
        created_at_utc="2026-08-23T00:00:00+00:00",
    )


class StaticRepositoryAnalyzerTests(unittest.TestCase):
    def test_detects_typical_pytorch_transformers_training_repository(self) -> None:
        snapshot = _snapshot(
            {
                "README.md": (
                    "Text classification fine-tuning with load_dataset('json', "
                    "data_files={'train': "
                    "train_file}). Expected columns are text and label."
                ),
                "pyproject.toml": (
                    '[project]\ndependencies = ["torch==2.7", '
                    '"transformers==4.54", "datasets==4.0"]\n'
                ),
                "requirements.txt": "torch==2.7\ntransformers==4.54\n",
                "train.py": (
                    "from transformers import Trainer, TrainingArguments\n"
                    "import torch\n"
                    "model = AutoModel.from_pretrained('org/base-model')\n"
                    "trainer = Trainer(model=model, args=TrainingArguments())\n"
                    "trainer.train()\n"
                    "score = f1_score(labels, predictions, average='macro')\n"
                    "model.save_pretrained('output')\n"
                ),
            },
            extra_files=(
                "inference.py",
                "model.safetensors",
                "legacy/pytorch_model.bin",
            ),
        )

        analysis = StaticRepositoryAnalyzer().analyze(snapshot)

        self.assertEqual(analysis.status, "blocked")
        self.assertEqual(analysis.next_action, "review_repository_risks")
        self.assertEqual(analysis.execution_policy, "static_only_never_execute")
        self.assertEqual(
            {item.name for item in analysis.frameworks},
            {"pytorch", "transformers"},
        )
        self.assertIn(
            ("pyproject.toml", "python-project"),
            {(item.path, item.kind) for item in analysis.dependency_manifests},
        )
        self.assertEqual(analysis.training_entrypoints[0].path, "train.py")
        self.assertGreaterEqual(analysis.training_entrypoints[0].confidence, 0.98)
        self.assertEqual(
            {item.task for item in analysis.task_candidates},
            {"text-classification"},
        )
        self.assertEqual({item.name for item in analysis.metrics}, {"macro-f1"})
        self.assertTrue(
            {"binary-model-weights", "pretrained-model", "safetensors-model"}
            <= {item.name for item in analysis.artifacts}
        )
        text_evidence = [
            ref
            for item in (
                *analysis.frameworks,
                *analysis.data_contract_hints,
                *analysis.metrics,
            )
            for ref in item.evidence_refs
        ]
        text_evidence.extend(
            ref for item in analysis.task_candidates for ref in item.evidence_refs
        )
        self.assertTrue(text_evidence)
        self.assertTrue(all(":L" in ref and "#sha256=" in ref for ref in text_evidence))
        self.assertTrue(
            all(
                ref.startswith("manifest:")
                for item in analysis.dependency_manifests
                for ref in item.evidence_refs
            )
        )
        serialized = analysis.to_dict()
        self.assertEqual(
            serialized["dependency_manifests"][0]["evidence"][0]["kind"],
            "manifest_entry",
        )
        entrypoint_evidence_kinds = {
            item["kind"]
            for item in serialized["training_entrypoints"][0]["evidence"]
        }
        self.assertEqual(
            entrypoint_evidence_kinds,
            {"text_line", "manifest_entry"},
        )
        self.assertEqual(
            serialized["base_model_candidates"][0]["model_id"],
            "org/base-model",
        )
        self.assertEqual(
            serialized["inference_entrypoints"][0]["path"],
            "inference.py",
        )
        self.assertTrue(
            {"huggingface-datasets", "split-files", "text-label-columns"}
            <= {item.name for item in analysis.data_contract_hints}
        )
        self.assertEqual(
            {item.name for item in analysis.weight_formats},
            {"binary-weights", "safetensors"},
        )
        self.assertIn(
            "unsafe_deserialization_format",
            {item.code for item in analysis.risks},
        )
        self.assertEqual(analysis.downstream_blockers, ())

    def test_repository_entrypoint_content_is_never_executed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            sentinel = Path(temporary_directory) / "repository-code-ran"
            source = (
                "from pathlib import Path\n"
                f"Path({str(sentinel)!r}).write_text('executed')\n"
                "raise RuntimeError('repository code must never run')\n"
                "loss.backward()\noptimizer.step()\n"
            )
            snapshot = _snapshot({"train.py": source})
            with (
                patch("builtins.exec", side_effect=AssertionError("exec called")),
                patch("builtins.eval", side_effect=AssertionError("eval called")),
                patch("builtins.compile", side_effect=AssertionError("compile called")),
                patch.object(
                    runpy,
                    "run_path",
                    side_effect=AssertionError("runpy called"),
                ),
                patch.object(
                    subprocess,
                    "run",
                    side_effect=AssertionError("subprocess.run called"),
                ),
                patch.object(
                    subprocess,
                    "Popen",
                    side_effect=AssertionError("subprocess.Popen called"),
                ),
            ):
                analysis = StaticRepositoryAnalyzer().analyze(snapshot)

            self.assertEqual(analysis.status, "complete")
            self.assertEqual(analysis.training_entrypoints[0].path, "train.py")
            self.assertFalse(sentinel.exists())

    def test_readme_launch_example_is_evidence_not_the_training_entrypoint(self) -> None:
        snapshot = _snapshot(
            {
                "README.md": "Run: torchrun scripts/train_custom.py --epochs 2\n",
                "scripts/train_custom.py": "loss.backward()\noptimizer.step()\n",
            }
        )

        analysis = StaticRepositoryAnalyzer().analyze(snapshot)

        self.assertEqual(
            [item.path for item in analysis.training_entrypoints],
            ["scripts/train_custom.py"],
        )
        self.assertNotIn(
            "README.md",
            {item.path for item in analysis.training_entrypoints},
        )

    def test_manifest_only_signals_are_typed_and_do_not_fake_line_numbers(self) -> None:
        snapshot = _snapshot(
            {"README.md": "Static repository metadata only."},
            extra_files=(
                "requirements-gpu.txt",
                "run_glue.py",
                "scripts/bootstrap.sh",
                "weights/model.onnx",
            ),
        )

        analysis = StaticRepositoryAnalyzer().analyze(snapshot)

        self.assertEqual(
            {item.task for item in analysis.task_candidates},
            {"text-classification"},
        )
        manifest_only_refs = [
            *(ref for item in analysis.task_candidates for ref in item.evidence_refs),
            *(
                ref
                for item in analysis.dependency_manifests
                for ref in item.evidence_refs
            ),
            *(
                ref
                for item in analysis.training_entrypoints
                for ref in item.evidence_refs
            ),
            *(ref for item in analysis.weight_formats for ref in item.evidence_refs),
            *(ref for item in analysis.artifacts for ref in item.evidence_refs),
            *(ref for item in analysis.risks for ref in item.evidence_refs),
        ]
        self.assertTrue(manifest_only_refs)
        self.assertTrue(
            all(reference.startswith("manifest:") for reference in manifest_only_refs)
        )
        self.assertTrue(all(":L" not in reference for reference in manifest_only_refs))
        serialized = analysis.to_dict()
        evidence = [
            item
            for collection in (
                serialized["task_candidates"],
                serialized["dependency_manifests"],
                serialized["training_entrypoints"],
                serialized["weight_formats"],
                serialized["artifacts"],
                serialized["risks"],
            )
            for result in collection
            for item in result["evidence"]
        ]
        self.assertTrue(evidence)
        self.assertTrue(all(item["kind"] == "manifest_entry" for item in evidence))

    def test_missing_training_entrypoint_requires_input(self) -> None:
        snapshot = _snapshot(
            {
                "README.md": "Weights and configuration for inference only.",
                "config.json": '{"architectures": ["ExampleModel"]}',
            },
            extra_files=("model.safetensors",),
        )

        analysis = StaticRepositoryAnalyzer().analyze(snapshot)

        self.assertEqual(analysis.status, "needs_input")
        self.assertEqual(analysis.next_action, "map_training_entrypoint")
        self.assertEqual(analysis.training_entrypoints, ())

    def test_unknown_license_is_a_downstream_blocker_not_fake_readiness(self) -> None:
        snapshot = _snapshot(
            {"train.py": "import torch\nloss.backward()\n"},
            license_name="unknown",
            license_status="unknown",
        )

        analysis = StaticRepositoryAnalyzer().analyze(snapshot)

        self.assertEqual(analysis.status, "complete")
        self.assertEqual(analysis.next_action, "resolve_license")
        self.assertEqual(
            [item.code for item in analysis.downstream_blockers],
            ["blocked_license_unknown"],
        )
        self.assertEqual(
            analysis.downstream_blockers[0].stage,
            "before_training_plan_environment_or_execution",
        )

    def test_known_non_allowlisted_license_requires_policy_review(self) -> None:
        snapshot = _snapshot(
            {"train.py": "loss.backward()\n"},
            license_name="openrail",
            license_status="known",
        )

        analysis = StaticRepositoryAnalyzer().analyze(snapshot)

        self.assertEqual(
            [item.code for item in analysis.downstream_blockers],
            ["blocked_license_review"],
        )
        self.assertEqual(analysis.next_action, "resolve_license")

    def test_restricted_license_is_denied_before_plan_or_execution(self) -> None:
        snapshot = _snapshot(
            {"train.py": "loss.backward()\n"},
            license_name="cc-by-nc-4.0",
            license_status="known",
        )

        analysis = StaticRepositoryAnalyzer().analyze(snapshot)

        self.assertEqual(analysis.status, "blocked")
        self.assertEqual(analysis.next_action, "resolve_license")
        self.assertEqual(
            [item.code for item in analysis.downstream_blockers],
            ["blocked_license_denied"],
        )
        self.assertIn("restricted", analysis.downstream_blockers[0].message)

    def test_contract_projection_and_structured_evidence_are_commit_bound(self) -> None:
        snapshot = _snapshot(
            {
                "README.md": "Expected columns are text and label.",
                "requirements.txt": "torch==2.7\n",
                "train.py": (
                    "model = AutoModel.from_pretrained('org/base-model')\n"
                    "loss.backward()\n"
                ),
            },
            extra_files=("predict.py",),
        )

        serialized = StaticRepositoryAnalyzer().analyze(snapshot).to_dict()

        for field in (
            "entrypoints",
            "data_contract_candidates",
            "dependency_files",
            "risk_findings",
            "inference_entrypoints",
            "base_model_candidates",
        ):
            self.assertIn(field, serialized)
        self.assertEqual(
            serialized["entrypoints"][0]["kind"],
            "train",
        )
        self.assertEqual(
            {item["kind"] for item in serialized["entrypoints"]},
            {"train", "inference"},
        )
        self.assertEqual(
            serialized["training_entrypoints"][0]["path"],
            serialized["entrypoints"][0]["path"],
        )
        evidence = [
            evidence_item
            for collection_name in (
                "entrypoints",
                "data_contract_candidates",
                "dependency_files",
                "base_model_candidates",
            )
            for finding in serialized[collection_name]
            for evidence_item in finding["evidence"]
        ]
        self.assertTrue(evidence)
        self.assertTrue(
            all(item["snapshot_id"] == snapshot.snapshot_id for item in evidence)
        )
        self.assertTrue(
            all(item["resolved_commit"] == COMMIT for item in evidence)
        )
        for item in evidence:
            if item["kind"] == "text_line":
                self.assertIn("path", item)
                self.assertIsInstance(item["line"], int)
                self.assertEqual(len(item["document_sha256"]), 64)
            elif item["kind"] == "manifest_entry":
                self.assertIn("path", item["manifest_entry"])
                self.assertEqual(
                    len(item["manifest_entry"]["tree_manifest_sha256"]),
                    64,
                )
            else:
                self.fail(f"unexpected evidence kind: {item['kind']}")

    def test_high_execution_risk_cannot_complete(self) -> None:
        snapshot = _snapshot(
            {
                "train.py": (
                    "loss.backward()\n"
                    "subprocess.run(['echo', 'unsafe'])\n"
                )
            }
        )

        analysis = StaticRepositoryAnalyzer().analyze(snapshot)

        self.assertEqual(analysis.status, "blocked")
        self.assertEqual(analysis.next_action, "review_repository_risks")
        self.assertIn(
            "direct_code_execution",
            {item.code for item in analysis.risks},
        )

    def test_framework_eval_and_documented_download_are_not_execution_risks(
        self,
    ) -> None:
        snapshot = _snapshot(
            {
                "README.md": "Download the public dataset with wget https://example.test/data.zip\n",
                "train.py": (
                    "import torch\n"
                    "model.eval()\n"
                    "loss.backward()\n"
                    "optimizer.step()\n"
                ),
            }
        )

        analysis = StaticRepositoryAnalyzer().analyze(snapshot)
        risks = {(item.code, item.severity) for item in analysis.risks}

        self.assertEqual(analysis.status, "complete")
        self.assertEqual(analysis.next_action, "ready_for_environment_check")
        self.assertNotIn(("direct_code_execution", "high"), risks)
        self.assertNotIn(("network_download_during_run", "high"), risks)
        self.assertIn(("network_download_documentation", "medium"), risks)

    def test_snapshot_manifest_and_selected_text_tampering_fail_closed(self) -> None:
        snapshot = _snapshot({"train.py": "import torch\nloss.backward()\n"})
        with self.subTest("tree-manifest"):
            tampered_manifest = replace(snapshot, tree_manifest_sha256="0" * 64)
            with self.assertRaisesRegex(
                RepositoryAnalysisError,
                "source_snapshot_integrity_failed:tree_manifest_sha256_mismatch",
            ):
                StaticRepositoryAnalyzer().analyze(tampered_manifest)

        with self.subTest("selected-document"):
            tampered_document = snapshot.documents[0]
            object.__setattr__(tampered_document, "content", b"changed after snapshot")
            with self.assertRaisesRegex(
                RepositoryAnalysisError,
                "source_snapshot_integrity_failed:document_",
            ):
                StaticRepositoryAnalyzer().analyze(snapshot)


if __name__ == "__main__":
    unittest.main()
