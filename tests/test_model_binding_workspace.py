from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from model_harness.errors import ContractError, HarnessError
from model_harness.io_utils import read_json, write_json
from model_harness.model_sources import (
    ModelSourceIncompleteError,
    ModelSourceUpstreamError,
    RemoteSourceFile,
    ResolvedSource,
    SourceDocument,
    source_candidate_id,
)
from model_harness.server import create_app


COMMIT_A = "a" * 40
COMMIT_B = "b" * 40


class FakeProvider:
    """Fully offline provider used to prove the two-step approval boundary."""

    def __init__(
        self,
        provider_id: str,
        *,
        fail_on: str | None = None,
        license_name: str = "apache-2.0",
        license_status: str = "known",
    ) -> None:
        self.provider_id = provider_id
        self.fail_on = fail_on
        self.license_name = license_name
        self.license_status = license_status
        self.calls: list[tuple[str, str | None]] = []
        self.contents = {
            "README.md": b"# Offline fixture\n\nTrain with python train.py.\n",
            "pyproject.toml": b'[project]\ndependencies=["torch", "transformers"]\n',
            "train.py": (
                b"import torch\nfrom transformers import Trainer\n"
                b"trainer = Trainer(model=model)\ntrainer.train()\n"
            ),
        }

    def resolve(
        self,
        repository: str,
        requested_revision: str | None,
        *,
        token: str | None = None,
    ) -> ResolvedSource:
        self.calls.append(("resolve", token))
        if self.fail_on == "resolve":
            raise ModelSourceUpstreamError("fixture_provider_unavailable")
        selected_revision = requested_revision or "main"
        commit = {
            "r1": COMMIT_A,
            "r2": COMMIT_B,
            "main": COMMIT_A,
            COMMIT_A: COMMIT_A,
            COMMIT_B: COMMIT_B,
        }.get(selected_revision, COMMIT_A)
        return ResolvedSource(
            provider=self.provider_id,
            repository=repository,
            requested_revision=selected_revision,
            resolved_commit=commit,
            license=self.license_name,
            license_status=self.license_status,
            tree_reference="c" * 40,
            metadata={"visibility": "public"},
        )

    def search(
        self,
        query: str,
        *,
        limit: int = 6,
        pipeline_tag: str | None = None,
        token: str | None = None,
    ) -> tuple[dict, ...]:
        del query, limit, pipeline_tag
        self.calls.append(("search", token))
        repository = (
            "fixture-org/offline-model"
            if self.provider_id == "huggingface"
            else "fixture-org/offline-trainer"
        )
        requested_revision = COMMIT_A if self.provider_id == "huggingface" else "main"
        return (
            {
                "candidate_id": source_candidate_id(
                    self.provider_id, repository, requested_revision
                ),
                "provider": self.provider_id,
                "repository": repository,
                "source_uri": (
                    f"https://huggingface.co/{repository}"
                    if self.provider_id == "huggingface"
                    else f"https://github.com/{repository}"
                ),
                "requested_revision": requested_revision,
                "resolved_commit": COMMIT_A if self.provider_id == "huggingface" else None,
                "license": self.license_name,
                "license_status": self.license_status,
                "description": "offline candidate",
                "task_tag": "text-classification",
                "popularity": {"downloads": 12, "stars": 3},
                "repository_size_bytes": 4096,
                "catalog_evidence": f"{self.provider_id}_official_api_fixture",
            },
        )

    def list_tree(
        self,
        source: ResolvedSource,
        *,
        token: str | None = None,
    ) -> tuple[RemoteSourceFile, ...]:
        self.calls.append(("list_tree", token))
        if self.fail_on == "tree":
            raise ModelSourceIncompleteError("source_tree_truncated")
        return tuple(
            RemoteSourceFile(
                path=path,
                kind="blob",
                mode="100644",
                size_bytes=len(content),
                remote_digest=hashlib.sha1(path.encode("utf-8")).hexdigest(),
            )
            for path, content in sorted(self.contents.items())
        )

    def read_document(
        self,
        source: ResolvedSource,
        file: RemoteSourceFile,
        *,
        token: str | None = None,
    ) -> SourceDocument:
        self.calls.append(("read_document", token))
        if self.fail_on == "document":
            raise ModelSourceIncompleteError("source_document_truncated")
        return SourceDocument.from_bytes(file.path, self.contents[file.path])

    def count(self, operation: str) -> int:
        return sum(name == operation for name, _token in self.calls)


def disk_bytes(root: Path) -> bytes:
    value = bytearray()
    for path in sorted(root.rglob("*")):
        if path.is_file() and not path.is_symlink():
            value.extend(path.read_bytes())
    return bytes(value)


class ModelBindingWorkspaceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.runs_dir = Path(self.temporary.name) / "runs"
        self.app = create_app(self.runs_dir)
        self.workspace = self.app.state.training_workspace
        self.github = FakeProvider("github")
        self.huggingface = FakeProvider("huggingface")
        self.workspace.model_source_providers = {
            "github": self.github,
            "huggingface": self.huggingface,
        }
        task = self.workspace.create_task(
            "Offline BYOM",
            "用文本和标签训练一个本地分类模型",
            {
                "modality": "text",
                "objective": "classification",
                "target_kind": "multiclass",
            },
        )
        self.task_id = task["task_id"]

    def tearDown(self) -> None:
        self.app.state.run_service.close()
        self.temporary.cleanup()

    def resolve(
        self,
        revision: str,
        *,
        token: str = "github_ephemeral_token",
    ) -> dict:
        return self.workspace.create_model_source_resolution(
            self.task_id,
            provider="github",
            repository="fixture-org/offline-trainer",
            requested_revision=revision,
            base_spec_revision=self.workspace.get_task(self.task_id)[
                "current_spec_revision"
            ],
            token=token,
        )

    def bind(
        self,
        resolution_id: str,
        commit: str,
        *,
        approved: bool = True,
        base_spec_revision: int | None = None,
        token: str = "github_ephemeral_token",
    ) -> dict:
        return self.workspace.bind_model_source(
            self.task_id,
            resolution_id,
            approval_confirmed=approved,
            expected_resolved_commit=commit,
            base_spec_revision=(
                base_spec_revision
                if base_spec_revision is not None
                else self.workspace.get_task(self.task_id)["current_spec_revision"]
            ),
            token=token,
        )

    def test_resolution_does_not_read_tree_and_binding_requires_three_checks(self) -> None:
        secret = "github_secret_never_persist"
        resolution_result = self.resolve("r1", token=secret)
        resolution = resolution_result["resolution"]
        self.assertEqual(resolution["task_id"], self.task_id)
        self.assertEqual(resolution["resolved_commit"], COMMIT_A)
        self.assertEqual(self.github.count("resolve"), 1)
        self.assertEqual(self.github.count("list_tree"), 0)
        self.assertEqual(self.github.count("read_document"), 0)

        cases = (
            {
                "approved": False,
                "commit": COMMIT_A,
                "base": 1,
            },
            {
                "approved": True,
                "commit": COMMIT_B,
                "base": 1,
            },
            {
                "approved": True,
                "commit": COMMIT_A,
                "base": 99,
            },
        )
        for case in cases:
            with self.subTest(case=case), self.assertRaises(
                (ContractError, HarnessError)
            ):
                self.bind(
                    resolution["resolution_id"],
                    case["commit"],
                    approved=case["approved"],
                    base_spec_revision=case["base"],
                    token=secret,
                )
            self.assertEqual(self.workspace.list_model_bindings(self.task_id), [])
            self.assertIsNone(self.workspace.current_model_binding(self.task_id))
            self.assertEqual(self.github.count("list_tree"), 0)
            self.assertEqual(self.github.count("read_document"), 0)

        bound = self.bind(
            resolution["resolution_id"],
            COMMIT_A,
            token=secret,
        )
        self.assertEqual(bound["task"]["task_id"], self.task_id)
        self.assertEqual(bound["binding"]["revision"], 1)
        self.assertEqual(bound["binding"]["resolution_id"], resolution["resolution_id"])
        self.assertEqual(bound["analysis"]["task_id"], self.task_id)
        self.assertEqual(self.github.count("list_tree"), 1)
        self.assertGreater(self.github.count("read_document"), 0)
        self.assertIn(("resolve", secret), self.github.calls)
        self.assertIn(("list_tree", secret), self.github.calls)
        self.assertNotIn(secret.encode("utf-8"), disk_bytes(self.workspace.root))

    def test_rebinding_preserves_data_and_run_history_but_invalidates_current_result(self) -> None:
        first_resolution = self.resolve("r1")["resolution"]
        first = self.bind(first_resolution["resolution_id"], COMMIT_A)

        task_path = self.workspace.root / "tasks" / self.task_id / "task.json"
        stored = read_json(task_path)
        stored.update(
            {
                "dataset_id": "dataset-existing",
                "dataset_history": ["dataset-existing", "dataset-prior"],
                "run_ids": ["run-prior", "run-current"],
                "last_run_id": "run-prior",
                "current_run_id": "run-current",
                "contract_confirmed": True,
                "confirmations": {
                    "data_authorized": True,
                    "labels_reviewed": True,
                    "gates_reviewed": True,
                },
                "confirmed_contract_sha256": "d" * 64,
                "status": "completed",
            }
        )
        write_json(task_path, stored)
        previous_result = {
            "run_id": "run-current",
            "task_id": self.task_id,
            "status": "completed",
            "metrics": {"accuracy": 0.9},
        }
        with patch.object(self.workspace.runs, "result", return_value=previous_result):
            self.assertEqual(
                self.workspace.get_task(self.task_id)["current_result"]["run_id"],
                "run-current",
            )
            second_resolution = self.resolve("r2")["resolution"]
            rebound = self.bind(second_resolution["resolution_id"], COMMIT_B)

        task = rebound["task"]
        self.assertEqual(task["task_id"], self.task_id)
        self.assertEqual(task["dataset_id"], "dataset-existing")
        self.assertEqual(
            task["dataset_history"], ["dataset-existing", "dataset-prior"]
        )
        self.assertEqual(task["run_ids"], ["run-prior", "run-current"])
        self.assertEqual(task["last_run_id"], "run-current")
        self.assertIsNone(task["current_run_id"])
        self.assertIsNone(task["current_result"])
        self.assertFalse(task["contract_confirmed"])
        self.assertEqual(task["confirmations"], {})
        self.assertIsNone(task["confirmed_contract_sha256"])

        bindings = self.workspace.list_model_bindings(self.task_id)
        self.assertEqual([item["revision"] for item in bindings], [1, 2])
        self.assertEqual(
            bindings[1]["supersedes_revision"],
            first["binding"]["revision"],
        )
        current = self.workspace.current_model_binding(self.task_id)
        self.assertEqual(current["binding_revision_id"], bindings[1]["binding_revision_id"])
        self.assertEqual(current["resolution_id"], second_resolution["resolution_id"])

    def test_task_spec_revision_marks_binding_stale_and_restart_preserves_lineage(self) -> None:
        resolution = self.resolve("r1")["resolution"]
        bound = self.bind(resolution["resolution_id"], COMMIT_A)
        binding_id = bound["binding"]["binding_revision_id"]
        revised = self.workspace.update_task_spec(
            self.task_id,
            {
                "base_revision": 1,
                "business_goal": "用新的标签定义训练同一个文本分类任务",
            },
        )
        self.assertEqual(revised["current_spec_revision"], 2)

        stale = self.workspace.current_model_binding(self.task_id)
        self.assertEqual(stale["binding_revision_id"], binding_id)
        self.assertEqual(stale["status"], "stale")
        self.assertEqual(stale["bound_spec_revision"], 1)
        self.assertEqual(stale["current_spec_revision"], 2)

        self.app.state.run_service.close()
        restarted_app = create_app(self.runs_dir)
        self.app = restarted_app
        restarted = restarted_app.state.training_workspace
        restarted.model_source_providers = {
            "github": FakeProvider("github"),
            "huggingface": FakeProvider("huggingface"),
        }
        recovered = restarted.current_model_binding(self.task_id)
        self.assertEqual(recovered["binding_revision_id"], binding_id)
        self.assertEqual(recovered["status"], "stale")
        self.assertEqual(
            [item["resolution_id"] for item in restarted.list_model_source_resolutions(self.task_id)],
            [resolution["resolution_id"]],
        )
        analysis = restarted.get_repository_analysis(
            self.task_id,
            bound["analysis"]["analysis_id"],
        )
        self.assertEqual(analysis["analysis_id"], bound["analysis"]["analysis_id"])


if __name__ == "__main__":
    unittest.main()
