from __future__ import annotations

import io
import math
import struct
import tempfile
import unittest
import wave
import zipfile
from pathlib import Path

try:
    from fastapi.testclient import TestClient
except ImportError:  # pragma: no cover
    TestClient = None  # type: ignore[assignment]

from model_harness.server import create_app


def build_wav(frequency_hz: float = 440.0) -> bytes:
    sample_rate = 16_000
    frame_count = 1_600
    frames = b"".join(
        struct.pack(
            "<h",
            int(10_000 * math.sin(2 * math.pi * frequency_hz * index / sample_rate)),
        )
        for index in range(frame_count)
    )
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(sample_rate)
        audio.writeframes(frames)
    return output.getvalue()


def build_audio_zip() -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("wake/alice_0.wav", build_wav(440))
        archive.writestr("other/bob_0.wav", build_wav(660))
    return output.getvalue()


def build_unsafe_zip() -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("../escape.wav", build_wav())
    return output.getvalue()


def create_audio_task(client: TestClient, name: str = "本地唤醒词") -> dict:
    response = client.post(
        "/tasks",
        json={
            "name": name,
            "business_goal": "用WAV音频识别唤醒词和其他声音",
            "capability_request": {"family": "audio_classification"},
        },
    )
    if response.status_code != 201:
        raise AssertionError(response.text)
    return response.json()["task"]


@unittest.skipIf(TestClient is None, "server extra is not installed")
class StagedAssetApiTests(unittest.TestCase):
    def test_audio_samples_persist_and_change_only_the_projected_next_action(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            runs_dir = Path(temp_dir) / "runs"
            app = create_app(runs_dir)
            with TestClient(app) as client:  # type: ignore[misc]
                created = create_audio_task(client)
                task_id = created["task_id"]
                self.assertEqual(created["status"], "needs_recipe")
                self.assertEqual(
                    created["capability_decision"]["status"], "resolved"
                )
                self.assertEqual(
                    created["control"]["next_action"]["id"],
                    "stage_recipe_samples",
                )
                lifecycle_before = {
                    key: created[key]
                    for key in (
                        "status",
                        "current_spec_revision",
                        "dataset_id",
                        "current_run_id",
                        "run_ids",
                    )
                }

                staged = client.post(
                    f"/tasks/{task_id}/staged-assets",
                    content=build_audio_zip(),
                    headers={
                        "Content-Type": "application/zip",
                        "X-Filename": "keyword-samples.zip",
                        "X-Spec-Revision": "1",
                    },
                )
                self.assertEqual(staged.status_code, 201, staged.text)
                body = staged.json()
                asset = body["asset"]
                task = body["task"]
                self.assertEqual(asset["task_id"], task_id)
                self.assertEqual(asset["spec_revision"], 1)
                self.assertEqual(asset["status"], "staged")
                self.assertEqual(asset["report"]["file_count"], 2)
                self.assertEqual(
                    {key: task[key] for key in lifecycle_before},
                    lifecycle_before,
                )
                self.assertEqual(task["staged_assets"]["current_staged_count"], 1)
                self.assertEqual(
                    task["staged_assets"]["latest"]["asset_id"],
                    asset["asset_id"],
                )
                self.assertEqual(
                    task["control"]["next_action"]["id"],
                    "start_recipe_build",
                )

                listed = client.get(f"/tasks/{task_id}/staged-assets")
                self.assertEqual(listed.status_code, 200, listed.text)
                self.assertEqual(
                    [item["asset_id"] for item in listed.json()["staged_assets"]],
                    [asset["asset_id"]],
                )
                self.assertEqual(listed.json()["summary"]["current_staged_count"], 1)
                detail = client.get(
                    f"/tasks/{task_id}/staged-assets/{asset['asset_id']}"
                )
                self.assertEqual(detail.status_code, 200, detail.text)
                self.assertEqual(detail.json()["staged_asset"]["sha256"], asset["sha256"])

                task_dir = runs_dir / "_workspace" / "tasks" / task_id
                self.assertFalse((task_dir / "datasets").exists())
                self.assertFalse(any(runs_dir.glob("run-*")))

            reopened_app = create_app(runs_dir)
            with TestClient(reopened_app) as client:  # type: ignore[misc]
                reopened = client.get(f"/tasks/{task_id}").json()["task"]
                self.assertEqual(reopened["task_id"], task_id)
                self.assertEqual(reopened["staged_assets"]["current_staged_count"], 1)
                self.assertEqual(
                    reopened["control"]["next_action"]["id"],
                    "start_recipe_build",
                )

    def test_malicious_zip_returns_422_with_queryable_quarantine_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            runs_dir = Path(temp_dir) / "runs"
            app = create_app(runs_dir)
            with TestClient(app) as client:  # type: ignore[misc]
                created = create_audio_task(client)
                task_id = created["task_id"]
                task_path = runs_dir / "_workspace" / "tasks" / task_id / "task.json"
                persisted_before = task_path.read_bytes()
                lifecycle_before = {
                    key: created[key]
                    for key in (
                        "status",
                        "current_spec_revision",
                        "dataset_id",
                        "current_run_id",
                        "run_ids",
                        "updated_at_utc",
                    )
                }

                rejected = client.post(
                    f"/tasks/{task_id}/staged-assets",
                    content=build_unsafe_zip(),
                    headers={"X-Filename": "unsafe.zip", "X-Spec-Revision": "1"},
                )
                self.assertEqual(rejected.status_code, 422, rejected.text)
                detail = rejected.json()["detail"]
                self.assertEqual(detail["status"], "quarantined")
                self.assertTrue(detail["asset_id"].startswith("asset-"))
                self.assertEqual(task_path.read_bytes(), persisted_before)

                task = client.get(f"/tasks/{task_id}").json()["task"]
                self.assertEqual(
                    {key: task[key] for key in lifecycle_before},
                    lifecycle_before,
                )
                self.assertEqual(task["staged_assets"]["quarantined_count"], 1)
                self.assertEqual(task["staged_assets"]["current_staged_count"], 0)
                self.assertEqual(
                    task["control"]["next_action"]["id"],
                    "stage_recipe_samples",
                )
                listed = client.get(f"/tasks/{task_id}/staged-assets").json()
                self.assertEqual(len(listed["staged_assets"]), 1)
                self.assertEqual(listed["staged_assets"][0]["status"], "quarantined")
                self.assertIsNone(listed["staged_assets"][0]["archive"])
                self.assertFalse(any(runs_dir.glob("run-*")))

    def test_stale_revision_is_rejected_and_old_samples_are_superseded(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            app = create_app(Path(temp_dir) / "runs")
            with TestClient(app) as client:  # type: ignore[misc]
                created = create_audio_task(client)
                task_id = created["task_id"]
                first = client.post(
                    f"/tasks/{task_id}/staged-assets",
                    content=build_audio_zip(),
                    headers={"X-Filename": "r1.zip", "X-Spec-Revision": "1"},
                ).json()["asset"]

                revised = client.patch(
                    f"/tasks/{task_id}/spec",
                    json={
                        "base_revision": 1,
                        "business_goal": "只识别唤醒词wake与other，输出单一类别",
                        "selected_family": "audio_classification",
                    },
                )
                self.assertEqual(revised.status_code, 200, revised.text)
                revised_task = revised.json()["task"]
                self.assertEqual(revised_task["current_spec_revision"], 2)
                self.assertEqual(revised_task["staged_assets"]["superseded_count"], 1)
                self.assertEqual(
                    revised_task["control"]["next_action"]["id"],
                    "stage_recipe_samples",
                )

                stale = client.post(
                    f"/tasks/{task_id}/staged-assets",
                    content=build_audio_zip(),
                    headers={"X-Filename": "stale.zip", "X-Spec-Revision": "1"},
                )
                self.assertEqual(stale.status_code, 409, stale.text)
                assets = client.get(f"/tasks/{task_id}/staged-assets").json()[
                    "staged_assets"
                ]
                self.assertEqual(len(assets), 1)
                self.assertEqual(assets[0]["asset_id"], first["asset_id"])
                self.assertEqual(assets[0]["status"], "superseded")

                current = client.post(
                    f"/tasks/{task_id}/staged-assets",
                    content=build_audio_zip(),
                    headers={"X-Filename": "r2.zip", "X-Spec-Revision": "2"},
                )
                self.assertEqual(current.status_code, 201, current.text)
                self.assertEqual(current.json()["asset"]["spec_revision"], 2)

    def test_task_ownership_and_capability_gate_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            app = create_app(Path(temp_dir) / "runs")
            with TestClient(app) as client:  # type: ignore[misc]
                owner = create_audio_task(client, "owner")
                other = create_audio_task(client, "other")
                asset = client.post(
                    f"/tasks/{owner['task_id']}/staged-assets",
                    content=build_audio_zip(),
                    headers={"X-Filename": "owner.zip"},
                ).json()["asset"]
                cross_task = client.get(
                    f"/tasks/{other['task_id']}/staged-assets/{asset['asset_id']}"
                )
                self.assertEqual(cross_task.status_code, 404, cross_task.text)

                unresolved = client.post(
                    "/tasks",
                    json={"name": "待澄清", "business_goal": "识别一些东西"},
                ).json()["task"]
                blocked = client.post(
                    f"/tasks/{unresolved['task_id']}/staged-assets",
                    content=build_audio_zip(),
                    headers={"X-Filename": "wrong.zip"},
                )
                self.assertEqual(blocked.status_code, 409, blocked.text)
                self.assertEqual(
                    client.get(
                        f"/tasks/{unresolved['task_id']}/staged-assets"
                    ).json()["staged_assets"],
                    [],
                )

                wrong_family = client.post(
                    "/tasks",
                    json={
                        "name": "OCR",
                        "business_goal": "读取图片中的文字",
                        "capability_request": {"family": "ocr"},
                    },
                ).json()["task"]
                blocked_family = client.post(
                    f"/tasks/{wrong_family['task_id']}/staged-assets",
                    content=build_audio_zip(),
                    headers={"X-Filename": "wrong-family.zip"},
                )
                self.assertEqual(blocked_family.status_code, 409, blocked_family.text)


if __name__ == "__main__":
    unittest.main()
