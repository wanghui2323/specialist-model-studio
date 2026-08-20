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
            app = create_app(temp_dir)
            with TestClient(app) as client:  # type: ignore[misc]
                health = client.get("/health")
                self.assertEqual(health.status_code, 200)
                self.assertTrue(health.json()["ok"])

                recipes = client.get("/recipes")
                self.assertEqual(recipes.status_code, 200)
                self.assertEqual(
                    recipes.json()["recipes"][0]["plugin_id"],
                    "digit-classification",
                )


if __name__ == "__main__":
    unittest.main()
