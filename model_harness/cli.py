from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .contracts import ContractError, SUPPORTED_RECIPES
from .io_utils import read_json
from .runner import initialize_workspace, run_task, verify_run


def _print_json(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="small-model-harness",
        description="Run auditable specialist-model training recipes.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list-recipes", help="List recipes implemented in this version.")

    init = sub.add_parser("init", help="Create a task contract from a recipe template.")
    init.add_argument("--recipe", required=True, choices=sorted(SUPPORTED_RECIPES))
    init.add_argument("--output", required=True)
    init.add_argument("--force", action="store_true")

    run = sub.add_parser("run", help="Validate a contract and execute its recipe.")
    run.add_argument("contract")
    run.add_argument("--runs-dir", default="runs")
    run.add_argument("--run-id")

    status = sub.add_parser("status", help="Read the persisted run state.")
    status.add_argument("run_dir")

    explain = sub.add_parser("explain", help="Print the learning report from a run.")
    explain.add_argument("run_dir")

    verify = sub.add_parser("verify", help="Verify run hashes and acceptance evidence.")
    verify.add_argument("run_dir")
    verify.add_argument("--deep", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "list-recipes":
            _print_json(
                {
                    "version": "0.1",
                    "recipes": [
                        {
                            "name": "digit-classification",
                            "status": "implemented",
                            "device": "cpu",
                            "purpose": "reference learning and harness validation",
                        }
                    ],
                }
            )
            return 0
        if args.command == "init":
            contract = initialize_workspace(args.recipe, args.output, args.force)
            _print_json({"ok": True, "contract": str(contract)})
            return 0
        if args.command == "run":
            run_dir = run_task(args.contract, args.runs_dir, args.run_id)
            state = read_json(run_dir / "run_state.json")
            _print_json(
                {
                    "ok": True,
                    "run_dir": str(run_dir),
                    "status": state["status"],
                    "offline_gates_passed": state["offline_gates_passed"],
                }
            )
            return 0
        if args.command == "status":
            _print_json(read_json(Path(args.run_dir).resolve() / "run_state.json"))
            return 0
        if args.command == "explain":
            report = (
                Path(args.run_dir).resolve()
                / "artifacts"
                / "learning_report.md"
            )
            print(report.read_text(encoding="utf-8"))
            return 0
        if args.command == "verify":
            result = verify_run(args.run_dir, args.deep)
            _print_json(result)
            return 0 if result["ok"] else 1
    except (ContractError, FileExistsError, FileNotFoundError, KeyError) as exc:
        _print_json({"ok": False, "error": f"{type(exc).__name__}: {exc}"})
        return 2
    return 1


if __name__ == "__main__":
    sys.exit(main())
