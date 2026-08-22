#!/usr/bin/env python3
"""Run one commit-pinned Hugging Face -> local training acceptance scenario.

This script deliberately uses the public HTTP contract through FastAPI's test
client.  It performs real Hugging Face metadata lookup and snapshot download,
CPU ONNX feature extraction, local candidate training, deep verification and a
process-style application restart against the same workspace.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from model_harness.io_utils import read_json, sha256_file, write_json
from model_harness.runner import verify_run
from model_harness.server import create_app


DEFAULT_REPO = "pyronear/mobilenet_v3_small"
DEFAULT_COMMIT = "a6a0b39ca1f5b0a247eb0a2e83f06cd95fc03674"


def _dataset_zip() -> bytes:
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for label, base_color, count in (
            ("warm-part", (225, 45, 35), 50),
            ("cool-part", (35, 75, 225), 50),
        ):
            for index in range(count):
                image = Image.new("RGB", (48, 40), base_color)
                draw = ImageDraw.Draw(image)
                if label == "warm-part":
                    draw.rectangle((5 + index % 4, 6, 27, 30), outline="white", width=3)
                    draw.line((3, 35 - index % 5, 43, 35 - index % 5), fill=(40, 210, 90), width=2)
                else:
                    draw.ellipse((7, 5 + index % 4, 34, 32), outline="white", width=3)
                    draw.line((40 - index % 5, 3, 40 - index % 5, 36), fill=(225, 190, 30), width=2)
                marker_x = 2 + (index % 10) * 4
                marker_y = 2 + (index // 10) * 7
                draw.rectangle(
                    (marker_x, marker_y, marker_x + 2, marker_y + 2),
                    fill=(index * 5 % 256, index * 11 % 256, index * 17 % 256),
                )
                image_bytes = io.BytesIO()
                image.save(image_bytes, format="PNG")
                archive.writestr(
                    f"hf-real-parts/{label}/{index:02d}.png",
                    image_bytes.getvalue(),
                )
    return payload.getvalue()


def _new_sample_image() -> bytes:
    output = io.BytesIO()
    image = Image.new("RGB", (53, 41), (215, 48, 35))
    draw = ImageDraw.Draw(image)
    draw.rectangle((8, 7, 32, 33), outline="white", width=3)
    draw.line((3, 37, 48, 37), fill=(30, 210, 95), width=2)
    image.save(output, format="PNG")
    return output.getvalue()


def _require(response: Any, expected: int, label: str) -> dict[str, Any]:
    if response.status_code != expected:
        raise RuntimeError(
            f"{label} failed: HTTP {response.status_code}: {response.text[:1000]}"
        )
    value = response.json()
    if not isinstance(value, dict):
        raise RuntimeError(f"{label} returned a non-object response")
    return value


def _run_once(runtime_dir: Path, repo_id: str, commit: str) -> dict[str, Any]:
    app = create_app(runtime_dir)
    with TestClient(app) as client:
        capability = _require(
            client.get("/model-assets/huggingface/capability"),
            200,
            "HF capability",
        )
        if capability.get("available") is not True:
            raise RuntimeError(f"Hugging Face capability unavailable: {capability}")

        card = _require(
            client.get(
                "/model-assets/huggingface/card",
                params={"repo_id": repo_id, "revision": commit},
            ),
            200,
            "HF model card",
        )["model"]
        if card.get("revision") != commit:
            raise RuntimeError("model card did not resolve to the requested immutable commit")
        if card.get("compatibility", {}).get("state") != "compatible_candidate":
            raise RuntimeError(f"model is not a compatible candidate: {card['compatibility']}")

        created = _require(
            client.post(
                "/tasks",
                json={
                    "name": "HF固定版本零件图片分类",
                    "business_goal": "用自己的零件图片训练一个二分类模型，并使用固定版本的Hugging Face ONNX模型提取特征",
                },
            ),
            201,
            "create task",
        )["task"]
        task_id = created["task_id"]
        if created.get("capability_decision", {}).get("status") != "resolved":
            created = _require(
                client.patch(
                    f"/tasks/{task_id}/spec",
                    json={
                        "base_revision": created["current_spec_revision"],
                        "selected_family": "image_classification",
                        "confirm": True,
                    },
                ),
                200,
                "confirm task spec",
            )["task"]

        rejected = client.post(
            f"/tasks/{task_id}/model-assets/huggingface",
            json={
                "repo_id": repo_id,
                "commit": commit,
                "approval_confirmed": False,
            },
        )
        if rejected.status_code != 409:
            raise RuntimeError("unapproved model download was not rejected")

        attached = _require(
            client.post(
                f"/tasks/{task_id}/model-assets/huggingface",
                json={
                    "repo_id": repo_id,
                    "commit": commit,
                    "approval_confirmed": True,
                },
            ),
            200,
            "approved model download",
        )
        asset = attached["model_asset"]
        if asset["resolved_commit"] != commit or asset["security_status"] != "verified":
            raise RuntimeError("downloaded model asset is not commit-pinned and verified")
        verified_asset = _require(
            client.get(f"/tasks/{task_id}/model-assets/current/verify"),
            200,
            "verify model asset",
        )
        if verified_asset.get("ok") is not True:
            raise RuntimeError(f"model asset verification failed: {verified_asset}")

        uploaded = _require(
            client.post(
                f"/tasks/{task_id}/dataset",
                content=_dataset_zip(),
                headers={"Content-Type": "application/zip", "X-Filename": "hf-parts.zip"},
            ),
            201,
            "upload dataset",
        )["task"]
        report = uploaded["dataset_report"]
        if report["total_images"] != 100 or report["class_count"] != 2:
            raise RuntimeError("unexpected imported image dataset report")

        _require(
            client.patch(
                f"/tasks/{task_id}/contract",
                json={
                    "release_gates": {
                        "clean_test_accuracy_min": 0.5,
                        "clean_test_macro_f1_min": 0.5,
                        "clean_test_worst_class_recall_min": 0.5,
                    }
                },
            ),
            200,
            "update release gates",
        )
        _require(
            client.post(
                f"/tasks/{task_id}/confirm",
                json={
                    "data_authorized": True,
                    "labels_reviewed": True,
                    "gates_reviewed": True,
                },
            ),
            200,
            "confirm contract",
        )
        started = _require(
            client.post(f"/tasks/{task_id}/runs"),
            202,
            "start training",
        )["task"]
        run_id = started["current_run_id"]
        app.state.run_service.wait(run_id, timeout=180)

        result = _require(client.get(f"/runs/{run_id}/result"), 200, "run result")
        if result["status"] != "completed":
            raise RuntimeError(f"training did not complete: {result.get('error')}")
        metrics = result["metrics"]
        training = metrics["training"]
        if training.get("feature_source") != "huggingface_onnx_plus_rgb_gradient_v1":
            raise RuntimeError("training did not use the Hugging Face ONNX feature path")
        provenance = training.get("model_asset") or {}
        if provenance.get("resolved_commit") != commit:
            raise RuntimeError("training metrics lost the fixed model commit")
        if result.get("evaluation_conclusion") != "release_ready" or result.get("release_ready") is not True:
            raise RuntimeError(
                "training completed but the independent integrity, quality, and evidence gates did not pass: "
                f"{result.get('evaluation_conclusion')}"
            )
        events = _require(client.get(f"/runs/{run_id}/events"), 200, "run events")["events"]
        event_types = [item["type"] for item in events]
        for required in (
            "preflight.completed",
            "training.candidates_completed",
            "evaluation.completed",
            "artifacts.packaged",
        ):
            if required not in event_types:
                raise RuntimeError(f"missing real run event: {required}")

        run_dir = runtime_dir / run_id
        deep = verify_run(run_dir, deep=True, registry=app.state.run_service.registry)
        if deep.get("ok") is not True or deep.get("deep_verified") is not True:
            raise RuntimeError(f"deep verification failed: {deep}")
        manifest = read_json(run_dir / "run_manifest.json")
        for artifact in (
            "base_model/model.onnx",
            "base_model/config.json",
            "model_asset_provenance.json",
        ):
            if artifact not in manifest["artifacts"]:
                raise RuntimeError(f"manifest is missing lineage artifact: {artifact}")

        evaluation = _require(
            client.get(f"/tasks/{task_id}/runs/{run_id}/evaluation-report"),
            200,
            "task-owned evaluation report",
        )["evaluation_report"]
        inferred = _require(
            client.post(
                f"/tasks/{task_id}/runs/{run_id}/sample-inferences",
                content=_new_sample_image(),
                headers={
                    "Content-Type": "image/png",
                    "X-Filename": "new-warm-part.png",
                    "X-Sample-Type": "image",
                },
            ),
            201,
            "new sample inference",
        )["sample_inference"]
        if inferred.get("status") != "passed":
            raise RuntimeError(f"new sample inference did not pass: {inferred}")
        bundle = _require(
            client.post(
                f"/tasks/{task_id}/runs/{run_id}/artifact-bundles",
                json={"sample_inference_check_id": inferred["check_id"]},
            ),
            201,
            "artifact bundle",
        )["artifact_bundle"]
        downloaded = client.get(
            f"/tasks/{task_id}/runs/{run_id}/artifact-bundles/"
            f"{bundle['bundle_id']}/download"
        )
        if downloaded.status_code != 200:
            raise RuntimeError(f"artifact bundle download failed: {downloaded.text[:1000]}")
        download_sha256 = hashlib.sha256(downloaded.content).hexdigest()
        if download_sha256 != bundle["archive"]["sha256"]:
            raise RuntimeError("downloaded artifact bundle hash mismatch")
        with zipfile.ZipFile(io.BytesIO(downloaded.content)) as archive:
            bundle_files = sorted(archive.namelist())
        for required_bundle_file in (
            "artifacts/model.joblib",
            "artifacts/base_model/model.onnx",
            "artifacts/base_model/config.json",
            "artifacts/model_asset_provenance.json",
            "evidence/evaluation_report.json",
            "evidence/inference_check.json",
        ):
            if required_bundle_file not in bundle_files:
                raise RuntimeError(
                    f"artifact bundle is missing required file: {required_bundle_file}"
                )

        return {
            "task_id": task_id,
            "run_id": run_id,
            "asset_id": asset["asset_id"],
            "repository": repo_id,
            "requested_commit": commit,
            "resolved_commit": asset["resolved_commit"],
            "license": asset["license"],
            "asset_manifest_sha256": asset["manifest_sha256"],
            "asset_files": asset["files"],
            "dataset": {
                "dataset_id": report["dataset_id"],
                "fingerprint_sha256": report["fingerprint_sha256"],
                "total_images": report["total_images"],
                "class_count": report["class_count"],
            },
            "run": {
                "status": result["status"],
                "total_duration_ms": result["total_duration_ms"],
                "timings_ms": result["timings_ms"],
                "event_count": len(events),
                "event_types": event_types,
                "selected_model": metrics["selected_model"],
                "feature_source": training["feature_source"],
                "feature_count": training["feature_count"],
                "onnx_runtime": training["onnx_runtime"],
                "clean_test": metrics["clean_test"],
                "gate_checks": metrics["gate_checks"],
                "evaluation_conclusion": result["evaluation_conclusion"],
                "release_ready": result["release_ready"],
            },
            "deep_verification": deep,
            "evaluation": {
                "report_id": evaluation["report_id"],
                "integrity_status": evaluation["integrity_status"],
                "metric_gate_status": evaluation["metric_gate_status"],
                "evidence_status": evaluation["evidence_status"],
                "conclusion": evaluation["conclusion"],
                "test_sample_count": evaluation["test_sample_count"],
            },
            "new_sample_inference": {
                "check_id": inferred["check_id"],
                "status": inferred["status"],
                "sample_sha256": inferred["sample"]["sha256"],
                "feature_sha256": inferred["features"]["sha256"],
                "prediction": inferred["prediction"],
                "model_sha256": inferred["model"]["sha256"],
            },
            "artifact_bundle": {
                "bundle_id": bundle["bundle_id"],
                "sha256": bundle["archive"]["sha256"],
                "size_bytes": bundle["archive"]["size_bytes"],
                "download_sha256": download_sha256,
                "files": bundle_files,
                "privacy_boundary": bundle["manifest"]["privacy_boundary"],
            },
            "run_manifest_sha256": sha256_file(run_dir / "run_manifest.json"),
            "artifact_hashes": manifest["artifacts"],
        }


def _verify_restart(runtime_dir: Path, scenario: dict[str, Any]) -> dict[str, Any]:
    app = create_app(runtime_dir)
    with TestClient(app) as client:
        task = _require(
            client.get(f"/tasks/{scenario['task_id']}"),
            200,
            "restart task lookup",
        )["task"]
        result = _require(
            client.get(f"/runs/{scenario['run_id']}/result"),
            200,
            "restart run lookup",
        )
        verified = _require(
            client.get(f"/tasks/{scenario['task_id']}/model-assets/current/verify"),
            200,
            "restart model verification",
        )
        assertions = {
            "same_task_id": task["task_id"] == scenario["task_id"],
            "same_run_id": result["run_id"] == scenario["run_id"],
            "run_completed": result["status"] == "completed",
            "same_asset_id": task.get("selected_model_asset_id") == scenario["asset_id"],
            "asset_still_verified": verified.get("ok") is True,
            "same_commit": task.get("model_asset", {}).get("resolved_commit")
            == scenario["resolved_commit"],
        }
        if not all(assertions.values()):
            raise RuntimeError(f"restart assertions failed: {assertions}")
        return {"passed": True, "assertions": assertions}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-id", default=DEFAULT_REPO)
    parser.add_argument("--commit", default=DEFAULT_COMMIT)
    parser.add_argument(
        "--output-root",
        type=Path,
        default=PROJECT_ROOT / "runs" / "acceptance" / "hf-real",
    )
    args = parser.parse_args()
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    scenario_root = (args.output_root / stamp).resolve()
    runtime_dir = scenario_root / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=False)

    report: dict[str, Any] = {
        "schema_version": "0.1",
        "scenario": "official_huggingface_commit_pinned_image_training",
        "started_at_utc": datetime.now(UTC).isoformat(),
        "status": "running",
    }
    try:
        scenario = _run_once(runtime_dir, args.repo_id, args.commit.lower())
        restart = _verify_restart(runtime_dir, scenario)
        report.update(
            {
                "status": "passed",
                "scenario_evidence": scenario,
                "restart": restart,
                "finished_at_utc": datetime.now(UTC).isoformat(),
            }
        )
    except Exception as exc:
        report.update(
            {
                "status": "failed",
                "error": f"{type(exc).__name__}: {exc}",
                "finished_at_utc": datetime.now(UTC).isoformat(),
            }
        )
        write_json(scenario_root / "report.json", report)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1
    write_json(scenario_root / "report.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
