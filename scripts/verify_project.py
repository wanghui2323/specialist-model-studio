#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    required = [
        "README.md",
        "LICENSE",
        "SECURITY.md",
        "THIRD_PARTY.md",
        "pyproject.toml",
        "docs/v0.3-conversation-console.md",
        "docs/v0.4-real-training-loop.md",
        "docs/v0.5-conversational-harness.md",
        "docs/v0.6-generic-training-harness.md",
        "docs/v0.7-beta-boundaries.md",
        "model_harness/chat.py",
        "model_harness/agent_bridge.py",
        "model_harness/workspace.py",
        "model_harness/data_adapters.py",
        "model_harness/recipe_builder.py",
        "model_harness/task_specs.py",
        "model_harness/staged_assets.py",
        "model_harness/recipe_factory.py",
        "model_harness/recipe_versions.py",
        "model_harness/audio_keyword.py",
        "model_harness/model_assets.py",
        "model_harness/huggingface_assets.py",
        "model_harness/huggingface_catalog.py",
        "model_harness/onnx_image_features.py",
        "model_harness/evidence.py",
        "model_harness/sample_inference.py",
        "model_harness/optimization.py",
        "model_harness/recipes/audio_keyword_plugin.py",
        "model_harness/recipes/image_folder_classification.py",
        "model_harness/recipes/image_folder_plugin.py",
        "model_harness/recipes/tabular_regression.py",
        "model_harness/recipes/tabular_regression_plugin.py",
        "model_harness/web/index.html",
        "model_harness/web/styles.css",
        "model_harness/web/app.js",
        "integrations/deepseek-harness/package.json",
        "integrations/deepseek-harness/index.js",
        "integrations/deepseek-harness/cordis.patch.yml",
        "integrations/deepseek-harness/presets/model-training/agent.cordis.yml",
        "integrations/deepseek-harness/presets/model-training/preset.yml",
        "scripts/install_dsh_preset.sh",
        "scripts/start_conversation_harness.sh",
        "scripts/acceptance_evidence.py",
        "scripts/collect_v07_external_evidence.py",
        "scripts/prepare_v07_acceptance_runtime.py",
        "scripts/run_hf_real_scenario.py",
        "scripts/verify_v07_beta.py",
        "acceptance/v0.7-gates.json",
        "acceptance/report.schema.json",
        "acceptance/external-evidence.schema.json",
        "acceptance/browser-report.schema.json",
        "acceptance/process-restart-report.schema.json",
        "acceptance/cold-clone-report.schema.json",
        "acceptance/browser/package.json",
        "acceptance/browser/package-lock.json",
        "acceptance/browser/collect-browser.mjs",
        "skills/train-small-model/SKILL.md",
        "examples/digit-classification/task_contract.json",
        "tests/test_workspace_loop.py",
        "tests/test_tabular_loop.py",
        "scripts/run_real_scenarios.py",
        "tests/test_acceptance_contract.py",
        "tests/test_acceptance_evidence.py",
        "tests/test_repository_truth.py",
    ]
    missing = [name for name in required if not (ROOT / name).is_file()]
    json.loads(
        (ROOT / "examples/digit-classification/task_contract.json").read_text(
            encoding="utf-8"
        )
    )
    result = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
        cwd=ROOT,
        check=False,
    )
    node_available = shutil.which("npm") is not None
    node_checks_passed = False
    if node_available:
        integration_dir = ROOT / "integrations" / "deepseek-harness"
        node_test = subprocess.run(
            ["npm", "test"], cwd=integration_dir, check=False
        )
        node_check = subprocess.run(
            ["npm", "run", "check"], cwd=integration_dir, check=False
        )
        node_checks_passed = node_test.returncode == 0 and node_check.returncode == 0
    summary = {
        "required_files_present": not missing,
        "missing": missing,
        "tests_passed": result.returncode == 0,
        "node_available": node_available,
        "dsh_adapter_checks_passed": node_checks_passed,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if not missing and result.returncode == 0 and node_checks_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
