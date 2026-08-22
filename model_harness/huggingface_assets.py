from __future__ import annotations

import fnmatch
import importlib
import os
import shutil
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Callable

from .model_assets import (
    COMMIT_PATTERN,
    DEFAULT_ALLOW_PATTERNS,
    REPO_ID_PATTERN,
    DownloadResult,
    ModelAsset,
    ModelAssetError,
    ModelAssetStore,
)


class HuggingFaceCapabilityUnavailable(ModelAssetError):
    """The optional official huggingface_hub client is unavailable."""


class HuggingFaceAssetError(ModelAssetError):
    """A sanitized Hugging Face metadata or snapshot failure."""


@dataclass(frozen=True)
class _HubBindings:
    api_factory: Callable[..., Any]
    snapshot_download: Callable[..., str]


@dataclass(frozen=True)
class TrainingModelAsset:
    asset: ModelAsset
    root: Path
    files: tuple[tuple[str, Path], ...]

    @property
    def model_files(self) -> tuple[Path, ...]:
        return tuple(
            path
            for relative_path, path in self.files
            if Path(relative_path).suffix.lower() in {".safetensors", ".onnx", ".model"}
        )

    def file(self, relative_path: str) -> Path:
        normalized = _safe_repo_file(relative_path)
        for selected, path in self.files:
            if selected == normalized:
                return path
        raise ModelAssetError("required_asset_file_missing")


def _official_bindings() -> _HubBindings:
    try:
        module = importlib.import_module("huggingface_hub")
        api_factory = getattr(module, "HfApi")
        snapshot_download = getattr(module, "snapshot_download")
    except (ImportError, AttributeError) as exc:
        raise HuggingFaceCapabilityUnavailable(
            "capability_unavailable:huggingface_hub"
        ) from exc
    return _HubBindings(
        api_factory=api_factory,
        snapshot_download=snapshot_download,
    )


def _safe_repo_file(value: str) -> str:
    if not value or "\\" in value or "\x00" in value:
        raise HuggingFaceAssetError("unsafe_huggingface_repo_path")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts:
        raise HuggingFaceAssetError("unsafe_huggingface_repo_path")
    parts = tuple(part for part in path.parts if part not in {"", "."})
    if (
        not parts
        or len(parts) > 12
        or any(part.startswith(".") or len(part) > 160 for part in parts)
    ):
        raise HuggingFaceAssetError("unsafe_huggingface_repo_path")
    normalized = "/".join(parts)
    if len(normalized) > 512:
        raise HuggingFaceAssetError("unsafe_huggingface_repo_path")
    return normalized


def _matches_allowed(relative_path: str, patterns: tuple[str, ...]) -> bool:
    basename = PurePosixPath(relative_path).name
    return any(
        fnmatch.fnmatchcase(relative_path, pattern)
        or fnmatch.fnmatchcase(basename, pattern)
        for pattern in patterns
    )


def _validate_allow_patterns(patterns: tuple[str, ...]) -> tuple[str, ...]:
    if not patterns or len(patterns) > 64:
        raise HuggingFaceAssetError("invalid_allow_patterns")
    selected: list[str] = []
    for raw in patterns:
        pattern = str(raw).strip()
        path = PurePosixPath(pattern.replace("\\", "/"))
        if (
            not pattern
            or len(pattern) > 200
            or pattern.startswith(("/", "."))
            or ".." in path.parts
            or "\\" in pattern
            or "\x00" in pattern
        ):
            raise HuggingFaceAssetError("invalid_allow_patterns")
        selected.append(pattern)
    return tuple(dict.fromkeys(selected))


def _repo_files(info: Any, allow_patterns: tuple[str, ...]) -> tuple[str, ...]:
    selected: list[str] = []
    for sibling in getattr(info, "siblings", ()) or ():
        raw = getattr(sibling, "rfilename", None)
        if raw is None and isinstance(sibling, dict):
            raw = sibling.get("rfilename")
        if not isinstance(raw, str):
            continue
        # Repositories commonly contain hidden metadata such as
        # .gitattributes. Files outside the explicit allowlist are irrelevant
        # to this asset and must not make an otherwise safe selection fail.
        # Matching paths still pass the strict validator before being copied.
        if not _matches_allowed(raw.replace("\\", "/"), allow_patterns):
            continue
        relative_path = _safe_repo_file(raw)
        selected.append(relative_path)
    if not selected:
        raise HuggingFaceAssetError("huggingface_allow_patterns_matched_no_files")
    return tuple(sorted(set(selected)))


def _license_from_info(info: Any) -> str:
    card_data = getattr(info, "card_data", None)
    if card_data is None:
        card_data = getattr(info, "cardData", None)
    if hasattr(card_data, "to_dict"):
        card_data = card_data.to_dict()
    if isinstance(card_data, dict):
        license_value = card_data.get("license")
    else:
        license_value = getattr(card_data, "license", None)
    if isinstance(license_value, str) and license_value.strip():
        return license_value.strip()
    if isinstance(license_value, (list, tuple)):
        selected = [str(item).strip() for item in license_value if str(item).strip()]
        if selected:
            return " AND ".join(selected)
    return "unknown"


def _safe_snapshot_source(snapshot_root: Path, relative_path: str) -> Path:
    source = snapshot_root.joinpath(*PurePosixPath(relative_path).parts)
    if not source.exists():
        raise HuggingFaceAssetError("huggingface_snapshot_incomplete")
    repository_cache_root = (
        snapshot_root.parent.parent
        if snapshot_root.parent.name == "snapshots"
        else snapshot_root
    )
    try:
        resolved = source.resolve(strict=True)
        resolved.relative_to(repository_cache_root.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise HuggingFaceAssetError("huggingface_snapshot_path_escape") from exc
    if not resolved.is_file():
        raise HuggingFaceAssetError("huggingface_snapshot_non_file")
    return resolved


class HuggingFaceHubDownloader:
    """Download a commit-pinned model snapshot through the official HF client."""

    def __init__(
        self,
        *,
        api_factory: Callable[..., Any] | None = None,
        snapshot_download_fn: Callable[..., str] | None = None,
        bindings_loader: Callable[[], _HubBindings] | None = None,
    ) -> None:
        self._api_factory = api_factory
        self._snapshot_download_fn = snapshot_download_fn
        self._bindings_loader = bindings_loader or _official_bindings

    def _bindings(self) -> _HubBindings:
        if self._api_factory is not None and self._snapshot_download_fn is not None:
            return _HubBindings(
                api_factory=self._api_factory,
                snapshot_download=self._snapshot_download_fn,
            )
        if (self._api_factory is None) != (self._snapshot_download_fn is None):
            raise HuggingFaceCapabilityUnavailable(
                "capability_unavailable:huggingface_hub_incomplete_binding"
            )
        return self._bindings_loader()

    def capability(self) -> dict[str, Any]:
        try:
            self._bindings()
        except HuggingFaceCapabilityUnavailable as exc:
            return {
                "available": False,
                "provider": "huggingface",
                "reason": str(exc),
            }
        return {
            "available": True,
            "provider": "huggingface",
            "download_semantics": "official_hf_api_commit_pinned_snapshot",
        }

    def download(
        self,
        *,
        provider: str,
        repo_id: str,
        revision: str,
        destination: Path,
        allow_patterns: tuple[str, ...],
        token: str | None,
    ) -> DownloadResult:
        if provider != "huggingface":
            raise HuggingFaceAssetError("unsupported_asset_provider")
        if not REPO_ID_PATTERN.fullmatch(repo_id) or any(
            part in {".", ".."} for part in repo_id.split("/")
        ):
            raise HuggingFaceAssetError("invalid_repo_id")
        selected_revision = revision.strip().lower()
        if not COMMIT_PATTERN.fullmatch(selected_revision):
            raise HuggingFaceAssetError("revision_not_immutable_commit")
        if token is not None and not isinstance(token, str):
            raise HuggingFaceAssetError("invalid_ephemeral_token")
        selected_patterns = _validate_allow_patterns(tuple(allow_patterns))
        if (
            not destination.is_dir()
            or destination.is_symlink()
            or any(destination.iterdir())
        ):
            raise HuggingFaceAssetError("asset_destination_not_empty")
        bindings = self._bindings()
        try:
            api = bindings.api_factory(token=token)
            info = api.model_info(
                repo_id=repo_id,
                revision=selected_revision,
                files_metadata=True,
                token=token,
            )
            resolved_commit = str(getattr(info, "sha", "")).strip().lower()
            if (
                not COMMIT_PATTERN.fullmatch(resolved_commit)
                or resolved_commit != selected_revision
            ):
                raise HuggingFaceAssetError("resolved_commit_mismatch")
            selected_files = _repo_files(info, selected_patterns)
            snapshot_value = bindings.snapshot_download(
                repo_id=repo_id,
                repo_type="model",
                revision=selected_revision,
                allow_patterns=list(selected_patterns),
                token=token,
            )
            snapshot_root = Path(snapshot_value).expanduser().resolve(strict=True)
            if not snapshot_root.is_dir():
                raise HuggingFaceAssetError("huggingface_snapshot_missing")
            for relative_path in selected_files:
                source = _safe_snapshot_source(snapshot_root, relative_path)
                target = destination.joinpath(*PurePosixPath(relative_path).parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
                os.chmod(target, 0o600)
            return DownloadResult(
                resolved_commit=resolved_commit,
                license=_license_from_info(info),
            )
        except HuggingFaceAssetError:
            raise
        except Exception:
            raise HuggingFaceAssetError("huggingface_download_failed") from None


def download_huggingface_asset(
    store: ModelAssetStore,
    *,
    repo_id: str,
    commit: str,
    allow_patterns: tuple[str, ...] = DEFAULT_ALLOW_PATTERNS,
    token: str | None = None,
    downloader: HuggingFaceHubDownloader | None = None,
) -> ModelAsset:
    selected_downloader = downloader or HuggingFaceHubDownloader()
    capability = selected_downloader.capability()
    if not capability["available"]:
        raise HuggingFaceCapabilityUnavailable(str(capability["reason"]))
    return store.download(
        provider="huggingface",
        repo_id=repo_id,
        requested_revision=commit,
        downloader=selected_downloader,
        allow_patterns=allow_patterns,
        token=token,
    )


def resolve_training_asset(
    store: ModelAssetStore,
    asset_id: str,
    *,
    required_files: tuple[str, ...] = (),
) -> TrainingModelAsset:
    verification = store.verify(asset_id)
    if not verification.ok:
        raise ModelAssetError("model_asset_integrity_verification_failed")
    root = store.asset_files_dir(asset_id)
    file_pairs = tuple(
        (item.relative_path, root.joinpath(*PurePosixPath(item.relative_path).parts))
        for item in verification.asset.files
    )
    handle = TrainingModelAsset(
        asset=verification.asset,
        root=root,
        files=file_pairs,
    )
    for required in required_files:
        handle.file(required)
    if not handle.model_files:
        raise ModelAssetError("model_asset_has_no_training_payload")
    return handle
