from __future__ import annotations

import os
from pathlib import Path


STUDIO_SOURCE_ROOT_ENV = "SPECIALIST_MODEL_STUDIO_SOURCE_ROOT"
STUDIO_SOURCE_MARKERS = (
    "pyproject.toml",
    "scripts/start_conversation_harness.sh",
    "integrations/deepseek-harness/package.json",
    "acceptance/dsh-runtime/package.json",
)


def validated_studio_source_root(candidate: Path) -> Path | None:
    """Return a canonical source root only when launcher inputs are complete."""

    try:
        resolved = candidate.expanduser().resolve(strict=True)
    except OSError:
        return None
    if not resolved.is_dir():
        return None
    if not all((resolved / marker).is_file() for marker in STUDIO_SOURCE_MARKERS):
        return None
    return resolved


def _explicit_source_root() -> Path | None:
    explicit = os.environ.get(STUDIO_SOURCE_ROOT_ENV, "").strip()
    if not explicit:
        return None
    explicit_path = Path(explicit).expanduser()
    if not explicit_path.is_absolute():
        raise RuntimeError(f"{STUDIO_SOURCE_ROOT_ENV} must be an absolute path.")
    resolved = validated_studio_source_root(explicit_path)
    if resolved is None:
        raise RuntimeError(
            f"{STUDIO_SOURCE_ROOT_ENV} does not identify a complete "
            "Specialist Model Studio source checkout."
        )
    return resolved


def resolve_studio_source_root(*, module_file: Path, prefix: Path) -> Path:
    """Resolve the complete checkout required by the conversation-native Studio."""

    explicit = _explicit_source_root()
    if explicit is not None:
        return explicit

    candidates = (
        module_file.resolve().parents[1],
        prefix.resolve().parent,
    )
    observed: set[Path] = set()
    for candidate in candidates:
        if candidate in observed:
            continue
        observed.add(candidate)
        resolved = validated_studio_source_root(candidate)
        if resolved is not None:
            return resolved

    raise RuntimeError(
        "The complete Studio launcher is not present in this installation. "
        f"Set {STUDIO_SOURCE_ROOT_ENV} to the absolute path of a complete "
        "Specialist Model Studio source checkout; `serve` remains available "
        "for backend-only use."
    )


def resolve_runtime_source_root(*, module_file: Path, prefix: Path) -> Path:
    """Resolve runtime identity while preserving backend-only wheel operation.

    Public Studio starts always provide the explicit source-root environment
    binding. Backend-only wheel users may not have the repository-managed Agent
    runtime, so their identity continues to point at the installed package root.
    """

    explicit = _explicit_source_root()
    if explicit is not None:
        return explicit

    package_root = module_file.resolve().parents[1]
    for candidate in (package_root, prefix.resolve().parent):
        resolved = validated_studio_source_root(candidate)
        if resolved is not None:
            return resolved
    return package_root
