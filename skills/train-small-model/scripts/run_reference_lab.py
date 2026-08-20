#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs-dir", default="runs")
    parser.add_argument("--run-id")
    args = parser.parse_args()
    root = project_root()
    sys.path.insert(0, str(root))
    from model_harness.runner import run_task

    contract = root / "examples" / "digit-classification" / "task_contract.json"
    run_dir = run_task(contract, root / args.runs_dir, args.run_id)
    print(json.dumps({"ok": True, "run_dir": str(run_dir)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
