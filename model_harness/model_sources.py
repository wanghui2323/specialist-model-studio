from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any, Mapping, Protocol, runtime_checkable
from urllib.parse import unquote, urlsplit

from .errors import HarnessError
from .model_assets import COMMIT_PATTERN, REPO_ID_PATTERN


MAX_PROVIDER_RESPONSE_BYTES = 8 * 1024 * 1024
MAX_TREE_FILES = 20_000
MAX_DOCUMENTS = 64
MAX_DOCUMENT_BYTES = 256 * 1024
MAX_TOTAL_DOCUMENT_BYTES = 2 * 1024 * 1024
MAX_TOKEN_BYTES = 4096
LICENSE_POLICY_VERSION = "v0.9-permissive-allowlist-1"

_DIGEST_PATTERN = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_TRAINING_SOURCE_NAME = re.compile(
    r"^(?:train|trainer|finetune|fine[-_]?tune|run[-_].*|.*[-_](?:train|finetune))\.py$",
    re.IGNORECASE,
)
_DECLARATIVE_DOCUMENT_NAMES = {
    "environment.yml",
    "environment.yaml",
    "package.json",
    "pipfile",
    "pyproject.toml",
    "requirements.txt",
    "setup.cfg",
    "setup.py",
}
_CONFIG_DOCUMENT_NAMES = {
    "config.json",
    "dataset_info.json",
    "preprocessor_config.json",
    "training_args.json",
    "training_config.json",
}


class ModelSourceError(HarnessError):
    """A sanitized model-source discovery or snapshot failure."""


class ModelSourceValidationError(ModelSourceError):
    """The requested source or returned metadata failed local validation."""


class ModelSourceUpstreamError(ModelSourceError):
    """The remote provider could not return trustworthy metadata."""


class ModelSourceIncompleteError(ModelSourceError):
    """The provider returned only a partial tree or document."""


def normalize_repository(value: str) -> str:
    if not isinstance(value, str):
        raise ModelSourceValidationError("invalid_repository")
    selected = value.strip()
    if selected != value or not REPO_ID_PATTERN.fullmatch(selected):
        raise ModelSourceValidationError("invalid_repository")
    if any(part in {"", ".", ".."} for part in selected.split("/")):
        raise ModelSourceValidationError("invalid_repository")
    return selected


def normalize_revision(value: str | None) -> str:
    selected = "main" if value is None else str(value).strip()
    if (
        not selected
        or len(selected) > 200
        or selected != ("main" if value is None else value)
        or selected.startswith(("/", "-"))
        or selected.endswith(("/", "."))
        or "//" in selected
        or ".." in selected
        or "@{" in selected
        or "\\" in selected
        or any(ord(character) < 32 or ord(character) == 127 for character in selected)
        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/+\-]*", selected)
    ):
        raise ModelSourceValidationError("invalid_revision")
    return selected.lower() if COMMIT_PATTERN.fullmatch(selected.lower()) else selected


def normalize_commit(value: str) -> str:
    selected = str(value).strip().lower()
    if not COMMIT_PATTERN.fullmatch(selected):
        raise ModelSourceValidationError("invalid_resolved_commit")
    return selected


def normalize_source_path(value: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise ModelSourceValidationError("unsafe_source_path")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts:
        raise ModelSourceValidationError("unsafe_source_path")
    parts = tuple(part for part in path.parts if part not in {"", "."})
    if (
        not parts
        or len(parts) > 32
        or any(len(part) > 160 for part in parts)
        or len("/".join(parts)) > 512
    ):
        raise ModelSourceValidationError("unsafe_source_path")
    return "/".join(parts)


def validate_ephemeral_token(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ModelSourceValidationError("invalid_ephemeral_token")
    encoded = value.encode("utf-8")
    if (
        not value
        or len(encoded) > MAX_TOKEN_BYTES
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise ModelSourceValidationError("invalid_ephemeral_token")
    return value


def canonical_json_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def evaluate_license_policy(
    license_name: str,
    license_status: str,
) -> dict[str, str]:
    selected = str(license_name or "unknown").strip() or "unknown"
    normalized = selected.lower().replace("_", "-")
    permissive = {
        "apache-2.0",
        "mit",
        "bsd-2-clause",
        "bsd-3-clause",
        "isc",
        "cc0-1.0",
    }
    denied_markers = (
        "non-commercial",
        "noncommercial",
        "cc-by-nc",
        "research-only",
        "no-commercial",
        "proprietary",
    )
    if license_status != "known" or normalized in {"", "unknown"}:
        decision, reason = "review", "license_metadata_missing"
    elif normalized in permissive:
        decision, reason = "allow", "declared_permissive_license"
    elif any(marker in normalized for marker in denied_markers):
        decision, reason = "deny", "declared_restricted_license"
    else:
        decision, reason = "review", "license_requires_manual_policy_review"
    return {
        "spdx": selected,
        "decision": decision,
        "reason": reason,
        "policy_version": LICENSE_POLICY_VERSION,
    }


def source_candidate_id(
    provider: str,
    repository: str,
    requested_revision: str | None,
) -> str:
    """Return a stable id for an untrusted catalog result.

    The id covers only the fields that authorize the later resolution request.
    Popularity, descriptions, and other mutable catalog metadata are display
    hints and cannot change what repository or revision the user confirms.
    """

    selected_provider = str(provider).strip().lower()
    if selected_provider not in {"github", "huggingface"}:
        raise ModelSourceValidationError("invalid_source_provider")
    selected_repository = normalize_repository(repository)
    selected_revision = normalize_revision(requested_revision)
    digest = canonical_json_sha256(
        {
            "provider": selected_provider,
            "repository": selected_repository,
            "requested_revision": selected_revision,
        }
    )
    return f"candidate_{digest[:24]}"


def parse_model_source_reference(
    value: str,
    *,
    provider_hint: str | None = None,
) -> dict[str, str]:
    """Parse a public Hugging Face/GitHub URL or a provider-qualified repo id.

    Only repository roots and optional ``/tree/<revision>`` URLs are accepted.
    Query strings, fragments, credentials, and ambiguous bare repository ids
    are rejected instead of being guessed.
    """

    if not isinstance(value, str):
        raise ModelSourceValidationError("invalid_source_reference")
    selected = value.strip()
    if not selected or selected != value or len(selected) > 2048:
        raise ModelSourceValidationError("invalid_source_reference")
    selected_hint = str(provider_hint or "").strip().lower() or None
    if selected_hint not in {None, "github", "huggingface"}:
        raise ModelSourceValidationError("invalid_source_provider")

    if "://" not in selected:
        if selected_hint is None:
            raise ModelSourceValidationError("provider_required_for_repository_id")
        return {
            "provider": selected_hint,
            "repository": normalize_repository(selected),
            "requested_revision": "main",
        }

    parsed = urlsplit(selected)
    if (
        parsed.scheme != "https"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ModelSourceValidationError("unsafe_source_reference")
    host = (parsed.hostname or "").lower()
    provider_by_host = {
        "github.com": "github",
        "www.github.com": "github",
        "huggingface.co": "huggingface",
        "www.huggingface.co": "huggingface",
    }
    provider = provider_by_host.get(host)
    if provider is None or (selected_hint is not None and selected_hint != provider):
        raise ModelSourceValidationError("unsupported_source_host")
    try:
        parts = [unquote(item) for item in parsed.path.split("/") if item]
    except Exception:
        raise ModelSourceValidationError("invalid_source_reference") from None
    if any("/" in item or "\\" in item or item in {".", ".."} for item in parts):
        raise ModelSourceValidationError("unsafe_source_reference")
    if len(parts) < 2:
        raise ModelSourceValidationError("invalid_source_reference")
    repository_name = parts[1]
    if provider == "github" and repository_name.endswith(".git"):
        repository_name = repository_name[:-4]
    repository = normalize_repository(f"{parts[0]}/{repository_name}")
    revision = "main"
    if len(parts) > 2:
        if parts[2] != "tree" or len(parts) < 4:
            raise ModelSourceValidationError("unsupported_source_reference_path")
        revision = normalize_revision("/".join(parts[3:]))
    return {
        "provider": provider,
        "repository": repository,
        "requested_revision": revision,
    }


@dataclass(frozen=True)
class RemoteSourceFile:
    path: str
    kind: str
    mode: str | None
    size_bytes: int | None
    remote_digest: str
    lfs_sha256: str | None = None

    def __post_init__(self) -> None:
        normalized_path = normalize_source_path(self.path)
        if normalized_path != self.path:
            raise ModelSourceValidationError("source_path_not_normalized")
        if self.kind not in {"blob", "tree", "symlink", "submodule", "executable"}:
            raise ModelSourceValidationError("invalid_source_file_kind")
        if self.mode is not None and self.mode not in {
            "040000",
            "100644",
            "100755",
            "120000",
            "160000",
        }:
            raise ModelSourceValidationError("invalid_source_file_mode")
        if self.size_bytes is not None and (
            isinstance(self.size_bytes, bool)
            or not isinstance(self.size_bytes, int)
            or self.size_bytes < 0
        ):
            raise ModelSourceValidationError("invalid_source_file_size")
        digest = str(self.remote_digest).lower()
        if not _DIGEST_PATTERN.fullmatch(digest):
            raise ModelSourceValidationError("invalid_remote_digest")
        if digest != self.remote_digest:
            raise ModelSourceValidationError("remote_digest_not_normalized")
        if self.lfs_sha256 is not None and not re.fullmatch(
            r"[0-9a-f]{64}", self.lfs_sha256
        ):
            raise ModelSourceValidationError("invalid_lfs_sha256")

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "kind": self.kind,
            "mode": self.mode,
            "size_bytes": self.size_bytes,
            "remote_digest": self.remote_digest,
            "lfs_sha256": self.lfs_sha256,
        }


@dataclass(frozen=True)
class ResolvedSource:
    provider: str
    repository: str
    requested_revision: str
    resolved_commit: str
    license: str
    license_status: str
    tree_reference: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[a-z][a-z0-9_-]{1,31}", self.provider):
            raise ModelSourceValidationError("invalid_source_provider")
        if normalize_repository(self.repository) != self.repository:
            raise ModelSourceValidationError("repository_not_normalized")
        if normalize_revision(self.requested_revision) != self.requested_revision:
            raise ModelSourceValidationError("revision_not_normalized")
        if normalize_commit(self.resolved_commit) != self.resolved_commit:
            raise ModelSourceValidationError("commit_not_normalized")
        if self.license_status not in {"known", "unknown"}:
            raise ModelSourceValidationError("invalid_license_status")
        if (
            not isinstance(self.license, str)
            or not self.license
            or len(self.license) > 200
        ):
            raise ModelSourceValidationError("invalid_license")
        if self.tree_reference is not None and not _DIGEST_PATTERN.fullmatch(
            self.tree_reference
        ):
            raise ModelSourceValidationError("invalid_tree_reference")
        try:
            json.dumps(dict(self.metadata), ensure_ascii=False)
        except (TypeError, ValueError) as exc:
            raise ModelSourceValidationError("invalid_source_metadata") from exc

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "repository": self.repository,
            "requested_revision": self.requested_revision,
            "resolved_commit": self.resolved_commit,
            "license": self.license,
            "license_status": self.license_status,
            "tree_reference": self.tree_reference,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class SourceDocument:
    path: str
    size_bytes: int
    sha256: str
    content: bytes

    def __post_init__(self) -> None:
        if normalize_source_path(self.path) != self.path:
            raise ModelSourceValidationError("document_path_not_normalized")
        if not isinstance(self.content, bytes):
            raise ModelSourceValidationError("document_content_must_be_bytes")
        if self.size_bytes != len(self.content) or self.size_bytes > MAX_DOCUMENT_BYTES:
            raise ModelSourceValidationError("document_size_mismatch")
        if hashlib.sha256(self.content).hexdigest() != self.sha256:
            raise ModelSourceValidationError("document_sha256_mismatch")

    @classmethod
    def from_bytes(cls, path: str, content: bytes) -> SourceDocument:
        selected_path = normalize_source_path(path)
        if len(content) > MAX_DOCUMENT_BYTES:
            raise ModelSourceValidationError("document_size_limit_exceeded")
        return cls(
            path=selected_path,
            size_bytes=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
            content=content,
        )

    def to_dict(self, *, include_content: bool = False) -> dict[str, Any]:
        value: dict[str, Any] = {
            "path": self.path,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
        }
        if include_content:
            value["content_utf8"] = self.content.decode("utf-8")
        return value


@dataclass(frozen=True)
class SourceSnapshot:
    schema_version: str
    snapshot_id: str
    task_id: str
    resolution_id: str
    provider: str
    repository: str
    requested_revision: str
    resolved_commit: str
    license: str
    license_status: str
    files: tuple[RemoteSourceFile, ...]
    documents: tuple[SourceDocument, ...]
    tree_manifest_sha256: str
    execution_policy: str
    created_at_utc: str
    license_policy: Mapping[str, str] = field(default_factory=dict)

    def to_dict(self, *, include_document_content: bool = False) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "snapshot_id": self.snapshot_id,
            "task_id": self.task_id,
            "resolution_id": self.resolution_id,
            "provider": self.provider,
            "repository": self.repository,
            "requested_revision": self.requested_revision,
            "resolved_commit": self.resolved_commit,
            "license": self.license,
            "license_status": self.license_status,
            "files": [item.to_dict() for item in self.files],
            "documents": [
                item.to_dict(include_content=include_document_content)
                for item in self.documents
            ],
            "tree_manifest_sha256": self.tree_manifest_sha256,
            "execution_policy": self.execution_policy,
            "created_at_utc": self.created_at_utc,
            "license_policy": dict(self.license_policy),
        }


@runtime_checkable
class SourceProvider(Protocol):
    provider_id: str

    def resolve(
        self,
        repository: str,
        requested_revision: str | None,
        *,
        token: str | None = None,
    ) -> ResolvedSource: ...

    def list_tree(
        self,
        source: ResolvedSource,
        *,
        token: str | None = None,
    ) -> tuple[RemoteSourceFile, ...]: ...

    def read_document(
        self,
        source: ResolvedSource,
        file: RemoteSourceFile,
        *,
        token: str | None = None,
    ) -> SourceDocument: ...


def tree_manifest_sha256(files: tuple[RemoteSourceFile, ...]) -> str:
    ordered = sorted((item.to_dict() for item in files), key=lambda item: item["path"])
    if len(ordered) > MAX_TREE_FILES:
        raise ModelSourceValidationError("source_tree_file_limit_exceeded")
    if len({item["path"] for item in ordered}) != len(ordered):
        raise ModelSourceValidationError("duplicate_source_path")
    return canonical_json_sha256(ordered)


def is_analysis_document_path(path: str) -> bool:
    normalized = normalize_source_path(path)
    selected = PurePosixPath(normalized)
    basename = selected.name
    lowered = basename.lower()
    if any(part.startswith(".") for part in selected.parts):
        return False
    if lowered.startswith(("readme", "license", "licence", "copying", "notice")):
        return True
    if lowered in _DECLARATIVE_DOCUMENT_NAMES or lowered in _CONFIG_DOCUMENT_NAMES:
        return True
    if lowered.startswith("requirements") and lowered.endswith(".txt"):
        return True
    return len(selected.parts) <= 6 and bool(_TRAINING_SOURCE_NAME.fullmatch(basename))


def collect_source_documents(
    provider: SourceProvider,
    source: ResolvedSource,
    files: tuple[RemoteSourceFile, ...],
    *,
    token: str | None = None,
) -> tuple[SourceDocument, ...]:
    selected_token = validate_ephemeral_token(token)
    candidates = [
        item
        for item in sorted(files, key=lambda value: value.path)
        if item.kind == "blob"
        and item.mode in {None, "100644"}
        and item.lfs_sha256 is None
        and item.size_bytes is not None
        and item.size_bytes <= MAX_DOCUMENT_BYTES
        and is_analysis_document_path(item.path)
    ]
    if len(candidates) > MAX_DOCUMENTS:
        raise ModelSourceValidationError("analysis_document_count_limit_exceeded")
    if sum(int(item.size_bytes or 0) for item in candidates) > MAX_TOTAL_DOCUMENT_BYTES:
        raise ModelSourceValidationError("document_total_size_limit_exceeded")
    documents: list[SourceDocument] = []
    total_bytes = 0
    for item in candidates:
        document = provider.read_document(
            source,
            item,
            token=selected_token,
        )
        if document.path != item.path:
            raise ModelSourceValidationError("document_path_mismatch")
        total_bytes += document.size_bytes
        if total_bytes > MAX_TOTAL_DOCUMENT_BYTES:
            raise ModelSourceValidationError("document_total_size_limit_exceeded")
        documents.append(document)
    return tuple(documents)


def verify_source_snapshot(snapshot: SourceSnapshot) -> tuple[str, ...]:
    errors: list[str] = []
    try:
        normalize_repository(snapshot.repository)
        normalize_revision(snapshot.requested_revision)
        normalize_commit(snapshot.resolved_commit)
    except ModelSourceValidationError as exc:
        errors.append(str(exc))
    if snapshot.schema_version != "0.1":
        errors.append("unsupported_source_snapshot_schema")
    if snapshot.execution_policy != "never_execute_in_l1":
        errors.append("unsafe_execution_policy")
    if snapshot.license_policy:
        expected_license_policy = evaluate_license_policy(
            snapshot.license, snapshot.license_status
        )
        if dict(snapshot.license_policy) != expected_license_policy:
            errors.append("license_policy_mismatch")
    try:
        observed_manifest = tree_manifest_sha256(snapshot.files)
    except ModelSourceValidationError as exc:
        errors.append(str(exc))
    else:
        if observed_manifest != snapshot.tree_manifest_sha256:
            errors.append("tree_manifest_sha256_mismatch")
    if len(snapshot.documents) > MAX_DOCUMENTS:
        errors.append("document_count_limit_exceeded")
    total_bytes = 0
    seen_paths: set[str] = set()
    files_by_path = {item.path: item for item in snapshot.files}
    for document in snapshot.documents:
        total_bytes += document.size_bytes
        if document.path in seen_paths:
            errors.append(f"duplicate_document:{document.path}")
        seen_paths.add(document.path)
        file = files_by_path.get(document.path)
        if file is None:
            errors.append(f"document_not_in_tree:{document.path}")
        elif file.kind != "blob" or file.mode not in {None, "100644"}:
            errors.append(f"unsafe_document_kind:{document.path}")
        elif file.lfs_sha256 is not None:
            errors.append(f"lfs_document_rejected:{document.path}")
        if not is_analysis_document_path(document.path):
            errors.append(f"document_not_allowlisted:{document.path}")
        if hashlib.sha256(document.content).hexdigest() != document.sha256:
            errors.append(f"document_sha256_mismatch:{document.path}")
        if len(document.content) != document.size_bytes:
            errors.append(f"document_size_mismatch:{document.path}")
    if total_bytes > MAX_TOTAL_DOCUMENT_BYTES:
        errors.append("document_total_size_limit_exceeded")
    return tuple(dict.fromkeys(errors))
