from __future__ import annotations

import unittest

from model_harness.errors import PluginError
from model_harness.plugins import PluginRegistry


class PluginRegistryTests(unittest.TestCase):
    def test_builtin_recipe_is_discoverable(self) -> None:
        registry = PluginRegistry()
        self.assertEqual(
            registry.recipe_ids(),
            ["digit-classification", "image-folder-classification", "tabular-regression"],
        )
        manifest = registry.get_recipe("digit-classification").manifest.to_dict()
        self.assertEqual(manifest["version"], "0.2.0")
        self.assertEqual(manifest["contract_schema_version"], "0.2")
        self.assertEqual(manifest["device"], "cpu")

    def test_capability_match_is_machine_readable_and_explainable(self) -> None:
        registry = PluginRegistry()
        matches = registry.match_recipes(
            {
                "modality": "tabular",
                "objective": "regression",
                "target_kind": "numeric",
                "data_adapter": "tabular-csv",
            }
        )
        self.assertEqual(matches[0]["plugin_id"], "tabular-regression")
        self.assertIn("objective=regression", matches[0]["reasons"])
        self.assertEqual(matches[0]["manifest"]["data_adapter"], "tabular-csv")

    def test_duplicate_plugin_id_is_rejected(self) -> None:
        registry = PluginRegistry()
        plugin = registry.get_recipe("digit-classification")
        with self.assertRaisesRegex(PluginError, "duplicate"):
            registry.register_recipe(plugin)


if __name__ == "__main__":
    unittest.main()
