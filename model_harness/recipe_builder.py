from __future__ import annotations

import ast
import json
import zipfile
from pathlib import Path
from typing import Any

from .io_utils import write_json


def _python_name(value: str) -> str:
    selected = "".join(character if character.isalnum() else "_" for character in value)
    if not selected or selected[0].isdigit():
        selected = f"recipe_{selected}"
    return selected.lower()


class RecipeScaffoldBuilder:
    """Build a reviewable Code Agent packet without executing generated code."""

    def create(self, task_dir: Path, request: dict[str, Any]) -> dict[str, Any]:
        request_id = str(request["recipe_request_id"])
        plugin_id = str(request["suggested_plugin_id"])
        capability = request.get("capability_request", {})
        build_dir = task_dir / "recipe_builds" / request_id
        build_dir.mkdir(parents=True, exist_ok=True)
        module_name = _python_name(plugin_id)
        files = {
            "BUILD_REQUEST.json": json.dumps(request, ensure_ascii=False, indent=2) + "\n",
            "README.md": self._readme(plugin_id, capability),
            "recipe_plugin.py": self._recipe_source(plugin_id, capability),
            "data_adapter_plugin.py": self._adapter_source(plugin_id, capability),
            "test_recipe_contract.py": self._test_source(module_name),
            "pyproject.entry-points.toml": self._entry_points(plugin_id, module_name),
        }
        checks: list[dict[str, Any]] = []
        for name, content in files.items():
            target = build_dir / name
            target.write_text(content, encoding="utf-8")
            if name.endswith(".py"):
                ast.parse(content, filename=name)
                checks.append({"check": f"python-syntax:{name}", "passed": True})
        checks.extend(
            [
                {"check": "recipe-protocol-methods", "passed": all(method in files["recipe_plugin.py"] for method in ("validate_contract", "train", "evaluate", "package", "deep_verify"))},
                {"check": "entry-point-declared", "passed": "ai_pm_model_harness.recipes" in files["pyproject.entry-points.toml"]},
                {"check": "generated-code-not-executed", "passed": True},
            ]
        )
        report = {
            "schema_version": "0.1",
            "recipe_request_id": request_id,
            "plugin_id": plugin_id,
            "status": "scaffold_ready",
            "checks": checks,
            "execution_boundary": "Scaffold code is not trusted or executed. Complete implementation, tests, dependency/license review, and plugin installation are required before recipe selection.",
        }
        write_json(build_dir / "scaffold_report.json", report)
        archive_path = task_dir / "recipe_builds" / f"{request_id}.zip"
        with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(build_dir.iterdir()):
                if path.is_file():
                    archive.write(path, arcname=f"{plugin_id}/{path.name}")
        return {
            **report,
            "archive_name": archive_path.name,
            "file_count": len(files) + 1,
        }

    @staticmethod
    def _readme(plugin_id: str, capability: dict[str, Any]) -> str:
        return f"""# Recipe Build Packet: {plugin_id}

This packet was generated from a persistent Model Harness Recipe Build Request.

Capability request:

```json
{json.dumps(capability, ensure_ascii=False, indent=2)}
```

## Completion gate

1. Implement and test the Data Adapter against representative and invalid user data.
2. Implement contract validation, training, independent evaluation, artifact packaging, strategies, and deep verification.
3. Replace every `NotImplementedError`; pin dependencies and record model/dataset licenses.
4. Install the two declared entry points in an isolated environment.
5. Run one successful scenario, one invalid-data scenario, and deep artifact verification.

Model Harness never executes this generated scaffold automatically. A human or Code Agent must finish it, and the plugin must pass registration and runtime validation first.
"""

    @staticmethod
    def _recipe_source(plugin_id: str, capability: dict[str, Any]) -> str:
        modality = str(capability.get("modality", "custom"))
        objective = str(capability.get("objective", "custom"))
        target = str(capability.get("target_kind", "custom"))
        return f'''from pathlib import Path
from typing import Any

from model_harness.plugin_api import RecipeManifest, StrategyProposal


class GeneratedRecipe:
    manifest = RecipeManifest(
        plugin_id={plugin_id!r}, version="0.1.0", contract_schema_version="0.2",
        description="Generated scaffold; implementation required.", task_type={objective!r},
        input_description="Define the validated dataset contract.",
        output_description="Define metrics and deployable artifacts.", device="cpu",
        purpose="user-data", modalities=({modality!r},), objectives=({objective!r},),
        data_adapter={f'{plugin_id}-adapter'!r}, target_kinds=({target!r},),
        capability_tags=("generated-scaffold",),
    )

    def template(self) -> dict[str, Any]:
        return {{"schema_version": "0.2", "recipe": self.manifest.plugin_id, "dataset": {{}}, "recipe_options": {{}}, "release_gates": {{}}}}

    def validate_contract(self, contract: dict[str, Any]) -> None:
        raise NotImplementedError("Implement dataset, option, resource, and release-gate validation")

    def train(self, contract: dict[str, Any]) -> Any:
        raise NotImplementedError("Implement deterministic training and candidate evidence")

    def evaluate(self, training: Any, contract: dict[str, Any]) -> Any:
        raise NotImplementedError("Implement an independent test split and task metrics")

    def package(self, training: Any, evaluation: Any, contract: dict[str, Any], artifact_dir: Path) -> dict[str, Any]:
        raise NotImplementedError("Package model, metrics, failures, model card, and inference example")

    def propose_strategies(self, metrics: dict[str, Any], contract: dict[str, Any]) -> list[StrategyProposal]:
        return []

    def apply_strategy(self, contract: dict[str, Any], strategy_id: str) -> dict[str, Any]:
        raise NotImplementedError("Implement approved strategy mutation")

    def learning_report(self, contract: dict[str, Any], metrics: dict[str, Any], strategies: list[StrategyProposal]) -> str:
        return "Generated Recipe implementation report pending."

    def deep_verify(self, artifact_dir: Path) -> list[str]:
        raise NotImplementedError("Load the packaged model and reproduce test predictions")


PLUGIN = GeneratedRecipe()
'''

    @staticmethod
    def _adapter_source(plugin_id: str, capability: dict[str, Any]) -> str:
        modality = str(capability.get("modality", "custom"))
        return f'''from pathlib import Path
from typing import Any

from model_harness.data_adapters import DataAdapterManifest, DataImportResult


class GeneratedDataAdapter:
    manifest = DataAdapterManifest(
        adapter_id={f'{plugin_id}-adapter'!r}, version="0.1.0",
        description="Generated scaffold; implementation required.",
        modalities=({modality!r},), file_extensions=(".replace-me",),
    )

    def supports(self, filename: str) -> bool:
        return filename.lower().endswith(self.manifest.file_extensions)

    def import_data(self, datasets_dir: Path, payload: bytes, filename: str, options: dict[str, Any]) -> DataImportResult:
        raise NotImplementedError("Validate size, paths, schema, labels/targets, privacy, and write an immutable dataset report")


ADAPTER = GeneratedDataAdapter()
'''

    @staticmethod
    def _test_source(module_name: str) -> str:
        return f'''import unittest


class GeneratedRecipeContractTests(unittest.TestCase):
    def test_valid_representative_data_completes_full_loop(self):
        self.fail("TODO: import representative data, train, evaluate, package, and deep verify")

    def test_invalid_data_is_rejected_before_training(self):
        self.fail("TODO: prove malformed or unsafe data creates no run")


if __name__ == "__main__":
    unittest.main()
'''

    @staticmethod
    def _entry_points(plugin_id: str, module_name: str) -> str:
        return f'''[project.entry-points."ai_pm_model_harness.recipes"]
{module_name} = "recipe_plugin:PLUGIN"

[project.entry-points."ai_pm_model_harness.data_adapters"]
{module_name}_adapter = "data_adapter_plugin:ADAPTER"
'''
