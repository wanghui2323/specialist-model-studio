from __future__ import annotations

import hashlib
import importlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from .model_assets import COMMIT_PATTERN
from .model_sources import (
    MAX_DOCUMENT_BYTES,
    MAX_TREE_FILES,
    ModelSourceUpstreamError,
    ModelSourceValidationError,
    RemoteSourceFile,
    ResolvedSource,
    SourceDocument,
    is_analysis_document_path,
    normalize_commit,
    normalize_repository,
    normalize_revision,
    normalize_source_path,
    source_candidate_id,
    validate_ephemeral_token,
)


HUGGINGFACE_OFFICIAL_ENDPOINT = "https://huggingface.co"


@dataclass(frozen=True)
class _HubBindings:
    api_factory: Callable[..., Any]
    hf_hub_download: Callable[..., str]


def _official_bindings() -> _HubBindings:
    try:
        module = importlib.import_module("huggingface_hub")
        api_factory = getattr(module, "HfApi")
        download_file = getattr(module, "hf_hub_download")
    except (ImportError, AttributeError) as exc:
        raise ModelSourceUpstreamError(
            "capability_unavailable:huggingface_hub"
        ) from exc
    return _HubBindings(api_factory=api_factory, hf_hub_download=download_file)


def _card_mapping(info: Any) -> Mapping[str, Any]:
    value = getattr(info, "card_data", None)
    if value is None:
        value = getattr(info, "cardData", None)
    if hasattr(value, "to_dict"):
        value = value.to_dict()
    return value if isinstance(value, Mapping) else {}


def _license(info: Any) -> tuple[str, str]:
    value = _card_mapping(info).get("license")
    if isinstance(value, str) and value.strip():
        selected = value.strip()
    elif isinstance(value, (list, tuple)):
        selected_values = [str(item).strip() for item in value if str(item).strip()]
        selected = " AND ".join(selected_values)
    else:
        selected = ""
    if (
        not selected
        or selected.lower() in {"unknown", "other", "noassertion"}
        or len(selected) > 200
        or any(ord(character) < 32 for character in selected)
    ):
        return "unknown", "unknown"
    return selected, "known"


def _mapping_value(value: Any, key: str) -> Any:
    if isinstance(value, Mapping):
        return value.get(key)
    return getattr(value, key, None)


@dataclass(frozen=True)
class HuggingFaceSourceProvider:
    api_factory: Callable[..., Any] | None = None
    hf_hub_download_fn: Callable[..., str] | None = None
    bindings_loader: Callable[[], _HubBindings] = _official_bindings
    provider_id: str = "huggingface"

    def search(
        self,
        query: str,
        *,
        pipeline_tag: str | None = None,
        limit: int = 6,
        token: str | None = None,
    ) -> tuple[dict[str, Any], ...]:
        selected_query = str(query).strip()
        if (
            not selected_query
            or len(selected_query) > 160
            or any(ord(character) < 32 for character in selected_query)
        ):
            raise ModelSourceValidationError("invalid_huggingface_search_query")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 10:
            raise ModelSourceValidationError("invalid_huggingface_search_limit")
        selected_pipeline = str(pipeline_tag or "").strip() or None
        if selected_pipeline is not None and (
            len(selected_pipeline) > 80
            or not all(
                character.isalnum() or character in {"-", "_"}
                for character in selected_pipeline
            )
        ):
            raise ModelSourceValidationError("invalid_huggingface_pipeline_tag")
        selected_token = validate_ephemeral_token(token)
        try:
            models: Iterable[Any] = self._api(selected_token).list_models(
                search=selected_query,
                pipeline_tag=selected_pipeline,
                sort="downloads",
                direction=-1,
                limit=limit,
                full=True,
                cardData=True,
                fetch_config=True,
                token=selected_token if selected_token is not None else False,
            )
            candidates: list[dict[str, Any]] = []
            for info in models:
                repository = normalize_repository(
                    str(getattr(info, "id", None) or getattr(info, "modelId", ""))
                )
                resolved_value = str(getattr(info, "sha", "") or "").strip().lower()
                resolved_commit = (
                    normalize_commit(resolved_value)
                    if resolved_value
                    else None
                )
                requested_revision = "main"
                license_name, license_status = _license(info)
                downloads = getattr(info, "downloads", 0)
                likes = getattr(info, "likes", 0)
                if (
                    isinstance(downloads, bool)
                    or not isinstance(downloads, int)
                    or downloads < 0
                ):
                    downloads = 0
                if isinstance(likes, bool) or not isinstance(likes, int) or likes < 0:
                    likes = 0
                library = str(getattr(info, "library_name", "") or "unknown")[:160]
                returned_pipeline = str(
                    getattr(info, "pipeline_tag", "") or "unknown"
                )[:160]
                candidates.append(
                    {
                        "candidate_id": source_candidate_id(
                            self.provider_id, repository, requested_revision
                        ),
                        "provider": self.provider_id,
                        "repository": repository,
                        "source_uri": f"https://huggingface.co/{repository}",
                        "requested_revision": requested_revision,
                        "resolved_commit": resolved_commit,
                        "catalog_commit_hint": resolved_commit,
                        "license": license_name,
                        "license_status": license_status,
                        "description": f"{returned_pipeline} · {library}",
                        "task_tag": returned_pipeline,
                        "library": library,
                        "popularity": {"downloads": downloads, "likes": likes},
                        "repository_size_bytes": None,
                        "catalog_evidence": "huggingface_official_hub_api",
                    }
                )
            return tuple(candidates)
        except (ModelSourceValidationError, ModelSourceUpstreamError):
            raise
        except Exception:
            raise ModelSourceUpstreamError("huggingface_search_failed") from None

    def _bindings(self) -> _HubBindings:
        if self.api_factory is not None and self.hf_hub_download_fn is not None:
            return _HubBindings(
                api_factory=self.api_factory,
                hf_hub_download=self.hf_hub_download_fn,
            )
        if (self.api_factory is None) != (self.hf_hub_download_fn is None):
            raise ModelSourceValidationError("incomplete_huggingface_provider_binding")
        return self.bindings_loader()

    def _api(self, token: str | None) -> Any:
        try:
            if self.api_factory is not None:
                return self.api_factory(token=token)
            return self._bindings().api_factory(
                endpoint=HUGGINGFACE_OFFICIAL_ENDPOINT,
                token=token if token is not None else False,
            )
        except ModelSourceValidationError:
            raise
        except Exception:
            raise ModelSourceUpstreamError("huggingface_api_unavailable") from None

    def resolve(
        self,
        repository: str,
        requested_revision: str | None,
        *,
        token: str | None = None,
    ) -> ResolvedSource:
        selected_repo = normalize_repository(repository)
        selected_revision = normalize_revision(requested_revision)
        selected_token = validate_ephemeral_token(token)
        try:
            info = self._api(selected_token).model_info(
                repo_id=selected_repo,
                revision=selected_revision,
                files_metadata=False,
                securityStatus=True,
                token=selected_token if selected_token is not None else False,
            )
        except (ModelSourceValidationError, ModelSourceUpstreamError):
            raise
        except Exception:
            raise ModelSourceUpstreamError("huggingface_resolve_failed") from None
        try:
            resolved_commit = normalize_commit(str(getattr(info, "sha", "")))
        except ModelSourceValidationError:
            raise ModelSourceUpstreamError("huggingface_commit_unavailable") from None
        if (
            COMMIT_PATTERN.fullmatch(selected_revision.lower())
            and resolved_commit != selected_revision.lower()
        ):
            raise ModelSourceUpstreamError("resolved_commit_mismatch")
        repository_id = str(getattr(info, "id", None) or getattr(info, "modelId", ""))
        if repository_id and normalize_repository(repository_id) != selected_repo:
            raise ModelSourceUpstreamError("huggingface_repository_mismatch")
        license_name, license_status = _license(info)
        tags = [
            str(item)[:160]
            for item in (getattr(info, "tags", None) or ())
            if isinstance(item, str)
        ][:40]
        return ResolvedSource(
            provider=self.provider_id,
            repository=selected_repo,
            requested_revision=selected_revision,
            resolved_commit=resolved_commit,
            license=license_name,
            license_status=license_status,
            tree_reference=resolved_commit,
            metadata={
                "source_kind": "huggingface_model_repository",
                "library": str(getattr(info, "library_name", "") or "unknown")[:160],
                "pipeline_tag": str(getattr(info, "pipeline_tag", "") or "unknown")[
                    :160
                ],
                "tags": tags,
            },
        )

    def list_tree(
        self,
        source: ResolvedSource,
        *,
        token: str | None = None,
    ) -> tuple[RemoteSourceFile, ...]:
        self._validate_source(source)
        selected_token = validate_ephemeral_token(token)
        try:
            tree: Iterable[Any] = self._api(selected_token).list_repo_tree(
                repo_id=source.repository,
                recursive=True,
                revision=source.resolved_commit,
                repo_type="model",
                token=selected_token if selected_token is not None else False,
            )
            files: list[RemoteSourceFile] = []
            seen_paths: set[str] = set()
            for index, item in enumerate(tree, start=1):
                if index > MAX_TREE_FILES:
                    raise ModelSourceValidationError("source_tree_file_limit_exceeded")
                path = normalize_source_path(str(_mapping_value(item, "path") or ""))
                if path in seen_paths:
                    raise ModelSourceUpstreamError("huggingface_duplicate_tree_path")
                seen_paths.add(path)
                blob_id = _mapping_value(item, "blob_id")
                tree_id = _mapping_value(item, "tree_id")
                lfs_value = _mapping_value(item, "lfs")
                if blob_id:
                    kind = "blob"
                    mode = None
                    digest = str(blob_id).strip().lower()
                    size_value = _mapping_value(item, "size")
                    if (
                        isinstance(size_value, bool)
                        or not isinstance(size_value, int)
                        or size_value < 0
                    ):
                        raise ModelSourceUpstreamError("huggingface_invalid_tree_entry")
                    size = size_value
                elif tree_id:
                    kind = "tree"
                    mode = "040000"
                    digest = str(tree_id).strip().lower()
                    size = None
                else:
                    raise ModelSourceUpstreamError("huggingface_invalid_tree_entry")
                lfs_sha256 = None
                if lfs_value is not None:
                    raw_lfs_sha = _mapping_value(lfs_value, "sha256")
                    if raw_lfs_sha is not None:
                        lfs_sha256 = str(raw_lfs_sha).strip().lower()
                files.append(
                    RemoteSourceFile(
                        path=path,
                        kind=kind,
                        mode=mode,
                        size_bytes=size,
                        remote_digest=digest,
                        lfs_sha256=lfs_sha256,
                    )
                )
        except (ModelSourceValidationError, ModelSourceUpstreamError):
            raise
        except Exception:
            raise ModelSourceUpstreamError("huggingface_tree_failed") from None
        return tuple(sorted(files, key=lambda item: item.path))

    def read_document(
        self,
        source: ResolvedSource,
        file: RemoteSourceFile,
        *,
        token: str | None = None,
    ) -> SourceDocument:
        self._validate_source(source)
        selected_token = validate_ephemeral_token(token)
        if (
            file.kind != "blob"
            or file.mode not in {None, "100644"}
            or file.lfs_sha256 is not None
            or file.size_bytes is None
            or file.size_bytes > MAX_DOCUMENT_BYTES
            or not is_analysis_document_path(file.path)
        ):
            raise ModelSourceValidationError("huggingface_document_not_readable")
        try:
            local_value = self._bindings().hf_hub_download(
                repo_id=source.repository,
                filename=file.path,
                repo_type="model",
                revision=source.resolved_commit,
                token=selected_token if selected_token is not None else False,
                endpoint=HUGGINGFACE_OFFICIAL_ENDPOINT,
            )
            local_path = Path(local_value).expanduser().resolve(strict=True)
            if not local_path.is_file():
                raise ModelSourceValidationError(
                    "huggingface_document_not_regular_file"
                )
            observed_size = local_path.stat().st_size
            if observed_size != file.size_bytes or observed_size > MAX_DOCUMENT_BYTES:
                raise ModelSourceValidationError("huggingface_document_size_mismatch")
            with local_path.open("rb") as handle:
                content = handle.read(MAX_DOCUMENT_BYTES + 1)
        except (ModelSourceValidationError, ModelSourceUpstreamError):
            raise
        except Exception:
            raise ModelSourceUpstreamError(
                "huggingface_document_download_failed"
            ) from None
        if len(content) != file.size_bytes or len(content) > MAX_DOCUMENT_BYTES:
            raise ModelSourceValidationError("huggingface_document_size_mismatch")
        if selected_token is not None and selected_token.encode("utf-8") in content:
            raise ModelSourceValidationError("credential_material_detected")
        if len(file.remote_digest) == 40:
            git_blob = hashlib.sha1(
                f"blob {len(content)}\0".encode("ascii") + content
            ).hexdigest()
            if git_blob != file.remote_digest:
                raise ModelSourceValidationError("huggingface_document_digest_mismatch")
        elif hashlib.sha256(content).hexdigest() != file.remote_digest:
            raise ModelSourceValidationError("huggingface_document_digest_mismatch")
        return SourceDocument.from_bytes(file.path, content)

    def _validate_source(self, source: ResolvedSource) -> None:
        if (
            not isinstance(source, ResolvedSource)
            or source.provider != self.provider_id
        ):
            raise ModelSourceValidationError("source_provider_mismatch")
        normalize_repository(source.repository)
        normalize_commit(source.resolved_commit)
