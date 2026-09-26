"""Bounded, stdin-only CPU jobs in an explicitly configured local OCI runtime.

The only host executable invoked here is the configured Docker CLI. Images must
already exist locally and be immutable. This module neither builds images nor
generates/runs repository repair code, and readiness does not qualify a recipe.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import stat
import subprocess
import tempfile
import threading
import time
from typing import Any, Callable
from urllib.parse import urlsplit
from uuid import uuid4


TRIAL_COMMAND = ("python", "/opt/studio/model_harness/oci_trial_runner.py")
MAX_PAYLOAD_BYTES = 24 * 1024 * 1024
_IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}\Z")
_IMAGE_REF = re.compile(r"[a-z0-9][a-z0-9._:/-]*@sha256:[0-9a-f]{64}\Z")
_IDENTITY = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
_CONTAINER_ID = re.compile(r"[0-9a-f]{64}\Z")
_LABEL_PREFIX = "io.specialist-model-studio."
_TMPFS = "rw,noexec,nosuid,nodev,size=32m,mode=1777"


def _digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(encoded).hexdigest()


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class OCIJobConfig:
    docker_binary: str
    endpoint: str
    image: str
    command: tuple[str, ...]
    timeout_seconds: int = 30
    memory_bytes: int = 536870912
    pids_limit: int = 128
    max_output_bytes: int = 262144

    def __post_init__(self) -> None:
        binary = Path(self.docker_binary)
        if not binary.is_absolute() or not binary.is_file() or not os.access(binary, os.X_OK):
            raise ValueError("docker_binary_must_be_absolute_executable")
        parsed = urlsplit(self.endpoint)
        if (parsed.scheme != "unix" or parsed.netloc or parsed.query or parsed.fragment
                or not parsed.path.startswith("/") or any(c in self.endpoint for c in ("%", "\x00", "\n", "\r"))
                or self.endpoint != "unix://" + parsed.path):
            raise ValueError("local_unix_socket_endpoint_required")
        if not (_IMAGE_ID.fullmatch(self.image) or _IMAGE_REF.fullmatch(self.image)):
            raise ValueError("immutable_image_digest_required")
        if not isinstance(self.command, tuple) or not self.command or any(
            not isinstance(item, str) or not item or "\x00" in item for item in self.command
        ):
            raise ValueError("nonempty_argv_tuple_required")
        # Commands are trusted operator configuration, never supplied by a job.
        for name, low, high in (
            ("timeout_seconds", 1, 3600), ("memory_bytes", 32 * 1024 * 1024, 64 * 1024**3),
            ("pids_limit", 1, 4096), ("max_output_bytes", 1, 16 * 1024 * 1024),
        ):
            value = getattr(self, name)
            if type(value) is not int or not low <= value <= high:
                raise ValueError(f"invalid_{name}")

    @classmethod
    def from_environment(cls) -> OCIJobConfig | None:
        values = [os.environ.get(key, "").strip() for key in (
            "MODEL_HARNESS_OCI_DOCKER", "MODEL_HARNESS_OCI_ENDPOINT", "MODEL_HARNESS_TRIAL_IMAGE",
        )]
        if not all(values):
            return None
        return cls(*values, command=TRIAL_COMMAND)

    @property
    def runtime_digest(self) -> str:
        return _digest({
            "schema_version": 1, "backend": "oci_cpu", "image": self.image,
            "command": self.command, "timeout_seconds": self.timeout_seconds,
            "memory_bytes": self.memory_bytes, "pids_limit": self.pids_limit,
            "max_output_bytes": self.max_output_bytes, "max_payload_bytes": MAX_PAYLOAD_BYTES,
            "isolation": {"network": "none", "readonly_rootfs": True, "user": "65534:65534",
                          "cpu_count": 1, "memory_swap": self.memory_bytes, "ipc": "private",
                          "cgroupns": "private", "cap_drop": ["ALL"], "no_new_privileges": True,
                          "tmpfs": {"/work": _TMPFS}, "log_driver": "local",
                          "log_options": {"max-size": "1m", "max-file": "1", "compress": "false"},
                          "host_mounts": False, "healthcheck": False},
        })


def from_environment() -> OCIJobConfig | None:
    """Convenience equivalent of OCIJobConfig.from_environment()."""
    return OCIJobConfig.from_environment()


class _JobError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass
class _ProcessResult:
    returncode: int | None
    stdout: bytes = b""
    stderr: bytes = b""
    interruption: str | None = None


def _pump(process: subprocess.Popen, payload: bytes, *, deadline: float,
          max_output: int, cancel: threading.Event | None = None) -> _ProcessResult:
    """Multiplex all three pipes; no writer thread can hang on a full stdin."""
    output = {"stdout": bytearray(), "stderr": bytearray()}
    consumed, offset, interruption = 0, 0, None
    selector = selectors.DefaultSelector()
    try:
        for name in ("stdout", "stderr"):
            stream = getattr(process, name)
            os.set_blocking(stream.fileno(), False)
            selector.register(stream, selectors.EVENT_READ, name)
        if payload:
            os.set_blocking(process.stdin.fileno(), False)
            selector.register(process.stdin, selectors.EVENT_WRITE, "stdin")
        else:
            process.stdin.close()
        while selector.get_map():
            if cancel is not None and cancel.is_set():
                interruption = "cancelled"
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                interruption = "timed_out"
                break
            for key, _ in selector.select(min(0.05, remaining)):
                stream, name = key.fileobj, key.data
                if name == "stdin":
                    try:
                        offset += os.write(stream.fileno(), payload[offset:offset + 65536])
                    except BrokenPipeError:
                        offset = len(payload)
                    except BlockingIOError:
                        continue
                    if offset == len(payload):
                        selector.unregister(stream)
                        stream.close()
                    continue
                try:
                    chunk = os.read(stream.fileno(), 65536)
                except BlockingIOError:
                    continue
                if not chunk:
                    selector.unregister(stream)
                    stream.close()
                    continue
                allowed = max(0, max_output - consumed)
                output[name].extend(chunk[:allowed])
                consumed += len(chunk)
                if consumed > max_output:
                    interruption = "output_limit_exceeded"
                    break
            if interruption:
                break
        if interruption is None:
            while process.poll() is None:
                if cancel is not None and cancel.is_set():
                    interruption = "cancelled"
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    interruption = "timed_out"
                    break
                try:
                    process.wait(timeout=min(0.05, remaining))
                except subprocess.TimeoutExpired:
                    pass
    finally:
        selector.close()
        # Killing the CLI does not prove that its container stopped. The caller
        # must subsequently observe and clean the exact owned container.
        if process.poll() is None:
            process.kill()
            try:
                process.wait(timeout=0.1)
            except subprocess.TimeoutExpired:
                pass
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream is not None and not stream.closed:
                stream.close()
    return _ProcessResult(process.returncode, bytes(output["stdout"]), bytes(output["stderr"]), interruption)


class OCIJobExecutor:
    def __init__(self, config: OCIJobConfig):
        self.config = config
        self._active: set[str] = set()
        self._lock = threading.Lock()

    @property
    def runtime_digest(self) -> str:
        return self.config.runtime_digest

    def _base(self, client_dir: str) -> tuple[list[str], dict[str, str]]:
        argv = [self.config.docker_binary, "--config", client_dir, "-H", self.config.endpoint]
        # Do not inherit proxy settings, contexts, client credentials or HOME.
        env = {"PATH": "/usr/bin:/bin", "DOCKER_CONFIG": client_dir,
               "DOCKER_HOST": self.config.endpoint, "LC_ALL": "C"}
        return argv, env

    def _run(self, args: list[str], client_dir: str, deadline: float, *, payload: bytes = b"",
             cancel: threading.Event | None = None, attached: bool = False,
             on_attached: Callable[[], None] | None = None) -> _ProcessResult:
        if time.monotonic() >= deadline:
            raise _JobError("control_deadline_exceeded")
        argv, env = self._base(client_dir)
        process = None
        try:
            process = subprocess.Popen(argv + args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE, env=env, bufsize=0, close_fds=True,
                                       start_new_session=True)
            if on_attached is not None:
                on_attached()
            result = _pump(process, payload, deadline=deadline if attached else min(deadline, time.monotonic() + 3),
                           max_output=self.config.max_output_bytes if attached else 1024 * 1024, cancel=cancel)
        except (OSError, ValueError) as error:
            raise _JobError("docker_client_unavailable") from error
        finally:
            if process is not None and process.poll() is None:
                process.kill()
                try:
                    process.wait(timeout=0.1)
                except subprocess.TimeoutExpired:
                    pass
            if process is not None:
                for stream in (process.stdin, process.stdout, process.stderr):
                    if stream is not None and not stream.closed:
                        stream.close()
        if not attached and result.interruption:
            raise _JobError("control_" + result.interruption)
        return result

    @staticmethod
    def _json(result: _ProcessResult) -> Any:
        if result.returncode != 0:
            raise _JobError("runtime_command_failed")
        try:
            return json.loads(result.stdout)
        except (ValueError, UnicodeDecodeError) as error:
            raise _JobError("invalid_runtime_observation") from error

    def _readiness(self, client_dir: str, deadline: float) -> dict[str, Any]:
        try:
            if not stat.S_ISSOCK(Path(urlsplit(self.config.endpoint).path).stat().st_mode):
                raise _JobError("local_socket_unavailable")
        except OSError as error:
            raise _JobError("local_socket_unavailable") from error
        server = self._json(self._run(["version", "--format", "{{json .Server}}"], client_dir, deadline))
        if not isinstance(server, dict) or server.get("Os") != "linux":
            raise _JobError("linux_server_required")
        image_result = self._run(["image", "inspect", self.config.image], client_dir, deadline)
        if image_result.returncode != 0:
            raise _JobError("immutable_local_image_unavailable")
        images = self._json(image_result)
        if not isinstance(images, list) or len(images) != 1 or not isinstance(images[0], dict):
            raise _JobError("invalid_image_observation")
        image = images[0]
        image_id = image.get("Id", "")
        if not isinstance(image_id, str) or not _IMAGE_ID.fullmatch(image_id):
            raise _JobError("invalid_image_identity")
        if (_IMAGE_ID.fullmatch(self.config.image) and image_id != self.config.image) or (
            "@" in self.config.image and self.config.image not in image.get("RepoDigests", [])
        ):
            raise _JobError("image_digest_mismatch")
        architectures = {"aarch64": "arm64", "x86_64": "amd64"}
        image_arch, server_arch = image.get("Architecture"), server.get("Arch")
        if (image.get("Os") != "linux" or not image_arch or not server_arch
                or architectures.get(image_arch, image_arch) != architectures.get(server_arch, server_arch)):
            raise _JobError("image_architecture_mismatch")
        if (image.get("Config") or {}).get("Volumes"):
            raise _JobError("image_declared_volumes_not_allowed")
        return {"image_id": image_id, "architecture": image_arch}

    def capability(self) -> dict[str, Any]:
        result = {"available": False, "reason": "runtime_unavailable", "backend": "oci_cpu",
                  "runtime_digest": self.runtime_digest, "image_id": None}
        try:
            with tempfile.TemporaryDirectory(prefix="studio-oci-client-") as client_dir:
                result.update(self._readiness(client_dir, time.monotonic() + 6.2))
            result.update(available=True, reason="ready")
        except _JobError as error:
            result["reason"] = error.code
        except Exception:
            result["reason"] = "runtime_observation_failed"
        return result

    def _identity(self, job_id: str, task_id: str, nonce: str | None = None) -> tuple[str, dict[str, str]]:
        if not all(isinstance(item, str) and _IDENTITY.fullmatch(item) for item in (job_id, task_id)):
            raise _JobError("invalid_job_identity")
        name = "studio-job-" + _digest({"task_id": task_id, "job_id": job_id})[:32]
        labels = {_LABEL_PREFIX + "task-id": task_id, _LABEL_PREFIX + "job-id": job_id,
                  _LABEL_PREFIX + "runtime-digest": self.runtime_digest}
        if nonce is not None:
            labels[_LABEL_PREFIX + "execution-id"] = nonce
        return name, labels

    def _inspect(self, target: str, client_dir: str, deadline: float) -> dict[str, Any] | None:
        result = self._run(["container", "inspect", target], client_dir, deadline)
        if result.returncode != 0:
            message = result.stderr.decode("utf-8", "replace").strip()
            absent = {f"Error: No such container: {target}", f"Error: No such object: {target}",
                      f"Error response from daemon: No such container: {target}",
                      f"Error response from daemon: No such object: {target}"}
            empty_observation = not result.stdout.strip()
            if not empty_observation:
                try:
                    empty_observation = json.loads(result.stdout) == []
                except (ValueError, UnicodeDecodeError):
                    pass
            if result.returncode == 1 and empty_observation and message in absent:
                return None
            raise _JobError("container_observation_unavailable")
        items = self._json(result)
        if not isinstance(items, list) or len(items) != 1 or not isinstance(items[0], dict):
            raise _JobError("invalid_container_observation")
        return items[0]

    @staticmethod
    def _owned(container: dict[str, Any], name: str, labels: dict[str, str], container_id: str | None = None) -> str:
        observed_id = container.get("Id", "")
        if not isinstance(observed_id, str) or not _CONTAINER_ID.fullmatch(observed_id):
            raise _JobError("invalid_container_identity")
        observed_labels = (container.get("Config") or {}).get("Labels") or {}
        if (container.get("Name") != "/" + name or (container_id and observed_id != container_id)
                or any(observed_labels.get(key) != value for key, value in labels.items())):
            raise _JobError("container_ownership_mismatch")
        return observed_id

    def _safe(self, container: dict[str, Any], image_id: str) -> None:
        config, host = container.get("Config") or {}, container.get("HostConfig") or {}
        expected_host = {
            "NetworkMode": "none", "ReadonlyRootfs": True, "Privileged": False,
            "NanoCpus": 1_000_000_000, "Memory": self.config.memory_bytes,
            "MemorySwap": self.config.memory_bytes, "PidsLimit": self.config.pids_limit,
            "IpcMode": "private", "CgroupnsMode": "private", "AutoRemove": False,
        }
        if container.get("Image") != image_id or any(host.get(key) != value for key, value in expected_host.items()):
            raise _JobError("container_security_flags_mismatch")
        if (config.get("User") != "65534:65534" or config.get("Entrypoint") != [self.config.command[0]]
                or config.get("Cmd") != list(self.config.command[1:]) or config.get("WorkingDir") != "/work"
                or config.get("Tty") is not False or config.get("OpenStdin") is not True
                or (config.get("Healthcheck") or {}).get("Test") != ["NONE"]
                or config.get("Volumes")):
            raise _JobError("container_command_or_user_mismatch")
        if (set(host.get("CapDrop") or []) != {"ALL"} or host.get("CapAdd")
                or set(host.get("SecurityOpt") or []) not in ({"no-new-privileges"}, {"no-new-privileges=true"})
                or host.get("Tmpfs") != {"/work": _TMPFS}
                or host.get("LogConfig") != {"Type": "local", "Config": {"max-size": "1m", "max-file": "1", "compress": "false"}}
                or (host.get("RestartPolicy") or {}).get("Name") != "no"):
            raise _JobError("container_security_flags_mismatch")
        for field in ("Binds", "Mounts", "VolumesFrom", "Devices", "DeviceRequests", "DeviceCgroupRules",
                      "PortBindings", "PublishAllPorts", "Links", "ExtraHosts", "PidMode", "UTSMode", "UsernsMode", "CgroupParent"):
            if host.get(field):
                raise _JobError("container_external_access_not_allowed")
        # --tmpfs normally appears only in HostConfig; some engines also list it.
        for mount in container.get("Mounts") or []:
            if (mount.get("Type") != "tmpfs" or mount.get("Destination") != "/work"
                    or mount.get("Source") or mount.get("RW") is not True):
                raise _JobError("container_mount_not_allowed")
        if set((container.get("NetworkSettings") or {}).get("Networks") or {}) - {"none"}:
            raise _JobError("container_external_network_not_allowed")
        if (container.get("State") or {}).get("Running") is not False:
            raise _JobError("container_started_before_verification")

    def _create_args(self, name: str, labels: dict[str, str]) -> list[str]:
        args = ["container", "create", "-i", "--name", name, "--pull=never", "--network", "none",
                "--read-only", "--user", "65534:65534", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
                "--cpus", "1", "--memory", str(self.config.memory_bytes), "--memory-swap", str(self.config.memory_bytes),
                "--pids-limit", str(self.config.pids_limit), "--ipc", "private", "--cgroupns", "private",
                "--tmpfs", "/work:" + _TMPFS, "--workdir", "/work", "--log-driver", "local",
                "--log-opt", "max-size=1m", "--log-opt", "max-file=1", "--log-opt", "compress=false",
                "--restart", "no", "--no-healthcheck",
                "--env", "TMPDIR=/work", "--env", "PYTHONDONTWRITEBYTECODE=1", "--env", "HF_HUB_OFFLINE=1",
                "--env", "HF_HUB_DISABLE_IMPLICIT_TOKEN=1", "--env", "ORT_DISABLE_TELEMETRY=1"]
        for key, value in sorted(labels.items()):
            args += ["--label", key + "=" + value]
        return args + ["--entrypoint", self.config.command[0], self.config.image, *self.config.command[1:]]

    def _cleanup(self, name: str, labels: dict[str, str], container_id: str | None,
                 client_dir: str, deadline: float) -> dict[str, Any]:
        result = {"cleanup_confirmed": False, "container_id": container_id, "exit_code": None,
                  "error_code": None, "was_running": None, "image_id": None}
        try:
            container = self._inspect(container_id or name, client_dir, deadline)
            if container is None:
                result["cleanup_confirmed"] = True
                return result
            exact = self._owned(container, name, labels, container_id)
            result.update(container_id=exact, image_id=container.get("Image"))
            state = container.get("State") or {}
            result["was_running"] = state.get("Running")
            if type(state.get("Running")) is not bool:
                raise _JobError("container_running_state_unknown")
            if state["Running"]:
                # Each mutation uses the immutable ID checked immediately above.
                try:
                    self._run(["container", "stop", "--time", "0", exact], client_dir, deadline)
                except _JobError:
                    pass  # An uncertain stop still requires inspection/kill.
                container = self._inspect(exact, client_dir, deadline)
                if container is None:
                    raise _JobError("container_disappeared_before_stop_confirmation")
                self._owned(container, name, labels, exact)
                state = container.get("State") or {}
                if state.get("Running") is True:
                    try:
                        self._run(["container", "kill", exact], client_dir, deadline)
                    except _JobError:
                        pass
                    container = self._inspect(exact, client_dir, deadline)
                    if container is None:
                        raise _JobError("container_disappeared_before_stop_confirmation")
                    self._owned(container, name, labels, exact)
                    state = container.get("State") or {}
            if state.get("Running") is not False:
                raise _JobError("container_stop_not_confirmed")
            if type(state.get("ExitCode")) is int:
                result["exit_code"] = state["ExitCode"]
            try:
                self._run(["container", "rm", exact], client_dir, deadline)
            except _JobError:
                pass  # A timeout must not be confused with confirmed failure.
            if self._inspect(exact, client_dir, deadline) is not None:
                raise _JobError("container_removal_not_confirmed")
            result["cleanup_confirmed"] = True
        except _JobError as error:
            result["error_code"] = error.code
        except Exception:
            result["error_code"] = "cleanup_observation_failed"
        return result

    def _result(self) -> dict[str, Any]:
        return {"status": "failed", "exit_code": None, "stdout": "", "stderr": "", "container_id": None,
                "cleanup_confirmed": False, "error_code": None, "started_at_utc": _utc(),
                "finished_at_utc": None, "image_id": None, "runtime_digest": self.runtime_digest}

    def execute(self, *, job_id: str, task_id: str, payload: bytes, cancel_event: threading.Event,
                on_started: Callable[[dict], None] | None = None) -> dict[str, Any]:
        result = self._result()
        begun = time.monotonic()
        work_deadline, cleanup_deadline = begun + self.config.timeout_seconds, begun + self.config.timeout_seconds + 14.5
        name, labels, claimed, create_attempted = None, {}, False, False
        try:
            name, labels = self._identity(job_id, task_id, uuid4().hex)
            if not isinstance(payload, bytes) or len(payload) > MAX_PAYLOAD_BYTES:
                raise _JobError("invalid_or_oversized_payload")
            with self._lock:
                if name in self._active:
                    raise _JobError("job_already_executing")
                self._active.add(name)
                claimed = True
            if cancel_event.is_set():
                result.update(status="cancelled", cleanup_confirmed=True, error_code="cancelled_before_create")
                return result
            with tempfile.TemporaryDirectory(prefix="studio-oci-client-") as client_dir:
                try:
                    readiness = self._readiness(client_dir, work_deadline)
                except _JobError as error:
                    result.update(status="blocked_environment", cleanup_confirmed=True, error_code=error.code)
                    return result
                result["image_id"] = readiness["image_id"]
                if self._inspect(name, client_dir, work_deadline) is not None:
                    result.update(status="blocked_environment", error_code="existing_container_requires_recovery")
                    return result
                try:
                    if cancel_event.is_set():
                        result.update(status="cancelled", cleanup_confirmed=True, error_code="cancelled_before_create")
                        return result
                    create_attempted = True
                    created = self._run(self._create_args(name, labels), client_dir, work_deadline)
                    if created.returncode != 0:
                        raise _JobError("container_create_failed")
                    identifier = created.stdout.decode("ascii", "strict").strip()
                    if not _CONTAINER_ID.fullmatch(identifier):
                        raise _JobError("invalid_created_container_identity")
                    result["container_id"] = identifier
                    container = self._inspect(identifier, client_dir, work_deadline)
                    if container is None:
                        raise _JobError("created_container_not_observed")
                    self._owned(container, name, labels, identifier)
                    self._safe(container, result["image_id"])
                    if on_started is not None:
                        # Persist identity before execution can produce effects.
                        on_started({"phase": "created", **{key: result[key] for key in (
                            "container_id", "image_id", "runtime_digest", "started_at_utc")}})
                    if cancel_event.is_set():
                        result.update(status="cancelled", error_code="cancelled_before_start")
                    else:
                        def observe_started() -> None:
                            if on_started is None:
                                return
                            observed = self._inspect(identifier, client_dir, work_deadline)
                            if observed is None:
                                raise _JobError("started_container_not_observed")
                            self._owned(observed, name, labels, identifier)
                            if (observed.get("State") or {}).get("Running") is True:
                                on_started({"phase": "running", **{key: result[key] for key in (
                                    "container_id", "image_id", "runtime_digest", "started_at_utc")}})

                        process = self._run(["container", "start", "--attach", "--interactive", identifier], client_dir,
                                            work_deadline, payload=payload, cancel=cancel_event, attached=True,
                                            on_attached=observe_started)
                        result.update(stdout=process.stdout.decode("utf-8", "replace"), stderr=process.stderr.decode("utf-8", "replace"),
                                      exit_code=process.returncode)
                        if process.interruption:
                            result.update(status=process.interruption if process.interruption in {"cancelled", "timed_out"} else "failed",
                                          error_code=process.interruption)
                        elif process.returncode == 0:
                            result.update(status="succeeded")
                        else:
                            result.update(status="failed", error_code="container_process_failed")
                except _JobError as error:
                    result.update(status="timed_out" if error.code in {"control_timed_out", "control_deadline_exceeded"} else "failed",
                                  error_code=error.code)
                except Exception:
                    result.update(status="failed", error_code="job_execution_failed")
                finally:
                    if create_attempted:
                        cleanup = self._cleanup(name, labels, result["container_id"], client_dir, cleanup_deadline)
                        result["container_id"] = cleanup["container_id"]
                        result["cleanup_confirmed"] = cleanup["cleanup_confirmed"]
                        if cleanup["exit_code"] is not None:
                            result["exit_code"] = cleanup["exit_code"]
                        if not cleanup["cleanup_confirmed"]:
                            result.update(status="observation_degraded", error_code=cleanup["error_code"] or "cleanup_not_confirmed")
                        elif result["status"] == "succeeded" and (
                            cleanup["was_running"] is not False or cleanup["exit_code"] != 0
                        ):
                            result.update(status="observation_degraded", error_code="successful_exit_not_confirmed")
        except _JobError as error:
            result.update(status="observation_degraded" if error.code == "container_observation_unavailable" else "failed",
                          error_code=error.code, cleanup_confirmed=not claimed and error.code != "job_already_executing")
        except Exception:
            result.update(status="observation_degraded", error_code="job_observation_failed")
        finally:
            if claimed:
                with self._lock:
                    self._active.discard(name)
            result["finished_at_utc"] = _utc()
        return result

    def recover(self, job_id: str, task_id: str) -> dict[str, Any]:
        """Observe/stop/remove a prior exact job; never create or restart it."""
        result = self._result()
        name, claimed = None, False
        try:
            name, labels = self._identity(job_id, task_id)
            with self._lock:
                if name in self._active:
                    raise _JobError("job_already_executing")
                self._active.add(name)
                claimed = True
            with tempfile.TemporaryDirectory(prefix="studio-oci-client-") as client_dir:
                cleanup = self._cleanup(name, labels, None, client_dir, time.monotonic() + 14.5)
            result.update({key: cleanup[key] for key in ("container_id", "exit_code", "cleanup_confirmed", "image_id")})
            if cleanup["cleanup_confirmed"]:
                result.update(status="cancelled", error_code="interrupted")
            else:
                result.update(status="observation_degraded", error_code=cleanup["error_code"] or "cleanup_not_confirmed")
        except _JobError as error:
            result.update(status="observation_degraded", error_code=error.code)
        except Exception:
            result.update(status="observation_degraded", error_code="recovery_observation_failed")
        finally:
            if claimed:
                with self._lock:
                    self._active.discard(name)
            result["finished_at_utc"] = _utc()
        return result
