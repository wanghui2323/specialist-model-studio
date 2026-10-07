from __future__ import annotations

import unittest

from model_harness.errors import PluginError
from model_harness.plugins import PluginRegistry


class PluginRegistryTests(unittest.TestCase):
    def test_builtin_recipe_is_discoverable(self) -> None:
        registry = PluginRegistry()
        self.assertEqual(
            registry.recipe_ids(),
            [
                "digit-classification",
                "generic-isolated-execution",
                "image-folder-classification",
                "tabular-classification",
                "tabular-regression",
            ],
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

    def test_explicit_training_route_cannot_be_replaced_by_a_cached_recipe(self) -> None:
        registry = PluginRegistry()
        self.assertTrue(registry.match_recipes({"modality": "image", "objective": "classification"}))
        self.assertEqual(registry.match_recipes({
            "modality": "image", "objective": "classification",
            "training_route": "fine_tune",
        }), [])


if __name__ == "__main__":
    unittest.main()

    def test_implementation_reuse_preference_is_not_a_training_route_requirement(self):
        registry=PluginRegistry()
        capability={'modality':'tabular','objective':'regression','target_kind':'continuous','data_adapter':'tabular-csv'}
        baseline=registry.match_recipes(capability)
        self.assertIn('tabular-regression',[m['recipe']['plugin_id'] if 'recipe' in m else m['plugin_id'] for m in baseline])
        for preference in ['verified_recipe','registered_recipe','existing_recipe','generic_execution']:
            self.assertEqual(registry.match_recipes({**capability,'training_route':preference}),baseline)
        self.assertEqual(registry.match_recipes({**capability,'training_route':'fine_tune'}),[])
