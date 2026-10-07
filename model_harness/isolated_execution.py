"""Task-agnostic OCI stages. No source code is ever executed on the host.

Creating/reading a bundle and probing are read-only. run_stage requires an exact
bundle digest and an explicit isolated root. Every stage receives only its own
input snapshot; outputs and logs are private evidence, never public exports.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import selectors
import shutil
import stat
import subprocess
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from threading import Event
from typing import Any, Mapping, Sequence
from uuid import uuid4

from .errors import ContractError

_IMAGE = re.compile(r"^(?:[A-Za-z0-9][A-Za-z0-9._:/-]*@)?sha256:[0-9a-f]{64}$")
_STAGE = re.compile(r"^[a-z][a-z0-9_-]{0,47}$")
_MAX_SOURCE_BYTES = 2 * 1024 * 1024
_MAX_SOURCE_FILES = 128


class InputBudgetExceeded(ContractError):
    """Path-free measured preparation failure; never relax the frozen limit."""
    def __init__(self, required_bytes: int, limit_bytes: int) -> None:
        self.required_bytes = required_bytes
        self.limit_bytes = limit_bytes
        super().__init__(f"stage input requires {required_bytes} bytes; approved limit is {limit_bytes} bytes")


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _relative(value: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 512 or "\\" in value or ":" in value or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ContractError("bundle paths must be safe relative POSIX file names")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} or len(part) > 255 for part in value.split("/")):
        raise ContractError("bundle paths must be safe relative POSIX file names")
    return path.as_posix()


@dataclass(frozen=True)
class ExecutionLimits:
    memory_bytes: int = 512 * 1024 * 1024
    cpus: float = 1.0
    pids: int = 64
    timeout_seconds: float = 60.0
    max_log_bytes: int = 1024 * 1024
    max_artifact_bytes: int = 64 * 1024 * 1024
    max_artifact_files: int = 128
    max_input_bytes: int = 256 * 1024 * 1024
    tmpfs_bytes: int = 64 * 1024 * 1024

    def __post_init__(self) -> None:
        integers = {
            "memory_bytes": (64 * 1024**2, 64 * 1024**3),
            "pids": (8, 512), "max_log_bytes": (1024, 16 * 1024**2),
            "max_artifact_bytes": (1024, 1024**3), "max_artifact_files": (1, 1024),
            "max_input_bytes": (1, 4 * 1024**3), "tmpfs_bytes": (1024**2, 1024**3),
        }
        for name, (minimum, maximum) in integers.items():
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
                raise ContractError(f"invalid execution limit: {name}")
        for name, minimum, maximum in (("cpus", 0.1, 32), ("timeout_seconds", 0.1, 86_400)):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not minimum <= value <= maximum:
                raise ContractError(f"invalid execution limit: {name}")
        if self.tmpfs_bytes > self.memory_bytes:
            raise ContractError("tmpfs limit must not exceed memory limit")


@dataclass(frozen=True)
class ExecutionBundle:
    files: tuple[tuple[str, str], ...]
    stages: tuple[tuple[str, tuple[str, ...]], ...]
    image: str
    limits: ExecutionLimits
    stage_limits: tuple[tuple[str, ExecutionLimits], ...] = ()

    @classmethod
    def create(cls, *, files: Mapping[str, str], stages: Mapping[str, Sequence[str]], image: str, limits: Mapping[str, Any] | ExecutionLimits | None = None,
               stage_limits: Mapping[str, Mapping[str, Any] | ExecutionLimits] | None = None) -> "ExecutionBundle":
        if not isinstance(image, str) or not _IMAGE.fullmatch(image):
            raise ContractError("image must be an immutable image ID or name@sha256:<64 lowercase hex> reference")
        if not isinstance(files, Mapping) or not 1 <= len(files) <= _MAX_SOURCE_FILES:
            raise ContractError("bundle must contain 1 to 128 source files")
        prepared_files = []
        paths: set[str] = set()
        total = 0
        for name, text in files.items():
            name = _relative(name)
            if not isinstance(text, str) or "\0" in text:
                raise ContractError("bundle source must be UTF-8 text without NUL")
            try:
                total += len(text.encode("utf-8"))
            except UnicodeError:
                raise ContractError("bundle source is not valid UTF-8") from None
            if total > _MAX_SOURCE_BYTES:
                raise ContractError("bundle source exceeds 2 MiB")
            if name.casefold() in paths:
                raise ContractError("bundle source paths collide")
            paths.add(name.casefold())
            prepared_files.append((name, text))
        if any(parent.as_posix().casefold() in paths for name, _ in prepared_files for parent in PurePosixPath(name).parents if parent.as_posix() != "."):
            raise ContractError("bundle file is also a directory")
        if not isinstance(stages, Mapping) or not 1 <= len(stages) <= 16:
            raise ContractError("bundle must contain 1 to 16 explicit stages")
        prepared_stages = []
        for name, argv in stages.items():
            if not isinstance(name, str) or not _STAGE.fullmatch(name):
                raise ContractError("invalid stage name")
            if not isinstance(argv, (list, tuple)) or not 1 <= len(argv) <= 128 or any(not isinstance(arg, str) or not arg or len(arg) > 4096 or "\0" in arg for arg in argv):
                raise ContractError("stage command must be a bounded argv list, not a shell string")
            prepared_stages.append((name, tuple(argv)))
        if isinstance(limits, ExecutionLimits):
            selected_limits = limits
        else:
            try:
                selected_limits = ExecutionLimits(**dict(limits or {}))
            except (TypeError, ValueError):
                raise ContractError("invalid execution limits") from None
        if stage_limits is not None and not isinstance(stage_limits, Mapping):
            raise ContractError("stage_limits must map declared stages to tighter limits")
        prepared_limits = []
        defaults = asdict(selected_limits)
        for stage, overrides in (stage_limits or {}).items():
            if stage not in stages:
                raise ContractError("stage_limits references an undeclared execution stage")
            if isinstance(overrides, ExecutionLimits):
                effective = overrides
            else:
                if not isinstance(overrides, Mapping) or set(overrides) - set(defaults):
                    raise ContractError("invalid stage_limits fields")
                try:
                    effective = ExecutionLimits(**{**defaults, **dict(overrides)})
                except (TypeError, ValueError):
                    raise ContractError("invalid stage execution limits") from None
            if any(value > defaults[key] for key, value in asdict(effective).items()):
                raise ContractError("stage_limits may only tighten the bundle default limits")
            prepared_limits.append((stage, effective))
        return cls(tuple(sorted(prepared_files)), tuple(sorted(prepared_stages)), image, selected_limits, tuple(sorted(prepared_limits)))

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ExecutionBundle":
        if not isinstance(value, Mapping) or set(value) - {"schema_version", "files", "stages", "image", "limits", "stage_limits"}:
            raise ContractError("invalid execution bundle fields")
        if value.get("schema_version", "0.1") != "0.1":
            raise ContractError("unsupported execution bundle schema")
        return cls.create(files=value.get("files"), stages=value.get("stages"), image=value.get("image"), limits=value.get("limits"), stage_limits=value.get("stage_limits"))

    def to_dict(self) -> dict[str, Any]:
        result = {"schema_version": "0.1", "files": dict(self.files), "stages": {name: list(argv) for name, argv in self.stages}, "image": self.image, "limits": asdict(self.limits)}
        # Omission is intentional: already-qualified legacy descriptors must
        # retain exactly the same canonical bytes and digest.
        if self.stage_limits:
            result["stage_limits"] = {name: asdict(limits) for name, limits in self.stage_limits}
        return result

    def limits_for_stage(self, stage: str) -> ExecutionLimits:
        if stage not in dict(self.stages):
            raise ContractError("unknown execution stage")
        return dict(self.stage_limits).get(stage, self.limits)

    @property
    def digest(self) -> str:
        return _digest(self.to_dict())


class _OutputViolation(RuntimeError):
    pass


def _scan_outputs(directory: Path, limits: ExecutionLimits, *, hashes: bool = False) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    pending = [(directory, 0)]
    total = directories = 0
    while pending:
        parent, depth = pending.pop()
        if depth > 10:
            raise _OutputViolation("artifact_directory_depth_limit")
        with os.scandir(parent) as entries:
            for entry in entries:
                try:
                    info = entry.stat(follow_symlinks=False)
                except FileNotFoundError:
                    continue
                relative = Path(entry.path).relative_to(directory).as_posix()
                try:
                    _relative(relative)
                except ContractError:
                    raise _OutputViolation("unsafe_artifact_path") from None
                if stat.S_ISDIR(info.st_mode):
                    directories += 1
                    if directories > limits.max_artifact_files * 4 + 16:
                        raise _OutputViolation("artifact_directory_count_limit")
                    pending.append((Path(entry.path), depth + 1))
                    continue
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                    raise _OutputViolation("linked_or_special_artifact")
                total += info.st_size
                if total > limits.max_artifact_bytes or len(found) >= limits.max_artifact_files:
                    raise _OutputViolation("artifact_size_or_count_limit")
                item = {"path": relative, "bytes": info.st_size}
                if hashes:
                    descriptor = os.open(entry.path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
                    with os.fdopen(descriptor, "rb") as handle:
                        current = os.fstat(handle.fileno())
                        if not stat.S_ISREG(current.st_mode) or current.st_nlink != 1 or current.st_size != info.st_size or current.st_ino != info.st_ino:
                            raise _OutputViolation("artifact_changed_during_collection")
                        digest = hashlib.sha256()
                        observed = 0
                        while chunk := handle.read(1024 * 1024):
                            observed += len(chunk)
                            if observed > info.st_size:
                                raise _OutputViolation("artifact_changed_during_collection")
                            digest.update(chunk)
                        if observed != info.st_size:
                            raise _OutputViolation("artifact_changed_during_collection")
                        item["sha256"] = digest.hexdigest()
                found.append(item)
    return sorted(found, key=lambda item: item["path"])


class OCIExecutor:
    def __init__(self, runtime: str | None = None) -> None:
        if runtime not in {None, "docker", "podman"}:
            raise ContractError("runtime must be docker or podman")
        self.runtime = runtime

    @staticmethod
    def _query(argv: list[str], *, timeout: float = 5) -> subprocess.CompletedProcess:
        return subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout, check=False)

    def probe(self) -> dict[str, Any]:
        failures = []
        for runtime in ((self.runtime,) if self.runtime else ("docker", "podman")):
            executable = shutil.which(runtime)
            if not executable:
                continue
            argv = [executable, "version", "--format", "{{.Server.Version}}"] if runtime == "docker" else [executable, "info", "--format", "{{.Version.Version}}"]
            try:
                result = self._query(argv)
                version = result.stdout.decode("utf-8", errors="replace").strip()
                if result.returncode == 0 and version:
                    return {"available": True, "runtime": runtime, "executable": executable, "version": version[:120], "reason": None}
            except (OSError, subprocess.SubprocessError):
                pass
            failures.append(runtime)
        return {"available": False, "runtime": self.runtime, "reason": "runtime_unavailable" if failures else "runtime_not_installed"}

    @staticmethod
    def _snapshot_inputs(files: Mapping[str, Path], destination: Path, limits: ExecutionLimits, cancel: Event | None) -> list[dict[str, Any]]:
        manifest = []
        total = 0
        keys: set[str] = set()
        if not isinstance(files, Mapping) or len(files) > 1024:
            raise ContractError("input_files must be a bounded explicit file mapping")
        required_bytes = 0
        for value in files.values():
            if cancel and cancel.is_set():
                raise InterruptedError("stage_cancelled")
            path = Path(value)
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode):
                raise ContractError("input must be a regular file, not a link or directory")
            required_bytes += info.st_size
        if required_bytes > limits.max_input_bytes:
            raise InputBudgetExceeded(required_bytes, limits.max_input_bytes)
        for relative, source in sorted(files.items()):
            if cancel and cancel.is_set():
                raise InterruptedError("stage_cancelled")
            relative = _relative(relative)
            if relative.casefold() in keys:
                raise ContractError("input file paths collide")
            keys.add(relative.casefold())
            source = Path(source)
            if source.is_symlink() or not source.is_file():
                raise ContractError("input must be a regular file, not a link or directory")
            descriptor = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            digest = hashlib.sha256()
            observed = 0
            with os.fdopen(descriptor, "rb") as reader, target.open("xb") as writer:
                before = os.fstat(reader.fileno())
                if not stat.S_ISREG(before.st_mode) or before.st_size + total > limits.max_input_bytes:
                    raise ContractError("input size/type exceeds stage limit")
                while chunk := reader.read(1024 * 1024):
                    observed += len(chunk)
                    if observed + total > limits.max_input_bytes:
                        raise ContractError("input size exceeds stage limit")
                    if cancel and cancel.is_set():
                        raise InterruptedError("stage_cancelled")
                    writer.write(chunk)
                    digest.update(chunk)
                after = os.fstat(reader.fileno())
                if observed != before.st_size or (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                    raise ContractError("input changed while creating immutable snapshot")
            target.chmod(0o444)
            total += observed
            manifest.append({"path": relative, "bytes": observed, "sha256": digest.hexdigest()})
        return manifest

    @staticmethod
    def _command(executable: str, bundle: ExecutionBundle, stage: str, name: str, source: Path, inputs: Path, output: Path) -> list[str]:
        limits = bundle.limits_for_stage(stage)
        # --mount CSV has no escaping for arbitrary commas; reject such roots
        # before this point rather than risk an additional mount option.
        return [executable, "run", "--name", name, "--pull=never", "--read-only", "--user", "65532:65532",
            "--network", "none", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "--pids-limit", str(limits.pids), "--memory", str(limits.memory_bytes), "--memory-swap", str(limits.memory_bytes),
            "--cpus", str(limits.cpus), "--ulimit", f"fsize={limits.max_artifact_bytes}:{limits.max_artifact_bytes}",
            "--ulimit", "nofile=256:256", "--ipc", "none", "--log-driver", "none",
            "--tmpfs", f"/tmp:rw,noexec,nosuid,nodev,size={limits.tmpfs_bytes},mode=1777",
            "--mount", f"type=bind,src={source},dst=/workspace/source,readonly",
            "--mount", f"type=bind,src={inputs},dst=/workspace/input,readonly",
            "--mount", f"type=bind,src={output},dst=/workspace/output",
            "--workdir", "/workspace/output", "--env", "HOME=/tmp", "--env", "TMPDIR=/tmp",
            "--env", "NUMBA_CACHE_DIR=/tmp/numba", "--env", "MPLCONFIGDIR=/tmp/matplotlib",
            "--env", "HF_HOME=/tmp/huggingface", "--env", "TORCH_HOME=/tmp/torch",
            "--env", f"OMP_NUM_THREADS={max(1, math.ceil(limits.cpus))}", "--env", f"OPENBLAS_NUM_THREADS={max(1, math.ceil(limits.cpus))}",
            "--env", "PYTHONDONTWRITEBYTECODE=1", "--env", "PYTHONUNBUFFERED=1",
            "--entrypoint", dict(bundle.stages)[stage][0], bundle.image, *dict(bundle.stages)[stage][1:]]

    def run_stage(self, bundle: ExecutionBundle, stage: str, *, expected_bundle_digest: str, isolated_root: Path, input_files: Mapping[str, Path] | None = None, cancel_event: Event | None = None) -> dict[str, Any]:
        # Reparse even a directly constructed frozen dataclass, before any IO.
        bundle = ExecutionBundle.from_dict(bundle.to_dict())
        if expected_bundle_digest != bundle.digest:
            raise ContractError("execution bundle digest mismatch")
        if stage not in dict(bundle.stages):
            raise ContractError("unknown execution stage")
        limits = bundle.limits_for_stage(stage)
        root = Path(isolated_root)
        if not root.is_absolute() or root.is_symlink() or any(c in str(root) for c in ",\n\r\0"):
            raise ContractError("isolated_root must be an absolute non-symlink path without mount delimiters")
        root = root.resolve()
        if any(c in str(root) for c in ",\n\r\0"):
            raise ContractError("resolved isolated_root contains mount delimiters")
        started = time.monotonic()
        evidence: dict[str, Any] = {"schema_version": "0.1", "object_type": "IsolatedStageExecution", "execution_id": "stage-" + uuid4().hex,
            "bundle_sha256": bundle.digest, "stage": stage, "image_reference": bundle.image, "limits": asdict(limits),
            "status": "blocked_environment", "executed": False, "exit_code": None, "created_at": datetime.now(UTC).isoformat(),
            "artifacts": [], "private_evidence": True, "public_export_authorized": False, "creates_training_run": False,
            "input_mount_scope": "only_explicit_stage_input_files", "mounts": [{"target": "/workspace/source", "mode": "ro"}, {"target": "/workspace/input", "mode": "ro"}, {"target": "/workspace/output", "mode": "rw"}],
            "container_user": "65532:65532", "network": "none", "errors": []}

        def finish() -> dict[str, Any]:
            evidence["duration_seconds"] = round(time.monotonic() - started, 6)
            evidence["evidence_sha256"] = _digest(evidence)
            return evidence

        if cancel_event and cancel_event.is_set():
            evidence.update(status="cancelled", errors=["cancelled_before_execution"])
            return finish()
        probe = self.probe()
        evidence["runtime"] = {key: probe.get(key) for key in ("runtime", "version", "available", "reason")}
        if not probe["available"]:
            evidence["errors"].append(probe["reason"])
            return finish()
        executable = probe["executable"]
        try:
            image_result = self._query([executable, "image", "inspect", bundle.image, "--format", '{"id":{{json .Id}},"repo_digests":{{json .RepoDigests}},"architecture":{{json .Architecture}},"os":{{json .Os}}}'])
            image = json.loads(image_result.stdout)
            pinned_matches = (isinstance(image, dict) and (
                image.get("id") == bundle.image if bundle.image.startswith("sha256:")
                else any(str(item).endswith("@" + bundle.image.split("@", 1)[1]) for item in image.get("repo_digests") or [])))
            if image_result.returncode or not isinstance(image, dict) or not isinstance(image.get("id"), str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", image["id"]) or not pinned_matches:
                raise ValueError("image digest not verified")
            evidence["image"] = image
            evidence["image_id"] = image["id"]
        except (OSError, subprocess.SubprocessError, ValueError, TypeError):
            evidence["errors"].append("pinned_image_not_present_or_not_verified")
            return finish()

        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        root = root.resolve()
        job = root / evidence["execution_id"]
        job.mkdir(mode=0o700)
        source, inputs, output = job / "source", job / "input", job / "output"
        for directory in (source, inputs, output, job / "logs"):
            directory.mkdir()
        output.chmod(0o777)  # parent job remains private; fixed container UID needs write access.
        evidence["job_directory"] = evidence["execution_id"]
        name = "sms-" + uuid4().hex
        evidence["container_name"] = name
        process = None
        log_path = job / "logs" / "stdio.log"
        seen = retained = 0
        log_digest = hashlib.sha256()
        termination = None
        cleanup_ok = False
        selector = selectors.DefaultSelector()
        try:
            for relative, text in bundle.files:
                target = source / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(text, encoding="utf-8")
                target.chmod(0o444)
            evidence["source_manifest_sha256"] = _digest([{ "path": key, "sha256": hashlib.sha256(value.encode()).hexdigest()} for key, value in bundle.files])
            evidence["inputs"] = self._snapshot_inputs(input_files or {}, inputs, limits, cancel_event)
            evidence["input_manifest_sha256"] = _digest(evidence["inputs"])
            for directory in (source, inputs):
                for child in directory.rglob("*"):
                    if child.is_dir():
                        child.chmod(0o555)
                directory.chmod(0o555)
            command = self._command(executable, bundle, stage, name, source, inputs, output)
            with log_path.open("xb") as log:
                process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, close_fds=True, start_new_session=True)
                assert process.stdout is not None
                os.set_blocking(process.stdout.fileno(), False)
                selector.register(process.stdout, selectors.EVENT_READ)
                deadline = time.monotonic() + limits.timeout_seconds
                next_scan = 0.0
                exited_at = None
                while True:
                    now = time.monotonic()
                    code = process.poll()
                    if code is None:
                        if cancel_event and cancel_event.is_set():
                            termination = "cancelled"
                            break
                        if now >= deadline:
                            termination = "timed_out"
                            break
                        if now >= next_scan:
                            _scan_outputs(output, limits)
                            next_scan = now + 0.2
                    else:
                        exited_at = exited_at or now
                    events = selector.select(0.1)
                    if events:
                        chunk = os.read(process.stdout.fileno(), 64 * 1024)
                        if not chunk:
                            if code is not None:
                                break
                        else:
                            seen += len(chunk)
                            selected = chunk[:max(0, limits.max_log_bytes - retained)]
                            if selected:
                                log.write(selected)
                                log_digest.update(selected)
                                retained += len(selected)
                    if exited_at is not None and now - exited_at > 1.0:
                        break
                if termination:
                    evidence["status"] = termination
                    evidence["errors"].append(termination)
                else:
                    process.wait(timeout=3)
                    evidence["cli_exit_code"] = process.returncode
        except InterruptedError:
            termination = "cancelled"
            evidence.update(status="cancelled", errors=["cancelled_during_input_snapshot"])
        except _OutputViolation as exc:
            termination = "output_limit_or_integrity_failure"
            evidence.update(status="failed", errors=[str(exc)])
        except InputBudgetExceeded as exc:
            termination = "input_bytes_exceed_approved_limit"
            evidence.update(status="failed", errors=[termination], setup_failure={
                "code": termination, "required_bytes": exc.required_bytes,
                "limit_bytes": exc.limit_bytes, "approval_change_required": True,
                "model_code_executed": False})
        except (OSError, subprocess.SubprocessError, ContractError):
            termination = "execution_setup_or_transport_failure"
            evidence.update(status="failed", errors=[termination])
        finally:
            selector.close()
            if process is not None:
                if termination:
                    try:
                        stopped = self._query([executable, "stop", "--time", "1", name], timeout=5)
                        evidence["stop_requested"] = stopped.returncode == 0
                    except (OSError, subprocess.SubprocessError):
                        evidence["stop_requested"] = False
                try:
                    state_result = self._query([executable, "inspect", "--format", "{{json .State}}", name])
                    state = json.loads(state_result.stdout)
                    if state_result.returncode or not isinstance(state, dict):
                        raise ValueError("state unavailable")
                    evidence["executed"] = bool(state.get("StartedAt") and not str(state["StartedAt"]).startswith("0001-"))
                    evidence["container_state"] = {key: state.get(key) for key in ("Status", "ExitCode", "OOMKilled", "StartedAt", "FinishedAt")}
                    evidence["exit_code"] = state.get("ExitCode") if state.get("Running") is False and type(state.get("ExitCode")) is int else None
                    if not termination:
                        evidence["status"] = "completed" if evidence["executed"] and state.get("Running") is False and state.get("Status") == "exited" and type(state.get("ExitCode")) is int and state["ExitCode"] == 0 and state.get("OOMKilled") is False and process.returncode == 0 else "failed"
                        if evidence["status"] == "failed":
                            evidence["errors"].append("container_did_not_complete_successfully")
                except (OSError, subprocess.SubprocessError, ValueError, TypeError):
                    if not termination:
                        evidence.update(status="observation_degraded", errors=["container_state_unavailable"])
                try:
                    cleanup = self._query([executable, "rm", "--force", name], timeout=10)
                    cleanup_ok = cleanup.returncode == 0
                except (OSError, subprocess.SubprocessError):
                    cleanup_ok = False
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=3)
                if process.stdout is not None:
                    process.stdout.close()
                if not cleanup_ok:
                    evidence["errors"].append("container_cleanup_unconfirmed")
                    if evidence["status"] == "completed":
                        evidence["status"] = "observation_degraded"
            else:
                cleanup_ok = True
            evidence["container_removed"] = cleanup_ok
            evidence["log"] = {"path": "logs/stdio.log", "bytes": retained, "bytes_observed": seen, "sha256": log_digest.hexdigest(), "truncated": seen > retained, "private": True}
        try:
            evidence["artifacts"] = _scan_outputs(output, limits, hashes=True) if cleanup_ok else []
            evidence["artifact_manifest_sha256"] = _digest(evidence["artifacts"])
        except (_OutputViolation, OSError) as exc:
            evidence["artifacts"] = []
            evidence["errors"].append(str(exc) if isinstance(exc, _OutputViolation) else "artifact_collection_failed")
            if evidence["status"] == "completed":
                evidence["status"] = "failed"
        evidence["artifact_limit_enforcement"] = "per_file_rlimit_and_periodic_total_size_monitor_then_final_verification"
        result = finish()
        (job / "execution.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        return result
