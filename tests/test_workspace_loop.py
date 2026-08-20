from __future__ import annotations

import io
import tempfile
import unittest
import zipfile
from pathlib import Path

from PIL import Image, ImageDraw

try:
    from fastapi.testclient import TestClient
except ImportError:  # pragma: no cover
    TestClient = None  # type: ignore[assignment]

from model_harness.server import create_app


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
