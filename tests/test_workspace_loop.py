from __future__ import annotations

import io
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw

try:
    from fastapi.testclient import TestClient
except ImportError:  # pragma: no cover
    TestClient = None  # type: ignore[assignment]

from model_harness.server import create_app
from model_harness.errors import HarnessError
from model_harness.io_utils import read_json, sha256_file, write_json


def build_image_dataset_zip() -> bytes:
    archive_bytes = io.BytesIO()
    with zipfile.ZipFile(archive_bytes, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for label, color, count in (("red-parts", (230, 35, 35), 10), ("blue-parts", (35, 75, 230), 6)):
            for index in range(count):
                image = Image.new("RGB", (36, 28), color)
                draw = ImageDraw.Draw(image)
                draw.rectangle((4 + index % 6, 4, 15 + index % 6, 20), outline=(255, 255, 255), width=2)
                draw.line((2, 2 + index * 2, 30, 2 + index * 2), fill=(20 + index, 180, 80), width=1)
                payload = io.BytesIO()
                image.save(payload, format="PNG")
                archive.writestr(f"parts-dataset/{label}/{index}.png", payload.getvalue())
    return archive_bytes.getvalue()


def build_image_dataset_with_duplicate_zip() -> bytes:
    source_bytes = build_image_dataset_zip()
    output = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(source_bytes)) as source, zipfile.ZipFile(
        output, "w", compression=zipfile.ZIP_DEFLATED
    ) as archive:
        for info in source.infolist():
            archive.writestr(info.filename, source.read(info.filename))
        archive.writestr(
            "parts-dataset/red-parts/copy-of-zero.png",
            source.read("parts-dataset/red-parts/0.png"),
        )
    return output.getvalue()


@unittest.skipIf(TestClient is None, "server extra is not installed")
class WorkspaceLoopTests(unittest.TestCase):
    def test_task_owned_resume_reauthorizes_after_restart(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            runs_dir = Path(temp_dir) / "runs"
            app = create_app(runs_dir)
            with TestClient(app) as client:  # type: ignore[misc]
                workspace = app.state.training_workspace
                task = workspace.create_task(
                    "restart resume guard",
                    "resume only through the owning task",
                    recipe_id="digit-classification",
                )
                task_id = task["task_id"]
                contract = app.state.run_service.registry.get_recipe(
                    "digit-classification"
                ).template()
                contract["task_id"] = task_id
                contract_path = workspace._contract_path(task_id)
                write_json(contract_path, contract)
                record = read_json(workspace._task_path(task_id))
                record["contract_confirmed"] = True
                record["confirmed_contract_sha256"] = sha256_file(contract_path)
                record["confirmations"] = {
                    "data_authorized": True,
                    "labels_reviewed": True,
                    "gates_reviewed": True,
                }
                parent = app.state.run_service.submit(
                    contract,
                    workspace_task_id=task_id,
                )
                app.state.run_service.wait(parent.name, timeout=30)
                record["current_run_id"] = parent.name
                record["run_ids"] = [parent.name]
                record["status"] = "interrupted"
                write_json(workspace._task_path(task_id), record)
                parent_run_id = parent.name

            parent_state_path = runs_dir / parent_run_id / "run_state.json"
            parent_state = read_json(parent_state_path)
            parent_state["status"] = "interrupted"
            write_json(parent_state_path, parent_state)

            restarted = create_app(runs_dir)
            with TestClient(restarted) as client:  # type: ignore[misc]
                resumed = client.post(
                    f"/tasks/{task_id}/runs/{parent_run_id}/resume"
                )
                self.assertEqual(resumed.status_code, 202, resumed.text)
                child_run_id = resumed.json()["task"]["current_run_id"]
                self.assertNotEqual(child_run_id, parent_run_id)
                restarted.state.run_service.wait(child_run_id, timeout=30)
                child = restarted.state.run_service.status(child_run_id)
                self.assertEqual(child["task_id"], task_id)
                self.assertEqual(child["parent_run_id"], parent_run_id)

    def test_run_endpoint_fails_before_submit_when_v09_authorization_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            runs_dir = Path(temp_dir) / "runs"
            app = create_app(runs_dir)
            with TestClient(app) as client:  # type: ignore[misc]
                created = client.post(
                    "/tasks",
                    json={
                        "name": "V3 execution guard",
                        "business_goal": "区分红色和蓝色零件",
                    },
                )
                task_id = created.json()["task"]["task_id"]
                uploaded = client.post(
                    f"/tasks/{task_id}/dataset",
                    content=build_image_dataset_zip(),
                    headers={
                        "Content-Type": "application/zip",
                        "X-Filename": "guard.zip",
                    },
                )
                self.assertEqual(uploaded.status_code, 201, uploaded.text)
                confirmed = client.post(
                    f"/tasks/{task_id}/confirm",
                    json={
                        "data_authorized": True,
                        "labels_reviewed": True,
                        "gates_reviewed": True,
                    },
                )
                self.assertEqual(confirmed.status_code, 200, confirmed.text)
                before = set(runs_dir.glob("*"))
                with patch.object(
                    app.state.training_workspace,
                    "authorize_v09_execution",
                    side_effect=HarnessError("blocked_resources fixture"),
                ):
                    response = client.post(f"/tasks/{task_id}/runs")
                self.assertEqual(response.status_code, 409, response.text)
                self.assertIn("blocked_resources", response.json()["detail"])
                self.assertEqual(set(runs_dir.glob("*")), before)
                task = client.get(f"/tasks/{task_id}").json()["task"]
                self.assertEqual(task["run_ids"], [])

    def test_run_intent_recovers_after_task_lineage_write_failure_without_duplicate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            runs_dir = Path(temp_dir) / "runs"
            app = create_app(runs_dir)
            with TestClient(app) as client:  # type: ignore[misc]
                task_id = client.post(
                    "/tasks",
                    json={
                        "name": "durable run intent",
                        "business_goal": "recover one real image training run",
                    },
                ).json()["task"]["task_id"]
                uploaded = client.post(
                    f"/tasks/{task_id}/dataset",
                    content=build_image_dataset_zip(),
                    headers={"X-Filename": "intent.zip"},
                )
                self.assertEqual(uploaded.status_code, 201, uploaded.text)
                confirmed = client.post(
                    f"/tasks/{task_id}/confirm",
                    json={
                        "data_authorized": True,
                        "labels_reviewed": True,
                        "gates_reviewed": True,
                    },
                )
                self.assertEqual(confirmed.status_code, 200, confirmed.text)
                workspace = app.state.training_workspace
                task_path = workspace._task_path(task_id)

                def fail_only_final_lineage_write(path: Path, value: object) -> None:
                    if (
                        Path(path) == task_path
                        and isinstance(value, dict)
                        and value.get("current_run_id")
                        and value.get("pending_run") is None
                    ):
                        raise OSError("injected final task ledger write failure")
                    write_json(Path(path), value)

                with patch(
                    "model_harness.workspace.write_json",
                    side_effect=fail_only_final_lineage_write,
                ):
                    with self.assertRaisesRegex(OSError, "injected final"):
                        workspace.start_run(task_id)

                persisted = read_json(task_path)
                pending_run_id = persisted["pending_run"]["run_id"]
                self.assertEqual(persisted["run_ids"], [])
                app.state.run_service.wait(pending_run_id, timeout=30)

                recovered = workspace.start_run(task_id)
                self.assertEqual(recovered["run_ids"], [pending_run_id])
                self.assertEqual(recovered["current_run_id"], pending_run_id)
                self.assertIsNone(read_json(task_path)["pending_run"])
                self.assertEqual(
                    [item["run_id"] for item in app.state.run_service.list_runs()],
                    [pending_run_id],
                )

            restarted = create_app(runs_dir)
            with TestClient(restarted) as client:  # type: ignore[misc]
                task = client.get(f"/tasks/{task_id}").json()["task"]
                self.assertEqual(task["run_ids"], [pending_run_id])
                self.assertEqual(task["current_run_id"], pending_run_id)

    def test_task_run_rejects_contract_owned_by_another_task_before_submit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            runs_dir = Path(temp_dir) / "runs"
            app = create_app(runs_dir)
            with TestClient(app) as client:  # type: ignore[misc]
                task_id = client.post(
                    "/tasks",
                    json={
                        "name": "contract owner guard",
                        "business_goal": "区分红色和蓝色零件",
                    },
                ).json()["task"]["task_id"]
                uploaded = client.post(
                    f"/tasks/{task_id}/dataset",
                    content=build_image_dataset_zip(),
                    headers={"X-Filename": "guard.zip"},
                )
                self.assertEqual(uploaded.status_code, 201, uploaded.text)
                confirmed = client.post(
                    f"/tasks/{task_id}/confirm",
                    json={
                        "data_authorized": True,
                        "labels_reviewed": True,
                        "gates_reviewed": True,
                    },
                )
                self.assertEqual(confirmed.status_code, 200, confirmed.text)
                workspace = app.state.training_workspace
                contract_path = workspace._contract_path(task_id)
                task_path = workspace._task_path(task_id)
                contract = read_json(contract_path)
                contract["task_id"] = "another-task"
                write_json(contract_path, contract)
                task = read_json(task_path)
                task["confirmed_contract_sha256"] = sha256_file(contract_path)
                write_json(task_path, task)

                before = {item["run_id"] for item in app.state.run_service.list_runs()}
                rejected = client.post(f"/tasks/{task_id}/runs")
                self.assertEqual(rejected.status_code, 409, rejected.text)
                self.assertIn("task_id", rejected.json()["detail"])
                self.assertEqual(
                    {item["run_id"] for item in app.state.run_service.list_runs()},
                    before,
                )

    def test_user_dataset_contract_run_and_artifacts_form_a_real_loop(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            app = create_app(Path(temp_dir) / "runs")
            with TestClient(app) as client:  # type: ignore[misc]
                created = client.post(
                    "/tasks",
                    json={"name": "零件颜色分类", "business_goal": "区分红色和蓝色零件"},
                )
                self.assertEqual(created.status_code, 201, created.text)
                task_id = created.json()["task"]["task_id"]

                blocked = client.post(f"/tasks/{task_id}/runs")
                self.assertEqual(blocked.status_code, 409)

                uploaded = client.post(
                    f"/tasks/{task_id}/dataset",
                    content=build_image_dataset_zip(),
                    headers={"Content-Type": "application/zip", "X-Filename": "parts.zip"},
                )
                self.assertEqual(uploaded.status_code, 201, uploaded.text)
                report = uploaded.json()["task"]["dataset_report"]
                self.assertEqual(report["total_images"], 16)
                self.assertEqual(report["class_count"], 2)

                missing_confirmation = client.post(
                    f"/tasks/{task_id}/confirm",
                    json={"data_authorized": True},
                )
                self.assertEqual(missing_confirmation.status_code, 422)

                updated = client.patch(
                    f"/tasks/{task_id}/contract",
                    json={
                        "release_gates": {
                            "clean_test_accuracy_min": 0.5,
                            "clean_test_macro_f1_min": 0.5,
                            "clean_test_worst_class_recall_min": 0.5,
                        }
                    },
                )
                self.assertEqual(updated.status_code, 200, updated.text)
                confirmed = client.post(
                    f"/tasks/{task_id}/confirm",
                    json={
                        "data_authorized": True,
                        "labels_reviewed": True,
                        "gates_reviewed": True,
                    },
                )
                self.assertEqual(confirmed.status_code, 200, confirmed.text)
                self.assertEqual(confirmed.json()["task"]["status"], "ready")

                started = client.post(f"/tasks/{task_id}/runs")
                self.assertEqual(started.status_code, 202, started.text)
                run_id = started.json()["task"]["current_run_id"]
                app.state.run_service.wait(run_id, timeout=30)

                reopened = client.get(f"/tasks/{task_id}")
                self.assertEqual(reopened.status_code, 200)
                task = reopened.json()["task"]
                self.assertEqual(task["task_id"], task_id)
                self.assertEqual(task["status"], "completed")
                self.assertEqual(task["current_result"]["recipe"], "image-folder-classification")
                self.assertGreater(task["current_result"]["total_duration_ms"], 0)
                self.assertEqual(task["current_result"]["metrics"]["dataset"]["total_images"], 16)

                events = client.get(f"/runs/{run_id}/events").json()["events"]
                self.assertIn("training.candidates_completed", {item["type"] for item in events})
                result = client.get(f"/runs/{run_id}/result").json()
                artifact_names = {item["name"] for item in result["artifacts"]}
                self.assertIn("model.joblib", artifact_names)
                self.assertIn("failure_samples.json", artifact_names)
                self.assertIn(
                    "balance-class-weights",
                    {item["strategy_id"] for item in result["strategies"] if item["actionable"]},
                )
                model = client.get(f"/runs/{run_id}/artifacts/model.joblib")
                self.assertEqual(model.status_code, 200)

                run_state_path = (
                    app.state.run_service.runs_dir / run_id / "run_state.json"
                )
                original_run_state = read_json(run_state_path)
                forged_run_state = dict(original_run_state)
                forged_run_state["task_id"] = "another-task"
                write_json(run_state_path, forged_run_state)
                before_children = {
                    item["run_id"] for item in app.state.run_service.list_runs()
                }
                wrong_owner = client.post(
                    f"/tasks/{task_id}/runs/{run_id}/strategies/balance-class-weights/apply",
                    json={"approval_confirmed": True},
                )
                self.assertEqual(wrong_owner.status_code, 409, wrong_owner.text)
                self.assertEqual(
                    {item["run_id"] for item in app.state.run_service.list_runs()},
                    before_children,
                )
                write_json(run_state_path, original_run_state)

                workspace = app.state.training_workspace
                task_path = workspace._task_path(task_id)
                persisted_task = read_json(task_path)
                persisted_task["contract_confirmed"] = False
                write_json(task_path, persisted_task)
                with patch.object(
                    app.state.run_service,
                    "resume",
                    side_effect=AssertionError("resume must not be called"),
                ):
                    blocked_resume = client.post(
                        f"/tasks/{task_id}/runs/{run_id}/resume"
                    )
                self.assertEqual(blocked_resume.status_code, 409, blocked_resume.text)
                with patch.object(
                    app.state.run_service,
                    "apply_strategy",
                    side_effect=AssertionError("strategy must not be called"),
                ):
                    blocked_strategy = client.post(
                        f"/tasks/{task_id}/runs/{run_id}/strategies/balance-class-weights/apply",
                        json={"approval_confirmed": True},
                    )
                self.assertEqual(
                    blocked_strategy.status_code, 409, blocked_strategy.text
                )
                self.assertEqual(
                    {item["run_id"] for item in app.state.run_service.list_runs()},
                    before_children,
                )
                persisted_task["contract_confirmed"] = True
                write_json(task_path, persisted_task)

                contract_path = workspace._contract_path(task_id)
                original_contract = read_json(contract_path)
                changed_contract = read_json(contract_path)
                changed_contract["release_gates"][
                    "clean_test_accuracy_min"
                ] = 0.51
                write_json(contract_path, changed_contract)
                persisted_task["confirmed_contract_sha256"] = sha256_file(
                    contract_path
                )
                write_json(task_path, persisted_task)
                stale_parent = client.post(
                    f"/tasks/{task_id}/runs/{run_id}/strategies/balance-class-weights/apply",
                    json={"approval_confirmed": True},
                )
                self.assertEqual(stale_parent.status_code, 409, stale_parent.text)
                self.assertIn("当前已确认训练合同", stale_parent.text)
                self.assertEqual(
                    {item["run_id"] for item in app.state.run_service.list_runs()},
                    before_children,
                )
                write_json(contract_path, original_contract)
                persisted_task["confirmed_contract_sha256"] = sha256_file(
                    contract_path
                )
                write_json(task_path, persisted_task)

                preview = report["previews"][0]["relative_path"]
                dataset_id = report["dataset_id"]
                image = client.get(f"/tasks/{task_id}/datasets/{dataset_id}/{preview}")
                self.assertEqual(image.status_code, 200)
                self.assertTrue(image.headers["content-type"].startswith("image/"))

                optimized = client.post(
                    f"/tasks/{task_id}/runs/{run_id}/strategies/balance-class-weights/apply",
                    json={"approval_confirmed": True},
                )
                self.assertEqual(optimized.status_code, 202, optimized.text)
                child_run_id = optimized.json()["task"]["current_run_id"]
                self.assertNotEqual(child_run_id, run_id)
                app.state.run_service.wait(child_run_id, timeout=30)
                child = client.get(f"/runs/{child_run_id}/result").json()
                self.assertEqual(child["parent_run_id"], run_id)
                self.assertEqual(
                    child["optimization_history"][0]["strategy_id"],
                    "balance-class-weights",
                )

    def test_dataset_rejects_too_few_images(self) -> None:
        archive_bytes = io.BytesIO()
        with zipfile.ZipFile(archive_bytes, "w") as archive:
            for label, color in (("a", "white"), ("b", "black")):
                image = Image.new("RGB", (8, 8), color)
                payload = io.BytesIO()
                image.save(payload, format="PNG")
                archive.writestr(f"{label}/one.png", payload.getvalue())
        with tempfile.TemporaryDirectory() as temp_dir:
            app = create_app(Path(temp_dir) / "runs")
            with TestClient(app) as client:  # type: ignore[misc]
                task_id = client.post(
                    "/tasks",
                    json={"name": "bad", "business_goal": "bad dataset"},
                ).json()["task"]["task_id"]
                response = client.post(
                    f"/tasks/{task_id}/dataset",
                    content=archive_bytes.getvalue(),
                    headers={"X-Filename": "bad.zip"},
                )
                self.assertEqual(response.status_code, 422)
                self.assertIn("每类至少需要5张", response.json()["detail"])

    def test_dataset_rejects_same_image_under_different_labels(self) -> None:
        archive_bytes = io.BytesIO()
        image = Image.new("RGB", (8, 8), "white")
        payload = io.BytesIO()
        image.save(payload, format="PNG")
        with zipfile.ZipFile(archive_bytes, "w") as archive:
            archive.writestr("a/shared.png", payload.getvalue())
            archive.writestr("b/shared.png", payload.getvalue())
        with tempfile.TemporaryDirectory() as temp_dir:
            app = create_app(Path(temp_dir) / "runs")
            with TestClient(app) as client:  # type: ignore[misc]
                task_id = client.post(
                    "/tasks",
                    json={"name": "conflict", "business_goal": "reject label conflict"},
                ).json()["task"]["task_id"]
                response = client.post(
                    f"/tasks/{task_id}/dataset",
                    content=archive_bytes.getvalue(),
                    headers={"X-Filename": "conflict.zip"},
                )
                self.assertEqual(response.status_code, 422)
                self.assertIn("相同图片被放入不同类别", response.json()["detail"])

    def test_dataset_excludes_same_label_duplicates_before_splitting(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            app = create_app(Path(temp_dir) / "runs")
            with TestClient(app) as client:  # type: ignore[misc]
                task_id = client.post(
                    "/tasks",
                    json={"name": "dedupe", "business_goal": "prevent split leakage"},
                ).json()["task"]["task_id"]
                response = client.post(
                    f"/tasks/{task_id}/dataset",
                    content=build_image_dataset_with_duplicate_zip(),
                    headers={"X-Filename": "duplicates.zip"},
                )
                self.assertEqual(response.status_code, 201, response.text)
                report = response.json()["task"]["dataset_report"]
                self.assertEqual(report["total_images"], 16)
                self.assertEqual(report["rejected_count"], 1)
                self.assertEqual(report["duplicate_groups"], 1)
                self.assertTrue(
                    any("避免划分泄漏" in risk["message"] for risk in report["risks"])
                )


if __name__ == "__main__":
    unittest.main()
