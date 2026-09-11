from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence
from uuid import uuid4

from .errors import ContractError


SCHEMA_VERSION = "0.1"
ESTIMATOR_VERSION = "resource-fit/0.1"

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,159}$")
_PACKAGE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_PINNED_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,127}$")
_GPU_MARKERS = ("cuda", "cudnn", "rocm", "tensorflow-gpu", "nvidia-")
_PLATFORMS = {"darwin", "linux"}
_ARCHITECTURES = {"arm64", "x86_64"}
_EXECUTION_BACKENDS = {"oci", "os_sandbox_worker"}
_PLAN_PATCH_FIELDS = {"resource_budget", "hyperparameters"}
_RESOURCE_BUDGET_FIELDS = {"max_seconds", "ram_bytes", "vram_bytes", "disk_bytes"}
# Automatic tuning is only presented as a viable plan revision when the
# observed host has enough of the constrained resource to make a bounded
# reduction credible.  Larger gaps remain an external/manual remediation.
_MIN_AUTOMATIC_REVISION_RATIO = 0.25


class ResourceFeasibilityError(ContractError):
    """Raised when a resource-feasibility object violates its frozen contract."""


def canonical_json(value: Any) -> bytes:
    """Return the one canonical representation used by every V3 digest."""

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def _copy_json(value: Any) -> Any:
    """Copy through canonical JSON so callers cannot mutate sealed state."""

    return json.loads(canonical_json(value).decode("utf-8"))


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _safe_id(value: str, label: str) -> str:
    selected = str(value or "").strip()
    if not _SAFE_ID.fullmatch(selected):
        raise ResourceFeasibilityError(f"invalid {label}")
    return selected


def _digest(value: str, label: str, *, prefixed: bool = False) -> str:
    selected = str(value or "").strip().lower()
    pattern = _DIGEST if prefixed else _SHA256
    if not pattern.fullmatch(selected):
        raise ResourceFeasibilityError(f"invalid {label}")
    return selected


def _non_negative_integer(value: Any, label: str) -> int:
    if isinstance(value, bool):
        raise ResourceFeasibilityError(f"invalid {label}")
    try:
        selected = int(value)
    except (TypeError, ValueError) as exc:
        raise ResourceFeasibilityError(f"invalid {label}") from exc
    if selected < 0:
        raise ResourceFeasibilityError(f"invalid {label}")
    return selected


def _normalize_arch(value: str) -> str:
    selected = str(value or "").strip().lower()
    aliases = {"aarch64": "arm64", "amd64": "x86_64", "x64": "x86_64"}
    return aliases.get(selected, selected)


def _run_read_only_probe(argv: Sequence[str], *, timeout: float = 3.0) -> tuple[bool, str]:
    """Run a fixed host capability query without a shell or repository input."""

    try:
        result = subprocess.run(
            list(argv),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
            timeout=timeout,
            cwd=os.path.abspath(os.sep),
        )
    except (OSError, subprocess.SubprocessError):
        return False, ""
    output = (result.stdout or "").strip()
    return result.returncode == 0, output[:500]


def _total_ram_bytes() -> int | None:
    try:
        pages = int(os.sysconf("SC_PHYS_PAGES"))
        page_size = int(os.sysconf("SC_PAGE_SIZE"))
        if pages > 0 and page_size > 0:
            return pages * page_size
    except (AttributeError, OSError, TypeError, ValueError):
        pass

    sysctl = shutil.which("sysctl")
    if sysctl:
        ok, output = _run_read_only_probe((sysctl, "-n", "hw.memsize"))
        if ok:
            try:
                value = int(output)
            except ValueError:
                value = 0
            if value > 0:
                return value
    return None


def _available_ram_bytes(total_bytes: int | None) -> int | None:
    meminfo = Path("/proc/meminfo")
    if meminfo.is_file():
        try:
            for line in meminfo.read_text(encoding="utf-8").splitlines():
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) * 1024
        except (OSError, IndexError, ValueError):
            pass

    if platform.system().lower() == "darwin":
        vm_stat = shutil.which("vm_stat")
        if vm_stat:
            ok, output = _run_read_only_probe((vm_stat,))
            if ok:
                page_match = re.search(r"page size of (\d+) bytes", output)
                page_size = int(page_match.group(1)) if page_match else 4096
                pages = 0
                for label in (
                    "Pages free",
                    "Pages inactive",
                    "Pages speculative",
                    "Pages purgeable",
                ):
                    match = re.search(rf"^{re.escape(label)}:\s+(\d+)\.", output, re.MULTILINE)
                    if match:
                        pages += int(match.group(1))
                if pages > 0:
                    available = pages * page_size
                    if total_bytes is not None:
                        available = min(available, total_bytes)
                    return available
    return None


def _probe_node() -> dict[str, Any]:
    executable = shutil.which("node")
    if not executable:
        return {
            "available": False,
            "executable": None,
            "version": None,
            "reason": "node executable was not found on PATH",
        }
    ok, output = _run_read_only_probe((executable, "--version"))
    return {
        "available": ok,
        "executable": executable,
        "version": output.splitlines()[0] if ok and output else None,
        "reason": None if ok else "node version probe failed",
    }


def _probe_container_runtime() -> dict[str, Any]:
    installed: list[dict[str, Any]] = []
    for runtime in ("docker", "podman"):
        executable = shutil.which(runtime)
        if not executable:
            continue
        version_ok, version_output = _run_read_only_probe((executable, "--version"))
        if runtime == "docker":
            available, _ = _run_read_only_probe(
                (executable, "version", "--format", "{{.Server.Version}}"),
                timeout=5.0,
            )
        else:
            available, _ = _run_read_only_probe(
                (executable, "info", "--format", "{{.Version.Version}}"),
                timeout=5.0,
            )
        candidate = {
            "runtime": runtime,
            "executable": executable,
            "version": version_output.splitlines()[0] if version_ok and version_output else None,
            "available": available,
        }
        installed.append(candidate)
        if available:
            return {
                **candidate,
                "reason": None,
                "installed_candidates": installed,
            }

    if installed:
        return {
            "available": False,
            "runtime": installed[0]["runtime"],
            "executable": installed[0]["executable"],
            "version": installed[0]["version"],
            "reason": "container CLI is installed but its runtime is unavailable or denied",
            "installed_candidates": installed,
        }
    return {
        "available": False,
        "runtime": None,
        "executable": None,
        "version": None,
        "reason": "no supported OCI container runtime was found on PATH",
        "installed_candidates": [],
    }


def _probe_accelerators(system: str, arch: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    accelerators: list[dict[str, Any]] = []
    detected: list[str] = []

    mps_detected = system == "darwin" and arch == "arm64"
    if mps_detected:
        detected.append("mps")
    accelerators.append(
        {
            "kind": "mps",
            "detected": mps_detected,
            "available": False,
            "memory_bytes": None,
            "reason": (
                "detected on the host but unavailable to the v0.9 CPU-only isolation runtime"
                if mps_detected
                else "MPS-capable Apple Silicon was not detected"
            ),
        }
    )

    nvidia_smi = shutil.which("nvidia-smi")
    cuda_detected = False
    cuda_devices: list[dict[str, Any]] = []
    if nvidia_smi:
        ok, output = _run_read_only_probe(
            (
                nvidia_smi,
                "--query-gpu=name,memory.total",
                "--format=csv,noheader,nounits",
            ),
            timeout=5.0,
        )
        if ok and output:
            for line in output.splitlines():
                name, separator, memory = line.rpartition(",")
                try:
                    memory_bytes = int(memory.strip()) * 1024 * 1024 if separator else None
                except ValueError:
                    memory_bytes = None
                cuda_devices.append(
                    {"name": name.strip() if separator else line.strip(), "memory_bytes": memory_bytes}
                )
            cuda_detected = bool(cuda_devices)
    if cuda_detected:
        detected.append("cuda")
    accelerators.append(
        {
            "kind": "cuda",
            "detected": cuda_detected,
            "available": False,
            "devices": cuda_devices,
            "reason": (
                "detected on the host but disabled by the v0.9 CPU-only execution policy"
                if cuda_detected
                else "CUDA hardware and a working nvidia-smi probe were not detected"
            ),
        }
    )

    unusable_reason = (
        "Host accelerators are detection evidence only; v0.9 executes CPU-only inside isolation."
        if detected
        else "v0.9 executes CPU-only inside isolation; no host accelerator was detected."
    )
    return accelerators, {
        "mode": "cpu_only",
        "detected": detected,
        "unusable_reason": unusable_reason,
    }


def _seal(payload: Mapping[str, Any], digest_field: str) -> bytes:
    unsigned = _copy_json(dict(payload))
    unsigned.pop(digest_field, None)
    unsigned[digest_field] = canonical_sha256(unsigned)
    return canonical_json(unsigned)


def _verify_sealed(
    value: Mapping[str, Any],
    digest_field: str,
    *,
    object_type: str,
) -> bytes:
    selected = _copy_json(dict(value))
    if selected.get("object_type") != object_type:
        raise ResourceFeasibilityError(f"invalid {object_type} object type")
    supplied = _digest(selected.pop(digest_field, None), digest_field)
    observed = canonical_sha256(selected)
    if supplied != observed:
        raise ResourceFeasibilityError(f"{digest_field} mismatch")
    selected[digest_field] = supplied
    return canonical_json(selected)


@dataclass(frozen=True, slots=True)
class ResourceProbe:
    """An immutable, content-addressed snapshot of host capabilities."""

    _canonical_record: bytes

    @classmethod
    def capture(
        cls,
        disk_path: str | Path = ".",
        *,
        probe_id: str | None = None,
        captured_at: str | None = None,
    ) -> ResourceProbe:
        selected_path = Path(disk_path).expanduser().resolve()
        disk_available = selected_path.exists()
        disk: dict[str, Any]
        if disk_available:
            usage = shutil.disk_usage(selected_path)
            disk = {
                "available": True,
                "path": str(selected_path),
                "total_bytes": usage.total,
                "used_bytes": usage.used,
                "free_bytes": usage.free,
                "reason": None,
            }
        else:
            disk = {
                "available": False,
                "path": str(selected_path),
                "total_bytes": None,
                "used_bytes": None,
                "free_bytes": None,
                "reason": "probe path does not exist",
            }

        system = platform.system().lower()
        arch = _normalize_arch(platform.machine())
        cpu_count = os.cpu_count()
        total_ram = _total_ram_bytes()
        available_ram = _available_ram_bytes(total_ram)
        accelerators, accelerator_policy = _probe_accelerators(system, arch)
        record = {
            "schema_version": SCHEMA_VERSION,
            "object_type": "ResourceProbe",
            "resource_probe_id": _safe_id(
                probe_id or f"probe_{uuid4().hex}", "resource probe id"
            ),
            "captured_at": captured_at or _now(),
            "os": {
                "available": bool(system),
                "name": system or None,
                "release": platform.release() or None,
                "reason": None if system else "operating system could not be detected",
            },
            "arch": {
                "available": bool(arch),
                "name": arch or None,
                "reason": None if arch else "machine architecture could not be detected",
            },
            "cpu": {
                "available": bool(cpu_count and cpu_count > 0),
                "logical_count": cpu_count if cpu_count and cpu_count > 0 else None,
                "model": platform.processor() or None,
                "reason": None if cpu_count and cpu_count > 0 else "CPU count could not be detected",
            },
            "ram": {
                "available": total_ram is not None,
                "total_bytes": total_ram,
                "available_bytes": available_ram,
                "reason": None if total_ram is not None else "physical RAM could not be detected",
            },
            "disk": disk,
            "python": {
                "available": True,
                "version": platform.python_version(),
                "executable": sys.executable,
                "reason": None,
            },
            "node": _probe_node(),
            "container_runtime": _probe_container_runtime(),
            "sandbox_worker": {
                "available": False,
                "reason": (
                    "v0.9 has no verified equivalent OS sandbox worker; "
                    "use an available OCI runtime"
                ),
            },
            "accelerators": accelerators,
            "accelerator_policy": accelerator_policy,
        }
        _validate_probe(record)
        return cls(_seal(record, "probe_sha256"))

    @classmethod
    def from_observations(cls, observations: Mapping[str, Any]) -> ResourceProbe:
        """Seal supplied probe facts, primarily for adapters and deterministic tests."""

        record = _copy_json(dict(observations))
        record.setdefault("schema_version", SCHEMA_VERSION)
        record.setdefault("object_type", "ResourceProbe")
        record.setdefault("resource_probe_id", f"probe_{uuid4().hex}")
        record.setdefault("captured_at", _now())
        _validate_probe(record)
        return cls(_seal(record, "probe_sha256"))

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ResourceProbe:
        canonical_record = _verify_sealed(
            value, "probe_sha256", object_type="ResourceProbe"
        )
        record = json.loads(canonical_record.decode("utf-8"))
        _validate_probe(record)
        return cls(canonical_record)

    @property
    def probe_sha256(self) -> str:
        return str(self.to_dict()["probe_sha256"])

    @property
    def resource_probe_id(self) -> str:
        return str(self.to_dict()["resource_probe_id"])

    def to_dict(self) -> dict[str, Any]:
        return json.loads(self._canonical_record.decode("utf-8"))


def _validate_probe(record: Mapping[str, Any]) -> None:
    if record.get("object_type") != "ResourceProbe":
        raise ResourceFeasibilityError("invalid ResourceProbe object type")
    expected_fields = {
        "schema_version",
        "object_type",
        "resource_probe_id",
        "captured_at",
        "os",
        "arch",
        "cpu",
        "ram",
        "disk",
        "python",
        "node",
        "container_runtime",
        "sandbox_worker",
        "accelerators",
        "accelerator_policy",
    }
    if set(record) - {"probe_sha256"} != expected_fields:
        raise ResourceFeasibilityError("ResourceProbe schema changed")
    _safe_id(str(record.get("resource_probe_id", "")), "resource probe id")
    if record.get("schema_version") != SCHEMA_VERSION:
        raise ResourceFeasibilityError("unsupported ResourceProbe schema_version")
    if not str(record.get("captured_at") or "").strip():
        raise ResourceFeasibilityError("ResourceProbe requires captured_at")
    for field in (
        "os",
        "arch",
        "cpu",
        "ram",
        "disk",
        "python",
        "node",
        "container_runtime",
        "sandbox_worker",
    ):
        value = record.get(field)
        if not isinstance(value, Mapping) or not isinstance(value.get("available"), bool):
            raise ResourceFeasibilityError(f"invalid ResourceProbe {field}")
        if not value.get("available") and not str(value.get("reason") or "").strip():
            raise ResourceFeasibilityError(f"unavailable ResourceProbe {field} requires reason")
    if record["sandbox_worker"].get("available") is not False:
        raise ResourceFeasibilityError(
            "v0.9 sandbox worker must remain unavailable until isolation is verified"
        )
    runtime = record["container_runtime"]
    if runtime.get("available") is True and (
        runtime.get("runtime") not in {"docker", "podman"}
        or not str(runtime.get("executable") or "").strip()
    ):
        raise ResourceFeasibilityError(
            "available container runtime requires a supported runtime and executable"
        )
    cpu_count = record["cpu"].get("logical_count")
    if record["cpu"].get("available") is True and (
        isinstance(cpu_count, bool)
        or not isinstance(cpu_count, int)
        or cpu_count < 1
    ):
        raise ResourceFeasibilityError(
            "available ResourceProbe CPU requires a positive logical_count"
        )
    total_ram = record["ram"].get("total_bytes")
    available_ram = record["ram"].get("available_bytes")
    if record["ram"].get("available") is True:
        total_ram = _non_negative_integer(total_ram, "probe total RAM")
        if total_ram < 1:
            raise ResourceFeasibilityError("probe total RAM must be positive")
        if available_ram is not None:
            available_ram = _non_negative_integer(
                available_ram, "probe available RAM"
            )
            if available_ram > total_ram:
                raise ResourceFeasibilityError(
                    "probe available RAM cannot exceed total RAM"
                )
    if record["disk"].get("available") is True:
        total_disk = _non_negative_integer(
            record["disk"].get("total_bytes"), "probe total disk"
        )
        used_disk = _non_negative_integer(
            record["disk"].get("used_bytes"), "probe used disk"
        )
        free_disk = _non_negative_integer(
            record["disk"].get("free_bytes"), "probe free disk"
        )
        if total_disk < 1 or used_disk > total_disk or free_disk > total_disk:
            raise ResourceFeasibilityError("invalid ResourceProbe disk measurements")
    accelerators = record.get("accelerators")
    if not isinstance(accelerators, list):
        raise ResourceFeasibilityError("invalid ResourceProbe accelerators")
    for accelerator in accelerators:
        if not isinstance(accelerator, Mapping):
            raise ResourceFeasibilityError("invalid ResourceProbe accelerator")
        if accelerator.get("available") is not False:
            raise ResourceFeasibilityError("v0.9 accelerator must be unavailable")
        if not isinstance(accelerator.get("detected"), bool):
            raise ResourceFeasibilityError("invalid ResourceProbe accelerator detection")
        if not str(accelerator.get("reason") or "").strip():
            raise ResourceFeasibilityError("ResourceProbe accelerator requires reason")
    accelerator_kinds = [
        str(accelerator.get("kind") or "").strip().lower()
        for accelerator in accelerators
    ]
    if any(not kind for kind in accelerator_kinds) or len(
        accelerator_kinds
    ) != len(set(accelerator_kinds)):
        raise ResourceFeasibilityError(
            "ResourceProbe accelerator kinds must be non-empty and unique"
        )
    policy = record.get("accelerator_policy")
    if not isinstance(policy, Mapping) or policy.get("mode") != "cpu_only":
        raise ResourceFeasibilityError("ResourceProbe policy must be cpu_only")
    detected = policy.get("detected")
    if not isinstance(detected, list):
        raise ResourceFeasibilityError("invalid ResourceProbe detected accelerators")
    if detected and not str(policy.get("unusable_reason") or "").strip():
        raise ResourceFeasibilityError("detected accelerators require unusable_reason")
    observed_detected = sorted(
        str(accelerator.get("kind") or "").strip().lower()
        for accelerator in accelerators
        if accelerator.get("detected") is True
    )
    declared_detected = sorted(str(value).strip().lower() for value in detected)
    if observed_detected != declared_detected:
        raise ResourceFeasibilityError("accelerator policy detection does not match probe facts")


def _validate_environment_payload(record: Mapping[str, Any]) -> None:
    if record.get("object_type") != "EnvironmentLock":
        raise ResourceFeasibilityError("invalid EnvironmentLock object type")
    expected_fields = {
        "schema_version",
        "object_type",
        "environment_lock_id",
        "source_snapshot_id",
        "platform",
        "execution_backend",
        "accelerator_policy",
        "base_image_digest",
        "packages",
        "system_dependencies",
        "network_allowlist",
    }
    if set(record) - {"lock_sha256"} != expected_fields:
        raise ResourceFeasibilityError("EnvironmentLock schema changed")
    if record.get("schema_version") != SCHEMA_VERSION:
        raise ResourceFeasibilityError("unsupported EnvironmentLock schema_version")
    _safe_id(str(record.get("environment_lock_id", "")), "environment lock id")
    _safe_id(str(record.get("source_snapshot_id", "")), "source snapshot id")
    selected_platform = record.get("platform")
    if not isinstance(selected_platform, Mapping) or set(selected_platform) != {
        "os",
        "arch",
    }:
        raise ResourceFeasibilityError("invalid EnvironmentLock platform")
    selected_os = str(selected_platform.get("os") or "").strip().lower()
    selected_arch = _normalize_arch(str(selected_platform.get("arch") or ""))
    if selected_os not in _PLATFORMS or selected_arch not in _ARCHITECTURES:
        raise ResourceFeasibilityError("unsupported EnvironmentLock platform")
    if record.get("execution_backend") not in _EXECUTION_BACKENDS:
        raise ResourceFeasibilityError("unsupported EnvironmentLock execution backend")
    _digest(record.get("base_image_digest"), "base image digest", prefixed=True)

    policy = record.get("accelerator_policy")
    if not isinstance(policy, Mapping) or policy.get("mode") != "cpu_only":
        raise ResourceFeasibilityError("EnvironmentLock accelerator policy must be cpu_only")
    if any(
        policy.get(field) not in (None, False, [], "")
        for field in ("available", "gpu_enabled", "container_usable")
    ):
        raise ResourceFeasibilityError("EnvironmentLock cannot make a GPU available")
    if set(policy) != {"mode", "detected", "unusable_reason"}:
        raise ResourceFeasibilityError("EnvironmentLock accelerator policy schema changed")
    detected = policy.get("detected")
    if not isinstance(detected, list) or any(
        not isinstance(value, str) or not value.strip() for value in detected
    ):
        raise ResourceFeasibilityError("invalid EnvironmentLock detected accelerators")
    if detected and not str(policy.get("unusable_reason") or "").strip():
        raise ResourceFeasibilityError("detected accelerators require unusable_reason")

    packages = record.get("packages")
    if not isinstance(packages, list):
        raise ResourceFeasibilityError("invalid EnvironmentLock packages")
    for package in packages:
        if not isinstance(package, Mapping):
            raise ResourceFeasibilityError("invalid EnvironmentLock package")
        if set(package) != {"name", "version", "hashes"}:
            raise ResourceFeasibilityError("EnvironmentLock package schema changed")
        name = str(package.get("name") or "").strip()
        version = str(package.get("version") or "").strip()
        if not _PACKAGE_NAME.fullmatch(name) or not _PINNED_VERSION.fullmatch(version):
            raise ResourceFeasibilityError("package requires an exact name and version")
        lowered = f"{name} {version}".lower()
        if any(marker in lowered for marker in _GPU_MARKERS) or re.search(r"\+cu\d+", lowered):
            raise ResourceFeasibilityError("GPU package is forbidden by cpu_only policy")
        hashes = package.get("hashes")
        if not isinstance(hashes, list) or not hashes:
            raise ResourceFeasibilityError("package requires at least one sha256 hash")
        for package_hash in hashes:
            _digest(package_hash, "package hash", prefixed=True)

    system_dependencies = record.get("system_dependencies")
    if not isinstance(system_dependencies, list):
        raise ResourceFeasibilityError("invalid EnvironmentLock system dependencies")
    for dependency in system_dependencies:
        selected = str(dependency or "").strip()
        if not selected or "*" in selected:
            raise ResourceFeasibilityError("system dependency must be exact")
        name, separator, version = selected.partition("=")
        if not separator or not name.strip() or not version.strip():
            raise ResourceFeasibilityError(
                "system dependency requires an exact version"
            )
        if any(marker in selected.lower() for marker in _GPU_MARKERS):
            raise ResourceFeasibilityError("GPU system dependency is forbidden")

    allowlist = record.get("network_allowlist")
    if not isinstance(allowlist, list):
        raise ResourceFeasibilityError("invalid EnvironmentLock network allowlist")
    for target in allowlist:
        selected = str(target or "").strip()
        if not selected or "*" in selected or any(ord(character) < 33 for character in selected):
            raise ResourceFeasibilityError("network allowlist entries must be exact")


@dataclass(frozen=True, slots=True)
class EnvironmentLock:
    """A validated environment definition that cannot drift after sealing."""

    _canonical_record: bytes

    @classmethod
    def create(
        cls,
        *,
        source_snapshot_id: str,
        platform_os: str,
        platform_arch: str,
        execution_backend: str,
        base_image_digest: str,
        packages: Sequence[Mapping[str, Any]],
        system_dependencies: Sequence[str] = (),
        network_allowlist: Sequence[str] = (),
        detected_accelerators: Sequence[str] = (),
        unusable_reason: str | None = None,
        environment_lock_id: str | None = None,
    ) -> EnvironmentLock:
        detected = [str(value).strip().lower() for value in detected_accelerators]
        record = {
            "schema_version": SCHEMA_VERSION,
            "object_type": "EnvironmentLock",
            "environment_lock_id": _safe_id(
                environment_lock_id or f"envlock_{uuid4().hex}",
                "environment lock id",
            ),
            "source_snapshot_id": _safe_id(source_snapshot_id, "source snapshot id"),
            "platform": {
                "os": str(platform_os).strip().lower(),
                "arch": _normalize_arch(platform_arch),
            },
            "execution_backend": str(execution_backend).strip(),
            "accelerator_policy": {
                "mode": "cpu_only",
                "detected": detected,
                "unusable_reason": (
                    str(unusable_reason).strip()
                    if unusable_reason is not None
                    else (
                        "Host accelerators are detection evidence only; v0.9 executes CPU-only."
                        if detected
                        else "v0.9 executes CPU-only."
                    )
                ),
            },
            "base_image_digest": str(base_image_digest).strip().lower(),
            "packages": [_copy_json(dict(package)) for package in packages],
            "system_dependencies": [str(value).strip() for value in system_dependencies],
            "network_allowlist": [str(value).strip() for value in network_allowlist],
        }
        _validate_environment_payload(record)
        return cls(_seal(record, "lock_sha256"))

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> EnvironmentLock:
        canonical_record = _verify_sealed(
            value, "lock_sha256", object_type="EnvironmentLock"
        )
        record = json.loads(canonical_record.decode("utf-8"))
        _validate_environment_payload(record)
        return cls(canonical_record)

    @property
    def lock_sha256(self) -> str:
        return str(self.to_dict()["lock_sha256"])

    @property
    def environment_lock_id(self) -> str:
        return str(self.to_dict()["environment_lock_id"])

    def to_dict(self) -> dict[str, Any]:
        return json.loads(self._canonical_record.decode("utf-8"))


def _reason(
    *,
    code: str,
    required: Any,
    observed: Any,
    unit: str,
    evidence_ref: str,
    estimator_version: str,
) -> dict[str, Any]:
    return {
        "code": code,
        "required": required,
        "observed": observed,
        "unit": unit,
        "evidence_ref": evidence_ref,
        "estimator_version": estimator_version,
    }


def _validate_plan_revision_patch(value: Any) -> dict[str, Any]:
    """Validate the subset accepted by ``revise_training_plan`` directly."""

    if not isinstance(value, Mapping) or not value:
        raise ResourceFeasibilityError(
            "plan revision alternative requires a non-empty typed patch"
        )
    selected = _copy_json(dict(value))
    unknown = set(selected) - _PLAN_PATCH_FIELDS
    if unknown:
        raise ResourceFeasibilityError(
            f"plan revision alternative contains unsupported fields: {sorted(unknown)}"
        )

    budget = selected.get("resource_budget")
    if budget is not None:
        if not isinstance(budget, Mapping) or not budget:
            raise ResourceFeasibilityError(
                "plan revision resource_budget must be a non-empty object"
            )
        unknown_budget = set(budget) - _RESOURCE_BUDGET_FIELDS
        if unknown_budget:
            raise ResourceFeasibilityError(
                "plan revision resource_budget contains unsupported fields: "
                f"{sorted(unknown_budget)}"
            )
        for field, amount in budget.items():
            if isinstance(amount, bool) or not isinstance(amount, int) or amount < 0:
                raise ResourceFeasibilityError(
                    f"plan revision resource_budget.{field} must be a non-negative integer"
                )
            if field == "max_seconds" and amount == 0:
                raise ResourceFeasibilityError(
                    "plan revision resource_budget.max_seconds must be positive"
                )

    hyperparameters = selected.get("hyperparameters")
    if hyperparameters is not None and (
        not isinstance(hyperparameters, Mapping) or not hyperparameters
    ):
        raise ResourceFeasibilityError(
            "plan revision hyperparameters must be a non-empty object"
        )
    return selected


def _validate_external_remediation(value: Any) -> dict[str, Any]:
    """Validate a host/operator action that must not create a plan revision."""

    if not isinstance(value, Mapping) or set(value) != {"external_remediation"}:
        raise ResourceFeasibilityError(
            "external remediation alternative requires external_remediation details"
        )
    selected = _copy_json(dict(value))
    remediation = selected["external_remediation"]
    expected = {"action", "required", "observed", "evidence_ref"}
    if not isinstance(remediation, Mapping) or set(remediation) != expected:
        raise ResourceFeasibilityError(
            "external remediation schema requires action, required, observed, and evidence_ref"
        )
    if not str(remediation.get("action") or "").strip() or not str(
        remediation.get("evidence_ref") or ""
    ).strip():
        raise ResourceFeasibilityError(
            "external remediation requires an action and evidence_ref"
        )
    return selected


def _plan_revision_alternative(
    changes: Mapping[str, Any], *, expected_effect: str
) -> dict[str, Any]:
    return {
        "changes": _validate_plan_revision_patch(changes),
        "expected_effect": str(expected_effect).strip(),
        "creates_new_plan": True,
    }


def _external_remediation_alternative(
    *,
    action: str,
    required: Any,
    observed: Any,
    evidence_ref: str,
    expected_effect: str,
) -> dict[str, Any]:
    changes = {
        "external_remediation": {
            "action": str(action).strip(),
            "required": _copy_json(required),
            "observed": _copy_json(observed),
            "evidence_ref": str(evidence_ref).strip(),
        }
    }
    return {
        "changes": _validate_external_remediation(changes),
        "expected_effect": str(expected_effect).strip(),
        "creates_new_plan": False,
    }


def _automatic_budget_target(required: int, observed: int) -> int:
    """Return a concrete budget below the current observation with headroom."""

    return min(required, max(0, int(observed * 0.8)))


def _can_automatically_reduce(required: int, observed: int) -> bool:
    return (
        required > 0
        and observed >= 0
        and observed / required >= _MIN_AUTOMATIC_REVISION_RATIO
    )


def _validate_fit_payload(record: Mapping[str, Any]) -> None:
    if record.get("object_type") != "ResourceFitReport":
        raise ResourceFeasibilityError("invalid ResourceFitReport object type")
    expected_fields = {
        "schema_version",
        "object_type",
        "resource_fit_report_id",
        "training_plan_revision_id",
        "training_plan_sha256",
        "environment_lock_id",
        "environment_lock_sha256",
        "resource_probe_id",
        "resource_probe_sha256",
        "probe",
        "requirements",
        "decision",
        "reasons",
        "alternatives",
        "estimator_version",
    }
    if set(record) - {"report_sha256"} != expected_fields:
        raise ResourceFeasibilityError("ResourceFitReport schema changed")
    if record.get("schema_version") != SCHEMA_VERSION:
        raise ResourceFeasibilityError("unsupported ResourceFitReport schema_version")
    _safe_id(str(record.get("resource_fit_report_id", "")), "resource fit report id")
    _safe_id(
        str(record.get("training_plan_revision_id", "")),
        "training plan revision id",
    )
    _safe_id(str(record.get("environment_lock_id", "")), "environment lock id")
    _safe_id(str(record.get("resource_probe_id", "")), "resource probe id")
    for field in (
        "training_plan_sha256",
        "environment_lock_sha256",
        "resource_probe_sha256",
    ):
        _digest(record.get(field), field)
    if record.get("decision") not in {
        "fit",
        "fit_with_revision",
        "blocked_resources",
        "blocked_platform",
        "blocked_environment",
    }:
        raise ResourceFeasibilityError("invalid ResourceFitReport decision")
    estimator_version = str(record.get("estimator_version") or "").strip()
    if not estimator_version:
        raise ResourceFeasibilityError("ResourceFitReport requires estimator_version")
    reasons = record.get("reasons")
    if not isinstance(reasons, list):
        raise ResourceFeasibilityError("invalid ResourceFitReport reasons")
    for reason in reasons:
        if not isinstance(reason, Mapping):
            raise ResourceFeasibilityError("invalid ResourceFitReport reason")
        if set(reason) != {
            "code",
            "required",
            "observed",
            "unit",
            "evidence_ref",
            "estimator_version",
        }:
            raise ResourceFeasibilityError("ResourceFitReport reason schema changed")
        if not str(reason.get("code") or "").strip():
            raise ResourceFeasibilityError("ResourceFitReport reason requires code")
        for field in ("required", "observed", "unit", "evidence_ref", "estimator_version"):
            if field not in reason:
                raise ResourceFeasibilityError(f"ResourceFitReport reason missing {field}")
        if reason.get("estimator_version") != estimator_version:
            raise ResourceFeasibilityError("reason estimator version mismatch")
        if not str(reason.get("unit") or "").strip() or not str(
            reason.get("evidence_ref") or ""
        ).strip():
            raise ResourceFeasibilityError("ResourceFitReport reason lacks evidence")
        if record["resource_probe_sha256"] not in str(reason["evidence_ref"]):
            raise ResourceFeasibilityError("ResourceFitReport reason references another probe")
    probe = record.get("probe")
    if not isinstance(probe, Mapping):
        raise ResourceFeasibilityError("ResourceFitReport requires the sealed probe")
    sealed_probe = ResourceProbe.from_dict(probe)
    if (
        sealed_probe.resource_probe_id != record["resource_probe_id"]
        or sealed_probe.probe_sha256 != record["resource_probe_sha256"]
    ):
        raise ResourceFeasibilityError("ResourceFitReport probe binding mismatch")
    if not isinstance(record.get("requirements"), Mapping) or set(
        record["requirements"]
    ) != {
        "max_seconds",
        "ram_bytes",
        "vram_bytes",
        "disk_bytes",
        "platform",
        "execution_backend",
        "accelerator_policy",
    }:
        raise ResourceFeasibilityError("ResourceFitReport requires resource requirements")
    alternatives = record.get("alternatives")
    if not isinstance(alternatives, list):
        raise ResourceFeasibilityError("invalid ResourceFitReport alternatives")
    plan_revision_alternatives = 0
    for alternative in alternatives:
        if not isinstance(alternative, Mapping) or set(alternative) != {
            "changes",
            "expected_effect",
            "creates_new_plan",
        }:
            raise ResourceFeasibilityError("resource alternative schema changed")
        if not str(alternative.get("expected_effect") or "").strip():
            raise ResourceFeasibilityError("invalid resource alternative")
        if alternative.get("creates_new_plan") is True:
            _validate_plan_revision_patch(alternative.get("changes"))
            plan_revision_alternatives += 1
        elif alternative.get("creates_new_plan") is False:
            _validate_external_remediation(alternative.get("changes"))
        else:
            raise ResourceFeasibilityError(
                "resource alternative creates_new_plan must be boolean"
            )
    if record.get("decision") != "fit" and not alternatives:
        raise ResourceFeasibilityError("blocked ResourceFitReport requires an alternative")
    if record.get("decision") == "fit" and alternatives:
        raise ResourceFeasibilityError("fit ResourceFitReport cannot contain alternatives")
    if (
        record.get("decision") == "fit_with_revision"
        and plan_revision_alternatives == 0
    ):
        raise ResourceFeasibilityError(
            "fit_with_revision requires a typed plan revision alternative"
        )
    semantic = {
        key: value
        for key, value in record.items()
        if key not in {"resource_fit_report_id", "report_sha256"}
    }
    expected_id = f"fit_{canonical_sha256(semantic)[:24]}"
    if record.get("resource_fit_report_id") != expected_id:
        raise ResourceFeasibilityError(
            "ResourceFitReport id does not match its semantic evidence"
        )


@dataclass(frozen=True, slots=True)
class ResourceFitReport:
    """An immutable decision bound to exact plan, environment and probe digests."""

    _canonical_record: bytes

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ResourceFitReport:
        canonical_record = _verify_sealed(
            value, "report_sha256", object_type="ResourceFitReport"
        )
        record = json.loads(canonical_record.decode("utf-8"))
        _validate_fit_payload(record)
        return cls(canonical_record)

    @property
    def report_sha256(self) -> str:
        return str(self.to_dict()["report_sha256"])

    @property
    def decision(self) -> str:
        return str(self.to_dict()["decision"])

    def to_dict(self) -> dict[str, Any]:
        return json.loads(self._canonical_record.decode("utf-8"))


def _as_environment_lock(value: EnvironmentLock | Mapping[str, Any]) -> EnvironmentLock:
    return value if isinstance(value, EnvironmentLock) else EnvironmentLock.from_dict(value)


def _as_resource_probe(value: ResourceProbe | Mapping[str, Any]) -> ResourceProbe:
    return value if isinstance(value, ResourceProbe) else ResourceProbe.from_dict(value)


def evaluate_resource_fit(
    *,
    training_plan_revision_id: str,
    training_plan_sha256: str,
    resource_budget: Mapping[str, Any],
    environment_lock: EnvironmentLock | Mapping[str, Any],
    resource_probe: ResourceProbe | Mapping[str, Any],
    estimator_version: str = ESTIMATOR_VERSION,
) -> ResourceFitReport:
    """Evaluate facts only; alternatives never mutate the supplied plan or lock."""

    plan_id = _safe_id(training_plan_revision_id, "training plan revision id")
    plan_digest = _digest(training_plan_sha256, "training plan sha256")
    estimator = str(estimator_version or "").strip()
    if not estimator:
        raise ResourceFeasibilityError("estimator_version is required")
    selected_budget = {
        "max_seconds": _non_negative_integer(resource_budget.get("max_seconds", 0), "max_seconds"),
        "ram_bytes": _non_negative_integer(resource_budget.get("ram_bytes", 0), "ram_bytes"),
        "vram_bytes": _non_negative_integer(resource_budget.get("vram_bytes", 0), "vram_bytes"),
        "disk_bytes": _non_negative_integer(resource_budget.get("disk_bytes", 0), "disk_bytes"),
    }
    env = _as_environment_lock(environment_lock)
    probe = _as_resource_probe(resource_probe)
    env_record = env.to_dict()
    probe_record = probe.to_dict()
    probe_prefix = f"ResourceProbe:{probe.probe_sha256}"

    reasons: list[dict[str, Any]] = []
    alternatives: list[dict[str, Any]] = []
    platform_blocked = False
    environment_blocked = False
    resources_blocked = False
    ram_blocked = False
    disk_blocked = False

    required_os = env_record["platform"]["os"]
    observed_os = probe_record["os"].get("name") or "unavailable"
    if env_record["execution_backend"] == "oci":
        os_matches = (
            probe_record["os"].get("available") is True
            and required_os == "linux"
            and observed_os in {"darwin", "linux"}
        )
        os_code = "oci_target_os_supported" if os_matches else "oci_target_os_unsupported"
    else:
        os_matches = probe_record["os"].get("available") is True and observed_os == required_os
        os_code = "platform_os_match" if os_matches else "platform_os_mismatch"
    reasons.append(
        _reason(
            code=os_code,
            required=required_os,
            observed=observed_os,
            unit="platform",
            evidence_ref=f"{probe_prefix}#/os/name",
            estimator_version=estimator,
        )
    )
    platform_blocked = platform_blocked or not os_matches

    required_arch = env_record["platform"]["arch"]
    observed_arch = _normalize_arch(str(probe_record["arch"].get("name") or "unavailable"))
    arch_matches = probe_record["arch"].get("available") is True and observed_arch == required_arch
    reasons.append(
        _reason(
            code="platform_arch_match" if arch_matches else "platform_arch_mismatch",
            required=required_arch,
            observed=observed_arch,
            unit="architecture",
            evidence_ref=f"{probe_prefix}#/arch/name",
            estimator_version=estimator,
        )
    )
    platform_blocked = platform_blocked or not arch_matches

    if env_record["execution_backend"] == "oci":
        container_available = (
            probe_record["container_runtime"].get("available") is True
        )
        reasons.append(
            _reason(
                code=(
                    "container_runtime_available"
                    if container_available
                    else "container_runtime_unavailable"
                ),
                required=True,
                observed=container_available,
                unit="boolean",
                evidence_ref=f"{probe_prefix}#/container_runtime/available",
                estimator_version=estimator,
            )
        )
        environment_blocked = not container_available
    else:
        worker_available = probe_record["sandbox_worker"].get("available") is True
        reasons.append(
            _reason(
                code=(
                    "sandbox_worker_available"
                    if worker_available
                    else "sandbox_worker_unverified"
                ),
                required=True,
                observed=worker_available,
                unit="boolean",
                evidence_ref=f"{probe_prefix}#/sandbox_worker/available",
                estimator_version=estimator,
            )
        )
        environment_blocked = not worker_available

    required_ram = selected_budget["ram_bytes"]
    observed_ram = probe_record["ram"].get("available_bytes")
    if observed_ram is None:
        reasons.append(
            _reason(
                code="ram_observation_unavailable",
                required=required_ram,
                observed="unavailable",
                unit="bytes",
                evidence_ref=f"{probe_prefix}#/ram/available_bytes",
                estimator_version=estimator,
            )
        )
        environment_blocked = True
    else:
        observed_ram = _non_negative_integer(observed_ram, "observed ram")
        ram_fits = observed_ram >= required_ram
        reasons.append(
            _reason(
                code="ram_sufficient" if ram_fits else "insufficient_ram",
                required=required_ram,
                observed=observed_ram,
                unit="bytes",
                evidence_ref=f"{probe_prefix}#/ram/available_bytes",
                estimator_version=estimator,
            )
        )
        resources_blocked = resources_blocked or not ram_fits
        ram_blocked = not ram_fits

    required_disk = selected_budget["disk_bytes"]
    observed_disk = probe_record["disk"].get("free_bytes")
    if observed_disk is None:
        reasons.append(
            _reason(
                code="disk_observation_unavailable",
                required=required_disk,
                observed="unavailable",
                unit="bytes",
                evidence_ref=f"{probe_prefix}#/disk/free_bytes",
                estimator_version=estimator,
            )
        )
        environment_blocked = True
    else:
        observed_disk = _non_negative_integer(observed_disk, "observed disk")
        disk_fits = observed_disk >= required_disk
        reasons.append(
            _reason(
                code="disk_sufficient" if disk_fits else "insufficient_disk",
                required=required_disk,
                observed=observed_disk,
                unit="bytes",
                evidence_ref=f"{probe_prefix}#/disk/free_bytes",
                estimator_version=estimator,
            )
        )
        resources_blocked = resources_blocked or not disk_fits
        disk_blocked = not disk_fits

    required_vram = selected_budget["vram_bytes"]
    if required_vram > 0:
        reasons.append(
            _reason(
                code="accelerator_forbidden_by_cpu_only_policy",
                required=required_vram,
                observed=0,
                unit="bytes",
                evidence_ref=f"{probe_prefix}#/accelerator_policy/mode",
                estimator_version=estimator,
            )
        )

    automatic_resource_revision = resources_blocked and all(
        (
            (
                not ram_blocked
                or (
                    isinstance(observed_ram, int)
                    and _can_automatically_reduce(required_ram, observed_ram)
                )
            ),
            (
                not disk_blocked
                or (
                    isinstance(observed_disk, int)
                    and _can_automatically_reduce(required_disk, observed_disk)
                )
            ),
        )
    )
    plan_revision_needed = resources_blocked or required_vram > 0
    can_create_plan_revision = plan_revision_needed and (
        not resources_blocked or automatic_resource_revision
    )

    if platform_blocked:
        decision = "blocked_platform"
    elif environment_blocked:
        decision = "blocked_environment"
    elif can_create_plan_revision:
        decision = "fit_with_revision"
    elif resources_blocked:
        decision = "blocked_resources"
    else:
        decision = "fit"

    if can_create_plan_revision:
        changes: dict[str, Any] = {}
        expected: list[str] = []
        if resources_blocked:
            changes["resource_budget"] = {}
            changes["hyperparameters"] = {
                "batch_size": 1,
                "gradient_accumulation_steps": 8,
                "parameter_efficient_tuning": "lora",
            }
            if ram_blocked and isinstance(observed_ram, int):
                changes["resource_budget"]["ram_bytes"] = _automatic_budget_target(
                    required_ram, observed_ram
                )
            if disk_blocked and isinstance(observed_disk, int):
                changes["resource_budget"]["disk_bytes"] = _automatic_budget_target(
                    required_disk, observed_disk
                )
            expected.append("lower peak RAM and disk demand")
        if required_vram > 0:
            changes.setdefault("resource_budget", {})["vram_bytes"] = 0
            changes.setdefault("hyperparameters", {}).update(
                {
                    "parameter_efficient_tuning": "lora",
                    "model_size": "smaller_cpu_compatible",
                }
            )
            expected.append("replace GPU assumptions with a CPU-sized plan")
        alternatives.append(
            _plan_revision_alternative(
                changes,
                expected_effect="; ".join(expected)
                or "reduce the plan to fit observed resources",
            )
        )

    if platform_blocked:
        alternatives.append(
            _external_remediation_alternative(
                action="use_compatible_host_or_isolation_platform",
                required={"os": required_os, "arch": required_arch},
                observed={"os": observed_os, "arch": observed_arch},
                evidence_ref=f"{probe_prefix}#/os",
                expected_effect=(
                    "move the task to a host or verified isolation worker matching "
                    f"{required_os}/{required_arch}"
                ),
            )
        )

    if env_record["execution_backend"] == "oci" and (
        probe_record["container_runtime"].get("available") is not True
    ):
        alternatives.append(
            _external_remediation_alternative(
                action="install_or_start_approved_oci_runtime",
                required=True,
                observed=False,
                evidence_ref=f"{probe_prefix}#/container_runtime/available",
                expected_effect="make the approved OCI isolation runtime available",
            )
        )
    elif env_record["execution_backend"] == "os_sandbox_worker" and (
        probe_record["sandbox_worker"].get("available") is not True
    ):
        alternatives.append(
            _external_remediation_alternative(
                action="configure_verified_os_sandbox_worker",
                required=True,
                observed=False,
                evidence_ref=f"{probe_prefix}#/sandbox_worker/available",
                expected_effect="provide a verified equivalent OS sandbox worker",
            )
        )

    if observed_ram is None:
        alternatives.append(
            _external_remediation_alternative(
                action="repair_ram_probe",
                required=required_ram,
                observed="unavailable",
                evidence_ref=f"{probe_prefix}#/ram/available_bytes",
                expected_effect="restore a trustworthy available-RAM measurement",
            )
        )
    if observed_disk is None:
        alternatives.append(
            _external_remediation_alternative(
                action="repair_disk_probe",
                required=required_disk,
                observed="unavailable",
                evidence_ref=f"{probe_prefix}#/disk/free_bytes",
                expected_effect="restore a trustworthy free-disk measurement",
            )
        )
    if resources_blocked and not automatic_resource_revision:
        alternatives.append(
            _external_remediation_alternative(
                action="use_larger_host_or_manually_reduce_training_scope",
                required={"ram_bytes": required_ram, "disk_bytes": required_disk},
                observed={"ram_bytes": observed_ram, "disk_bytes": observed_disk},
                evidence_ref=f"{probe_prefix}#/ram/available_bytes",
                expected_effect=(
                    "provide materially more resources or create a manually reviewed "
                    "smaller-model plan"
                ),
            )
        )

    semantic = {
        "schema_version": SCHEMA_VERSION,
        "object_type": "ResourceFitReport",
        "training_plan_revision_id": plan_id,
        "training_plan_sha256": plan_digest,
        "environment_lock_id": env.environment_lock_id,
        "environment_lock_sha256": env.lock_sha256,
        "resource_probe_id": probe.resource_probe_id,
        "resource_probe_sha256": probe.probe_sha256,
        "probe": probe_record,
        "requirements": {
            **selected_budget,
            "platform": _copy_json(env_record["platform"]),
            "execution_backend": env_record["execution_backend"],
            "accelerator_policy": "cpu_only",
        },
        "decision": decision,
        "reasons": reasons,
        "alternatives": alternatives,
        "estimator_version": estimator,
    }
    semantic_digest = canonical_sha256(semantic)
    record = {
        **semantic,
        "resource_fit_report_id": f"fit_{semantic_digest[:24]}",
    }
    _validate_fit_payload(record)
    return ResourceFitReport(_seal(record, "report_sha256"))


__all__ = [
    "ESTIMATOR_VERSION",
    "EnvironmentLock",
    "ResourceFeasibilityError",
    "ResourceFitReport",
    "ResourceProbe",
    "canonical_json",
    "canonical_sha256",
    "evaluate_resource_fit",
]
