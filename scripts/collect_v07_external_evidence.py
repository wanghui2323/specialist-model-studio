#!/usr/bin/env python3
"""Produce raw, challenge-bound v0.7 acceptance observations.

This script is only a collector.  It never decides whether an acceptance gate
passed.  ``verify_v07_beta.py`` launches it with a fresh challenge and then
independently validates schemas, hashes, browser logs and the live restarted
service.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model_harness.server import create_app  # noqa: E402
from scripts.acceptance_evidence import sha256_file  # noqa: E402
from scripts.prepare_v07_acceptance_runtime import (  # noqa: E402
    _prepare_audio,
    _prepare_tabular,
    _verify_restart,
)


PRODUCER_ID = "model-harness-v07-controlled-producer"
PRODUCER_VERSION = "0.3.0"
PLAYWRIGHT_VERSION = "1.62.1"
CHROME = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
FAMILIES = ("image", "tabular", "audio")
SOURCE_FILES = {
    "python_producer": "scripts/collect_v07_external_evidence.py",
    "browser_producer": "acceptance/browser/collect-browser.mjs",
    "browser_package": "acceptance/browser/package.json",
    "browser_lock": "acceptance/browser/package-lock.json",
}
TOOL_NAMES = ("python", "git", "node", "npm", "uv", "chrome")


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _run_checked(
    command: list[str],
    *,
    cwd: Path = ROOT,
    environment: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"controlled command failed ({completed.returncode}): {command}\n{completed.stdout[-4000:]}"
        )
    return completed


def _git_text(
    tools: dict[str, Path],
    environment: dict[str, str],
    *arguments: str,
) -> str:
    completed = _run_checked(
        [str(tools["git"]), *arguments],
        environment=environment,
    )
    return completed.stdout.strip()


def _validated_tools(args: argparse.Namespace) -> dict[str, Path]:
    selected = {
        "python": Path(sys.executable),
        "git": args.git,
        "node": args.node,
        "npm": args.npm,
        "uv": args.uv,
        "chrome": args.chrome,
    }
    tools: dict[str, Path] = {}
    for name in TOOL_NAMES:
        candidate = selected[name].expanduser()
        if not candidate.is_absolute():
            raise ValueError(f"controlled tool path must be absolute: {name}")
        resolved = candidate.resolve(strict=True)
        if not resolved.is_file() or not os.access(resolved, os.X_OK):
            raise ValueError(f"controlled tool is not executable: {name}")
        if name != "python" and resolved != candidate:
            raise ValueError(f"controlled tool path must already be canonical: {name}")
        tools[name] = candidate if name == "python" else resolved
    return tools


def _controlled_environment(cache_root: Path, tools: dict[str, Path]) -> dict[str, str]:
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
    directories = [str(path.parent) for path in tools.values()]
    environment.update(
        {
            "PATH": os.pathsep.join(
                dict.fromkeys([*directories, "/usr/bin", "/bin", "/usr/sbin", "/sbin"])
            ),
            "TMPDIR": str(cache_root / "tmp"),
            "PYTHONPYCACHEPREFIX": str(cache_root / "pycache"),
            "PYTHONUNBUFFERED": "1",
            "PYTHONNOUSERSITE": "1",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "NPM_CONFIG_USERCONFIG": "/dev/null",
            "UV_NO_CONFIG": "1",
        }
    )
    (cache_root / "tmp").mkdir(parents=True, exist_ok=True)
    return environment


def _validate_source(
    source_commit: str,
    tools: dict[str, Path],
    environment: dict[str, str],
) -> None:
    if len(source_commit) != 40 or any(character not in "0123456789abcdef" for character in source_commit):
        raise ValueError("source commit must be an immutable lowercase SHA")
    if _git_text(tools, environment, "rev-parse", "HEAD") != source_commit:
        raise RuntimeError("producer source commit does not match HEAD")
    if _git_text(tools, environment, "status", "--porcelain"):
        raise RuntimeError("controlled evidence requires a clean worktree")
    for relative in SOURCE_FILES.values():
        if not (ROOT / relative).is_file():
            raise RuntimeError(f"controlled producer source is missing: {relative}")


def _find_hf_report(report_root: Path, source_commit: str) -> tuple[Path, dict[str, Any]]:
    candidates = sorted(report_root.glob("*/report.json"))
    if len(candidates) != 1:
        raise RuntimeError("the fresh HF report root must contain exactly one scenario report")
    path = candidates[0].resolve()
    report = json.loads(path.read_text(encoding="utf-8"))
    scenario = report.get("scenario_evidence") or {}
    if report.get("status") != "passed":
        raise RuntimeError("the fixed-commit HF scenario did not pass")
    resolved_commit = str(scenario.get("resolved_commit") or "")
    if len(resolved_commit) != 40:
        raise RuntimeError("the HF report is not bound to an immutable model commit")
    runtime_dir = path.parent / "runtime"
    if not runtime_dir.is_dir():
        raise RuntimeError("the HF scenario runtime is missing")
    # The repository source commit and the model commit are intentionally distinct.
    if not source_commit:
        raise RuntimeError("source commit is missing")
    return path, report


def _image_journey(report: dict[str, Any]) -> dict[str, Any]:
    scenario = report["scenario_evidence"]
    evaluation = scenario["evaluation"]
    inference = scenario["new_sample_inference"]
    bundle = scenario["artifact_bundle"]
    journey = {
        "task_id": scenario["task_id"],
        "run_id": scenario["run_id"],
        "evaluation_report_id": evaluation["report_id"],
        "inference_check_id": inference["check_id"],
        "artifact_bundle_id": bundle["bundle_id"],
        "recipe": "image-folder-classification",
        "training_status": scenario["run"]["status"],
        "evaluation_status": evaluation.get("integrity_status"),
        "evaluation_conclusion": evaluation.get("conclusion"),
        "inference_status": inference["status"],
        "bundle_status": "completed",
        "bundle_sha256": bundle["sha256"],
        "sample_sha256": inference["sample_sha256"],
        "model_asset_id": scenario["asset_id"],
        "image_source": "official_huggingface_fixed_commit",
        "repository": scenario["repository"],
        "resolved_commit": scenario["resolved_commit"],
    }
    if not all(journey.get(key) for key in ("task_id", "run_id", "evaluation_report_id", "inference_check_id", "artifact_bundle_id", "model_asset_id")):
        raise RuntimeError("HF image journey is missing a required identity")
    return journey


def _prepare_three_family_runtime(hf_report_path: Path, hf_report: dict[str, Any]) -> tuple[Path, dict[str, Any]]:
    runtime_dir = hf_report_path.parent / "runtime"
    journeys: dict[str, dict[str, Any]] = {"image": _image_journey(hf_report)}
    app = create_app(runtime_dir)
    with TestClient(app) as client:
        journeys["tabular"] = _prepare_tabular(client, app)
        journeys["audio"] = _prepare_audio(client, app)
    if tuple(journeys) != FAMILIES:
        raise RuntimeError("three-family journey order drifted")
    restart = _verify_restart(runtime_dir, journeys)
    report = {
        "schema_version": "0.1",
        "status": "passed",
        "mode": "official_hf_fixed_commit",
        "started_at_utc": hf_report["started_at_utc"],
        "finished_at_utc": _now(),
        "journey_families": journeys,
        "restart": restart,
        "huggingface": {
            "skipped": False,
            "repository": journeys["image"]["repository"],
            "requested_commit": journeys["image"]["resolved_commit"],
        },
    }
    _write_json(runtime_dir / "journeys.json", report)
    return runtime_dir, report


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as selected:
        selected.bind(("127.0.0.1", 0))
        return int(selected.getsockname()[1])


def _http_bytes(url: str, *, timeout: float = 5.0) -> tuple[int, bytes, str]:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return int(response.status), response.read(), response.headers.get("content-type", "")


def _http_json(url: str) -> tuple[int, dict[str, Any]]:
    status, payload, _ = _http_bytes(url)
    value = json.loads(payload.decode("utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"expected JSON object from {url}")
    return status, value


def _wait_ready(base_url: str, process: subprocess.Popen[str], timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"service exited before ready: {process.returncode}")
        try:
            status, value = _http_json(f"{base_url}/health")
            if status == 200 and value.get("ok") is True:
                return
        except (OSError, urllib.error.URLError, ValueError, json.JSONDecodeError):
            pass
        time.sleep(0.1)
    raise RuntimeError("service did not become ready")


def _process_identity(
    pid: int,
    command: list[str],
    environment: dict[str, str],
) -> dict[str, str]:
    ps = Path("/bin/ps")
    if not ps.is_file():
        raise RuntimeError("trusted ps executable is unavailable")
    started = _run_checked(
        [str(ps), "-p", str(pid), "-o", "lstart="],
        environment=environment,
    ).stdout.strip()
    observed_command = _run_checked(
        [str(ps), "-p", str(pid), "-o", "command="],
        environment=environment,
    ).stdout.strip()
    if not started or not observed_command:
        raise RuntimeError("service process identity is unavailable")
    return {
        "start_token": hashlib.sha256(started.encode("utf-8")).hexdigest(),
        "observed_command_sha256": hashlib.sha256(
            observed_command.encode("utf-8")
        ).hexdigest(),
        "expected_argv_sha256": hashlib.sha256(
            json.dumps(command, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
    }


def _start_service(
    runtime_dir: Path,
    port: int,
    log_path: Path,
    environment: dict[str, str],
) -> tuple[subprocess.Popen[str], Any, list[str]]:
    handle = log_path.open("x", encoding="utf-8")
    command = [
        sys.executable,
        "-m",
        "model_harness.cli",
        "serve",
        "--runs-dir",
        str(runtime_dir),
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
    ]
    process = subprocess.Popen(
        command,
        cwd=ROOT,
        env=environment,
        text=True,
        stdout=handle,
        stderr=subprocess.STDOUT,
    )
    try:
        _wait_ready(f"http://127.0.0.1:{port}", process)
    except Exception:
        process.terminate()
        process.wait(timeout=10)
        handle.close()
        raise
    return process, handle, command


def _collect_family(base_url: str, family: str, journey: dict[str, Any]) -> dict[str, Any]:
    task_id = journey["task_id"]
    run_id = journey["run_id"]
    _, task_payload = _http_json(f"{base_url}/tasks/{task_id}")
    _, result = _http_json(f"{base_url}/runs/{run_id}/result")
    _, evaluation_payload = _http_json(f"{base_url}/tasks/{task_id}/runs/{run_id}/evaluation-report")
    _, inference_payload = _http_json(f"{base_url}/tasks/{task_id}/runs/{run_id}/sample-inferences/{journey['inference_check_id']}")
    _, bundle_payload = _http_json(f"{base_url}/tasks/{task_id}/runs/{run_id}/artifact-bundles/{journey['artifact_bundle_id']}")
    _, events_payload = _http_json(f"{base_url}/runs/{run_id}/events")
    bundle_status, bundle_bytes, _ = _http_bytes(f"{base_url}/tasks/{task_id}/runs/{run_id}/artifact-bundles/{journey['artifact_bundle_id']}/download")
    if bundle_status != 200:
        raise RuntimeError(f"{family} bundle download failed")
    task = task_payload["task"]
    evaluation = evaluation_payload["evaluation_report"]
    inference = inference_payload["sample_inference"]
    bundle = bundle_payload["artifact_bundle"]
    events = events_payload.get("events") or []
    if not isinstance(events, list) or not events:
        raise RuntimeError(f"{family} run events are missing")
    snapshot = {
        "task_id": task.get("task_id"),
        "run_id": result.get("run_id"),
        "evaluation_report_id": evaluation.get("report_id"),
        "inference_check_id": inference.get("check_id"),
        "artifact_bundle_id": bundle.get("bundle_id"),
        "training_status": result.get("status"),
        "evaluation_conclusion": evaluation.get("conclusion"),
        "inference_status": inference.get("status"),
        "bundle_status": bundle.get("status"),
        "bundle_sha256": bundle.get("archive", {}).get("sha256"),
        "bundle_download_sha256": hashlib.sha256(bundle_bytes).hexdigest(),
        "event_count": len(events),
        "event_last_seq": int(events[-1]["seq"]),
    }
    if family == "image":
        _, verification = _http_json(f"{base_url}/tasks/{task_id}/model-assets/current/verify")
        if verification.get("ok") is not True:
            raise RuntimeError("image ModelAsset verification failed")
        snapshot["model_asset_id"] = task.get("selected_model_asset_id")
    if family == "audio":
        _, build_payload = _http_json(f"{base_url}/tasks/{task_id}/recipe-builds/{journey['build_attempt_id']}")
        build = build_payload["recipe_build"]
        snapshot["build_attempt_id"] = build.get("attempt_id")
        snapshot["recipe_version_id"] = journey.get("recipe_version_id")
    return snapshot


def _collect_families(base_url: str, journeys: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {family: _collect_family(base_url, family, journeys[family]) for family in FAMILIES}


def _port_is_closed(base_url: str) -> bool:
    try:
        _http_bytes(f"{base_url}/health", timeout=0.5)
    except (OSError, urllib.error.URLError):
        return True
    return False


def _copy_json_artifact(source: Path, destination: Path) -> None:
    value = json.loads(source.read_text(encoding="utf-8"))
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _artifact_reference(root: Path, path: Path) -> dict[str, Any]:
    selected = path.resolve(strict=True)
    relative = selected.relative_to(root.resolve(strict=True))
    return {"path": relative.as_posix(), "sha256": sha256_file(selected), "size_bytes": selected.stat().st_size}


def _tool_reference(path: Path) -> dict[str, str]:
    resolved = path.resolve(strict=True)
    return {
        "path": str(path),
        "resolved_path": str(resolved),
        "sha256": sha256_file(resolved),
    }


def _cold_environment(
    root: Path,
    clone: Path,
    tools: dict[str, Path],
) -> dict[str, str]:
    environment = _controlled_environment(root / "controlled-environment", tools)
    cache = root / "cache"
    environment.update(
        {
            "XDG_CACHE_HOME": str(cache / "xdg"),
            "HF_HOME": str(cache / "hf-home"),
            "HF_HUB_CACHE": str(cache / "hf-hub"),
            "UV_CACHE_DIR": str(cache / "uv"),
            "UV_PROJECT_ENVIRONMENT": str(clone / ".venv"),
            "npm_config_cache": str(cache / "npm"),
            "PYTHONUNBUFFERED": "1",
        }
    )
    return environment


def _run_cold_command(command_id: str, argv: list[str], *, cwd: Path, environment: dict[str, str], log_handle: Any) -> dict[str, Any]:
    started = time.monotonic()
    completed = subprocess.run(argv, cwd=cwd, env=environment, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
    duration = round(time.monotonic() - started, 6)
    log_handle.write(json.dumps({"id": command_id, "argv": argv, "cwd": str(cwd), "exit_code": completed.returncode, "duration_seconds": duration, "output": completed.stdout}, ensure_ascii=False) + "\n")
    log_handle.flush()
    return {"id": command_id, "argv": argv, "exit_code": int(completed.returncode), "duration_seconds": duration}


def _collect_cold_clone(
    source_commit: str,
    producer_run_id: str,
    artifacts: Path,
    tools: dict[str, Path],
) -> tuple[dict[str, Any], Path, Path]:
    command_log = artifacts / "cold-clone" / "commands.ndjson"
    report_path = artifacts / "cold-clone" / "cold-clone-report.json"
    copied_journeys = artifacts / "cold-clone" / "minimal-journeys.json"
    command_log.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="model-harness-v07-cold-clone-") as temporary:
        root = Path(temporary).resolve()
        clone = root / "repo"
        environment = _cold_environment(root, clone, tools)
        commands: list[dict[str, Any]] = []
        resolved_commit = ""
        worktree_clean_before_run = False
        preexisting_runs = True
        preexisting_model_cache = True
        with command_log.open("x", encoding="utf-8") as log_handle:
            specs = [
                ("clone", [str(tools["git"]), "clone", "--no-local", "--no-hardlinks", "--no-checkout", str(ROOT), str(clone)], root),
                ("checkout", [str(tools["git"]), "-C", str(clone), "checkout", "--detach", source_commit], root),
                ("uv_sync", [str(tools["uv"]), "sync", "--project", str(clone), "--frozen", "--extra", "server", "--extra", "test"], clone),
                ("python_tests", [str(tools["uv"]), "run", "--project", str(clone), "python", "-m", "unittest", "discover", "-s", "tests", "-v"], clone),
                ("node_ci", [str(tools["npm"]), "--prefix", str(clone / "integrations" / "deepseek-harness"), "ci", "--ignore-scripts"], clone),
                ("node_tests", [str(tools["npm"]), "--prefix", str(clone / "integrations" / "deepseek-harness"), "test"], clone),
                ("node_check", [str(tools["npm"]), "--prefix", str(clone / "integrations" / "deepseek-harness"), "run", "check"], clone),
                ("browser_ci", [str(tools["npm"]), "--prefix", str(clone / "acceptance" / "browser"), "ci", "--ignore-scripts"], clone),
                ("minimal_loop", [str(tools["uv"]), "run", "--project", str(clone), "python", "scripts/prepare_v07_acceptance_runtime.py", "--runtime-dir", str(root / "minimal-runtime"), "--skip-hf"], clone),
            ]
            for command_id, argv, cwd in specs:
                record = _run_cold_command(command_id, argv, cwd=cwd, environment=environment, log_handle=log_handle)
                commands.append(record)
                if record["exit_code"] != 0:
                    raise RuntimeError(f"cold clone command failed: {command_id}")
                if command_id == "checkout":
                    resolved_commit = _run_checked(
                        [str(tools["git"]), "rev-parse", "HEAD"],
                        cwd=clone,
                        environment=environment,
                    ).stdout.strip()
                    worktree_clean_before_run = _run_checked(
                        [str(tools["git"]), "status", "--porcelain"],
                        cwd=clone,
                        environment=environment,
                    ).stdout.strip() == ""
                    preexisting_runs = (clone / "runs").exists()
                    preexisting_model_cache = any(
                        path.exists()
                        for path in (
                            root / "cache" / "hf-home",
                            root / "cache" / "hf-hub",
                            clone / ".venv",
                        )
                    )
        minimal_path = root / "minimal-runtime" / "journeys.json"
        minimal = json.loads(minimal_path.read_text(encoding="utf-8"))
        _copy_json_artifact(minimal_path, copied_journeys)
        family_ids = {
            family: {
                key: minimal["journey_families"][family][key]
                for key in ("task_id", "run_id", "evaluation_report_id", "inference_check_id", "artifact_bundle_id")
            }
            for family in FAMILIES
        }
        report = {
            "schema_version": "0.1",
            "source_commit": source_commit,
            "producer_run_id": producer_run_id,
            "clone_method": "git_clone_no_local_no_hardlinks",
            "resolved_commit": resolved_commit,
            "worktree_clean_before_run": worktree_clean_before_run,
            "preexisting_runs": preexisting_runs,
            "preexisting_model_cache": preexisting_model_cache,
            "commands": commands,
            "minimal_family_ids": family_ids,
        }
        _write_json(report_path, report)
        return report, command_log, copied_journeys


def collect(args: argparse.Namespace) -> Path:
    source_commit = args.source_commit.lower()
    challenge = args.verifier_challenge.lower()
    if len(challenge) != 32 or any(character not in "0123456789abcdef" for character in challenge):
        raise ValueError("verifier challenge must be 32 lowercase hex characters")
    tools = _validated_tools(args)
    producer_cache = args.hf_report_root.expanduser().resolve().parent / "controlled-producer-cache"
    environment = _controlled_environment(producer_cache, tools)
    _validate_source(source_commit, tools, environment)
    output = args.output_dir.expanduser().resolve()
    if output.exists():
        raise FileExistsError("controlled evidence output must not already exist")
    output.mkdir(parents=True, mode=0o700)
    artifacts = output / "artifacts"
    artifacts.mkdir(mode=0o700)
    producer_run_id = f"evidence-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{uuid4().hex[:8]}"
    hf_report_path, hf_report = _find_hf_report(args.hf_report_root.expanduser().resolve(), source_commit)
    runtime_dir, journeys = _prepare_three_family_runtime(hf_report_path, hf_report)
    runtime_artifacts = artifacts / "runtime"
    _copy_json_artifact(runtime_dir / "journeys.json", runtime_artifacts / "journeys.json")
    _copy_json_artifact(hf_report_path, runtime_artifacts / "hf-report.json")

    port = _free_port()
    base_url = f"http://127.0.0.1:{port}"
    process_artifacts = artifacts / "process"
    process_artifacts.mkdir(parents=True)
    before_process: subprocess.Popen[str] | None = None
    after_process: subprocess.Popen[str] | None = None
    before_handle: Any = None
    after_handle: Any = None
    completed = False
    try:
        before_process, before_handle, _ = _start_service(
            runtime_dir,
            port,
            process_artifacts / "before.log",
            environment,
        )
        before = _collect_families(base_url, journeys["journey_families"])
        before_process.terminate()
        before_exit_code = before_process.wait(timeout=20)
        before_handle.close()
        before_handle = None
        old_port_closed = _port_is_closed(base_url)
        live_after_log = runtime_dir / ".controlled-after-service.log"
        after_process, after_handle, after_command = _start_service(
            runtime_dir,
            port,
            live_after_log,
            environment,
        )
        process_identity = _process_identity(
            after_process.pid,
            after_command,
            environment,
        )
        _write_json(
            output / "service-lease.json",
            {
                "schema_version": "0.2",
                "source_commit": source_commit,
                "verifier_challenge": challenge,
                "producer_run_id": producer_run_id,
                "pid": after_process.pid,
                "base_url": base_url,
                **process_identity,
            },
        )
        after = _collect_families(base_url, journeys["journey_families"])
        health_status, _ = _http_json(f"{base_url}/health")
        openapi_status, _ = _http_json(f"{base_url}/openapi.json")
        process_report = {
            "schema_version": "0.1",
            "source_commit": source_commit,
            "producer_run_id": producer_run_id,
            "base_url": base_url,
            "before_pid": before_process.pid,
            "after_pid": after_process.pid,
            "before_exit_code": before_exit_code,
            "old_port_closed": old_port_closed,
            "health_status_after": health_status,
            "openapi_status_after": openapi_status,
            "before": before,
            "after": after,
        }
        _write_json(process_artifacts / "process-restart-report.json", process_report)
        browser_package = ROOT / "acceptance" / "browser"
        _run_checked(
            [str(tools["npm"]), "ci", "--prefix", str(browser_package), "--ignore-scripts"],
            environment=environment,
        )
        node_version = _run_checked(
            [str(tools["node"]), "--version"],
            environment=environment,
        ).stdout.strip()
        installed_playwright = _run_checked(
            [str(tools["node"]), "-p", "require('./node_modules/playwright-core/package.json').version"],
            cwd=browser_package,
            environment=environment,
        ).stdout.strip()
        if installed_playwright != PLAYWRIGHT_VERSION:
            raise RuntimeError("installed playwright-core version drifted")
        browser_output = artifacts / "browser"
        _run_checked(
            [
                str(tools["node"]),
                str(browser_package / "collect-browser.mjs"),
                "--base-url",
                base_url,
                "--journeys",
                str(runtime_dir / "journeys.json"),
                "--output-dir",
                str(browser_output),
                "--source-commit",
                source_commit,
                "--producer-run-id",
                producer_run_id,
                "--chrome",
                str(tools["chrome"]),
            ],
            environment=environment,
        )

        _, cold_log, cold_journeys = _collect_cold_clone(
            source_commit,
            producer_run_id,
            artifacts,
            tools,
        )
        shutil.copyfile(live_after_log, process_artifacts / "after.log")
        source_files = {
            key: {"path": relative, "sha256": sha256_file(ROOT / relative)}
            for key, relative in SOURCE_FILES.items()
        }
        manifest = {
            "schema_version": "0.3",
            "source_commit": source_commit,
            "generated_at_utc": _now(),
            "producer": {
                "id": PRODUCER_ID,
                "version": PRODUCER_VERSION,
                "status": "completed",
                "run_id": producer_run_id,
                "verifier_challenge": challenge,
                "python_version": sys.version.split()[0],
                "node_version": node_version,
                "playwright_core_version": installed_playwright,
                "command": list(args.invoked_argv),
                "source_files": source_files,
                "tools": {
                    name: _tool_reference(tools[name]) for name in TOOL_NAMES
                },
            },
            "runtime": {
                "mode": "official_hf_fixed_commit",
                "base_url": base_url,
                "after_pid": after_process.pid,
                "journeys": _artifact_reference(output, runtime_artifacts / "journeys.json"),
                "hf_report": _artifact_reference(output, runtime_artifacts / "hf-report.json"),
            },
            "browser": {
                "report": _artifact_reference(output, browser_output / "browser-report.json"),
                "desktop": {name: _artifact_reference(output, browser_output / "desktop" / filename) for name, filename in {"screenshot": "final.png", "network_log": "network.ndjson", "console_log": "console.ndjson", "trace": "trace.zip"}.items()},
                "mobile": {name: _artifact_reference(output, browser_output / "mobile" / filename) for name, filename in {"screenshot": "final.png", "network_log": "network.ndjson", "console_log": "console.ndjson", "trace": "trace.zip"}.items()},
            },
            "process_restart": {
                "report": _artifact_reference(output, process_artifacts / "process-restart-report.json"),
                "before_log": _artifact_reference(output, process_artifacts / "before.log"),
                "after_log": _artifact_reference(output, process_artifacts / "after.log"),
            },
            "cold_clone": {
                "report": _artifact_reference(output, artifacts / "cold-clone" / "cold-clone-report.json"),
                "command_log": _artifact_reference(output, cold_log),
                "minimal_journeys": _artifact_reference(output, cold_journeys),
            },
        }
        manifest_path = output / "external-evidence.json"
        _write_json(manifest_path, manifest)
        completed = True
        return manifest_path
    finally:
        if before_process is not None and before_process.poll() is None:
            before_process.terminate()
            before_process.wait(timeout=10)
        if before_handle is not None:
            before_handle.close()
        # A successful producer intentionally leaves the second service alive so
        # the verifier can query it.  The verifier owns final termination.
        if not completed and after_process is not None and after_process.poll() is None:
            after_process.terminate()
            after_process.wait(timeout=10)
        if after_handle is not None:
            after_handle.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect challenge-bound raw v0.7 acceptance evidence.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--verifier-challenge", required=True)
    parser.add_argument("--hf-report-root", type=Path, required=True)
    parser.add_argument("--git", type=Path, required=True)
    parser.add_argument("--node", type=Path, required=True)
    parser.add_argument("--npm", type=Path, required=True)
    parser.add_argument("--uv", type=Path, required=True)
    parser.add_argument("--chrome", type=Path, required=True)
    selected = parser.parse_args()
    selected.invoked_argv = [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:]]
    return selected


def main() -> int:
    arguments = parse_args()
    path = collect(arguments)
    print(json.dumps({"status": "collected", "manifest": str(path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
