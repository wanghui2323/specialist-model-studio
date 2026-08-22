from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from model_harness.model_assets import DownloadResult
from model_harness.server import create_app


COMMIT = "a" * 40


class FakeCatalog:
    def capability(self):
        return {"available": True, "provider": "huggingface"}

    def search(self, query, **kwargs):
        return [{"repository": "fixture/model", "revision": COMMIT}]

    def model_card(self, repo_id, **kwargs):
        return {
            "repository": repo_id,
            "revision": COMMIT,
            "license": "apache-2.0",
            "library": "onnx",
            "pipeline_tag": "image-classification",
            "files": [
                {"path": "config.json", "size_bytes": 120},
                {"path": "model.onnx", "size_bytes": 32},
            ],
            "compatibility": {
                "state": "compatible_candidate",
                "checks": {"local_cpu_runtime": True},
                "blocking_reasons": [],
                "training_binding": "image_classification_onnx_feature_v1",
            },
        }


class FixtureDownloader:
    def __init__(self):
        self.token_seen = False

    def capability(self):
        return {"available": True, "provider": "huggingface"}

    def download(self, *, revision, destination, token, **kwargs):
        self.token_seen = token is not None
        (destination / "model.onnx").write_bytes(b"fixture onnx bytes")
        (destination / "config.json").write_text(
            json.dumps(
                {
                    "mean": [0.5, 0.5, 0.5],
                    "std": [0.5, 0.5, 0.5],
                    "input_shape": [3, 8, 8],
                    "classes": ["feature"],
                }
            ),
            encoding="utf-8",
        )
        (destination / "README.md").write_text("# fixture", encoding="utf-8")
        return DownloadResult(resolved_commit=revision, license="apache-2.0")


class HuggingFaceWorkspaceTests(unittest.TestCase):
    def test_approved_fixed_commit_asset_binds_to_same_task_without_a_run(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            app = create_app(Path(temporary) / "runs")
            workspace = app.state.training_workspace
            workspace.huggingface_catalog = FakeCatalog()
            downloader = FixtureDownloader()
            workspace.huggingface_downloader = downloader
            with TestClient(app) as client:
                created = client.post(
                    "/tasks",
                    json={
                        "name": "HF image task",
                        "business_goal": "用图片训练一个二分类模型",
                    },
                ).json()["task"]
                task_id = created["task_id"]
                confirmed = client.patch(
                    f"/tasks/{task_id}/spec",
                    json={
                        "base_revision": 1,
                        "selected_family": "image_classification",
                        "confirm": True,
                    },
                )
                self.assertEqual(confirmed.status_code, 200, confirmed.text)

                rejected = client.post(
                    f"/tasks/{task_id}/model-assets/huggingface",
                    json={
                        "repo_id": "fixture/model",
                        "commit": COMMIT,
                        "approval_confirmed": False,
                    },
                )
                self.assertEqual(rejected.status_code, 409, rejected.text)
                self.assertEqual(workspace.model_assets.list_assets(), [])

                token = "hf_ephemeral_workspace_token"
                attached = client.post(
                    f"/tasks/{task_id}/model-assets/huggingface",
                    json={
                        "repo_id": "fixture/model",
                        "commit": COMMIT,
                        "approval_confirmed": True,
                    },
                    headers={"X-HF-Token": token},
                )
                self.assertEqual(attached.status_code, 200, attached.text)
                value = attached.json()
                self.assertEqual(value["task"]["task_id"], task_id)
                self.assertEqual(value["task"]["run_ids"], [])
                self.assertEqual(value["model_asset"]["resolved_commit"], COMMIT)
                self.assertEqual(value["model_asset"]["security_status"], "verified")
                self.assertTrue(downloader.token_seen)
                verified = client.get(
                    f"/tasks/{task_id}/model-assets/current/verify"
                )
                self.assertEqual(verified.status_code, 200, verified.text)
                self.assertTrue(verified.json()["ok"])
                disk = b"".join(
                    path.read_bytes()
                    for path in workspace.root.rglob("*")
                    if path.is_file() and not path.is_symlink()
                )
                self.assertNotIn(token.encode(), disk)


if __name__ == "__main__":
    unittest.main()
