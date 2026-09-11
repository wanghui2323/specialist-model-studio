#!/usr/bin/env python3
from __future__ import annotations

import argparse
import io
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from fastapi.testclient import TestClient
from PIL import Image
from sklearn.datasets import load_digits

from model_harness.runner import verify_run
from model_harness.server import create_app


ROOT = Path(__file__).resolve().parents[1]


def build_digits_zip(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    dataset = load_digits()
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for index, (pixels, target) in enumerate(
            zip(dataset.images, dataset.target, strict=True)
        ):
            scaled = np.asarray(np.clip(pixels / 16.0 * 255.0, 0, 255), dtype=np.uint8)
            image = Image.fromarray(scaled, mode="L").resize((32, 32), Image.Resampling.NEAREST)
            payload = io.BytesIO()
            image.save(payload, format="PNG")
            archive.writestr(f"handwritten-digits/{int(target)}/{index:04d}.png", payload.getvalue())
    return path


def run_task(
    client: TestClient,
    app: Any,
    *,
    name: str,
    business_goal: str,
    capability_request: dict[str, Any],
    dataset_path: Path,
    upload_headers: dict[str, str],
    timeout: float = 180,
) -> dict[str, Any]:
    created = client.post(
        "/tasks",
        json={
            "name": name,
            "business_goal": business_goal,
            "capability_request": capability_request,
        },
    )
    created.raise_for_status()
    task = created.json()["task"]
    task_id = task["task_id"]
    before_run_ids = list(task["run_ids"])
    blocked = client.post(f"/tasks/{task_id}/runs")
    if blocked.status_code != 409:
        raise RuntimeError(f"unconfirmed run was not blocked: {blocked.status_code} {blocked.text}")
    reopened_before = client.get(f"/tasks/{task_id}").json()["task"]
    if reopened_before["run_ids"] != before_run_ids:
        raise RuntimeError("blocked run mutated task lineage")

    uploaded = client.post(
        f"/tasks/{task_id}/dataset",
        content=dataset_path.read_bytes(),
        headers={"X-Filename": dataset_path.name, **upload_headers},
    )
    uploaded.raise_for_status()
    confirmed = client.post(
        f"/tasks/{task_id}/confirm",
        json={
            "data_authorized": True,
            "labels_reviewed": True,
            "gates_reviewed": True,
        },
    )
    confirmed.raise_for_status()
    started = client.post(f"/tasks/{task_id}/runs")
    started.raise_for_status()
    run_id = started.json()["task"]["current_run_id"]
    app.state.run_service.wait(run_id, timeout=timeout)
    reopened = client.get(f"/tasks/{task_id}")
    reopened.raise_for_status()
    task = reopened.json()["task"]
    if task["task_id"] != task_id or task["current_run_id"] != run_id:
        raise RuntimeError("task identity changed after run")
    result = task["current_result"]
    verification = verify_run(app.state.run_service.runs_dir / run_id, deep=True)
    if not verification["ok"] or not verification["deep_verified"]:
        raise RuntimeError(f"deep verification failed: {verification['errors']}")
    return {
        "task_id": task_id,
        "run_id": run_id,
        "status": task["status"],
        "recipe_id": task["recipe_id"],
        "data_adapter_id": task["data_adapter_id"],
        "dataset_id": task["dataset_id"],
        "dataset_report": task["dataset_report"],
        "metrics": result["metrics"],
        "artifact_names": sorted(item["name"] for item in result["artifacts"]),
        "event_count": len(client.get(f"/runs/{run_id}/events").json()["events"]),
        "deep_verification": verification,
        "negative_case": {
            "action": "start before contract confirmation",
            "http_status": blocked.status_code,
            "run_ids_unchanged": reopened_before["run_ids"] == before_run_ids,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run two real public-data Specialist Model Studio scenarios.")
    parser.add_argument(
        "--wine-csv",
        type=Path,
        default=ROOT / "runs" / "_validation_inputs" / "wine-quality" / "winequality-red.csv",
    )
    parser.add_argument(
        "--runs-dir",
        type=Path,
        default=ROOT / "runs" / "real-validation",
    )
    args = parser.parse_args()
    wine_csv = args.wine_csv.expanduser().resolve()
    if not wine_csv.is_file():
        raise FileNotFoundError(
            f"Wine Quality CSV not found: {wine_csv}. Download UCI dataset 186 first."
        )
    digits_zip = build_digits_zip(
        ROOT / "runs" / "_validation_inputs" / "digits" / "handwritten-digits.zip"
    )
    app = create_app(args.runs_dir)
    with TestClient(app) as client:
        digits = run_task(
            client,
            app,
            name="真实手写数字识别",
            business_goal="从用户导入的手写数字图片中识别0到9",
            capability_request={
                "modality": "image",
                "objective": "classification",
                "target_kind": "multiclass",
                "data_adapter": "image-folder-zip",
                "tags": ["ocr", "user-data"],
            },
            dataset_path=digits_zip,
            upload_headers={"Content-Type": "application/zip"},
        )
        wine = run_task(
            client,
            app,
            name="葡萄酒质量预测",
            business_goal="根据理化指标预测Vinho Verde葡萄酒质量评分",
            capability_request={
                "modality": "tabular",
                "objective": "regression",
                "target_kind": "numeric",
                "target_column": "quality",
                "data_adapter": "tabular-csv",
                "tags": ["prediction", "user-data"],
            },
            dataset_path=wine_csv,
            upload_headers={
                "Content-Type": "text/csv",
                "X-Target-Column": "quality",
                "X-Delimiter": ";",
            },
        )
        unmatched = client.post(
            "/tasks",
            json={
                "name": "设备异响识别",
                "business_goal": "识别三类设备异响",
                "capability_request": {
                    "modality": "audio",
                    "objective": "classification",
                    "target_kind": "multiclass",
                },
            },
        )
        unmatched.raise_for_status()
        unmatched_task = unmatched.json()["task"]
    report = {
        "schema_version": "0.1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "product_claim": "Two real public-data scenarios validate the extensible Harness; they are not the capability boundary.",
        "sources": {
            "digits": {
                "name": "scikit-learn digits / UCI Optical Recognition of Handwritten Digits test set",
                "url": "https://scikit-learn.org/stable/modules/generated/sklearn.datasets.load_digits.html",
                "samples": 1797,
                "classes": 10,
            },
            "wine_quality": {
                "name": "UCI Wine Quality dataset 186 (red wine)",
                "url": "https://archive.ics.uci.edu/dataset/186/wine+quality",
                "license": "CC BY 4.0",
            },
        },
        "scenarios": {"digits_image_classification": digits, "wine_tabular_regression": wine},
        "unmatched_capability": {
            "task_id": unmatched_task["task_id"],
            "status": unmatched_task["status"],
            "run_ids": unmatched_task["run_ids"],
            "recipe_request": unmatched_task["recipe_request"],
        },
    }
    report_path = args.runs_dir / "real_scenarios_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"report": str(report_path), "scenarios": report["scenarios"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
