from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

try:
    from fastapi.testclient import TestClient
except ImportError:  # pragma: no cover
    TestClient = None  # type: ignore[assignment]

from model_harness.server import create_app
from model_harness.task_specs import (
    TASK_FAMILY_VALUES,
    capability_decision,
    capability_for_family,
)


class CapabilityDecisionCandidateTests(unittest.TestCase):
    def test_home_starter_prompts_route_to_relevant_backend_families(
        self,
    ) -> None:
        cases = (
            (
                "我想训练一个模型，把普通话录音转成文字，用在本地设备上。",
                "needs_confirmation",
                "asr",
                {"asr"},
            ),
            (
                "我想训练一个模型，识别合同图片里的关键信息。",
                "needs_clarification",
                None,
                {"ocr", "image_classification", "object_detection"},
            ),
            (
                "我想用自己的零件图片训练一个缺陷检测模型。",
                "needs_clarification",
                None,
                {"image_classification", "object_detection", "segmentation"},
            ),
            (
                "我想用历史表格数据训练一个设备寿命预测模型。",
                "needs_confirmation",
                "tabular_regression",
                {"tabular_regression"},
            ),
        )

        for prompt, expected_status, expected_family, relevant_families in cases:
            with self.subTest(prompt=prompt):
                decision = capability_decision("首页示例任务", prompt, {})
                candidate_families = {
                    item["family"] for item in decision["candidates"]
                }

                self.assertEqual(decision["status"], expected_status)
                self.assertEqual(decision["selected_family"], expected_family)
                self.assertTrue(
                    relevant_families.issubset(candidate_families),
                    (relevant_families, candidate_families),
                )
                if expected_family == "asr":
                    self.assertNotIn("ocr", candidate_families)

    def test_ambiguous_modalities_offer_only_relevant_clarification_candidates(
        self,
    ) -> None:
        cases = (
            (
                "模糊语音模型",
                "我想训练一个语音模型",
                {
                    "audio_classification",
                    "asr",
                    "speech_synthesis",
                    "custom",
                },
            ),
            (
                "模糊图像模型",
                "我想训练一个图像模型",
                {
                    "image_classification",
                    "ocr",
                    "object_detection",
                    "segmentation",
                },
            ),
            (
                "模糊表格模型",
                "我想用 CSV 表格训练一个模型",
                {
                    "tabular_classification",
                    "tabular_regression",
                    "time_series_forecasting",
                    "anomaly_detection",
                },
            ),
            (
                "模糊文本模型",
                "我想训练一个文本模型",
                {
                    "text_classification",
                    "named_entity_recognition",
                    "custom",
                },
            ),
        )
        for name, goal, expected in cases:
            with self.subTest(name=name):
                decision = capability_decision(name, goal, {})
                candidates = {
                    item["family"] for item in decision["candidates"]
                }

                self.assertEqual(decision["status"], "needs_clarification")
                self.assertIsNone(decision["selected_family"])
                self.assertEqual(candidates, expected)
                self.assertGreaterEqual(len(candidates), 2)
                self.assertLessEqual(len(candidates), 4)
                self.assertIsInstance(decision["question"], str)
                self.assertIn("请选择", decision["question"])

    def test_unknown_modality_retains_generic_fallback(self) -> None:
        decision = capability_decision(
            "未知专用模型",
            "我想训练一个模型，但还没有定义输入和输出",
            {},
        )

        self.assertEqual(decision["status"], "needs_clarification")
        self.assertIsNone(decision["selected_family"])
        self.assertEqual(
            [item["family"] for item in decision["candidates"]],
            ["classification", "regression", "custom"],
        )
        self.assertEqual(
            decision["reason_codes"],
            ["missing_input_output_definition"],
        )


class CapabilityFamilyMigrationTests(unittest.TestCase):
    def test_image_classification_to_asr_clears_family_owned_fields(self) -> None:
        migrated = capability_for_family(
            "asr",
            {
                "family": "image_classification",
                "modality": "image",
                "objective": "classification",
                "target_kind": "multiclass",
                "target_column": "label",
                "primary_metric": "validation_macro_f1",
                "data_adapter": "image-folder-zip",
                "tags": ["edge"],
                "constraints": {"latency_ms": 100},
            },
        )

        self.assertEqual(migrated["family"], "asr")
        self.assertEqual(migrated["modality"], "audio")
        self.assertEqual(migrated["objective"], "speech_recognition")
        for key in (
            "target_kind",
            "target_column",
            "primary_metric",
            "data_adapter",
        ):
            self.assertNotIn(key, migrated)
        self.assertEqual(migrated["tags"], ["edge"])
        self.assertEqual(migrated["constraints"], {"latency_ms": 100})

    def test_tabular_regression_to_ocr_clears_regression_contract_fields(self) -> None:
        migrated = capability_for_family(
            "ocr",
            {
                "family": "tabular_regression",
                "modality": "tabular",
                "objective": "regression",
                "target_kind": "numeric",
                "target_column": "remaining_life",
                "primary_metric": "validation_mae",
                "data_adapter": "tabular-csv",
            },
        )

        self.assertEqual(
            migrated,
            {
                "family": "ocr",
                "modality": "image",
                "objective": "ocr",
            },
        )

    def test_same_family_update_preserves_compatible_fields(self) -> None:
        current = {
            "family": "image_classification",
            "modality": "image",
            "objective": "classification",
            "target_kind": "binary",
            "primary_metric": "validation_macro_f1",
            "data_adapter": "image-folder-zip",
            "tags": ["edge"],
            "constraints": {"latency_ms": 50},
        }

        self.assertEqual(
            capability_for_family("image_classification", current),
            current,
        )


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

    def test_cross_family_revision_does_not_persist_previous_recipe_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            app = create_app(Path(temp_dir) / "runs")
            with TestClient(app) as client:  # type: ignore[misc]
                task = client.post(
                    "/tasks",
                    json={
                        "name": "零件分类",
                        "business_goal": "把零件图片分为合格和不合格",
                        "capability_request": {
                            "family": "image_classification",
                            "modality": "image",
                            "objective": "classification",
                            "target_kind": "binary",
                            "primary_metric": "validation_macro_f1",
                            "data_adapter": "image-folder-zip",
                        },
                    },
                ).json()["task"]

                response = client.patch(
                    f"/tasks/{task['task_id']}/spec",
                    json={
                        "base_revision": 1,
                        "selected_family": "asr",
                        "user_note": "改为把录音转写成文字",
                    },
                )

                self.assertEqual(response.status_code, 200, response.text)
                revised = response.json()["task"]
                self.assertEqual(
                    revised["capability_request"],
                    {
                        "family": "asr",
                        "modality": "audio",
                        "objective": "speech_recognition",
                    },
                )
                self.assertEqual(revised["status"], "needs_recipe")
                self.assertIsNone(revised["recipe_id"])


if __name__ == "__main__":
    unittest.main()
