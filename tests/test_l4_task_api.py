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
                archive.writestr(
                    f"parts/{label}/{index}.png",
                    output.getvalue(),
                )
    return payload.getvalue()


def _new_image() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (31, 25), (215, 40, 40)).save(output, format="PNG")
    return output.getvalue()


def _completed_image_task(client: TestClient, app: object) -> tuple[str, str]:
    created = client.post(
        "/tasks",
        json={
            "name": "L4零件颜色分类",
            "business_goal": "区分红色和蓝色零件",
        },
    )
    assert created.status_code == 201, created.text
    task_id = created.json()["task"]["task_id"]
    uploaded = client.post(
        f"/tasks/{task_id}/dataset",
        content=_image_dataset_zip(),
        headers={"Content-Type": "application/zip", "X-Filename": "parts.zip"},
    )
    assert uploaded.status_code == 201, uploaded.text
    updated = client.patch(
        f"/tasks/{task_id}/contract",
        json={
            "release_gates": {
                "clean_test_accuracy_min": 0.0,
                "clean_test_macro_f1_min": 0.0,
                "clean_test_worst_class_recall_min": 0.0,
            }
        },
    )
    assert updated.status_code == 200, updated.text
    confirmed = client.post(
        f"/tasks/{task_id}/confirm",
        json={
            "data_authorized": True,
            "labels_reviewed": True,
            "gates_reviewed": True,
        },
    )
    assert confirmed.status_code == 200, confirmed.text
    started = client.post(f"/tasks/{task_id}/runs")
    assert started.status_code == 202, started.text
    run_id = started.json()["task"]["current_run_id"]
    app.state.run_service.wait(run_id, timeout=30)  # type: ignore[attr-defined]
    return task_id, run_id


@unittest.skipIf(TestClient is None, "server extra is not installed")
class L4TaskApiTests(unittest.TestCase):
    def test_task_owned_evaluation_sample_and_bundle_form_a_real_product_loop(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            app = create_app(Path(temporary) / "runs")
            with TestClient(app) as client:  # type: ignore[misc]
                task_id, run_id = _completed_image_task(client, app)

                evaluation = client.get(
                    f"/tasks/{task_id}/runs/{run_id}/evaluation-report"
                )
                self.assertEqual(evaluation.status_code, 200, evaluation.text)
                evaluation_body = evaluation.json()
                self.assertEqual(
                    evaluation_body["evaluation_report"]["run_id"],
                    run_id,
                )
                self.assertEqual(
                    evaluation_body["evaluation_report"]["integrity_status"],
                    "passed",
                )
                self.assertEqual(
                    evaluation_body["task"]["control"]["current_stage"],
                    "evaluation",
                )

                inferred = client.post(
                    f"/tasks/{task_id}/runs/{run_id}/sample-inferences",
                    content=_new_image(),
                    headers={
                        "Content-Type": "image/png",
                        "X-Filename": "new-red-part.png",
                        "X-Sample-Type": "image",
                    },
                )
                self.assertEqual(inferred.status_code, 201, inferred.text)
                inference_body = inferred.json()
                sample_check = inference_body["sample_inference"]
                self.assertEqual(sample_check["status"], "passed")
                self.assertEqual(sample_check["sample"]["type"], "image")
                self.assertTrue(sample_check["prediction"])
                self.assertEqual(
                    inference_body["task"]["control"]["current_stage"],
                    "evaluation",
                )

                listed = client.get(
                    f"/tasks/{task_id}/runs/{run_id}/sample-inferences"
                )
                self.assertEqual(listed.status_code, 200, listed.text)
                self.assertEqual(
                    listed.json()["sample_inferences"][0]["check_id"],
                    sample_check["check_id"],
                )
                detail = client.get(
                    f"/tasks/{task_id}/runs/{run_id}/sample-inferences/"
                    f"{sample_check['check_id']}"
                )
                self.assertEqual(detail.status_code, 200, detail.text)
                self.assertEqual(
                    detail.json()["sample_inference"],
                    sample_check,
                )

                built = client.post(
                    f"/tasks/{task_id}/runs/{run_id}/artifact-bundles",
                    json={"sample_inference_check_id": sample_check["check_id"]},
                )
                self.assertEqual(built.status_code, 201, built.text)
                bundle = built.json()["artifact_bundle"]
                bundle_id = bundle["bundle_id"]
                self.assertEqual(bundle["status"], "completed")
                self.assertFalse(
                    bundle["manifest"]["privacy_boundary"]["raw_data_included"]
                )

                bundles = client.get(
                    f"/tasks/{task_id}/runs/{run_id}/artifact-bundles"
                )
                self.assertEqual(bundles.status_code, 200, bundles.text)
                self.assertEqual(
                    bundles.json()["artifact_bundles"][0]["bundle_id"],
                    bundle_id,
                )
                bundle_detail = client.get(
                    f"/tasks/{task_id}/runs/{run_id}/artifact-bundles/{bundle_id}"
                )
                self.assertEqual(bundle_detail.status_code, 200, bundle_detail.text)
                downloaded = client.get(
                    f"/tasks/{task_id}/runs/{run_id}/artifact-bundles/"
                    f"{bundle_id}/download"
                )
                self.assertEqual(downloaded.status_code, 200, downloaded.text)
                self.assertEqual(downloaded.headers["content-type"], "application/zip")
                with zipfile.ZipFile(io.BytesIO(downloaded.content)) as archive:
                    names = set(archive.namelist())
                self.assertIn("bundle_manifest.json", names)
                self.assertIn("evidence/evaluation_report.json", names)
                self.assertIn("evidence/inference_check.json", names)
                self.assertNotIn("task_contract.json", names)

    def test_failed_sample_and_cross_task_access_preserve_run_lineage(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            app = create_app(Path(temporary) / "runs")
            with TestClient(app) as client:  # type: ignore[misc]
                owner_task_id, run_id = _completed_image_task(client, app)
                before_owner = client.get(f"/tasks/{owner_task_id}").json()["task"]
                before_run_ids = list(before_owner["run_ids"])
                before_service_runs = [
                    item["run_id"] for item in app.state.run_service.list_runs()
                ]

                invalid = client.post(
                    f"/tasks/{owner_task_id}/runs/{run_id}/sample-inferences",
                    content=b"not an image",
                    headers={"X-Filename": "broken.png", "X-Sample-Type": "image"},
                )
                self.assertEqual(invalid.status_code, 422, invalid.text)
                invalid_body = invalid.json()
                self.assertEqual(invalid_body["sample_inference"]["status"], "blocked")
                blocked_id = invalid_body["sample_inference"]["check_id"]
                blocked_detail = client.get(
                    f"/tasks/{owner_task_id}/runs/{run_id}/sample-inferences/"
                    f"{blocked_id}"
                )
                self.assertEqual(blocked_detail.status_code, 200, blocked_detail.text)
                self.assertEqual(
                    blocked_detail.json()["sample_inference"]["status"],
                    "blocked",
                )

                other = client.post(
                    "/tasks",
                    json={
                        "name": "其他训练任务",
                        "business_goal": "验证运行隔离",
                    },
                )
                self.assertEqual(other.status_code, 201, other.text)
                other_task_id = other.json()["task"]["task_id"]

                cross_evaluation = client.get(
                    f"/tasks/{other_task_id}/runs/{run_id}/evaluation-report"
                )
                self.assertEqual(cross_evaluation.status_code, 409)
                cross_sample = client.post(
                    f"/tasks/{other_task_id}/runs/{run_id}/sample-inferences",
                    content=_new_image(),
                    headers={"X-Filename": "cross.png", "X-Sample-Type": "image"},
                )
                self.assertEqual(cross_sample.status_code, 409)
                cross_bundle = client.post(
                    f"/tasks/{other_task_id}/runs/{run_id}/artifact-bundles",
                    json={},
                )
                self.assertEqual(cross_bundle.status_code, 409)

                after_owner = client.get(f"/tasks/{owner_task_id}").json()["task"]
                after_other = client.get(f"/tasks/{other_task_id}").json()["task"]
                after_service_runs = [
                    item["run_id"] for item in app.state.run_service.list_runs()
                ]
                self.assertEqual(after_owner["run_ids"], before_run_ids)
                self.assertEqual(after_other["run_ids"], [])
                self.assertEqual(after_service_runs, before_service_runs)
                self.assertIsNone(after_owner["current_result"]["parent_run_id"])


if __name__ == "__main__":
    unittest.main()
