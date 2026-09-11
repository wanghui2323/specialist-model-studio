from __future__ import annotations

import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from model_harness.contracts import ContractError, validate_contract
from model_harness.data_adapters import DataAdapterRegistry
from model_harness.plugins import PluginRegistry
from model_harness.templates import DIGIT_CLASSIFICATION_TEMPLATE
from tests.test_tabular_loop import build_regression_csv
from tests.test_workspace_loop import build_image_dataset_zip


class DiagnosticsGateTests(unittest.TestCase):
    def test_minimum_test_samples_one_is_rejected(self) -> None:
        contract = deepcopy(DIGIT_CLASSIFICATION_TEMPLATE)
        contract["diagnostics"]["minimum_test_samples"] = 1
        with self.assertRaisesRegex(
            ContractError,
            "diagnostics.minimum_test_samples must be an integer >= 20",
        ):
            validate_contract(contract)

    def test_minimum_test_samples_boundary(self) -> None:
        for value, valid in ((19, False), (20, True), (50, True)):
            with self.subTest(value=value):
                contract = deepcopy(DIGIT_CLASSIFICATION_TEMPLATE)
                contract["diagnostics"]["minimum_test_samples"] = value
                if valid:
                    validate_contract(contract)
                else:
                    with self.assertRaisesRegex(
                        ContractError,
                        "diagnostics.minimum_test_samples must be an integer >= 20",
                    ):
                        validate_contract(contract)

    def test_boolean_minimum_test_samples_is_rejected(self) -> None:
        contract = deepcopy(DIGIT_CLASSIFICATION_TEMPLATE)
        contract["diagnostics"]["minimum_test_samples"] = True
        with self.assertRaisesRegex(
            ContractError,
            "diagnostics.minimum_test_samples must be an integer >= 20",
        ):
            validate_contract(contract)

    def test_missing_minimum_test_samples_remains_valid(self) -> None:
        contract = deepcopy(DIGIT_CLASSIFICATION_TEMPLATE)
        contract["diagnostics"].pop("minimum_test_samples", None)
        validate_contract(contract)

    def test_all_builtin_recipe_templates_validate_with_real_dataset_bindings(self) -> None:
        registry = PluginRegistry(include_builtins=True)
        adapters = DataAdapterRegistry(include_builtins=True)
        validate_contract(
            deepcopy(registry.get_recipe("digit-classification").template()),
            registry=registry,
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            image_data = adapters.get("image-folder-zip").import_data(
                root / "image",
                build_image_dataset_zip(),
                "parts.zip",
                {},
            )
            image_contract = registry.get_recipe(
                "image-folder-classification"
            ).template()
            image_contract["dataset"].update(image_data.contract_dataset)
            validate_contract(image_contract, registry=registry)

            tabular_data = adapters.get("tabular-csv").import_data(
                root / "tabular",
                build_regression_csv(),
                "quality.csv",
                {
                    "target_column": "quality",
                    "ignored_columns": ["sample_id"],
                    "objective": "regression",
                },
            )
            tabular_contract = registry.get_recipe("tabular-regression").template()
            tabular_contract["dataset"].update(tabular_data.contract_dataset)
            validate_contract(tabular_contract, registry=registry)


if __name__ == "__main__":
    unittest.main()
