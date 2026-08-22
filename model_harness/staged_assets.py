from __future__ import annotations

import hashlib
import io
import os
import re
import stat
import unicodedata
import wave
import zipfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath, PureWindowsPath
from threading import Lock
from typing import Any
from uuid import uuid4

from .errors import ContractError
from .io_utils import read_json, write_json


ASSET_SCHEMA_VERSION = "0.1"
STAGED_ASSET_KIND = "audio_sample_zip"
STAGED_ASSET_STATUSES = frozenset(
    {"staged", "quarantined", "consumed", "superseded"}
)
_WINDOWS_DRIVE = re.compile(r"^[A-Za-z]:")


@dataclass(frozen=True)
class StagedAssetLimits:
    """Hard limits applied before a sample archive can be staged.

    The archive is inspected in memory and retained as one read-only file. It
    is deliberately not extracted into the task workspace.
    """

    max_archive_bytes: int = 32 * 1024 * 1024
    max_files: int = 256
    max_file_bytes: int = 8 * 1024 * 1024
    max_uncompressed_bytes: int = 64 * 1024 * 1024
    max_compression_ratio: float = 250.0
    max_member_name_length: int = 512
    min_duration_seconds: float = 0.02
    max_duration_seconds: float = 30.0
    min_sample_rate_hz: int = 4_000
    max_sample_rate_hz: int = 192_000

    def __post_init__(self) -> None:
        integer_limits = (
            self.max_archive_bytes,
            self.max_files,
            self.max_file_bytes,
            self.max_uncompressed_bytes,
            self.max_member_name_length,
        )
        if any(value <= 0 for value in integer_limits):
            raise ValueError("staged asset size and count limits must be positive")
        if self.max_compression_ratio <= 0:
            raise ValueError("max_compression_ratio must be positive")
        if not 0 <= self.min_duration_seconds <= self.max_duration_seconds:
            raise ValueError("audio duration limits are invalid")
        if not 0 < self.min_sample_rate_hz <= self.max_sample_rate_hz:
            raise ValueError("audio sample-rate limits are invalid")


class StagedAssetRejected(ContractError):
    """A sample payload was quarantined instead of being staged."""

    def __init__(self, message: str, asset: dict[str, Any]) -> None:
        super().__init__(message)
        self.asset = asset
        self.asset_id = str(asset["asset_id"])


class StagedAssetNotFound(ContractError):
    """The requested staged asset does not exist in this task."""


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _canonical_member_name(name: str, *, limit: int) -> tuple[str, str]:
    """Return a display path and a case-folded collision key.

    ZIP names are normalized only for comparison. Any spelling that would
    depend on extraction-platform behavior is rejected rather than repaired.
    """

    if not name or "\x00" in name:
        raise ValueError("ZIP contains an empty or NUL member path")
    if len(name) > limit:
        raise ValueError(f"ZIP member path exceeds {limit} characters")
    normalized = unicodedata.normalize("NFC", name.replace("\\", "/"))
    if normalized.startswith(("/", "//")):
        raise ValueError("ZIP contains an absolute member path")
    if PureWindowsPath(name).is_absolute() or _WINDOWS_DRIVE.match(name):
        raise ValueError("ZIP contains a Windows absolute member path")
    directory_spelling = normalized.endswith("/")
    selected = normalized[:-1] if directory_spelling else normalized
    parts = selected.split("/")
    if not selected or any(part in {"", ".", ".."} for part in parts):
        raise ValueError("ZIP contains path traversal or ambiguous path segments")
    if any(len(part) > 255 for part in parts):
        raise ValueError("ZIP contains an overlong path component")
    canonical = PurePosixPath(*parts).as_posix()
    return canonical, canonical.casefold()


def _member_kind(info: zipfile.ZipInfo) -> str:
    unix_mode = info.external_attr >> 16
    file_type = stat.S_IFMT(unix_mode)
    if file_type == stat.S_IFLNK:
        return "symlink"
    if info.is_dir() or file_type == stat.S_IFDIR:
        return "directory"
    if file_type not in {0, stat.S_IFREG}:
        return "special"
    return "file"


def _read_member(
    archive: zipfile.ZipFile,
    info: zipfile.ZipInfo,
    *,
    max_bytes: int,
) -> bytes:
    chunks: list[bytes] = []
    observed = 0
    with archive.open(info, "r") as handle:
        while True:
            chunk = handle.read(min(1024 * 1024, max_bytes + 1 - observed))
            if not chunk:
                break
            observed += len(chunk)
            if observed > max_bytes:
                raise ValueError(
                    f"ZIP member exceeds the {max_bytes}-byte streamed-read limit"
                )
            chunks.append(chunk)
    if observed != info.file_size:
        raise ValueError("ZIP member size differs from its central-directory record")
    return b"".join(chunks)


def _inspect_pcm_wav(payload: bytes, relative_path: str) -> dict[str, Any]:
    try:
        with wave.open(io.BytesIO(payload), "rb") as audio:
            channels = audio.getnchannels()
            sample_width = audio.getsampwidth()
            sample_rate = audio.getframerate()
            frame_count = audio.getnframes()
            compression = audio.getcomptype()
            if compression != "NONE":
                raise ValueError("only uncompressed PCM WAV is accepted")
            if channels <= 0 or sample_width not in {1, 2, 3, 4}:
                raise ValueError("WAV has unsupported PCM channel/sample-width metadata")
            if sample_rate <= 0 or frame_count <= 0:
                raise ValueError("WAV must contain non-empty audio frames")
            decoded = audio.readframes(frame_count)
            expected_bytes = frame_count * channels * sample_width
            if len(decoded) != expected_bytes:
                raise ValueError("WAV PCM frames are truncated")
    except (EOFError, wave.Error) as exc:
        raise ValueError(f"damaged WAV: {relative_path}") from exc
    duration = frame_count / sample_rate
    return {
        "relative_path": relative_path,
        "sha256": hashlib.sha256(payload).hexdigest(),
        "size_bytes": len(payload),
        "channels": channels,
        "sample_width_bits": sample_width * 8,
        "sample_rate_hz": sample_rate,
        "frame_count": frame_count,
        "duration_seconds": round(duration, 6),
        "encoding": "PCM",
    }


class StagedDataAssetStore:
    """Persistent, task-scoped storage for safely inspected sample archives.

    This component has no Run or Dataset dependency. A successful call stores
    the original ZIP as a read-only blob plus an inspection report; it never
    extracts the archive and never imports it as formal training data.
    """

    def __init__(
        self,
        task_dir: Path,
        task_id: str,
        *,
        limits: StagedAssetLimits | None = None,
    ) -> None:
        selected_task_id = str(task_id).strip()
        if not selected_task_id:
            raise ValueError("task_id is required")
        self.task_dir = Path(task_dir)
        self.task_id = selected_task_id
        self.limits = limits or StagedAssetLimits()
        self.assets_dir = self.task_dir / "staged_assets"
        self.assets_dir.mkdir(parents=True, exist_ok=True)
        if self.assets_dir.is_symlink():
            raise ContractError("staged_assets directory must not be a symlink")
        self._lock = Lock()

    def stage_audio_zip(
        self,
        payload: bytes,
        filename: str,
        spec_revision: int,
    ) -> dict[str, Any]:
        """Inspect and persist an audio sample ZIP.

        Validation failures create a durable ``quarantined`` evidence record
        without retaining the rejected payload, then raise
        :class:`StagedAssetRejected`.
        """

        if isinstance(spec_revision, bool) or not isinstance(spec_revision, int):
            raise ContractError("spec_revision must be a positive integer")
        if spec_revision <= 0:
            raise ContractError("spec_revision must be a positive integer")
        if not isinstance(payload, bytes):
            raise ContractError("staged asset payload must be bytes")

        source_filename = str(filename).strip()
        digest = hashlib.sha256(payload).hexdigest()
        with self._lock:
            existing = self._find_by_digest(digest, spec_revision)
            if existing is not None:
                if existing["status"] == "quarantined":
                    message = str(
                        existing.get("report", {}).get(
                            "failure_message", "sample archive was quarantined"
                        )
                    )
                    raise StagedAssetRejected(message, existing)
                return existing

            asset_id = f"asset-{uuid4().hex[:12]}"
            created_at = _now()
            try:
                display_filename = self._validate_source(
                    payload, source_filename, self.limits
                )
                report = self._inspect_archive(payload)
            except (ValueError, zipfile.BadZipFile, RuntimeError, NotImplementedError) as exc:
                message = str(exc) or "sample ZIP validation failed"
                asset = self._asset_record(
                    asset_id=asset_id,
                    spec_revision=spec_revision,
                    source_filename=Path(source_filename.replace("\\", "/")).name,
                    sha256=digest,
                    size_bytes=len(payload),
                    status="quarantined",
                    created_at=created_at,
                    archive=None,
                    report={
                        "schema_version": ASSET_SCHEMA_VERSION,
                        "status": "failed",
                        "failure_code": "unsafe_or_invalid_audio_zip",
                        "failure_message": message,
                        "retained_payload": False,
                        "gates": [
                            {
                                "gate": "safe_audio_zip",
                                "passed": False,
                                "message": message,
                            }
                        ],
                    },
                )
                self._persist(asset, payload=None)
                raise StagedAssetRejected(message, asset) from exc

            asset = self._asset_record(
                asset_id=asset_id,
                spec_revision=spec_revision,
                source_filename=display_filename,
                sha256=digest,
                size_bytes=len(payload),
                status="staged",
                created_at=created_at,
                archive={
                    "relative_path": "source.zip",
                    "size_bytes": len(payload),
                    "read_only": True,
                    "extracted": False,
                },
                report=report,
            )
            self._persist(asset, payload=payload)
            return asset

    # A short alias keeps Workspace integration readable while the public
    # endpoint still names the resource "staged-assets".
    stage = stage_audio_zip

    def list_assets(self, *, status: str | None = None) -> list[dict[str, Any]]:
        if status is not None and status not in STAGED_ASSET_STATUSES:
            raise ContractError(f"unknown staged asset status: {status}")
        assets: list[dict[str, Any]] = []
        for metadata_path in self.assets_dir.glob("asset-*/asset.json"):
            asset = self._read_record(metadata_path)
            if status is None or asset["status"] == status:
                assets.append(asset)
        return sorted(
            assets,
            key=lambda item: (str(item.get("created_at", "")), item["asset_id"]),
        )

    def get_asset(self, asset_id: str) -> dict[str, Any]:
        selected = self._validate_asset_id(asset_id)
        metadata_path = self.assets_dir / selected / "asset.json"
        if not metadata_path.is_file() or metadata_path.is_symlink():
            raise StagedAssetNotFound(f"staged asset not found: {selected}")
        return self._read_record(metadata_path)

    # Natural names for callers that model this component as a repository.
    list = list_assets
    get = get_asset

    def archive_path(self, asset_id: str) -> Path:
        asset = self.get_asset(asset_id)
        if asset["status"] == "quarantined" or not asset.get("archive"):
            raise ContractError("quarantined staged assets do not retain an archive")
        selected = self._validate_asset_id(asset_id)
        target = self.assets_dir / selected / "source.zip"
        if not target.is_file() or target.is_symlink():
            raise ContractError("staged asset archive is missing or unsafe")
        if target.parent.resolve() != (self.assets_dir / selected).resolve():
            raise ContractError("staged asset archive escaped its asset directory")
        return target

    def mark_consumed(self, asset_id: str) -> dict[str, Any]:
        return self._transition(asset_id, "consumed", allowed_from={"staged"})

    def mark_superseded(self, asset_id: str) -> dict[str, Any]:
        return self._transition(
            asset_id,
            "superseded",
            allowed_from={"staged", "consumed"},
        )

    @staticmethod
    def _validate_source(
        payload: bytes,
        filename: str,
        limits: StagedAssetLimits,
    ) -> str:
        if not payload:
            raise ValueError("sample ZIP is empty")
        if len(payload) > limits.max_archive_bytes:
            raise ValueError(
                f"sample ZIP exceeds the {limits.max_archive_bytes}-byte upload limit"
            )
        if not filename:
            raise ValueError("source filename is required")
        normalized = filename.replace("\\", "/")
        if (
            normalized.startswith("/")
            or PureWindowsPath(filename).is_absolute()
            or _WINDOWS_DRIVE.match(filename)
            or "/" in normalized
        ):
            raise ValueError("source filename must be a basename, not a path")
        if not normalized.casefold().endswith(".zip"):
            raise ValueError("audio samples must be uploaded as a ZIP archive")
        if not zipfile.is_zipfile(io.BytesIO(payload)):
            raise ValueError("uploaded payload is not a valid ZIP archive")
        return normalized

    def _inspect_archive(self, payload: bytes) -> dict[str, Any]:
        limits = self.limits
        inventory: list[dict[str, Any]] = []
        seen: dict[str, str] = {}
        file_paths: set[str] = set()
        directory_paths: set[str] = set()
        declared_total = 0

        with zipfile.ZipFile(io.BytesIO(payload), "r") as archive:
            for info in archive.infolist():
                relative_path, collision_key = _canonical_member_name(
                    info.filename,
                    limit=limits.max_member_name_length,
                )
                if collision_key in seen:
                    raise ValueError(
                        "ZIP contains duplicate normalized paths: "
                        f"{seen[collision_key]} and {relative_path}"
                    )
                seen[collision_key] = relative_path
                kind = _member_kind(info)
                if kind == "symlink":
                    raise ValueError(f"ZIP symlinks are not accepted: {relative_path}")
                if kind == "special":
                    raise ValueError(
                        f"ZIP special filesystem entries are not accepted: {relative_path}"
                    )
                if info.flag_bits & 0x1:
                    raise ValueError(f"encrypted ZIP members are not accepted: {relative_path}")
                if info.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
                    raise ValueError(
                        f"unsupported ZIP compression method for: {relative_path}"
                    )

                parent_keys = [
                    PurePosixPath(*PurePosixPath(relative_path).parts[:index])
                    .as_posix()
                    .casefold()
                    for index in range(1, len(PurePosixPath(relative_path).parts))
                ]
                if any(parent in file_paths for parent in parent_keys):
                    raise ValueError(
                        f"ZIP path is nested below a file entry: {relative_path}"
                    )
                if kind == "directory":
                    if collision_key in file_paths:
                        raise ValueError(f"ZIP file/directory path collision: {relative_path}")
                    directory_paths.add(collision_key)
                    continue
                if collision_key in directory_paths:
                    raise ValueError(f"ZIP file/directory path collision: {relative_path}")
                file_paths.add(collision_key)
                if any(
                    existing.startswith(f"{collision_key}/")
                    for existing in file_paths - {collision_key}
                ):
                    raise ValueError(
                        f"ZIP file shadows an existing directory path: {relative_path}"
                    )
                if len(file_paths) > limits.max_files:
                    raise ValueError(
                        f"ZIP contains more than {limits.max_files} files"
                    )
                if not relative_path.casefold().endswith(".wav"):
                    raise ValueError(f"non-WAV sample is not accepted: {relative_path}")
                if info.file_size < 0 or info.file_size > limits.max_file_bytes:
                    raise ValueError(
                        f"WAV exceeds the {limits.max_file_bytes}-byte file limit: "
                        f"{relative_path}"
                    )
                declared_total += info.file_size
                if declared_total > limits.max_uncompressed_bytes:
                    raise ValueError(
                        "ZIP exceeds the total uncompressed-byte limit of "
                        f"{limits.max_uncompressed_bytes}"
                    )
                ratio = info.file_size / max(info.compress_size, 1)
                if (
                    info.file_size >= 1024 * 1024
                    and ratio > limits.max_compression_ratio
                ):
                    raise ValueError(
                        f"suspicious ZIP compression ratio for: {relative_path}"
                    )

                wav_payload = _read_member(
                    archive,
                    info,
                    # Trust neither the declared length nor the decompressor:
                    # reading one byte beyond this value is enough to reject a
                    # size mismatch without inflating up to the global limit.
                    max_bytes=info.file_size,
                )
                inspected = _inspect_pcm_wav(wav_payload, relative_path)
                duration = float(inspected["duration_seconds"])
                if not limits.min_duration_seconds <= duration <= limits.max_duration_seconds:
                    raise ValueError(
                        f"WAV duration is outside the accepted range: {relative_path}"
                    )
                sample_rate = int(inspected["sample_rate_hz"])
                if not limits.min_sample_rate_hz <= sample_rate <= limits.max_sample_rate_hz:
                    raise ValueError(
                        f"WAV sample rate is outside the accepted range: {relative_path}"
                    )
                inventory.append(inspected)

        if not inventory:
            raise ValueError("sample ZIP must contain at least one PCM WAV file")

        total_duration = sum(float(item["duration_seconds"]) for item in inventory)
        labels = sorted(
            {
                PurePosixPath(item["relative_path"]).parts[-2]
                for item in inventory
                if len(PurePosixPath(item["relative_path"]).parts) >= 2
            }
        )
        return {
            "schema_version": ASSET_SCHEMA_VERSION,
            "status": "passed",
            "kind": STAGED_ASSET_KIND,
            "file_count": len(inventory),
            "total_uncompressed_bytes": declared_total,
            "total_duration_seconds": round(total_duration, 6),
            "sample_rates_hz": sorted(
                {int(item["sample_rate_hz"]) for item in inventory}
            ),
            "channel_counts": sorted({int(item["channels"]) for item in inventory}),
            "labels_inferred_from_parent_folders": labels,
            "files": inventory,
            "retained_payload": True,
            "extracted": False,
            "gates": [
                {"gate": "safe_member_paths", "passed": True},
                {"gate": "archive_limits", "passed": True},
                {"gate": "pcm_wav_decode", "passed": True},
                {"gate": "read_only_archive_staging", "passed": True},
            ],
        }

    def _asset_record(
        self,
        *,
        asset_id: str,
        spec_revision: int,
        source_filename: str,
        sha256: str,
        size_bytes: int,
        status: str,
        created_at: str,
        archive: dict[str, Any] | None,
        report: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "schema_version": ASSET_SCHEMA_VERSION,
            "asset_id": asset_id,
            "task_id": self.task_id,
            "spec_revision": spec_revision,
            "kind": STAGED_ASSET_KIND,
            "source_filename": source_filename,
            "sha256": sha256,
            "size_bytes": size_bytes,
            "status": status,
            "created_at": created_at,
            "updated_at": created_at,
            "archive": archive,
            "report": report,
            "limits": asdict(self.limits),
        }

    def _persist(self, asset: dict[str, Any], payload: bytes | None) -> None:
        asset_id = self._validate_asset_id(str(asset["asset_id"]))
        final_dir = self.assets_dir / asset_id
        temporary_dir = self.assets_dir / f".{asset_id}.{uuid4().hex}.tmp"
        temporary_dir.mkdir(parents=False, exist_ok=False)
        try:
            if payload is not None:
                archive_path = temporary_dir / "source.zip"
                with archive_path.open("xb") as handle:
                    handle.write(payload)
                    handle.flush()
                    os.fsync(handle.fileno())
                archive_path.chmod(0o444)
            write_json(temporary_dir / "asset.json", asset)
            os.replace(temporary_dir, final_dir)
        finally:
            if temporary_dir.exists():
                for child in temporary_dir.iterdir():
                    child.unlink(missing_ok=True)
                temporary_dir.rmdir()

    def _read_record(self, metadata_path: Path) -> dict[str, Any]:
        try:
            asset = read_json(metadata_path)
        except (OSError, ValueError) as exc:
            raise ContractError(
                f"staged asset metadata is unreadable: {metadata_path.parent.name}"
            ) from exc
        required = {
            "asset_id",
            "task_id",
            "spec_revision",
            "sha256",
            "status",
            "report",
        }
        if not isinstance(asset, dict) or not required.issubset(asset):
            raise ContractError(
                f"staged asset metadata is incomplete: {metadata_path.parent.name}"
            )
        if asset["task_id"] != self.task_id:
            raise ContractError("staged asset task ownership mismatch")
        if asset["asset_id"] != metadata_path.parent.name:
            raise ContractError("staged asset identity mismatch")
        if asset["status"] not in STAGED_ASSET_STATUSES:
            raise ContractError("staged asset has an invalid persisted status")
        return asset

    def _find_by_digest(
        self, sha256: str, spec_revision: int
    ) -> dict[str, Any] | None:
        for asset in self.list_assets():
            if asset["sha256"] == sha256 and asset["spec_revision"] == spec_revision:
                return asset
        return None

    def _transition(
        self,
        asset_id: str,
        target_status: str,
        *,
        allowed_from: set[str],
    ) -> dict[str, Any]:
        if target_status not in STAGED_ASSET_STATUSES:
            raise ContractError(f"unknown staged asset status: {target_status}")
        with self._lock:
            asset = self.get_asset(asset_id)
            if asset["status"] == target_status:
                return asset
            if asset["status"] not in allowed_from:
                raise ContractError(
                    f"cannot transition staged asset from {asset['status']} "
                    f"to {target_status}"
                )
            asset["status"] = target_status
            asset["updated_at"] = _now()
            write_json(
                self.assets_dir / self._validate_asset_id(asset_id) / "asset.json",
                asset,
            )
            return asset

    @staticmethod
    def _validate_asset_id(asset_id: str) -> str:
        selected = str(asset_id).strip()
        if not re.fullmatch(r"asset-[a-f0-9]{12}", selected):
            raise StagedAssetNotFound(f"invalid staged asset id: {selected}")
        return selected


# Preferred concise name for new integrations.
StagedAssetStore = StagedDataAssetStore


__all__ = [
    "ASSET_SCHEMA_VERSION",
    "STAGED_ASSET_KIND",
    "STAGED_ASSET_STATUSES",
    "StagedAssetLimits",
    "StagedAssetNotFound",
    "StagedAssetRejected",
    "StagedAssetStore",
    "StagedDataAssetStore",
]
