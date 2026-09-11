from __future__ import annotations

import hashlib
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier
from unittest.mock import patch

from model_harness.delivery_authorizations import (
    DeliveryAuthorizationError,
    DeliveryAuthorizationStore,
    delivery_scope_sha256,
)


class DeliveryAuthorizationStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.task_id = "task-delivery-test"
        self.scope = {
            "action": "build_artifact_bundle",
            "task_id": self.task_id,
            "run_id": "run-delivery-test",
            "evaluation_report_id": "evaluation-test",
            "evaluation_report_sha256": "a" * 64,
            "sample_inference_check_id": None,
            "inference_check_id": None,
            "sample_inference_evidence_sha256": None,
            "inference_evidence_sha256": None,
        }

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def approval(checkpoint_id: str) -> dict[str, str]:
        return {
            "actor": "user",
            "checkpoint_id": checkpoint_id,
            "verified_by": "agent_bridge_token",
            "bridge_token_sha256": hashlib.sha256(
                b"test-agent-bridge-token"
            ).hexdigest(),
        }

    def issue(
        self,
        checkpoint_id: str,
        *,
        ttl_seconds: int = 600,
    ) -> tuple[dict[str, object], str]:
        return DeliveryAuthorizationStore(self.root).issue(
            task_id=self.task_id,
            action="build_artifact_bundle",
            scope=self.scope,
            approval=self.approval(checkpoint_id),
            ttl_seconds=ttl_seconds,
        )

    def test_persists_verifiable_approval_and_rejects_forged_or_replayed_checkpoint(
        self,
    ) -> None:
        store = DeliveryAuthorizationStore(self.root)
        with self.assertRaisesRegex(
            DeliveryAuthorizationError,
            "verified agent-bridge approval",
        ):
            store.issue(
                task_id=self.task_id,
                action="build_artifact_bundle",
                scope=self.scope,
                approval={
                    "actor": "user",
                    "checkpoint_id": "forged-checkpoint",
                },
            )

        record, _token = self.issue("native-checkpoint-1")
        persisted = DeliveryAuthorizationStore(self.root).get(
            self.task_id,
            str(record["authorization_id"]),
        )
        self.assertEqual(
            persisted["approval_decision"]["checkpoint_id"],
            "native-checkpoint-1",
        )
        self.assertEqual(
            persisted["approval_decision"]["verified_by"],
            "agent_bridge_token",
        )
        self.assertNotIn("token_sha256", store.public(persisted))
        with self.assertRaisesRegex(
            DeliveryAuthorizationError,
            "already issued",
        ):
            self.issue("native-checkpoint-1")

    def test_file_lock_allows_only_one_cross_instance_reservation(self) -> None:
        record, token = self.issue("native-concurrent-checkpoint")
        authorization_id = str(record["authorization_id"])
        barrier = Barrier(2)

        def reserve() -> bool:
            barrier.wait(timeout=5)
            try:
                DeliveryAuthorizationStore(self.root).reserve(
                    task_id=self.task_id,
                    authorization_id=authorization_id,
                    authorization_token=token,
                    action="build_artifact_bundle",
                    approved_scope_sha256=delivery_scope_sha256(self.scope),
                    current_scope=self.scope,
                )
                return True
            except DeliveryAuthorizationError:
                return False

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(lambda _index: reserve(), range(2)))
        self.assertEqual(sorted(outcomes), [False, True])
        persisted = DeliveryAuthorizationStore(self.root).get(
            self.task_id,
            authorization_id,
        )
        self.assertEqual(persisted["status"], "consuming")

    def test_wrong_token_scope_drift_and_expiry_fail_closed(self) -> None:
        record, token = self.issue("native-wrong-token")
        authorization_id = str(record["authorization_id"])
        store = DeliveryAuthorizationStore(self.root)
        with self.assertRaisesRegex(DeliveryAuthorizationError, "token is invalid"):
            store.reserve(
                task_id=self.task_id,
                authorization_id=authorization_id,
                authorization_token="wrong-token",
                action="build_artifact_bundle",
                approved_scope_sha256=delivery_scope_sha256(self.scope),
                current_scope=self.scope,
            )
        self.assertEqual(store.get(self.task_id, authorization_id)["status"], "issued")

        drift_record, drift_token = self.issue("native-scope-drift")
        changed_scope = {**self.scope, "run_id": "run-other"}
        with self.assertRaisesRegex(DeliveryAuthorizationError, "changed or stale"):
            store.reserve(
                task_id=self.task_id,
                authorization_id=str(drift_record["authorization_id"]),
                authorization_token=drift_token,
                action="build_artifact_bundle",
                approved_scope_sha256=delivery_scope_sha256(self.scope),
                current_scope=changed_scope,
            )
        self.assertEqual(
            store.get(self.task_id, str(drift_record["authorization_id"]))[
                "status"
            ],
            "invalidated",
        )

        issued_at = datetime(2026, 8, 27, tzinfo=UTC)
        with patch(
            "model_harness.delivery_authorizations._utc_now",
            return_value=issued_at,
        ):
            expired_record, expired_token = self.issue(
                "native-expired",
                ttl_seconds=1,
            )
        with patch(
            "model_harness.delivery_authorizations._utc_now",
            return_value=issued_at + timedelta(seconds=2),
        ):
            with self.assertRaisesRegex(DeliveryAuthorizationError, "expired"):
                store.reserve(
                    task_id=self.task_id,
                    authorization_id=str(expired_record["authorization_id"]),
                    authorization_token=expired_token,
                    action="build_artifact_bundle",
                    approved_scope_sha256=delivery_scope_sha256(self.scope),
                    current_scope=self.scope,
                )
        self.assertEqual(
            store.get(self.task_id, str(expired_record["authorization_id"]))[
                "status"
            ],
            "expired",
        )


if __name__ == "__main__":
    unittest.main()
