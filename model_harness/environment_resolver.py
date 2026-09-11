from __future__ import annotations

"""Resolve a static, server-owned dependency lock from snapshot documents."""

import base64
import re
from copy import deepcopy
from typing import Any, Mapping, Sequence

from .errors import ContractError


_PINNED_REQUIREMENT = re.compile(
    r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)==(?P<version>[^\s;]+)"
    r"(?P<rest>(?:\s+--hash=sha256:[0-9a-fA-F]{64})+)\s*$"
)
_HASH = re.compile(r"--hash=sha256:(?P<digest>[0-9a-fA-F]{64})(?:\s|$)")
_RESOLVER_VERSION = "static-dependency-resolver/0.2"


def _records(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [deepcopy(dict(item)) for item in value if isinstance(item, Mapping)]


def _document_text(snapshot: Mapping[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in _records(snapshot.get("documents")):
        path = str(item.get("path") or "")
        encoded = item.get("content_base64")
        if not path or not isinstance(encoded, str):
            continue
        try:
            raw = base64.b64decode(encoded, validate=True)
            text = raw.decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            continue
        result[path] = text
    return result


def _logical_lines(text: str) -> list[tuple[int, str]]:
    """Return logical requirement lines with their real first source line."""

    lines: list[tuple[int, str]] = []
    parts: list[str] = []
    start_line: int | None = None
    for line_number, raw in enumerate(text.splitlines(), start=1):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        # pip treats a hash-looking option after a whitespace-prefixed `#` as
        # comment text. Strip it before joining continuations so evidence can
        # never turn a non-enforced comment into an immutable package hash.
        stripped = re.sub(r"\s+#.*$", "", stripped).rstrip()
        if not stripped:
            continue
        if start_line is None:
            start_line = line_number
        continued = stripped.endswith("\\")
        parts.append(stripped[:-1].rstrip() if continued else stripped)
        if continued:
            continue
        lines.append((start_line, " ".join(parts).strip()))
        parts = []
        start_line = None
    if parts and start_line is not None:
        # Preserve an unfinished continuation as invalid syntax. Silently
        # treating it as complete can authorize a lock that pip would parse
        # differently once another line is appended.
        lines.append((start_line, " ".join(parts).strip() + " \\"))
    return lines


def resolve_environment_dependencies(
    *,
    snapshot: Mapping[str, Any],
    analysis: Mapping[str, Any],
) -> dict[str, Any]:
    """Return exact packages or typed unresolved evidence without executing code."""

    if not isinstance(snapshot, Mapping) or not isinstance(analysis, Mapping):
        raise ContractError("snapshot and analysis must be objects")
    manifests = _records(
        analysis.get("dependency_files")
        or analysis.get("dependency_manifests")
    )
    if not manifests:
        return {
            "status": "blocked",
            "packages": [],
            "system_dependencies": [],
            "network_allowlist": [],
            "evidence_refs": [],
            "unresolved": [
                {
                    "code": "dependency_manifest_missing",
                    "path": None,
                    "observed": (
                        "repository analysis captured no dependency manifest or "
                        "server-verifiable base-image SBOM"
                    ),
                    "evidence_refs": [],
                }
            ],
            "resolver_version": _RESOLVER_VERSION,
        }

    documents = _document_text(snapshot)
    requirements = [
        item
        for item in manifests
        if item.get("kind") == "pip-requirements"
        or str(item.get("path") or "").lower().startswith("requirements")
    ]
    unresolved: list[dict[str, Any]] = []
    packages_by_name: dict[str, dict[str, Any]] = {}
    evidence_refs: list[str] = []
    for manifest in requirements:
        path = str(manifest.get("path") or "")
        text = documents.get(path)
        refs = [str(item) for item in manifest.get("evidence_refs") or []]
        evidence_refs.extend(ref for ref in refs if ref not in evidence_refs)
        if text is None:
            unresolved.append(
                {
                    "code": "dependency_manifest_content_unavailable",
                    "path": path,
                    "observed": "manifest listed but bounded content was not captured",
                    "evidence_refs": refs,
                }
            )
            continue
        for line_number, line in _logical_lines(text):
            if line.startswith(("-r ", "--requirement ", "-e ", "--editable ")) or " @ " in line:
                unresolved.append(
                    {
                        "code": "dependency_source_not_immutable",
                        "path": path,
                        "line": line_number,
                        "observed": line[:240],
                    }
                )
                continue
            match = _PINNED_REQUIREMENT.match(line)
            hashes = sorted({item.lower() for item in _HASH.findall(line)})
            if match is None or not hashes:
                unresolved.append(
                    {
                        "code": "dependency_not_exactly_pinned_and_hashed",
                        "path": path,
                        "line": line_number,
                        "observed": line[:240],
                    }
                )
                continue
            name = match.group("name").lower().replace("_", "-")
            package = {
                "name": name,
                "version": match.group("version"),
                "hashes": [f"sha256:{digest}" for digest in hashes],
            }
            line_ref = f"{path}:L{line_number}"
            if line_ref not in evidence_refs:
                evidence_refs.append(line_ref)
            previous = packages_by_name.get(name)
            if previous is not None and previous != package:
                unresolved.append(
                    {
                        "code": "dependency_version_conflict",
                        "path": path,
                        "line": line_number,
                        "observed": {"previous": previous, "next": package},
                    }
                )
                continue
            packages_by_name[name] = package

    unsupported = [
        item
        for item in manifests
        if item not in requirements
    ]
    if unsupported and not requirements:
        for item in unsupported:
            unresolved.append(
                {
                    "code": "dependency_manifest_requires_lock_export",
                    "path": str(item.get("path") or ""),
                    "observed": str(item.get("kind") or "unknown"),
                    "evidence_refs": list(item.get("evidence_refs") or []),
                }
            )
    elif unsupported:
        # A hashed requirements export is the executable lock; other project
        # metadata remains provenance and does not silently add packages.
        for item in unsupported:
            evidence_refs.extend(
                ref
                for ref in (str(value) for value in item.get("evidence_refs") or [])
                if ref not in evidence_refs
            )

    return {
        "status": "blocked" if unresolved else "ready",
        "packages": [packages_by_name[name] for name in sorted(packages_by_name)],
        "system_dependencies": [],
        "network_allowlist": [],
        "evidence_refs": evidence_refs,
        "unresolved": unresolved,
        "resolver_version": _RESOLVER_VERSION,
    }
