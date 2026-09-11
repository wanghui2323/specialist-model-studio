from __future__ import annotations

import csv
import io
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

try:
    from fastapi.testclient import TestClient
except ImportError:  # pragma: no cover
    TestClient = None  # type: ignore[assignment]

from model_harness.server import create_app
from model_harness.io_utils import read_json, write_json as durable_write_json
import model_harness.workspace as workspace_module


def regression_csv(*, offset: float = 0.0) -> bytes:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["sample_id", "temperature", "quality"])
    for index in range(40):
        temperature = 18.0 + index * 0.25
        writer.writerow(
            [
                f"sample-{index:03d}",
                temperature,
                round(temperature * 0.4 + offset, 4),
            ]
        )
    return output.getvalue().encode("utf-8")


@unittest.skipIf(TestClient is None, "server extra is not installed")
class DatasetUploadIdempotencyTests(unittest.TestCase):
    def _create_task(self, client: TestClient) -> str:  # type: ignore[type-arg]
        response = client.post(
            "/tasks",
            json={
                "name": "幂等数据导入",
                "business_goal": "根据温度预测质量数值",
                "capability_request": {
                    "modality": "tabular",
                    "objective": "regression",
                    "target_kind": "numeric",
                    "target_column": "quality",
                },
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        return str(response.json()["task"]["task_id"])

    @staticmethod
    def _headers(request_id: str) -> dict[str, str]:
        return {
            "Content-Type": "text/csv",
            "X-Filename": "measurements.csv",
            "X-Target-Column": "quality",
            "X-Ignored-Columns": "sample_id",
            "X-Request-ID": request_id,
        }

    def test_same_request_replays_one_dataset_and_changed_payload_conflicts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            runs_dir = Path(temp_dir) / "runs"
            request_id = "dataset-upload-request-1"
            payload = regression_csv()

            app = create_app(runs_dir)
            with TestClient(app) as client:  # type: ignore[misc]
                task_id = self._create_task(client)
                endpoint = f"/tasks/{task_id}/dataset"

                first = client.post(
                    endpoint,
                    content=payload,
                    headers=self._headers(request_id),
                )
                self.assertEqual(first.status_code, 201, first.text)
                first_body = first.json()
                dataset_id = first_body["dataset_upload"]["dataset_id"]
                self.assertEqual(first_body["task"]["dataset_id"], dataset_id)
                self.assertFalse(first_body["idempotent_replay"])

                replay = client.post(
                    endpoint,
                    content=payload,
                    headers=self._headers(request_id),
                )
                self.assertEqual(replay.status_code, 201, replay.text)
                replay_body = replay.json()
                self.assertTrue(replay_body["idempotent_replay"])
                self.assertEqual(
                    replay_body["dataset_upload"]["dataset_id"],
                    dataset_id,
                )
                self.assertEqual(replay_body["task"]["dataset_history"], [dataset_id])

                conflict = client.post(
                    endpoint,
                    content=regression_csv(offset=1.0),
                    headers=self._headers(request_id),
                )
                self.assertEqual(conflict.status_code, 409, conflict.text)
                self.assertIn("x-request-id", conflict.text)

                receipt = client.get(
                    f"/tasks/{task_id}/dataset-upload-receipts/{request_id}"
                )
                self.assertEqual(receipt.status_code, 200, receipt.text)
                self.assertEqual(
                    receipt.json()["dataset_upload"]["dataset_id"],
                    dataset_id,
                )
                self.assertEqual(receipt.json()["task"]["dataset_id"], dataset_id)

            restarted = create_app(runs_dir)
            with TestClient(restarted) as client:  # type: ignore[misc]
                replay_after_restart = client.post(
                    f"/tasks/{task_id}/dataset",
                    content=payload,
                    headers=self._headers(request_id),
                )
                self.assertEqual(
                    replay_after_restart.status_code,
                    201,
                    replay_after_restart.text,
                )
                self.assertTrue(replay_after_restart.json()["idempotent_replay"])
                self.assertEqual(
                    replay_after_restart.json()["dataset_upload"]["dataset_id"],
                    dataset_id,
                )
                self.assertEqual(
                    replay_after_restart.json()["task"]["dataset_history"],
                    [dataset_id],
                )

    def test_processing_receipt_recovers_after_dataset_commit_crash(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            runs_dir = Path(temp_dir) / "runs"
            request_id = "dataset-upload-crash-after-attach"
            payload = regression_csv()
            app = create_app(runs_dir)
            with TestClient(app) as client:  # type: ignore[misc]
                task_id = self._create_task(client)
                workspace = app.state.training_workspace

                def crash_before_completed_receipt(path: Path, value: object) -> None:
                    if (
                        path.parent.name == "dataset_upload_receipts"
                        and isinstance(value, dict)
                        and value.get("status") == "completed"
                    ):
                        raise SystemExit("simulated crash after dataset commit")
                    durable_write_json(path, value)

                with patch(
                    "model_harness.workspace.write_json",
                    side_effect=crash_before_completed_receipt,
                ):
                    with self.assertRaisesRegex(SystemExit, "simulated crash"):
                        workspace.attach_dataset_idempotent(
                            task_id,
                            payload,
                            "measurements.csv",
                            request_id=request_id,
                            options={
                                "target_column": "quality",
                                "ignored_columns": ["sample_id"],
                            },
                        )

                committed = workspace.get_task(task_id)
                self.assertEqual(len(committed["dataset_history"]), 1)

            restarted = create_app(runs_dir)
            with TestClient(restarted):  # type: ignore[misc]
                task, receipt, replayed = (
                    restarted.state.training_workspace.attach_dataset_idempotent(
                        task_id,
                        payload,
                        "measurements.csv",
                        request_id=request_id,
                        options={
                            "target_column": "quality",
                            "ignored_columns": ["sample_id"],
                        },
                    )
                )
                self.assertTrue(replayed)
                self.assertTrue(receipt["recovered_after_restart"])
                self.assertEqual(receipt["dataset_id"], task["dataset_id"])
                self.assertEqual(task["dataset_history"], [task["dataset_id"]])

    def test_processing_receipt_fails_closed_when_dataset_identity_drifts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            runs_dir = Path(temp_dir) / "runs"
            request_id = "dataset-upload-drift-after-attach"
            payload = regression_csv()
            app = create_app(runs_dir)
            with TestClient(app) as client:  # type: ignore[misc]
                task_id = self._create_task(client)
                workspace = app.state.training_workspace

                def crash_before_completed_receipt(path: Path, value: object) -> None:
                    if (
                        path.parent.name == "dataset_upload_receipts"
                        and isinstance(value, dict)
                        and value.get("status") == "completed"
                    ):
                        raise SystemExit("simulated crash after dataset commit")
                    durable_write_json(path, value)

                with patch(
                    "model_harness.workspace.write_json",
                    side_effect=crash_before_completed_receipt,
                ):
                    with self.assertRaisesRegex(SystemExit, "simulated crash"):
                        workspace.attach_dataset_idempotent(
                            task_id,
                            payload,
                            "measurements.csv",
                            request_id=request_id,
                            options={
                                "target_column": "quality",
                                "ignored_columns": ["sample_id"],
                            },
                        )

                task = workspace.get_task(task_id)
                report_path = (
                    workspace._task_dir(task_id)
                    / "datasets"
                    / task["dataset_id"]
                    / "dataset_report.json"
                )
                report = read_json(report_path)
                report["upload_request_digest_sha256"] = "0" * 64
                durable_write_json(report_path, report)

            restarted = create_app(runs_dir)
            with TestClient(restarted):  # type: ignore[misc]
                with self.assertRaisesRegex(Exception, "上传身份无法核对"):
                    restarted.state.training_workspace.attach_dataset_idempotent(
                        task_id,
                        payload,
                        "measurements.csv",
                        request_id=request_id,
                        options={
                            "target_column": "quality",
                            "ignored_columns": ["sample_id"],
                        },
                    )

    def test_processing_receipt_retries_when_crash_precedes_dataset_commit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            runs_dir = Path(temp_dir) / "runs"
            request_id = "dataset-upload-crash-before-attach"
            payload = regression_csv()
            app = create_app(runs_dir)
            with TestClient(app) as client:  # type: ignore[misc]
                task_id = self._create_task(client)
                workspace = app.state.training_workspace
                with patch.object(
                    workspace,
                    "attach_dataset",
                    side_effect=SystemExit("simulated crash before dataset commit"),
                ):
                    with self.assertRaisesRegex(SystemExit, "simulated crash"):
                        workspace.attach_dataset_idempotent(
                            task_id,
                            payload,
                            "measurements.csv",
                            request_id=request_id,
                            options={
                                "target_column": "quality",
                                "ignored_columns": ["sample_id"],
                            },
                        )
                self.assertEqual(workspace.get_task(task_id)["dataset_history"], [])

            restarted = create_app(runs_dir)
            with TestClient(restarted):  # type: ignore[misc]
                task, receipt, replayed = (
                    restarted.state.training_workspace.attach_dataset_idempotent(
                        task_id,
                        payload,
                        "measurements.csv",
                        request_id=request_id,
                        options={
                            "target_column": "quality",
                            "ignored_columns": ["sample_id"],
                        },
                    )
                )
                self.assertFalse(replayed)
                self.assertFalse(receipt["recovered_after_restart"])
                self.assertEqual(task["dataset_history"], [task["dataset_id"]])

    def test_concurrent_same_request_across_workspaces_commits_once(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace_dir = root / "shared-workspace"
            app_one = create_app(root / "runs-one", workspace_dir=workspace_dir)
            app_two = create_app(root / "runs-two", workspace_dir=workspace_dir)
            payload = regression_csv()
            request_id = "dataset-upload-concurrent"

            with TestClient(app_one) as client_one, TestClient(app_two):  # type: ignore[misc]
                task_id = self._create_task(client_one)
                workspaces = [
                    app_one.state.training_workspace,
                    app_two.state.training_workspace,
                ]

                def upload(index: int) -> tuple[str, bool]:
                    task, receipt, replayed = workspaces[index % 2].attach_dataset_idempotent(
                        task_id,
                        payload,
                        "measurements.csv",
                        request_id=request_id,
                        options={
                            "target_column": "quality",
                            "ignored_columns": ["sample_id"],
                        },
                    )
                    self.assertEqual(receipt["dataset_id"], task["dataset_id"])
                    return str(receipt["dataset_id"]), replayed

                with ThreadPoolExecutor(max_workers=8) as executor:
                    results = list(executor.map(upload, range(8)))

                dataset_ids = {dataset_id for dataset_id, _ in results}
                self.assertEqual(len(dataset_ids), 1)
                self.assertEqual(sum(not replayed for _, replayed in results), 1)
                task = app_one.state.training_workspace.get_task(task_id)
                self.assertEqual(task["dataset_history"], [task["dataset_id"]])

    def test_windows_lock_retries_and_unlocks_only_after_acquisition(self) -> None:
        class FakeMsvcrt:
            LK_NBLCK = 1
            LK_UNLCK = 2

            def __init__(self) -> None:
                self.failures_remaining = 2
                self.calls: list[int] = []

            def locking(self, _fd: int, mode: int, _count: int) -> None:
                self.calls.append(mode)
                if mode == self.LK_NBLCK and self.failures_remaining:
                    self.failures_remaining -= 1
                    raise OSError("busy")

        with tempfile.TemporaryDirectory() as temp_dir:
            app = create_app(Path(temp_dir) / "runs")
            with TestClient(app) as client:  # type: ignore[misc]
                task_id = self._create_task(client)
                fake = FakeMsvcrt()
                with (
                    patch.object(workspace_module, "fcntl", None),
                    patch.object(workspace_module, "msvcrt", fake),
                    patch.object(workspace_module.time, "sleep", return_value=None),
                ):
                    with app.state.training_workspace._dataset_upload_process_lock(
                        task_id
                    ):
                        pass
                self.assertEqual(
                    fake.calls,
                    [fake.LK_NBLCK, fake.LK_NBLCK, fake.LK_NBLCK, fake.LK_UNLCK],
                )

    def test_windows_lock_timeout_does_not_unlock_unacquired_lock(self) -> None:
        class BusyMsvcrt:
            LK_NBLCK = 1
            LK_UNLCK = 2

            def __init__(self) -> None:
                self.calls: list[int] = []

            def locking(self, _fd: int, mode: int, _count: int) -> None:
                self.calls.append(mode)
                raise OSError("busy")

        with tempfile.TemporaryDirectory() as temp_dir:
            app = create_app(Path(temp_dir) / "runs")
            with TestClient(app) as client:  # type: ignore[misc]
                task_id = self._create_task(client)
                fake = BusyMsvcrt()
                with (
                    patch.object(workspace_module, "fcntl", None),
                    patch.object(workspace_module, "msvcrt", fake),
                    patch.object(
                        workspace_module,
                        "DATASET_UPLOAD_LOCK_TIMEOUT_SECONDS",
                        0.0,
                    ),
                ):
                    with self.assertRaisesRegex(Exception, "另一进程正在导入"):
                        with app.state.training_workspace._dataset_upload_process_lock(
                            task_id
                        ):
                            pass
                self.assertEqual(fake.calls, [fake.LK_NBLCK])


if __name__ == "__main__":
    unittest.main()
