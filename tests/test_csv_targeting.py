from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

try:
    from fastapi.testclient import TestClient
except ImportError:  # pragma: no cover - optional dependency
    TestClient = None  # type: ignore[assignment]

from model_harness.csv_targeting import recommend_csv_target_column
from model_harness.server import create_app


COLUMNS = ["area_sqm", "bedrooms", "building_age_years", "price"]


class CsvTargetRecommendationTests(unittest.TestCase):
    def test_declared_price_wins_over_earlier_feature_mentions(self) -> None:
        recommendation = recommend_csv_target_column(
            {
                "business_goal": (
                    "根据 area_sqm、bedrooms、building_age_years 预测 price"
                ),
                "capability_request": {
                    "modality": "tabular",
                    "objective": "regression",
                    "target_column": "price",
                },
            },
            COLUMNS,
        )

        self.assertEqual(recommendation["status"], "recommended")
        self.assertEqual(recommendation["target_column"], "price")
        self.assertEqual(recommendation["source"], "task_capability")
        self.assertEqual(recommendation["confidence"], "high")

    def test_prediction_phrase_identifies_price_not_input_columns(self) -> None:
        recommendation = recommend_csv_target_column(
            {
                "business_goal": (
                    "根据 area_sqm、bedrooms、building_age_years 预测 price，"
                    "用于离线批量估值"
                )
            },
            COLUMNS,
        )

        self.assertEqual(recommendation["status"], "recommended")
        self.assertEqual(recommendation["target_column"], "price")
        self.assertEqual(recommendation["source"], "task_prediction_phrase")

    def test_undeclared_and_nonstandard_columns_do_not_fake_recommendation(
        self,
    ) -> None:
        recommendation = recommend_csv_target_column(
            {"business_goal": "分析房屋数据字段之间的关系"},
            ["area_sqm", "bedrooms", "building_age_years", "city_code"],
        )

        self.assertEqual(recommendation["status"], "needs_confirmation")
        self.assertIsNone(recommendation["target_column"])
        self.assertIsNone(recommendation["source"])
        self.assertEqual(recommendation["reason_code"], "target_not_declared")

    def test_missing_declared_target_does_not_substitute_common_column(self) -> None:
        recommendation = recommend_csv_target_column(
            {
                "capability_request": {
                    "modality": "tabular",
                    "objective": "regression",
                    "target_column": "price",
                }
            },
            ["area_sqm", "bedrooms", "quality"],
        )

        self.assertEqual(recommendation["status"], "declared_target_missing")
        self.assertEqual(recommendation["declared_target_column"], "price")
        self.assertIsNone(recommendation["target_column"])
        self.assertEqual(
            recommendation["reason_code"],
            "declared_target_not_in_header",
        )

    def test_safe_name_fallback_requires_one_unambiguous_candidate(self) -> None:
        single = recommend_csv_target_column(
            {"business_goal": "训练一个表格回归模型"},
            ["feature_a", "feature_b", "price"],
        )
        ambiguous = recommend_csv_target_column(
            {"business_goal": "训练一个表格回归模型"},
            ["feature_a", "price", "score"],
        )

        self.assertEqual(single["target_column"], "price")
        self.assertEqual(single["source"], "safe_common_target_name")
        self.assertEqual(ambiguous["status"], "needs_confirmation")
        self.assertIsNone(ambiguous["target_column"])


@unittest.skipIf(TestClient is None, "server extra is not installed")
class CsvTargetRecommendationApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.app = create_app(Path(self.temporary.name) / "runs")
        self.client_context = TestClient(self.app)  # type: ignore[misc]
        self.client = self.client_context.__enter__()

    def tearDown(self) -> None:
        self.client_context.__exit__(None, None, None)
        self.temporary.cleanup()

    def test_task_owned_api_returns_structured_recommendation(self) -> None:
        created = self.client.post(
            "/tasks",
            json={
                "name": "房价预测",
                "business_goal": (
                    "根据 area_sqm、bedrooms、building_age_years 预测 price"
                ),
                "capability_request": {
                    "modality": "tabular",
                    "objective": "regression",
                    "target_kind": "numeric",
                    "target_column": "price",
                },
            },
        )
        self.assertEqual(created.status_code, 201, created.text)
        task_id = created.json()["task"]["task_id"]

        response = self.client.post(
            f"/tasks/{task_id}/csv-target-recommendation",
            json={"columns": COLUMNS},
        )

        self.assertEqual(response.status_code, 200, response.text)
        recommendation = response.json()["recommendation"]
        self.assertEqual(recommendation["target_column"], "price")
        self.assertEqual(recommendation["reason_code"], "declared_target_matches_header")

    def test_api_rejects_invalid_column_contract_and_missing_task(self) -> None:
        created = self.client.post(
            "/tasks",
            json={"name": "表格任务", "business_goal": "分析表格数据"},
        )
        task_id = created.json()["task"]["task_id"]

        invalid = self.client.post(
            f"/tasks/{task_id}/csv-target-recommendation",
            json={"columns": ["only_one"]},
        )
        missing = self.client.post(
            "/tasks/not-a-task/csv-target-recommendation",
            json={"columns": ["feature", "target"]},
        )

        self.assertEqual(invalid.status_code, 422, invalid.text)
        self.assertEqual(missing.status_code, 404, missing.text)


if __name__ == "__main__":
    unittest.main()
