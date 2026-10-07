from __future__ import annotations

import csv
import io
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from model_harness.agent_bridge import agent_public_projection
from model_harness.server import create_app


def _regression_csv(row_count: int = 80) -> bytes:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["sample_id", "temperature", "pressure", "quality"])
    for index in range(row_count):
        temperature = 18.0 + (index % 23) * 0.7
        pressure = 90.0 + (index % 17) * 1.1
        quality = 0.5 * temperature - 0.1 * pressure + (index % 3) * 0.02
        writer.writerow(
            [f"S-{index:03d}", temperature, pressure, round(quality, 4)]
        )
    return output.getvalue().encode("utf-8")


def _all_keys(value: Any) -> list[str]:
    if isinstance(value, dict):
        return [
            *[str(key) for key in value],
            *[
                nested
                for child in value.values()
                for nested in _all_keys(child)
            ],
        ]
    if isinstance(value, list):
        return [nested for child in value for nested in _all_keys(child)]
    return []


class AgentPublicProjectionTests(unittest.TestCase):
    def test_recursive_projection_removes_paths_without_mutating_local_object(self) -> None:
        local_root = "/Users/local-user/private/model-harness/task-one"
        source = {
            "task": {
                "task_id": "task-one",
                "dataset_report": {
                    "root": local_root,
                    "manifest_path": f"{local_root}/dataset_manifest.json",
                    "report_path": f"{local_root}/dataset_report.json",
                    "files": [
                        {
                            "relative_path": "class-a/example.png",
                            "path": "class-a/example.png",
                        }
                    ],
                },
                "control": {
                    "next_action": {"href": "/tasks/task-one/confirm"}
                },
                "note": f"stored at {local_root}/dataset_report.json",
                "other_host_path": "runtime resolved /Applications/Local Tool/cache.bin",
            }
        }

        projected = agent_public_projection(source)
        serialized = json.dumps(projected, ensure_ascii=False)
        self.assertNotIn(local_root, serialized)
        self.assertNotIn("/Applications/Local Tool/cache.bin", serialized)
        self.assertNotIn("root", projected["task"]["dataset_report"])
        self.assertNotIn("manifest_path", projected["task"]["dataset_report"])
        self.assertNotIn("report_path", projected["task"]["dataset_report"])
        self.assertEqual(
            projected["task"]["control"]["next_action"]["href"],
            "/tasks/task-one/confirm",
        )
        self.assertEqual(
            projected["task"]["dataset_report"]["files"][0]["relative_path"],
            "class-a/example.png",
        )
        self.assertEqual(source["task"]["dataset_report"]["root"], local_root)

    def test_chinese_slash_prose_is_not_mistaken_for_an_absolute_path(self) -> None:
        projected = agent_public_projection(
            {
                "note": "复核时间/分组泄漏；真实缓存位于 /tmp/private/cache.bin",
            }
        )

        self.assertIn("时间/分组泄漏", projected["note"])
        self.assertNotIn("/tmp/private/cache.bin", projected["note"])
        self.assertIn("[local-path-redacted]", projected["note"])

    def test_markdown_and_chinese_quoted_slash_pairs_keep_their_meaning(self) -> None:
        examples = [
            "`day_of_week`/`is_weekend` 与日期必须一致。",
            "先复核「退货」/「退款」与「换货」的边界。",
            "比较“训练”/“验证”与‘准确率’/‘召回率’。",
            "路径保留语义：`x`/`y`；缓存 `/tmp/private/cache.bin`，附件「/Users/person/data.csv」。",
        ]
        for text in examples[:3]:
            with self.subTest(text=text):
                self.assertEqual(agent_public_projection(text), text)
        projected = agent_public_projection(examples[3])
        self.assertIn("`x`/`y`", projected)
        self.assertNotIn("/tmp/private", projected)
        self.assertNotIn("/Users/person", projected)
        self.assertIn("`[local-path-redacted]`", projected)
        self.assertIn("「[local-path-redacted]」", projected)
        self.assertNotIn("source_path", agent_public_projection({"source_path": "/Users/person/data.csv"}))

    def test_host_paths_adjacent_to_chinese_and_embedded_file_uris_stay_private(self) -> None:
        value = agent_public_projection({"note": "路径/Users/person/private.csv；打开 file:///tmp/private.csv 或 ~/private.csv"})
        self.assertNotIn("/Users/person", value["note"])
        self.assertNotIn("/tmp/private", value["note"])
        self.assertNotIn("~/private", value["note"])
        self.assertIn("[local-path-redacted]", value["note"])

    def test_known_host_root_after_chinese_text_is_redacted_but_url_is_not(self) -> None:
        projected = agent_public_projection("路径/Users/private/file 与缓存/tmp/cache.bin；参考 https://example.com/Users/private/file")
        self.assertIn("路径[local-path-redacted]", projected)
        self.assertIn("缓存[local-path-redacted]", projected)
        self.assertIn("https://example.com/Users/private/file", projected)
        self.assertEqual(agent_public_projection("`day_of_week`/`is_weekend`"), "`day_of_week`/`is_weekend`")

    def test_agent_header_is_path_safe_while_local_ui_projection_is_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            runs_dir = Path(temporary) / "runs"
            app = create_app(runs_dir)
            with TestClient(app) as client:
                created = client.post(
                    "/tasks",
                    json={
                        "name": "Agent public projection",
                        "business_goal": "predict a quality score",
                        "capability_request": {
                            "modality": "tabular",
                            "objective": "regression",
                            "target_kind": "numeric",
                            "target_column": "quality",
                        },
                    },
                )
                self.assertEqual(created.status_code, 201, created.text)
                task_id = created.json()["task"]["task_id"]
                uploaded = client.post(
                    f"/tasks/{task_id}/dataset",
                    content=_regression_csv(),
                    headers={
                        "Content-Type": "text/csv",
                        "X-Filename": "quality.csv",
                        "X-Target-Column": "quality",
                        "X-Ignored-Columns": "sample_id",
                    },
                )
                self.assertEqual(uploaded.status_code, 201, uploaded.text)

                local_task = client.get(f"/tasks/{task_id}").json()["task"]
                local_serialized = json.dumps(local_task, ensure_ascii=False)
                self.assertIn(str(runs_dir.resolve()), local_serialized)
                self.assertIn("root", local_task["contract"]["dataset"])
                self.assertIn("manifest_path", local_task["contract"]["dataset"])
                self.assertIn("report_path", local_task["contract"]["dataset"])

                remote = client.get(
                    f"/tasks/{task_id}",
                    headers={"X-Model-Harness-Projection": "agent-v1"},
                )
                self.assertEqual(remote.status_code, 200, remote.text)
                public_task = remote.json()["task"]
                public_serialized = json.dumps(public_task, ensure_ascii=False)
                self.assertNotIn(str(runs_dir.resolve()), public_serialized)
                self.assertFalse(
                    {"root", "manifest_path", "report_path"}.intersection(
                        _all_keys(public_task)
                    )
                )
                self.assertEqual(public_task["dataset_report"]["row_count"], 80)
                self.assertTrue(
                    public_task["control"]["next_action"]["href"].startswith(
                        f"/tasks/{task_id}/"
                    )
                )

                reopened_local = client.get(f"/tasks/{task_id}").json()["task"]
                self.assertIn(str(runs_dir.resolve()), json.dumps(reopened_local))


if __name__ == "__main__":
    unittest.main()
