from __future__ import annotations

import tempfile
import unittest

try:
    from fastapi.testclient import TestClient
except ImportError:  # optional dependency
    TestClient = None  # type: ignore[assignment]

from model_harness.server import create_app


@unittest.skipIf(TestClient is None, "server extra is not installed")
class ServerTests(unittest.TestCase):
    def test_health_and_recipe_endpoints(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            app = create_app(temp_dir, conversation_url="http://127.0.0.1:3999")
            with TestClient(app) as client:  # type: ignore[misc]
                health = client.get("/health")
                self.assertEqual(health.status_code, 200)
                self.assertTrue(health.json()["ok"])
                self.assertEqual(health.json()["version"], "0.9.0-rc.1")
                self.assertEqual(health.json()["package_version"], "0.9.0rc1")
                self.assertEqual(
                    health.json()["feature_track"], "v0.9-universal-byom"
                )
                self.assertEqual(health.json()["release_status"], "unreleased_rc")
                self.assertEqual(health.json()["scope"], "backend")
                self.assertFalse(health.json()["agent_required"])
                self.assertEqual(health.json()["primary_experience"], "conversation")
                self.assertEqual(health.json()["conversation_url"], "/app")

                runtime = client.get("/runtime")
                self.assertEqual(runtime.status_code, 200)
                self.assertEqual(runtime.json()["workbench_url"], "/app")
                self.assertEqual(
                    runtime.json()["feature_track"], "v0.9-universal-byom"
                )
                self.assertEqual(runtime.json()["release_status"], "unreleased_rc")
                self.assertEqual(
                    runtime.json()["source_execution_policy"],
                    "static_analysis_only_without_verified_isolation",
                )
                self.assertFalse(runtime.json()["byom_execution_available"])
                self.assertEqual(
                    runtime.json()["supported_protocol_end"],
                    "resource_feasibility",
                )
                self.assertTrue(
                    runtime.json()["registered_recipe_training_available"]
                )

                openapi = client.get("/openapi.json")
                self.assertEqual(openapi.status_code, 200)
                self.assertEqual(openapi.json()["info"]["version"], "0.9.0-rc.1")

                root = client.get("/", follow_redirects=False)
                self.assertEqual(root.status_code, 307)
                self.assertEqual(root.headers["location"], "/app")

                recipes = client.get("/recipes")
                self.assertEqual(recipes.status_code, 200)
                self.assertEqual(
                    recipes.json()["recipes"][0]["plugin_id"],
                    "digit-classification",
                )

                families = client.get("/task-spec/families")
                self.assertEqual(families.status_code, 200)
                family_values = {
                    item["family"] for item in families.json()["families"]
                }
                self.assertTrue(
                    {"asr", "speech_synthesis", "segmentation", "custom"}
                    <= family_values
                )

                template = client.get("/recipes/digit-classification/template")
                self.assertEqual(template.status_code, 200)
                self.assertEqual(
                    template.json()["contract"]["recipe"],
                    "digit-classification",
                )

                console = client.get("/app")
                self.assertEqual(console.status_code, 200)
                self.assertIn("Specialist Model Studio · 专业模型智能工作台", console.text)
                self.assertIn("把一句需求", console.text)
                self.assertIn("可验收的小模型", console.text)
                self.assertNotIn("Workspace Write", console.text)

                chat = client.post("/chat", json={"message": "有哪些能力"})
                self.assertEqual(chat.status_code, 200)
                self.assertEqual(chat.json()["kind"], "recipes")

    def test_strategy_api_requires_explicit_approval(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            app = create_app(temp_dir)
            with TestClient(app) as client:  # type: ignore[misc]
                response = client.post(
                    "/runs/missing/strategies/add-shift-augmentation/apply",
                    json={},
                )
                self.assertEqual(response.status_code, 409)
                self.assertIn("approval_confirmed=true", response.json()["detail"])

    def test_global_and_chat_run_creation_surfaces_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            app = create_app(temp_dir)
            with TestClient(app) as client:  # type: ignore[misc]
                task = client.post(
                    "/tasks",
                    json={"name": "guarded", "business_goal": "still ambiguous"},
                ).json()["task"]
                template = client.get(
                    "/recipes/digit-classification/template"
                ).json()["contract"]
                template["task_id"] = task["task_id"]

                responses = (
                    client.post("/runs", json={"contract": template}),
                    client.post("/runs/missing/cancel", json={}),
                    client.post("/runs/missing/resume", json={}),
                    client.post(
                        "/runs/missing/strategies/add-shift-augmentation/apply",
                        json={"approval_confirmed": True},
                    ),
                    client.post("/chat", json={"message": "/start"}),
                    client.post(
                        "/chat",
                        json={"message": "/cancel", "run_id": "missing"},
                    ),
                    client.post(
                        "/chat",
                        json={
                            "message": "/apply add-shift-augmentation",
                            "run_id": "missing",
                        },
                    ),
                )
                self.assertTrue(
                    all(response.status_code == 409 for response in responses),
                    [response.text for response in responses],
                )
                self.assertEqual(app.state.run_service.list_runs(), [])


if __name__ == "__main__":
    unittest.main()
