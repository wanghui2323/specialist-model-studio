from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import re
import shutil
import stat
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from threading import RLock
from typing import Any, Protocol, runtime_checkable
from uuid import uuid4

from .errors import HarnessError
from .io_utils import read_json, write_json


COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")
PROVIDER_PATTERN = re.compile(r"^[a-z][a-z0-9._-]{0,31}$")
REPO_ID_PATTERN = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}/[A-Za-z0-9][A-Za-z0-9._-]{0,95}$"
)
DEFAULT_ALLOW_PATTERNS = (
    "*.safetensors",
    "*.safetensors.index.json",
    "*.onnx",
    "*.model",
    "*.tiktoken",
    "*.json",
    "*.txt",
    "*.md",
    "LICENSE*",
    "README*",
)
SAFE_SUFFIXES = {
    ".safetensors",
    ".onnx",
    ".model",
    ".tiktoken",
    ".json",
    ".txt",
    ".md",
}
MODEL_SUFFIXES = {".safetensors", ".onnx", ".model"}
BANNED_SUFFIXES = {
    ".bin",
    ".pt",
    ".pth",
    ".pkl",
    ".pickle",
    ".joblib",
    ".ckpt",
    ".py",
    ".pyc",
    ".sh",
    ".bash",
    ".zsh",
    ".bat",
    ".cmd",
    ".com",
    ".exe",
    ".dll",
    ".dylib",
    ".so",
    ".jar",
    ".zip",
    ".tar",
    ".gz",
    ".7z",
}
EXECUTABLE_MAGICS = (
    b"\x7fELF",
    b"MZ",
    b"\xcf\xfa\xed\xfe",
    b"\xce\xfa\xed\xfe",
    b"\xfe\xed\xfa\xcf",
    b"\xfe\xed\xfa\xce",
)
PICKLE_MAGICS = tuple(b"\x80" + bytes([version]) for version in range(2, 7))
ARCHIVE_MAGICS = (b"PK\x03\x04", b"\x1f\x8b")
MAX_METADATA_FILE_BYTES = 32 * 1024 * 1024
MAX_SAFETENSORS_HEADER_BYTES = 100 * 1024 * 1024
CREDENTIAL_MARKERS = (
    b"authorization: bearer ",
    b'"authorization":"bearer ',
    b'"access_token":',
    b'"refresh_token":',
    b"x-api-key:",
    b"-----begin private key-----",
)


class ModelAssetError(HarnessError):
    """A safe, expected failure while staging or verifying a model asset."""


@dataclass(frozen=True)
class DownloadResult:
    resolved_commit: str
    license: str


@runtime_checkable
class ModelAssetDownloader(Protocol):
    def download(
        self,
        *,
        provider: str,
        repo_id: str,
        revision: str,
        destination: Path,
        allow_patterns: tuple[str, ...],
        token: str | None,
    ) -> DownloadResult: ...


@dataclass(frozen=True)
class ModelAssetFile:
    relative_path: str
    size_bytes: int
    sha256: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> ModelAssetFile:
        return cls(
            relative_path=str(value["relative_path"]),
            size_bytes=int(value["size_bytes"]),
            sha256=str(value["sha256"]),
        )


@dataclass(frozen=True)
class ModelAsset:
    asset_id: str
    provider: str
    repo_id: str
    requested_revision: str
    resolved_commit: str
    license: str
    security_status: str
    allow_patterns: tuple[str, ...]
    files: tuple[ModelAssetFile, ...]
    manifest_sha256: str
    status: str
    created_at: str
    failure_code: str | None = None

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["allow_patterns"] = list(self.allow_patterns)
        value["files"] = [item.to_dict() for item in self.files]
        return value

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> ModelAsset:
        return cls(
            asset_id=str(value["asset_id"]),
            provider=str(value["provider"]),
            repo_id=str(value["repo_id"]),
            requested_revision=str(value["requested_revision"]),
            resolved_commit=str(value.get("resolved_commit", "")),
            license=str(value.get("license", "unknown")),
            security_status=str(value["security_status"]),
            allow_patterns=tuple(str(item) for item in value["allow_patterns"]),
            files=tuple(ModelAssetFile.from_dict(item) for item in value["files"]),
            manifest_sha256=str(value["manifest_sha256"]),
            status=str(value["status"]),
            created_at=str(value["created_at"]),
            failure_code=(
                str(value["failure_code"])
                if value.get("failure_code") is not None
                else None
            ),
        )


@dataclass(frozen=True)
class AssetVerification:
    asset: ModelAsset
    ok: bool
    errors: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "asset": self.asset.to_dict(),
            "ok": self.ok,
            "errors": list(self.errors),
        }


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _manifest_sha256(files: tuple[ModelAssetFile, ...]) -> str:
    payload = json.dumps(
        [item.to_dict() for item in files],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _empty_manifest_sha256() -> str:
    return _manifest_sha256(())


def _safe_relative_path(value: str) -> str:
    if "\\" in value or "\x00" in value:
        raise ModelAssetError("unsafe_relative_path")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts:
        raise ModelAssetError("unsafe_relative_path")
    parts = tuple(part for part in path.parts if part not in {"", "."})
    if not parts or len(parts) > 12:
        raise ModelAssetError("unsafe_relative_path")
    if any(part.startswith(".") or len(part) > 160 for part in parts):
        raise ModelAssetError("unsafe_relative_path")
    normalized = "/".join(parts)
    if len(normalized) > 512:
        raise ModelAssetError("unsafe_relative_path")
    return normalized


def _validate_patterns(patterns: tuple[str, ...]) -> tuple[str, ...]:
    if not patterns or len(patterns) > 64:
        raise ModelAssetError("invalid_allow_patterns")
    selected: list[str] = []
    for raw in patterns:
        pattern = str(raw).strip()
        if (
            not pattern
            or len(pattern) > 200
            or pattern.startswith(("/", "."))
            or ".." in PurePosixPath(pattern.replace("\\", "/")).parts
            or "\\" in pattern
            or "\x00" in pattern
        ):
            raise ModelAssetError("invalid_allow_patterns")
        selected.append(pattern)
    return tuple(dict.fromkeys(selected))


def _matches_allowed(relative_path: str, patterns: tuple[str, ...]) -> bool:
    basename = PurePosixPath(relative_path).name
    return any(
        fnmatch.fnmatchcase(relative_path, pattern)
        or fnmatch.fnmatchcase(basename, pattern)
        for pattern in patterns
    )


def _validate_safetensors(path: Path) -> None:
    file_size = path.stat().st_size
    if file_size < 10:
        raise ModelAssetError("invalid_safetensors_file")
    with path.open("rb") as handle:
        raw_header_size = handle.read(8)
        header_size = int.from_bytes(raw_header_size, "little", signed=False)
        if (
            header_size < 2
            or header_size > MAX_SAFETENSORS_HEADER_BYTES
            or 8 + header_size > file_size
        ):
            raise ModelAssetError("invalid_safetensors_file")
        try:
            header = json.loads(handle.read(header_size).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ModelAssetError("invalid_safetensors_file") from exc
    if not isinstance(header, dict):
        raise ModelAssetError("invalid_safetensors_file")
    data_size = file_size - 8 - header_size
    intervals: list[tuple[int, int]] = []
    for name, metadata in header.items():
        if name == "__metadata__":
            if not isinstance(metadata, dict):
                raise ModelAssetError("invalid_safetensors_file")
            continue
        if not isinstance(name, str) or not isinstance(metadata, dict):
            raise ModelAssetError("invalid_safetensors_file")
        offsets = metadata.get("data_offsets")
        shape = metadata.get("shape")
        dtype = metadata.get("dtype")
        if (
            not isinstance(offsets, list)
            or len(offsets) != 2
            or not all(isinstance(value, int) for value in offsets)
            or not isinstance(shape, list)
            or not all(isinstance(value, int) and value >= 0 for value in shape)
            or not isinstance(dtype, str)
            or not dtype
        ):
            raise ModelAssetError("invalid_safetensors_file")
        start, end = offsets
        if start < 0 or end < start or end > data_size:
            raise ModelAssetError("invalid_safetensors_file")
        intervals.append((start, end))
    if not intervals:
        raise ModelAssetError("safetensors_contains_no_tensors")
    ordered = sorted(intervals)
    if ordered[0][0] != 0 or any(
        current[1] != following[0]
        for current, following in zip(ordered, ordered[1:])
    ) or ordered[-1][1] != data_size:
        raise ModelAssetError("invalid_safetensors_offsets")


def _validate_file_type(path: Path, relative_path: str, size_bytes: int) -> None:
    name = path.name
    suffix = path.suffix.lower()
    if suffix in BANNED_SUFFIXES:
        raise ModelAssetError("unsafe_file_type")
    if (
        suffix not in SAFE_SUFFIXES
        and not name.startswith("LICENSE")
        and not name.startswith("README")
    ):
        raise ModelAssetError("unsafe_file_type")
    mode = path.lstat().st_mode
    if mode & 0o111:
        raise ModelAssetError("executable_file_rejected")
    with path.open("rb") as handle:
        prefix = handle.read(16)
    if prefix.startswith(EXECUTABLE_MAGICS):
        raise ModelAssetError("executable_content_rejected")
    if prefix.startswith(PICKLE_MAGICS):
        raise ModelAssetError("pickle_content_rejected")
    if prefix.startswith(ARCHIVE_MAGICS):
        raise ModelAssetError("archive_content_rejected")
    if suffix == ".json":
        if size_bytes > MAX_METADATA_FILE_BYTES:
            raise ModelAssetError("metadata_file_size_limit_exceeded")
        try:
            with path.open("r", encoding="utf-8") as handle:
                json.load(handle)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ModelAssetError("invalid_json_file") from exc
    if suffix in {".txt", ".md"} or name.startswith(("LICENSE", "README")):
        if size_bytes > MAX_METADATA_FILE_BYTES:
            raise ModelAssetError("metadata_file_size_limit_exceeded")
    if suffix == ".safetensors":
        _validate_safetensors(path)
    if relative_path.endswith(".safetensors.index.json") and suffix != ".json":
        raise ModelAssetError("unsafe_file_type")


def _sha256_rejecting_secret(path: Path, forbidden_secret: bytes | None) -> str:
    digest = hashlib.sha256()
    tail = b""
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            combined = tail + block
            lowered = combined.lower().replace(b" ", b"")
            if forbidden_secret and forbidden_secret in combined:
                raise ModelAssetError("credential_material_detected")
            if any(marker.replace(b" ", b"") in lowered for marker in CREDENTIAL_MARKERS):
                raise ModelAssetError("credential_material_detected")
            tail_size = max(
                [len(forbidden_secret or b""), *(len(item) for item in CREDENTIAL_MARKERS)]
            ) - 1
            tail = combined[-tail_size:] if tail_size > 0 else b""
            digest.update(block)
    return digest.hexdigest()


class ModelAssetStore:
    def __init__(
        self,
        root: str | Path,
        *,
        max_file_bytes: int = 20 * 1024 * 1024 * 1024,
        max_total_bytes: int = 50 * 1024 * 1024 * 1024,
        max_files: int = 10_000,
    ) -> None:
        self.root = Path(root).expanduser().resolve()
        self.active_dir = self.root / "active"
        self.staging_dir = self.root / "staging"
        self.quarantine_dir = self.root / "quarantine"
        self.max_file_bytes = int(max_file_bytes)
        self.max_total_bytes = int(max_total_bytes)
        self.max_files = int(max_files)
        if self.max_file_bytes <= 0 or self.max_total_bytes <= 0 or self.max_files <= 0:
            raise ValueError("asset store limits must be positive")
        for directory in (self.active_dir, self.staging_dir, self.quarantine_dir):
            directory.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._recover_staging()

    def _record_path(self, container: Path) -> Path:
        return container / "asset.json"

    def _write_record(self, container: Path, asset: ModelAsset) -> None:
        write_json(self._record_path(container), asset.to_dict())

    def _purge_staged_payload(self, container: Path) -> None:
        for child in list(container.iterdir()):
            if child.name == "asset.json":
                continue
            if child.is_symlink() or not child.is_dir():
                child.unlink(missing_ok=True)
            else:
                shutil.rmtree(child, ignore_errors=True)

    def _load_record(self, container: Path) -> ModelAsset:
        try:
            asset = ModelAsset.from_dict(read_json(self._record_path(container)))
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ModelAssetError("invalid_asset_record") from exc
        if asset.asset_id != container.name:
            raise ModelAssetError("asset_record_id_mismatch")
        return asset

    def _recover_staging(self) -> None:
        with self._lock:
            for container in sorted(self.staging_dir.iterdir()):
                if not container.is_dir() or container.is_symlink():
                    continue
                try:
                    asset = self._load_record(container)
                except ModelAssetError:
                    asset = ModelAsset(
                        asset_id=container.name,
                        provider="unknown",
                        repo_id="unknown/unknown",
                        requested_revision="",
                        resolved_commit="",
                        license="unknown",
                        security_status="rejected",
                        allow_patterns=(),
                        files=(),
                        manifest_sha256=_empty_manifest_sha256(),
                        status="quarantined",
                        created_at=_utc_now(),
                        failure_code="interrupted_staging_record_invalid",
                    )
                recovered = replace(
                    asset,
                    files=(),
                    manifest_sha256=_empty_manifest_sha256(),
                    security_status="rejected",
                    status="quarantined",
                    failure_code="interrupted_during_staging",
                )
                self._purge_staged_payload(container)
                self._write_record(container, recovered)
                destination = self.quarantine_dir / recovered.asset_id
                if destination.exists():
                    destination = self.quarantine_dir / (
                        f"{recovered.asset_id}-recovered-{uuid4().hex[:8]}"
                    )
                    recovered = replace(recovered, asset_id=destination.name)
                    self._write_record(container, recovered)
                os.replace(container, destination)

    def _new_asset(
        self,
        *,
        provider: str,
        repo_id: str,
        requested_revision: str,
        allow_patterns: tuple[str, ...],
    ) -> ModelAsset:
        return ModelAsset(
            asset_id=f"asset-{uuid4().hex[:12]}",
            provider=provider,
            repo_id=repo_id,
            requested_revision=requested_revision,
            resolved_commit="",
            license="unknown",
            security_status="pending",
            allow_patterns=allow_patterns,
            files=(),
            manifest_sha256=_empty_manifest_sha256(),
            status="staging",
            created_at=_utc_now(),
        )

    def _validate_request(
        self,
        provider: str,
        repo_id: str,
        requested_revision: str,
        allow_patterns: tuple[str, ...],
    ) -> tuple[str, str, str, tuple[str, ...]]:
        selected_provider = provider.strip().lower()
        selected_repo = repo_id.strip()
        selected_revision = requested_revision.strip().lower()
        if not PROVIDER_PATTERN.fullmatch(selected_provider):
            raise ModelAssetError("invalid_provider")
        if not REPO_ID_PATTERN.fullmatch(selected_repo) or any(
            part in {".", ".."} for part in selected_repo.split("/")
        ):
            raise ModelAssetError("invalid_repo_id")
        selected_patterns = _validate_patterns(allow_patterns)
        return selected_provider, selected_repo, selected_revision, selected_patterns

    def _staging_extras(self, container: Path) -> list[str]:
        return sorted(
            child.name
            for child in container.iterdir()
            if child.name not in {"asset.json", "files"}
        )

    def _scan_files(
        self,
        files_root: Path,
        allow_patterns: tuple[str, ...],
        forbidden_secret: bytes | None = None,
    ) -> tuple[ModelAssetFile, ...]:
        records: list[ModelAssetFile] = []
        total_bytes = 0

        def visit(directory: Path) -> None:
            nonlocal total_bytes
            for entry in sorted(os.scandir(directory), key=lambda item: item.name):
                path = Path(entry.path)
                mode = entry.stat(follow_symlinks=False).st_mode
                if stat.S_ISLNK(mode):
                    raise ModelAssetError("symlink_rejected")
                if stat.S_ISDIR(mode):
                    relative_dir = _safe_relative_path(
                        path.relative_to(files_root).as_posix()
                    )
                    if relative_dir:
                        visit(path)
                    continue
                if not stat.S_ISREG(mode):
                    raise ModelAssetError("non_regular_file_rejected")
                relative_path = _safe_relative_path(
                    path.relative_to(files_root).as_posix()
                )
                if not _matches_allowed(relative_path, allow_patterns):
                    raise ModelAssetError("file_not_allowlisted")
                size = int(entry.stat(follow_symlinks=False).st_size)
                if size < 0 or size > self.max_file_bytes:
                    raise ModelAssetError("file_size_limit_exceeded")
                digest = _sha256_rejecting_secret(path, forbidden_secret)
                _validate_file_type(path, relative_path, size)
                total_bytes += size
                if total_bytes > self.max_total_bytes:
                    raise ModelAssetError("asset_size_limit_exceeded")
                records.append(
                    ModelAssetFile(
                        relative_path=relative_path,
                        size_bytes=size,
                        sha256=digest,
                    )
                )
                if len(records) > self.max_files:
                    raise ModelAssetError("asset_file_count_exceeded")

        visit(files_root)
        if not records:
            raise ModelAssetError("asset_contains_no_files")
        if not any(Path(item.relative_path).suffix.lower() in MODEL_SUFFIXES for item in records):
            raise ModelAssetError("asset_contains_no_model_payload")
        return tuple(sorted(records, key=lambda item: item.relative_path))

    def _quarantine_staging(
        self, container: Path, asset: ModelAsset, failure_code: str
    ) -> ModelAsset:
        quarantined = replace(
            asset,
            files=(),
            manifest_sha256=_empty_manifest_sha256(),
            security_status="rejected",
            status="quarantined",
            failure_code=failure_code,
        )
        self._purge_staged_payload(container)
        self._write_record(container, quarantined)
        destination = self.quarantine_dir / quarantined.asset_id
        os.replace(container, destination)
        return quarantined

    def download(
        self,
        *,
        provider: str,
        repo_id: str,
        requested_revision: str,
        downloader: ModelAssetDownloader,
        allow_patterns: tuple[str, ...] = DEFAULT_ALLOW_PATTERNS,
        token: str | None = None,
    ) -> ModelAsset:
        if token is not None and (not isinstance(token, str) or len(token) > 4096):
            raise ModelAssetError("invalid_ephemeral_token")
        selected_provider, selected_repo, selected_revision, selected_patterns = (
            self._validate_request(
                provider, repo_id, requested_revision, tuple(allow_patterns)
            )
        )
        if token and any(
            token in value
            for value in (
                selected_provider,
                selected_repo,
                selected_revision,
                *selected_patterns,
            )
        ):
            raise ModelAssetError("request_metadata_contains_token")
        with self._lock:
            asset = self._new_asset(
                provider=selected_provider,
                repo_id=selected_repo,
                requested_revision=selected_revision,
                allow_patterns=selected_patterns,
            )
            container = self.staging_dir / asset.asset_id
            files_root = container / "files"
            files_root.mkdir(parents=True, exist_ok=False, mode=0o700)
            self._write_record(container, asset)
            try:
                if not COMMIT_PATTERN.fullmatch(selected_revision):
                    raise ModelAssetError("revision_not_immutable_commit")
                try:
                    result = downloader.download(
                        provider=selected_provider,
                        repo_id=selected_repo,
                        revision=selected_revision,
                        destination=files_root,
                        allow_patterns=selected_patterns,
                        token=token,
                    )
                except Exception:
                    raise ModelAssetError("downloader_failed") from None
                if not isinstance(result, DownloadResult):
                    raise ModelAssetError("invalid_downloader_result")
                resolved_commit = result.resolved_commit.strip().lower()
                if (
                    not COMMIT_PATTERN.fullmatch(resolved_commit)
                    or resolved_commit != selected_revision
                ):
                    raise ModelAssetError("resolved_commit_mismatch")
                license_name = result.license.strip()
                if (
                    not license_name
                    or len(license_name) > 200
                    or any(ord(character) < 32 for character in license_name)
                ):
                    raise ModelAssetError("invalid_or_missing_license")
                if token and token in license_name:
                    raise ModelAssetError("credential_material_detected")
                asset = replace(
                    asset,
                    resolved_commit=resolved_commit,
                    license=license_name,
                )
                if self._staging_extras(container):
                    raise ModelAssetError("staging_path_escape_detected")
                files = self._scan_files(
                    files_root,
                    selected_patterns,
                    token.encode("utf-8") if token else None,
                )
                active = replace(
                    asset,
                    resolved_commit=resolved_commit,
                    license=license_name,
                    security_status="verified",
                    files=files,
                    manifest_sha256=_manifest_sha256(files),
                    status="active",
                    failure_code=None,
                )
                self._write_record(container, active)
                destination = self.active_dir / active.asset_id
                os.replace(container, destination)
                return active
            except ModelAssetError as exc:
                failure_code = str(exc)
                self._quarantine_staging(container, asset, failure_code)
                raise ModelAssetError(
                    f"model_asset_quarantined:{asset.asset_id}:{failure_code}"
                ) from None
            except Exception:
                failure_code = "asset_validation_failed"
                if container.exists():
                    self._quarantine_staging(container, asset, failure_code)
                raise ModelAssetError(
                    f"model_asset_quarantined:{asset.asset_id}:{failure_code}"
                ) from None

    def _container_for(self, asset_id: str) -> Path:
        if not re.fullmatch(r"asset-[0-9a-f]{12}(?:-recovered-[0-9a-f]{8})?", asset_id):
            raise ModelAssetError("invalid_asset_id")
        active = self.active_dir / asset_id
        quarantined = self.quarantine_dir / asset_id
        if active.is_dir() and not active.is_symlink():
            return active
        if quarantined.is_dir() and not quarantined.is_symlink():
            return quarantined
        raise ModelAssetError("unknown_asset")

    def get(self, asset_id: str) -> ModelAsset:
        with self._lock:
            return self._load_record(self._container_for(asset_id))

    def list(self, *, include_quarantined: bool = True) -> list[ModelAsset]:
        with self._lock:
            assets: list[ModelAsset] = []
            locations = [self.active_dir]
            if include_quarantined:
                locations.append(self.quarantine_dir)
            for location in locations:
                for container in sorted(location.iterdir()):
                    if container.is_dir() and not container.is_symlink():
                        assets.append(self._load_record(container))
            return sorted(assets, key=lambda item: (item.created_at, item.asset_id))

    def list_assets(self, *, include_quarantined: bool = True) -> list[ModelAsset]:
        return self.list(include_quarantined=include_quarantined)

    def _integrity_errors(self, container: Path, asset: ModelAsset) -> tuple[str, ...]:
        errors: list[str] = []
        if asset.manifest_sha256 != _manifest_sha256(asset.files):
            errors.append("manifest_checksum_mismatch")
        files_root = container / "files"
        try:
            actual = self._scan_files(files_root, asset.allow_patterns)
        except (ModelAssetError, OSError):
            errors.append("unsafe_or_unreadable_file_tree")
            return tuple(errors)
        expected_by_path = {item.relative_path: item for item in asset.files}
        actual_by_path = {item.relative_path: item for item in actual}
        if set(expected_by_path) != set(actual_by_path):
            errors.append("file_set_mismatch")
        for relative_path in sorted(set(expected_by_path) & set(actual_by_path)):
            expected = expected_by_path[relative_path]
            observed = actual_by_path[relative_path]
            if expected.size_bytes != observed.size_bytes:
                errors.append(f"size_mismatch:{relative_path}")
            if expected.sha256 != observed.sha256:
                errors.append(f"sha256_mismatch:{relative_path}")
        return tuple(errors)

    def verify(self, asset_id: str) -> AssetVerification:
        with self._lock:
            container = self._container_for(asset_id)
            asset = self._load_record(container)
            if asset.status != "active" or container.parent != self.active_dir:
                return AssetVerification(
                    asset=asset, ok=False, errors=("asset_not_active",)
                )
            errors = self._integrity_errors(container, asset)
            if not errors:
                return AssetVerification(asset=asset, ok=True, errors=())
            quarantined = replace(
                asset,
                security_status="tampered",
                status="quarantined",
                failure_code="integrity_verification_failed",
            )
            self._write_record(container, quarantined)
            destination = self.quarantine_dir / asset.asset_id
            os.replace(container, destination)
            return AssetVerification(asset=quarantined, ok=False, errors=errors)

    def asset_files_dir(self, asset_id: str) -> Path:
        asset = self.get(asset_id)
        if asset.status != "active" or asset.security_status != "verified":
            raise ModelAssetError("asset_not_active")
        return self.active_dir / asset.asset_id / "files"
