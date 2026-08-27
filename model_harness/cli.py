from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from . import __version__
from .errors import ContractError, HarnessError, PluginError
from .io_utils import read_json


def _print_json(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def build_parser(*, prog: str = "specialist-model-studio") -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=prog,
        description="Run the auditable specialist-model training engine used by Specialist Model Studio.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list-recipes", help="List discovered recipe plugins.")

    init = sub.add_parser("init", help="Create a task contract from a recipe template.")
    init.add_argument(
        "--recipe",
        required=True,
        metavar="PLUGIN_ID",
        help="Recipe plugin id; run list-recipes to inspect discovered plugins.",
    )
    init.add_argument("--output", required=True)
    init.add_argument("--force", action="store_true")

    run = sub.add_parser("run", help="Validate a contract and execute its recipe.")
    run.add_argument("contract")
    run.add_argument("--runs-dir", default="runs")
    run.add_argument("--run-id")

    status = sub.add_parser("status", help="Read the persisted run state.")
    status.add_argument("run_dir")

    events = sub.add_parser("events", help="Read append-only run events.")
    events.add_argument("run_dir")
    events.add_argument("--after-seq", type=int, default=0)

    explain = sub.add_parser("explain", help="Print the learning report from a run.")
    explain.add_argument("run_dir")

    strategies = sub.add_parser(
        "strategies",
        help="Print optimization strategies proposed by a completed run.",
    )
    strategies.add_argument("run_dir")

    apply_strategy = sub.add_parser(
        "apply-strategy",
        help="Approve a strategy and execute it as a child run.",
    )
    apply_strategy.add_argument("run_dir")
    apply_strategy.add_argument("strategy_id")
    apply_strategy.add_argument("--run-id")

    resume = sub.add_parser(
        "resume",
        help="Create a child run from an interrupted, cancelled or failed run.",
    )
    resume.add_argument("run_dir")
    resume.add_argument("--run-id")

    verify = sub.add_parser("verify", help="Verify run hashes and acceptance evidence.")
    verify.add_argument("run_dir")
    verify.add_argument("--deep", action="store_true")

    start = sub.add_parser(
        "start",
        help="Start the complete local Studio with its real multi-agent runtime.",
    )
    start.add_argument("--runs-dir")
    start.add_argument("--host")
    start.add_argument("--port", type=int)
    start.add_argument("--agent-host")
    start.add_argument("--agent-port", type=int)

    serve = sub.add_parser(
        "serve",
        help="Advanced: start only the local backend HTTP/SSE API.",
    )
    serve.add_argument("--runs-dir", default="runs")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--max-workers", type=int, default=1)
    return parser


def _read_events(path: Path, after_seq: int) -> list[dict[str, Any]]:
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            record = json.loads(line)
            if int(record["seq"]) > after_seq:
                records.append(record)
    return records


def _start_studio(args: argparse.Namespace) -> int:
    """Run the audited source-checkout launcher without weakening its gates."""

    repository_root = Path(__file__).resolve().parents[1]
    launcher = repository_root / "scripts" / "start_conversation_harness.sh"
    if not launcher.is_file():
        raise RuntimeError(
            "The complete Studio launcher is not present in this installation. "
            "Run `specialist-model-studio start` from a Specialist Model Studio "
            "source checkout; `serve` remains available for backend-only use."
        )

    environment = dict(os.environ)
    environment["SPECIALIST_MODEL_STUDIO_PUBLIC_START"] = "1"
    environment["MODEL_HARNESS_PYTHON"] = sys.executable
    for argument, variable in (
        (args.runs_dir, "MODEL_HARNESS_RUNS_DIR"),
        (args.host, "MODEL_HARNESS_HOST"),
        (args.port, "MODEL_HARNESS_PORT"),
        (args.agent_host, "MODEL_HARNESS_AGENT_HOST"),
        (args.agent_port, "MODEL_HARNESS_AGENT_PORT"),
    ):
        if argument is not None:
            environment[variable] = str(argument)

    try:
        completed = subprocess.run(
            ["bash", str(launcher)],
            cwd=repository_root,
            env=environment,
            check=False,
        )
    except KeyboardInterrupt:
        return 130
    return int(completed.returncode)


def main(argv: list[str] | None = None) -> int:
    invoked_as = Path(sys.argv[0]).name if argv is None else "specialist-model-studio"
    args = build_parser(prog=invoked_as).parse_args(argv)
    try:
        if args.command == "list-recipes":
            from .plugins import default_registry

            registry = default_registry()
            _print_json(
                {
                    "version": __version__,
                    "recipes": registry.recipe_manifests(),
                }
            )
            return 0
        if args.command == "init":
            from .plugins import default_registry
            from .runner import initialize_workspace

            registry = default_registry()
            contract = initialize_workspace(
                args.recipe,
                args.output,
                args.force,
                registry=registry,
            )
            _print_json({"ok": True, "contract": str(contract)})
            return 0
        if args.command == "run":
            from .plugins import default_registry
            from .runner import run_task

            registry = default_registry()
            run_dir = run_task(
                args.contract,
                args.runs_dir,
                args.run_id,
                registry=registry,
            )
            state = read_json(run_dir / "run_state.json")
            _print_json(
                {
                    "ok": state["status"] == "completed",
                    "run_dir": str(run_dir),
                    "status": state["status"],
                    "offline_gates_passed": state.get("offline_gates_passed"),
                }
            )
            return 0 if state["status"] == "completed" else 1
        if args.command == "status":
            _print_json(read_json(Path(args.run_dir).resolve() / "run_state.json"))
            return 0
        if args.command == "events":
            run_dir = Path(args.run_dir).resolve()
            _print_json(
                {
                    "events": _read_events(
                        run_dir / "events.ndjson",
                        args.after_seq,
                    )
                }
            )
            return 0
        if args.command == "explain":
            report = Path(args.run_dir).resolve() / "artifacts" / "learning_report.md"
            print(report.read_text(encoding="utf-8"))
            return 0
        if args.command == "strategies":
            path = (
                Path(args.run_dir).resolve()
                / "artifacts"
                / "optimization_strategies.json"
            )
            _print_json(read_json(path))
            return 0
        if args.command in {"apply-strategy", "resume"}:
            from .plugins import default_registry
            from .service import RunService

            registry = default_registry()
            parent = Path(args.run_dir).resolve()
            with RunService(
                parent.parent,
                registry=registry,
                recover=False,
            ) as service:
                if args.command == "apply-strategy":
                    child = service.apply_strategy(
                        parent.name,
                        args.strategy_id,
                        child_run_id=args.run_id,
                    )
                else:
                    child = service.resume(parent.name, child_run_id=args.run_id)
                service.wait(child.name)
                state = service.status(child.name)
            _print_json(
                {
                    "ok": state["status"] == "completed",
                    "run_dir": str(child),
                    "parent_run_id": parent.name,
                    "status": state["status"],
                }
            )
            return 0 if state["status"] == "completed" else 1
        if args.command == "verify":
            from .plugins import default_registry
            from .runner import verify_run

            registry = default_registry()
            result = verify_run(args.run_dir, args.deep, registry=registry)
            _print_json(result)
            return 0 if result["ok"] else 1
        if args.command == "start":
            return _start_studio(args)
        if args.command == "serve":
            from .server import serve

            serve(
                runs_dir=args.runs_dir,
                host=args.host,
                port=args.port,
                max_workers=args.max_workers,
            )
            return 0
    except (
        ContractError,
        FileExistsError,
        FileNotFoundError,
        HarnessError,
        KeyError,
        PluginError,
        RuntimeError,
    ) as exc:
        _print_json({"ok": False, "error": f"{type(exc).__name__}: {exc}"})
        return 2
    return 1


if __name__ == "__main__":
    sys.exit(main())
