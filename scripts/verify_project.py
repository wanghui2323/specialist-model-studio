#!/usr/bin/env python3
from __future__ import annotations

import json
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
        "skills/train-small-model/SKILL.md",
        "examples/digit-classification/task_contract.json",
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
    summary = {
        "required_files_present": not missing,
        "missing": missing,
        "tests_passed": result.returncode == 0,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if not missing and result.returncode == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
