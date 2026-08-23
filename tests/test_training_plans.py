from __future__ import annotations

import tempfile
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path

from model_harness.errors import ContractError
from model_harness.io_utils import read_json, write_json
from model_harness.training_plans import (
    ApprovalRecord,
    StaleTrainingPlanError,
    TrainingPlanApprovalRequired,
    TrainingPlanIntegrityError,
    TrainingPlanRevision,
    TrainingPlanStore,
    canonical_approval_sha256,
    canonical_json,
    canonical_plan_sha256,
)


SNAPSHOT_A = "a" * 64
ANALYSIS_A = "b" * 64
SNAPSHOT_B = "c" * 64
ANALYSIS_B = "d" * 64


def _plan_values() -> dict:
    return {
        "base_spec_revision": 3,
        "source_snapshot_id": "snapshot_fixture_a",
        "snapshot_digest": SNAPSHOT_A,
        "analysis_id": "analysis_fixture_a",
        "analysis_digest": ANALYSIS_A,
        "entrypoint": {
            "argv": ["python", "train.py", "--epochs", "2"],
            "working_dir": "/workspace/source",
        },
        "dataset_mapping": {"train": "data/train.csv", "target": "label"},
        "hyperparameters": {"learning_rate": 0.001, "batch_size": 8},
        "evaluation": {"metrics": ["accuracy"], "gates": {"accuracy": 0.8}},
        "artifact_contract": {"files": ["model.onnx"]},
        "resource_budget": {
            "max_seconds": 600,
            "ram_bytes": 4_000_000_000,
            "vram_bytes": 0,
            "disk_bytes": 2_000_000_000,
        },
        "execution_policy": {
            "backend": "oci",
            "network_allowlist": [],
            "secret_scopes": [],
        },
    }


def _authorization_values(plan: dict) -> dict:
    return {
        "expected_plan_sha256": plan["plan_sha256"],
        "current_spec_revision": plan["base_spec_revision"],
        "source_snapshot_id": plan["source_snapshot_id"],
        "snapshot_digest": plan["snapshot_digest"],
        "analysis_id": plan["analysis_id"],
        "analysis_digest": plan["analysis_digest"],
    }


class TrainingPlanDigestTests(unittest.TestCase):
    def test_canonical_plan_digest_is_order_stable_and_excludes_only_self_hash(self) -> None:
        left = {
            "task_id": "task_a",
            "nested": {"z": 2, "a": 1},
            "plan_sha256": "old-value",
        }
        right = {
            "plan_sha256": "another-old-value",
            "nested": {"a": 1, "z": 2},
            "task_id": "task_a",
        }
        self.assertEqual(canonical_plan_sha256(left), canonical_plan_sha256(right))

        changed = dict(right)
        changed["task_id"] = "task_b"
        self.assertNotEqual(
            canonical_plan_sha256(left), canonical_plan_sha256(changed)
        )
        with self.assertRaises(ContractError):
            canonical_json({"unsafe": float("nan")})

    def test_plan_and_approval_value_objects_are_deeply_immutable(self) -> None:
        values = _plan_values()
        plan = TrainingPlanRevision.create(
            training_plan_revision_id="plan_fixture",
            task_id="task_fixture",
            revision=1,
            created_at="2026-08-23T00:00:00+00:00",
            **values,
        )
        first = plan.to_dict()
        first["hyperparameters"]["batch_size"] = 999
        self.assertEqual(plan.to_dict()["hyperparameters"]["batch_size"], 8)
        with self.assertRaises(FrozenInstanceError):
            plan._canonical_record = b"changed"  # type: ignore[misc]

        approval = ApprovalRecord.create(
            approval_id="approval_fixture",
            task_id="task_fixture",
            subject_id="plan_fixture",
            digest=plan.plan_sha256,
            decision="approve",
            actor="human@example.test",
            reason="reviewed",
            sequence=1,
            created_at="2026-08-23T00:01:00+00:00",
        )
        copied = approval.to_dict()
        copied["decision"] = "reject"
        self.assertEqual(approval.to_dict()["decision"], "approve")


class TrainingPlanStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "workspace"
        self.task_id = "task_training_plan_fixture"
        write_json(
            self.root / "tasks" / self.task_id / "task.json",
            {"schema_version": "0.2", "task_id": self.task_id},
        )
        self.store = TrainingPlanStore(self.root)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _create(self) -> dict:
        return self.store.create_revision(self.task_id, **_plan_values())

    def _approve(self, plan: dict) -> dict:
        return self.store.approve(
            self.task_id,
            plan["training_plan_revision_id"],
            expected_plan_sha256=plan["plan_sha256"],
            actor="reviewer@example.test",
            reason="digest and plan reviewed",
        )

    def _authorize(self, store: TrainingPlanStore, plan: dict) -> dict:
        return store.authorize_use(
            self.task_id,
            plan["training_plan_revision_id"],
            **_authorization_values(plan),
        )

    def _plan_path(self, plan: dict) -> Path:
        return (
            self.root
            / "tasks"
            / self.task_id
            / "training_plans"
            / "revisions"
            / f"{plan['training_plan_revision_id']}.json"
        )

    def test_approve_exact_digest_persists_across_restart_and_authorizes_use(self) -> None:
        plan = self._create()
        approval = self._approve(plan)
        self.assertEqual(approval["subject_type"], "training_plan_revision")
        self.assertEqual(approval["subject_id"], plan["training_plan_revision_id"])
        self.assertEqual(approval["digest"], plan["plan_sha256"])
        self.assertEqual(
            self.store.effective_status(
                self.task_id, plan["training_plan_revision_id"]
            ),
            "approved",
        )

        reopened = TrainingPlanStore(self.root)
        self.assertEqual(reopened.current_revision(self.task_id), plan)
        self.assertEqual(
            reopened.list_approvals(self.task_id, plan["training_plan_revision_id"]),
            [approval],
        )
        self.assertEqual(self._authorize(reopened, plan), plan)

        stored = read_json(self._plan_path(plan))
        self.assertEqual(stored["status"], "awaiting_approval")
        self.assertNotIn("effective_status", stored)

    def test_revision_supersedes_without_mutation_and_old_approval_never_carries(self) -> None:
        first = self._create()
        self._approve(first)
        first_bytes = self._plan_path(first).read_bytes()

        second = self.store.revise_revision(
            self.task_id,
            first["training_plan_revision_id"],
            expected_parent_sha256=first["plan_sha256"],
            changes={
                "hyperparameters": {
                    "learning_rate": 0.001,
                    "batch_size": 4,
                    "gradient_accumulation_steps": 2,
                }
            },
        )
        self.assertEqual(second["revision"], 2)
        self.assertEqual(
            second["parent_revision_id"], first["training_plan_revision_id"]
        )
        self.assertEqual(second["parent_plan_sha256"], first["plan_sha256"])
        self.assertEqual(self._plan_path(first).read_bytes(), first_bytes)
        self.assertEqual(
            self.store.effective_status(
                self.task_id, first["training_plan_revision_id"]
            ),
            "superseded",
        )
        self.assertEqual(
            self.store.effective_status(
                self.task_id, second["training_plan_revision_id"]
            ),
            "awaiting_approval",
        )
        with self.assertRaises(TrainingPlanApprovalRequired):
            self._authorize(self.store, second)
        with self.assertRaises(StaleTrainingPlanError):
            self._authorize(self.store, first)

        self._approve(second)
        self.assertEqual(self._authorize(self.store, second), second)
        self.assertEqual(
            read_json(self._plan_path(first))["status"], "awaiting_approval"
        )
        self.assertEqual(
            read_json(self._plan_path(second))["status"], "awaiting_approval"
        )

    def test_reject_and_cancel_append_decisions_and_revoke_authorization(self) -> None:
        plan = self._create()
        rejected = self.store.reject(
            self.task_id,
            plan["training_plan_revision_id"],
            expected_plan_sha256=plan["plan_sha256"],
            actor="reviewer@example.test",
            reason="resource limits are unacceptable",
        )
        self.assertEqual(rejected["sequence"], 1)
        self.assertEqual(
            self.store.effective_status(
                self.task_id, plan["training_plan_revision_id"]
            ),
            "rejected",
        )
        with self.assertRaises(TrainingPlanApprovalRequired):
            self._authorize(self.store, plan)

        approved = self._approve(plan)
        self.assertEqual(approved["sequence"], 2)
        self.assertEqual(approved["previous_approval_id"], rejected["approval_id"])
        self.assertEqual(self._authorize(self.store, plan), plan)

        cancelled = self.store.cancel(
            self.task_id,
            plan["training_plan_revision_id"],
            expected_plan_sha256=plan["plan_sha256"],
            actor="reviewer@example.test",
            reason="user cancelled before execution",
        )
        self.assertEqual(cancelled["sequence"], 3)
        self.assertEqual(
            self.store.effective_status(
                self.task_id, plan["training_plan_revision_id"]
            ),
            "cancelled",
        )
        with self.assertRaises(TrainingPlanApprovalRequired):
            self._authorize(self.store, plan)

    def test_plan_tamper_after_approval_fails_even_if_attacker_reseals_record(self) -> None:
        plan = self._create()
        self._approve(plan)
        path = self._plan_path(plan)
        changed = read_json(path)
        changed["hyperparameters"]["batch_size"] = 999
        changed["plan_sha256"] = canonical_plan_sha256(changed)
        write_json(path, changed)

        with self.assertRaisesRegex(
            TrainingPlanIntegrityError, "pointer|chain|digest"
        ):
            self.store.get_revision(
                self.task_id, plan["training_plan_revision_id"]
            )
        with self.assertRaisesRegex(
            TrainingPlanIntegrityError, "pointer|chain|digest"
        ):
            self._authorize(self.store, plan)

    def test_approval_tamper_fails_even_if_attacker_reseals_record(self) -> None:
        plan = self._create()
        approval = self._approve(plan)
        path = (
            self.root
            / "tasks"
            / self.task_id
            / "training_plans"
            / "approvals"
            / plan["training_plan_revision_id"]
            / f"{approval['approval_id']}.json"
        )
        changed = read_json(path)
        changed["decision"] = "cancel"
        changed["reason"] = "tampered"
        changed["approval_sha256"] = canonical_approval_sha256(changed)
        write_json(path, changed)

        with self.assertRaisesRegex(TrainingPlanIntegrityError, "head"):
            self.store.list_approvals(
                self.task_id, plan["training_plan_revision_id"]
            )

    def test_current_pointer_tamper_fails_closed_on_read(self) -> None:
        plan = self._create()
        pointer_path = (
            self.root
            / "tasks"
            / self.task_id
            / "training_plans"
            / "current.json"
        )
        changed = read_json(pointer_path)
        changed["revision"] = 999
        write_json(pointer_path, changed)
        with self.assertRaisesRegex(TrainingPlanIntegrityError, "pointer"):
            self.store.get_revision(
                self.task_id, plan["training_plan_revision_id"]
            )

    def test_current_pointer_is_restart_safe_and_recovers_interrupted_update(self) -> None:
        first = self._create()
        pointer_path = (
            self.root
            / "tasks"
            / self.task_id
            / "training_plans"
            / "current.json"
        )
        pointer_path.unlink()
        reopened = TrainingPlanStore(self.root)
        self.assertEqual(reopened.current_revision(self.task_id), first)
        recovered_first_pointer = pointer_path.read_bytes()

        second = reopened.revise_revision(
            self.task_id,
            first["training_plan_revision_id"],
            expected_parent_sha256=first["plan_sha256"],
            changes={"resource_budget": {**first["resource_budget"], "max_seconds": 900}},
        )
        pointer_path.write_bytes(recovered_first_pointer)
        after_interruption = TrainingPlanStore(self.root)
        self.assertEqual(after_interruption.current_revision(self.task_id), second)
        self.assertEqual(
            read_json(pointer_path)["training_plan_revision_id"],
            second["training_plan_revision_id"],
        )

    def test_approval_head_recovers_interrupted_projection_update(self) -> None:
        plan = self._create()
        first = self._approve(plan)
        head_path = (
            self.root
            / "tasks"
            / self.task_id
            / "training_plans"
            / "approval_heads"
            / f"{plan['training_plan_revision_id']}.json"
        )
        first_head = head_path.read_bytes()
        second = self.store.reject(
            self.task_id,
            plan["training_plan_revision_id"],
            expected_plan_sha256=plan["plan_sha256"],
            actor="reviewer@example.test",
            reason="new evidence invalidated approval",
        )

        head_path.write_bytes(first_head)
        reopened = TrainingPlanStore(self.root)
        self.assertEqual(
            reopened.list_approvals(
                self.task_id, plan["training_plan_revision_id"]
            ),
            [first, second],
        )
        self.assertEqual(read_json(head_path)["sequence"], 2)

        head_path.unlink()
        reopened_again = TrainingPlanStore(self.root)
        self.assertEqual(
            reopened_again.list_approvals(
                self.task_id, plan["training_plan_revision_id"]
            )[-1]["decision"],
            "reject",
        )
        self.assertEqual(read_json(head_path)["approval_id"], second["approval_id"])

    def test_authorization_fails_closed_on_any_upstream_lineage_drift(self) -> None:
        plan = self._create()
        self._approve(plan)
        cases = {
            "current_spec_revision": 4,
            "source_snapshot_id": "snapshot_fixture_b",
            "snapshot_digest": SNAPSHOT_B,
            "analysis_id": "analysis_fixture_b",
            "analysis_digest": ANALYSIS_B,
        }
        for field, changed_value in cases.items():
            values = _authorization_values(plan)
            values[field] = changed_value
            with self.subTest(field=field), self.assertRaisesRegex(
                StaleTrainingPlanError, field.replace("current_", "base_")
                if field == "current_spec_revision"
                else field,
            ):
                self.store.authorize_use(
                    self.task_id,
                    plan["training_plan_revision_id"],
                    **values,
                )

    def test_invalid_mutation_and_path_escape_are_rejected(self) -> None:
        first = self._create()
        with self.assertRaises(ContractError):
            self.store.create_revision(self.task_id, **_plan_values())
        for changes in (
            {},
            {"status": "approved"},
            {"plan_sha256": "0" * 64},
            {"hyperparameters": first["hyperparameters"]},
            {
                "execution_policy": {
                    "backend": "host_subprocess",
                    "network_allowlist": [],
                    "secret_scopes": [],
                }
            },
            {
                "execution_policy": {
                    "backend": "oci",
                    "network_allowlist": ["*"],
                    "secret_scopes": [],
                }
            },
            {
                "resource_budget": {
                    **first["resource_budget"],
                    "max_seconds": 0,
                }
            },
            {
                "entrypoint": {
                    "argv": ["python", "train.py"],
                    "working_dir": "../host",
                }
            },
        ):
            with self.subTest(changes=changes), self.assertRaises(ContractError):
                self.store.revise_revision(
                    self.task_id,
                    first["training_plan_revision_id"],
                    expected_parent_sha256=first["plan_sha256"],
                    changes=changes,
                )

        for unsafe in ("", ".", "..", "../escape", "/tmp/escape", "task\\escape"):
            with self.subTest(task_id=unsafe), self.assertRaises(ContractError):
                self.store.current_revision(unsafe)

    def test_training_plan_storage_symlink_escape_fails_before_writing(self) -> None:
        linked_task = "task_training_plan_linked"
        linked_root = self.root / "tasks" / linked_task
        write_json(
            linked_root / "task.json",
            {"schema_version": "0.2", "task_id": linked_task},
        )
        outside = Path(self.temporary.name) / "outside-plan"
        outside.mkdir()
        (linked_root / "training_plans").symlink_to(
            outside, target_is_directory=True
        )

        with self.assertRaisesRegex(
            TrainingPlanIntegrityError, "training plan directory changed"
        ):
            self.store.create_revision(linked_task, **_plan_values())
        self.assertEqual(list(outside.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
