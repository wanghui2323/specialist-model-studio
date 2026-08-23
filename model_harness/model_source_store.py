from __future__ import annotations

import base64
import hashlib
import json
import os
import re
from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import parse_qsl, urlsplit
from uuid import uuid4

from .errors import ContractError
from .io_utils import read_json, write_json
from .model_sources import (
    ModelSourceValidationError,
    RemoteSourceFile,
    SourceDocument,
    SourceSnapshot as DomainSourceSnapshot,
    evaluate_license_policy,
    normalize_commit,
    normalize_repository,
    normalize_revision,
    tree_manifest_sha256,
    verify_source_snapshot,
)
from .repository_analysis import RepositoryAnalysis as DomainRepositoryAnalysis


RECORD_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,159}$")
PROVIDERS = {"huggingface", "github"}
_CREDENTIAL_TERMS = {
    "authorization",
    "cookie",
    "credential",
    "credentials",
    "password",
    "privatekey",
    "secret",
    "token",
}
_MODEL_SEARCH_URL = re.compile(r"(?i)\bhttps?://[^\s<>\"']+")
_MODEL_SEARCH_CREDENTIAL_QUERY_KEYS = frozenset(
    {
        "access_token",
        "api_key",
        "apikey",
        "auth_token",
        "authorization",
        "client_secret",
        "github_token",
        "hf_token",
        "password",
        "token",
    }
)
_MODEL_SEARCH_HIGH_CONFIDENCE_CREDENTIAL = re.compile(
    r"(?ix)"
    r"(?:"
    r"(?<![a-z0-9_])(?:github_pat_[a-z0-9_]{20,255}"
    r"|gh[pousr]_[a-z0-9]{20,255}"
    r"|hf_[a-z0-9]{28,255})(?![a-z0-9_])"
    r"|(?:\bauthorization\s*[:=]\s*)?\bbearer\s+"
    r"[a-z0-9._~+/=-]{24,255}(?![a-z0-9._~+/=-])"
    r")"
)


class ModelSourceIntegrityError(ContractError):
    """Raised when a source or binding record no longer matches its digest."""


class StaleBindingIntentError(ContractError):
    """Raised when a prepared binding no longer targets the current revision."""


class StaleTaskSpecRevisionError(ContractError):
    """Raised after an intent is durably aborted because TaskSpec changed."""


SpecRevisionResolver = Callable[[str], int]


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def content_digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def _seal(value: Mapping[str, Any]) -> dict[str, Any]:
    record = deepcopy(dict(value))
    if "content_digest" in record:
        raise ModelSourceIntegrityError("content_digest is store-owned")
    record["content_digest"] = content_digest(record)
    return record


def _verify_seal(
    value: Any,
    *,
    expected_type: str,
    source: str,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ModelSourceIntegrityError(f"invalid record at {source}")
    supplied = value.get("content_digest")
    unsigned = {key: item for key, item in value.items() if key != "content_digest"}
    if not isinstance(supplied, str) or supplied != content_digest(unsigned):
        raise ModelSourceIntegrityError(f"record digest mismatch at {source}")
    if value.get("object_type") != expected_type:
        raise ModelSourceIntegrityError(f"record type mismatch at {source}")
    return deepcopy(value)


def _safe_record_id(value: str, label: str) -> str:
    selected = str(value)
    if not RECORD_ID_PATTERN.fullmatch(selected):
        raise ContractError(f"invalid {label}")
    return selected


def _safe_task_id(value: str) -> str:
    selected = str(value)
    if (
        not selected
        or len(selected) > 160
        or selected in {".", ".."}
        or "\x00" in selected
        or "/" in selected
        or "\\" in selected
        or Path(selected).name != selected
    ):
        raise ContractError("invalid task id")
    return selected


def _safe_text(value: Any, label: str, *, maximum: int = 1024) -> str:
    selected = str(value or "").strip()
    if not selected or len(selected) > maximum or "\x00" in selected:
        raise ContractError(f"invalid {label}")
    return selected


def _credential_key(value: Any) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", "_", str(value).lower()).strip("_")
    joined = normalized.replace("_", "")
    return bool(set(normalized.split("_")) & _CREDENTIAL_TERMS) or any(
        marker in joined
        for marker in ("accesstoken", "authtoken", "apikey", "clientsecret")
    )


def _assert_no_credentials(value: Any, *, ephemeral_secret: str | None = None) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if _credential_key(key):
                raise ContractError("credential fields cannot be persisted")
            _assert_no_credentials(item, ephemeral_secret=ephemeral_secret)
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            _assert_no_credentials(item, ephemeral_secret=ephemeral_secret)
        return
    if ephemeral_secret and isinstance(value, str) and ephemeral_secret in value:
        raise ContractError("credential material cannot be persisted")


def _reject_uri_credentials(value: str | None) -> None:
    if not value:
        return
    parsed = urlsplit(value)
    if parsed.username is not None or parsed.password is not None:
        raise ContractError("credential material cannot be persisted in source URI")
    if any(_credential_key(key) for key, _ in parse_qsl(parsed.query)):
        raise ContractError("credential material cannot be persisted in source URI")


def model_search_contains_credentials(value: str) -> bool:
    """Recognize credential-bearing input without flagging ordinary token words."""

    if _MODEL_SEARCH_HIGH_CONFIDENCE_CREDENTIAL.search(value):
        return True
    for match in _MODEL_SEARCH_URL.finditer(value):
        candidate = match.group(0).rstrip(".,;:!?)]}>")
        try:
            parsed = urlsplit(candidate)
        except ValueError:
            continue
        if parsed.username is not None or parsed.password is not None:
            return True
        for component in (parsed.query, parsed.fragment):
            for key, secret in parse_qsl(component, keep_blank_values=True):
                normalized_key = key.strip().lower().replace("-", "_")
                if (
                    normalized_key in _MODEL_SEARCH_CREDENTIAL_QUERY_KEYS
                    and secret.strip()
                ):
                    return True
    return False


@dataclass(frozen=True)
class SourceResolution:
    schema_version: str
    object_type: str
    resolution_id: str
    task_id: str
    revision: int
    provider: str
    repository: str
    source_uri: str | None
    requested_revision: str
    resolved_commit: str
    details: dict[str, Any]
    semantic_digest: str
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class StoredSourceSnapshotRecord:
    schema_version: str
    object_type: str
    snapshot_id: str
    task_id: str
    revision: int
    resolution_id: str
    resolution_digest: str
    provider: str
    repository: str
    source_uri: str | None
    requested_revision: str
    resolved_commit: str
    license: str
    license_status: str
    files: list[dict[str, Any]]
    tree_manifest_sha256: str
    documents: list[dict[str, Any]]
    documents_digest: str
    execution_policy: str
    details: dict[str, Any]
    semantic_digest: str
    created_at_utc: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class StoredRepositoryAnalysisRecord:
    schema_version: str
    object_type: str
    analysis_id: str
    task_id: str
    revision: int
    snapshot_id: str
    snapshot_digest: str
    status: str
    analysis: dict[str, Any]
    semantic_digest: str
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BindingIntent:
    schema_version: str
    object_type: str
    intent_id: str
    task_id: str
    idempotency_digest: str
    base_spec_revision: int
    base_binding_revision: int
    binding_revision: int
    binding_revision_id: str
    resolution_id: str
    resolution_digest: str
    snapshot_id: str
    snapshot_digest: str
    analysis_id: str
    analysis_digest: str
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ModelBindingRevision:
    schema_version: str
    object_type: str
    binding_revision_id: str
    task_id: str
    revision: int
    supersedes_revision: int | None
    base_spec_revision: int
    intent_id: str
    intent_digest: str
    resolution_id: str
    resolution_digest: str
    snapshot_id: str
    snapshot_digest: str
    analysis_id: str
    analysis_digest: str
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ModelSourceStore:
    """Task-owned immutable model-source records and recoverable bindings.

    Immutable domain records live below ``tasks/<task_id>/model_sources``.
    A binding commit is a small recoverable transaction: an immutable commit
    request authorizes replay, a deterministic binding revision is written, an
    atomically replaced pointer selects it, and an immutable receipt closes it.
    Merely preparing an intent never authorizes recovery to activate it.
    """

    SCHEMA_VERSION = "0.1"

    def __init__(self, workspace_root: str | Path) -> None:
        self.root = Path(workspace_root).expanduser().resolve()
        tasks_candidate = self.root / "tasks"
        if tasks_candidate.is_symlink():
            raise ContractError("tasks directory cannot be a symlink")
        tasks_candidate.mkdir(parents=True, exist_ok=True)
        self.tasks_dir = tasks_candidate.resolve()
        self._lock = RLock()

    def create_search_record(
        self,
        task_id: str,
        *,
        base_spec_revision: int,
        query_plan: Mapping[str, Any],
        providers: Sequence[str],
        candidates: Sequence[Mapping[str, Any]],
        provider_errors: Sequence[Mapping[str, Any]] = (),
        auth_tokens: Sequence[str | None] = (),
    ) -> dict[str, Any]:
        task_id = _safe_task_id(task_id)
        if (
            isinstance(base_spec_revision, bool)
            or not isinstance(base_spec_revision, int)
            or base_spec_revision < 1
        ):
            raise ContractError("base_spec_revision must be a positive integer")
        selected_providers = [str(item).strip().lower() for item in providers]
        if (
            not selected_providers
            or len(set(selected_providers)) != len(selected_providers)
            or any(item not in PROVIDERS for item in selected_providers)
        ):
            raise ContractError("invalid source search providers")
        selected_query_plan = deepcopy(dict(query_plan))
        for key in ("user_query", "effective_query"):
            value = selected_query_plan.get(key)
            if value is not None and (
                not isinstance(value, str) or model_search_contains_credentials(value)
            ):
                raise ContractError("credential material cannot be persisted in search query")
        selected_candidates = [deepcopy(dict(item)) for item in candidates]
        selected_errors = [deepcopy(dict(item)) for item in provider_errors]
        if len(selected_candidates) > 20:
            raise ContractError("too many source search candidates")
        seen_candidate_ids: set[str] = set()
        for candidate in selected_candidates:
            candidate_id = _safe_record_id(
                str(candidate.get("candidate_id") or ""), "candidate id"
            )
            provider = str(candidate.get("provider") or "").strip().lower()
            if provider not in selected_providers:
                raise ContractError("candidate provider was not searched")
            try:
                repository = normalize_repository(str(candidate.get("repository") or ""))
                requested_revision = normalize_revision(
                    str(candidate.get("requested_revision") or "main")
                )
            except ModelSourceValidationError as error:
                raise ContractError(str(error)) from error
            if candidate_id in seen_candidate_ids:
                raise ContractError("duplicate source search candidate")
            seen_candidate_ids.add(candidate_id)
            candidate["candidate_id"] = candidate_id
            candidate["provider"] = provider
            candidate["repository"] = repository
            candidate["requested_revision"] = requested_revision
            _reject_uri_credentials(str(candidate.get("source_uri") or ""))
        ephemeral = [item for item in auth_tokens if item]
        _assert_no_credentials(selected_query_plan)
        _assert_no_credentials(selected_candidates)
        _assert_no_credentials(selected_errors)
        for secret in ephemeral:
            _assert_no_credentials(selected_query_plan, ephemeral_secret=secret)
            _assert_no_credentials(selected_candidates, ephemeral_secret=secret)
            _assert_no_credentials(selected_errors, ephemeral_secret=secret)
        semantic = {
            "task_id": task_id,
            "base_spec_revision": base_spec_revision,
            "query_plan": selected_query_plan,
            "providers": selected_providers,
            "candidates": selected_candidates,
            "provider_errors": selected_errors,
            "execution_policy": "catalog_metadata_only_no_download_no_execution",
        }
        semantic_digest = content_digest(semantic)
        with self._lock:
            existing = self._find_semantic(
                self.list_search_records(task_id), semantic_digest
            )
            if existing is not None:
                return existing
            revision = self._next_revision(self.list_search_records(task_id))
            search_id = f"source-search-r{revision}-{semantic_digest[:12]}"
            record = _seal(
                {
                    "schema_version": self.SCHEMA_VERSION,
                    "object_type": "source_search_record",
                    "search_id": search_id,
                    "revision": revision,
                    **semantic,
                    "semantic_digest": semantic_digest,
                    "created_at": _utc_now(),
                }
            )
            self._write_immutable(
                self._record_path(task_id, "searches", search_id),
                record,
                expected_type="source_search_record",
            )
            return deepcopy(record)

    def create_resolution(
        self,
        task_id: str,
        *,
        provider: str,
        repository: str,
        requested_revision: str,
        resolved_commit: str,
        source_uri: str | None = None,
        details: Mapping[str, Any] | None = None,
        auth_token: str | None = None,
    ) -> dict[str, Any]:
        task_id = _safe_task_id(task_id)
        selected_provider = str(provider).strip().lower()
        if selected_provider not in PROVIDERS:
            raise ContractError("provider must be huggingface or github")
        try:
            selected_repository = normalize_repository(repository)
            selected_requested = normalize_revision(requested_revision)
            selected_commit = normalize_commit(resolved_commit)
        except ModelSourceValidationError as error:
            raise ContractError(str(error)) from error
        selected_uri = (
            _safe_text(source_uri, "source URI", maximum=2048)
            if source_uri is not None
            else None
        )
        _reject_uri_credentials(selected_uri)
        if auth_token is not None and not isinstance(auth_token, str):
            raise ContractError("auth_token must be text")
        if auth_token and any(
            auth_token in selected
            for selected in (
                selected_repository,
                selected_requested,
                selected_uri or "",
            )
        ):
            raise ContractError("credential material cannot be persisted")
        selected_details = deepcopy(dict(details or {}))
        _assert_no_credentials(
            selected_details,
            ephemeral_secret=auth_token if auth_token else None,
        )
        semantic = {
            "task_id": task_id,
            "provider": selected_provider,
            "repository": selected_repository,
            "source_uri": selected_uri,
            "requested_revision": selected_requested,
            "resolved_commit": selected_commit,
            "details": selected_details,
        }
        semantic_digest = content_digest(semantic)
        with self._lock:
            existing = self._find_semantic(
                self.list_resolutions(task_id), semantic_digest
            )
            if existing is not None:
                return existing
            revision = self._next_revision(self.list_resolutions(task_id))
            resolution = SourceResolution(
                schema_version=self.SCHEMA_VERSION,
                object_type="source_resolution",
                resolution_id=f"source-resolution-r{revision}-{semantic_digest[:12]}",
                task_id=task_id,
                revision=revision,
                provider=selected_provider,
                repository=selected_repository,
                source_uri=selected_uri,
                requested_revision=selected_requested,
                resolved_commit=selected_commit,
                details=selected_details,
                semantic_digest=semantic_digest,
                created_at=_utc_now(),
            )
            record = _seal(resolution.to_dict())
            self._write_immutable(
                self._record_path(
                    task_id, "resolutions", record["resolution_id"]
                ),
                record,
                expected_type="source_resolution",
            )
            return deepcopy(record)

    def create_snapshot(
        self,
        task_id: str,
        *,
        resolution_id: str,
        files: Sequence[RemoteSourceFile | Mapping[str, Any]],
        license: str,
        license_status: str,
        documents: Sequence[SourceDocument | Mapping[str, Any]] = (),
        details: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        task_id = _safe_task_id(task_id)
        resolution = self.get_resolution(task_id, resolution_id)
        domain_files = self._normalize_files(files)
        selected_files = [item.to_dict() for item in domain_files]
        domain_documents = self._normalize_documents(documents, domain_files)
        selected_documents = [
            {
                "path": item.path,
                "size_bytes": item.size_bytes,
                "sha256": item.sha256,
                "content_base64": base64.b64encode(item.content).decode("ascii"),
            }
            for item in domain_documents
        ]
        selected_license = _safe_text(license, "license", maximum=256)
        selected_license_status = str(license_status).strip()
        if selected_license_status not in {"known", "unknown"}:
            raise ContractError("license_status must be known or unknown")
        selected_details = deepcopy(dict(details or {}))
        _assert_no_credentials(selected_details)
        expected_license_policy = evaluate_license_policy(
            selected_license, selected_license_status
        )
        supplied_license_policy = selected_details.get("license_policy")
        if (
            supplied_license_policy is not None
            and supplied_license_policy != expected_license_policy
        ):
            raise ContractError("license policy does not match source license")
        selected_details["license_policy"] = expected_license_policy
        manifest_digest = tree_manifest_sha256(domain_files)
        semantic = {
            "task_id": task_id,
            "resolution_id": resolution["resolution_id"],
            "resolution_digest": resolution["content_digest"],
            "provider": resolution["provider"],
            "repository": resolution["repository"],
            "source_uri": resolution["source_uri"],
            "requested_revision": resolution["requested_revision"],
            "resolved_commit": resolution["resolved_commit"],
            "license": selected_license,
            "license_status": selected_license_status,
            "files": selected_files,
            "documents": selected_documents,
            "tree_manifest_sha256": manifest_digest,
            "execution_policy": "never_execute_in_l1",
            "details": selected_details,
        }
        semantic_digest = content_digest(semantic)
        with self._lock:
            existing = self._find_semantic(
                self.list_snapshots(task_id), semantic_digest
            )
            if existing is not None:
                return existing
            revision = self._next_revision(self.list_snapshots(task_id))
            snapshot = StoredSourceSnapshotRecord(
                schema_version=self.SCHEMA_VERSION,
                object_type="source_snapshot",
                snapshot_id=f"source-snapshot-r{revision}-{semantic_digest[:12]}",
                task_id=task_id,
                revision=revision,
                resolution_id=resolution["resolution_id"],
                resolution_digest=resolution["content_digest"],
                provider=resolution["provider"],
                repository=resolution["repository"],
                source_uri=resolution["source_uri"],
                requested_revision=resolution["requested_revision"],
                resolved_commit=resolution["resolved_commit"],
                license=selected_license,
                license_status=selected_license_status,
                files=selected_files,
                tree_manifest_sha256=manifest_digest,
                documents=selected_documents,
                documents_digest=content_digest(selected_documents),
                execution_policy="never_execute_in_l1",
                details=selected_details,
                semantic_digest=semantic_digest,
                created_at_utc=_utc_now(),
            )
            record = _seal(snapshot.to_dict())
            self._write_immutable(
                self._record_path(task_id, "snapshots", record["snapshot_id"]),
                record,
                expected_type="source_snapshot",
            )
            return deepcopy(record)

    def create_analysis(
        self,
        task_id: str,
        *,
        snapshot_id: str,
        analysis: DomainRepositoryAnalysis | Mapping[str, Any],
    ) -> dict[str, Any]:
        task_id = _safe_task_id(task_id)
        snapshot = self.get_snapshot(task_id, snapshot_id)
        if isinstance(analysis, DomainRepositoryAnalysis):
            selected_analysis = deepcopy(analysis.to_dict())
        elif isinstance(analysis, Mapping):
            selected_analysis = deepcopy(dict(analysis))
        else:
            raise ContractError("analysis must be a RepositoryAnalysis")
        _assert_no_credentials(selected_analysis)
        status = str(selected_analysis.get("status", "")).strip()
        if not status:
            raise ContractError("RepositoryAnalysis requires status")
        domain_analysis_id = _safe_record_id(
            str(selected_analysis.get("analysis_id", "")),
            "repository analysis id",
        )
        if selected_analysis.get("task_id") != task_id:
            raise ContractError("RepositoryAnalysis task identity mismatch")
        if selected_analysis.get("source_snapshot_id") != snapshot["snapshot_id"]:
            raise ContractError("RepositoryAnalysis does not describe snapshot")
        if selected_analysis.get("resolved_commit") != snapshot["resolved_commit"]:
            raise ContractError("RepositoryAnalysis commit does not match snapshot")
        semantic = {
            "task_id": task_id,
            "snapshot_id": snapshot["snapshot_id"],
            "snapshot_digest": snapshot["content_digest"],
            "analysis": selected_analysis,
        }
        semantic_digest = content_digest(semantic)
        with self._lock:
            existing = self._find_semantic(
                self.list_analyses(task_id), semantic_digest
            )
            if existing is not None:
                return existing
            revision = self._next_revision(self.list_analyses(task_id))
            repository_analysis = StoredRepositoryAnalysisRecord(
                schema_version=self.SCHEMA_VERSION,
                object_type="repository_analysis",
                analysis_id=domain_analysis_id,
                task_id=task_id,
                revision=revision,
                snapshot_id=snapshot["snapshot_id"],
                snapshot_digest=snapshot["content_digest"],
                status=status,
                analysis=selected_analysis,
                semantic_digest=semantic_digest,
                created_at=_utc_now(),
            )
            record = _seal(repository_analysis.to_dict())
            self._write_immutable(
                self._record_path(task_id, "analyses", record["analysis_id"]),
                record,
                expected_type="repository_analysis",
            )
            return deepcopy(record)

    def prepare_binding_intent(
        self,
        task_id: str,
        *,
        snapshot_id: str,
        analysis_id: str,
        idempotency_key: str,
        base_spec_revision: int,
        base_binding_revision: int | None = None,
    ) -> dict[str, Any]:
        task_id = _safe_task_id(task_id)
        key = _safe_text(idempotency_key, "idempotency key", maximum=512)
        selected_spec_revision = self._validate_spec_revision(base_spec_revision)
        snapshot = self.get_snapshot(task_id, snapshot_id)
        analysis = self.get_analysis(task_id, analysis_id)
        if analysis["snapshot_id"] != snapshot["snapshot_id"]:
            raise ContractError("RepositoryAnalysis does not describe snapshot")
        current = self.current_binding(task_id)
        current_revision = int(current["revision"]) if current else 0
        if base_binding_revision is None:
            selected_base = current_revision
        else:
            if (
                isinstance(base_binding_revision, bool)
                or not isinstance(base_binding_revision, int)
                or base_binding_revision < 0
            ):
                raise ContractError("base_binding_revision must be a non-negative integer")
            selected_base = base_binding_revision
        if selected_base != current_revision:
            raise StaleBindingIntentError("current binding revision changed")
        idempotency_digest = content_digest(
            {"task_id": task_id, "idempotency_key": key}
        )
        resolution = self.get_resolution(task_id, snapshot["resolution_id"])
        semantic = {
            "task_id": task_id,
            "idempotency_digest": idempotency_digest,
            "base_spec_revision": selected_spec_revision,
            "base_binding_revision": selected_base,
            "binding_revision": selected_base + 1,
            "resolution_id": resolution["resolution_id"],
            "resolution_digest": resolution["content_digest"],
            "snapshot_id": snapshot["snapshot_id"],
            "snapshot_digest": snapshot["content_digest"],
            "analysis_id": analysis["analysis_id"],
            "analysis_digest": analysis["content_digest"],
        }
        semantic_digest = content_digest(semantic)
        intent_id = f"binding-intent-{idempotency_digest[:20]}"
        binding_revision_id = (
            f"model-binding-r{selected_base + 1}-{semantic_digest[:12]}"
        )
        intent = BindingIntent(
            schema_version=self.SCHEMA_VERSION,
            object_type="binding_intent",
            intent_id=intent_id,
            task_id=task_id,
            idempotency_digest=idempotency_digest,
            base_spec_revision=selected_spec_revision,
            base_binding_revision=selected_base,
            binding_revision=selected_base + 1,
            binding_revision_id=binding_revision_id,
            resolution_id=resolution["resolution_id"],
            resolution_digest=resolution["content_digest"],
            snapshot_id=snapshot["snapshot_id"],
            snapshot_digest=snapshot["content_digest"],
            analysis_id=analysis["analysis_id"],
            analysis_digest=analysis["content_digest"],
            created_at=_utc_now(),
        )
        record = _seal(intent.to_dict())
        path = self._intent_record_path(task_id, intent_id, "intent.json")
        with self._lock:
            if path.is_file():
                existing = self._read_record(path, "binding_intent", task_id)
                comparable = (
                    "task_id",
                    "idempotency_digest",
                    "base_spec_revision",
                    "base_binding_revision",
                    "binding_revision",
                    "binding_revision_id",
                    "resolution_id",
                    "resolution_digest",
                    "snapshot_id",
                    "snapshot_digest",
                    "analysis_id",
                    "analysis_digest",
                )
                if any(existing.get(key) != record.get(key) for key in comparable):
                    raise ModelSourceIntegrityError(
                        "idempotency key was reused for a different binding"
                    )
                return existing
            self._write_immutable(
                path,
                record,
                expected_type="binding_intent",
            )
            return deepcopy(record)

    def request_binding_commit(
        self,
        task_id: str,
        intent_id: str,
        *,
        expected_intent_digest: str,
    ) -> dict[str, Any]:
        task_id = _safe_task_id(task_id)
        intent_id = _safe_record_id(intent_id, "binding intent id")
        with self._lock:
            envelope = self.get_binding_intent(task_id, intent_id)
            intent = envelope["intent"]
            if envelope["status"] == "aborted_spec_changed":
                raise StaleTaskSpecRevisionError(
                    "binding intent was aborted because TaskSpec changed"
                )
            if envelope["status"] == "aborted_binding_changed":
                raise StaleBindingIntentError(
                    "binding intent was aborted because current binding changed"
                )
            if expected_intent_digest != intent["content_digest"]:
                raise ModelSourceIntegrityError("binding intent digest does not match")
            self._verify_intent_references(task_id, intent)
            request_path = self._intent_record_path(
                task_id, intent_id, "commit_request.json"
            )
            if not request_path.is_file():
                request = _seal(
                    {
                        "schema_version": self.SCHEMA_VERSION,
                        "object_type": "binding_commit_request",
                        "task_id": task_id,
                        "intent_id": intent_id,
                        "intent_digest": intent["content_digest"],
                        "base_spec_revision": intent["base_spec_revision"],
                        "base_binding_revision": intent["base_binding_revision"],
                        "binding_revision_id": intent["binding_revision_id"],
                        "requested_at": _utc_now(),
                    }
                )
                self._write_immutable(
                    request_path,
                    request,
                    expected_type="binding_commit_request",
                )
            return self.get_binding_intent(task_id, intent_id)

    def commit_binding_intent(
        self,
        task_id: str,
        intent_id: str,
        *,
        expected_intent_digest: str,
        resolve_spec_revision: SpecRevisionResolver | None = None,
        current_spec_revision: int | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            self.request_binding_commit(
                task_id,
                intent_id,
                expected_intent_digest=expected_intent_digest,
            )
            return self._apply_binding_intent(
                task_id,
                intent_id,
                resolve_spec_revision=resolve_spec_revision,
                current_spec_revision=current_spec_revision,
            )

    def recover_pending_commits(
        self,
        task_id: str | None = None,
        *,
        resolve_spec_revision: SpecRevisionResolver | None = None,
        current_spec_revision: int | None = None,
    ) -> list[dict[str, Any]]:
        if task_id is None and current_spec_revision is not None:
            raise ContractError(
                "current_spec_revision requires a single task_id during recovery"
            )
        task_ids = [task_id] if task_id is not None else self._task_ids()
        recovered: list[dict[str, Any]] = []
        with self._lock:
            for selected_task_id in task_ids:
                selected_task_id = _safe_task_id(selected_task_id)
                intent_root = self._collection_dir(
                    selected_task_id, "binding_intents"
                )
                for directory in sorted(intent_root.iterdir()):
                    if not directory.is_dir() or directory.is_symlink():
                        if directory.is_symlink():
                            raise ContractError("binding intent directory cannot be a symlink")
                        continue
                    intent_id = _safe_record_id(directory.name, "binding intent id")
                    envelope = self.get_binding_intent(
                        selected_task_id, intent_id
                    )
                    if envelope["status"] == "commit_requested":
                        try:
                            recovered.append(
                                self._apply_binding_intent(
                                    selected_task_id,
                                    intent_id,
                                    resolve_spec_revision=resolve_spec_revision,
                                    current_spec_revision=current_spec_revision,
                                )
                            )
                        except (StaleTaskSpecRevisionError, StaleBindingIntentError):
                            continue
        return recovered

    def get_resolution(self, task_id: str, resolution_id: str) -> dict[str, Any]:
        task_id = _safe_task_id(task_id)
        resolution_id = _safe_record_id(resolution_id, "source resolution id")
        resolution = self._read_record(
            self._record_path(task_id, "resolutions", resolution_id),
            "source_resolution",
            task_id,
        )
        if resolution.get("resolution_id") != resolution_id:
            raise ModelSourceIntegrityError("SourceResolution identity mismatch")
        return resolution

    def get_search_record(self, task_id: str, search_id: str) -> dict[str, Any]:
        task_id = _safe_task_id(task_id)
        search_id = _safe_record_id(search_id, "source search id")
        record = self._read_record(
            self._record_path(task_id, "searches", search_id),
            "source_search_record",
            task_id,
        )
        if record.get("search_id") != search_id:
            raise ModelSourceIntegrityError("SourceSearchRecord identity mismatch")
        return record

    def get_snapshot(self, task_id: str, snapshot_id: str) -> dict[str, Any]:
        task_id = _safe_task_id(task_id)
        snapshot_id = _safe_record_id(snapshot_id, "source snapshot id")
        snapshot = self._read_record(
            self._record_path(task_id, "snapshots", snapshot_id),
            "source_snapshot",
            task_id,
        )
        if snapshot.get("snapshot_id") != snapshot_id:
            raise ModelSourceIntegrityError("SourceSnapshot identity mismatch")
        resolution = self.get_resolution(task_id, str(snapshot["resolution_id"]))
        expected = {
            "resolution_digest": resolution["content_digest"],
            "provider": resolution["provider"],
            "repository": resolution["repository"],
            "source_uri": resolution["source_uri"],
            "requested_revision": resolution["requested_revision"],
            "resolved_commit": resolution["resolved_commit"],
        }
        if any(snapshot.get(key) != value for key, value in expected.items()):
            raise ModelSourceIntegrityError("SourceSnapshot resolution lineage changed")
        if content_digest(snapshot.get("documents")) != snapshot.get(
            "documents_digest"
        ):
            raise ModelSourceIntegrityError("SourceSnapshot documents changed")
        self._domain_snapshot_from_record(snapshot)
        return snapshot

    def load_source_snapshot(
        self, task_id: str, snapshot_id: str
    ) -> DomainSourceSnapshot:
        """Rehydrate the one public provider/analyzer SourceSnapshot type."""

        return self._domain_snapshot_from_record(
            self.get_snapshot(task_id, snapshot_id)
        )

    def get_analysis(self, task_id: str, analysis_id: str) -> dict[str, Any]:
        task_id = _safe_task_id(task_id)
        analysis_id = _safe_record_id(analysis_id, "repository analysis id")
        analysis = self._read_record(
            self._record_path(task_id, "analyses", analysis_id),
            "repository_analysis",
            task_id,
        )
        if analysis.get("analysis_id") != analysis_id:
            raise ModelSourceIntegrityError("RepositoryAnalysis identity mismatch")
        snapshot = self.get_snapshot(task_id, str(analysis["snapshot_id"]))
        if analysis.get("snapshot_digest") != snapshot["content_digest"]:
            raise ModelSourceIntegrityError(
                "RepositoryAnalysis snapshot lineage changed"
            )
        return analysis

    def get_binding_revision(
        self, task_id: str, binding_revision_id: str
    ) -> dict[str, Any]:
        task_id = _safe_task_id(task_id)
        binding_revision_id = _safe_record_id(
            binding_revision_id, "model binding revision id"
        )
        binding = self._read_record(
            self._record_path(task_id, "bindings", binding_revision_id),
            "model_binding_revision",
            task_id,
        )
        if binding.get("binding_revision_id") != binding_revision_id:
            raise ModelSourceIntegrityError("ModelBindingRevision identity mismatch")
        self._verify_binding_references(task_id, binding)
        return binding

    def get_binding_intent(
        self, task_id: str, intent_id: str
    ) -> dict[str, Any]:
        task_id = _safe_task_id(task_id)
        intent_id = _safe_record_id(intent_id, "binding intent id")
        intent = self._read_record(
            self._intent_record_path(task_id, intent_id, "intent.json"),
            "binding_intent",
            task_id,
        )
        if intent.get("intent_id") != intent_id:
            raise ModelSourceIntegrityError("BindingIntent identity mismatch")
        request_path = self._intent_record_path(
            task_id, intent_id, "commit_request.json"
        )
        receipt_path = self._intent_record_path(
            task_id, intent_id, "commit_receipt.json"
        )
        abort_path = self._intent_record_path(task_id, intent_id, "abort.json")
        request = (
            self._read_record(
                request_path,
                "binding_commit_request",
                task_id,
            )
            if request_path.is_file()
            else None
        )
        receipt = (
            self._read_record(
                receipt_path,
                "binding_commit_receipt",
                task_id,
            )
            if receipt_path.is_file()
            else None
        )
        abort = (
            self._read_record(
                abort_path,
                "binding_abort_record",
                task_id,
            )
            if abort_path.is_file()
            else None
        )
        if request and (
            request.get("intent_id") != intent_id
            or request.get("intent_digest") != intent["content_digest"]
            or request.get("binding_revision_id") != intent["binding_revision_id"]
            or request.get("base_spec_revision") != intent["base_spec_revision"]
            or request.get("base_binding_revision")
            != intent["base_binding_revision"]
        ):
            raise ModelSourceIntegrityError("commit request lineage changed")
        if receipt:
            if request is None:
                raise ModelSourceIntegrityError("commit receipt has no request")
            if (
                receipt.get("intent_id") != intent_id
                or receipt.get("intent_digest") != intent["content_digest"]
                or receipt.get("request_digest") != request["content_digest"]
                or receipt.get("binding_revision_id")
                != intent["binding_revision_id"]
                or receipt.get("base_spec_revision")
                != intent["base_spec_revision"]
                or receipt.get("base_binding_revision")
                != intent["base_binding_revision"]
            ):
                raise ModelSourceIntegrityError("commit receipt lineage changed")
        if abort:
            if request is None:
                raise ModelSourceIntegrityError("binding abort has no commit request")
            if receipt is not None:
                raise ModelSourceIntegrityError("binding intent is both aborted and committed")
            if (
                abort.get("intent_id") != intent_id
                or abort.get("intent_digest") != intent["content_digest"]
                or abort.get("request_digest") != request["content_digest"]
                or abort.get("binding_revision_id")
                != intent["binding_revision_id"]
                or abort.get("base_spec_revision")
                != intent["base_spec_revision"]
                or abort.get("base_binding_revision")
                != intent["base_binding_revision"]
                or abort.get("reason")
                not in {"aborted_spec_changed", "aborted_binding_changed"}
            ):
                raise ModelSourceIntegrityError("binding abort lineage changed")
            if abort["reason"] == "aborted_spec_changed" and (
                abort.get("observed_spec_revision") is None
                or abort.get("observed_binding_revision") is not None
            ):
                raise ModelSourceIntegrityError("binding spec abort evidence changed")
            if abort["reason"] == "aborted_binding_changed" and (
                abort.get("observed_binding_revision") is None
                or abort.get("observed_spec_revision") is not None
            ):
                raise ModelSourceIntegrityError("binding revision abort evidence changed")
        status = (
            "committed"
            if receipt
            else str(abort["reason"])
            if abort
            else "commit_requested"
            if request
            else "prepared"
        )
        return {
            "status": status,
            "intent": intent,
            "commit_request": request,
            "commit_receipt": receipt,
            "abort": abort,
        }

    def current_binding(self, task_id: str) -> dict[str, Any] | None:
        task_id = _safe_task_id(task_id)
        path = self._model_source_root(task_id) / "current_binding.json"
        if not path.is_file():
            if path.is_symlink():
                raise ContractError("current binding pointer cannot be a symlink")
            return None
        pointer = self._read_record(path, "current_model_binding", task_id)
        binding = self.get_binding_revision(
            task_id, str(pointer["binding_revision_id"])
        )
        if (
            pointer.get("binding_digest") != binding["content_digest"]
            or pointer.get("revision") != binding["revision"]
            or pointer.get("base_spec_revision") != binding["base_spec_revision"]
        ):
            raise ModelSourceIntegrityError("current binding pointer changed")
        return binding

    def list_resolutions(self, task_id: str) -> list[dict[str, Any]]:
        return self._list_records(task_id, "resolutions", "source_resolution")

    def list_search_records(self, task_id: str) -> list[dict[str, Any]]:
        return self._list_records(task_id, "searches", "source_search_record")

    def list_snapshots(self, task_id: str) -> list[dict[str, Any]]:
        records = self._list_records(task_id, "snapshots", "source_snapshot")
        return [self.get_snapshot(task_id, item["snapshot_id"]) for item in records]

    def list_analyses(self, task_id: str) -> list[dict[str, Any]]:
        records = self._list_records(task_id, "analyses", "repository_analysis")
        return [self.get_analysis(task_id, item["analysis_id"]) for item in records]

    def list_binding_revisions(self, task_id: str) -> list[dict[str, Any]]:
        records = self._list_records(
            task_id, "bindings", "model_binding_revision"
        )
        return [
            self.get_binding_revision(task_id, item["binding_revision_id"])
            for item in records
        ]

    def binding_context(
        self,
        task_id: str,
        binding_revision_id: str | None = None,
    ) -> dict[str, Any] | None:
        binding = (
            self.get_binding_revision(task_id, binding_revision_id)
            if binding_revision_id is not None
            else self.current_binding(task_id)
        )
        if binding is None:
            return None
        snapshot = self.get_snapshot(task_id, str(binding["snapshot_id"]))
        return {
            "binding": binding,
            "resolution": self.get_resolution(
                task_id, str(binding["resolution_id"])
            ),
            "snapshot": snapshot,
            "source_snapshot": self._domain_snapshot_from_record(snapshot),
            "analysis": self.get_analysis(
                task_id, str(binding["analysis_id"])
            ),
        }

    def _apply_binding_intent(
        self,
        task_id: str,
        intent_id: str,
        *,
        resolve_spec_revision: SpecRevisionResolver | None,
        current_spec_revision: int | None,
    ) -> dict[str, Any]:
        envelope = self.get_binding_intent(task_id, intent_id)
        intent = envelope["intent"]
        request = envelope["commit_request"]
        receipt = envelope["commit_receipt"]
        if envelope["status"] == "aborted_spec_changed":
            raise StaleTaskSpecRevisionError(
                "binding intent was aborted because TaskSpec changed"
            )
        if envelope["status"] == "aborted_binding_changed":
            raise StaleBindingIntentError(
                "binding intent was aborted because current binding changed"
            )
        if request is None:
            raise ContractError("binding commit was not requested")
        if receipt is not None:
            binding = self.get_binding_revision(
                task_id, str(receipt["binding_revision_id"])
            )
            if receipt.get("binding_digest") != binding["content_digest"]:
                raise ModelSourceIntegrityError("commit receipt binding digest changed")
            return binding

        self._verify_intent_references(task_id, intent)
        observed_spec_revision = self._resolve_current_spec_revision(
            task_id,
            resolve_spec_revision=resolve_spec_revision,
            current_spec_revision=current_spec_revision,
        )
        if observed_spec_revision != int(intent["base_spec_revision"]):
            self._record_spec_abort(
                task_id,
                intent,
                request,
                observed_spec_revision=observed_spec_revision,
            )
            raise StaleTaskSpecRevisionError(
                "TaskSpec changed after binding intent preparation"
            )
        current = self.current_binding(task_id)
        current_revision = int(current["revision"]) if current else 0
        if current and current["binding_revision_id"] == intent["binding_revision_id"]:
            binding = current
        else:
            if current_revision != int(intent["base_binding_revision"]):
                self._record_binding_abort(
                    task_id,
                    intent,
                    request,
                    observed_binding_revision=current_revision,
                )
                raise StaleBindingIntentError("current binding revision changed")
            binding = _seal(
                ModelBindingRevision(
                    schema_version=self.SCHEMA_VERSION,
                    object_type="model_binding_revision",
                    binding_revision_id=str(intent["binding_revision_id"]),
                    task_id=task_id,
                    revision=int(intent["binding_revision"]),
                    supersedes_revision=(
                        current_revision if current_revision > 0 else None
                    ),
                    base_spec_revision=int(intent["base_spec_revision"]),
                    intent_id=str(intent["intent_id"]),
                    intent_digest=str(intent["content_digest"]),
                    resolution_id=str(intent["resolution_id"]),
                    resolution_digest=str(intent["resolution_digest"]),
                    snapshot_id=str(intent["snapshot_id"]),
                    snapshot_digest=str(intent["snapshot_digest"]),
                    analysis_id=str(intent["analysis_id"]),
                    analysis_digest=str(intent["analysis_digest"]),
                    created_at=str(request["requested_at"]),
                ).to_dict()
            )
            self._write_immutable(
                self._record_path(
                    task_id, "bindings", binding["binding_revision_id"]
                ),
                binding,
                expected_type="model_binding_revision",
            )
            self._verify_binding_references(task_id, binding)
            pointer = _seal(
                {
                    "schema_version": self.SCHEMA_VERSION,
                    "object_type": "current_model_binding",
                    "task_id": task_id,
                    "binding_revision_id": binding["binding_revision_id"],
                    "binding_digest": binding["content_digest"],
                    "revision": binding["revision"],
                    "base_spec_revision": binding["base_spec_revision"],
                    "updated_at": _utc_now(),
                }
            )
            pointer_path = self._model_source_root(task_id) / "current_binding.json"
            if pointer_path.is_symlink():
                raise ContractError("current binding pointer cannot be a symlink")
            write_json(pointer_path, pointer)

        receipt_record = _seal(
            {
                "schema_version": self.SCHEMA_VERSION,
                "object_type": "binding_commit_receipt",
                "task_id": task_id,
                "intent_id": intent_id,
                "intent_digest": intent["content_digest"],
                "request_digest": request["content_digest"],
                "binding_revision_id": binding["binding_revision_id"],
                "binding_digest": binding["content_digest"],
                "base_spec_revision": intent["base_spec_revision"],
                "base_binding_revision": intent["base_binding_revision"],
                "committed_at": _utc_now(),
            }
        )
        self._write_immutable(
            self._intent_record_path(task_id, intent_id, "commit_receipt.json"),
            receipt_record,
            expected_type="binding_commit_receipt",
        )
        return deepcopy(binding)

    def _resolve_current_spec_revision(
        self,
        task_id: str,
        *,
        resolve_spec_revision: SpecRevisionResolver | None,
        current_spec_revision: int | None,
    ) -> int:
        if resolve_spec_revision is not None and current_spec_revision is not None:
            raise ContractError(
                "provide either resolve_spec_revision or current_spec_revision"
            )
        if resolve_spec_revision is not None:
            try:
                observed = resolve_spec_revision(task_id)
            except Exception as error:
                raise ContractError("could not resolve current TaskSpec revision") from error
        elif current_spec_revision is not None:
            observed = current_spec_revision
        else:
            raise ContractError("current TaskSpec revision is required")
        return self._validate_spec_revision(observed)

    @staticmethod
    def _validate_spec_revision(value: Any) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ContractError("base_spec_revision must be a positive integer")
        return value

    def _record_spec_abort(
        self,
        task_id: str,
        intent: Mapping[str, Any],
        request: Mapping[str, Any],
        *,
        observed_spec_revision: int,
    ) -> None:
        abort = _seal(
            {
                "schema_version": self.SCHEMA_VERSION,
                "object_type": "binding_abort_record",
                "task_id": task_id,
                "intent_id": intent["intent_id"],
                "intent_digest": intent["content_digest"],
                "request_digest": request["content_digest"],
                "binding_revision_id": intent["binding_revision_id"],
                "base_spec_revision": intent["base_spec_revision"],
                "base_binding_revision": intent["base_binding_revision"],
                "observed_spec_revision": observed_spec_revision,
                "observed_binding_revision": None,
                "reason": "aborted_spec_changed",
                "aborted_at": _utc_now(),
            }
        )
        self._write_immutable(
            self._intent_record_path(
                task_id, str(intent["intent_id"]), "abort.json"
            ),
            abort,
            expected_type="binding_abort_record",
        )

    def _record_binding_abort(
        self,
        task_id: str,
        intent: Mapping[str, Any],
        request: Mapping[str, Any],
        *,
        observed_binding_revision: int,
    ) -> None:
        abort = _seal(
            {
                "schema_version": self.SCHEMA_VERSION,
                "object_type": "binding_abort_record",
                "task_id": task_id,
                "intent_id": intent["intent_id"],
                "intent_digest": intent["content_digest"],
                "request_digest": request["content_digest"],
                "binding_revision_id": intent["binding_revision_id"],
                "base_spec_revision": intent["base_spec_revision"],
                "base_binding_revision": intent["base_binding_revision"],
                "observed_spec_revision": None,
                "observed_binding_revision": observed_binding_revision,
                "reason": "aborted_binding_changed",
                "aborted_at": _utc_now(),
            }
        )
        self._write_immutable(
            self._intent_record_path(
                task_id, str(intent["intent_id"]), "abort.json"
            ),
            abort,
            expected_type="binding_abort_record",
        )

    def _verify_intent_references(
        self, task_id: str, intent: Mapping[str, Any]
    ) -> None:
        resolution = self.get_resolution(task_id, str(intent["resolution_id"]))
        snapshot = self.get_snapshot(task_id, str(intent["snapshot_id"]))
        analysis = self.get_analysis(task_id, str(intent["analysis_id"]))
        expected = {
            "resolution_digest": resolution["content_digest"],
            "snapshot_digest": snapshot["content_digest"],
            "analysis_digest": analysis["content_digest"],
        }
        if any(intent.get(key) != value for key, value in expected.items()):
            raise ModelSourceIntegrityError("binding intent lineage changed")
        if snapshot["resolution_id"] != resolution["resolution_id"]:
            raise ModelSourceIntegrityError("binding intent resolution lineage changed")
        if analysis["snapshot_id"] != snapshot["snapshot_id"]:
            raise ModelSourceIntegrityError("binding intent analysis lineage changed")

    def _verify_binding_references(
        self, task_id: str, binding: Mapping[str, Any]
    ) -> None:
        intent = self.get_binding_intent(task_id, str(binding["intent_id"]))[
            "intent"
        ]
        self._verify_intent_references(task_id, intent)
        resolution = self.get_resolution(task_id, str(binding["resolution_id"]))
        snapshot = self.get_snapshot(task_id, str(binding["snapshot_id"]))
        analysis = self.get_analysis(task_id, str(binding["analysis_id"]))
        expected = {
            "intent_id": intent["intent_id"],
            "intent_digest": intent["content_digest"],
            "binding_revision_id": intent["binding_revision_id"],
            "revision": intent["binding_revision"],
            "base_spec_revision": intent["base_spec_revision"],
            "resolution_id": intent["resolution_id"],
            "resolution_digest": resolution["content_digest"],
            "snapshot_id": intent["snapshot_id"],
            "snapshot_digest": snapshot["content_digest"],
            "analysis_id": intent["analysis_id"],
            "analysis_digest": analysis["content_digest"],
            "supersedes_revision": (
                intent["base_binding_revision"]
                if int(intent["base_binding_revision"]) > 0
                else None
            ),
        }
        if any(binding.get(key) != value for key, value in expected.items()):
            raise ModelSourceIntegrityError("ModelBindingRevision lineage changed")

    def _normalize_files(
        self, files: Sequence[RemoteSourceFile | Mapping[str, Any]]
    ) -> tuple[RemoteSourceFile, ...]:
        if isinstance(files, (str, bytes)) or not isinstance(files, Sequence):
            raise ContractError("files must be a sequence")
        selected: list[RemoteSourceFile] = []
        for raw in files:
            if isinstance(raw, RemoteSourceFile):
                item = raw.to_dict()
            elif isinstance(raw, Mapping):
                item = dict(raw)
            else:
                raise ContractError("remote source file must be an object")
            _assert_no_credentials(item)
            size_value = item.get("size_bytes")
            if size_value is not None and (
                isinstance(size_value, bool) or not isinstance(size_value, int)
            ):
                raise ContractError("invalid RemoteSourceFile")
            try:
                selected.append(
                    RemoteSourceFile(
                        path=str(item["path"]),
                        kind=str(item["kind"]),
                        mode=(str(item["mode"]) if item.get("mode") is not None else None),
                        size_bytes=size_value,
                        remote_digest=str(item["remote_digest"]),
                        lfs_sha256=(
                            str(item["lfs_sha256"])
                            if item.get("lfs_sha256") is not None
                            else None
                        ),
                    )
                )
            except (KeyError, ModelSourceValidationError, TypeError, ValueError) as error:
                raise ContractError("invalid RemoteSourceFile") from error
        if not selected:
            raise ContractError("SourceSnapshot requires at least one remote file")
        ordered = tuple(sorted(selected, key=lambda item: item.path))
        try:
            tree_manifest_sha256(ordered)
        except ModelSourceValidationError as error:
            raise ContractError(str(error)) from error
        return ordered

    def _normalize_documents(
        self,
        documents: Sequence[SourceDocument | Mapping[str, Any]],
        files: Sequence[RemoteSourceFile],
    ) -> tuple[SourceDocument, ...]:
        if isinstance(documents, (str, bytes)) or not isinstance(documents, Sequence):
            raise ContractError("documents must be a sequence")
        files_by_path = {item.path: item for item in files}
        selected: list[SourceDocument] = []
        for raw in documents:
            if isinstance(raw, SourceDocument):
                item = {
                    "path": raw.path,
                    "size_bytes": raw.size_bytes,
                    "sha256": raw.sha256,
                    "content": raw.content,
                }
            elif isinstance(raw, Mapping):
                item = deepcopy(dict(raw))
            else:
                raise ContractError("SourceDocument must be an object")
            _assert_no_credentials(item)
            content = item.get("content")
            if content is None and isinstance(item.get("content_utf8"), str):
                content = str(item["content_utf8"]).encode("utf-8")
            if content is None and isinstance(item.get("content_base64"), str):
                try:
                    content = base64.b64decode(
                        str(item["content_base64"]), validate=True
                    )
                except ValueError as error:
                    raise ContractError("invalid SourceDocument content") from error
            size_value = item.get("size_bytes")
            if isinstance(size_value, bool) or not isinstance(size_value, int):
                raise ContractError("invalid SourceDocument")
            try:
                document = SourceDocument(
                    path=str(item["path"]),
                    size_bytes=size_value,
                    sha256=str(item["sha256"]),
                    content=content,
                )
            except (KeyError, ModelSourceValidationError, TypeError, ValueError) as error:
                raise ContractError("invalid SourceDocument") from error
            file = files_by_path.get(document.path)
            if file is None:
                raise ContractError("SourceDocument must reference a remote source file")
            if file.kind != "blob" or file.mode not in {None, "100644"}:
                raise ContractError("SourceDocument references an unsafe source file")
            selected.append(document)
        ordered = tuple(sorted(selected, key=lambda item: item.path))
        probe = DomainSourceSnapshot(
            schema_version="0.1",
            snapshot_id="source-snapshot-validation",
            task_id="source-snapshot-validation",
            resolution_id="source-resolution-validation",
            provider="github",
            repository="fixture/validation",
            requested_revision="main",
            resolved_commit="0" * 40,
            license="unknown",
            license_status="unknown",
            files=tuple(files),
            documents=ordered,
            tree_manifest_sha256=tree_manifest_sha256(tuple(files)),
            execution_policy="never_execute_in_l1",
            created_at_utc=_utc_now(),
        )
        document_errors = tuple(
            item for item in verify_source_snapshot(probe) if "document" in item
        )
        if document_errors:
            raise ContractError(
                f"invalid SourceDocument set: {','.join(document_errors)}"
            )
        return ordered

    def _domain_snapshot_from_record(
        self, snapshot: Mapping[str, Any]
    ) -> DomainSourceSnapshot:
        try:
            files = tuple(
                RemoteSourceFile(
                    path=str(item["path"]),
                    kind=str(item["kind"]),
                    mode=(str(item["mode"]) if item.get("mode") is not None else None),
                    size_bytes=item.get("size_bytes"),
                    remote_digest=str(item["remote_digest"]),
                    lfs_sha256=(
                        str(item["lfs_sha256"])
                        if item.get("lfs_sha256") is not None
                        else None
                    ),
                )
                for item in snapshot["files"]
            )
            documents = tuple(
                SourceDocument(
                    path=str(item["path"]),
                    size_bytes=int(item["size_bytes"]),
                    sha256=str(item["sha256"]),
                    content=base64.b64decode(
                        str(item["content_base64"]), validate=True
                    ),
                )
                for item in snapshot["documents"]
            )
            domain = DomainSourceSnapshot(
                schema_version=str(snapshot["schema_version"]),
                snapshot_id=str(snapshot["snapshot_id"]),
                task_id=str(snapshot["task_id"]),
                resolution_id=str(snapshot["resolution_id"]),
                provider=str(snapshot["provider"]),
                repository=str(snapshot["repository"]),
                requested_revision=str(snapshot["requested_revision"]),
                resolved_commit=str(snapshot["resolved_commit"]),
                license=str(snapshot["license"]),
                license_status=str(snapshot["license_status"]),
                files=files,
                documents=documents,
                tree_manifest_sha256=str(snapshot["tree_manifest_sha256"]),
                execution_policy=str(snapshot["execution_policy"]),
                created_at_utc=str(snapshot["created_at_utc"]),
                license_policy=deepcopy(
                    dict(snapshot.get("details", {}).get("license_policy") or {})
                ),
            )
        except (KeyError, ValueError, TypeError, ModelSourceValidationError) as error:
            raise ModelSourceIntegrityError(
                "stored SourceSnapshot cannot be rehydrated"
            ) from error
        errors = verify_source_snapshot(domain)
        if errors:
            raise ModelSourceIntegrityError(
                f"stored SourceSnapshot failed verification: {','.join(errors)}"
            )
        return domain

    def _task_root(self, task_id: str) -> Path:
        task_id = _safe_task_id(task_id)
        candidate = self.tasks_dir / task_id
        if candidate.is_symlink():
            raise ContractError("task directory cannot be a symlink")
        resolved = candidate.resolve(strict=False)
        if resolved.parent != self.tasks_dir:
            raise ContractError("invalid task id")
        task_path = candidate / "task.json"
        if task_path.is_symlink():
            raise ContractError("task record cannot be a symlink")
        if not task_path.is_file():
            raise FileNotFoundError(f"task not found: {task_id}")
        try:
            task = read_json(task_path)
        except Exception as error:
            raise ModelSourceIntegrityError("task record is not valid JSON") from error
        if not isinstance(task, dict) or task.get("task_id") != task_id:
            raise ModelSourceIntegrityError("task record identity mismatch")
        return candidate

    def _secure_directory(self, task_id: str, *parts: str) -> Path:
        task_root = self._task_root(task_id)
        current = task_root
        for part in parts:
            if not RECORD_ID_PATTERN.fullmatch(part):
                raise ContractError("invalid model source storage path")
            current = current / part
            if current.is_symlink():
                raise ContractError("model source storage directory cannot be a symlink")
            current.mkdir(exist_ok=True)
            if not current.is_dir() or task_root.resolve() not in (
                current.resolve(),
                *current.resolve().parents,
            ):
                raise ContractError("model source storage escaped task directory")
        return current

    def _model_source_root(self, task_id: str) -> Path:
        return self._secure_directory(task_id, "model_sources")

    def _collection_dir(self, task_id: str, collection: str) -> Path:
        if collection not in {
            "searches",
            "resolutions",
            "snapshots",
            "analyses",
            "bindings",
            "binding_intents",
        }:
            raise ContractError("unknown model source collection")
        return self._secure_directory(task_id, "model_sources", collection)

    def _record_path(self, task_id: str, collection: str, record_id: str) -> Path:
        record_id = _safe_record_id(record_id, "record id")
        return self._collection_dir(task_id, collection) / f"{record_id}.json"

    def _intent_record_path(
        self, task_id: str, intent_id: str, filename: str
    ) -> Path:
        intent_id = _safe_record_id(intent_id, "binding intent id")
        if filename not in {
            "intent.json",
            "commit_request.json",
            "commit_receipt.json",
            "abort.json",
        }:
            raise ContractError("invalid binding intent record")
        directory = self._secure_directory(
            task_id, "model_sources", "binding_intents", intent_id
        )
        return directory / filename

    def _read_record(
        self, path: Path, expected_type: str, task_id: str
    ) -> dict[str, Any]:
        if path.is_symlink():
            raise ContractError("model source record cannot be a symlink")
        if not path.is_file():
            raise FileNotFoundError(f"record not found: {path.name}")
        try:
            value = read_json(path)
        except Exception as error:
            raise ModelSourceIntegrityError(
                f"record is not valid JSON: {path.name}"
            ) from error
        record = _verify_seal(
            value,
            expected_type=expected_type,
            source=path.name,
        )
        if record.get("task_id") != task_id:
            raise ModelSourceIntegrityError(f"record task identity mismatch: {path.name}")
        return record

    def _write_immutable(
        self,
        path: Path,
        value: Mapping[str, Any],
        *,
        expected_type: str,
    ) -> None:
        if path.is_symlink():
            raise ContractError("immutable record cannot be a symlink")
        if path.is_file():
            existing = self._read_record(
                path, expected_type, str(value["task_id"])
            )
            if canonical_json(existing) != canonical_json(value):
                raise ModelSourceIntegrityError(
                    f"immutable record already differs: {path.name}"
                )
            return
        if path.exists():
            raise ContractError("immutable record path is not a file")
        pending = path.parent / f".{path.name}.{uuid4().hex}.pending"
        try:
            write_json(pending, dict(value))
            try:
                os.link(pending, path)
            except FileExistsError:
                existing = self._read_record(
                    path, expected_type, str(value["task_id"])
                )
                if canonical_json(existing) != canonical_json(value):
                    raise ModelSourceIntegrityError(
                        f"immutable record race differs: {path.name}"
                    )
        finally:
            pending.unlink(missing_ok=True)

    def _list_records(
        self, task_id: str, collection: str, expected_type: str
    ) -> list[dict[str, Any]]:
        task_id = _safe_task_id(task_id)
        directory = self._collection_dir(task_id, collection)
        identity_field = {
            "source_search_record": "search_id",
            "source_resolution": "resolution_id",
            "source_snapshot": "snapshot_id",
            "repository_analysis": "analysis_id",
            "model_binding_revision": "binding_revision_id",
        }[expected_type]
        records: list[dict[str, Any]] = []
        for path in sorted(directory.glob("*.json")):
            record = self._read_record(path, expected_type, task_id)
            if record.get(identity_field) != path.stem:
                raise ModelSourceIntegrityError(
                    f"record identity does not match path: {path.name}"
                )
            records.append(record)
        return sorted(records, key=lambda item: (int(item["revision"]), item.get("created_at", "")))

    def _task_ids(self) -> list[str]:
        selected: list[str] = []
        for path in sorted(self.tasks_dir.iterdir()):
            if path.is_symlink():
                raise ContractError("task directory cannot be a symlink")
            if path.is_dir() and (path / "task.json").is_file():
                selected.append(_safe_task_id(path.name))
        return selected

    @staticmethod
    def _find_semantic(
        records: Sequence[Mapping[str, Any]], semantic_digest: str
    ) -> dict[str, Any] | None:
        for record in records:
            if record.get("semantic_digest") == semantic_digest:
                return deepcopy(dict(record))
        return None

    @staticmethod
    def _next_revision(records: Sequence[Mapping[str, Any]]) -> int:
        return max((int(item["revision"]) for item in records), default=0) + 1
