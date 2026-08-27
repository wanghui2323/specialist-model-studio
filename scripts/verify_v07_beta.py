#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.acceptance_evidence import (  # noqa: E402
    SchemaValidationError,
    pid_is_alive,
    png_dimensions,
    read_json_object,
    read_ndjson,
    resolve_artifact,
    sha256_file,
    validate_json_schema,
)

GATES_PATH = ROOT / "acceptance" / "v0.7-gates.json"
REPORT_SCHEMA_PATH = ROOT / "acceptance" / "report.schema.json"
EXTERNAL_SCHEMA_PATH = ROOT / "acceptance" / "external-evidence.schema.json"
BROWSER_REPORT_SCHEMA_PATH = ROOT / "acceptance" / "browser-report.schema.json"
PROCESS_REPORT_SCHEMA_PATH = ROOT / "acceptance" / "process-restart-report.schema.json"
COLD_CLONE_REPORT_SCHEMA_PATH = ROOT / "acceptance" / "cold-clone-report.schema.json"
CONTROLLED_PRODUCER_PATH = ROOT / "scripts" / "collect_v07_external_evidence.py"
CONTROLLED_SOURCE_FILES = {
    "python_producer": "scripts/collect_v07_external_evidence.py",
    "browser_producer": "acceptance/browser/collect-browser.mjs",
    "browser_package": "acceptance/browser/package.json",
    "browser_lock": "acceptance/browser/package-lock.json",
}
ALLOWED_STATUSES = {"passed", "failed", "blocked"}
COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
CHROME_CANDIDATES = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
)
TOOL_CANDIDATES = {
    "git": ("/usr/bin/git", "/usr/local/bin/git", "/opt/homebrew/bin/git"),
    "node": ("/usr/local/bin/node", "/opt/homebrew/bin/node", "/usr/bin/node"),
    "npm": ("/usr/local/bin/npm", "/opt/homebrew/bin/npm", "/usr/bin/npm"),
    "uv": (
        "/Library/Frameworks/Python.framework/Versions/3.12/bin/uv",
        "/usr/local/bin/uv",
        "/opt/homebrew/bin/uv",
        "/usr/bin/uv",
    ),
    "gh": ("/usr/local/bin/gh", "/opt/homebrew/bin/gh", "/usr/bin/gh"),
    "chrome": CHROME_CANDIDATES,
}


class LoadedExternalEvidence:
    def __init__(
        self,
        *,
        manifest: dict[str, Any],
        path: Path,
        root: Path,
        manifest_sha256: str,
        artifact_paths: dict[str, Path],
        reports: dict[str, dict[str, Any]],
    ) -> None:
        self.manifest = manifest
        self.path = path
        self.root = root
        self.manifest_sha256 = manifest_sha256
        self.artifact_paths = artifact_paths
        self.reports = reports


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return value


def instantiate_levels(config: dict[str, Any]) -> list[dict[str, Any]]:
    levels: list[dict[str, Any]] = []
    for level in config["levels"]:
        levels.append(
            {
                "level_id": str(level["level_id"]),
                "name": str(level["name"]),
                "status": "blocked",
                "gates": [
                    {
                        "gate_id": str(gate["gate_id"]),
                        "required": bool(gate["required"]),
                        "required_for_github_release": bool(
                            gate.get("required_for_github_release", False)
                        ),
                        "status": "blocked",
                        "summary": "No executable acceptance evidence has been collected.",
                        "evidence": {},
                        "blockers": ["acceptance_evidence_missing"],
                    }
                    for gate in level["gates"]
                ],
            }
        )
    recompute_level_statuses(levels)
    return levels


def _gate_index(levels: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        str(gate["gate_id"]): gate
        for level in levels
        for gate in level["gates"]
    }


def set_gate(
    levels: list[dict[str, Any]],
    gate_id: str,
    status: str,
    summary: str,
    *,
    evidence: dict[str, Any] | None = None,
    blockers: Iterable[str] = (),
) -> None:
    if status not in ALLOWED_STATUSES:
        raise ValueError(f"invalid gate status: {status}")
    selected = _gate_index(levels).get(gate_id)
    if selected is None:
        raise KeyError(f"unknown acceptance gate: {gate_id}")
    blocker_values = [str(item) for item in blockers if str(item)]
    if status == "passed" and blocker_values:
        raise ValueError("a passed gate cannot retain blockers")
    selected.update(
        {
            "status": status,
            "summary": summary,
            "evidence": deepcopy(evidence or {}),
            "blockers": blocker_values,
        }
    )


def recompute_level_statuses(levels: list[dict[str, Any]]) -> None:
    for level in levels:
        required = [gate for gate in level["gates"] if gate["required"]]
        statuses = [str(gate["status"]) for gate in required]
        invalid = sorted(set(statuses) - ALLOWED_STATUSES)
        if invalid:
            raise ValueError(f"invalid required gate status: {invalid}")
        if "failed" in statuses:
            level["status"] = "failed"
        elif "blocked" in statuses:
            level["status"] = "blocked"
        else:
            level["status"] = "passed"


def summarize_levels(
    levels: list[dict[str, Any]],
    *,
    github_released: bool = False,
) -> dict[str, Any]:
    recompute_level_statuses(levels)
    required = [
        gate
        for level in levels
        for gate in level["gates"]
        if gate["required"]
    ]
    statuses = [str(gate["status"]) for gate in required]
    invalid = sorted(set(statuses) - ALLOWED_STATUSES)
    if invalid:
        raise ValueError(f"invalid required gate status: {invalid}")
    local_beta_verified = all(level["status"] == "passed" for level in levels)
    effective_github_release = bool(github_released and local_beta_verified)
    if effective_github_release:
        release_state = "github_released"
    elif local_beta_verified:
        release_state = "local_beta_verified"
    else:
        release_state = "blocked_local_beta"
    return {
        "local_beta_verified": local_beta_verified,
        "github_released": effective_github_release,
        "required_gate_counts": {
            "total": len(required),
            "passed": statuses.count("passed"),
            "failed": statuses.count("failed"),
            "blocked": statuses.count("blocked"),
        },
        "blocking_gate_ids": sorted(
            str(gate["gate_id"])
            for gate in required
            if gate["status"] == "blocked"
        ),
        "failed_gate_ids": sorted(
            str(gate["gate_id"])
            for gate in required
            if gate["status"] == "failed"
        ),
        "release_state": release_state,
    }


def github_release_gate_passed(levels: list[dict[str, Any]]) -> bool:
    release_gates = [
        gate
        for level in levels
        for gate in level["gates"]
        if gate.get("required_for_github_release") is True
    ]
    return bool(release_gates) and all(
        gate.get("status") == "passed" for gate in release_gates
    )


def validate_report_shape(
    report: dict[str, Any],
    config: dict[str, Any],
) -> None:
    validate_json_schema(report, load_json(REPORT_SCHEMA_PATH))
    required_top = {
        "schema_version",
        "acceptance_id",
        "iteration",
        "started_at_utc",
        "finished_at_utc",
        "source",
        "isolation",
        "external_evidence",
        "commands",
        "levels",
        "summary",
    }
    if set(report) != required_top:
        raise ValueError("acceptance report top-level fields do not match schema")
    levels = report.get("levels")
    if not isinstance(levels, list) or len(levels) != 6:
        raise ValueError("acceptance report must contain exactly L0-L5")
    configured_levels = [str(item["level_id"]) for item in config["levels"]]
    actual_levels = [str(item.get("level_id")) for item in levels]
    if actual_levels != configured_levels:
        raise ValueError("acceptance report levels are missing, duplicated or reordered")
    configured_gates = {
        str(gate["gate_id"])
        for level in config["levels"]
        for gate in level["gates"]
    }
    actual_gates = {
        str(gate.get("gate_id"))
        for level in levels
        for gate in level.get("gates", [])
    }
    if actual_gates != configured_gates:
        raise ValueError("acceptance report gates do not match gate contract")
    configured_required = {
        str(gate["gate_id"]): bool(gate["required"])
        for level in config["levels"]
        for gate in level["gates"]
    }
    actual_required = {
        str(gate.get("gate_id")): gate.get("required")
        for level in levels
        for gate in level.get("gates", [])
    }
    if actual_required != configured_required:
        raise ValueError("acceptance report required flags do not match gate contract")
    configured_release_required = {
        str(gate["gate_id"]): bool(gate.get("required_for_github_release", False))
        for level in config["levels"]
        for gate in level["gates"]
    }
    actual_release_required = {
        str(gate.get("gate_id")): gate.get("required_for_github_release")
        for level in levels
        for gate in level.get("gates", [])
    }
    if actual_release_required != configured_release_required:
        raise ValueError(
            "acceptance report GitHub release flags do not match gate contract"
        )
    if any(level.get("status") not in ALLOWED_STATUSES for level in levels):
        raise ValueError("acceptance report contains a forbidden level status")
    if any(
        gate.get("status") not in ALLOWED_STATUSES
        for level in levels
        for gate in level.get("gates", [])
    ):
        raise ValueError("acceptance report contains a forbidden gate status")
    expected_levels = deepcopy(levels)
    recompute_level_statuses(expected_levels)
    if [item["status"] for item in expected_levels] != [
        item["status"] for item in levels
    ]:
        raise ValueError("a level status does not match its required gates")
    expected_summary = summarize_levels(
        deepcopy(levels),
        github_released=github_release_gate_passed(levels),
    )
    if report["summary"] != expected_summary:
        raise ValueError("acceptance summary is not derived from required gates")


def _display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path.resolve())


def _display_command(command: list[str]) -> list[str]:
    selected: list[str] = []
    for value in command:
        path = Path(value)
        if path.is_absolute():
            selected.append(_display_path(path))
        else:
            selected.append(value)
    return selected


def _trusted_executable(candidates: Iterable[str]) -> str:
    selected = tuple(candidates)
    for candidate in selected:
        path = Path(candidate)
        if path.is_file() and os.access(path, os.X_OK):
            return str(path.resolve())
    return str(Path(selected[0]))


def _trusted_tools(python_executable: str) -> dict[str, str]:
    tools = {
        name: _trusted_executable(candidates)
        for name, candidates in TOOL_CANDIDATES.items()
    }
    python = Path(python_executable)
    # Keep the venv launcher path: resolving its symlink would bypass
    # pyvenv.cfg and execute outside the pinned project environment.
    tools["python"] = str(python.absolute())
    return tools


def _base_trusted_environment(tools: dict[str, str]) -> dict[str, str]:
    environment = {
        key: os.environ[key]
        for key in (
            "HOME",
            "USER",
            "LOGNAME",
            "LANG",
            "LC_ALL",
            "LC_CTYPE",
            "TZ",
            "TERM",
            "SSL_CERT_FILE",
            "SSL_CERT_DIR",
            "REQUESTS_CA_BUNDLE",
            "CURL_CA_BUNDLE",
        )
        if key in os.environ and "\0" not in os.environ[key]
    }
    tool_directories = [str(Path(value).parent) for value in tools.values()]
    fixed_directories = ["/usr/bin", "/bin", "/usr/sbin", "/sbin"]
    environment["PATH"] = os.pathsep.join(
        dict.fromkeys([*tool_directories, *fixed_directories])
    )
    environment.update(
        {
            "PYTHONUNBUFFERED": "1",
            "PYTHONNOUSERSITE": "1",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "NPM_CONFIG_USERCONFIG": "/dev/null",
            "UV_NO_CONFIG": "1",
        }
    )
    return environment


def _redacted_environment(
    runtime_root: Path,
    tools: dict[str, str] | None = None,
) -> dict[str, str]:
    selected_tools = tools or _trusted_tools(sys.executable)
    environment = _base_trusted_environment(selected_tools)
    temp_root = runtime_root / "tmp"
    temp_root.mkdir(parents=True, exist_ok=True)
    shared_hf_hub_cache = (
        Path.home().resolve() / ".cache" / "huggingface" / "hub"
    )
    environment.update(
        {
            "TMPDIR": str(temp_root),
            "PYTHONPYCACHEPREFIX": str(runtime_root / "pycache"),
            "XDG_CACHE_HOME": str(runtime_root / "cache"),
            "HF_HOME": str(runtime_root / "hf-home"),
            "HF_HUB_CACHE": str(shared_hf_hub_cache),
            "HF_HUB_DISABLE_XET": "1",
            "TRANSFORMERS_CACHE": str(runtime_root / "hf-home" / "transformers"),
            "MODEL_HARNESS_ACCEPTANCE_ROOT": str(runtime_root),
            "MODEL_HARNESS_ACCEPTANCE": "1",
        }
    )
    return environment


def run_command(
    command_id: str,
    command: list[str],
    *,
    cwd: Path,
    environment: dict[str, str],
    logs_dir: Path,
    timeout_seconds: float = 600.0,
    blocked_exit_codes: Iterable[int] = (),
) -> dict[str, Any]:
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = logs_dir / f"{command_id}.log"
    executable = command[0]
    if Path(executable).is_absolute():
        available = Path(executable).is_file()
    else:
        available = shutil.which(executable, path=environment.get("PATH")) is not None
    if not available:
        output = f"required executable is unavailable: {executable}\n"
        log_path.write_text(output, encoding="utf-8")
        return {
            "command": _display_command(command),
            "cwd": _display_path(cwd),
            "status": "blocked",
            "exit_code": None,
            "duration_seconds": 0.0,
            "log_path": str(Path("logs") / log_path.name),
            "output_tail": output.splitlines(),
        }
    started = time.perf_counter()
    process = subprocess.Popen(
        command,
        cwd=cwd,
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        start_new_session=os.name == "posix",
    )
    try:
        output, _ = process.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired as error:
        if os.name == "posix":
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        else:
            process.terminate()
        try:
            trailing, _ = process.communicate(timeout=3)
        except subprocess.TimeoutExpired:
            if os.name == "posix":
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            else:
                process.kill()
            trailing, _ = process.communicate()
        duration = time.perf_counter() - started
        output = error.stdout or ""
        if isinstance(output, bytes):
            output = output.decode("utf-8", errors="replace")
        if trailing and trailing not in output:
            output += trailing
        output += f"\nacceptance command timed out after {timeout_seconds} seconds\n"
        log_path.write_text(output, encoding="utf-8")
        return {
            "command": _display_command(command),
            "cwd": _display_path(cwd),
            "status": "failed",
            "exit_code": None,
            "duration_seconds": round(duration, 6),
            "log_path": str(Path("logs") / log_path.name),
            "output_tail": [line[-500:] for line in output.splitlines()[-20:]],
        }
    duration = time.perf_counter() - started
    output = output or ""
    log_path.write_text(output, encoding="utf-8")
    blocked_codes = {int(value) for value in blocked_exit_codes}
    if process.returncode == 0:
        status = "passed"
    elif process.returncode in blocked_codes:
        status = "blocked"
    else:
        status = "failed"
    return {
        "command": _display_command(command),
        "cwd": _display_path(cwd),
        "status": status,
        "exit_code": int(process.returncode),
        "duration_seconds": round(duration, 6),
        "log_path": str(Path("logs") / log_path.name),
        "output_tail": [line[-500:] for line in output.splitlines()[-20:]],
    }


def command_not_run(
    command_id: str,
    command: list[str],
    *,
    cwd: Path,
    logs_dir: Path,
    status: str,
    reason: str,
) -> dict[str, Any]:
    if status not in {"failed", "blocked"}:
        raise ValueError("an unexecuted command must be failed or blocked")
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = logs_dir / f"{command_id}.log"
    log_path.write_text(reason + "\n", encoding="utf-8")
    return {
        "command": _display_command(command),
        "cwd": _display_path(cwd),
        "status": status,
        "exit_code": None,
        "duration_seconds": 0.0,
        "log_path": str(Path("logs") / log_path.name),
        "output_tail": [reason],
    }


def combine_command_status(
    commands: dict[str, dict[str, Any]],
    command_ids: Iterable[str],
) -> str:
    statuses = [commands[item]["status"] for item in command_ids]
    if "failed" in statuses:
        return "failed"
    if "blocked" in statuses:
        return "blocked"
    return "passed"


def _runs_metadata_fingerprint() -> str:
    runs_dir = ROOT / "runs"
    records: list[tuple[str, int, int]] = []
    if runs_dir.is_dir():
        for path in sorted(runs_dir.rglob("*")):
            relative = path.relative_to(runs_dir)
            if relative.parts and relative.parts[0] == "acceptance":
                continue
            if path.is_file() and not path.is_symlink():
                stat_result = path.stat()
                records.append(
                    (relative.as_posix(), stat_result.st_size, stat_result.st_mtime_ns)
                )
    payload = json.dumps(records, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _git_value(
    *arguments: str,
    tools: dict[str, str] | None = None,
) -> str | None:
    selected_tools = tools or _trusted_tools(sys.executable)
    try:
        result = subprocess.run(
            [selected_tools["git"], *arguments],
            cwd=ROOT,
            env=_base_trusted_environment(selected_tools),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def normalize_version(value: str | None) -> str | None:
    if not value:
        return None
    selected = value.strip().lower()
    selected = re.sub(r"^(\d+\.\d+\.\d+)a(\d+)$", r"\1-alpha.\2", selected)
    selected = re.sub(r"^(\d+\.\d+\.\d+)b(\d+)$", r"\1-beta.\2", selected)
    return selected


def source_snapshot(tools: dict[str, str] | None = None) -> dict[str, Any]:
    selected_tools = tools or _trusted_tools(sys.executable)
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    pyproject_version = str(pyproject.get("project", {}).get("version") or "") or None
    server_source = (ROOT / "model_harness" / "server.py").read_text(encoding="utf-8")
    server_match = re.search(r"version\s*=\s*[\"']([^\"']+)", server_source)
    package_source = (ROOT / "model_harness" / "__init__.py").read_text(
        encoding="utf-8"
    )
    package_match = re.search(r"__version__\s*=\s*[\"']([^\"']+)", package_source)
    node_package = load_json(ROOT / "integrations" / "deepseek-harness" / "package.json")
    versions = {
        "pyproject": pyproject_version,
        "server": server_match.group(1) if server_match else None,
        "python_package": package_match.group(1) if package_match else None,
        "node_adapter": str(node_package.get("version") or "") or None,
    }
    versions["normalized"] = {
        key: normalize_version(value) for key, value in versions.items()
    }
    status = _git_value("status", "--porcelain", tools=selected_tools)
    return {
        "git_commit": _git_value("rev-parse", "HEAD", tools=selected_tools),
        "git_branch": _git_value("branch", "--show-current", tools=selected_tools),
        "worktree_clean": status == "" if status is not None else False,
        "versions": versions,
    }


def probe_contract(config: dict[str, Any]) -> tuple[str, dict[str, Any], list[str]]:
    try:
        schema = load_json(REPORT_SCHEMA_PATH)
        external_schema = load_json(
            ROOT / "acceptance" / "external-evidence.schema.json"
        )
        loop = load_json(ROOT / "plans" / "v0.7-real-training-beta" / "loop-tasks.json")
        requirements = (
            ROOT / "plans" / "v0.7-real-training-beta" / "requirements.md"
        ).read_text(encoding="utf-8")
        level_ids = [item["level_id"] for item in config["levels"]]
        loop_ids = [item["loop_id"] for item in loop["loops"]]
        allowed_lifecycle = {"planned", "implementing", "implemented", "verified", "accepted"}
        lifecycle_values = {
            str(item["status"])
            for level in loop["loops"]
            for item in [level, *level.get("tasks", [])]
        }
        optional_local_gates = [
            gate
            for level in config["levels"]
            for gate in level["gates"]
            if not gate["required"]
        ]
        hf_scenario = config["live_scenarios"][
            "official_huggingface_fixed_commit"
        ]
        assertions = {
            "gate_levels_are_L0_to_L5": level_ids == [f"L{index}" for index in range(6)],
            "loop_levels_are_L0_to_L5": loop_ids == [f"L{index}" for index in range(6)],
            "lifecycle_values_allowed": lifecycle_values <= allowed_lifecycle,
            "report_schema_is_object": schema.get("type") == "object",
            "external_schema_is_object": external_schema.get("type") == "object",
            "release_gate_is_only_local_optional": [
                gate["gate_id"] for gate in optional_local_gates
            ]
            == ["L5-release-chain"],
            "release_gate_controls_github_only": bool(optional_local_gates)
            and optional_local_gates[0].get("required_for_github_release") is True,
            "hf_scenario_uses_fixed_commit": bool(
                COMMIT_PATTERN.fullmatch(str(hf_scenario.get("commit", "")))
            ),
            "requirements_declare_truth_boundary": "不承诺\u201c所有模型现在都能训练\u201d" in requirements,
        }
        status = "passed" if all(assertions.values()) else "failed"
        blockers = [] if status == "passed" else ["contract_assertion_failed"]
        return status, {"assertions": assertions}, blockers
    except (OSError, ValueError, KeyError, TypeError) as error:
        return "failed", {"error": str(error)}, ["contract_unreadable"]


def probe_service(runtime_root: Path) -> tuple[str, dict[str, Any], list[str]]:
    evidence: dict[str, Any] = {}
    try:
        from fastapi.testclient import TestClient

        from model_harness.server import create_app

        app = create_app(runtime_root / "service-runs")
        with TestClient(app) as client:
            health = client.get("/health")
            evidence["health_status"] = health.status_code
            evidence["health_version"] = (
                health.json().get("version") if health.status_code == 200 else None
            )
            try:
                openapi = client.get("/openapi.json")
                evidence["openapi_status"] = openapi.status_code
                evidence["openapi_path_count"] = (
                    len(openapi.json().get("paths", {}))
                    if openapi.status_code == 200
                    else 0
                )
            except Exception as error:
                evidence["openapi_status"] = 500
                evidence["openapi_error"] = f"{type(error).__name__}: {error}"
        passed = (
            evidence.get("health_status") == 200
            and evidence.get("openapi_status") == 200
            and int(evidence.get("openapi_path_count", 0)) > 0
        )
        return (
            "passed" if passed else "failed",
            evidence,
            [] if passed else ["health_or_openapi_failed"],
        )
    except Exception as error:
        evidence["probe_error"] = f"{type(error).__name__}: {error}"
        return "failed", evidence, ["fresh_service_probe_failed"]


def probe_registry() -> tuple[str, dict[str, Any], list[str]]:
    try:
        from model_harness.data_adapters import default_data_adapter_registry
        from model_harness.plugins import default_registry

        recipes = default_registry().recipe_ids()
        adapters = default_data_adapter_registry().adapter_ids()
        expected_recipes = [
            "digit-classification",
            "image-folder-classification",
            "tabular-regression",
        ]
        expected_adapters = ["image-folder-zip", "tabular-csv"]
        assertions = {
            "builtin_recipes_exact": recipes == expected_recipes,
            "builtin_adapters_exact": adapters == expected_adapters,
            "audio_requires_dynamic_registration": "audio-keyword-classification"
            not in recipes,
        }
        status = "passed" if all(assertions.values()) else "failed"
        return (
            status,
            {"recipes": recipes, "data_adapters": adapters, "assertions": assertions},
            [] if status == "passed" else ["registry_claim_mismatch"],
        )
    except Exception as error:
        return "failed", {"error": str(error)}, ["registry_probe_failed"]


def probe_huggingface_real_report(
    report_root: Path,
    command_status: str,
    scenario_contract: dict[str, Any],
) -> tuple[str, dict[str, Any], list[str]]:
    report_paths = sorted(report_root.glob("*/report.json"))
    if len(report_paths) != 1:
        status = "blocked" if command_status == "blocked" else "failed"
        return status, {"report_count": len(report_paths)}, ["hf_real_report_missing_or_ambiguous"]
    try:
        report = load_json(report_paths[0])
    except (OSError, ValueError, json.JSONDecodeError) as error:
        return "failed", {"error": str(error)}, ["hf_real_report_unreadable"]
    scenario = report.get("scenario_evidence")
    restart = report.get("restart")
    if not isinstance(scenario, dict) or not isinstance(restart, dict):
        error = str(report.get("error", ""))
        external_unavailable = any(
            marker in error.lower()
            for marker in (
                "huggingface_download_failed",
                "capability unavailable",
                "name resolution",
                "connection",
                "timed out",
            )
        )
        status = "blocked" if external_unavailable else "failed"
        return (
            status,
            {
                "scenario": report.get("scenario"),
                "report_status": report.get("status"),
                "error": error,
            },
            ["hf_external_service_unavailable" if external_unavailable else "hf_real_scenario_failed"],
        )
    asset_files = scenario.get("asset_files")
    dataset = scenario.get("dataset")
    run = scenario.get("run")
    evaluation = scenario.get("evaluation")
    inference = scenario.get("new_sample_inference")
    bundle = scenario.get("artifact_bundle")
    privacy = bundle.get("privacy_boundary", {}) if isinstance(bundle, dict) else {}
    assertions = {
        "command_passed": command_status == "passed",
        "report_passed": report.get("status") == "passed",
        "official_client_declared": scenario_contract.get("client")
        == "official_huggingface_hub",
        "repository_matches": scenario.get("repository") == scenario_contract.get("repo_id"),
        "immutable_commit_requested": bool(
            COMMIT_PATTERN.fullmatch(str(scenario_contract.get("commit", "")))
        ),
        "resolved_commit_matches": scenario.get("resolved_commit")
        == scenario_contract.get("commit"),
        "asset_manifest_hashed": bool(
            SHA256_PATTERN.fullmatch(str(scenario.get("asset_manifest_sha256", "")))
        ),
        "asset_files_hashed": isinstance(asset_files, list)
        and bool(asset_files)
        and all(
            isinstance(item, dict)
            and SHA256_PATTERN.fullmatch(str(item.get("sha256", "")))
            for item in asset_files
        ),
        "dataset_size_matches": isinstance(dataset, dict)
        and dataset.get("total_images") == scenario_contract.get("dataset_total_images"),
        "real_training_completed": isinstance(run, dict)
        and run.get("status") == "completed"
        and run.get("release_ready") is True
        and isinstance(run.get("total_duration_ms"), (int, float))
        and float(run["total_duration_ms"]) > 0,
        "hf_features_consumed": isinstance(run, dict)
        and run.get("feature_source") == "huggingface_onnx_plus_rgb_gradient_v1",
        "independent_test_evidence": isinstance(evaluation, dict)
        and evaluation.get("conclusion") == "release_ready"
        and isinstance(evaluation.get("test_sample_count"), int)
        and evaluation["test_sample_count"]
        >= int(scenario_contract.get("minimum_test_samples", 1)),
        "new_sample_inference_passed": isinstance(inference, dict)
        and inference.get("status") == "passed"
        and bool(SHA256_PATTERN.fullmatch(str(inference.get("sample_sha256", "")))),
        "bundle_hash_verified": isinstance(bundle, dict)
        and bundle.get("sha256") == bundle.get("download_sha256")
        and bool(SHA256_PATTERN.fullmatch(str(bundle.get("sha256", "")))),
        "bundle_privacy_boundary": isinstance(privacy, dict)
        and privacy.get("raw_data_included") is False,
        "application_restart_passed": restart.get("passed") is True
        and all((restart.get("assertions") or {}).values()),
    }
    passed = all(assertions.values())
    evidence = {
        "scenario": report.get("scenario"),
        "repository": scenario.get("repository"),
        "requested_commit": scenario.get("requested_commit"),
        "resolved_commit": scenario.get("resolved_commit"),
        "license": scenario.get("license"),
        "asset_id": scenario.get("asset_id"),
        "asset_manifest_sha256": scenario.get("asset_manifest_sha256"),
        "asset_files": deepcopy(asset_files),
        "dataset": deepcopy(dataset),
        "task_id": scenario.get("task_id"),
        "run_id": scenario.get("run_id"),
        "run": deepcopy(run),
        "evaluation": deepcopy(evaluation),
        "new_sample_inference": deepcopy(inference),
        "artifact_bundle": deepcopy(bundle),
        "run_manifest_sha256": scenario.get("run_manifest_sha256"),
        "restart": deepcopy(restart),
        "assertions": assertions,
    }
    return (
        "passed" if passed else "failed",
        evidence,
        [] if passed else ["hf_real_scenario_assertion_failed"],
    )


def _evidence_unavailable_status(blockers: list[str]) -> str:
    blocked_markers = ("not_collected", "prerequisite", "not_supplied")
    return "blocked" if any(marker in item for item in blockers for marker in blocked_markers) else "failed"


def _read_external_evidence(
    path: Path | None,
    *,
    source_commit: str | None,
    expected_challenge: str | None,
    expected_command: list[str] | None,
    expected_tools: dict[str, str] | None = None,
    producer_status: str | None = None,
) -> tuple[LoadedExternalEvidence | None, list[str]]:
    if path is None:
        return None, ["controlled_external_evidence_not_collected"]
    if expected_challenge is None or expected_command is None:
        return None, ["external_evidence_not_challenge_bound"]
    selected_path = path.expanduser().resolve()
    try:
        value = read_json_object(selected_path)
        schema = load_json(EXTERNAL_SCHEMA_PATH)
        validate_json_schema(value, schema)
    except (OSError, ValueError, json.JSONDecodeError, SchemaValidationError):
        return None, ["external_evidence_schema_or_read_failure"]
    producer = value["producer"]
    blockers: list[str] = []
    if producer_status != "passed":
        blockers.append("controlled_producer_execution_not_passed")
    if not source_commit or value.get("source_commit") != source_commit:
        blockers.append("external_evidence_source_commit_mismatch")
    if producer.get("verifier_challenge") != expected_challenge:
        blockers.append("external_evidence_challenge_mismatch")
    if producer.get("command") != expected_command:
        blockers.append("external_evidence_command_mismatch")
    if expected_tools is None:
        blockers.append("external_evidence_trusted_tools_missing")
    else:
        declared_tools = producer.get("tools") or {}
        for name in ("python", "git", "node", "npm", "uv", "chrome"):
            expected_path = Path(expected_tools[name])
            try:
                resolved_path = expected_path.resolve(strict=True)
                expected_hash = sha256_file(resolved_path)
            except OSError:
                blockers.append(f"trusted_tool_unavailable:{name}")
                continue
            declared = declared_tools.get(name) or {}
            if (
                declared.get("path") != str(expected_path)
                or declared.get("resolved_path") != str(resolved_path)
                or declared.get("sha256") != expected_hash
            ):
                blockers.append(f"trusted_tool_provenance_mismatch:{name}")
    for key, relative in CONTROLLED_SOURCE_FILES.items():
        declared = producer["source_files"].get(key) or {}
        source_path = ROOT / relative
        if declared.get("path") != relative or not source_path.is_file():
            blockers.append(f"producer_source_path_mismatch:{key}")
        elif declared.get("sha256") != sha256_file(source_path):
            blockers.append(f"producer_source_hash_mismatch:{key}")

    root = selected_path.parent
    references: dict[str, dict[str, Any]] = {
        "runtime.journeys": value["runtime"]["journeys"],
        "runtime.hf_report": value["runtime"]["hf_report"],
        "browser.report": value["browser"]["report"],
        "process_restart.report": value["process_restart"]["report"],
        "process_restart.before_log": value["process_restart"]["before_log"],
        "process_restart.after_log": value["process_restart"]["after_log"],
        "cold_clone.report": value["cold_clone"]["report"],
        "cold_clone.command_log": value["cold_clone"]["command_log"],
        "cold_clone.minimal_journeys": value["cold_clone"]["minimal_journeys"],
    }
    for viewport in ("desktop", "mobile"):
        for artifact in ("screenshot", "network_log", "console_log", "trace"):
            references[f"browser.{viewport}.{artifact}"] = value["browser"][viewport][artifact]
    artifact_paths: dict[str, Path] = {}
    for key, reference in references.items():
        try:
            artifact_paths[key] = resolve_artifact(root, reference)
        except (OSError, ValueError):
            blockers.append(f"external_artifact_invalid:{key}")
    if blockers:
        return None, sorted(set(blockers))

    try:
        reports = {
            "journeys": read_json_object(artifact_paths["runtime.journeys"]),
            "hf": read_json_object(artifact_paths["runtime.hf_report"]),
            "browser": read_json_object(artifact_paths["browser.report"]),
            "process_restart": read_json_object(artifact_paths["process_restart.report"]),
            "cold_clone": read_json_object(artifact_paths["cold_clone.report"]),
            "minimal_journeys": read_json_object(artifact_paths["cold_clone.minimal_journeys"]),
        }
        validate_json_schema(reports["browser"], load_json(BROWSER_REPORT_SCHEMA_PATH))
        validate_json_schema(reports["process_restart"], load_json(PROCESS_REPORT_SCHEMA_PATH))
        validate_json_schema(reports["cold_clone"], load_json(COLD_CLONE_REPORT_SCHEMA_PATH))
    except (OSError, ValueError, json.JSONDecodeError, SchemaValidationError):
        return None, ["external_artifact_report_schema_invalid"]
    run_id = producer["run_id"]
    for report_id in ("browser", "process_restart", "cold_clone"):
        report = reports[report_id]
        if report.get("source_commit") != source_commit or report.get("producer_run_id") != run_id:
            return None, [f"external_artifact_provenance_mismatch:{report_id}"]
    if reports["journeys"].get("mode") != "official_hf_fixed_commit" or reports["journeys"].get("status") != "passed":
        return None, ["external_runtime_journeys_invalid"]
    return (
        LoadedExternalEvidence(
            manifest=value,
            path=selected_path,
            root=root,
            manifest_sha256=sha256_file(selected_path),
            artifact_paths=artifact_paths,
            reports=reports,
        ),
        [],
    )


def _journey_families(external: LoadedExternalEvidence) -> dict[str, dict[str, Any]]:
    families = external.reports["journeys"].get("journey_families")
    if not isinstance(families, dict) or set(families) != {"image", "tabular", "audio"}:
        raise ValueError("journey families are missing or drifted")
    return families


def probe_browser_evidence(
    external: LoadedExternalEvidence | None,
    load_blockers: list[str],
    *,
    width: int,
    height: int,
) -> tuple[str, dict[str, Any], list[str]]:
    if external is None:
        blockers = load_blockers or ["browser_evidence_missing"]
        return _evidence_unavailable_status(blockers), {}, blockers
    name = "desktop" if width == 1440 else "mobile"
    runs = external.reports["browser"]["runs"]
    matches = [item for item in runs if item.get("viewport") == {"width": width, "height": height}]
    if len(matches) != 1:
        return "failed", {"matching_run_count": len(matches)}, ["browser_viewport_evidence_invalid"]
    record = matches[0]
    screenshot_path = external.artifact_paths[f"browser.{name}.screenshot"]
    network_path = external.artifact_paths[f"browser.{name}.network_log"]
    console_path = external.artifact_paths[f"browser.{name}.console_log"]
    try:
        screenshot_size = png_dimensions(screenshot_path)
        network = read_ndjson(network_path)
        console = read_ndjson(console_path)
        journeys = _journey_families(external)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        return "failed", {"error": str(error)}, ["browser_raw_artifact_invalid"]
    request_failures = [item for item in network if item.get("kind") == "requestfailed"]
    http_errors = [item for item in network if item.get("kind") == "response" and int(item.get("status", 0)) >= 400]
    console_errors = [item for item in console if item.get("level") == "error" or item.get("kind") == "pageerror"]
    observed_paths = {
        (str(item.get("method")), str(item.get("path")), int(item.get("status", 0)))
        for item in network
        if item.get("kind") == "response"
    }
    family_network: dict[str, bool] = {}
    family_ids: dict[str, Any] = {}
    for family, journey in journeys.items():
        task = urllib.parse.quote(str(journey["task_id"]), safe="")
        run = urllib.parse.quote(str(journey["run_id"]), safe="")
        required_paths = {
            ("GET", f"/tasks/{task}", 200),
            ("GET", f"/runs/{run}/events", 200),
            ("GET", f"/tasks/{task}/runs/{run}/evaluation-report", 200),
            ("GET", f"/tasks/{task}/runs/{run}/sample-inferences", 200),
            ("GET", f"/tasks/{task}/runs/{run}/artifact-bundles", 200),
        }
        family_network[family] = required_paths.issubset(observed_paths)
        observed_family = record["families"][family]
        family_ids[family] = {
            key: observed_family.get(key)
            for key in ("task_id", "run_id", "evaluation_report_id", "inference_check_id", "artifact_bundle_id")
        }
        family_network[f"{family}_ids_match"] = all(
            observed_family.get(key) == journey.get(key)
            for key in ("task_id", "run_id", "evaluation_report_id", "inference_check_id", "artifact_bundle_id")
        )
        family_network[f"{family}_result_visible"] = (
            journey["artifact_bundle_id"] in observed_family["bundle_text"]
            and bool(observed_family["evaluation_text"].strip())
            and "待评测" not in observed_family["evaluation_text"]
        )
    producer_run_id = external.manifest["producer"]["run_id"]
    draft_prefix = "desktop" if width == 1440 else "mobile"
    expected_first = hashlib.sha256(f"controlled-first-{producer_run_id}-{draft_prefix}".encode()).hexdigest()
    expected_second = hashlib.sha256(f"controlled-second-{producer_run_id}-{draft_prefix}".encode()).hexdigest()
    measurements = record["measurements"]
    targets = measurements["primary_targets"]
    assertions = {
        "screenshot_dimensions_exact": screenshot_size == (width, height),
        "console_log_recomputed": record["console_error_count"] == len(console_errors),
        "request_failures_recomputed": record["request_failure_count"] == len(request_failures),
        "http_errors_recomputed": record["http_error_count"] == len(http_errors),
        "console_clean": not console_errors,
        "network_clean": not request_failures and not http_errors,
        "no_horizontal_overflow": measurements["horizontal_overflow_px"] == 0,
        "minimum_targets_44px": all(float(item["width"]) >= 44 and float(item["height"]) >= 44 for item in targets),
        "context_reachable": measurements["context_reachable"] is True,
        "results_reachable": measurements["results_reachable"] is True,
        "draft_hashes_challenge_bound": record["drafts"]["first_value_sha256"] == expected_first and record["drafts"]["second_value_sha256"] == expected_second,
        "drafts_isolated_and_reload_safe": all(record["drafts"][key] is True for key in ("first_restored", "first_survived_reload", "second_restored")),
        "three_family_network_coverage": all(family_network.values()),
    }
    status = "passed" if all(assertions.values()) else "failed"
    evidence = {
        "viewport": {"width": width, "height": height},
        "screenshot": {"path": _display_path(screenshot_path), "sha256": sha256_file(screenshot_path), "dimensions": list(screenshot_size)},
        "network_log": {"path": _display_path(network_path), "sha256": sha256_file(network_path), "record_count": len(network)},
        "console_log": {"path": _display_path(console_path), "sha256": sha256_file(console_path), "record_count": len(console)},
        "http_error_count": len(http_errors),
        "request_failure_count": len(request_failures),
        "console_error_count": len(console_errors),
        "journey_families": family_ids,
        "assertions": assertions,
    }
    return status, evidence, [] if status == "passed" else ["browser_independent_verification_failed"]


def probe_three_family_journeys(
    external: LoadedExternalEvidence | None,
    load_blockers: list[str],
) -> tuple[str, dict[str, Any], list[str]]:
    if external is None:
        blockers = load_blockers or ["three_family_evidence_missing"]
        return _evidence_unavailable_status(blockers), {}, blockers
    try:
        journeys = _journey_families(external)
        observed = external.reports["process_restart"]["after"]
    except (KeyError, TypeError, ValueError):
        return "failed", {}, ["three_family_reports_invalid"]
    selected: dict[str, Any] = {}
    assertions: dict[str, bool] = {}
    for family in ("image", "tabular", "audio"):
        journey = journeys[family]
        snapshot = observed[family]
        selected[family] = {
            key: snapshot.get(key)
            for key in ("task_id", "run_id", "evaluation_report_id", "inference_check_id", "artifact_bundle_id")
        }
        assertions[f"{family}_identities_match"] = all(
            snapshot.get(key) == journey.get(key)
            for key in selected[family]
        )
        assertions[f"{family}_chain_complete"] = (
            snapshot.get("training_status") == "completed"
            and snapshot.get("evaluation_conclusion") == "release_ready"
            and snapshot.get("inference_status") == "passed"
            and snapshot.get("bundle_status") == "completed"
            and snapshot.get("bundle_sha256") == snapshot.get("bundle_download_sha256")
        )
    status = "passed" if all(assertions.values()) else "failed"
    return status, {"journey_families": selected, "assertions": assertions}, [] if status == "passed" else ["three_family_lineage_invalid"]


def _http_bytes(url: str, *, timeout: float = 5.0) -> tuple[int, bytes]:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    # These calls independently re-check the controlled loopback service.  Do
    # not inherit macOS system proxy settings: a proxy response is not evidence
    # about the service bound to 127.0.0.1.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=timeout) as response:
        return int(response.status), response.read()


def _http_json(url: str) -> tuple[int, dict[str, Any]]:
    status, payload = _http_bytes(url)
    value = json.loads(payload.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("HTTP response is not a JSON object")
    return status, value


def _terminate_controlled_pid(pid: int, timeout: float = 10.0) -> bool:
    if not pid_is_alive(pid):
        return True
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return not pid_is_alive(pid)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not pid_is_alive(pid):
            return True
        time.sleep(0.05)
    return False


def _process_identity(
    pid: int,
    environment: dict[str, str],
) -> dict[str, str]:
    ps = Path("/bin/ps")
    if not ps.is_file():
        raise ValueError("trusted ps executable is unavailable")

    def read_field(field: str) -> str:
        completed = subprocess.run(
            [str(ps), "-p", str(pid), "-o", f"{field}="],
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=5,
            check=False,
        )
        value = completed.stdout.strip()
        if completed.returncode != 0 or not value:
            raise ValueError(f"process {field} is unavailable")
        return value

    started = read_field("lstart")
    command = read_field("command")
    return {
        "start_token": hashlib.sha256(started.encode("utf-8")).hexdigest(),
        "observed_command_sha256": hashlib.sha256(
            command.encode("utf-8")
        ).hexdigest(),
    }


def _cleanup_controlled_service_lease(
    lease_path: Path,
    *,
    expected_challenge: str | None,
    expected_source_commit: str | None,
    expected_run_id: str | None,
    expected_pid: int | None,
    expected_base_url: str | None,
    expected_runtime_dir: Path | None,
    trusted_tools: dict[str, str],
    environment: dict[str, str],
) -> tuple[bool, int | None]:
    if expected_challenge is None:
        return True, None
    try:
        if lease_path.is_symlink():
            raise ValueError("lease may not be a symlink")
        lease = read_json_object(lease_path.resolve(strict=True))
        if set(lease) != {
            "schema_version",
            "source_commit",
            "verifier_challenge",
            "producer_run_id",
            "pid",
            "base_url",
            "start_token",
            "observed_command_sha256",
            "expected_argv_sha256",
        }:
            raise ValueError("lease fields drifted")
        if (
            lease.get("schema_version") != "0.2"
            or lease.get("source_commit") != expected_source_commit
            or lease.get("verifier_challenge") != expected_challenge
        ):
            raise ValueError("lease provenance mismatch")
        run_id = lease.get("producer_run_id")
        if not isinstance(run_id, str) or not re.fullmatch(
            r"evidence-[0-9TZ-]+-[0-9a-f]{8}", run_id
        ):
            raise ValueError("lease producer run id is invalid")
        if expected_run_id is not None and run_id != expected_run_id:
            raise ValueError("lease producer run id does not match manifest")
        pid = lease.get("pid")
        base_url = lease.get("base_url")
        if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
            raise ValueError("lease PID is invalid")
        if not isinstance(base_url, str) or not re.fullmatch(
            r"http://127\.0\.0\.1:[0-9]{2,5}", base_url
        ):
            raise ValueError("lease URL is invalid")
        if expected_pid is not None and pid != expected_pid:
            raise ValueError("lease PID does not match manifest")
        if expected_base_url is not None and base_url != expected_base_url:
            raise ValueError("lease URL does not match manifest")
        if expected_runtime_dir is None or not expected_runtime_dir.is_dir():
            raise ValueError("controlled runtime identity is unavailable")
        port = urllib.parse.urlparse(base_url).port
        expected_command = [
            trusted_tools["python"],
            "-m",
            "model_harness.cli",
            "serve",
            "--runs-dir",
            str(expected_runtime_dir),
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ]
        expected_argv_sha256 = hashlib.sha256(
            json.dumps(expected_command, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        if lease.get("expected_argv_sha256") != expected_argv_sha256:
            raise ValueError("lease argv identity mismatch")
        for field in ("start_token", "observed_command_sha256"):
            if not SHA256_PATTERN.fullmatch(str(lease.get(field) or "")):
                raise ValueError(f"lease {field} is invalid")
    except (OSError, ValueError, json.JSONDecodeError):
        return False, None
    if not pid_is_alive(pid):
        return True, pid
    try:
        live_identity = _process_identity(pid, environment)
        if any(live_identity[key] != lease[key] for key in live_identity):
            return False, pid
        status, health = _http_json(f"{base_url}/health")
    except (OSError, ValueError, urllib.error.URLError, json.JSONDecodeError):
        # Do not signal a live but unrelated/reused PID when the leased service
        # can no longer prove ownership of its loopback endpoint.
        return False, pid
    if status != 200 or health.get("ok") is not True:
        return False, pid
    return _terminate_controlled_pid(pid), pid


def _live_family_snapshot(base_url: str, family: str, journey: dict[str, Any]) -> dict[str, Any]:
    task_id = str(journey["task_id"])
    run_id = str(journey["run_id"])
    task_path = urllib.parse.quote(task_id, safe="")
    run_path = urllib.parse.quote(run_id, safe="")
    _, task_payload = _http_json(f"{base_url}/tasks/{task_path}")
    _, result = _http_json(f"{base_url}/runs/{run_path}/result")
    _, evaluation_payload = _http_json(f"{base_url}/tasks/{task_path}/runs/{run_path}/evaluation-report")
    inference_id = urllib.parse.quote(str(journey["inference_check_id"]), safe="")
    _, inference_payload = _http_json(f"{base_url}/tasks/{task_path}/runs/{run_path}/sample-inferences/{inference_id}")
    bundle_id = urllib.parse.quote(str(journey["artifact_bundle_id"]), safe="")
    _, bundle_payload = _http_json(f"{base_url}/tasks/{task_path}/runs/{run_path}/artifact-bundles/{bundle_id}")
    _, bundle_bytes = _http_bytes(f"{base_url}/tasks/{task_path}/runs/{run_path}/artifact-bundles/{bundle_id}/download")
    _, events_payload = _http_json(f"{base_url}/runs/{run_path}/events")
    task = task_payload["task"]
    evaluation = evaluation_payload["evaluation_report"]
    inference = inference_payload["sample_inference"]
    bundle = bundle_payload["artifact_bundle"]
    events = events_payload["events"]
    if task.get("task_id") != task_id or task.get("current_run_id") != run_id or result.get("run_id") != run_id:
        raise ValueError(f"{family} task/run ownership mismatch")
    selected = {
        "task_id": task["task_id"],
        "run_id": result["run_id"],
        "evaluation_report_id": evaluation["report_id"],
        "inference_check_id": inference["check_id"],
        "artifact_bundle_id": bundle["bundle_id"],
        "training_status": result["status"],
        "evaluation_conclusion": evaluation["conclusion"],
        "inference_status": inference["status"],
        "bundle_status": bundle["status"],
        "bundle_sha256": bundle["archive"]["sha256"],
        "bundle_download_sha256": hashlib.sha256(bundle_bytes).hexdigest(),
        "event_count": len(events),
        "event_last_seq": int(events[-1]["seq"]),
    }
    if family == "image":
        _, verification = _http_json(f"{base_url}/tasks/{task_path}/model-assets/current/verify")
        if verification.get("ok") is not True:
            raise ValueError("image ModelAsset failed live verification")
        selected["model_asset_id"] = task.get("selected_model_asset_id")
    if family == "audio":
        build_id = urllib.parse.quote(str(journey["build_attempt_id"]), safe="")
        _, build_payload = _http_json(f"{base_url}/tasks/{task_path}/recipe-builds/{build_id}")
        selected["build_attempt_id"] = build_payload["recipe_build"]["attempt_id"]
        selected["recipe_version_id"] = journey.get("recipe_version_id")
    return selected


def probe_process_restart_evidence(
    external: LoadedExternalEvidence | None,
    load_blockers: list[str],
    identity_kinds: Iterable[str] = (),
) -> tuple[str, dict[str, Any], list[str]]:
    del identity_kinds
    if external is not None and not isinstance(external, LoadedExternalEvidence):
        return "failed", {}, ["controlled_evidence_object_required"]
    if external is None:
        blockers = load_blockers or ["process_restart_evidence_missing"]
        return _evidence_unavailable_status(blockers), {}, blockers
    section = external.reports["process_restart"]
    journeys = _journey_families(external)
    base_url = section["base_url"]
    assertions = {
        "manifest_base_url_matches": external.manifest["runtime"]["base_url"] == base_url,
        "manifest_pid_matches": external.manifest["runtime"]["after_pid"] == section["after_pid"],
        "different_process_ids": section["before_pid"] != section["after_pid"],
        "before_process_stopped": not pid_is_alive(section["before_pid"]),
        "after_process_alive": pid_is_alive(section["after_pid"]),
        "before_process_exited_cleanly": section["before_exit_code"] == 0,
        "old_port_was_closed": section["old_port_closed"] is True,
        "health_and_openapi_passed": section["health_status_after"] == 200 and section["openapi_status_after"] == 200,
        "before_after_snapshots_equal": section["before"] == section["after"],
    }
    live: dict[str, Any] = {}
    try:
        health_status, health = _http_json(f"{base_url}/health")
        openapi_status, openapi = _http_json(f"{base_url}/openapi.json")
        assertions["live_health_openapi"] = health_status == 200 and health.get("ok") is True and openapi_status == 200 and bool(openapi.get("paths"))
        for family in ("image", "tabular", "audio"):
            live[family] = _live_family_snapshot(base_url, family, journeys[family])
            assertions[f"{family}_live_equals_restart_snapshot"] = live[family] == section["after"][family]
            assertions[f"{family}_ids_match_journey"] = all(
                live[family].get(key) == journeys[family].get(key)
                for key in ("task_id", "run_id", "evaluation_report_id", "inference_check_id", "artifact_bundle_id")
            )
    except (OSError, KeyError, ValueError, urllib.error.URLError, json.JSONDecodeError) as error:
        assertions["live_service_query"] = False
        live["error"] = str(error)
    else:
        assertions["live_service_query"] = True
    status = "passed" if all(assertions.values()) else "failed"
    evidence = {"before_pid": section["before_pid"], "after_pid": section["after_pid"], "base_url": base_url, "live_families": live, "assertions": assertions}
    return status, evidence, [] if status == "passed" else ["process_restart_independent_verification_failed"]


def _command_option_value(argv: list[str], option: str) -> str | None:
    if argv.count(option) != 1:
        return None
    option_index = argv.index(option)
    if option_index + 1 >= len(argv):
        return None
    selected = str(argv[option_index + 1]).strip()
    return selected or None


def probe_cold_clone_evidence(
    external: LoadedExternalEvidence | None,
    load_blockers: list[str],
    *,
    source_commit: str | None,
) -> tuple[str, dict[str, Any], list[str]]:
    if external is None:
        blockers = load_blockers or ["cold_clone_evidence_missing"]
        return _evidence_unavailable_status(blockers), {}, blockers
    section = external.reports["cold_clone"]
    minimal = external.reports["minimal_journeys"]
    try:
        log_records = read_ndjson(external.artifact_paths["cold_clone.command_log"])
    except (OSError, ValueError, json.JSONDecodeError) as error:
        return "failed", {"error": str(error)}, ["cold_clone_command_log_invalid"]
    expected_ids = ["clone", "checkout", "uv_sync", "python_tests", "node_ci", "node_tests", "node_check", "browser_ci", "minimal_loop"]
    commands = section["commands"]
    tool_paths = {
        name: external.manifest["producer"]["tools"][name]["path"]
        for name in ("git", "npm", "uv")
    }
    logged = {item.get("id"): item for item in log_records}
    command_ids = [item.get("id") for item in commands]
    command_logs_match = all(
        command["id"] in logged
        and logged[command["id"]].get("argv") == command["argv"]
        and logged[command["id"]].get("exit_code") == command["exit_code"]
        for command in commands
    )
    minimal_checkpoint_id = _command_option_value(
        commands[8]["argv"],
        "--user-approval-checkpoint-id",
    )
    producer_checkpoint_id = _command_option_value(
        external.manifest["producer"]["command"],
        "--user-approval-checkpoint-id",
    )
    command_shapes = {
        "clone": commands[0]["argv"][:5] == [tool_paths["git"], "clone", "--no-local", "--no-hardlinks", "--no-checkout"] and commands[0]["argv"][5] == str(ROOT),
        "checkout": commands[1]["argv"][:3] == [tool_paths["git"], "-C", commands[1]["argv"][2]] and commands[1]["argv"][-3:] == ["checkout", "--detach", source_commit],
        "uv_sync": commands[2]["argv"][0:2] == [tool_paths["uv"], "sync"] and "--frozen" in commands[2]["argv"],
        "python_tests": commands[3]["argv"][-6:] == ["-m", "unittest", "discover", "-s", "tests", "-v"],
        "node_ci": commands[4]["argv"][0] == tool_paths["npm"] and "ci" in commands[4]["argv"] and "--ignore-scripts" in commands[4]["argv"],
        "node_tests": commands[5]["argv"][0] == tool_paths["npm"] and commands[5]["argv"][-1] == "test",
        "node_check": commands[6]["argv"][0] == tool_paths["npm"] and commands[6]["argv"][-2:] == ["run", "check"],
        "browser_ci": commands[7]["argv"][0] == tool_paths["npm"] and "acceptance/browser" in "/".join(commands[7]["argv"]) and "--ignore-scripts" in commands[7]["argv"],
        "minimal_loop": (
            commands[8]["argv"][0] == tool_paths["uv"]
            and commands[8]["argv"].count("--skip-hf") == 1
            and "prepare_v07_acceptance_runtime.py"
            in " ".join(commands[8]["argv"])
            and minimal_checkpoint_id is not None
            and minimal_checkpoint_id == producer_checkpoint_id
        ),
    }
    minimal_families = minimal.get("journey_families") or {}
    minimal_match = minimal.get("status") == "passed" and minimal.get("mode") == "local_image_skip_hf" and set(minimal_families) == {"image", "tabular", "audio"}
    if minimal_match:
        for family in ("image", "tabular", "audio"):
            expected = section["minimal_family_ids"][family]
            minimal_match = minimal_match and all(minimal_families[family].get(key) == value for key, value in expected.items())
    assertions = {
        "resolved_exact_source_commit": bool(source_commit) and section["resolved_commit"] == source_commit,
        "worktree_clean_before_run": section["worktree_clean_before_run"] is True,
        "no_preexisting_runs": section["preexisting_runs"] is False,
        "no_preexisting_model_cache": section["preexisting_model_cache"] is False,
        "command_ids_exact": command_ids == expected_ids,
        "all_commands_exited_zero": all(item["exit_code"] == 0 for item in commands),
        "command_logs_recomputed": command_logs_match,
        "command_shapes_trusted": all(command_shapes.values()),
        "no_recursive_acceptance": all("verify_v07_beta.py" not in " ".join(item["argv"]) for item in commands),
        "minimal_three_family_loop_recomputed": minimal_match,
    }
    status = "passed" if all(assertions.values()) else "failed"
    evidence = {"resolved_commit": section["resolved_commit"], "command_ids": command_ids, "command_log_sha256": sha256_file(external.artifact_paths["cold_clone.command_log"]), "minimal_journeys_sha256": sha256_file(external.artifact_paths["cold_clone.minimal_journeys"]), "assertions": assertions}
    return status, evidence, [] if status == "passed" else ["cold_clone_independent_verification_failed"]


def _gh_api(path: str) -> tuple[str, Any, str]:
    tools = _trusted_tools(sys.executable)
    gh = Path(tools["gh"])
    if not gh.is_file() or not os.access(gh, os.X_OK):
        return "blocked", None, "github_cli_unavailable"
    try:
        completed = subprocess.run(
            [str(gh), "api", "--hostname", "github.com", path],
            cwd=ROOT,
            env=_base_trusted_environment(tools),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "blocked", None, "github_api_unavailable"
    if completed.returncode != 0:
        message = (completed.stderr or completed.stdout or "").lower()
        if "http 404" in message or "not found" in message:
            return "failed", None, "github_api_object_not_found"
        return "blocked", None, "github_api_auth_or_network_unavailable"
    try:
        return "passed", json.loads(completed.stdout), ""
    except json.JSONDecodeError:
        return "failed", None, "github_api_invalid_json"


def _gh_check_runs(
    repository: str,
    source_commit: str,
) -> tuple[str, dict[str, Any] | None, str]:
    """Read every check run page and fail closed on count or identity drift."""

    page = 1
    expected_total: int | None = None
    check_runs: list[dict[str, Any]] = []
    seen_ids: set[int] = set()
    while True:
        endpoint = (
            f"repos/{repository}/commits/{source_commit}/check-runs"
            f"?filter=latest&per_page=100&page={page}"
        )
        status, value, reason = _gh_api(endpoint)
        if status != "passed":
            return status, None, reason
        if not isinstance(value, dict):
            return "failed", None, "github_check_runs_invalid_shape"
        total_count = value.get("total_count")
        page_runs = value.get("check_runs")
        if (
            not isinstance(total_count, int)
            or isinstance(total_count, bool)
            or total_count < 0
            or not isinstance(page_runs, list)
            or len(page_runs) > 100
            or not all(isinstance(item, dict) for item in page_runs)
        ):
            return "failed", None, "github_check_runs_invalid_shape"
        if expected_total is None:
            expected_total = total_count
        elif total_count != expected_total:
            return "failed", None, "github_check_runs_total_changed"

        for item in page_runs:
            check_id = item.get("id")
            if (
                not isinstance(check_id, int)
                or isinstance(check_id, bool)
                or check_id <= 0
                or check_id in seen_ids
            ):
                return "failed", None, "github_check_run_identity_invalid"
            seen_ids.add(check_id)
            check_runs.append(item)

        if len(check_runs) == expected_total:
            return (
                "passed",
                {"total_count": expected_total, "check_runs": check_runs},
                "",
            )
        if len(check_runs) > expected_total or not page_runs:
            return "failed", None, "github_check_runs_incomplete"
        maximum_pages = max(1, (expected_total + 99) // 100)
        if page >= maximum_pages:
            return "failed", None, "github_check_runs_incomplete"
        page += 1


def probe_release_evidence(
    *,
    source_commit: str | None,
    repository: str,
    tag: str,
    required_check_names: list[str],
) -> tuple[str, dict[str, Any], list[str]]:
    if not source_commit or not COMMIT_PATTERN.fullmatch(source_commit):
        return "blocked", {}, ["release_source_commit_missing"]
    if (
        not required_check_names
        or any(not isinstance(name, str) or not name.strip() for name in required_check_names)
        or len(required_check_names) != len(set(required_check_names))
    ):
        return "failed", {}, ["release_required_check_contract_invalid"]
    calls = {
        "commit": f"repos/{repository}/commits/{source_commit}",
        "pulls": f"repos/{repository}/commits/{source_commit}/pulls",
        "tag": f"repos/{repository}/git/ref/tags/{tag}",
        "release": f"repos/{repository}/releases/tags/{tag}",
    }
    responses: dict[str, Any] = {}
    blockers: list[str] = []
    failures: list[str] = []
    for key, path in calls.items():
        status, value, reason = _gh_api(path)
        if status == "blocked":
            blockers.append(f"{key}:{reason}")
        elif status == "failed":
            failures.append(f"{key}:{reason}")
        else:
            responses[key] = value
    check_status, check_response, check_reason = _gh_check_runs(
        repository,
        source_commit,
    )
    if check_status == "blocked":
        blockers.append(f"checks:{check_reason}")
    elif check_status == "failed":
        failures.append(f"checks:{check_reason}")
    else:
        responses["checks"] = check_response
    if failures:
        return "failed", {"api_objects": sorted(responses)}, failures
    if blockers:
        return "blocked", {"api_objects": sorted(responses)}, blockers
    tag_object = responses["tag"].get("object") or {}
    tag_commit = tag_object.get("sha")
    annotated_tag: Any = None
    if tag_object.get("type") == "tag":
        status, annotated_tag, reason = _gh_api(f"repos/{repository}/git/tags/{tag_commit}")
        if status != "passed":
            return status, {"api_objects": sorted(responses)}, [f"annotated_tag:{reason}"]
        tag_commit = (annotated_tag.get("object") or {}).get("sha")
    pulls = responses["pulls"] if isinstance(responses["pulls"], list) else []
    merged = [
        item
        for item in pulls
        if item.get("merged_at")
        and item.get("html_url")
        and (
            item.get("merge_commit_sha") == source_commit
            or (item.get("head") or {}).get("sha") == source_commit
        )
    ]
    checks = (responses["checks"] or {}).get("check_runs") or []
    check_total = (responses["checks"] or {}).get("total_count")
    required_checks = {
        name: [item for item in checks if item.get("name") == name]
        for name in required_check_names
    }
    required_checks_unique = all(
        len(items) == 1 for items in required_checks.values()
    )
    required_checks_successful = required_checks_unique and all(
        items[0].get("status") == "completed"
        and items[0].get("conclusion") == "success"
        and items[0].get("head_sha") == source_commit
        for items in required_checks.values()
    )
    release = responses["release"] or {}
    assertions = {
        "commit_exact": responses["commit"].get("sha") == source_commit,
        "associated_pr_merged_and_bound": bool(merged),
        "check_run_collection_complete": isinstance(check_total, int)
        and not isinstance(check_total, bool)
        and check_total == len(checks),
        "required_checks_unique": required_checks_unique,
        "required_checks_successful_on_source": required_checks_successful,
        "tag_resolves_exact_commit": tag_commit == source_commit,
        "release_exact_tag": release.get("tag_name") == tag,
        "release_published": release.get("draft") is False and release.get("prerelease") in (False, True) and bool(release.get("html_url")),
    }
    status = "passed" if all(assertions.values()) else "failed"
    evidence = {
        "repository": repository,
        "source_commit": source_commit,
        "tag": tag,
        "required_check_names": list(required_check_names),
        "commit_url": responses["commit"].get("html_url"),
        "pull_request_urls": [item.get("html_url") for item in merged],
        "check_run_urls": [
            items[0].get("html_url")
            for items in required_checks.values()
            if len(items) == 1
        ],
        "release_url": release.get("html_url"),
        "assertions": assertions,
    }
    return status, evidence, [] if status == "passed" else ["github_release_api_assertion_failed"]


def _command_gate(
    levels: list[dict[str, Any]],
    gate_id: str,
    commands: dict[str, dict[str, Any]],
    command_ids: list[str],
    passed_summary: str,
    failed_summary: str,
) -> None:
    status = combine_command_status(commands, command_ids)
    blockers = [] if status == "passed" else [f"command_not_passed:{item}" for item in command_ids if commands[item]["status"] != "passed"]
    set_gate(
        levels,
        gate_id,
        status,
        passed_summary if status == "passed" else failed_summary,
        evidence={"command_ids": command_ids},
        blockers=blockers,
    )


def execute_acceptance(
    output_path: Path,
    *,
    user_approval_checkpoint_id: str,
    controlled_evidence_dir: Path | None = None,
) -> dict[str, Any]:
    selected_checkpoint_id = str(user_approval_checkpoint_id).strip()
    if not selected_checkpoint_id:
        raise ValueError("user approval checkpoint id must not be empty")
    config = load_json(GATES_PATH)
    levels = instantiate_levels(config)
    started_at = utc_now()
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    acceptance_id = f"acceptance-{timestamp}-{uuid4().hex[:8]}"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    logs_dir = output_path.parent / "logs"
    python = ROOT / ".venv" / "bin" / "python"
    python_executable = str(python if python.is_file() else Path(sys.executable))
    trusted_tools = _trusted_tools(python_executable)
    python_executable = trusted_tools["python"]
    source = source_snapshot(trusted_tools)
    source_commit_clean = bool(
        source.get("worktree_clean")
        and COMMIT_PATTERN.fullmatch(str(source.get("git_commit") or ""))
    )
    selected_controlled_evidence_dir = (
        controlled_evidence_dir.expanduser().resolve()
        if controlled_evidence_dir is not None
        else (output_path.parent / "controlled-external-evidence").resolve()
    )
    selected_external_path = selected_controlled_evidence_dir / "external-evidence.json"
    external_evidence: LoadedExternalEvidence | None = None
    external_evidence_blockers = ["controlled_external_evidence_not_collected"]
    evidence_challenge: str | None = None
    evidence_command: list[str] | None = None
    before_runs = _runs_metadata_fingerprint()
    commands: dict[str, dict[str, Any]] = {}

    with tempfile.TemporaryDirectory(prefix="model-harness-v07-acceptance-") as temp_dir:
        runtime_root = Path(temp_dir).resolve()
        environment = _redacted_environment(runtime_root, trusted_tools)

        command_specs = [
            (
                "python_full_suite",
                [python_executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
                ROOT,
            ),
            (
                "node_tests",
                [trusted_tools["npm"], "test"],
                ROOT / "integrations" / "deepseek-harness",
            ),
            (
                "node_check",
                [trusted_tools["npm"], "run", "check"],
                ROOT / "integrations" / "deepseek-harness",
            ),
            (
                "l1_backend",
                [
                    python_executable,
                    "-m",
                    "unittest",
                    "tests.test_task_specs",
                    "tests.test_agent_bridge",
                    "-v",
                ],
                ROOT,
            ),
            (
                "l2_staged_assets",
                [
                    python_executable,
                    "-m",
                    "unittest",
                    "tests.test_staged_assets",
                    "tests.test_staged_asset_api",
                    "-v",
                ],
                ROOT,
            ),
            (
                "l2_recipe_factory",
                [
                    python_executable,
                    "-m",
                    "unittest",
                    "tests.test_recipe_factory",
                    "-v",
                ],
                ROOT,
            ),
            (
                "scenario_image",
                [
                    python_executable,
                    "-m",
                    "unittest",
                    "tests.test_workspace_loop.WorkspaceLoopTests.test_user_dataset_contract_run_and_artifacts_form_a_real_loop",
                    "-v",
                ],
                ROOT,
            ),
            (
                "scenario_tabular",
                [
                    python_executable,
                    "-m",
                    "unittest",
                    "tests.test_tabular_loop.TabularLoopTests.test_capability_task_csv_contract_run_and_artifacts_form_a_real_loop",
                    "-v",
                ],
                ROOT,
            ),
            (
                "scenario_audio",
                [
                    python_executable,
                    "-m",
                    "unittest",
                    "tests.test_recipe_factory_workspace.RecipeFactoryWorkspaceTests.test_audio_gap_build_register_resume_and_real_run",
                    "-v",
                ],
                ROOT,
            ),
            (
                "l3_primitives",
                [python_executable, "-m", "unittest", "tests.test_model_assets", "-v"],
                ROOT,
            ),
            (
                "l3_hf_contract",
                [
                    python_executable,
                    "-m",
                    "unittest",
                    "tests.test_huggingface_catalog",
                    "tests.test_huggingface_assets",
                    "tests.test_hf_workspace",
                    "tests.test_onnx_image_features",
                    "-v",
                ],
                ROOT,
            ),
            (
                "l4_evidence",
                [
                    python_executable,
                    "-m",
                    "unittest",
                    "tests.test_evidence",
                    "tests.test_run_evidence_lifecycle",
                    "-v",
                ],
                ROOT,
            ),
            (
                "l4_sample_inference",
                [python_executable, "-m", "unittest", "tests.test_sample_inference", "-v"],
                ROOT,
            ),
            (
                "l4_task_api",
                [python_executable, "-m", "unittest", "tests.test_l4_task_api", "-v"],
                ROOT,
            ),
            (
                "l4_optimization_provenance",
                [python_executable, "-m", "unittest", "tests.test_optimization_provenance", "-v"],
                ROOT,
            ),
        ]
        for command_id, command, cwd in command_specs:
            commands[command_id] = run_command(
                command_id,
                command,
                cwd=cwd,
                environment=environment,
                logs_dir=logs_dir,
            )

        hf_scenario_contract = config["live_scenarios"][
            "official_huggingface_fixed_commit"
        ]
        hf_report_root = runtime_root / "hf-real"
        commands["l3_hf_real_scenario"] = run_command(
            "l3_hf_real_scenario",
            [
                python_executable,
                str(ROOT / str(hf_scenario_contract["runner_script"])),
                "--repo-id",
                str(hf_scenario_contract["repo_id"]),
                "--commit",
                str(hf_scenario_contract["commit"]),
                "--output-root",
                str(hf_report_root),
            ],
            cwd=ROOT,
            environment=environment,
            logs_dir=logs_dir,
            timeout_seconds=600.0,
        )
        hf_real_result = probe_huggingface_real_report(
            hf_report_root,
            commands["l3_hf_real_scenario"]["status"],
            hf_scenario_contract,
        )
        if hf_real_result[0] == "blocked":
            commands["l3_hf_real_scenario"]["status"] = "blocked"

        evidence_challenge = uuid4().hex
        evidence_command = [
            python_executable,
            str(CONTROLLED_PRODUCER_PATH),
            "--output-dir",
            str(selected_controlled_evidence_dir),
            "--source-commit",
            str(source.get("git_commit") or ""),
            "--verifier-challenge",
            evidence_challenge,
            "--hf-report-root",
            str(hf_report_root),
            "--git",
            trusted_tools["git"],
            "--node",
            trusted_tools["node"],
            "--npm",
            trusted_tools["npm"],
            "--uv",
            trusted_tools["uv"],
            "--chrome",
            trusted_tools["chrome"],
            "--user-approval-checkpoint-id",
            selected_checkpoint_id,
        ]
        if selected_controlled_evidence_dir.exists():
            commands["controlled_external_evidence"] = command_not_run(
                "controlled_external_evidence",
                evidence_command,
                cwd=ROOT,
                logs_dir=logs_dir,
                status="failed",
                reason=(
                    "Refused pre-existing external evidence directory; this run must "
                    "create fresh challenge-bound evidence."
                ),
            )
            external_evidence_blockers = ["preexisting_external_evidence_refused"]
        elif not source_commit_clean:
            commands["controlled_external_evidence"] = command_not_run(
                "controlled_external_evidence",
                evidence_command,
                cwd=ROOT,
                logs_dir=logs_dir,
                status="blocked",
                reason="Controlled evidence requires a clean immutable source commit.",
            )
            external_evidence_blockers = ["controlled_producer_source_prerequisite_missing"]
        elif hf_real_result[0] != "passed":
            commands["controlled_external_evidence"] = command_not_run(
                "controlled_external_evidence",
                evidence_command,
                cwd=ROOT,
                logs_dir=logs_dir,
                status="blocked",
                reason="Controlled evidence requires the fixed-commit HF runtime from this acceptance run.",
            )
            external_evidence_blockers = ["controlled_producer_hf_prerequisite_missing"]
        else:
            commands["controlled_external_evidence"] = run_command(
                "controlled_external_evidence",
                evidence_command,
                cwd=ROOT,
                environment=environment,
                logs_dir=logs_dir,
                timeout_seconds=1800.0,
            )
            external_evidence, external_evidence_blockers = _read_external_evidence(
                selected_external_path,
                source_commit=source.get("git_commit"),
                expected_challenge=evidence_challenge,
                expected_command=evidence_command,
                expected_tools=trusted_tools,
                producer_status=commands["controlled_external_evidence"]["status"],
            )

        after_runs = _runs_metadata_fingerprint()
        isolation_passed = before_runs == after_runs
        set_gate(
            levels,
            "L0-isolated-workspace",
            "passed" if isolation_passed else "failed",
            (
                "All acceptance commands used temporary runtime roots and project training runs were unchanged."
                if isolation_passed
                else "Acceptance execution changed project training runs and is not isolated."
            ),
            evidence={
                "temporary_runtime_created": runtime_root.is_dir(),
                "project_runs_metadata_unchanged": isolation_passed,
                "project_runs_reused": False,
            },
            blockers=[] if isolation_passed else ["project_runs_changed"],
        )

        set_gate(
            levels,
            "L0-source-commit-clean",
            "passed" if source_commit_clean else "failed",
            (
                "Acceptance source is a clean, immutable Git commit."
                if source_commit_clean
                else "Acceptance source is dirty or lacks an immutable 40-character commit."
            ),
            evidence={
                "git_commit": source.get("git_commit"),
                "git_branch": source.get("git_branch"),
                "worktree_clean": source.get("worktree_clean"),
            },
            blockers=[] if source_commit_clean else ["acceptance_source_not_clean_commit"],
        )

        contract_status, contract_evidence, contract_blockers = probe_contract(config)
        set_gate(
            levels,
            "L0-contract-truth",
            contract_status,
            "Contracts and status vocabularies are structurally consistent." if contract_status == "passed" else "A requirements, Loop or acceptance contract assertion failed.",
            evidence=contract_evidence,
            blockers=contract_blockers,
        )

        expected_version = str(config["expected_product_version"])
        normalized = source["versions"]["normalized"]
        version_passed = bool(normalized) and all(
            value == expected_version for value in normalized.values()
        )
        set_gate(
            levels,
            "L0-version-sync",
            "passed" if version_passed else "failed",
            "All product surfaces report the same v0.7 Beta version." if version_passed else "Product version sources do not all match the required v0.7 Beta version.",
            evidence={"expected": expected_version, "observed": normalized},
            blockers=[] if version_passed else ["version_sources_mismatch"],
        )

        service_status, service_evidence, service_blockers = probe_service(runtime_root)
        set_gate(
            levels,
            "L0-health-openapi",
            service_status,
            "Fresh health and OpenAPI probes passed." if service_status == "passed" else "Fresh health or OpenAPI probe failed.",
            evidence=service_evidence,
            blockers=service_blockers,
        )

        full_suite_status = combine_command_status(
            commands, ["python_full_suite", "node_tests", "node_check"]
        )
        set_gate(
            levels,
            "L0-full-suite",
            full_suite_status,
            "Complete Python and Node suites passed." if full_suite_status == "passed" else "The complete Python or Node verification did not pass.",
            evidence={"command_ids": ["python_full_suite", "node_tests", "node_check"]},
            blockers=[] if full_suite_status == "passed" else ["full_suite_not_green"],
        )

        registry_status, registry_evidence, registry_blockers = probe_registry()
        set_gate(
            levels,
            "L0-registry-claim-match",
            registry_status,
            "Built-in registries match the declared static baseline." if registry_status == "passed" else "Built-in registry contents contradict the declared baseline.",
            evidence=registry_evidence,
            blockers=registry_blockers,
        )

        for gate_id, passed_summary in (
            ("L1-ambiguity-guard", "Ambiguous task guards passed backend verification."),
            ("L1-same-id-revision", "TaskSpec revision and identity recovery passed backend verification."),
            ("L1-control-projection-consistency", "Control projections passed list, detail and restart verification."),
            ("L1-dual-cancel", "Agent and Run cancellation ownership tests passed."),
            ("L1-rejected-write-no-lineage", "Rejected L1 writes preserved task and Run lineage."),
        ):
            _command_gate(
                levels,
                gate_id,
                commands,
                ["l1_backend"],
                passed_summary,
                "Required L1 backend verification failed.",
            )
        desktop_browser = probe_browser_evidence(
            external_evidence,
            external_evidence_blockers,
            width=1440,
            height=900,
        )
        mobile_browser = probe_browser_evidence(
            external_evidence,
            external_evidence_blockers,
            width=390,
            height=844,
        )
        browser_statuses = [desktop_browser[0], mobile_browser[0]]
        if "failed" in browser_statuses:
            draft_browser_status = "failed"
        elif "blocked" in browser_statuses:
            draft_browser_status = "blocked"
        else:
            draft_browser_status = "passed"
        draft_browser_blockers = [
            blocker
            for result in (desktop_browser, mobile_browser)
            for blocker in result[2]
        ]
        set_gate(
            levels,
            "L1-task-draft-browser",
            draft_browser_status,
            (
                "Task-local drafts and same-task reload passed at both required viewports."
                if draft_browser_status == "passed"
                else "Task-local draft isolation still lacks valid two-viewport browser evidence."
            ),
            evidence={
                "desktop": desktop_browser[1],
                "mobile": mobile_browser[1],
            },
            blockers=draft_browser_blockers,
        )

        for gate_id, command_id, passed_summary in (
            ("L2-staged-no-run", "l2_staged_assets", "Staged audio assets remained separate from DatasetVersion and Run lineage."),
            ("L2-malicious-quarantine", "l2_staged_assets", "Malicious staged archives failed closed with persistent evidence."),
            ("L2-build-events-restart", "l2_recipe_factory", "BuildAttempt lifecycle and restart recovery tests passed."),
            ("L2-declarative-only", "l2_recipe_factory", "RecipeSpec allowlists and blocked executable build tests passed."),
            ("L2-approval-digest-atomicity", "l2_recipe_factory", "Registration approval, digest, revision and recovery tests passed."),
            ("L2-audio-train-deep-verify-restart", "scenario_audio", "The real PCM audio backend scenario trained, deep-verified and reopened the same task."),
        ):
            _command_gate(
                levels,
                gate_id,
                commands,
                [command_id],
                passed_summary,
                f"Required L2 verification failed in {command_id}.",
            )

        set_gate(
            levels,
            "L3-official-hf-fixed-commit",
            hf_real_result[0],
            (
                "The pinned Hugging Face asset was consumed by real training, evaluation, sample inference, bundle delivery and restart."
                if hf_real_result[0] == "passed"
                else "The pinned Hugging Face real-training scenario did not produce a complete verified lineage."
            ),
            evidence={
                "command_ids": ["l3_hf_real_scenario"],
                "scenario": hf_real_result[1],
            },
            blockers=hf_real_result[2],
        )

        for gate_id, command_ids, passed_summary in (
            (
                "L3-hf-discovery-card-compat",
                ["l3_hf_contract"],
                "Hugging Face discovery, card, compatibility and product API tests passed.",
            ),
            (
                "L3-immutable-commit-reject-no-cache",
                ["l3_hf_contract", "l3_primitives"],
                "Approval, immutable commit and rejection-without-cache tests passed.",
            ),
            (
                "L3-token-license-hashes-tamper",
                ["l3_hf_contract", "l3_primitives", "l3_hf_real_scenario"],
                "Credential redaction, license, hashes and tamper quarantine passed with live HF evidence.",
            ),
            (
                "L3-task-contract-lineage",
                ["l3_hf_contract", "l3_hf_real_scenario"],
                "Task-scoped ModelAsset binding and frozen contract lineage tests passed.",
            ),
            (
                "L3-real-run-time-resource-events",
                ["scenario_image", "scenario_tabular", "scenario_audio", "l3_hf_real_scenario"],
                "Three real training backends emitted measured run evidence.",
            ),
            (
                "L3-interrupted-download-recovery",
                ["l3_primitives"],
                "Interrupted ModelAsset staging recovery tests passed.",
            ),
        ):
            _command_gate(
                levels,
                gate_id,
                commands,
                command_ids,
                passed_summary,
                f"Required L3 verification failed or was blocked for {gate_id}.",
            )

        for gate_id, command_ids, passed_summary in (
            (
                "L4-conclusion-dimensions",
                ["l4_evidence", "l4_task_api"],
                "Completion, integrity, quality and evidence sufficiency conclusions stayed separate.",
            ),
            (
                "L4-three-family-evaluation",
                ["scenario_image", "scenario_tabular", "scenario_audio", "l4_evidence", "l4_task_api"],
                "Three real training families and EvaluationReport lifecycle tests passed.",
            ),
            (
                "L4-candidates-failures-history",
                ["l4_evidence", "l4_optimization_provenance"],
                "Candidate provenance, failures and parent-child history tests passed.",
            ),
            (
                "L4-raw-sample-inference-reentry",
                ["l4_sample_inference", "l4_task_api", "l3_hf_real_scenario"],
                "Real raw image, row and WAV inference checks passed and reopened after restart.",
            ),
            (
                "L4-tamper-block",
                ["l4_evidence", "l4_sample_inference", "l4_task_api"],
                "Tampered model, contract and bundle sources produced persistent blocked evidence.",
            ),
            (
                "L4-bundle-hash-privacy-reentry",
                ["l4_evidence", "l4_task_api", "l3_hf_real_scenario"],
                "Atomic bundle hashes, privacy exclusions and restart re-entry tests passed.",
            ),
        ):
            _command_gate(
                levels,
                gate_id,
                commands,
                command_ids,
                passed_summary,
                f"Required L4 verification failed or was blocked for {gate_id}.",
            )

        scenario_ids = ["scenario_image", "scenario_tabular", "scenario_audio"]
        scenario_status = combine_command_status(commands, scenario_ids)
        family_journeys = probe_three_family_journeys(
            external_evidence,
            external_evidence_blockers,
        )
        l4_required_statuses = [
            gate["status"]
            for gate in _gate_index(levels).values()
            if str(gate["gate_id"]).startswith("L4-") and gate["required"]
        ]
        family_statuses = [scenario_status, family_journeys[0], *l4_required_statuses]
        if "failed" in family_statuses:
            three_family_status = "failed"
        elif "blocked" in family_statuses:
            three_family_status = "blocked"
        else:
            three_family_status = "passed"
        set_gate(
            levels,
            "L5-three-family-real",
            three_family_status,
            (
                "Image, tabular and audio journeys each reached training, evaluation, raw inference and bundle delivery."
                if three_family_status == "passed"
                else "The three complete product journeys do not yet have one consistent evidence chain."
            ),
            evidence={
                "command_ids": scenario_ids,
                "backend_scenario_status": scenario_status,
                **family_journeys[1],
            },
            blockers=(
                []
                if three_family_status == "passed"
                else family_journeys[2] or ["three_family_product_journeys_incomplete"]
            ),
        )

        restart_result = probe_process_restart_evidence(
            external_evidence,
            external_evidence_blockers,
            config["external_evidence_contract"]["restart_identity_kinds"],
        )
        negative_paths = {
            "rejection": combine_command_status(commands, ["l1_backend", "l2_staged_assets"]),
            "failure": combine_command_status(commands, ["python_full_suite"]),
            "cancellation": combine_command_status(commands, ["l1_backend", "l2_recipe_factory"]),
            "disconnect": combine_command_status(commands, ["l1_backend"]),
            "tamper": combine_command_status(commands, ["l3_primitives", "l4_evidence", "l4_sample_inference"]),
            "restart": restart_result[0],
        }
        negative_statuses = list(negative_paths.values())
        if "failed" in negative_statuses:
            all_negative_status = "failed"
        elif "blocked" in negative_statuses:
            all_negative_status = "blocked"
        else:
            all_negative_status = "passed"
        set_gate(
            levels,
            "L5-all-negative",
            all_negative_status,
            (
                "Integrated rejection, failure, cancellation, disconnect, tamper and restart paths persisted auditable evidence."
                if all_negative_status == "passed"
                else "Integrated negative-path evidence is missing, blocked or failed."
            ),
            evidence={
                "negative_paths": negative_paths,
                "source": "repository_test_commands_plus_live_restart",
            },
            blockers=(
                []
                if all_negative_status == "passed"
                else restart_result[2] or ["integrated_negative_acceptance_incomplete"]
            ),
        )

        for gate_id, result, passed_summary in (
            (
                "L5-desktop-browser",
                desktop_browser,
                "The complete 1440x900 browser journey passed with clean console and network evidence.",
            ),
            (
                "L5-mobile-browser",
                mobile_browser,
                "The complete 390x844 browser journey passed reachability, overflow and 44px checks.",
            ),
            (
                "L5-process-restart",
                restart_result,
                "A real process PID change preserved every required object identity and OpenAPI availability.",
            ),
        ):
            set_gate(
                levels,
                gate_id,
                result[0],
                passed_summary if result[0] == "passed" else f"Required evidence did not pass for {gate_id}.",
                evidence=result[1],
                blockers=result[2],
            )

        cold_clone_result = probe_cold_clone_evidence(
            external_evidence,
            external_evidence_blockers,
            source_commit=source.get("git_commit"),
        )
        set_gate(
            levels,
            "L5-cold-clone",
            cold_clone_result[0],
            (
                "A fresh empty checkout of the exact source commit installed and reproduced the verifier and minimal loop."
                if cold_clone_result[0] == "passed"
                else "Cold-clone evidence is missing, stale or failed."
            ),
            evidence=cold_clone_result[1],
            blockers=cold_clone_result[2],
        )

        release_result = probe_release_evidence(
            source_commit=source.get("git_commit"),
            repository=str(config["release_contract"]["repository"]),
            tag=str(config["release_contract"]["tag"]),
            required_check_names=list(
                config["release_contract"]["required_check_names"]
            ),
        )
        set_gate(
            levels,
            "L5-release-chain",
            release_result[0],
            (
                "Commit, PR, CI, merge, tag and GitHub Release were independently evidenced."
                if release_result[0] == "passed"
                else "GitHub release-chain evidence is separate and not yet verified."
            ),
            evidence=release_result[1],
            blockers=release_result[2],
        )

        runtime_candidates = sorted(hf_report_root.glob("*/runtime"))
        controlled_runtime_dir = (
            runtime_candidates[0].resolve()
            if len(runtime_candidates) == 1
            else None
        )
        process_stopped, controlled_pid = _cleanup_controlled_service_lease(
            selected_controlled_evidence_dir / "service-lease.json",
            expected_challenge=evidence_challenge,
            expected_source_commit=source.get("git_commit"),
            expected_run_id=(
                external_evidence.manifest["producer"]["run_id"]
                if external_evidence is not None
                else None
            ),
            expected_pid=(
                int(external_evidence.manifest["runtime"]["after_pid"])
                if external_evidence is not None
                else None
            ),
            expected_base_url=(
                str(external_evidence.manifest["runtime"]["base_url"])
                if external_evidence is not None
                else None
            ),
            expected_runtime_dir=controlled_runtime_dir,
            trusted_tools=trusted_tools,
            environment=environment,
        )
        if not process_stopped:
            process_gate = _gate_index(levels)["L5-process-restart"]
            set_gate(
                levels,
                "L5-process-restart",
                "failed",
                "The controlled restart service could not be safely terminated after verification.",
                evidence={
                    **process_gate["evidence"],
                    "controlled_process_stopped": False,
                    "controlled_pid": controlled_pid,
                },
                blockers=["controlled_restart_process_cleanup_unverified"],
            )

        required_without_zero = [
            gate
            for level in levels
            for gate in level["gates"]
            if gate["required"] and gate["gate_id"] != "L5-zero-p0"
        ]
        upstream_statuses = [str(gate["status"]) for gate in required_without_zero]
        if "failed" in upstream_statuses:
            zero_p0_status = "failed"
        elif "blocked" in upstream_statuses:
            zero_p0_status = "blocked"
        else:
            zero_p0_status = "passed"
        set_gate(
            levels,
            "L5-zero-p0",
            zero_p0_status,
            (
                "Every required local Beta gate passed; no declared P0 remains failed or blocked."
                if zero_p0_status == "passed"
                else "At least one required local Beta gate remains failed or blocked."
            ),
            evidence={
                "required_gate_count_excluding_self": len(required_without_zero),
                "failed_gate_ids": [
                    gate["gate_id"] for gate in required_without_zero if gate["status"] == "failed"
                ],
                "blocked_gate_ids": [
                    gate["gate_id"] for gate in required_without_zero if gate["status"] == "blocked"
                ],
            },
            blockers=[] if zero_p0_status == "passed" else ["upstream_required_gates_not_passed"],
        )

    recompute_level_statuses(levels)
    report = {
        "schema_version": "0.1",
        "acceptance_id": acceptance_id,
        "iteration": str(config["iteration"]),
        "started_at_utc": started_at,
        "finished_at_utc": utc_now(),
        "source": source,
        "isolation": {
            "temporary_runtime_created": True,
            "project_runs_reused": False,
            "runtime_path_persisted": False,
        },
        "external_evidence": {
            "status": "verified" if external_evidence is not None and not external_evidence_blockers else ("invalid" if selected_external_path.exists() else "not_collected"),
            "path": _display_path(selected_external_path),
            "sha256": external_evidence.manifest_sha256 if external_evidence is not None else None,
            "producer_id": external_evidence.manifest["producer"]["id"] if external_evidence is not None else None,
            "producer_version": external_evidence.manifest["producer"]["version"] if external_evidence is not None else None,
            "producer_run_id": external_evidence.manifest["producer"]["run_id"] if external_evidence is not None else None,
            "source_commit": external_evidence.manifest["source_commit"] if external_evidence is not None else None,
            "command_id": "controlled_external_evidence",
            "blockers": external_evidence_blockers,
        },
        "commands": commands,
        "levels": levels,
        "summary": summarize_levels(
            levels,
            github_released=github_release_gate_passed(levels),
        ),
    }
    validate_report_shape(report, config)
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the fail-closed Model Harness v0.7 L0-L5 acceptance aggregator."
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Acceptance report JSON path. Defaults to runs/acceptance/<id>/acceptance-report.json.",
    )
    parser.add_argument(
        "--controlled-evidence-dir",
        type=Path,
        help=(
            "Optional fresh output directory for this run's controlled evidence. "
            "Existing directories and hand-authored JSON are refused."
        ),
    )
    parser.add_argument(
        "--user-approval-checkpoint-id",
        required=True,
        help=(
            "Identifier of the explicit user approval checkpoint authorizing "
            "the controlled acceptance runs and artifact delivery actions."
        ),
    )
    return parser.parse_args()


def main() -> int:
    arguments = parse_args()
    if arguments.output:
        output_path = arguments.output.expanduser().resolve()
    else:
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        output_path = (
            ROOT
            / "runs"
            / "acceptance"
            / f"v0.7-{timestamp}-{uuid4().hex[:8]}"
            / "acceptance-report.json"
        )
    report = execute_acceptance(
        output_path,
        user_approval_checkpoint_id=arguments.user_approval_checkpoint_id,
        controlled_evidence_dir=arguments.controlled_evidence_dir,
    )
    print(
        json.dumps(
            {
                "report": str(output_path),
                "local_beta_verified": report["summary"]["local_beta_verified"],
                "github_released": report["summary"]["github_released"],
                "required_gate_counts": report["summary"]["required_gate_counts"],
                "failed_gate_ids": report["summary"]["failed_gate_ids"],
                "blocking_gate_ids": report["summary"]["blocking_gate_ids"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report["summary"]["local_beta_verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
