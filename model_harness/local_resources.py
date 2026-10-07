"""Public, observation-only host inventory independent of any training plan."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from .resource_feasibility import ResourceProbe, canonical_sha256


def _label(value: Any) -> str | None:
    # Hardware names and versions are labels, never paths, URLs, environment
    # dumps or command diagnostics. The public inventory omits raw reasons.
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value or len(value) > 160 or not re.fullmatch(r"[\w .,+()\-]+", value):
        return None
    return value


def _number(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _gib(value: Any) -> float | None:
    number = _number(value)
    return round(number / 1024**3, 2) if number is not None else None


def capture_local_resource_inventory(disk_path: Path) -> dict[str, Any]:
    """Capture fixed host queries and expose only allowlisted observations.

    ``disk_path`` is supplied by the server's configured runs directory, never
    by an HTTP caller. No task/evidence store, plan, Run or authorization is
    read or written. ResourceProbe only performs bounded read-only commands.
    """
    observed = ResourceProbe.capture(disk_path).to_dict()
    captured_at = str(observed["captured_at"])
    datetime.fromisoformat(captured_at.replace("Z", "+00:00"))

    def section(name: str) -> Mapping[str, Any]:
        value = observed.get(name)
        return value if isinstance(value, Mapping) else {}

    cpu, ram, disk = section("cpu"), section("ram"), section("disk")
    operating_system, architecture = section("os"), section("arch")
    python, node, container = section("python"), section("node"), section("container_runtime")
    accelerators = []
    for raw in observed.get("accelerators", []):
        if not isinstance(raw, Mapping) or raw.get("kind") not in {"cuda", "mps"}:
            continue
        kind = raw["kind"]
        accelerators.append({
            "kind": kind,
            "detected": raw.get("detected") is True,
            # Host detection is not execution availability. Preserve the
            # existing CPU-only executor policy even if hardware is present.
            "available": False,
            "detection_basis": "host_platform_capability" if kind == "mps" else "nvidia_smi",
            "memory_bytes": _number(raw.get("memory_bytes")),
            "memory_gib": _gib(raw.get("memory_bytes")),
            "devices": [
                {
                    "name": _label(device.get("name")),
                    "memory_bytes": _number(device.get("memory_bytes")),
                    "memory_gib": _gib(device.get("memory_bytes")),
                }
                for device in raw.get("devices", []) if isinstance(device, Mapping)
            ],
        })
    inventory: dict[str, Any] = {
        "schema_version": "0.1",
        "object_type": "LocalResourceInventory",
        "captured_at": captured_at,
        "observation_only": True,
        "model_fit_assessed": False,
        "execution_authorized": False,
        "cpu": {
            "detected": cpu.get("available") is True,
            "logical_count": _number(cpu.get("logical_count")),
            "model": _label(cpu.get("model")),
        },
        "ram": {
            "detected": ram.get("available") is True,
            "total_bytes": _number(ram.get("total_bytes")),
            "available_bytes": _number(ram.get("available_bytes")),
            "total_gib": _gib(ram.get("total_bytes")),
            "available_gib": _gib(ram.get("available_bytes")),
        },
        "disk": {
            "detected": disk.get("available") is True,
            "total_bytes": _number(disk.get("total_bytes")),
            "free_bytes": _number(disk.get("free_bytes")),
            "total_gib": _gib(disk.get("total_bytes")),
            "free_gib": _gib(disk.get("free_bytes")),
        },
        "accelerators": accelerators,
        "runtime": {
            "os": {"name": _label(operating_system.get("name")), "release": _label(operating_system.get("release"))},
            "architecture": _label(architecture.get("name")),
            "python": {"detected": python.get("available") is True, "version": _label(python.get("version"))},
            "node": {"detected": node.get("available") is True, "version": _label(node.get("version"))},
            "container": {
                "runtime": container.get("runtime") if container.get("runtime") in {"docker", "podman"} else None,
                "daemon_reachable": container.get("available") is True,
                "version": _label(container.get("version")),
            },
        },
        "executor_policy": {"mode": "cpu_only", "accelerators_enabled": False},
    }
    inventory["observation_sha256"] = canonical_sha256(inventory)
    return inventory
