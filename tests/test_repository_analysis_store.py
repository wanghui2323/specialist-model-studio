from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from model_harness.errors import ContractError
from model_harness.io_utils import write_json
from model_harness.repository_analysis_store import (
    BindingAnalysisAttemptStore,
    RepositoryAnalysisIntegrityError,
    RepositoryAnalysisStore,
    StaleAnalysisAttemptError,
)


SNAPSHOT_ID = "source-snapshot-r1-abc123def456"
SNAPSHOT_DIGEST = "a" * 64


class RepositoryAnalysisStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.task_id = "analysis-task"
        self.store = RepositoryAnalysisStore(self.root)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _create_attempt(
        self,
        *,
        mapping_revision_id: str | None = None,
    ) -> dict:
        return self.store.create_attempt(
            self.task_id,
            snapshot_id=SNAPSHOT_ID,
            snapshot_digest=SNAPSHOT_DIGEST,
            analyzer_version="repository-analysis/0.2",
            manual_mapping_revision_id=mapping_revision_id,
        )

    def test_lifecycle_is_append_only_and_recovers_after_restart(self) -> None:
        queued = self._create_attempt()
        attempt_id = queued["attempt"]["attempt_id"]
        attempt_path = next(
            (self.root / "tasks" / self.task_id).glob(
                "repository_analysis_lifecycle/attempts/*/attempt.json"
            )
        )
        immutable_attempt_bytes = attempt_path.read_bytes()

        running = self.store.mark_running(self.task_id, attempt_id)
        completed = self.store.complete(
            self.task_id,
            attempt_id,
            analysis={
                "status": "complete",
                "execution_policy": "static_only_never_execute",
                "frameworks": [{"name": "pytorch", "evidence_refs": ["train.py:1"]}],
            },
        )

        self.assertEqual(queued["current_state"]["status"], "queued")
        self.assertEqual(running["current_state"]["status"], "running")
        self.assertEqual(completed["current_state"]["status"], "completed")
        self.assertEqual(completed["current_state"]["state_revision"], 3)
        self.assertEqual(attempt_path.read_bytes(), immutable_attempt_bytes)
        self.assertEqual(
            len(
                list(
                    attempt_path.parent.joinpath("states").glob("*.json")
                )
            ),
            3,
        )

        restarted = RepositoryAnalysisStore(self.root)
        current = restarted.current_attempt(self.task_id, SNAPSHOT_ID)
        self.assertIsNotNone(current)
        assert current is not None
        self.assertEqual(current["attempt"]["attempt_id"], attempt_id)
        self.assertEqual(current["current_state"]["status"], "completed")
        self.assertEqual(
            current["current_state"]["result"]["analysis_digest"],
            completed["current_state"]["result"]["analysis_digest"],
        )

    def test_failed_attempt_records_typed_evidence_and_retry_is_new_attempt(self) -> None:
        first = self._create_attempt()
        first_id = first["attempt"]["attempt_id"]
        failed = self.store.fail(
            self.task_id,
            first_id,
            stage="document_parse",
            code="invalid_toml",
            message="pyproject.toml could not be parsed",
            retryable=True,
            details={"path": "pyproject.toml"},
        )

        evidence = failed["current_state"]["failure"]
        self.assertEqual(
            {key: evidence[key] for key in ("stage", "code", "message", "retryable")},
            {
                "stage": "document_parse",
                "code": "invalid_toml",
                "message": "pyproject.toml could not be parsed",
                "retryable": True,
            },
        )

        retried = self.store.retry(self.task_id, first_id)
        second_id = retried["attempt"]["attempt_id"]
        self.assertNotEqual(second_id, first_id)
        self.assertEqual(retried["attempt"]["attempt_sequence"], 2)
        self.assertEqual(retried["attempt"]["retry_of_attempt_id"], first_id)
        self.assertEqual(
            retried["attempt"]["retry_of_attempt_digest"],
            first["attempt"]["content_digest"],
        )
        self.assertEqual(
            self.store.current_attempt(self.task_id, SNAPSHOT_ID)["attempt"]["attempt_id"],
            second_id,
        )
        with self.assertRaises(StaleAnalysisAttemptError):
            self.store.mark_running(self.task_id, first_id)
        with self.assertRaisesRegex(
            ContractError, "only a terminal analysis attempt can be retried"
        ):
            self.store.retry(self.task_id, second_id)

    def test_transition_rules_and_cancellation_are_fail_closed(self) -> None:
        created = self._create_attempt()
        attempt_id = created["attempt"]["attempt_id"]
        with self.assertRaisesRegex(
            ContractError, "invalid analysis transition queued -> completed"
        ):
            self.store.complete(
                self.task_id,
                attempt_id,
                analysis={"status": "complete"},
            )

        self.store.mark_running(self.task_id, attempt_id)
        cancelled = self.store.cancel(
            self.task_id,
            attempt_id,
            reason="user requested cancellation before parsing",
        )
        self.assertEqual(cancelled["current_state"]["status"], "cancelled")
        self.assertEqual(
            cancelled["current_state"]["cancellation"]["reason"],
            "user requested cancellation before parsing",
        )
        with self.assertRaisesRegex(ContractError, "invalid analysis transition"):
            self.store.mark_running(self.task_id, attempt_id)

    def test_manual_mapping_revisions_do_not_overwrite_prior_analysis(self) -> None:
        first_mapping = self.store.create_manual_mapping_revision(
            self.task_id,
            snapshot_id=SNAPSHOT_ID,
            snapshot_digest=SNAPSHOT_DIGEST,
            mapping={
                "training_entrypoint": "scripts/train.py",
                "dataset_argument": "--data-dir",
            },
        )
        first = self._create_attempt(
            mapping_revision_id=first_mapping["mapping_revision_id"]
        )
        first_id = first["attempt"]["attempt_id"]
        self.store.mark_running(self.task_id, first_id)
        completed = self.store.complete(
            self.task_id,
            first_id,
            analysis={
                "status": "complete",
                "training_entrypoint": "scripts/train.py",
            },
        )
        completed_digest = completed["current_state"]["content_digest"]

        second_mapping = self.store.create_manual_mapping_revision(
            self.task_id,
            snapshot_id=SNAPSHOT_ID,
            snapshot_digest=SNAPSHOT_DIGEST,
            mapping={
                "training_entrypoint": "tools/finetune.py",
                "dataset_argument": "--dataset",
            },
        )
        retried = self.store.retry(
            self.task_id,
            first_id,
            manual_mapping_revision_id=second_mapping["mapping_revision_id"],
        )

        mappings = self.store.list_manual_mapping_revisions(
            self.task_id, SNAPSHOT_ID
        )
        self.assertEqual([item["revision"] for item in mappings], [1, 2])
        self.assertEqual(
            second_mapping["supersedes_revision_id"],
            first_mapping["mapping_revision_id"],
        )
        self.assertEqual(
            self.store.get_attempt(self.task_id, first_id)["current_state"][
                "content_digest"
            ],
            completed_digest,
        )
        self.assertEqual(
            retried["attempt"]["manual_mapping_revision_id"],
            second_mapping["mapping_revision_id"],
        )
        self.assertEqual(
            self.store.get_manual_mapping_revision(
                self.task_id, first_mapping["mapping_revision_id"]
            )["mapping"]["training_entrypoint"],
            "scripts/train.py",
        )

    def test_subsequent_attempt_requires_explicit_retry_lineage(self) -> None:
        first = self._create_attempt()
        self.store.fail(
            self.task_id,
            first["attempt"]["attempt_id"],
            stage="analysis",
            code="no_entrypoint",
            message="No training entrypoint was found",
            retryable=True,
        )
        with self.assertRaisesRegex(
            ContractError, "must identify the retry source"
        ):
            self._create_attempt()

    def test_digest_tampering_is_detected_after_restart(self) -> None:
        created = self._create_attempt()
        attempt_id = created["attempt"]["attempt_id"]
        self.store.mark_running(self.task_id, attempt_id)
        state_path = sorted(
            (
                self.root
                / "tasks"
                / self.task_id
                / "repository_analysis_lifecycle"
                / "attempts"
                / attempt_id
                / "states"
            ).glob("*.json")
        )[-1]
        tampered = json.loads(state_path.read_text(encoding="utf-8"))
        tampered["status"] = "completed"
        write_json(state_path, tampered)

        restarted = RepositoryAnalysisStore(self.root)
        with self.assertRaisesRegex(
            RepositoryAnalysisIntegrityError, "digest mismatch"
        ):
            restarted.current_attempt(self.task_id, SNAPSHOT_ID)

    def test_missing_current_index_is_rebuilt_from_immutable_pointer(self) -> None:
        created = self._create_attempt()
        attempt_id = created["attempt"]["attempt_id"]
        self.store.mark_running(self.task_id, attempt_id)
        current_path = (
            self.root
            / "tasks"
            / self.task_id
            / "repository_analysis_lifecycle"
            / "pointers"
            / SNAPSHOT_ID
            / "current.json"
        )
        current_path.unlink()

        restarted = RepositoryAnalysisStore(self.root)
        recovered = restarted.current_attempt(self.task_id, SNAPSHOT_ID)
        self.assertIsNotNone(recovered)
        assert recovered is not None
        self.assertEqual(recovered["current_state"]["status"], "running")
        self.assertTrue(current_path.is_file())

    def test_interrupted_state_or_attempt_commit_recovers_from_immutable_facts(self) -> None:
        created = self._create_attempt()
        attempt_id = created["attempt"]["attempt_id"]
        self.store.mark_running(self.task_id, attempt_id)
        lifecycle_root = (
            self.root
            / "tasks"
            / self.task_id
            / "repository_analysis_lifecycle"
        )
        pointer_root = lifecycle_root / "pointers" / SNAPSHOT_ID
        running_pointer = sorted(
            (pointer_root / "revisions").glob("*.json")
        )[-1]
        running_pointer.unlink()
        (pointer_root / "current.json").unlink()

        recovered = RepositoryAnalysisStore(self.root).current_attempt(
            self.task_id, SNAPSHOT_ID
        )
        self.assertIsNotNone(recovered)
        assert recovered is not None
        self.assertEqual(recovered["current_state"]["status"], "running")
        self.assertEqual(recovered["pointer"]["selection_reason"], "recovered_after_restart")

        other_root = Path(self.temporary.name) / "other-workspace"
        other = RepositoryAnalysisStore(other_root)
        orphan = other.create_attempt(
            self.task_id,
            snapshot_id=SNAPSHOT_ID,
            snapshot_digest=SNAPSHOT_DIGEST,
            analyzer_version="repository-analysis/0.2",
        )
        other_lifecycle = (
            other_root
            / "tasks"
            / self.task_id
            / "repository_analysis_lifecycle"
        )
        for state_path in (
            other_lifecycle
            / "attempts"
            / orphan["attempt"]["attempt_id"]
            / "states"
        ).glob("*.json"):
            state_path.unlink()
        for pointer_path in (
            other_lifecycle / "pointers" / SNAPSHOT_ID
        ).rglob("*.json"):
            pointer_path.unlink()

        recovered_orphan = RepositoryAnalysisStore(other_root).current_attempt(
            self.task_id, SNAPSHOT_ID
        )
        self.assertIsNotNone(recovered_orphan)
        assert recovered_orphan is not None
        self.assertEqual(recovered_orphan["current_state"]["status"], "queued")
        self.assertEqual(
            recovered_orphan["pointer"]["selection_reason"],
            "recovered_after_restart",
        )

    def test_multiline_exception_message_is_durably_normalized(self) -> None:
        created = self._create_attempt()
        failed = self.store.fail(
            self.task_id,
            created["attempt"]["attempt_id"],
            stage="parser",
            code="parse_failed",
            message="first line\nsecond line\twith context",
            retryable=True,
        )
        self.assertEqual(
            failed["current_state"]["failure"]["message"],
            "first line second line with context",
        )

    def test_store_never_invokes_repository_code_or_host_processes(self) -> None:
        with (
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
            mapping = self.store.create_manual_mapping_revision(
                self.task_id,
                snapshot_id=SNAPSHOT_ID,
                snapshot_digest=SNAPSHOT_DIGEST,
                mapping={"training_entrypoint": "malicious/train.py"},
            )
            created = self._create_attempt(
                mapping_revision_id=mapping["mapping_revision_id"]
            )
            running = self.store.mark_running(
                self.task_id, created["attempt"]["attempt_id"]
            )
            self.assertEqual(
                running["attempt"]["execution_policy"],
                "static_only_never_execute",
            )

    def test_analysis_storage_symlink_escape_fails_before_writing(self) -> None:
        linked_task = "linked-analysis-task"
        task_root = self.root / "tasks" / linked_task
        task_root.mkdir(parents=True)
        outside = self.root / "outside"
        outside.mkdir()
        (task_root / "repository_analysis_lifecycle").symlink_to(
            outside, target_is_directory=True
        )

        with self.assertRaisesRegex(
            RepositoryAnalysisIntegrityError,
            "repository analysis directory changed",
        ):
            self.store.create_attempt(
                linked_task,
                snapshot_id=SNAPSHOT_ID,
                snapshot_digest=SNAPSHOT_DIGEST,
                analyzer_version="repository-analysis/0.2",
            )
        self.assertEqual(list(outside.iterdir()), [])


class BindingAnalysisAttemptStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.task_id = "binding-analysis-task"
        task_dir = self.root / "tasks" / self.task_id
        task_dir.mkdir(parents=True)
        write_json(task_dir / "task.json", {"task_id": self.task_id})
        self.store = BindingAnalysisAttemptStore(self.root)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def create_attempt(self) -> dict:
        return self.store.create_attempt(
            self.task_id,
            resolution_id="source-resolution-r1-abc123def456",
            resolution_digest="b" * 64,
            expected_resolved_commit="c" * 40,
            base_spec_revision=1,
        )

    def test_attempt_is_visible_before_binding_and_retains_terminal_evidence(self) -> None:
        queued = self.create_attempt()
        attempt_id = queued["attempt"]["attempt_id"]
        self.assertEqual(queued["current_state"]["status"], "queued")
        self.assertEqual(
            self.store.current_attempt(self.task_id)["attempt"]["attempt_id"],
            attempt_id,
        )
        running = self.store.mark_running(self.task_id, attempt_id)
        self.assertEqual(running["current_state"]["status"], "running")
        failed = self.store.fail(
            self.task_id,
            attempt_id,
            stage="source_snapshot",
            code="provider_timeout",
            message="provider timed out",
            retryable=True,
            details={"resolution_id": "source-resolution-r1-abc123def456"},
        )
        self.assertEqual(failed["current_state"]["status"], "failed")
        restarted = BindingAnalysisAttemptStore(self.root)
        recovered = restarted.current_attempt(self.task_id)
        self.assertEqual(
            recovered["current_state"]["failure"]["code"],
            "provider_timeout",
        )
        retried = restarted.create_attempt(
            self.task_id,
            resolution_id="source-resolution-r1-abc123def456",
            resolution_digest="b" * 64,
            expected_resolved_commit="c" * 40,
            base_spec_revision=1,
        )
        self.assertEqual(retried["attempt"]["retry_of_attempt_id"], attempt_id)

    def test_restart_converts_nonterminal_attempt_to_durable_failure(self) -> None:
        queued = self.create_attempt()
        attempt_id = queued["attempt"]["attempt_id"]
        self.store.mark_running(self.task_id, attempt_id)

        restarted = BindingAnalysisAttemptStore(self.root)
        recovered = restarted.recover_interrupted_attempts()
        self.assertEqual(len(recovered), 1)
        current = restarted.current_attempt(self.task_id)
        self.assertEqual(current["current_state"]["status"], "failed")
        self.assertEqual(
            current["current_state"]["failure"]["code"],
            "interrupted_by_restart",
        )
        self.assertEqual(
            current["current_state"]["failure"]["details"]["previous_status"],
            "running",
        )


if __name__ == "__main__":
    unittest.main()
