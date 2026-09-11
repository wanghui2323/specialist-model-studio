from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from model_harness.errors import ContractError
from model_harness.io_utils import read_json, write_json
from model_harness.model_source_store import (
    ModelSourceIntegrityError,
    ModelSourceStore,
    StaleBindingIntentError,
    StaleTaskSpecRevisionError,
    content_digest,
)
from model_harness.model_sources import RemoteSourceFile, SourceDocument, source_candidate_id
from model_harness.repository_analysis import RepositoryAnalysis


COMMIT_A = "a" * 40
COMMIT_B = "b" * 40
README_TEXT = "# Fixture model\n\nTrain with `python train.py`.\n"
README_SHA256 = hashlib.sha256(README_TEXT.encode("utf-8")).hexdigest()


def _disk_bytes(root: Path) -> bytes:
    payload = bytearray()
    for path in sorted(root.rglob("*")):
        if path.is_file() and not path.is_symlink():
            payload.extend(path.read_bytes())
    return bytes(payload)


class ModelSourceStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "workspace"
        self.task_id = "task-source-a"
        self._create_task(self.task_id)
        self.store = ModelSourceStore(self.root)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _create_task(self, task_id: str) -> None:
        write_json(
            self.root / "tasks" / task_id / "task.json",
            {"schema_version": "0.2", "task_id": task_id, "name": task_id},
        )

    def _resolution(
        self,
        *,
        provider: str = "huggingface",
        commit: str = COMMIT_A,
        token: str | None = None,
    ) -> dict:
        repository = (
            "fixture/tiny-model"
            if provider == "huggingface"
            else "fixture-org/tiny-trainer"
        )
        return self.store.create_resolution(
            self.task_id,
            provider=provider,
            repository=repository,
            requested_revision=commit,
            resolved_commit=commit,
            source_uri=(
                f"https://huggingface.co/{repository}"
                if provider == "huggingface"
                else f"https://github.com/{repository}"
            ),
            details={"visibility": "public", "default_branch": "main"},
            auth_token=token,
        )

    def _snapshot(self, resolution: dict) -> dict:
        return self.store.create_snapshot(
            self.task_id,
            resolution_id=resolution["resolution_id"],
            license="apache-2.0",
            license_status="known",
            files=[
                RemoteSourceFile(
                    path="README.md",
                    kind="blob",
                    mode="100644",
                    size_bytes=len(README_TEXT.encode("utf-8")),
                    remote_digest="1" * 40,
                ),
                RemoteSourceFile(
                    path="train.py",
                    kind="blob",
                    mode="100644",
                    size_bytes=123,
                    remote_digest="2" * 40,
                ),
            ],
            documents=[SourceDocument.from_bytes("README.md", README_TEXT.encode())],
            details={"lfs_complete": True, "submodules_complete": True},
        )

    def _analysis(self, snapshot: dict) -> dict:
        analysis = RepositoryAnalysis(
            analysis_id=f"analysis_{snapshot['semantic_digest'][:20]}",
            task_id=self.task_id,
            source_snapshot_id=snapshot["snapshot_id"],
            resolved_commit=snapshot["resolved_commit"],
            analyzer_version="repository-analysis/test",
            status="complete",
            next_action="build_training_plan",
            execution_policy="static_only_never_execute",
            license=snapshot["license"],
            license_status=snapshot["license_status"],
            frameworks=(),
            dependency_manifests=(),
            training_entrypoints=(),
            data_contract_hints=(),
            weight_formats=(),
            risks=(),
            downstream_blockers=(),
        )
        return self.store.create_analysis(
            self.task_id,
            snapshot_id=snapshot["snapshot_id"],
            analysis=analysis,
        )

    def _chain(self) -> tuple[dict, dict, dict]:
        resolution = self._resolution()
        snapshot = self._snapshot(resolution)
        analysis = self._analysis(snapshot)
        return resolution, snapshot, analysis

    def test_official_search_record_is_immutable_restart_safe_and_token_free(self) -> None:
        token = "catalog_secret_never_persist"
        candidate_id = source_candidate_id("github", "fixture-org/trainer", "main")
        search = self.store.create_search_record(
            self.task_id,
            base_spec_revision=1,
            query_plan={"user_query": "trainer", "effective_query": "trainer"},
            providers=["github"],
            candidates=[
                {
                    "candidate_id": candidate_id,
                    "provider": "github",
                    "repository": "fixture-org/trainer",
                    "source_uri": "https://github.com/fixture-org/trainer",
                    "requested_revision": "main",
                    "resolved_commit": None,
                    "license": "MIT",
                    "license_status": "known",
                    "catalog_evidence": "github_official_search_api",
                }
            ],
            auth_tokens=[token],
        )
        restarted = ModelSourceStore(self.root)
        self.assertEqual(
            restarted.get_search_record(self.task_id, search["search_id"]), search
        )
        self.assertNotIn(token.encode(), _disk_bytes(self.root))
        path = (
            self.root
            / "tasks"
            / self.task_id
            / "model_sources"
            / "searches"
            / f"{search['search_id']}.json"
        )
        value = read_json(path)
        value["candidates"][0]["repository"] = "fixture-org/forged"
        write_json(path, value)
        with self.assertRaises(ModelSourceIntegrityError):
            restarted.get_search_record(self.task_id, search["search_id"])

    def test_search_record_rejects_secret_query_without_writing_it(self) -> None:
        cases = (
            (
                "store_url_secret_never_persist",
                "https://github.com/fixture/model?token=store_url_secret_never_persist",
            ),
            (
                "github_pat_" + "C" * 40,
                "vision model github_pat_" + "C" * 40,
            ),
        )

        for secret, query in cases:
            with self.subTest(secret_prefix=secret[:12]), self.assertRaises(
                ContractError
            ) as raised:
                self.store.create_search_record(
                    self.task_id,
                    base_spec_revision=1,
                    query_plan={"user_query": query, "effective_query": query},
                    providers=["github"],
                    candidates=[],
                )
            self.assertNotIn(secret, str(raised.exception))

        self.assertEqual(self.store.list_search_records(self.task_id), [])
        disk = _disk_bytes(self.root)
        for secret, _query in cases:
            self.assertNotIn(secret.encode("utf-8"), disk)

    def test_full_binding_lifecycle_is_idempotent_and_survives_restart(self) -> None:
        token = "hf_secret_never_persist_this"
        resolution = self._resolution(token=token)
        snapshot = self._snapshot(resolution)
        analysis = self._analysis(snapshot)
        intent = self.store.prepare_binding_intent(
            self.task_id,
            snapshot_id=snapshot["snapshot_id"],
            analysis_id=analysis["analysis_id"],
            idempotency_key="user-selected-fixture-v1",
            base_spec_revision=1,
        )
        duplicate = self.store.prepare_binding_intent(
            self.task_id,
            snapshot_id=snapshot["snapshot_id"],
            analysis_id=analysis["analysis_id"],
            idempotency_key="user-selected-fixture-v1",
            base_spec_revision=1,
        )
        self.assertEqual(intent, duplicate)
        self.assertEqual(
            self.store.get_binding_intent(self.task_id, intent["intent_id"])[
                "status"
            ],
            "prepared",
        )

        binding = self.store.commit_binding_intent(
            self.task_id,
            intent["intent_id"],
            expected_intent_digest=intent["content_digest"],
            current_spec_revision=1,
        )
        self.assertEqual(binding["task_id"], self.task_id)
        self.assertEqual(binding["snapshot_id"], snapshot["snapshot_id"])
        self.assertEqual(binding["analysis_id"], analysis["analysis_id"])
        self.assertEqual(binding["revision"], 1)
        self.assertEqual(binding["base_spec_revision"], 1)
        intent_state = self.store.get_binding_intent(
            self.task_id, intent["intent_id"]
        )
        self.assertEqual(intent_state["intent"]["base_spec_revision"], 1)
        self.assertEqual(
            intent_state["commit_request"]["base_spec_revision"], 1
        )
        self.assertEqual(
            intent_state["commit_receipt"]["base_spec_revision"], 1
        )
        self.assertEqual(
            self.store.get_binding_intent(self.task_id, intent["intent_id"])[
                "status"
            ],
            "committed",
        )
        self.assertEqual(
            self.store.commit_binding_intent(
                self.task_id,
                intent["intent_id"],
                expected_intent_digest=intent["content_digest"],
                current_spec_revision=1,
            ),
            binding,
        )

        restarted = ModelSourceStore(self.root)
        current = restarted.current_binding(self.task_id)
        self.assertEqual(current, binding)
        self.assertEqual(
            restarted.get_snapshot(self.task_id, current["snapshot_id"]), snapshot
        )
        self.assertEqual(
            restarted.get_analysis(self.task_id, current["analysis_id"]), analysis
        )
        self.assertEqual(
            restarted.get_resolution(self.task_id, snapshot["resolution_id"]),
            resolution,
        )
        context = restarted.binding_context(self.task_id)
        self.assertIsNotNone(context)
        assert context is not None
        self.assertEqual(context["binding"], binding)
        self.assertEqual(context["snapshot"], snapshot)
        self.assertEqual(context["analysis"], analysis)
        self.assertEqual(context["source_snapshot"].snapshot_id, snapshot["snapshot_id"])
        self.assertNotIn(token.encode(), _disk_bytes(self.root))

    def test_both_providers_and_resolution_versions_preserve_source_facts(self) -> None:
        first = self._resolution(provider="github", commit=COMMIT_A)
        duplicate = self._resolution(provider="github", commit=COMMIT_A)
        second = self._resolution(provider="github", commit=COMMIT_B)
        self.assertEqual(first, duplicate)
        self.assertEqual(first["revision"], 1)
        self.assertEqual(second["revision"], 2)
        self.assertEqual(second["provider"], "github")
        self.assertEqual(second["repository"], "fixture-org/tiny-trainer")
        self.assertEqual(second["requested_revision"], COMMIT_B)
        self.assertEqual(second["resolved_commit"], COMMIT_B)
        self.assertEqual(
            [item["resolution_id"] for item in self.store.list_resolutions(self.task_id)],
            [first["resolution_id"], second["resolution_id"]],
        )

    def test_snapshot_preserves_remote_files_and_bounded_source_documents(self) -> None:
        resolution = self._resolution(provider="github")
        snapshot = self._snapshot(resolution)
        self.assertEqual(snapshot["provider"], resolution["provider"])
        self.assertEqual(snapshot["repository"], resolution["repository"])
        self.assertEqual(
            snapshot["requested_revision"], resolution["requested_revision"]
        )
        self.assertEqual(snapshot["resolved_commit"], resolution["resolved_commit"])
        self.assertEqual(snapshot["files"][0]["path"], "README.md")
        domain = self.store.load_source_snapshot(
            self.task_id, snapshot["snapshot_id"]
        )
        self.assertEqual(domain.repository, resolution["repository"])
        self.assertEqual(domain.files[0].path, "README.md")
        self.assertEqual(domain.documents[0].content, README_TEXT.encode())
        self.assertEqual(domain.documents[0].sha256, README_SHA256)

        with self.assertRaisesRegex(ContractError, "invalid SourceDocument"):
            self.store.create_snapshot(
                self.task_id,
                resolution_id=resolution["resolution_id"],
                license="apache-2.0",
                license_status="known",
                files=[
                    RemoteSourceFile(
                        path="README.md",
                        kind="blob",
                        mode="100644",
                        size_bytes=len(README_TEXT.encode()),
                        remote_digest="3" * 40,
                    )
                ],
                documents=[
                    {
                        "path": "README.md",
                        "size_bytes": len(README_TEXT.encode()),
                        "sha256": "d" * 64,
                        "content": README_TEXT.encode(),
                    }
                ],
            )

    def test_prepared_intent_is_not_recovered_until_commit_was_requested(self) -> None:
        _, snapshot, analysis = self._chain()
        prepared = self.store.prepare_binding_intent(
            self.task_id,
            snapshot_id=snapshot["snapshot_id"],
            analysis_id=analysis["analysis_id"],
            idempotency_key="prepared-only",
            base_spec_revision=1,
        )
        restarted = ModelSourceStore(self.root)
        self.assertEqual(restarted.recover_pending_commits(self.task_id), [])
        self.assertIsNone(restarted.current_binding(self.task_id))
        self.assertEqual(
            restarted.get_binding_intent(self.task_id, prepared["intent_id"])[
                "status"
            ],
            "prepared",
        )

    def test_commit_request_recovers_idempotently_after_restart(self) -> None:
        _, snapshot, analysis = self._chain()
        intent = self.store.prepare_binding_intent(
            self.task_id,
            snapshot_id=snapshot["snapshot_id"],
            analysis_id=analysis["analysis_id"],
            idempotency_key="recover-after-request",
            base_spec_revision=1,
        )
        requested = self.store.request_binding_commit(
            self.task_id,
            intent["intent_id"],
            expected_intent_digest=intent["content_digest"],
        )
        self.assertEqual(requested["status"], "commit_requested")
        self.assertIsNone(self.store.current_binding(self.task_id))

        restarted = ModelSourceStore(self.root)
        [binding] = restarted.recover_pending_commits(
            self.task_id, resolve_spec_revision=lambda _task_id: 1
        )
        self.assertEqual(binding["binding_revision_id"], intent["binding_revision_id"])
        self.assertEqual(restarted.current_binding(self.task_id), binding)
        self.assertEqual(
            restarted.recover_pending_commits(
                self.task_id, resolve_spec_revision=lambda _task_id: 1
            ),
            [],
        )

    def test_spec_change_after_commit_request_aborts_and_never_recovers(self) -> None:
        _, snapshot, analysis = self._chain()
        intent = self.store.prepare_binding_intent(
            self.task_id,
            snapshot_id=snapshot["snapshot_id"],
            analysis_id=analysis["analysis_id"],
            idempotency_key="spec-changed-before-recovery",
            base_spec_revision=1,
        )
        self.store.request_binding_commit(
            self.task_id,
            intent["intent_id"],
            expected_intent_digest=intent["content_digest"],
        )

        restarted = ModelSourceStore(self.root)
        self.assertEqual(
            restarted.recover_pending_commits(
                self.task_id, resolve_spec_revision=lambda _task_id: 2
            ),
            [],
        )
        self.assertIsNone(restarted.current_binding(self.task_id))
        self.assertEqual(restarted.list_binding_revisions(self.task_id), [])
        state = restarted.get_binding_intent(self.task_id, intent["intent_id"])
        self.assertEqual(state["status"], "aborted_spec_changed")
        self.assertIsNone(state["commit_receipt"])
        self.assertEqual(state["abort"]["base_spec_revision"], 1)
        self.assertEqual(state["abort"]["observed_spec_revision"], 2)
        self.assertEqual(state["abort"]["reason"], "aborted_spec_changed")

        restarted_again = ModelSourceStore(self.root)
        self.assertEqual(
            restarted_again.recover_pending_commits(
                self.task_id, resolve_spec_revision=lambda _task_id: 1
            ),
            [],
        )
        self.assertIsNone(restarted_again.current_binding(self.task_id))
        with self.assertRaises(StaleTaskSpecRevisionError):
            restarted_again.commit_binding_intent(
                self.task_id,
                intent["intent_id"],
                expected_intent_digest=intent["content_digest"],
                current_spec_revision=1,
            )

    def test_stale_concurrent_intent_cannot_replace_current_binding(self) -> None:
        resolution, snapshot, analysis = self._chain()
        first = self.store.prepare_binding_intent(
            self.task_id,
            snapshot_id=snapshot["snapshot_id"],
            analysis_id=analysis["analysis_id"],
            idempotency_key="first",
            base_spec_revision=1,
        )
        stale = self.store.prepare_binding_intent(
            self.task_id,
            snapshot_id=snapshot["snapshot_id"],
            analysis_id=analysis["analysis_id"],
            idempotency_key="stale",
            base_spec_revision=1,
        )
        active = self.store.commit_binding_intent(
            self.task_id,
            first["intent_id"],
            expected_intent_digest=first["content_digest"],
            current_spec_revision=1,
        )
        with self.assertRaises(StaleBindingIntentError):
            self.store.commit_binding_intent(
                self.task_id,
                stale["intent_id"],
                expected_intent_digest=stale["content_digest"],
                current_spec_revision=1,
            )
        self.assertEqual(self.store.current_binding(self.task_id), active)
        stale_state = self.store.get_binding_intent(
            self.task_id, stale["intent_id"]
        )
        self.assertEqual(stale_state["status"], "aborted_binding_changed")
        self.assertIsNone(stale_state["commit_receipt"])
        self.assertEqual(stale_state["abort"]["base_binding_revision"], 0)
        self.assertEqual(stale_state["abort"]["observed_binding_revision"], 1)

        restarted = ModelSourceStore(self.root)
        self.assertEqual(
            restarted.recover_pending_commits(
                self.task_id, resolve_spec_revision=lambda _task_id: 1
            ),
            [],
        )
        self.assertEqual(restarted.current_binding(self.task_id), active)
        with self.assertRaises(StaleBindingIntentError):
            restarted.commit_binding_intent(
                self.task_id,
                stale["intent_id"],
                expected_intent_digest=stale["content_digest"],
                current_spec_revision=1,
            )

        newer_snapshot = self.store.create_snapshot(
            self.task_id,
            resolution_id=resolution["resolution_id"],
            license="apache-2.0",
            license_status="known",
            files=[
                RemoteSourceFile(
                    path="train.py",
                    kind="blob",
                    mode="100644",
                    size_bytes=124,
                    remote_digest="4" * 40,
                )
            ],
        )
        with self.assertRaisesRegex(ContractError, "does not describe snapshot"):
            self.store.prepare_binding_intent(
                self.task_id,
                snapshot_id=newer_snapshot["snapshot_id"],
                analysis_id=analysis["analysis_id"],
                idempotency_key="crossed-lineage",
                base_spec_revision=1,
            )

    def test_tampering_any_immutable_record_or_current_pointer_fails_closed(self) -> None:
        resolution, snapshot, analysis = self._chain()
        cases = [
            (
                self.root
                / "tasks"
                / self.task_id
                / "model_sources"
                / "resolutions"
                / f"{resolution['resolution_id']}.json",
                lambda: self.store.get_resolution(
                    self.task_id, resolution["resolution_id"]
                ),
            ),
            (
                self.root
                / "tasks"
                / self.task_id
                / "model_sources"
                / "snapshots"
                / f"{snapshot['snapshot_id']}.json",
                lambda: self.store.get_snapshot(self.task_id, snapshot["snapshot_id"]),
            ),
            (
                self.root
                / "tasks"
                / self.task_id
                / "model_sources"
                / "analyses"
                / f"{analysis['analysis_id']}.json",
                lambda: self.store.get_analysis(self.task_id, analysis["analysis_id"]),
            ),
        ]
        for path, load in cases:
            with self.subTest(path=path.name):
                original = path.read_text(encoding="utf-8")
                value = read_json(path)
                value["created_at"] = "tampered"
                write_json(path, value)
                with self.assertRaises(ModelSourceIntegrityError):
                    load()
                path.write_text(original, encoding="utf-8")

        intent = self.store.prepare_binding_intent(
            self.task_id,
            snapshot_id=snapshot["snapshot_id"],
            analysis_id=analysis["analysis_id"],
            idempotency_key="pointer-tamper",
            base_spec_revision=1,
        )
        self.store.commit_binding_intent(
            self.task_id,
            intent["intent_id"],
            expected_intent_digest=intent["content_digest"],
            current_spec_revision=1,
        )
        pointer = (
            self.root
            / "tasks"
            / self.task_id
            / "model_sources"
            / "current_binding.json"
        )
        value = read_json(pointer)
        value["revision"] = 999
        write_json(pointer, value)
        with self.assertRaises(ModelSourceIntegrityError):
            self.store.current_binding(self.task_id)

    def test_resealed_binding_cannot_cross_to_another_valid_source_lineage(self) -> None:
        _first_resolution, first_snapshot, first_analysis = self._chain()
        intent = self.store.prepare_binding_intent(
            self.task_id,
            snapshot_id=first_snapshot["snapshot_id"],
            analysis_id=first_analysis["analysis_id"],
            idempotency_key="bind-first-lineage",
            base_spec_revision=1,
        )
        binding = self.store.commit_binding_intent(
            self.task_id,
            intent["intent_id"],
            expected_intent_digest=intent["content_digest"],
            current_spec_revision=1,
        )

        second_resolution = self._resolution(commit=COMMIT_B)
        second_snapshot = self._snapshot(second_resolution)
        second_analysis = self._analysis(second_snapshot)
        path = (
            self.root
            / "tasks"
            / self.task_id
            / "model_sources"
            / "bindings"
            / f"{binding['binding_revision_id']}.json"
        )
        resealed = read_json(path)
        resealed.update(
            {
                "resolution_id": second_resolution["resolution_id"],
                "resolution_digest": second_resolution["content_digest"],
                "snapshot_id": second_snapshot["snapshot_id"],
                "snapshot_digest": second_snapshot["content_digest"],
                "analysis_id": second_analysis["analysis_id"],
                "analysis_digest": second_analysis["content_digest"],
            }
        )
        resealed["content_digest"] = content_digest(
            {
                key: value
                for key, value in resealed.items()
                if key != "content_digest"
            }
        )
        write_json(path, resealed)

        with self.assertRaisesRegex(
            ModelSourceIntegrityError, "ModelBindingRevision lineage changed"
        ):
            self.store.get_binding_revision(
                self.task_id, binding["binding_revision_id"]
            )

    def test_task_and_record_paths_cannot_escape_tasks_directory(self) -> None:
        for task_id in ("", ".", "..", "../escape", "/tmp/escape", "task\\escape"):
            with self.subTest(task_id=task_id), self.assertRaises(ContractError):
                self.store.create_resolution(
                    task_id,
                    provider="github",
                    repository="fixture/repo",
                    requested_revision=COMMIT_A,
                    resolved_commit=COMMIT_A,
                )
        with self.assertRaises(FileNotFoundError):
            self.store.create_resolution(
                "missing-task",
                provider="github",
                repository="fixture/repo",
                requested_revision=COMMIT_A,
                resolved_commit=COMMIT_A,
            )

        outside = Path(self.temporary.name) / "outside"
        outside.mkdir()
        link = self.root / "tasks" / "linked-task"
        link.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(ContractError):
            self.store.create_resolution(
                "linked-task",
                provider="github",
                repository="fixture/repo",
                requested_revision=COMMIT_A,
                resolved_commit=COMMIT_A,
            )
        self.assertEqual(list(outside.iterdir()), [])

    def test_credentials_and_unsafe_manifest_paths_are_rejected(self) -> None:
        with self.assertRaisesRegex(ContractError, "credential"):
            self.store.create_resolution(
                self.task_id,
                provider="huggingface",
                repository="fixture/model",
                requested_revision=COMMIT_A,
                resolved_commit=COMMIT_A,
                details={"nested": {"access_token": "secret"}},
            )
        with self.assertRaisesRegex(ContractError, "credential"):
            self.store.create_resolution(
                self.task_id,
                provider="github",
                repository="fixture/model",
                requested_revision=COMMIT_A,
                resolved_commit=COMMIT_A,
                source_uri="https://oauth-secret@github.com/fixture/model",
            )

        resolution = self._resolution()
        for relative_path in ("../private", "/etc/passwd", "folder\\file"):
            with self.subTest(relative_path=relative_path), self.assertRaises(
                ContractError
            ):
                self.store.create_snapshot(
                    self.task_id,
                    resolution_id=resolution["resolution_id"],
                    license="apache-2.0",
                    license_status="known",
                    files=[
                        {
                            "path": relative_path,
                            "kind": "blob",
                            "mode": "100644",
                            "size_bytes": 1,
                            "remote_digest": "e" * 40,
                            "lfs_sha256": None,
                        }
                    ],
                )


if __name__ == "__main__":
    unittest.main()
