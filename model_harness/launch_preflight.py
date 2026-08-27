from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .errors import ContractError


LAUNCH_RESOURCE_PREFLIGHT_VERSION = "1.0"
_POLICY_FIELDS = {
    "checkpoint_size_bytes",
    "retained_checkpoint_copies",
    "peak_checkpoint_copies",
    "artifact_reserve_bytes",
    "minimum_free_disk_bytes_after_peak",
    "minimum_available_ram_bytes",
    "maximum_swap_used_bytes",
}


def _non_negative_integer(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ContractError(
            f"launch_resource_policy.{label} must be non-negative integer"
        )
    return value


def validate_launch_resource_policy(value: Any) -> dict[str, int] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping) or set(value) != _POLICY_FIELDS:
        raise ContractError(
            "launch_resource_policy must declare checkpoint peak copies, "
            "disk reserve, available RAM, and swap thresholds"
        )
    selected = {
        field: _non_negative_integer(value.get(field), field)
        for field in sorted(_POLICY_FIELDS)
    }
    checkpoint_size = selected["checkpoint_size_bytes"]
    retained = selected["retained_checkpoint_copies"]
    peak = selected["peak_checkpoint_copies"]
    if checkpoint_size > 0 and peak < retained + 1:
        raise ContractError(
            "launch_resource_policy.peak_checkpoint_copies must include the "
            "new checkpoint before retained checkpoints are pruned"
        )
    if checkpoint_size == 0 and (retained != 0 or peak != 0):
        raise ContractError(
            "zero checkpoint_size_bytes requires zero checkpoint copy counts"
        )
    return selected


def _available_ram_bytes() -> int | None:
    meminfo = Path("/proc/meminfo")
    if meminfo.is_file():
        try:
            for line in meminfo.read_text(encoding="utf-8").splitlines():
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) * 1024
        except (OSError, IndexError, ValueError):
            return None
    if platform.system().lower() != "darwin":
        return None
    executable = shutil.which("vm_stat")
    if not executable:
        return None
    try:
        result = subprocess.run(
            [executable],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
            timeout=3.0,
            cwd=os.path.abspath(os.sep),
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    page_match = re.search(r"page size of (\d+) bytes", result.stdout)
    page_size = int(page_match.group(1)) if page_match else 4096
    pages = 0
    for label in (
        "Pages free",
        "Pages inactive",
        "Pages speculative",
    ):
        match = re.search(
            rf"^{re.escape(label)}:\s+(\d+)\.",
            result.stdout,
            re.MULTILINE,
        )
        if match:
            pages += int(match.group(1))
    return pages * page_size if pages > 0 else None


def _swap_used_bytes() -> int | None:
    meminfo = Path("/proc/meminfo")
    if meminfo.is_file():
        values: dict[str, int] = {}
        try:
            for line in meminfo.read_text(encoding="utf-8").splitlines():
                key, separator, remainder = line.partition(":")
                if separator and key in {"SwapTotal", "SwapFree"}:
                    values[key] = int(remainder.split()[0]) * 1024
        except (OSError, IndexError, ValueError):
            return None
        if {"SwapTotal", "SwapFree"} <= values.keys():
            return max(0, values["SwapTotal"] - values["SwapFree"])
    if platform.system().lower() != "darwin":
        return None
    executable = shutil.which("sysctl")
    if not executable:
        return None
    try:
        result = subprocess.run(
            [executable, "-n", "vm.swapusage"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
            timeout=3.0,
            cwd=os.path.abspath(os.sep),
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    match = re.search(r"used\s*=\s*([0-9.]+)([KMGTP])", result.stdout)
    if not match:
        return None
    multipliers = {
        "K": 1024,
        "M": 1024**2,
        "G": 1024**3,
        "T": 1024**4,
        "P": 1024**5,
    }
    return int(float(match.group(1)) * multipliers[match.group(2)])


def capture_launch_resource_observation(disk_path: str | Path) -> dict[str, Any]:
    selected_path = Path(disk_path).expanduser().resolve()
    disk_free = None
    if selected_path.exists():
        disk_free = shutil.disk_usage(selected_path).free
    return {
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "disk_path": str(selected_path),
        "disk_free_bytes": disk_free,
        "available_ram_bytes": _available_ram_bytes(),
        "swap_used_bytes": _swap_used_bytes(),
    }


def evaluate_launch_resource_preflight(
    contract: Mapping[str, Any],
    *,
    disk_path: str | Path,
    observation: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    policy = validate_launch_resource_policy(
        contract.get("launch_resource_policy")
    )
    observed = dict(
        observation
        if observation is not None
        else capture_launch_resource_observation(disk_path)
    )
    if policy is None:
        return {
            "schema_version": LAUNCH_RESOURCE_PREFLIGHT_VERSION,
            "decision": "not_declared",
            "policy_present": False,
            "requirements": None,
            "observation": observed,
            "checks": [],
        }

    peak_checkpoint_bytes = (
        policy["checkpoint_size_bytes"]
        * policy["peak_checkpoint_copies"]
    )
    required_free_disk = (
        peak_checkpoint_bytes
        + policy["artifact_reserve_bytes"]
        + policy["minimum_free_disk_bytes_after_peak"]
    )
    checks: list[dict[str, Any]] = []

    def check(code: str, required: int, observed_value: Any, mode: str) -> None:
        passed = (
            isinstance(observed_value, int)
            and not isinstance(observed_value, bool)
            and (
                observed_value >= required
                if mode == "minimum"
                else observed_value <= required
            )
        )
        checks.append(
            {
                "code": code,
                "required": required,
                "observed": observed_value,
                "unit": "bytes",
                "passed": passed,
            }
        )

    check(
        "checkpoint_peak_disk_reserve",
        required_free_disk,
        observed.get("disk_free_bytes"),
        "minimum",
    )
    check(
        "available_ram_floor",
        policy["minimum_available_ram_bytes"],
        observed.get("available_ram_bytes"),
        "minimum",
    )
    check(
        "swap_used_ceiling",
        policy["maximum_swap_used_bytes"],
        observed.get("swap_used_bytes"),
        "maximum",
    )
    return {
        "schema_version": LAUNCH_RESOURCE_PREFLIGHT_VERSION,
        "decision": (
            "fit" if all(item["passed"] for item in checks) else "blocked"
        ),
        "policy_present": True,
        "requirements": {
            **policy,
            "peak_checkpoint_bytes": peak_checkpoint_bytes,
            "required_free_disk_bytes_at_launch": required_free_disk,
        },
        "observation": observed,
        "checks": checks,
    }


__all__ = [
    "LAUNCH_RESOURCE_PREFLIGHT_VERSION",
    "capture_launch_resource_observation",
    "evaluate_launch_resource_preflight",
    "validate_launch_resource_policy",
]
