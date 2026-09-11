from __future__ import annotations

import io
import os
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
from tests.contract_confirmation import contract_confirmation_payload
from tests.run_authorization import authorize_task_run, start_authorized_task_run


AGENT_BRIDGE_TOKEN = "test-agent-bridge-token"
AGENT_BRIDGE_HEADERS = {
    "X-Model-Harness-Agent-Token": AGENT_BRIDGE_TOKEN,
}


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


def _ready_image_task(client: TestClient) -> str:
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
        json=contract_confirmation_payload(client, task_id),
    )
    assert confirmed.status_code == 200, confirmed.text
    return task_id


def _completed_image_task(client: TestClient, app: object) -> tuple[str, str]:
    task_id = _ready_image_task(client)
    started = start_authorized_task_run(client, task_id)
    assert started.status_code == 202, started.text
    run_id = started.json()["task"]["current_run_id"]
    app.state.run_service.wait(run_id, timeout=30)  # type: ignore[attr-defined]
    return task_id, run_id


def _authorized_sample_inference(
    client: TestClient,
    task_id: str,
    run_id: str,
    payload: bytes,
    *,
    filename: str,
    checkpoint_id: str,
):
    uploaded = client.post(
        f"/tasks/{task_id}/runs/{run_id}/inference-inputs",
        content=payload,
        headers={"X-Filename": filename, "X-Sample-Type": "image"},
    )
    assert uploaded.status_code == 201, uploaded.text
    inference_input = uploaded.json()["inference_input"]
    authorized = client.post(
        f"/tasks/{task_id}/runs/{run_id}/sample-inference-authorizations",
        headers=AGENT_BRIDGE_HEADERS,
        json={
            "inference_input_id": inference_input["inference_input_id"],
            "inference_input_sha256": inference_input["sha256"],
            "approval": {"actor": "user", "checkpoint_id": checkpoint_id},
        },
    )
    assert authorized.status_code == 201, authorized.text
    authorization_body = authorized.json()
    authorization = authorization_body["sample_inference_authorization"]
    return client.post(
        f"/tasks/{task_id}/runs/{run_id}/inference-inputs/"
        f"{inference_input['inference_input_id']}/execute",
        json={
            "sample_inference_authorization_id": authorization[
                "authorization_id"
            ],
            "authorization_token": authorization_body["authorization_token"],
            "sample_inference_request_sha256": authorization["scope_sha256"],
        },
    )


@unittest.skipIf(TestClient is None, "server extra is not installed")
class L4TaskApiTests(unittest.TestCase):
    def test_run_start_requires_verified_one_shot_backend_authorization(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with patch.dict(
                os.environ,
                {"MODEL_HARNESS_AGENT_BRIDGE_TOKEN": AGENT_BRIDGE_TOKEN},
            ):
                app = create_app(Path(temporary) / "runs")
            with TestClient(app) as client:  # type: ignore[misc]
                task_id = _ready_image_task(client)

                bypassed = client.post(f"/tasks/{task_id}/runs")
                self.assertEqual(bypassed.status_code, 409, bypassed.text)
                task = client.get(f"/tasks/{task_id}").json()["task"]
                self.assertIsNone(task["current_run_id"])
                self.assertEqual(task["run_ids"], [])

                forged = client.post(
                    f"/tasks/{task_id}/run-authorizations",
                    json={
                        "contract_sha256": task["confirmed_contract_sha256"],
                        "dataset_id": task["dataset_id"],
                        "dataset_fingerprint_sha256": task["dataset_report"][
                            "fingerprint_sha256"
                        ],
                        "spec_revision": task["current_spec_revision"],
                        "approval": {
                            "actor": "user",
                            "checkpoint_id": "forged-native-approval",
                        },
                    },
                )
                self.assertEqual(forged.status_code, 403, forged.text)

                issued = authorize_task_run(
                    client,
                    task_id,
                    checkpoint_id="native-run-approval:l4-hard-gate",
                )
                authorization = issued["run_authorization"]
                self.assertEqual(authorization["action"], "start_task_run")
                self.assertEqual(
                    authorization["approval_decision"]["verified_by"],
                    "agent_bridge_token",
                )
                self.assertEqual(
                    authorization["scope"]["prior_task_status"],
                    "ready",
                )
                self.assertIsNone(authorization["scope"]["prior_run_id"])

                wrong_token = client.post(
                    f"/tasks/{task_id}/runs",
                    json={
                        "run_authorization_id": authorization["authorization_id"],
                        "authorization_token": "not-the-issued-token",
                        "run_request_sha256": authorization["scope_sha256"],
                    },
                )
                self.assertEqual(wrong_token.status_code, 409, wrong_token.text)

                started = client.post(
                    f"/tasks/{task_id}/runs",
                    json={
                        "run_authorization_id": authorization["authorization_id"],
                        "authorization_token": issued["authorization_token"],
                        "run_request_sha256": authorization["scope_sha256"],
                    },
                )
                self.assertEqual(started.status_code, 202, started.text)
                run_id = started.json()["task"]["current_run_id"]
                self.assertTrue(run_id)

                replayed = client.post(
                    f"/tasks/{task_id}/runs",
                    json={
                        "run_authorization_id": authorization["authorization_id"],
                        "authorization_token": issued["authorization_token"],
                        "run_request_sha256": authorization["scope_sha256"],
                    },
                )
                self.assertEqual(replayed.status_code, 409, replayed.text)
                self.assertEqual(
                    client.get(f"/tasks/{task_id}").json()["task"]["run_ids"],
                    [run_id],
                )
                app.state.run_service.wait(run_id, timeout=30)  # type: ignore[attr-defined]

    def test_task_owned_evaluation_sample_and_bundle_form_a_real_product_loop(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with patch.dict(
                os.environ,
                {"MODEL_HARNESS_AGENT_BRIDGE_TOKEN": AGENT_BRIDGE_TOKEN},
            ):
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

                legacy = client.post(
                    f"/tasks/{task_id}/runs/{run_id}/sample-inferences",
                    content=_new_image(),
                    headers={
                        "Content-Type": "image/png",
                        "X-Filename": "new-red-part.png",
                        "X-Sample-Type": "image",
                    },
                )
                self.assertEqual(legacy.status_code, 410, legacy.text)
                inferred = _authorized_sample_inference(
                    client,
                    task_id,
                    run_id,
                    _new_image(),
                    filename="new-red-part.png",
                    checkpoint_id="native-sample-loop-approval",
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

                unauthorized_build = client.post(
                    f"/tasks/{task_id}/runs/{run_id}/artifact-bundles",
                    json={"sample_inference_check_id": sample_check["check_id"]},
                )
                self.assertEqual(unauthorized_build.status_code, 409)

                authorization_payload = {
                    "evaluation_report_id": evaluation_body[
                        "evaluation_report"
                    ]["report_id"],
                    "evaluation_report_sha256": evaluation_body[
                        "evaluation_report"
                    ]["report_sha256"],
                    "sample_inference_check_id": sample_check["check_id"],
                    "approval": {
                        "actor": "user",
                        "checkpoint_id": "native-build-checkpoint-1",
                    },
                }
                forged_approval = client.post(
                    f"/tasks/{task_id}/runs/{run_id}/artifact-bundle-authorizations",
                    json=authorization_payload,
                )
                self.assertEqual(forged_approval.status_code, 403)
                wrong_bridge = client.post(
                    f"/tasks/{task_id}/runs/{run_id}/artifact-bundle-authorizations",
                    json=authorization_payload,
                    headers={"X-Model-Harness-Agent-Token": "wrong"},
                )
                self.assertEqual(wrong_bridge.status_code, 403)
                authorized = client.post(
                    f"/tasks/{task_id}/runs/{run_id}/artifact-bundle-authorizations",
                    json=authorization_payload,
                    headers=AGENT_BRIDGE_HEADERS,
                )
                self.assertEqual(authorized.status_code, 201, authorized.text)
                build_authorization = authorized.json()
                build_record = build_authorization[
                    "artifact_bundle_authorization"
                ]
                self.assertEqual(
                    build_record["approval_decision"]["verified_by"],
                    "agent_bridge_token",
                )

                built = client.post(
                    f"/tasks/{task_id}/runs/{run_id}/artifact-bundles",
                    json={
                        "artifact_bundle_authorization_id": build_record[
                            "authorization_id"
                        ],
                        "authorization_token": build_authorization[
                            "authorization_token"
                        ],
                        "bundle_request_sha256": build_record["scope_sha256"],
                        "sample_inference_check_id": sample_check["check_id"],
                    },
                )
                self.assertEqual(built.status_code, 201, built.text)
                bundle = built.json()["artifact_bundle"]
                bundle_id = bundle["bundle_id"]
                self.assertEqual(bundle["status"], "completed")
                self.assertFalse(
                    bundle["manifest"]["privacy_boundary"]["raw_data_included"]
                )
                lineage = bundle["manifest"]["authorization_lineage"]
                self.assertEqual(
                    lineage["authorization_id"],
                    build_record["authorization_id"],
                )
                self.assertEqual(
                    lineage["approval_checkpoint_id"],
                    "native-build-checkpoint-1",
                )
                replayed_build = client.post(
                    f"/tasks/{task_id}/runs/{run_id}/artifact-bundles",
                    json={
                        "artifact_bundle_authorization_id": build_record[
                            "authorization_id"
                        ],
                        "authorization_token": build_authorization[
                            "authorization_token"
                        ],
                        "bundle_request_sha256": build_record["scope_sha256"],
                        "sample_inference_check_id": sample_check["check_id"],
                    },
                )
                self.assertEqual(replayed_build.status_code, 409)

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
                bare_download = client.get(
                    f"/tasks/{task_id}/runs/{run_id}/artifact-bundles/"
                    f"{bundle_id}/download"
                )
                self.assertEqual(bare_download.status_code, 405)
                download_authorized = client.post(
                    f"/tasks/{task_id}/runs/{run_id}/artifact-bundles/"
                    f"{bundle_id}/download-authorizations",
                    json={
                        "manifest_sha256": bundle["manifest_sha256"],
                        "archive_sha256": bundle["archive"]["sha256"],
                        "approval": {
                            "actor": "user",
                            "checkpoint_id": "native-download-checkpoint-1",
                        },
                    },
                    headers=AGENT_BRIDGE_HEADERS,
                )
                self.assertEqual(
                    download_authorized.status_code,
                    201,
                    download_authorized.text,
                )
                download_authorization = download_authorized.json()
                download_record = download_authorization[
                    "artifact_bundle_download_authorization"
                ]
                download_payload = {
                    "artifact_bundle_download_authorization_id": download_record[
                        "authorization_id"
                    ],
                    "authorization_token": download_authorization[
                        "authorization_token"
                    ],
                    "download_request_sha256": download_record["scope_sha256"],
                }
                downloaded = client.post(
                    f"/tasks/{task_id}/runs/{run_id}/artifact-bundles/"
                    f"{bundle_id}/download",
                    json=download_payload,
                )
                self.assertEqual(downloaded.status_code, 200, downloaded.text)
                self.assertEqual(downloaded.headers["content-type"], "application/zip")
                with zipfile.ZipFile(io.BytesIO(downloaded.content)) as archive:
                    names = set(archive.namelist())
                self.assertIn("bundle_manifest.json", names)
                self.assertIn("evidence/evaluation_report.json", names)
                self.assertIn("evidence/inference_check.json", names)
                self.assertNotIn("task_contract.json", names)
                replayed_download = client.post(
                    f"/tasks/{task_id}/runs/{run_id}/artifact-bundles/"
                    f"{bundle_id}/download",
                    json=download_payload,
                )
                self.assertEqual(replayed_download.status_code, 409)
                build_audit = client.get(
                    f"/tasks/{task_id}/delivery-authorizations/"
                    f"{build_record['authorization_id']}"
                )
                self.assertEqual(build_audit.status_code, 200, build_audit.text)
                self.assertEqual(
                    build_audit.json()["delivery_authorization"]["status"],
                    "consumed",
                )
                download_audit = client.get(
                    f"/tasks/{task_id}/delivery-authorizations/"
                    f"{download_record['authorization_id']}"
                )
                self.assertEqual(download_audit.status_code, 200, download_audit.text)
                self.assertEqual(
                    download_audit.json()["delivery_authorization"]["status"],
                    "consumed",
                )

    def test_failed_sample_and_cross_task_access_preserve_run_lineage(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with patch.dict(
                os.environ,
                {"MODEL_HARNESS_AGENT_BRIDGE_TOKEN": AGENT_BRIDGE_TOKEN},
            ):
                app = create_app(Path(temporary) / "runs")
            with TestClient(app) as client:  # type: ignore[misc]
                owner_task_id, run_id = _completed_image_task(client, app)
                before_owner = client.get(f"/tasks/{owner_task_id}").json()["task"]
                before_run_ids = list(before_owner["run_ids"])
                before_service_runs = [
                    item["run_id"] for item in app.state.run_service.list_runs()
                ]

                invalid = _authorized_sample_inference(
                    client,
                    owner_task_id,
                    run_id,
                    b"not an image",
                    filename="broken.png",
                    checkpoint_id="native-blocked-sample-approval",
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
                    f"/tasks/{other_task_id}/runs/{run_id}/inference-inputs",
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
