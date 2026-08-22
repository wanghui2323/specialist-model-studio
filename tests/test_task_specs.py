from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

try:
    from fastapi.testclient import TestClient
except ImportError:  # pragma: no cover
    TestClient = None  # type: ignore[assignment]

from model_harness.server import create_app
from model_harness.task_specs import TASK_FAMILY_VALUES


@unittest.skipIf(TestClient is None, "server extra is not installed")
class TaskSpecRevisionTests(unittest.TestCase):
    def test_inferred_classification_requires_confirmation_then_persists_revision(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            runs_dir = Path(temp_dir) / "runs"
            app = create_app(runs_dir)
            with TestClient(app) as client:  # type: ignore[misc]
                created = client.post(
                    "/tasks",
                    json={
                        "name": "零件颜色分类",
                        "business_goal": "用图片区分红色与蓝色零件",
                    },
                )
                self.assertEqual(created.status_code, 201, created.text)
                task = created.json()["task"]
                task_id = task["task_id"]
                self.assertEqual(task["current_spec_revision"], 1)
                self.assertEqual(
                    task["capability_decision"]["status"],
                    "needs_confirmation",
                )
                self.assertEqual(
                    task["capability_decision"]["selected_family"],
                    "image_classification",
                )
                self.assertEqual(
                    task["control"]["next_action"]["id"],
                    "confirm_task_spec",
                )
                self.assertEqual(len(task["control"]["blocked_by"]), 1)

                confirmed = client.patch(
                    f"/tasks/{task_id}/spec",
                    json={
                        "base_revision": 1,
                        "selected_family": "image_classification",
                        "user_note": "整张图片只输出一个颜色类别",
                    },
                )
                self.assertEqual(confirmed.status_code, 200, confirmed.text)
                revised = confirmed.json()["task"]
                self.assertEqual(revised["task_id"], task_id)
                self.assertEqual(revised["current_spec_revision"], 2)
                self.assertEqual(
                    revised["capability_decision"]["status"],
                    "resolved",
                )
                self.assertEqual(
                    revised["recipe_id"],
                    "image-folder-classification",
                )
                self.assertEqual(revised["status"], "awaiting_data")
                self.assertEqual(
                    revised["control"]["next_action"]["id"],
                    "upload_dataset",
                )
                self.assertEqual(len(revised["control"]["blocked_by"]), 0)

                revisions = client.get(
                    f"/tasks/{task_id}/spec/revisions"
                ).json()
                self.assertEqual(revisions["current_revision"], 2)
                self.assertEqual(
                    [item["revision"] for item in revisions["revisions"]],
                    [1, 2],
                )
                self.assertEqual(
                    revisions["revisions"][0]["capability_request"],
                    {},
                )
                self.assertEqual(
                    revisions["revisions"][1]["user_note"],
                    "整张图片只输出一个颜色类别",
                )

                listed = next(
                    item
                    for item in client.get("/tasks").json()["tasks"]
                    if item["task_id"] == task_id
                )
                reopened = client.get(f"/tasks/{task_id}").json()["task"]
                self.assertEqual(listed["control"], reopened["control"])
                self.assertEqual(listed["task_spec"], reopened["task_spec"])

                stale = client.patch(
                    f"/tasks/{task_id}/spec",
                    json={
                        "base_revision": 1,
                        "business_goal": "这条过期修订不应写入",
                    },
                )
                self.assertEqual(stale.status_code, 409, stale.text)
                self.assertEqual(
                    client.get(f"/tasks/{task_id}").json()["task"][
                        "current_spec_revision"
                    ],
                    2,
                )

            reopened_app = create_app(runs_dir)
            with TestClient(reopened_app) as client:  # type: ignore[misc]
                persisted = client.get(f"/tasks/{task_id}").json()["task"]
                self.assertEqual(persisted["task_id"], task_id)
                self.assertEqual(persisted["current_spec_revision"], 2)
                self.assertEqual(
                    persisted["control"]["next_action"]["id"],
                    "upload_dataset",
                )

    def test_ocr_generic_recognition_and_multi_intent_require_clarification(self) -> None:
        cases = (
            ("OCR合同识别", "从合同图片中识别文字"),
            ("图片识别", "识别图片里的内容"),
            ("文档理解", "需要OCR文字识别、文档分类与目标检测"),
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            app = create_app(Path(temp_dir) / "runs")
            with TestClient(app) as client:  # type: ignore[misc]
                for name, goal in cases:
                    with self.subTest(name=name):
                        task = client.post(
                            "/tasks",
                            json={"name": name, "business_goal": goal},
                        ).json()["task"]
                        self.assertEqual(task["status"], "needs_clarification")
                        self.assertEqual(
                            task["capability_decision"]["status"],
                            "needs_clarification",
                        )
                        self.assertEqual(
                            task["control"]["next_action"]["id"],
                            "clarify_task_spec",
                        )
                        candidate_families = {
                            item["family"]
                            for item in task["capability_decision"]["candidates"]
                        }
                        self.assertIn("ocr", candidate_families)
                        if name == "文档理解":
                            corrected = client.patch(
                                f"/tasks/{task['task_id']}/spec",
                                json={
                                    "base_revision": 1,
                                    "selected_family": "image_classification",
                                },
                            )
                            self.assertEqual(
                                corrected.status_code,
                                200,
                                corrected.text,
                            )
                            self.assertEqual(
                                corrected.json()["task"]["capability_decision"][
                                    "status"
                                ],
                                "resolved",
                            )

    def test_raw_csv_regression_goal_can_be_confirmed_without_frontend_inference(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            app = create_app(Path(temp_dir) / "runs")
            with TestClient(app) as client:  # type: ignore[misc]
                task = client.post(
                    "/tasks",
                    json={
                        "name": "质量数值预测",
                        "business_goal": "用CSV表格回归预测每行的质量分数",
                    },
                ).json()["task"]
                self.assertEqual(
                    task["capability_decision"]["selected_family"],
                    "tabular_regression",
                )
                self.assertEqual(
                    task["control"]["next_action"]["id"],
                    "confirm_task_spec",
                )
                confirmed = client.patch(
                    f"/tasks/{task['task_id']}/spec",
                    json={"base_revision": 1, "confirm": True},
                )
                self.assertEqual(confirmed.status_code, 200, confirmed.text)
                revised = confirmed.json()["task"]
                self.assertEqual(revised["recipe_id"], "tabular-regression")
                self.assertEqual(
                    revised["control"]["next_action"]["id"],
                    "upload_dataset",
                )

    def test_mainstream_intents_select_the_correct_task_family(self) -> None:
        cases = (
            (
                "本地语音转写",
                "用录音训练语音识别模型，把语音转写成文字",
                "asr",
            ),
            (
                "本地唤醒词",
                "用自己的录音训练本地关键词识别模型",
                "audio_classification",
            ),
            (
                "训练自己的声音",
                "用自己的录音训练我的声音，再把输入文本生成语音",
                "speech_synthesis",
            ),
            (
                "零件目标检测",
                "从工业零件图片中框出缺陷并输出边界框",
                "object_detection",
            ),
            (
                "缺陷像素分割",
                "给工业零件图片做缺陷分割，输出像素级掩码",
                "segmentation",
            ),
            (
                "销量时序预测",
                "用历史销售数据预测下个月销量",
                "time_series_forecasting",
            ),
            (
                "设备异常检测",
                "根据传感器时序数据检测异常并输出异常分数",
                "anomaly_detection",
            ),
            (
                "评论情感分类",
                "对用户评论文本做情感分类",
                "text_classification",
            ),
            (
                "合同实体抽取",
                "从合同文本中做命名实体识别",
                "named_entity_recognition",
            ),
            (
                "客户流失分类",
                "用CSV表格每行数据做客户流失分类",
                "tabular_classification",
            ),
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            app = create_app(Path(temp_dir) / "runs")
            with TestClient(app) as client:  # type: ignore[misc]
                for name, goal, expected_family in cases:
                    with self.subTest(family=expected_family):
                        response = client.post(
                            "/tasks",
                            json={"name": name, "business_goal": goal},
                        )
                        self.assertEqual(response.status_code, 201, response.text)
                        task = response.json()["task"]
                        self.assertEqual(
                            task["capability_decision"]["status"],
                            "needs_confirmation",
                        )
                        self.assertEqual(
                            task["capability_decision"]["selected_family"],
                            expected_family,
                        )
                        self.assertEqual(
                            task["capability_decision"]["candidates"][0][
                                "family"
                            ],
                            expected_family,
                        )

    def test_unsupported_and_unknown_families_never_fake_recipe_support(self) -> None:
        self.assertEqual(
            set(TASK_FAMILY_VALUES),
            {
                "image_classification",
                "ocr",
                "object_detection",
                "segmentation",
                "audio_classification",
                "asr",
                "speech_synthesis",
                "tabular_classification",
                "tabular_regression",
                "time_series_forecasting",
                "anomaly_detection",
                "text_classification",
                "named_entity_recognition",
                "classification",
                "regression",
                "custom",
            },
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            app = create_app(Path(temp_dir) / "runs")
            with TestClient(app) as client:  # type: ignore[misc]
                asr_task = client.post(
                    "/tasks",
                    json={
                        "name": "企业录音转写",
                        "business_goal": "训练ASR模型把会议录音转写为文字",
                    },
                ).json()["task"]
                confirmed_asr = client.patch(
                    f"/tasks/{asr_task['task_id']}/spec",
                    json={"base_revision": 1, "confirm": True},
                )
                self.assertEqual(confirmed_asr.status_code, 200, confirmed_asr.text)
                unsupported = confirmed_asr.json()["task"]
                self.assertEqual(unsupported["task_id"], asr_task["task_id"])
                self.assertEqual(unsupported["status"], "needs_recipe")
                self.assertEqual(unsupported["capability_status"], "needs_recipe")
                self.assertIsNone(unsupported["recipe_id"])
                self.assertIsNone(unsupported["current_run_id"])
                self.assertEqual(
                    unsupported["capability_request"],
                    {
                        "family": "asr",
                        "modality": "audio",
                        "objective": "speech_recognition",
                    },
                )

                tts_task = client.post(
                    "/tasks",
                    json={
                        "name": "训练我的声音",
                        "business_goal": "用自己的录音做音色克隆和文本转语音",
                    },
                ).json()["task"]
                confirmed_tts = client.patch(
                    f"/tasks/{tts_task['task_id']}/spec",
                    json={"base_revision": 1, "confirm": True},
                )
                self.assertEqual(confirmed_tts.status_code, 200, confirmed_tts.text)
                unsupported_tts = confirmed_tts.json()["task"]
                self.assertEqual(unsupported_tts["status"], "needs_recipe")
                self.assertEqual(
                    unsupported_tts["capability_status"],
                    "needs_recipe",
                )
                self.assertIsNone(unsupported_tts["recipe_id"])
                self.assertIsNone(unsupported_tts["current_run_id"])
                self.assertEqual(
                    unsupported_tts["capability_request"],
                    {
                        "family": "speech_synthesis",
                        "modality": "audio",
                        "objective": "speech_synthesis",
                    },
                )

                unknown = client.post(
                    "/tasks",
                    json={
                        "name": "新型传感器专用模型",
                        "business_goal": "用一种新的传感器输入产生专用输出",
                    },
                ).json()["task"]
                candidates = {
                    item["family"]
                    for item in unknown["capability_decision"]["candidates"]
                }
                self.assertEqual(unknown["status"], "needs_clarification")
                self.assertIn("custom", candidates)
                self.assertNotEqual(
                    candidates,
                    {"image_classification", "ocr", "object_detection"},
                )

                custom_response = client.patch(
                    f"/tasks/{unknown['task_id']}/spec",
                    json={
                        "base_revision": 1,
                        "selected_family": "other",
                        "user_note": "自定义输入输出，等待构建Recipe",
                    },
                )
                self.assertEqual(
                    custom_response.status_code,
                    200,
                    custom_response.text,
                )
                custom = custom_response.json()["task"]
                self.assertEqual(custom["task_id"], unknown["task_id"])
                self.assertEqual(
                    custom["capability_decision"]["selected_family"],
                    "custom",
                )
                self.assertEqual(custom["status"], "needs_recipe")
                self.assertEqual(custom["capability_status"], "needs_recipe")
                self.assertIsNone(custom["recipe_id"])
                self.assertIsNone(custom["current_run_id"])
                self.assertEqual(
                    custom["capability_request"],
                    {
                        "family": "custom",
                        "modality": "specialist",
                        "objective": "custom",
                    },
                )

    def test_ocr_clarification_can_be_corrected_without_faking_recipe_support(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            app = create_app(Path(temp_dir) / "runs")
            with TestClient(app) as client:  # type: ignore[misc]
                task = client.post(
                    "/tasks",
                    json={
                        "name": "合同OCR",
                        "business_goal": "从合同图片中识别文字",
                    },
                ).json()["task"]
                task_id = task["task_id"]
                self.assertEqual(
                    task["control"]["next_action"]["id"],
                    "clarify_task_spec",
                )

                corrected = client.patch(
                    f"/tasks/{task_id}/spec",
                    json={"base_revision": 1, "selected_family": "ocr"},
                )
                self.assertEqual(corrected.status_code, 200, corrected.text)
                revised = corrected.json()["task"]
                self.assertEqual(revised["task_id"], task_id)
                self.assertEqual(revised["current_spec_revision"], 2)
                self.assertEqual(
                    revised["capability_decision"]["status"],
                    "resolved",
                )
                self.assertEqual(revised["recipe_id"], None)
                self.assertEqual(revised["status"], "needs_recipe")
                self.assertEqual(
                    revised["control"]["current_stage"],
                    "capability_resolution",
                )
                self.assertEqual(
                    revised["control"]["next_action"]["id"],
                    "review_capability_gap",
                )


if __name__ == "__main__":
    unittest.main()
