from __future__ import annotations

import io
import tempfile
import unittest
import zipfile
from pathlib import Path

from PIL import Image, ImageDraw

try:
    from fastapi.testclient import TestClient
except ImportError:  # pragma: no cover - optional dependency
    TestClient = None  # type: ignore[assignment]

from model_harness.io_utils import read_json, sha256_file, write_json
from model_harness.server import create_app
from tests.run_authorization import (
    request_task_run_authorization,
    start_authorized_task_run,
)


def _image_dataset_zip() -> bytes:
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for label, color in (
            ("red-parts", (225, 35, 35)),
            ("blue-parts", (35, 70, 225)),
        ):
            for index in range(8):
                image = Image.new("RGB", (36, 28), color)
                draw = ImageDraw.Draw(image)
                draw.rectangle(
                    (3 + index, 4, 15 + index, 21),
                    outline=(255, 255, 255),
                    width=2,
                )
                output = io.BytesIO()
                image.save(output, format="PNG")
                archive.writestr(f"parts/{label}/{index}.png", output.getvalue())
    return payload.getvalue()


@unittest.skipIf(TestClient is None, "server extra is not installed")
class ConfirmationBindingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.app = create_app(Path(self.temp_dir.name) / "runs")
        self.client_context = TestClient(self.app)  # type: ignore[misc]
        self.client = self.client_context.__enter__()
        self.dataset_payload = _image_dataset_zip()

    def tearDown(self) -> None:
        self.client_context.__exit__(None, None, None)
        self.temp_dir.cleanup()

    def _create_data_ready_task(self) -> str:
        created = self.client.post(
            "/tasks",
            json={
                "name": "合同摘要绑定测试",
                "business_goal": "区分红色和蓝色零件",
            },
        )
        self.assertEqual(created.status_code, 201, created.text)
        task_id = created.json()["task"]["task_id"]
        uploaded = self.client.post(
            f"/tasks/{task_id}/dataset",
            content=self.dataset_payload,
            headers={"Content-Type": "application/zip", "X-Filename": "parts.zip"},
        )
        self.assertEqual(uploaded.status_code, 201, uploaded.text)
        return task_id

    def _confirm(self, task_id: str) -> None:
        task_response = self.client.get(f"/tasks/{task_id}")
        self.assertEqual(task_response.status_code, 200, task_response.text)
        revision = task_response.json()["task"]["contract_revision"]
        expected = {
            field: revision[field]
            for field in (
                "contract_revision_id",
                "contract_sha256",
                "task_id",
                "spec_revision_id",
                "dataset_id",
                "dataset_fingerprint_sha256",
            )
        }
        response = self.client.post(
            f"/tasks/{task_id}/confirm",
            json={
                "data_authorized": True,
                "labels_reviewed": True,
                "gates_reviewed": True,
                "expected_contract_revision": expected,
                "approval": {
                    "actor": "test-user",
                    "checkpoint_id": f"checkpoint:{task_id}",
                },
            },
        )
        self.assertEqual(response.status_code, 200, response.text)

    def _task_path(self, task_id: str) -> Path:
        return self.app.state.training_workspace.tasks_dir / task_id / "task.json"

    def _contract_path(self, task_id: str) -> Path:
        return self.app.state.training_workspace.tasks_dir / task_id / "task_contract.json"

    def _tamper_contract(self, task_id: str) -> None:
        path = self._contract_path(task_id)
        contract = read_json(path)
        contract["release_gates"]["clean_test_accuracy_min"] = 0.0
        write_json(path, contract)

    def _start_and_wait(self, task_id: str) -> None:
        response = start_authorized_task_run(self.client, task_id)
        self.assertEqual(response.status_code, 202, response.text)
        run_id = response.json()["task"]["current_run_id"]
        self.app.state.run_service.wait(run_id, timeout=30)

    def test_confirmed_digest_is_persisted_and_allows_start(self) -> None:
        task_id = self._create_data_ready_task()
        self._confirm(task_id)
        task = read_json(self._task_path(task_id))
        self.assertTrue(task.get("confirmed_contract_sha256"))
        self.assertEqual(
            task["confirmed_contract_sha256"],
            sha256_file(self._contract_path(task_id)),
        )
        self.assertEqual(
            task["confirmed_contract_revision_id"],
            task["current_contract_revision_id"],
        )
        decisions = self.client.get(f"/tasks/{task_id}/approval-decisions")
        self.assertEqual(decisions.status_code, 200, decisions.text)
        approval = decisions.json()["approval_decisions"][0]
        self.assertEqual(approval["actor"], "test-user")
        self.assertEqual(approval["checkpoint_id"], f"checkpoint:{task_id}")
        self.assertEqual(
            approval["contract_revision_id"],
            task["confirmed_contract_revision_id"],
        )
        retrieved = self.client.get(
            f"/tasks/{task_id}/approval-decisions/{approval['approval_decision_id']}"
        )
        self.assertEqual(retrieved.status_code, 200, retrieved.text)
        self.assertEqual(retrieved.json()["approval_decision"], approval)
        self._start_and_wait(task_id)

    def test_confirm_without_expected_identity_fails_closed(self) -> None:
        task_id = self._create_data_ready_task()
        response = self.client.post(
            f"/tasks/{task_id}/confirm",
            json={
                "data_authorized": True,
                "labels_reviewed": True,
                "gates_reviewed": True,
                "approval": {
                    "actor": "test-user",
                    "checkpoint_id": "checkpoint:missing-identity",
                },
            },
        )
        self.assertEqual(response.status_code, 409, response.text)
        task = read_json(self._task_path(task_id))
        self.assertFalse(task["contract_confirmed"])
        self.assertEqual(task.get("approval_decision_ids"), [])

    def test_stale_expected_identity_returns_409_without_approval(self) -> None:
        task_id = self._create_data_ready_task()
        task_response = self.client.get(f"/tasks/{task_id}")
        revision = task_response.json()["task"]["contract_revision"]
        expected = {
            field: revision[field]
            for field in (
                "contract_revision_id",
                "contract_sha256",
                "task_id",
                "spec_revision_id",
                "dataset_id",
                "dataset_fingerprint_sha256",
            )
        }
        expected["contract_sha256"] = "0" * 64
        response = self.client.post(
            f"/tasks/{task_id}/confirm",
            json={
                "data_authorized": True,
                "labels_reviewed": True,
                "gates_reviewed": True,
                "expected_contract_revision": expected,
                "approval": {
                    "actor": "test-user",
                    "checkpoint_id": "checkpoint:stale",
                },
            },
        )
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(
            self.client.get(f"/tasks/{task_id}/approval-decisions").json()[
                "approval_decisions"
            ],
            [],
        )

    def test_disk_tamper_blocks_start_and_requests_reconfirmation(self) -> None:
        task_id = self._create_data_ready_task()
        self._confirm(task_id)
        self._tamper_contract(task_id)
        response = request_task_run_authorization(
            self.client,
            task_id,
            checkpoint_id="native-run:tampered-contract",
        )
        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn("重新确认", response.json()["detail"])

    def test_tamper_resets_persisted_confirmation_state(self) -> None:
        task_id = self._create_data_ready_task()
        self._confirm(task_id)
        self._tamper_contract(task_id)
        response = request_task_run_authorization(
            self.client,
            task_id,
            checkpoint_id="native-run:tampered-contract-reset",
        )
        self.assertEqual(response.status_code, 409, response.text)
        task = read_json(self._task_path(task_id))
        self.assertFalse(task["contract_confirmed"])
        self.assertEqual(task["confirmations"], {})
        self.assertIsNone(task["confirmed_contract_sha256"])
        self.assertEqual(task["status"], "data_ready")

    def test_approval_tamper_blocks_start_and_resets_confirmation(self) -> None:
        task_id = self._create_data_ready_task()
        self._confirm(task_id)
        task = read_json(self._task_path(task_id))
        approval_id = task["current_approval_decision_id"]
        approval_path = (
            self.app.state.training_workspace.tasks_dir
            / task_id
            / "approval_decisions"
            / f"{approval_id}.json"
        )
        approval = read_json(approval_path)
        approval["actor"] = "tampered-user"
        write_json(approval_path, approval)

        response = request_task_run_authorization(
            self.client,
            task_id,
            checkpoint_id="native-run:tampered-approval",
        )
        self.assertEqual(response.status_code, 409, response.text)
        persisted = read_json(self._task_path(task_id))
        self.assertFalse(persisted["contract_confirmed"])
        self.assertIsNone(persisted["current_approval_decision_id"])
        self.assertIn(approval_id, persisted["approval_decision_ids"])
        self.assertTrue(approval_path.is_file())

    def test_reconfirm_binds_new_digest_and_allows_start(self) -> None:
        task_id = self._create_data_ready_task()
        self._confirm(task_id)
        old_digest = read_json(self._task_path(task_id))["confirmed_contract_sha256"]
        old_revision = read_json(self._task_path(task_id))[
            "current_contract_revision_id"
        ]
        response = self.client.patch(
            f"/tasks/{task_id}/contract",
            json={"release_gates": {"clean_test_accuracy_min": 0.0}},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self._confirm(task_id)
        task = read_json(self._task_path(task_id))
        self.assertNotEqual(task["confirmed_contract_sha256"], old_digest)
        self.assertNotEqual(task["current_contract_revision_id"], old_revision)
        revisions = self.client.get(f"/tasks/{task_id}/contract-revisions")
        self.assertEqual(revisions.status_code, 200, revisions.text)
        self.assertEqual(len(revisions.json()["contract_revisions"]), 2)
        self.assertEqual(
            task["confirmed_contract_sha256"],
            sha256_file(self._contract_path(task_id)),
        )
        self._start_and_wait(task_id)

    def test_update_contract_clears_confirmed_digest(self) -> None:
        task_id = self._create_data_ready_task()
        self._confirm(task_id)
        self.assertTrue(read_json(self._task_path(task_id)).get("confirmed_contract_sha256"))
        response = self.client.patch(
            f"/tasks/{task_id}/contract",
            json={"release_gates": {"clean_test_accuracy_min": 0.5}},
        )
        self.assertEqual(response.status_code, 200, response.text)
        task = read_json(self._task_path(task_id))
        self.assertIsNone(task["confirmed_contract_sha256"])
        self.assertFalse(task["contract_confirmed"])
        self.assertEqual(task["confirmations"], {})

    def test_replacing_dataset_clears_confirmed_digest(self) -> None:
        task_id = self._create_data_ready_task()
        self._confirm(task_id)
        before = read_json(self._task_path(task_id))
        self.assertTrue(before.get("confirmed_contract_sha256"))
        response = self.client.post(
            f"/tasks/{task_id}/dataset",
            content=self.dataset_payload,
            headers={"Content-Type": "application/zip", "X-Filename": "parts.zip"},
        )
        self.assertEqual(response.status_code, 201, response.text)
        task = read_json(self._task_path(task_id))
        self.assertNotEqual(task["dataset_id"], before["dataset_id"])
        self.assertIsNone(task["confirmed_contract_sha256"])
        self.assertFalse(task["contract_confirmed"])
        self.assertEqual(task["confirmations"], {})


if __name__ == "__main__":
    unittest.main()
