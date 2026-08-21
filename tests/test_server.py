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
                self.assertEqual(health.json()["primary_experience"], "conversation")
                self.assertEqual(health.json()["conversation_url"], "/app")

                runtime = client.get("/runtime")
                self.assertEqual(runtime.status_code, 200)
                self.assertEqual(runtime.json()["workbench_url"], "/app")

                root = client.get("/", follow_redirects=False)
                self.assertEqual(root.status_code, 307)
                self.assertEqual(root.headers["location"], "/app")

                recipes = client.get("/recipes")
                self.assertEqual(recipes.status_code, 200)
                self.assertEqual(
                    recipes.json()["recipes"][0]["plugin_id"],
                    "digit-classification",
                )

                template = client.get("/recipes/digit-classification/template")
                self.assertEqual(template.status_code, 200)
                self.assertEqual(
                    template.json()["contract"]["recipe"],
                    "digit-classification",
                )

                console = client.get("/app")
                self.assertEqual(console.status_code, 200)
                self.assertIn("Model Harness · 对话式模型训练", console.text)
                self.assertIn("你希望模型", console.text)
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


if __name__ == "__main__":
    unittest.main()
