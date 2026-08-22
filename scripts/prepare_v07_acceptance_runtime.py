#!/usr/bin/env python3
"""Prepare restart-verifiable v0.7 image, tabular, and audio journeys.

The production path uses the official fixed-commit Hugging Face image scenario.
``--skip-hf`` keeps tests offline by running the built-in image Recipe while
preserving the same EvaluationReport -> new sample -> ArtifactBundle evidence
chain. All product mutations go through the real local HTTP API.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import sys
import wave
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from model_harness.io_utils import write_json
from model_harness.server import create_app
from scripts.run_hf_real_scenario import DEFAULT_COMMIT, DEFAULT_REPO, _run_once


JOURNEY_SCHEMA_VERSION = "0.1"
FAMILIES = ("image", "tabular", "audio")


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _require(response: Any, status: int, label: str) -> dict[str, Any]:
    if response.status_code != status:
        raise RuntimeError(
            f"{label} failed: HTTP {response.status_code}: {response.text[:1000]}"
        )
    value = response.json()
    if not isinstance(value, dict):
        raise RuntimeError(f"{label} returned a non-object response")
    return value


def _prepare_empty_runtime(runtime_dir: str | Path) -> Path:
    selected = Path(runtime_dir).expanduser()
    if selected.exists():
        if not selected.is_dir():
            raise ValueError("runtime path must be a directory")
        if any(selected.iterdir()):
            raise ValueError("runtime directory must be empty")
    else:
        selected.mkdir(parents=True)
    return selected.resolve()


def _image_dataset_zip(samples_per_class: int = 50) -> bytes:
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for label, color in (
            ("warm-part", (225, 42, 35)),
            ("cool-part", (35, 72, 225)),
        ):
            for index in range(samples_per_class):
                image = Image.new("RGB", (44, 36), color)
                draw = ImageDraw.Draw(image)
                if label == "warm-part":
                    draw.rectangle(
                        (5 + index % 4, 6, 26, 29),
                        outline="white",
                        width=2,
                    )
                else:
                    draw.ellipse(
                        (7, 5 + index % 4, 33, 30),
                        outline="white",
                        width=2,
                    )
                draw.point(
                    (2 + index % 20, 32 - index % 5),
                    fill=(index * 7 % 255, index * 13 % 255, index * 19 % 255),
                )
                image_bytes = io.BytesIO()
                image.save(image_bytes, format="PNG")
                archive.writestr(
                    f"local-image/{label}/{index:03d}.png",
                    image_bytes.getvalue(),
                )
    return payload.getvalue()


def _new_image() -> bytes:
    payload = io.BytesIO()
    image = Image.new("RGB", (49, 39), (215, 48, 38))
    draw = ImageDraw.Draw(image)
    draw.rectangle((8, 7, 32, 31), outline="white", width=3)
    image.save(payload, format="PNG")
    return payload.getvalue()


def _tabular_csv(row_count: int = 180) -> bytes:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        ["sample_id", "temperature", "pressure", "machine_type", "quality"]
    )
    for index in range(row_count):
        temperature = 18.0 + (index % 37) * 0.7
        pressure = 90.0 + (index % 23) * 1.3
        machine_type = ("A", "B", "C")[index % 3]
        machine_effect = {"A": 1.2, "B": -0.4, "C": 0.6}[machine_type]
        quality = (
            0.42 * temperature
            - 0.08 * pressure
            + machine_effect
            + (index % 5) * 0.03
        )
        writer.writerow(
            [
                f"S-{index:04d}",
                temperature,
                pressure,
                machine_type,
                round(quality, 4),
            ]
        )
    return output.getvalue().encode("utf-8")


def _wav_bytes(
    frequency: float,
    *,
    speaker_index: int,
    sample_rate: int = 16_000,
    duration: float = 0.45,
) -> bytes:
    rng = np.random.default_rng(20_000 + speaker_index)
    timeline = np.arange(
        int(sample_rate * duration),
        dtype=np.float64,
    ) / sample_rate
    phase = (speaker_index % 7) * 0.13
    signal = (
        0.58 * np.sin(2 * np.pi * frequency * timeline + phase)
        + 0.13 * np.sin(2 * np.pi * frequency * 2.01 * timeline)
        + rng.normal(0.0, 0.012, size=len(timeline))
    )
    pcm = np.round(np.clip(signal, -1.0, 1.0) * 32767.0).astype("<i2")
    payload = io.BytesIO()
    with wave.open(payload, "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(sample_rate)
        target.writeframes(pcm.tobytes())
    return payload.getvalue()


def _audio_dataset_zip() -> bytes:
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for speaker_index in range(50):
            speaker = f"speaker{speaker_index:02d}"
            archive.writestr(
                f"yes/{speaker}_nohash_0.wav",
                _wav_bytes(360.0, speaker_index=speaker_index),
            )
            archive.writestr(
                f"no/{speaker}_nohash_0.wav",
                _wav_bytes(960.0, speaker_index=100 + speaker_index),
            )
    return payload.getvalue()


def _evaluation_status(report: dict[str, Any]) -> str:
    if report.get("integrity_status") != "passed":
        raise RuntimeError(f"run integrity did not pass: {report}")
    evidence_status = str(report.get("evidence_status"))
    if evidence_status == "insufficient_evidence":
        return "insufficient_evidence"
    if report.get("metric_gate_status") == "failed":
        return "quality_failed"
    if report.get("metric_gate_status") != "passed":
        raise RuntimeError(f"metric gate status is not final: {report}")
    if evidence_status != "sufficient":
        raise RuntimeError(f"evidence status is not final: {report}")
    return "passed"


def _complete_l4_chain(
    client: TestClient,
    *,
    task_id: str,
    run_id: str,
    sample: bytes,
    filename: str,
    sample_type: str,
) -> dict[str, Any]:
    result = _require(client.get(f"/runs/{run_id}/result"), 200, "run result")
    if result.get("status") != "completed":
        raise RuntimeError(f"run did not complete: {result.get('error')}")
    evaluation = _require(
        client.get(f"/tasks/{task_id}/runs/{run_id}/evaluation-report"),
        200,
        "evaluation report",
    )["evaluation_report"]
    evaluation_status = _evaluation_status(evaluation)
    inference = _require(
        client.post(
            f"/tasks/{task_id}/runs/{run_id}/sample-inferences",
            content=sample,
            headers={
                "X-Filename": filename,
                "X-Sample-Type": sample_type,
            },
        ),
        201,
        "new sample inference",
    )["sample_inference"]
    if inference.get("status") != "passed":
        raise RuntimeError(f"new sample inference did not pass: {inference}")
    bundle = _require(
        client.post(
            f"/tasks/{task_id}/runs/{run_id}/artifact-bundles",
            json={"sample_inference_check_id": inference["check_id"]},
        ),
        201,
        "artifact bundle",
    )["artifact_bundle"]
    if bundle.get("status") != "completed":
        raise RuntimeError(f"artifact bundle did not complete: {bundle}")
    privacy = bundle.get("manifest", {}).get("privacy_boundary", {})
    if privacy != {
        "raw_data_included": False,
        "test_references_included": False,
        "internal_state_included": False,
        "absolute_paths_in_manifest": False,
    }:
        raise RuntimeError(f"artifact bundle privacy boundary failed: {privacy}")
    downloaded = client.get(
        f"/tasks/{task_id}/runs/{run_id}/artifact-bundles/"
        f"{bundle['bundle_id']}/download"
    )
    if downloaded.status_code != 200:
        raise RuntimeError(
            f"artifact bundle download failed: HTTP {downloaded.status_code}"
        )
    download_sha256 = hashlib.sha256(downloaded.content).hexdigest()
    if download_sha256 != bundle["archive"]["sha256"]:
        raise RuntimeError("artifact bundle download hash mismatch")
    required_ids = {
        "task_id": task_id,
        "run_id": run_id,
        "evaluation_report_id": evaluation.get("report_id"),
        "inference_check_id": inference.get("check_id"),
        "artifact_bundle_id": bundle.get("bundle_id"),
    }
    if not all(isinstance(value, str) and value for value in required_ids.values()):
        raise RuntimeError(f"journey is missing a persistent id: {required_ids}")
    return {
        **required_ids,
        "recipe": result.get("recipe"),
        "training_status": "completed",
        "evaluation_status": evaluation_status,
        "evaluation_conclusion": evaluation.get("conclusion"),
        "inference_status": "passed",
        "bundle_status": "completed",
        "bundle_sha256": bundle["archive"]["sha256"],
        "sample_sha256": inference["sample"]["sha256"],
    }


def _start_and_wait(
    client: TestClient,
    app: Any,
    task_id: str,
    *,
    timeout: float = 60,
) -> str:
    started = _require(
        client.post(f"/tasks/{task_id}/runs"),
        202,
        "start run",
    )["task"]
    run_id = str(started["current_run_id"])
    app.state.run_service.wait(run_id, timeout=timeout)
    return run_id


def _prepare_local_image(client: TestClient, app: Any) -> dict[str, Any]:
    task = _require(
        client.post(
            "/tasks",
            json={
                "name": "L5本地图片分类",
                "business_goal": "区分暖色和冷色零件",
                "recipe_id": "image-folder-classification",
            },
        ),
        201,
        "create image task",
    )["task"]
    task_id = str(task["task_id"])
    _require(
        client.post(
            f"/tasks/{task_id}/dataset",
            content=_image_dataset_zip(),
            headers={"X-Filename": "local-parts.zip"},
        ),
        201,
        "upload image dataset",
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
        "confirm image contract",
    )
    run_id = _start_and_wait(client, app, task_id)
    journey = _complete_l4_chain(
        client,
        task_id=task_id,
        run_id=run_id,
        sample=_new_image(),
        filename="new-warm-part.png",
        sample_type="image",
    )
    journey.update(
        {
            "model_asset_id": None,
            "image_source": "builtin_image_recipe_skip_hf",
        }
    )
    return journey


def _prepare_tabular(client: TestClient, app: Any) -> dict[str, Any]:
    task = _require(
        client.post(
            "/tasks",
            json={
                "name": "L5质量分预测",
                "business_goal": "根据设备参数预测质量分",
                "capability_request": {
                    "modality": "tabular",
                    "objective": "regression",
                    "target_kind": "numeric",
                    "target_column": "quality",
                },
            },
        ),
        201,
        "create tabular task",
    )["task"]
    task_id = str(task["task_id"])
    _require(
        client.post(
            f"/tasks/{task_id}/dataset",
            content=_tabular_csv(),
            headers={
                "Content-Type": "text/csv",
                "X-Filename": "quality.csv",
                "X-Target-Column": "quality",
                "X-Ignored-Columns": "sample_id",
            },
        ),
        201,
        "upload tabular dataset",
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
        "confirm tabular contract",
    )
    run_id = _start_and_wait(client, app, task_id)
    sample = json.dumps(
        {
            "temperature": 27.1,
            "pressure": 104.3,
            "machine_type": "B",
            "sample_id": "new-device-row",
        },
        ensure_ascii=False,
    ).encode("utf-8")
    return _complete_l4_chain(
        client,
        task_id=task_id,
        run_id=run_id,
        sample=sample,
        filename="new-device-row.json",
        sample_type="tabular",
    )


def _prepare_audio(client: TestClient, app: Any) -> dict[str, Any]:
    payload = _audio_dataset_zip()
    task = _require(
        client.post(
            "/tasks",
            json={
                "name": "L5离线关键词分类",
                "business_goal": "识别 yes 和 no 两个本地控制词",
                "capability_request": {"family": "audio_classification"},
            },
        ),
        201,
        "create audio task",
    )["task"]
    task_id = str(task["task_id"])
    if task.get("status") != "needs_recipe":
        raise RuntimeError(f"audio task did not expose the Recipe gap: {task}")
    _require(
        client.post(
            f"/tasks/{task_id}/staged-assets",
            content=payload,
            headers={"X-Filename": "recipe-samples.zip"},
        ),
        201,
        "stage audio Recipe samples",
    )
    built = _require(
        client.post(f"/tasks/{task_id}/recipe-builds", json={}),
        201,
        "build declarative audio Recipe",
    )
    attempt = built["build_attempt"]
    if attempt.get("status") != "awaiting_registration":
        raise RuntimeError(f"audio Recipe build is not reviewable: {attempt}")
    attempt_id = str(attempt["attempt_id"])
    registered = _require(
        client.post(
            f"/tasks/{task_id}/recipe-builds/{attempt_id}/register",
            json={
                "decision": "approved",
                "actor": "v0.7-acceptance-preparer",
                "reason": "validated trusted declarative audio Recipe digests",
                "candidate_digest": attempt["candidate_digest"],
                "validation_digest": attempt["validation_digest"],
            },
        ),
        200,
        "register declarative audio Recipe",
    )["task"]
    if registered.get("recipe_id") != "audio-keyword-classification":
        raise RuntimeError(f"audio Recipe did not activate: {registered}")
    _require(
        client.post(
            f"/tasks/{task_id}/dataset",
            content=payload,
            headers={"X-Filename": "formal-keywords.zip"},
        ),
        201,
        "upload formal audio dataset",
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
        "confirm audio contract",
    )
    run_id = _start_and_wait(client, app, task_id)
    journey = _complete_l4_chain(
        client,
        task_id=task_id,
        run_id=run_id,
        sample=_wav_bytes(360.0, speaker_index=999),
        filename="new-yes.wav",
        sample_type="audio",
    )
    journey["build_attempt_id"] = attempt_id
    journey["recipe_version_id"] = registered.get("recipe_version_id")
    return journey


def _hf_journey(runtime_dir: Path, repo_id: str, commit: str) -> dict[str, Any]:
    scenario = _run_once(runtime_dir, repo_id, commit)
    evaluation = scenario["evaluation"]
    if evaluation.get("integrity_status") != "passed":
        raise RuntimeError(f"HF image Run integrity did not pass: {evaluation}")
    if scenario["new_sample_inference"].get("status") != "passed":
        raise RuntimeError("HF image new-sample inference did not pass")
    required_ids = {
        "task_id": scenario.get("task_id"),
        "run_id": scenario.get("run_id"),
        "evaluation_report_id": evaluation.get("report_id"),
        "inference_check_id": scenario["new_sample_inference"].get("check_id"),
        "artifact_bundle_id": scenario["artifact_bundle"].get("bundle_id"),
    }
    if not all(isinstance(value, str) and value for value in required_ids.values()):
        raise RuntimeError(f"HF image journey is missing an id: {required_ids}")
    return {
        **required_ids,
        "recipe": "image-folder-classification",
        "training_status": scenario["run"]["status"],
        "evaluation_status": _evaluation_status(evaluation),
        "evaluation_conclusion": evaluation.get("conclusion"),
        "inference_status": "passed",
        "bundle_status": "completed",
        "bundle_sha256": scenario["artifact_bundle"]["sha256"],
        "sample_sha256": scenario["new_sample_inference"]["sample_sha256"],
        "model_asset_id": scenario["asset_id"],
        "image_source": "official_huggingface_fixed_commit",
        "repository": scenario["repository"],
        "resolved_commit": scenario["resolved_commit"],
    }


def _verify_restart(
    runtime_dir: Path,
    journeys: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    app = create_app(runtime_dir)
    verified: dict[str, Any] = {}
    with TestClient(app) as client:
        for family in FAMILIES:
            journey = journeys[family]
            task_id = journey["task_id"]
            run_id = journey["run_id"]
            task = _require(
                client.get(f"/tasks/{task_id}"),
                200,
                f"restart {family} task",
            )["task"]
            result = _require(
                client.get(f"/runs/{run_id}/result"),
                200,
                f"restart {family} run",
            )
            evaluation = _require(
                client.get(f"/tasks/{task_id}/runs/{run_id}/evaluation-report"),
                200,
                f"restart {family} evaluation",
            )["evaluation_report"]
            inference = _require(
                client.get(
                    f"/tasks/{task_id}/runs/{run_id}/sample-inferences/"
                    f"{journey['inference_check_id']}"
                ),
                200,
                f"restart {family} inference",
            )["sample_inference"]
            bundle = _require(
                client.get(
                    f"/tasks/{task_id}/runs/{run_id}/artifact-bundles/"
                    f"{journey['artifact_bundle_id']}"
                ),
                200,
                f"restart {family} bundle",
            )["artifact_bundle"]
            assertions = {
                "task_id_same": task.get("task_id") == task_id,
                "run_id_same": result.get("run_id") == run_id,
                "run_completed": result.get("status") == "completed",
                "evaluation_id_same": evaluation.get("report_id")
                == journey["evaluation_report_id"],
                "inference_id_same": inference.get("check_id")
                == journey["inference_check_id"],
                "bundle_id_same": bundle.get("bundle_id")
                == journey["artifact_bundle_id"],
            }
            if family == "audio":
                build = _require(
                    client.get(
                        f"/tasks/{task_id}/recipe-builds/"
                        f"{journey['build_attempt_id']}"
                    ),
                    200,
                    "restart audio build attempt",
                )["recipe_build"]
                assertions["build_attempt_id_same"] = (
                    build.get("attempt_id") == journey["build_attempt_id"]
                )
                assertions["recipe_restored"] = (
                    task.get("recipe_id") == "audio-keyword-classification"
                )
            if family == "image" and journey.get("model_asset_id"):
                model_asset = _require(
                    client.get(f"/tasks/{task_id}/model-assets/current/verify"),
                    200,
                    "restart image model asset",
                )
                assertions["model_asset_id_same"] = (
                    task.get("selected_model_asset_id")
                    == journey["model_asset_id"]
                )
                assertions["model_asset_verified"] = model_asset.get("ok") is True
            if not all(assertions.values()):
                raise RuntimeError(
                    f"restart verification failed for {family}: {assertions}"
                )
            verified[family] = {"passed": True, "assertions": assertions}
    return {"passed": True, "families": verified, "verified_at_utc": _now()}


def prepare_acceptance_runtime(
    runtime_dir: str | Path,
    *,
    skip_hf: bool = False,
    repo_id: str = DEFAULT_REPO,
    commit: str = DEFAULT_COMMIT,
) -> dict[str, Any]:
    selected_runtime = _prepare_empty_runtime(runtime_dir)
    normalized_commit = str(commit).strip().lower()
    if not skip_hf and (
        len(normalized_commit) != 40
        or any(character not in "0123456789abcdef" for character in normalized_commit)
    ):
        raise ValueError("Hugging Face commit must be an immutable 40-character SHA")

    journeys: dict[str, dict[str, Any]] = {}
    started_at = _now()
    if skip_hf:
        app = create_app(selected_runtime)
        with TestClient(app) as client:
            journeys["image"] = _prepare_local_image(client, app)
            journeys["tabular"] = _prepare_tabular(client, app)
            journeys["audio"] = _prepare_audio(client, app)
    else:
        journeys["image"] = _hf_journey(
            selected_runtime,
            repo_id,
            normalized_commit,
        )
        app = create_app(selected_runtime)
        with TestClient(app) as client:
            journeys["tabular"] = _prepare_tabular(client, app)
            journeys["audio"] = _prepare_audio(client, app)

    if tuple(journeys) != FAMILIES:
        raise RuntimeError(f"journey family order or membership drifted: {journeys}")
    restart = _verify_restart(selected_runtime, journeys)
    report = {
        "schema_version": JOURNEY_SCHEMA_VERSION,
        "status": "passed",
        "mode": "local_image_skip_hf" if skip_hf else "official_hf_fixed_commit",
        "started_at_utc": started_at,
        "finished_at_utc": _now(),
        "journey_families": journeys,
        "restart": restart,
        "huggingface": {
            "skipped": bool(skip_hf),
            "repository": None if skip_hf else repo_id,
            "requested_commit": None if skip_hf else normalized_commit,
        },
    }
    output_path = selected_runtime / "journeys.json"
    write_json(output_path, report)
    reopened = json.loads(output_path.read_text(encoding="utf-8"))
    if reopened != report:
        raise RuntimeError("journeys.json did not persist exactly")
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Prepare three restart-verifiable Model Harness v0.7 journeys in "
            "an empty runtime directory."
        )
    )
    parser.add_argument("--runtime-dir", type=Path, required=True)
    parser.add_argument(
        "--skip-hf",
        action="store_true",
        help="Use the local image Recipe instead of network Hugging Face assets.",
    )
    parser.add_argument("--repo-id", default=DEFAULT_REPO)
    parser.add_argument("--commit", default=DEFAULT_COMMIT)
    return parser.parse_args()


def main() -> int:
    arguments = parse_args()
    report = prepare_acceptance_runtime(
        arguments.runtime_dir,
        skip_hf=arguments.skip_hf,
        repo_id=arguments.repo_id,
        commit=arguments.commit,
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "mode": report["mode"],
                "journeys": str(arguments.runtime_dir.expanduser().resolve() / "journeys.json"),
                "family_ids": {
                    family: {
                        key: report["journey_families"][family].get(key)
                        for key in (
                            "task_id",
                            "run_id",
                            "evaluation_report_id",
                            "inference_check_id",
                            "artifact_bundle_id",
                        )
                    }
                    for family in FAMILIES
                },
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
