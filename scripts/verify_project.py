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
        "model_harness/chat.py",
        "model_harness/agent_bridge.py",
        "model_harness/workspace.py",
        "model_harness/data_adapters.py",
        "model_harness/recipe_builder.py",
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
        "skills/train-small-model/SKILL.md",
        "examples/digit-classification/task_contract.json",
        "tests/test_workspace_loop.py",
        "tests/test_tabular_loop.py",
        "scripts/run_real_scenarios.py",
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
