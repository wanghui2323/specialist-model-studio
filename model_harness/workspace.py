from __future__ import annotations

import hashlib
import base64
import binascii
import io
import json
import os
import re
import shutil
import time
import zipfile
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from threading import RLock
from typing import Any, Mapping
from uuid import uuid4

try:  # POSIX local workspaces
    import fcntl  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - exercised on Windows
    fcntl = None  # type: ignore[assignment]

try:  # Windows local workspaces
    import msvcrt  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - exercised on POSIX
    msvcrt = None  # type: ignore[assignment]

DATASET_UPLOAD_LOCK_TIMEOUT_SECONDS = 300.0
DATASET_UPLOAD_LOCK_POLL_SECONDS = 0.05

from PIL import Image, UnidentifiedImageError

from .blockers import BlockerStore, verify_recipe_unavailable_evidence
from .feasibility_store import FeasibilityStore
from .environment_resolver import resolve_environment_dependencies
from .contracts import (
    ApprovalDecision,
    ApprovalDecisionIntegrityError,
    ContractRevision,
    ContractRevisionConflictError,
    ContractRevisionIntegrityError,
    validate_contract,
)
from .data_adapters import DataAdapterRegistry, default_data_adapter_registry
from .delivery_authorizations import (
    DeliveryAuthorizationError,
    DeliveryAuthorizationStore,
    delivery_scope_sha256,
)
from .errors import ContractError, HarnessError
from .io_utils import read_json, sha256_file, write_json
from .huggingface_assets import (
    HuggingFaceHubDownloader,
    download_huggingface_asset,
    resolve_training_asset,
)
from .huggingface_catalog import HuggingFaceCatalog
from .github_source import GitHubSourceProvider
from .inference_inputs import InferenceInputError, InferenceInputStore
from .model_assets import ModelAssetError, ModelAssetStore
from .model_source_store import ModelSourceStore, model_search_contains_credentials
from .model_sources import (
    ModelSourceError,
    ModelSourceUpstreamError,
    ResolvedSource,
    SourceProvider,
    collect_source_documents,
    evaluate_license_policy,
    parse_model_source_reference,
    source_candidate_id,
)
from .huggingface_source import HuggingFaceSourceProvider
from .recipe_builder import RecipeScaffoldBuilder
from .recipe_factory import RecipeFactory
from .repository_analysis import (
    ANALYZER_VERSION,
    RepositoryAnalysisError,
    StaticRepositoryAnalyzer,
)
from .repository_analysis_store import (
    BindingAnalysisAttemptStore,
    RepositoryAnalysisStore,
)
from .resource_feasibility import (
    EnvironmentLock,
    ResourceProbe,
    evaluate_resource_fit,
)
from .runner import new_run_id
from .service import RunService
from .sample_inference import SampleInferenceBlocked
from .state import ACTIVE_STATUSES
from .staged_assets import StagedAssetNotFound, StagedAssetStore
from .task_specs import (
    build_task_spec_revision,
    capability_for_family,
    modality_from_candidate_families,
    normalize_family,
)
from .training_plans import StaleTrainingPlanError, TrainingPlanStore
from .training_plan_compiler import compile_training_plan


TASK_SCHEMA_VERSION = "0.2"
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
MAX_ARCHIVE_BYTES = 200 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 750 * 1024 * 1024
MAX_IMAGE_FILES = 10_000
MIN_IMAGES_PER_CLASS = 5

_MODEL_SEARCH_TERMS = {
    ("image", "classification"): ("image classification", "image-classification"),
    ("image", "ocr"): ("optical character recognition OCR", "image-to-text"),
    ("image", "object_detection"): ("object detection training", "object-detection"),
    ("image", "segmentation"): ("image segmentation training", "image-segmentation"),
    ("audio", "classification"): ("audio classification keyword spotting", "audio-classification"),
    ("audio", "speech_recognition"): ("automatic speech recognition", "automatic-speech-recognition"),
    ("audio", "speech_synthesis"): ("text to speech training", "text-to-speech"),
    ("tabular", "classification"): ("tabular classification training", None),
    ("tabular", "regression"): ("tabular regression training", None),
    ("time_series", "forecasting"): ("time series forecasting training", "time-series-forecasting"),
    ("text", "classification"): ("text classification training", "text-classification"),
    ("text", "named_entity_recognition"): ("named entity recognition training", "token-classification"),
    ("specialist", "anomaly_detection"): ("anomaly detection training", None),
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_digest(value: Mapping[str, Any]) -> str:
    """Return a stable digest for one JSON evidence snapshot."""

    encoded = json.dumps(
        dict(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _model_search_plan(
    task: dict[str, Any],
    query: str | None,
) -> dict[str, Any]:
    raw_query = str(query or "").strip()
    if len(raw_query) > 160 or any(ord(character) < 32 for character in raw_query):
        raise ContractError("模型搜索词无效")
    if model_search_contains_credentials(raw_query):
        raise ContractError("模型搜索词包含疑似凭据，请移除后重试")
    capability = task.get("capability_request", {})
    modality = str(capability.get("modality") or "specialist").strip().lower()
    objective = str(capability.get("objective") or "custom").strip().lower()
    fallback, pipeline_tag = _MODEL_SEARCH_TERMS.get(
        (modality, objective),
        (f"{modality} {objective} model training", None),
    )
    # Chinese business descriptions are valuable context for the user but are
    # weak direct queries for the two English-first provider catalogs. Keep the
    # original visible and use a deterministic capability query for providers.
    ascii_letters = sum(
        character.isascii() and character.isalpha() for character in raw_query
    )
    effective = raw_query if raw_query and ascii_letters >= 3 else fallback
    if model_search_contains_credentials(effective):
        raise ContractError("模型搜索词包含疑似凭据，请移除后重试")
    return {
        "user_query": raw_query or None,
        "effective_query": effective,
        "pipeline_tag": pipeline_tag,
        "derived_from": {
            "modality": modality,
            "objective": objective,
            "task_spec_revision": int(task.get("current_spec_revision") or 0),
        },
    }


def _rank_model_source_candidate(candidate: dict[str, Any]) -> tuple[int, int, str]:
    known_license = 1 if candidate.get("license_status") == "known" else 0
    popularity = candidate.get("popularity") or {}
    popularity_value = int(popularity.get("downloads") or popularity.get("stars") or 0)
    return (-known_license, -popularity_value, str(candidate.get("repository") or ""))


def _decorate_model_source_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    value = deepcopy(candidate)
    reasons: list[str] = []
    cautions: list[str] = []
    if value.get("license_status") == "known":
        reasons.append(f"目录声明许可证 {value.get('license')}")
    else:
        cautions.append("许可证未知，绑定后仍会阻断训练计划")
    popularity = value.get("popularity") or {}
    if value.get("provider") == "huggingface":
        reasons.append(f"Hugging Face 任务标签：{value.get('task_tag') or 'unknown'}")
        if int(popularity.get("downloads") or 0) > 0:
            reasons.append(f"目录记录 {int(popularity['downloads']):,} 次下载")
    else:
        reasons.append("来自 GitHub 官方仓库搜索")
        cautions.append("GitHub Tree 大小可能只包含 Git LFS 指针，绑定后会明确标注")
        if int(popularity.get("stars") or 0) > 0:
            reasons.append(f"目录记录 {int(popularity['stars']):,} Stars")
    cautions.append("尚未完成固定版本的仓库分析与本机资源适配")
    value["why_shortlisted"] = reasons
    value["cautions"] = cautions
    value["selection_state"] = "needs_user_confirmation"
    return value


def _model_source_error_message(code: str) -> str:
    lowered = code.lower()
    if "not_found" in lowered:
        return "没有找到该公开仓库或版本；请检查地址、权限或 revision。"
    if "authentication" in lowered or "private" in lowered:
        return "该来源需要权限；可提供仅用于本次请求的 Token 后重试。"
    if "rate_limit" in lowered or "rate_limited" in lowered:
        return "官方目录当前触发限流；请稍后重试或提供仅用于本次请求的 Token。"
    if "license" in lowered:
        return "模型来源的许可证信息不足，当前不能进入后续训练计划。"
    if "truncated" in lowered or "incomplete" in lowered:
        return "官方接口返回了不完整仓库清单；系统已停止绑定以避免错误分析。"
    if "digest" in lowered or "mismatch" in lowered:
        return "来源内容与固定版本证据不一致；系统已停止绑定。"
    return "官方模型来源请求失败；失败事实已保存，可在同一任务中重试。"


def _canonical_model_source_blocker_code(reason_code: str) -> str:
    lowered = reason_code.lower()
    if "license" in lowered:
        return "blocked_license"
    if any(marker in lowered for marker in ("digest", "mismatch", "tamper")):
        return "blocked_security"
    return "blocked_repository"


def _license_policy(license_name: str, license_status: str) -> dict[str, Any]:
    return evaluate_license_policy(license_name, license_status)


def _safe_slug(value: str, fallback: str = "item") -> str:
    slug = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff._-]+", "-", value).strip("-.")
    return slug[:72] or fallback


def _deep_update(target: dict[str, Any], changes: dict[str, Any]) -> None:
    """Apply trusted nested contract overrides without discarding defaults."""

    for key, value in changes.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _deep_update(target[key], value)
        else:
            target[key] = deepcopy(value)


def _safe_zip_parts(name: str) -> tuple[str, ...] | None:
    path = PurePosixPath(name.replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts:
        raise ContractError(f"压缩包包含不安全路径：{name}")
    parts = tuple(part for part in path.parts if part not in {"", "."})
    if not parts or any(part.startswith(".") for part in parts):
        return None
    if "__MACOSX" in parts:
        return None
    return parts


def _archive_entries(archive: zipfile.ZipFile) -> list[tuple[zipfile.ZipInfo, tuple[str, ...]]]:
    candidates: list[tuple[zipfile.ZipInfo, tuple[str, ...]]] = []
    uncompressed = 0
    for info in archive.infolist():
        if info.is_dir():
            continue
        parts = _safe_zip_parts(info.filename)
        if parts is None or Path(parts[-1]).suffix.lower() not in IMAGE_EXTENSIONS:
            continue
        uncompressed += int(info.file_size)
        if uncompressed > MAX_UNCOMPRESSED_BYTES:
            raise ContractError("解压后的图片总量超过750MB安全上限")
        candidates.append((info, parts))
    if len(candidates) > MAX_IMAGE_FILES:
        raise ContractError(f"图片数量超过{MAX_IMAGE_FILES}张安全上限")
    if not candidates:
        raise ContractError("ZIP中没有找到PNG/JPG/JPEG/WEBP/BMP图片")

    first_parts = {parts[0] for _, parts in candidates}
    drop_common_root = len(first_parts) == 1 and all(len(parts) >= 3 for _, parts in candidates)
    normalized: list[tuple[zipfile.ZipInfo, tuple[str, ...]]] = []
    for info, parts in candidates:
        selected = parts[1:] if drop_common_root else parts
        if len(selected) < 2:
            raise ContractError(
                "图片必须按 类别/图片.jpg 组织；ZIP根目录下不能直接放图片"
            )
        normalized.append((info, selected))
    return normalized


def import_image_archive(
    datasets_dir: Path,
    payload: bytes,
    filename: str,
) -> tuple[dict[str, Any], Path]:
    if not payload:
        raise ContractError("上传文件为空")
    if len(payload) > MAX_ARCHIVE_BYTES:
        raise ContractError("ZIP文件超过200MB上传上限")
    if not filename.lower().endswith(".zip"):
        raise ContractError("当前只支持ZIP格式的数据集")

    dataset_id = f"dataset-{uuid4().hex[:10]}"
    temporary_dir = datasets_dir / f".{dataset_id}.tmp"
    final_dir = datasets_dir / dataset_id
    files_dir = temporary_dir / "files"
    files_dir.mkdir(parents=True, exist_ok=False)
    samples: list[dict[str, Any]] = []
    rejected: list[dict[str, str]] = []
    dimensions: list[tuple[int, int]] = []
    modes: Counter[str] = Counter()
    hashes: dict[str, list[tuple[str, str]]] = defaultdict(list)
    duplicate_hashes: set[str] = set()

    try:
        try:
            archive = zipfile.ZipFile(io.BytesIO(payload))
        except zipfile.BadZipFile as exc:
            raise ContractError("上传文件不是有效ZIP") from exc
        with archive:
            entries = _archive_entries(archive)
            for index, (info, parts) in enumerate(entries, start=1):
                label = parts[0].strip()
                if not label:
                    rejected.append({"path": info.filename, "reason": "类别目录为空"})
                    continue
                raw = archive.read(info)
                digest = hashlib.sha256(raw).hexdigest()
                try:
                    with Image.open(io.BytesIO(raw)) as image:
                        image.load()
                        width, height = image.size
                        mode = image.mode
                        if width < 4 or height < 4:
                            raise ValueError("图片尺寸小于4×4")
                except (UnidentifiedImageError, OSError, ValueError) as exc:
                    rejected.append({"path": info.filename, "reason": str(exc)})
                    continue

                previous = hashes.get(digest, [])
                if previous:
                    if any(previous_label != label for previous_label, _ in previous):
                        raise ContractError(
                            "发现相同图片被放入不同类别，请先修正标签冲突"
                        )
                    duplicate_hashes.add(digest)
                    hashes[digest].append((label, info.filename))
                    rejected.append(
                        {
                            "path": info.filename,
                            "reason": f"与 {previous[0][1]} 内容重复，已从划分中排除",
                        }
                    )
                    continue

                class_dir = files_dir / _safe_slug(label, "class")
                class_dir.mkdir(parents=True, exist_ok=True)
                suffix = Path(parts[-1]).suffix.lower()
                target_name = f"{index:05d}-{_safe_slug(Path(parts[-1]).stem, 'image')}{suffix}"
                target = class_dir / target_name
                target.write_bytes(raw)
                relative = target.relative_to(temporary_dir).as_posix()
                samples.append(
                    {
                        "label": label,
                        "relative_path": relative,
                        "original_path": info.filename,
                        "sha256": digest,
                        "width": width,
                        "height": height,
                        "mode": mode,
                    }
                )
                dimensions.append((width, height))
                modes[mode] += 1
                hashes[digest].append((label, relative))

        counts = Counter(sample["label"] for sample in samples)
        if len(counts) < 2:
            raise ContractError("至少需要2个类别目录")
        too_small = {label: count for label, count in counts.items() if count < MIN_IMAGES_PER_CLASS}
        if too_small:
            details = "、".join(f"{label}={count}" for label, count in sorted(too_small.items()))
            raise ContractError(f"每类至少需要{MIN_IMAGES_PER_CLASS}张有效图片；当前 {details}")

        cross_label_duplicates = [
            {"sha256": digest, "occurrences": occurrences}
            for digest, occurrences in hashes.items()
            if len({label for label, _ in occurrences}) > 1
        ]
        if cross_label_duplicates:
            raise ContractError(
                f"发现{len(cross_label_duplicates)}组相同图片被放入不同类别，请先修正标签冲突"
            )
        duplicate_groups = len(duplicate_hashes)
        width_values = [value[0] for value in dimensions]
        height_values = [value[1] for value in dimensions]
        ordered_hashes = "\n".join(
            f"{item['label']}:{item['sha256']}" for item in sorted(samples, key=lambda item: item["relative_path"])
        )
        imbalance_ratio = max(counts.values()) / min(counts.values())
        risks: list[dict[str, str]] = []
        if rejected:
            risks.append({"level": "warning", "message": f"{len(rejected)}张无效或重复图片已从划分中排除"})
        if duplicate_groups:
            risks.append({"level": "warning", "message": f"发现{duplicate_groups}组同标签重复图片，已去重以避免划分泄漏"})
        if imbalance_ratio >= 1.5:
            risks.append({"level": "warning", "message": f"最大类别是最小类别的{imbalance_ratio:.1f}倍"})
        if not risks:
            risks.append({"level": "ok", "message": "未发现阻断训练的数据问题"})

        report = {
            "schema_version": "0.1",
            "dataset_id": dataset_id,
            "source_filename": Path(filename).name,
            "imported_at_utc": _utc_now(),
            "fingerprint_sha256": hashlib.sha256(ordered_hashes.encode("utf-8")).hexdigest(),
            "total_images": len(samples),
            "class_count": len(counts),
            "class_counts": dict(sorted(counts.items())),
            "minimum_class_count": min(counts.values()),
            "imbalance_ratio": float(imbalance_ratio),
            "rejected_count": len(rejected),
            "rejected_files": rejected[:50],
            "duplicate_groups": duplicate_groups,
            "dimensions": {
                "min_width": min(width_values),
                "max_width": max(width_values),
                "min_height": min(height_values),
                "max_height": max(height_values),
            },
            "image_modes": dict(sorted(modes.items())),
            "risks": risks,
            "previews": [
                {"label": item["label"], "relative_path": item["relative_path"]}
                for item in samples[:12]
            ],
        }
        write_json(temporary_dir / "dataset_manifest.json", {"samples": samples})
        write_json(temporary_dir / "dataset_report.json", report)
        datasets_dir.mkdir(parents=True, exist_ok=True)
        os.replace(temporary_dir, final_dir)
        return report, final_dir
    except Exception:
        shutil.rmtree(temporary_dir, ignore_errors=True)
        raise


class TrainingWorkspace:
    """Persistent task, dataset, contract and run ownership for the local Harness."""

    def __init__(
        self,
        root: str | Path,
        runs: RunService,
        data_adapters: DataAdapterRegistry | None = None,
    ) -> None:
        self.root = Path(root).expanduser().resolve()
        self.tasks_dir = self.root / "tasks"
        self.tasks_dir.mkdir(parents=True, exist_ok=True)
        self.runs = runs
        self.runs.attach_workspace(self.root)
        self.data_adapters = data_adapters or default_data_adapter_registry()
        self.recipe_builder = RecipeScaffoldBuilder()
        self.recipe_factory = RecipeFactory(self.root / "recipe_factory")
        self.model_assets = ModelAssetStore(self.root / "model_assets")
        self.huggingface_catalog = HuggingFaceCatalog()
        self.huggingface_downloader = HuggingFaceHubDownloader()
        self.model_source_store = ModelSourceStore(self.root)
        self.blocker_store = BlockerStore(self.root)
        self.training_plan_store = TrainingPlanStore(self.root)
        self.feasibility_store = FeasibilityStore(self.root)
        self.delivery_authorization_store = DeliveryAuthorizationStore(self.root)
        self.inference_input_store = InferenceInputStore(self.root)
        self.model_source_providers: dict[str, SourceProvider] = {
            "github": GitHubSourceProvider(),
            "huggingface": HuggingFaceSourceProvider(),
        }
        self.repository_analyzer = StaticRepositoryAnalyzer()
        self.repository_analysis_store = RepositoryAnalysisStore(self.root)
        self.binding_analysis_attempt_store = BindingAnalysisAttemptStore(self.root)
        self._lock = RLock()
        self._binding_executor = ThreadPoolExecutor(
            max_workers=2,
            thread_name_prefix="model-binding",
        )
        self._binding_futures: dict[str, Any] = {}
        self._binding_executor_closed = False
        self.binding_analysis_attempt_store.recover_interrupted_attempts()
        self._recover_model_binding_commits()
        self._restore_model_binding_task_projections()
        self._restore_registered_recipe_versions()
        self._recover_pending_runs()

    def close(self) -> None:
        with self._lock:
            if self._binding_executor_closed:
                return
            self._binding_executor_closed = True
        self._binding_executor.shutdown(wait=True, cancel_futures=False)

    def create_task(
        self,
        name: str,
        business_goal: str,
        capability_request: dict[str, Any] | None = None,
        recipe_id: str | None = None,
        *,
        task_id: str | None = None,
    ) -> dict[str, Any]:
        selected_name = name.strip()
        selected_goal = business_goal.strip()
        if not selected_name:
            raise ContractError("任务名称不能为空")
        if not selected_goal:
            raise ContractError("业务目标不能为空")
        # Identity is opaque and stable; the user-facing name remains mutable
        # display metadata and must never become a routing or storage key.
        selected_task_id = task_id.strip() if isinstance(task_id, str) else ""
        if selected_task_id and not re.fullmatch(r"task-[0-9a-f]{32}", selected_task_id):
            raise ContractError("task_id 必须是 opaque task-<32 hex> 对象 ID")
        task_id = selected_task_id or f"task-{uuid4().hex}"
        now = _utc_now()
        capability = self._normalize_capability(capability_request or {})
        spec = build_task_spec_revision(
            task_id=task_id,
            revision=1,
            name=selected_name,
            business_goal=selected_goal,
            capability_request=capability,
            created_at_utc=now,
            source="task_created",
            supersedes_revision=None,
        )
        decision_status = spec["capability_decision"]["status"]
        selected_recipe = None
        recipe_source = None
        capability_status = decision_status
        if recipe_id:
            plugin = self.runs.registry.get_recipe(recipe_id)
            if decision_status == "resolved":
                if (
                    recipe_id
                    in self._eligible_recipe_ids_for_capability(
                        deepcopy(spec["capability_request"])
                    )
                ):
                    selected_recipe = plugin.manifest.plugin_id
                    recipe_source = "explicit"
                    capability_status = "matched"
                else:
                    # A caller-supplied Recipe is never evidence that the
                    # original goal changed.  Preserve the TaskSpec and the
                    # typed capability gap instead of manufacturing an
                    # awaiting-data image/tabular task from an unsupported
                    # ASR, TTS, OCR, forecasting, or other specialist goal.
                    capability_status = "needs_recipe"
            # ``needs_confirmation`` and ``needs_clarification`` are
            # human-owned TaskSpec gates.  A Recipe id cannot answer either
            # gate or rewrite the original capability on the caller's behalf.
        elif decision_status == "resolved":
            selected_recipe = self._select_recipe_for_capability(capability)
            if selected_recipe:
                recipe_source = "matched"
                capability_status = "matched"
            else:
                capability_status = "needs_recipe"
        if decision_status == "needs_clarification":
            status = "needs_clarification"
        elif decision_status == "needs_confirmation":
            status = "needs_confirmation"
        elif selected_recipe:
            status = "awaiting_data"
        else:
            status = "needs_recipe"
        task = {
            "schema_version": TASK_SCHEMA_VERSION,
            "task_id": task_id,
            "name": selected_name,
            "business_goal": selected_goal,
            "status": status,
            "capability_request": capability,
            "capability_status": capability_status,
            "recipe_id": selected_recipe,
            "recipe_source": recipe_source,
            "current_spec_revision": 1,
            "spec_revision_ids": [spec["revision_id"]],
            "data_adapter_id": None,
            "dataset_id": None,
            "dataset_history": [],
            "contract_confirmed": False,
            "confirmations": {},
            "confirmed_contract_sha256": None,
            "contract_revision_ids": [],
            "current_contract_revision_id": None,
            "confirmed_contract_revision_id": None,
            "approval_decision_ids": [],
            "current_approval_decision_id": None,
            "delivery_authorization_ids": [],
            "contract_stale": False,
            "current_model_binding_revision_id": None,
            "last_model_binding_revision_id": None,
            "model_binding_bound_spec_revision": None,
            "model_binding_stale_for_spec_revision": False,
            "current_run_id": None,
            "last_run_id": None,
            "run_ids": [],
            "pending_run": None,
            "created_at_utc": now,
            "updated_at_utc": now,
        }
        with self._lock:
            task_path = self._task_path(task_id)
            if task_path.is_file():
                raise ContractError(f"任务对象已存在: {task_id}")
            write_json(task_path, task)
            write_json(self._spec_revision_path(task_id, 1), spec)
            if capability_status == "needs_recipe":
                self._persist_missing_recipe_evidence(
                    task_id,
                    capability,
                    task_spec=spec,
                )
        return self.get_task(task_id)

    def list_tasks(self, *, include_archived: bool = False) -> list[dict[str, Any]]:
        with self._lock:
            stored_tasks = [
                self._reconcile_pending_run(read_json(path))[0]
                for path in self.tasks_dir.glob("*/task.json")
            ]
        tasks = [
            self._view(task)
            for task in stored_tasks
            if include_archived or not task.get("archived_at_utc")
        ]
        return sorted(tasks, key=lambda item: item["updated_at_utc"], reverse=True)

    def get_task(self, task_id: str) -> dict[str, Any]:
        with self._lock:
            task, _recovered = self._reconcile_pending_run(
                read_json(self._task_path(task_id))
            )
        return self._view(task)

    def current_training_plan(self, task_id: str) -> dict[str, Any] | None:
        task = read_json(self._task_path(task_id))
        plan = self.training_plan_store.current_revision(task_id)
        if plan is None:
            return None
        return self._training_plan_view(task, plan)

    def get_training_plan(
        self,
        task_id: str,
        revision_id: str,
    ) -> dict[str, Any]:
        task = read_json(self._task_path(task_id))
        plan = self.training_plan_store.get_revision(task_id, revision_id)
        return self._training_plan_view(task, plan)

    def _training_plan_view(
        self,
        task: Mapping[str, Any],
        plan: Mapping[str, Any],
    ) -> dict[str, Any]:
        task_id = str(task["task_id"])
        view = self.training_plan_store.revision_view(
            task_id, str(plan["training_plan_revision_id"])
        )
        binding = self.model_source_store.current_binding(task_id)
        stale_reasons: list[str] = []
        if int(plan["base_spec_revision"]) != int(task["current_spec_revision"]):
            stale_reasons.append("task_spec_changed")
        if binding is None:
            stale_reasons.append("model_binding_missing")
        else:
            context = self.model_source_store.binding_context(
                task_id, str(binding["binding_revision_id"])
            )
            assert context is not None
            if plan["source_snapshot_id"] != context["snapshot"]["snapshot_id"]:
                stale_reasons.append("source_snapshot_changed")
            if plan["snapshot_digest"] != context["snapshot"]["content_digest"]:
                stale_reasons.append("source_snapshot_digest_changed")
            if plan["analysis_id"] != context["analysis"]["analysis_id"]:
                stale_reasons.append("repository_analysis_changed")
            if plan["analysis_digest"] != context["analysis"]["content_digest"]:
                stale_reasons.append("repository_analysis_digest_changed")
        view["stale"] = bool(stale_reasons)
        view["stale_reasons"] = stale_reasons
        return view

    def create_training_plan(
        self,
        task_id: str,
        *,
        base_spec_revision: int,
        entrypoint_path: str | None = None,
        hyperparameters: dict[str, Any] | None = None,
        resource_budget: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            task = read_json(self._task_path(task_id))
            self._require_task_mutable(task, "生成训练计划")
            current_spec = self._ensure_spec_revision(task)
            if (
                isinstance(base_spec_revision, bool)
                or not isinstance(base_spec_revision, int)
                or base_spec_revision < 1
            ):
                raise ContractError("base_spec_revision 必须是正整数")
            if base_spec_revision != int(current_spec["revision"]):
                raise HarnessError("TaskSpec 已更新，请刷新后重新生成训练计划")
            if self.training_plan_store.current_revision(task_id) is not None:
                raise ContractError("训练计划已存在；修改必须创建新的不可变 revision")
            binding = self.model_source_store.current_binding(task_id)
            if binding is None:
                raise HarnessError("请先选择并批准模型来源")
            context = self.model_source_store.binding_context(
                task_id, str(binding["binding_revision_id"])
            )
            assert context is not None
            snapshot = context["snapshot"]
            analysis_record = context["analysis"]
            analysis = analysis_record["analysis"]
            analysis_status = str(analysis.get("status") or "")
            if analysis_status != "complete":
                if analysis_status in {"needs_input", "needs_manual_mapping"}:
                    raise HarnessError(
                        "仓库静态分析还需要入口或数据映射；请先创建新的分析 revision"
                    )
                raise HarnessError(
                    "仓库静态分析存在未解决的风险或阻断；不能生成可批准的训练计划"
                )
            license_policy = dict(
                snapshot.get("details", {}).get("license_policy") or {}
            ) or _license_policy(
                str(snapshot["license"]), str(snapshot["license_status"])
            )
            if license_policy.get("decision") != "allow":
                raise HarnessError("当前许可证策略未放行，不能生成可批准的训练计划")

            candidates = analysis.get("training_entrypoints") or []
            selected_path = str(entrypoint_path or "").strip()
            if not selected_path and candidates:
                selected_path = str(candidates[0].get("path", "")).strip()
            files = {
                str(item.get("path")): item
                for item in snapshot.get("files", [])
                if item.get("kind") in {"blob", "executable"}
            }
            if not selected_path or selected_path not in files:
                blocker = self.blocker_store.append(
                    task_id,
                    stage="training_plan",
                    code="blocked_repository",
                    message="仓库静态分析未确认训练入口；请从固定文件清单中人工选择入口。",
                    retry_action="map_training_entrypoint",
                    related_object_type="RepositoryAnalysis",
                    related_object_id=str(analysis_record["analysis_id"]),
                    related_object_digest=str(analysis_record["content_digest"]),
                    details={
                        "reason_code": "blocked_training_entrypoint",
                        "candidate_paths": [item.get("path") for item in candidates],
                    },
                )
                raise HarnessError(str(blocker["message"]))

            compiled = compile_training_plan(
                task_spec=current_spec,
                snapshot=snapshot,
                analysis=analysis,
                selected_entrypoint=selected_path,
                hyperparameters=hyperparameters,
                resource_budget=resource_budget,
            )
            plan = self.training_plan_store.create_revision(
                task_id,
                base_spec_revision=int(current_spec["revision"]),
                source_snapshot_id=str(snapshot["snapshot_id"]),
                snapshot_digest=str(snapshot["content_digest"]),
                analysis_id=str(analysis_record["analysis_id"]),
                analysis_digest=str(analysis_record["content_digest"]),
                **compiled,
            )
            self.blocker_store.resolve_active_stage(
                task_id,
                "training_plan",
                action="training_plan_revision_created",
                related_object_type="TrainingPlanRevision",
                related_object_id=str(plan["training_plan_revision_id"]),
            )
        return self.current_training_plan(task_id) or {}

    def decide_training_plan(
        self,
        task_id: str,
        revision_id: str,
        *,
        expected_plan_sha256: str,
        decision: str,
        reason: str = "",
    ) -> dict[str, Any]:
        with self._lock:
            task = read_json(self._task_path(task_id))
            self._require_task_mutable(task, "审批训练计划")
            if decision == "approve":
                self.training_plan_store.approve(
                    task_id,
                    revision_id,
                    expected_plan_sha256=expected_plan_sha256,
                    actor="local_user",
                    reason=reason,
                )
            elif decision == "reject":
                self.training_plan_store.reject(
                    task_id,
                    revision_id,
                    expected_plan_sha256=expected_plan_sha256,
                    actor="local_user",
                    reason=reason or "用户拒绝当前计划",
                )
            elif decision == "cancel":
                self.training_plan_store.cancel(
                    task_id,
                    revision_id,
                    expected_plan_sha256=expected_plan_sha256,
                    actor="local_user",
                    reason=reason or "用户取消当前计划",
                )
            else:
                raise ContractError("decision 必须是 approve、reject 或 cancel")
        return self.current_training_plan(task_id) or {}

    def revise_training_plan(
        self,
        task_id: str,
        revision_id: str,
        *,
        expected_parent_sha256: str,
        base_spec_revision: int,
        entrypoint_path: str | None = None,
        hyperparameters: dict[str, Any] | None = None,
        resource_budget: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a new immutable plan from the current exact parent digest.

        A model-source, TaskSpec, entrypoint, hyperparameter, or resource change
        must never mutate an approved plan in place.  This method rebuilds the
        lineage fields from the current persisted task and source snapshot, then
        delegates the append-only child creation to ``TrainingPlanStore``.
        """

        with self._lock:
            task = read_json(self._task_path(task_id))
            self._require_task_mutable(task, "修订训练计划")
            current_spec = self._ensure_spec_revision(task)
            if (
                isinstance(base_spec_revision, bool)
                or not isinstance(base_spec_revision, int)
                or base_spec_revision < 1
            ):
                raise ContractError("base_spec_revision 必须是正整数")
            if base_spec_revision != int(current_spec["revision"]):
                raise HarnessError("TaskSpec 已更新，请刷新后重新生成训练计划")

            current = self.training_plan_store.current_revision(task_id)
            if current is None:
                raise FileNotFoundError("training plan does not exist")
            if current["training_plan_revision_id"] != revision_id:
                raise StaleTrainingPlanError("只能从当前训练计划创建新 revision")
            if current["plan_sha256"] != expected_parent_sha256:
                raise StaleTrainingPlanError("父训练计划 digest 已变化")

            binding = self.model_source_store.current_binding(task_id)
            if binding is None:
                raise HarnessError("请先选择并批准模型来源")
            if (
                task.get("current_model_binding_revision_id")
                != binding.get("binding_revision_id")
                or task.get("model_binding_stale_for_spec_revision") is True
                or int(binding.get("base_spec_revision", 0))
                != int(current_spec["revision"])
            ):
                raise HarnessError("当前模型来源绑定已过期，请为当前TaskSpec重新解析并批准")
            context = self.model_source_store.binding_context(
                task_id, str(binding["binding_revision_id"])
            )
            assert context is not None
            snapshot = context["snapshot"]
            analysis_record = context["analysis"]
            analysis = analysis_record["analysis"]
            analysis_status = str(analysis.get("status") or "")
            if analysis_status != "complete":
                if analysis_status in {"needs_input", "needs_manual_mapping"}:
                    raise HarnessError(
                        "仓库静态分析还需要入口或数据映射；请先创建新的分析 revision"
                    )
                raise HarnessError(
                    "仓库静态分析存在未解决的风险或阻断；不能修订可批准的训练计划"
                )
            license_policy = dict(
                snapshot.get("details", {}).get("license_policy") or {}
            ) or _license_policy(
                str(snapshot["license"]), str(snapshot["license_status"])
            )
            if license_policy.get("decision") != "allow":
                raise HarnessError("当前许可证策略未放行，不能修订训练计划")

            candidates = analysis.get("training_entrypoints") or []
            selected_path = str(entrypoint_path or "").strip()
            if not selected_path and candidates:
                selected_path = str(candidates[0].get("path", "")).strip()
            if not selected_path:
                argv = current.get("entrypoint", {}).get("argv") or []
                selected_path = str(argv[1]).strip() if len(argv) > 1 else ""
            files = {
                str(item.get("path")): item
                for item in snapshot.get("files", [])
                if item.get("kind") in {"blob", "executable"}
            }
            if not selected_path or selected_path not in files:
                raise HarnessError(
                    "训练入口不在当前固定来源清单中，请从清单重新选择"
                )

            next_budget = dict(current["resource_budget"])
            if resource_budget is not None:
                next_budget.update(resource_budget)
            next_hyperparameters = (
                dict(hyperparameters)
                if hyperparameters is not None
                else dict(current["hyperparameters"])
            )
            compiled = compile_training_plan(
                task_spec=current_spec,
                snapshot=snapshot,
                analysis=analysis,
                selected_entrypoint=selected_path,
                hyperparameters=next_hyperparameters,
                resource_budget=next_budget,
            )
            revised = self.training_plan_store.revise_revision(
                task_id,
                revision_id,
                expected_parent_sha256=expected_parent_sha256,
                changes={
                    "base_spec_revision": int(current_spec["revision"]),
                    "source_snapshot_id": str(snapshot["snapshot_id"]),
                    "snapshot_digest": str(snapshot["content_digest"]),
                    "analysis_id": str(analysis_record["analysis_id"]),
                    "analysis_digest": str(analysis_record["content_digest"]),
                    **compiled,
                },
            )
            self.blocker_store.resolve_active_stage(
                task_id,
                "training_plan",
                action="training_plan_revision_created",
                related_object_type="TrainingPlanRevision",
                related_object_id=str(revised["training_plan_revision_id"]),
            )
            for stage in ("resource_probe", "environment_lock", "resource_fit"):
                self.blocker_store.resolve_active_stage(
                    task_id,
                    stage,
                    action="training_plan_revision_invalidated_resource_evidence",
                    related_object_type="TrainingPlanRevision",
                    related_object_id=str(revised["training_plan_revision_id"]),
                )
        return self.current_training_plan(task_id) or {}

    def current_resource_feasibility(self, task_id: str) -> dict[str, Any]:
        read_json(self._task_path(task_id))
        bundle = self.feasibility_store.current_bundle(task_id)
        blockers = sorted(
            [
            item
            for item in self.blocker_store.list(task_id, active_only=True)
            if item.get("stage") in {
                "resource_probe",
                "environment_lock",
                "resource_fit",
            }
            ],
            key=lambda item: (
                str(item.get("created_at_utc") or ""),
                str(item.get("blocker_id") or ""),
            ),
            reverse=True,
        )
        report = bundle.get("resource_fit_report")
        probe = bundle.get("resource_probe")
        environment_lock = bundle.get("environment_lock")
        plan_view = self.current_training_plan(task_id)
        current_plan = plan_view.get("plan") if isinstance(plan_view, dict) else None
        lineage_current = bool(
            isinstance(report, dict)
            and isinstance(current_plan, dict)
            and isinstance(probe, dict)
            and isinstance(environment_lock, dict)
            and report.get("training_plan_revision_id")
            == current_plan.get("training_plan_revision_id")
            and report.get("training_plan_sha256")
            == current_plan.get("plan_sha256")
            and report.get("resource_probe_id") == probe.get("resource_probe_id")
            and report.get("resource_probe_sha256") == probe.get("probe_sha256")
            and report.get("environment_lock_id")
            == environment_lock.get("environment_lock_id")
            and report.get("environment_lock_sha256")
            == environment_lock.get("lock_sha256")
            and not blockers
        )
        if isinstance(report, dict) and not lineage_current:
            bundle = {
                **bundle,
                "stale_resource_fit_report": report,
                "resource_fit_report": None,
            }
            report = None
        elif report is None:
            historical_reports = self.feasibility_store.list_resource_fit_reports(
                task_id
            )
            if historical_reports:
                bundle = {
                    **bundle,
                    "stale_resource_fit_report": historical_reports[-1],
                }
        decision = (
            str(report["decision"])
            if isinstance(report, dict)
            else str(blockers[0]["code"])
            if blockers
            else "not_checked"
        )
        return {**bundle, "decision": decision, "blockers": blockers}

    def get_resource_probe(self, task_id: str, probe_id: str) -> dict[str, Any]:
        read_json(self._task_path(task_id))
        return self.feasibility_store.get_resource_probe(task_id, probe_id)

    def get_environment_lock(self, task_id: str, lock_id: str) -> dict[str, Any]:
        read_json(self._task_path(task_id))
        return self.feasibility_store.get_environment_lock(task_id, lock_id)

    def get_resource_fit_report(
        self,
        task_id: str,
        report_id: str,
    ) -> dict[str, Any]:
        read_json(self._task_path(task_id))
        return self.feasibility_store.get_resource_fit_report(task_id, report_id)

    def check_resource_feasibility(
        self,
        task_id: str,
        *,
        training_plan_revision_id: str,
        expected_plan_sha256: str,
        base_image_digest: str | None = None,
        packages: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        if packages:
            raise ContractError(
                "packages由服务端从固定SourceSnapshot解析，客户端不能注入依赖锁"
            )
        with self._lock:
            task = read_json(self._task_path(task_id))
            self._require_task_mutable(task, "检查资源可行性")
            plan_view = self.current_training_plan(task_id)
            if plan_view is None:
                raise HarnessError("请先生成并批准训练计划")
            if plan_view.get("stale") is True:
                raise HarnessError("训练计划已过期，请为当前任务重新生成 revision")
            binding = self.model_source_store.current_binding(task_id)
            if binding is None:
                raise HarnessError("当前模型来源绑定不存在")
            context = self.model_source_store.binding_context(
                task_id, str(binding["binding_revision_id"])
            )
            assert context is not None
            plan = self.training_plan_store.authorize_use(
                task_id,
                training_plan_revision_id,
                expected_plan_sha256=expected_plan_sha256,
                current_spec_revision=int(task["current_spec_revision"]),
                source_snapshot_id=str(context["snapshot"]["snapshot_id"]),
                snapshot_digest=str(context["snapshot"]["content_digest"]),
                analysis_id=str(context["analysis"]["analysis_id"]),
                analysis_digest=str(context["analysis"]["content_digest"]),
            )
            probe = ResourceProbe.capture(self.root)
            probe_record = self.feasibility_store.append_resource_probe(task_id, probe)
            for stage in ("resource_probe", "environment_lock", "resource_fit"):
                self.blocker_store.resolve_active_stage(
                    task_id,
                    stage,
                    action="superseded_by_new_resource_probe",
                    related_object_type="ResourceProbe",
                    related_object_id=str(probe_record["resource_probe_id"]),
                )
            runtime = probe_record["container_runtime"]
            if runtime.get("available") is not True:
                message = (
                    "本机未检测到可用的 Docker/Podman 隔离运行时。当前可以继续审阅来源、分析和计划，"
                    "但不能构建环境或执行第三方训练代码。"
                )
                self.blocker_store.append(
                    task_id,
                    stage="environment_lock",
                    code="blocked_environment",
                    message=message,
                    retry_action="install_or_start_oci_runtime_then_retry",
                    related_object_type="ResourceProbe",
                    related_object_id=str(probe_record["resource_probe_id"]),
                    related_object_digest=str(probe_record["probe_sha256"]),
                    details={
                        "detector": "container_runtime_probe",
                        "required": "available Docker or Podman runtime",
                        "observed": runtime,
                        "retryable": True,
                    },
                )
                return self.current_resource_feasibility(task_id)

            selected_digest = str(base_image_digest or "").strip().lower()
            if not selected_digest:
                self.blocker_store.append(
                    task_id,
                    stage="environment_lock",
                    code="blocked_environment",
                    message="需要提供已解析的基础镜像 sha256 digest；镜像 tag 会漂移，不能进入不可变环境锁。",
                    retry_action="provide_base_image_digest",
                    related_object_type="ResourceProbe",
                    related_object_id=str(probe_record["resource_probe_id"]),
                    related_object_digest=str(probe_record["probe_sha256"]),
                    details={
                        "detector": "base_image_digest_validator",
                        "required": "sha256:<64 hex>",
                        "observed": "missing",
                        "retryable": True,
                    },
                )
                return self.current_resource_feasibility(task_id)

            dependency_resolution = resolve_environment_dependencies(
                snapshot=context["snapshot"],
                analysis=context["analysis"]["analysis"],
            )
            if dependency_resolution["status"] != "ready":
                self.blocker_store.append(
                    task_id,
                    stage="environment_lock",
                    code="blocked_environment",
                    message=(
                        "仓库依赖尚未形成精确版本和sha256哈希锁；"
                        "请提交锁定后的requirements导出，再重新检查。"
                    ),
                    retry_action="provide_hashed_dependency_lock",
                    related_object_type="RepositoryAnalysis",
                    related_object_id=str(context["analysis"]["analysis_id"]),
                    related_object_digest=str(context["analysis"]["content_digest"]),
                    details={
                        "reason_code": "blocked_dependency_lock",
                        "detector": "static_dependency_resolver",
                        "required": "exact package versions with sha256 hashes",
                        "observed": dependency_resolution["unresolved"],
                        "evidence_refs": dependency_resolution["evidence_refs"],
                        "resolver_version": dependency_resolution["resolver_version"],
                        "retryable": True,
                    },
                )
                return self.current_resource_feasibility(task_id)

            accelerator_policy = probe_record["accelerator_policy"]
            environment = EnvironmentLock.create(
                source_snapshot_id=str(context["snapshot"]["snapshot_id"]),
                platform_os="linux",
                platform_arch=str(probe_record["arch"].get("name") or ""),
                execution_backend=str(plan["execution_policy"]["backend"]),
                base_image_digest=selected_digest,
                packages=dependency_resolution["packages"],
                system_dependencies=dependency_resolution[
                    "system_dependencies"
                ],
                network_allowlist=plan["execution_policy"]["network_allowlist"],
                detected_accelerators=accelerator_policy.get("detected") or (),
                unusable_reason=str(accelerator_policy.get("unusable_reason") or ""),
            )
            environment_record = self.feasibility_store.append_environment_lock(
                task_id, environment
            )
            estimate_basis = (
                plan.get("dataset_mapping", {})
                .get("plan_basis", {})
                .get("resource_estimate_basis", {})
            )
            if (
                not isinstance(estimate_basis, dict)
                or estimate_basis.get("status") != "complete"
            ):
                self.blocker_store.resolve_active_stage(
                    task_id,
                    "environment_lock",
                    action="environment_lock_created",
                    related_object_type="EnvironmentLock",
                    related_object_id=str(environment_record["environment_lock_id"]),
                )
                self.blocker_store.append(
                    task_id,
                    stage="resource_fit",
                    code="blocked_resources",
                    message=(
                        "当前预算只是仓库快照启发式上限，尚未绑定基础模型权重与用户数据规模证据；"
                        "不能生成资源fit结论。V3分析阶段到此停止，请进入L3环境构建资格验证补齐证据。"
                    ),
                    retry_action="continue_to_l3_qualification",
                    related_object_type="TrainingPlanRevision",
                    related_object_id=str(plan["training_plan_revision_id"]),
                    related_object_digest=str(plan["plan_sha256"]),
                    details={
                        "detector": "resource_estimate_evidence_gate",
                        "required": (
                            "immutable base-model size/digest, dataset size/digest, "
                            "and qualified build measurement"
                        ),
                        "observed": estimate_basis,
                        "retryable": False,
                    },
                )
                return self.current_resource_feasibility(task_id)
            report = evaluate_resource_fit(
                training_plan_revision_id=str(plan["training_plan_revision_id"]),
                training_plan_sha256=str(plan["plan_sha256"]),
                resource_budget=plan["resource_budget"],
                environment_lock=environment_record,
                resource_probe=probe_record,
            )
            report_record = self.feasibility_store.append_resource_fit_report(
                task_id, report
            )
            self.blocker_store.resolve_active_stage(
                task_id,
                "environment_lock",
                action="environment_lock_created",
                related_object_type="EnvironmentLock",
                related_object_id=str(environment_record["environment_lock_id"]),
            )
            if report_record["decision"] in {"fit", "fit_with_revision"}:
                self.blocker_store.resolve_active_stage(
                    task_id,
                    "resource_fit",
                    action=(
                        "resource_fit_confirmed"
                        if report_record["decision"] == "fit"
                        else "resource_fit_revision_recommended"
                    ),
                    related_object_type="ResourceFitReport",
                    related_object_id=str(report_record["resource_fit_report_id"]),
                )
            else:
                self.blocker_store.append(
                    task_id,
                    stage="resource_fit",
                    code=str(report_record["decision"]),
                    message="当前训练计划超出这台机器或隔离环境的可用条件；请选择降级建议并创建新的计划 revision。",
                    retry_action="create_revised_training_plan",
                    related_object_type="ResourceFitReport",
                    related_object_id=str(report_record["resource_fit_report_id"]),
                    related_object_digest=str(report_record["report_sha256"]),
                    details={
                        "detector": "resource_fit_estimator",
                        "reasons": report_record["reasons"],
                        "alternatives": report_record["alternatives"],
                        "retryable": True,
                    },
                )
        return self.current_resource_feasibility(task_id)

    def archive_task(self, task_id: str) -> dict[str, Any]:
        """Soft-archive a task while preserving its task and run evidence."""

        with self._lock:
            task = read_json(self._task_path(task_id))
            if task.get("status") == "running":
                raise HarnessError("真实训练运行中，暂不能归档任务")
            if not task.get("archived_at_utc"):
                archived_at = _utc_now()
                task["archived_at_utc"] = archived_at
                task["updated_at_utc"] = archived_at
                write_json(self._task_path(task_id), task)
        return self.get_task(task_id)

    def search_huggingface_models(
        self,
        query: str,
        *,
        pipeline_tag: str | None = None,
        limit: int = 10,
        token: str | None = None,
    ) -> list[dict[str, Any]]:
        return self.huggingface_catalog.search(
            query,
            pipeline_tag=pipeline_tag,
            limit=limit,
            token=token,
        )

    def huggingface_model_card(
        self,
        repo_id: str,
        *,
        revision: str | None = None,
        token: str | None = None,
    ) -> dict[str, Any]:
        return self.huggingface_catalog.model_card(
            repo_id,
            revision=revision,
            token=token,
        )

    def model_source_provider_capabilities(self) -> list[dict[str, Any]]:
        """Describe the providers that can resolve immutable model sources."""

        return [
            {
                "provider": provider_id,
                "search": "official_provider_api",
                "resolution": "immutable_40_character_commit",
                "analysis": "static_only_never_execute",
                "token_policy": "ephemeral_request_header_only",
            }
            for provider_id in sorted(self.model_source_providers)
        ]

    def list_blockers(
        self,
        task_id: str,
        *,
        active_only: bool = False,
    ) -> list[dict[str, Any]]:
        read_json(self._task_path(task_id))
        return self.blocker_store.list(task_id, active_only=active_only)

    def get_blocker(self, task_id: str, blocker_id: str) -> dict[str, Any]:
        read_json(self._task_path(task_id))
        return self.blocker_store.get(task_id, blocker_id)

    def _record_model_source_blocker(
        self,
        task_id: str,
        *,
        stage: str,
        error: Exception,
        retry_action: str,
        related_object_type: str | None = None,
        related_object_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        reason_code = str(error).strip() or error.__class__.__name__
        reason_code = (
            re.sub(r"[^a-zA-Z0-9._:-]+", "_", reason_code)[:120]
            or "unknown_error"
        )
        code = _canonical_model_source_blocker_code(reason_code)
        selected_details = deepcopy(dict(details or {}))
        selected_details["reason_code"] = reason_code
        selected_details["canonical_code"] = code
        evidence_refs = selected_details.get("evidence_refs")
        return self.blocker_store.append(
            task_id,
            stage=stage,
            code=code,
            message=_model_source_error_message(reason_code),
            retry_action=retry_action,
            related_object_type=related_object_type,
            related_object_id=related_object_id,
            details=selected_details,
            detector="model_source_provider@0.9",
            facts=selected_details,
            rule={
                "failure_closed": True,
                "required": "immutable_source_resolution_and_snapshot",
            },
            evidence_refs=(
                list(evidence_refs) if isinstance(evidence_refs, list) else []
            ),
            recovery_actions=[retry_action],
            retryable=True,
        )

    def _record_repository_analysis_blocker(
        self,
        task_id: str,
        analysis_record: dict[str, Any],
    ) -> dict[str, Any] | None:
        analysis = analysis_record.get("analysis") or {}
        blocking_risks = [
            deepcopy(item)
            for item in analysis.get("risks", [])
            if isinstance(item, dict)
            and str(item.get("severity") or "").lower() in {"critical", "high"}
        ]
        if str(analysis.get("status") or "") != "blocked" or not blocking_risks:
            return None
        evidence_refs = list(
            dict.fromkeys(
                str(reference)
                for risk in blocking_risks
                for reference in risk.get("evidence_refs", [])
                if str(reference).strip()
            )
        )
        retry_action = "review_repository_risks"
        return self.blocker_store.append(
            task_id,
            stage="repository_analysis",
            code="blocked_security",
            message=(
                "仓库静态分析发现未解决的高风险执行或供应链行为；"
                "当前来源只能审阅，不得生成计划或启动运行。"
            ),
            retry_action=retry_action,
            related_object_type="RepositoryAnalysis",
            related_object_id=str(analysis_record["analysis_id"]),
            related_object_digest=str(analysis_record["content_digest"]),
            details={
                "reason_code": "blocked_high_risk_repository_analysis",
                "risk_codes": [str(item.get("code") or "unknown") for item in blocking_risks],
                "retryable": True,
            },
            detector=str(analysis.get("analyzer_version") or ANALYZER_VERSION),
            facts={"blocking_risks": blocking_risks},
            rule={"maximum_allowed_risk_severity": "medium"},
            evidence_refs=evidence_refs,
            recovery_actions=[retry_action],
            retryable=True,
        )

    def search_model_sources(
        self,
        task_id: str,
        *,
        query: str | None,
        providers: list[str] | tuple[str, ...] | None,
        limit_per_provider: int,
        base_spec_revision: int,
        tokens: dict[str, str | None] | None = None,
    ) -> dict[str, Any]:
        """Search official provider catalogs without downloading or executing code."""

        if (
            isinstance(limit_per_provider, bool)
            or not isinstance(limit_per_provider, int)
            or not 1 <= limit_per_provider <= 10
        ):
            raise ContractError("limit_per_provider必须在1到10之间")
        requested_providers = tuple(
            dict.fromkeys(
                str(item).strip().lower()
                for item in (providers or tuple(sorted(self.model_source_providers)))
            )
        )
        if not requested_providers or any(
            provider not in self.model_source_providers
            for provider in requested_providers
        ):
            raise ContractError("搜索Provider必须是huggingface或github")
        if (
            isinstance(base_spec_revision, bool)
            or not isinstance(base_spec_revision, int)
            or base_spec_revision < 1
        ):
            raise ContractError("base_spec_revision必须是正整数")
        with self._lock:
            task = read_json(self._task_path(task_id))
            if task.get("archived_at_utc"):
                raise HarnessError("归档任务不能搜索新的模型来源")
            if task.get("status") == "running":
                raise HarnessError("运行中不能搜索新的模型来源")
            spec = self._ensure_spec_revision(task)
            if int(spec["revision"]) != base_spec_revision:
                raise HarnessError(
                    f"TaskSpec已更新到 revision {spec['revision']}，请刷新后重试"
                )
            if spec.get("capability_decision", {}).get("status") != "resolved":
                raise HarnessError("请先确认任务理解，再搜索模型来源")
            plan = _model_search_plan(task, query)

        token_map = tokens or {}

        def invoke(provider_id: str) -> tuple[str, tuple[dict[str, Any], ...]]:
            provider = self.model_source_providers[provider_id]
            search = getattr(provider, "search", None)
            if not callable(search):
                raise HarnessError(f"{provider_id}未提供官方目录搜索")
            kwargs: dict[str, Any] = {
                "limit": limit_per_provider,
                "token": token_map.get(provider_id),
            }
            if provider_id == "huggingface":
                kwargs["pipeline_tag"] = plan["pipeline_tag"]
            return provider_id, tuple(search(plan["effective_query"], **kwargs))

        candidates: list[dict[str, Any]] = []
        provider_errors: list[dict[str, str]] = []
        with ThreadPoolExecutor(max_workers=len(requested_providers)) as executor:
            futures = {
                executor.submit(invoke, provider_id): provider_id
                for provider_id in requested_providers
            }
            for future in as_completed(futures):
                provider_id = futures[future]
                try:
                    returned_provider, returned = future.result()
                    if returned_provider != provider_id:
                        raise HarnessError("模型搜索Provider返回不匹配")
                    candidates.extend(
                        _decorate_model_source_candidate(item) for item in returned
                    )
                except Exception as exc:
                    if isinstance(exc, (ContractError, HarnessError)):
                        reason = str(exc)
                    else:
                        reason = "provider_search_failed"
                    provider_errors.append(
                        {"provider": provider_id, "reason": reason, "retry": "retry_search"}
                    )
        candidates.sort(key=_rank_model_source_candidate)
        search_record = self.model_source_store.create_search_record(
            task_id,
            base_spec_revision=base_spec_revision,
            query_plan=plan,
            providers=requested_providers,
            candidates=candidates,
            provider_errors=provider_errors,
            auth_tokens=tuple(token_map.values()),
        )
        all_providers_failed = (
            not candidates and len(provider_errors) == len(requested_providers)
        )
        if all_providers_failed:
            reasons = ",".join(
                f"{item['provider']}:{item['reason']}" for item in provider_errors
            )
            error = ModelSourceUpstreamError(
                f"model_source_search_failed:{reasons}"
            )
            self._record_model_source_blocker(
                task_id,
                stage="source_discovery",
                error=error,
                retry_action="retry_model_source_search",
                details={
                    "providers": list(requested_providers),
                    "search_id": search_record["search_id"],
                },
            )
            raise error
        self.blocker_store.resolve_active_stage(
            task_id,
            "source_discovery",
            action="official_catalog_search_succeeded",
            related_object_type="SourceSearchRecord",
            related_object_id=str(search_record["search_id"]),
        )
        return {
            "search_id": search_record["search_id"],
            "task_id": task_id,
            "base_spec_revision": base_spec_revision,
            "query_plan": deepcopy(search_record["query_plan"]),
            "providers": list(requested_providers),
            "candidates": deepcopy(search_record["candidates"]),
            "provider_errors": deepcopy(search_record["provider_errors"]),
            "execution_policy": "catalog_metadata_only_no_download_no_execution",
        }

    def create_model_source_resolution(
        self,
        task_id: str,
        *,
        provider: str,
        repository: str,
        requested_revision: str | None,
        base_spec_revision: int,
        token: str | None = None,
        selection_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Resolve a mutable source reference without reading repository files."""

        selected_provider = str(provider).strip().lower()
        if selected_provider not in self.model_source_providers:
            raise ContractError("未知模型来源Provider")
        if (
            isinstance(base_spec_revision, bool)
            or not isinstance(base_spec_revision, int)
            or base_spec_revision < 1
        ):
            raise ContractError("base_spec_revision必须是正整数")
        with self._lock:
            task = read_json(self._task_path(task_id))
            if task.get("archived_at_utc"):
                raise HarnessError("归档任务不能绑定新的模型来源")
            if task.get("status") == "running":
                raise HarnessError("运行中不能解析新的模型来源")
            spec = self._ensure_spec_revision(task)
            if int(spec["revision"]) != base_spec_revision:
                raise HarnessError(
                    f"TaskSpec已更新到 revision {spec['revision']}，请刷新后重试"
                )
            source_provider = self.model_source_providers[selected_provider]

        try:
            resolved = source_provider.resolve(
                repository,
                requested_revision,
                token=token,
            )
        except ModelSourceError as error:
            self._record_model_source_blocker(
                task_id,
                stage="source_resolution",
                error=error,
                retry_action="edit_or_retry_model_source",
                details={
                    "provider": selected_provider,
                    "repository": str(repository)[:200],
                },
            )
            raise
        if resolved.provider != selected_provider:
            raise HarnessError("模型来源Provider返回了不匹配的来源")

        with self._lock:
            task = read_json(self._task_path(task_id))
            self._require_task_mutable(task, "保存模型来源解析")
            current_spec = self._ensure_spec_revision(task)
            if int(current_spec["revision"]) != base_spec_revision:
                raise HarnessError(
                    f"TaskSpec已更新到 revision {current_spec['revision']}，来源未保存"
                )
            resolution = self.model_source_store.create_resolution(
                task_id,
                provider=resolved.provider,
                repository=resolved.repository,
                requested_revision=resolved.requested_revision,
                resolved_commit=resolved.resolved_commit,
                source_uri=(
                    f"https://github.com/{resolved.repository}"
                    if resolved.provider == "github"
                    else f"https://huggingface.co/{resolved.repository}"
                ),
                details={
                    "base_spec_revision": base_spec_revision,
                    "license": resolved.license,
                    "license_status": resolved.license_status,
                    "tree_reference": resolved.tree_reference,
                    "provider_metadata": dict(resolved.metadata),
                    "selection_context": deepcopy(selection_context or {"origin": "manual"}),
                },
                auth_token=token,
            )
            self.blocker_store.resolve_active_stage(
                task_id,
                "source_resolution",
                action="source_resolution_succeeded",
                related_object_type="SourceResolution",
                related_object_id=str(resolution["resolution_id"]),
            )
        return {"resolution": resolution}

    def create_model_source_resolution_from_reference(
        self,
        task_id: str,
        *,
        source_reference: str,
        provider_hint: str | None,
        requested_revision: str | None,
        base_spec_revision: int,
        token: str | None = None,
    ) -> dict[str, Any]:
        parsed = parse_model_source_reference(
            source_reference,
            provider_hint=provider_hint,
        )
        selected_revision = requested_revision or parsed["requested_revision"]
        return self.create_model_source_resolution(
            task_id,
            provider=parsed["provider"],
            repository=parsed["repository"],
            requested_revision=selected_revision,
            base_spec_revision=base_spec_revision,
            token=token,
            selection_context={
                "origin": "manual_reference",
                "source_reference_host": (
                    "github.com"
                    if parsed["provider"] == "github"
                    else "huggingface.co"
                ),
            },
        )

    def confirm_model_source_candidate(
        self,
        task_id: str,
        *,
        search_id: str,
        candidate_id: str,
        approval_confirmed: bool,
        base_spec_revision: int,
        tokens: dict[str, str | None] | None = None,
    ) -> dict[str, Any]:
        if approval_confirmed is not True:
            raise HarnessError("选择模型来源需要明确确认")
        search_record = self.model_source_store.get_search_record(task_id, search_id)
        if search_record.get("base_spec_revision") != base_spec_revision:
            raise HarnessError("搜索结果基于过期的TaskSpec，请重新搜索")
        candidate = next(
            (
                item
                for item in search_record.get("candidates", [])
                if item.get("candidate_id") == candidate_id
            ),
            None,
        )
        if not isinstance(candidate, dict):
            raise ContractError("候选模型不属于该搜索记录")
        provider = str(candidate.get("provider") or "").strip().lower()
        repository = str(candidate.get("repository") or "").strip()
        requested_revision = str(
            candidate.get("requested_revision") or "main"
        ).strip()
        supplied_candidate_id = str(candidate.get("candidate_id") or "").strip()
        expected_candidate_id = source_candidate_id(
            provider, repository, requested_revision
        )
        if supplied_candidate_id != expected_candidate_id:
            raise ContractError("候选模型标识已变化，请重新搜索")
        query_plan = search_record.get("query_plan", {})
        selected_query = str(
            query_plan.get("user_query") or query_plan.get("effective_query") or ""
        ).strip()
        token = (tokens or {}).get(provider)
        return self.create_model_source_resolution(
            task_id,
            provider=provider,
            repository=repository,
            requested_revision=requested_revision,
            base_spec_revision=base_spec_revision,
            token=token,
            selection_context={
                "origin": "official_catalog_search",
                "search_id": str(search_record["search_id"]),
                "search_digest": str(search_record["content_digest"]),
                "candidate_id": expected_candidate_id,
                "search_query": selected_query or None,
                "catalog_evidence": str(
                    candidate.get("catalog_evidence") or "official_provider_api"
                )[:120],
                "approved": True,
            },
        )

    def get_model_source_resolution(
        self,
        task_id: str,
        resolution_id: str,
    ) -> dict[str, Any]:
        read_json(self._task_path(task_id))
        return self.model_source_store.get_resolution(task_id, resolution_id)

    def get_model_source_search(
        self,
        task_id: str,
        search_id: str,
    ) -> dict[str, Any]:
        read_json(self._task_path(task_id))
        return self.model_source_store.get_search_record(task_id, search_id)

    def list_model_source_searches(self, task_id: str) -> list[dict[str, Any]]:
        read_json(self._task_path(task_id))
        return self.model_source_store.list_search_records(task_id)

    def list_model_source_resolutions(self, task_id: str) -> list[dict[str, Any]]:
        read_json(self._task_path(task_id))
        return self.model_source_store.list_resolutions(task_id)

    def queue_model_source_binding(
        self,
        task_id: str,
        resolution_id: str,
        *,
        approval_confirmed: bool,
        expected_resolved_commit: str,
        base_spec_revision: int,
        token: str | None = None,
    ) -> dict[str, Any]:
        """Persist a binding/analysis attempt before any remote source read."""

        if approval_confirmed is not True:
            raise HarnessError("绑定模型来源需要明确批准")
        expected_commit = str(expected_resolved_commit).strip().lower()
        if not re.fullmatch(r"[0-9a-f]{40}", expected_commit):
            raise ContractError("expected_resolved_commit必须是40位commit")
        if (
            isinstance(base_spec_revision, bool)
            or not isinstance(base_spec_revision, int)
            or base_spec_revision < 1
        ):
            raise ContractError("base_spec_revision必须是正整数")

        with self._lock:
            task = read_json(self._task_path(task_id))
            if task.get("archived_at_utc"):
                raise HarnessError("归档任务不能绑定新的模型来源")
            if task.get("status") == "running":
                raise HarnessError("运行中不能更换模型来源")
            spec = self._ensure_spec_revision(task)
            if int(spec["revision"]) != base_spec_revision:
                raise HarnessError(
                    f"TaskSpec已更新到 revision {spec['revision']}，请刷新后重试"
                )
            resolution = self.model_source_store.get_resolution(
                task_id, resolution_id
            )
            if resolution["resolved_commit"] != expected_commit:
                raise HarnessError("批准的commit与已解析来源不一致")
            if resolution.get("details", {}).get(
                "base_spec_revision"
            ) != base_spec_revision:
                raise HarnessError("来源解析基于过期的TaskSpec")
            if str(resolution["provider"]) not in self.model_source_providers:
                raise ContractError("模型来源Provider当前不可用")
            if self._binding_executor_closed:
                raise HarnessError("模型绑定后台执行器已停止")
            attempt = self.binding_analysis_attempt_store.create_attempt(
                task_id,
                resolution_id=resolution_id,
                resolution_digest=str(resolution["content_digest"]),
                expected_resolved_commit=expected_commit,
                base_spec_revision=base_spec_revision,
                analyzer_version=ANALYZER_VERSION,
            )
            attempt_id = str(attempt["attempt"]["attempt_id"])
            if (
                attempt["current_state"]["status"] == "queued"
                and attempt_id not in self._binding_futures
            ):
                future = self._binding_executor.submit(
                    self._execute_model_source_binding_attempt,
                    task_id,
                    attempt_id,
                    resolution_id,
                    expected_commit,
                    base_spec_revision,
                    token,
                )
                self._binding_futures[attempt_id] = future
                future.add_done_callback(
                    lambda _future, selected_id=attempt_id: self._forget_binding_future(
                        selected_id, _future
                    )
                )
        return deepcopy(attempt)

    def get_model_binding_attempt(
        self, task_id: str, attempt_id: str
    ) -> dict[str, Any]:
        read_json(self._task_path(task_id))
        return self.binding_analysis_attempt_store.get_attempt(task_id, attempt_id)

    def current_model_binding_attempt(
        self, task_id: str
    ) -> dict[str, Any] | None:
        read_json(self._task_path(task_id))
        return self.binding_analysis_attempt_store.current_attempt(task_id)

    def list_model_binding_attempts(self, task_id: str) -> list[dict[str, Any]]:
        read_json(self._task_path(task_id))
        return [
            self.binding_analysis_attempt_store.get_attempt(
                task_id, str(item["attempt_id"])
            )
            for item in self.binding_analysis_attempt_store.list_attempts(task_id)
        ]

    def cancel_model_binding_attempt(
        self,
        task_id: str,
        attempt_id: str,
        *,
        reason: str = "用户取消模型来源绑定与静态分析",
    ) -> dict[str, Any]:
        """Cancel one active source-read attempt without creating a binding.

        The workspace lock is the linearization boundary shared with the final
        snapshot/analysis/binding commit.  A cancellation that acquires it
        first wins and the background worker must leave zero binding result;
        once the final commit wins, cancellation reports that the attempt is
        already terminal instead of rewriting history.
        """

        with self._lock:
            read_json(self._task_path(task_id))
            attempt = self.binding_analysis_attempt_store.get_attempt(
                task_id, attempt_id
            )
            status = str(attempt["current_state"]["status"])
            if status not in {"queued", "running"}:
                return {"cancelled": False, "binding_attempt": attempt}
            cancelled = self.binding_analysis_attempt_store.cancel(
                task_id,
                attempt_id,
                reason=reason,
            )
            future = self._binding_futures.get(attempt_id)
            if future is not None:
                future.cancel()
            return {"cancelled": True, "binding_attempt": cancelled}

    def _execute_model_source_binding_attempt(
        self,
        task_id: str,
        attempt_id: str,
        resolution_id: str,
        expected_commit: str,
        base_spec_revision: int,
        token: str | None,
    ) -> None:
        try:
            current = self.binding_analysis_attempt_store.get_attempt(
                task_id, attempt_id
            )
            if current["current_state"]["status"] != "queued":
                return
            self.binding_analysis_attempt_store.mark_running(task_id, attempt_id)
            result = self.bind_model_source(
                task_id,
                resolution_id,
                approval_confirmed=True,
                expected_resolved_commit=expected_commit,
                base_spec_revision=base_spec_revision,
                token=token,
                binding_attempt_id=attempt_id,
            )
            # ``bind_model_source`` appends the completed attempt while holding
            # the same workspace lock as the final binding commit.  Reading the
            # result here only asserts that the atomic finalization happened.
            if result["binding"]["binding_revision_id"]:
                completed = self.binding_analysis_attempt_store.get_attempt(
                    task_id, attempt_id
                )
                if completed["current_state"]["status"] != "completed":
                    raise HarnessError("模型来源绑定已提交但Attempt未形成完成证据")
        except Exception as error:
            try:
                attempt = self.binding_analysis_attempt_store.get_attempt(
                    task_id, attempt_id
                )
                if attempt["current_state"]["status"] in {"queued", "running"}:
                    raw_message = " ".join(str(error).split()) or error.__class__.__name__
                    if token:
                        raw_message = raw_message.replace(token, "[REDACTED]")
                    safe_code = re.sub(
                        r"[^a-z0-9._:-]+",
                        "_",
                        error.__class__.__name__.lower(),
                    )[:160]
                    self.binding_analysis_attempt_store.fail(
                        task_id,
                        attempt_id,
                        stage="binding_and_repository_analysis",
                        code=safe_code or "binding_analysis_failed",
                        message=raw_message[:1000],
                        retryable=isinstance(
                            error, (ModelSourceError, RepositoryAnalysisError)
                        ),
                        details={
                            "resolution_id": resolution_id,
                            "expected_resolved_commit": expected_commit,
                        },
                    )
            except Exception:
                # The original immutable attempt and any already-written state
                # remain the recovery source even if failure projection itself
                # cannot be appended because of an integrity violation.
                return

    def _forget_binding_future(self, attempt_id: str, future: Any) -> None:
        with self._lock:
            if self._binding_futures.get(attempt_id) is future:
                self._binding_futures.pop(attempt_id, None)

    def bind_model_source(
        self,
        task_id: str,
        resolution_id: str,
        *,
        approval_confirmed: bool,
        expected_resolved_commit: str,
        base_spec_revision: int,
        token: str | None = None,
        binding_attempt_id: str | None = None,
    ) -> dict[str, Any]:
        """Create a static source snapshot and atomically bind it to a task."""

        if approval_confirmed is not True:
            raise HarnessError("绑定模型来源需要明确批准")
        expected_commit = str(expected_resolved_commit).strip().lower()
        if not re.fullmatch(r"[0-9a-f]{40}", expected_commit):
            raise ContractError("expected_resolved_commit必须是40位commit")
        if (
            isinstance(base_spec_revision, bool)
            or not isinstance(base_spec_revision, int)
            or base_spec_revision < 1
        ):
            raise ContractError("base_spec_revision必须是正整数")

        with self._lock:
            task = read_json(self._task_path(task_id))
            if task.get("archived_at_utc"):
                raise HarnessError("归档任务不能绑定新的模型来源")
            if task.get("status") == "running":
                raise HarnessError("运行中不能更换模型来源")
            spec = self._ensure_spec_revision(task)
            if int(spec["revision"]) != base_spec_revision:
                raise HarnessError(
                    f"TaskSpec已更新到 revision {spec['revision']}，请刷新后重试"
                )
            resolution = self.model_source_store.get_resolution(
                task_id, resolution_id
            )
            if resolution["resolved_commit"] != expected_commit:
                raise HarnessError("批准的commit与已解析来源不一致")
            resolution_base = resolution.get("details", {}).get(
                "base_spec_revision"
            )
            if resolution_base != base_spec_revision:
                raise HarnessError("来源解析基于过期的TaskSpec")
            provider_id = str(resolution["provider"])
            source_provider = self.model_source_providers.get(provider_id)
            if source_provider is None:
                raise ContractError("模型来源Provider当前不可用")
            current = self.model_source_store.current_binding(task_id)
            if (
                current is not None
                and current.get("resolution_id") == resolution_id
                and task.get("current_model_binding_revision_id")
                == current.get("binding_revision_id")
                and not task.get("model_binding_stale_for_spec_revision")
            ):
                context = self.model_source_store.binding_context(
                    task_id, str(current["binding_revision_id"])
                )
                assert context is not None
                if (
                    context["analysis"]["analysis"].get("analyzer_version")
                    == ANALYZER_VERSION
                ):
                    return {
                        "task": self.get_task(task_id),
                        "binding": self._model_binding_projection(
                            task, current, context, current_binding_id=str(current["binding_revision_id"])
                        ),
                        "analysis": deepcopy(context["analysis"]["analysis"]),
                    }
            details = resolution.get("details", {})
            resolved_source = ResolvedSource(
                provider=provider_id,
                repository=str(resolution["repository"]),
                requested_revision=str(resolution["requested_revision"]),
                resolved_commit=str(resolution["resolved_commit"]),
                license=str(details.get("license") or "unknown"),
                license_status=str(details.get("license_status") or "unknown"),
                tree_reference=(
                    str(details["tree_reference"])
                    if details.get("tree_reference") is not None
                    else None
                ),
                metadata=(
                    deepcopy(details["provider_metadata"])
                    if isinstance(details.get("provider_metadata"), dict)
                    else {}
                ),
            )

        try:
            files = source_provider.list_tree(resolved_source, token=token)
            documents = collect_source_documents(
                source_provider,
                resolved_source,
                files,
                token=token,
            )
        except ModelSourceError as error:
            self._record_model_source_blocker(
                task_id,
                stage="source_snapshot",
                error=error,
                retry_action="retry_model_source_binding",
                related_object_type="SourceResolution",
                related_object_id=resolution_id,
                details={
                    "provider": resolved_source.provider,
                    "repository": resolved_source.repository,
                    "resolved_commit": resolved_source.resolved_commit,
                },
            )
            raise

        with self._lock:
            task = read_json(self._task_path(task_id))
            self._require_task_mutable(task, "提交模型来源绑定")
            if binding_attempt_id is not None:
                attempt = self.binding_analysis_attempt_store.get_attempt(
                    task_id, binding_attempt_id
                )
                if attempt["current_state"]["status"] != "running":
                    raise HarnessError("模型来源绑定已取消，未写入来源快照或绑定")
            current_spec = self._ensure_spec_revision(task)
            if int(current_spec["revision"]) != base_spec_revision:
                raise HarnessError(
                    f"TaskSpec已更新到 revision {current_spec['revision']}，来源未绑定"
                )
            resolution = self.model_source_store.get_resolution(
                task_id, resolution_id
            )
            if resolution["resolved_commit"] != expected_commit:
                raise HarnessError("来源commit在绑定前发生变化")
            snapshot = self.model_source_store.create_snapshot(
                task_id,
                resolution_id=resolution_id,
                files=files,
                documents=documents,
                license=resolved_source.license,
                license_status=resolved_source.license_status,
                details={"collection_policy": "bounded_static_documents_v1"},
            )
            source_snapshot = self.model_source_store.load_source_snapshot(
                task_id, str(snapshot["snapshot_id"])
            )
            current_attempt = self.repository_analysis_store.current_attempt(
                task_id, str(snapshot["snapshot_id"])
            )
            if current_attempt is None:
                analysis_attempt = self.repository_analysis_store.create_attempt(
                    task_id,
                    snapshot_id=str(snapshot["snapshot_id"]),
                    snapshot_digest=str(snapshot["content_digest"]),
                    expected_resolved_commit=source_snapshot.resolved_commit,
                    analyzer_version=ANALYZER_VERSION,
                )
            elif (
                current_attempt["current_state"]["status"] == "completed"
                and current_attempt["attempt"].get("analyzer_version")
                == ANALYZER_VERSION
            ):
                analysis_attempt = current_attempt
            elif current_attempt["current_state"]["status"] == "completed":
                analysis_attempt = self.repository_analysis_store.retry(
                    task_id,
                    str(current_attempt["attempt"]["attempt_id"]),
                    analyzer_version=ANALYZER_VERSION,
                    expected_resolved_commit=source_snapshot.resolved_commit,
                )
            else:
                current_status = current_attempt["current_state"]["status"]
                if current_status in {"queued", "running"}:
                    if current_status == "queued":
                        self.repository_analysis_store.mark_running(
                            task_id,
                            str(current_attempt["attempt"]["attempt_id"]),
                        )
                    self.repository_analysis_store.fail(
                        task_id,
                        str(current_attempt["attempt"]["attempt_id"]),
                        stage="static_repository_analysis",
                        code="interrupted_analysis_attempt",
                        message="上一轮静态分析未形成终态，已保留并创建重试 attempt。",
                        retryable=True,
                        details={"previous_status": current_status},
                    )
                analysis_attempt = self.repository_analysis_store.retry(
                    task_id,
                    str(current_attempt["attempt"]["attempt_id"]),
                    expected_resolved_commit=source_snapshot.resolved_commit,
                )
            attempt_status = analysis_attempt["current_state"]["status"]
            if attempt_status == "queued":
                self.repository_analysis_store.mark_running(
                    task_id, str(analysis_attempt["attempt"]["attempt_id"])
                )
            try:
                domain_analysis = self.repository_analyzer.analyze(source_snapshot)
            except Exception as error:
                error_code = re.sub(
                    r"[^a-zA-Z0-9._:-]+", "_", str(error).strip()
                )[:160] or error.__class__.__name__
                if analysis_attempt["current_state"]["status"] != "completed":
                    self.repository_analysis_store.fail(
                        task_id,
                        str(analysis_attempt["attempt"]["attempt_id"]),
                        stage="static_repository_analysis",
                        code=error_code,
                        message=str(error)[:1000] or "repository analysis failed",
                        retryable=isinstance(
                            error, (RepositoryAnalysisError, ModelSourceError)
                        ),
                        details={"snapshot_id": str(snapshot["snapshot_id"])},
                    )
                if isinstance(error, (RepositoryAnalysisError, ModelSourceError)):
                    self._record_model_source_blocker(
                        task_id,
                        stage="repository_analysis",
                        error=error,
                        retry_action="review_or_retry_repository_analysis",
                        related_object_type="SourceSnapshot",
                        related_object_id=str(snapshot["snapshot_id"]),
                    )
                raise
            if analysis_attempt["current_state"]["status"] == "completed":
                persisted_analysis = (
                    analysis_attempt["current_state"].get("result") or {}
                ).get("analysis")
                if persisted_analysis != domain_analysis.to_dict():
                    raise HarnessError(
                        "同一来源快照的静态分析结果发生漂移，请创建新的 analyzer 版本"
                    )
            else:
                self.repository_analysis_store.complete(
                    task_id,
                    str(analysis_attempt["attempt"]["attempt_id"]),
                    analysis=domain_analysis.to_dict(),
                )
            analysis_record = self.model_source_store.create_analysis(
                task_id,
                snapshot_id=str(snapshot["snapshot_id"]),
                analysis=domain_analysis,
            )
            if domain_analysis.downstream_blockers:
                policy = dict(source_snapshot.license_policy) or _license_policy(
                    source_snapshot.license, source_snapshot.license_status
                )
                downstream = domain_analysis.downstream_blockers[0]
                self.blocker_store.append(
                    task_id,
                    stage="training_plan",
                    code="blocked_license",
                    message=downstream.message,
                    retry_action="review_model_source_license",
                    related_object_type="SourceSnapshot",
                    related_object_id=str(snapshot["snapshot_id"]),
                    related_object_digest=str(snapshot["content_digest"]),
                    details={
                        "policy": policy,
                        "downstream_code": downstream.code,
                        "evidence_refs": list(downstream.evidence_refs),
                    },
                    detector="repository_analysis@0.9",
                    facts={
                        "license": source_snapshot.license,
                        "license_status": source_snapshot.license_status,
                        "policy": policy,
                        "downstream_code": downstream.code,
                    },
                    rule={"license_policy_decision_required": "allow"},
                    evidence_refs=list(downstream.evidence_refs),
                    recovery_actions=["review_model_source_license"],
                    retryable=True,
                )
            current = self.model_source_store.current_binding(task_id)
            base_binding_revision = int(current["revision"]) if current else 0
            intent = self.model_source_store.prepare_binding_intent(
                task_id,
                snapshot_id=str(snapshot["snapshot_id"]),
                analysis_id=str(analysis_record["analysis_id"]),
                idempotency_key=(
                    f"{task_id}:{base_spec_revision}:{resolution_id}:"
                    f"{snapshot['content_digest']}:{analysis_record['content_digest']}"
                ),
                base_spec_revision=base_spec_revision,
                base_binding_revision=base_binding_revision,
            )
            binding = self.model_source_store.commit_binding_intent(
                task_id,
                str(intent["intent_id"]),
                expected_intent_digest=str(intent["content_digest"]),
                current_spec_revision=base_spec_revision,
            )
            self._activate_model_binding_on_task(
                task,
                binding,
                bound_spec_revision=base_spec_revision,
            )
            write_json(self._task_path(task_id), task)
            context = self.model_source_store.binding_context(
                task_id, str(binding["binding_revision_id"])
            )
            assert context is not None
            binding_view = self._model_binding_projection(
                task,
                binding,
                context,
                current_binding_id=str(binding["binding_revision_id"]),
            )
            self.blocker_store.resolve_active_stage(
                task_id,
                "source_snapshot",
                action="source_snapshot_created",
                related_object_type="SourceSnapshot",
                related_object_id=str(snapshot["snapshot_id"]),
            )
            if domain_analysis.status == "complete":
                self.blocker_store.resolve_active_stage(
                    task_id,
                    "repository_analysis",
                    action="repository_analysis_completed",
                    related_object_type="RepositoryAnalysis",
                    related_object_id=str(analysis_record["analysis_id"]),
                )
            else:
                self._record_repository_analysis_blocker(
                    task_id,
                    analysis_record,
                )
            if binding_attempt_id is not None:
                self.binding_analysis_attempt_store.complete(
                    task_id,
                    binding_attempt_id,
                    result={
                        "binding_revision_id": binding["binding_revision_id"],
                        "resolution_id": binding["resolution_id"],
                        "snapshot_id": binding["snapshot_id"],
                        "analysis_id": analysis_record["analysis_id"],
                        "binding_status": binding_view["status"],
                    },
                )
        return {
            "task": self.get_task(task_id),
            "binding": binding_view,
            "analysis": deepcopy(analysis_record["analysis"]),
        }

    def list_model_bindings(self, task_id: str) -> list[dict[str, Any]]:
        task = read_json(self._task_path(task_id))
        current = self.model_source_store.current_binding(task_id)
        current_id = str(current["binding_revision_id"]) if current else None
        bindings: list[dict[str, Any]] = []
        for binding in self.model_source_store.list_binding_revisions(task_id):
            context = self.model_source_store.binding_context(
                task_id, str(binding["binding_revision_id"])
            )
            assert context is not None
            bindings.append(
                self._model_binding_projection(
                    task,
                    binding,
                    context,
                    current_binding_id=current_id,
                )
            )
        return bindings

    def get_model_binding(
        self,
        task_id: str,
        binding_revision_id: str,
    ) -> dict[str, Any]:
        task = read_json(self._task_path(task_id))
        binding = self.model_source_store.get_binding_revision(
            task_id, binding_revision_id
        )
        context = self.model_source_store.binding_context(
            task_id, binding_revision_id
        )
        assert context is not None
        current = self.model_source_store.current_binding(task_id)
        return self._model_binding_projection(
            task,
            binding,
            context,
            current_binding_id=(
                str(current["binding_revision_id"]) if current else None
            ),
        )

    def current_model_binding(self, task_id: str) -> dict[str, Any] | None:
        with self._lock:
            task = read_json(self._task_path(task_id))
            binding = self.model_source_store.current_binding(task_id)
            if binding is None:
                return None
            if task.get("current_model_binding_revision_id") != binding.get(
                "binding_revision_id"
            ):
                context = self.model_source_store.binding_context(
                    task_id, str(binding["binding_revision_id"])
                )
                assert context is not None
                bound_spec_revision = int(
                    context["resolution"].get("details", {}).get(
                        "base_spec_revision", 0
                    )
                )
                self._activate_model_binding_on_task(
                    task,
                    binding,
                    bound_spec_revision=bound_spec_revision,
                )
                write_json(self._task_path(task_id), task)
            context = self.model_source_store.binding_context(
                task_id, str(binding["binding_revision_id"])
            )
            assert context is not None
            return self._model_binding_projection(
                task,
                binding,
                context,
                current_binding_id=str(binding["binding_revision_id"]),
            )

    def get_repository_analysis(
        self,
        task_id: str,
        analysis_id: str,
    ) -> dict[str, Any]:
        read_json(self._task_path(task_id))
        record = self.model_source_store.get_analysis(task_id, analysis_id)
        return deepcopy(record["analysis"])

    def get_repository_analysis_envelope(
        self,
        task_id: str,
        analysis_id: str,
    ) -> dict[str, Any]:
        """Project one analysis with only its exact persisted blocker evidence."""

        read_json(self._task_path(task_id))
        record = self.model_source_store.get_analysis(task_id, analysis_id)
        related_blockers = [
            blocker
            for blocker in self.blocker_store.list(task_id)
            if blocker.get("related_object_type") == "RepositoryAnalysis"
            and blocker.get("related_object_id") == record["analysis_id"]
            and blocker.get("related_object_digest") == record["content_digest"]
        ]
        return {
            "analysis": deepcopy(record["analysis"]),
            "analysis_record": {
                "analysis_id": record["analysis_id"],
                "task_id": record["task_id"],
                "content_digest": record["content_digest"],
                "revision": record["revision"],
                "status": record["status"],
            },
            "blockers": deepcopy(related_blockers),
        }

    def get_repository_evidence_excerpt(
        self,
        task_id: str,
        analysis_id: str,
        *,
        path: str,
        line: int,
        context_lines: int = 3,
    ) -> dict[str, Any]:
        """Return a bounded excerpt from the exact captured source document."""

        read_json(self._task_path(task_id))
        if isinstance(line, bool) or not isinstance(line, int) or line < 1:
            raise ContractError("evidence line must be a positive integer")
        if (
            isinstance(context_lines, bool)
            or not isinstance(context_lines, int)
            or context_lines < 0
            or context_lines > 8
        ):
            raise ContractError("context_lines must be between 0 and 8")
        selected_path = str(path or "").strip()
        if (
            not selected_path
            or PurePosixPath(selected_path).is_absolute()
            or ".." in PurePosixPath(selected_path).parts
        ):
            raise ContractError("invalid evidence path")
        record = self.model_source_store.get_analysis(task_id, analysis_id)
        snapshot = self.model_source_store.get_snapshot(
            task_id, str(record["snapshot_id"])
        )
        document = next(
            (
                item
                for item in snapshot.get("documents", [])
                if item.get("path") == selected_path
            ),
            None,
        )
        if not isinstance(document, dict):
            raise FileNotFoundError("evidence document was not captured")
        try:
            content = base64.b64decode(
                str(document["content_base64"]), validate=True
            )
            text = content.decode("utf-8")
        except (KeyError, ValueError, UnicodeDecodeError, binascii.Error) as exc:
            raise ContractError("evidence document failed integrity decoding") from exc
        observed_sha = hashlib.sha256(content).hexdigest()
        if observed_sha != document.get("sha256"):
            raise ContractError("evidence document digest changed")
        lines = text.splitlines()
        if line > max(len(lines), 1):
            raise ContractError("evidence line is outside the captured document")
        start = max(1, line - context_lines)
        end = min(len(lines), line + context_lines)
        return {
            "analysis_id": analysis_id,
            "snapshot_id": snapshot["snapshot_id"],
            "resolved_commit": snapshot["resolved_commit"],
            "path": selected_path,
            "document_sha256": observed_sha,
            "requested_line": line,
            "line_start": start,
            "line_end": end,
            "lines": [
                {"line": index, "text": lines[index - 1]}
                for index in range(start, end + 1)
            ],
        }

    def apply_repository_manual_mapping(
        self,
        task_id: str,
        analysis_id: str,
        *,
        training_entrypoint: str,
        dataset_argument: str | None = None,
        inference_entrypoint: str | None = None,
    ) -> dict[str, Any]:
        """Create a traceable analysis + binding revision from user mapping.

        Manual mapping only changes interpretation of the already captured,
        immutable source snapshot. It never reads a local checkout and never
        executes repository code.
        """

        def selected_path(value: str, field: str) -> str:
            candidate = str(value or "").strip()
            parsed = PurePosixPath(candidate)
            if (
                not candidate
                or parsed.is_absolute()
                or ".." in parsed.parts
                or any(ord(character) < 32 for character in candidate)
            ):
                raise ContractError(f"invalid {field}")
            return candidate

        selected_training = selected_path(
            training_entrypoint, "training entrypoint"
        )
        if PurePosixPath(selected_training).suffix.lower() != ".py":
            raise ContractError(
                "V3 manual mapping currently supports only Python training entrypoints"
            )
        selected_inference = (
            selected_path(inference_entrypoint, "inference entrypoint")
            if inference_entrypoint is not None
            and str(inference_entrypoint).strip()
            else None
        )
        if (
            selected_inference is not None
            and PurePosixPath(selected_inference).suffix.lower() != ".py"
        ):
            raise ContractError(
                "V3 manual mapping currently supports only Python inference entrypoints"
            )
        selected_dataset_argument = (
            str(dataset_argument).strip()
            if dataset_argument is not None and str(dataset_argument).strip()
            else None
        )
        if selected_dataset_argument is not None and (
            len(selected_dataset_argument) > 200
            or any(ord(character) < 32 for character in selected_dataset_argument)
        ):
            raise ContractError("invalid dataset argument")

        with self._lock:
            task = read_json(self._task_path(task_id))
            self._require_task_mutable(task, "修改仓库分析映射")
            current_spec = self._ensure_spec_revision(task)
            current_binding = self.model_source_store.current_binding(task_id)
            if current_binding is None:
                raise ContractError("current model binding not found")
            context = self.model_source_store.binding_context(
                task_id, str(current_binding["binding_revision_id"])
            )
            assert context is not None
            current_analysis_record = context["analysis"]
            if current_analysis_record["analysis_id"] != analysis_id:
                raise ContractError("repository analysis is no longer current")
            snapshot = context["snapshot"]
            valid_files = {
                str(item.get("path")): str(item.get("kind"))
                for item in snapshot.get("files", [])
                if isinstance(item, dict)
                and item.get("kind") in {"blob", "executable"}
            }
            if selected_training not in valid_files:
                raise ContractError(
                    "training entrypoint is not an executable file in the current snapshot"
                )
            if (
                selected_inference is not None
                and selected_inference not in valid_files
            ):
                raise ContractError(
                    "inference entrypoint is not an executable file in the current snapshot"
                )

            current_attempt = self.repository_analysis_store.current_attempt(
                task_id, str(snapshot["snapshot_id"])
            )
            if current_attempt is None:
                raise ContractError("repository analysis attempt not found")
            if current_attempt["current_state"]["status"] not in {
                "completed",
                "failed",
                "cancelled",
            }:
                raise ContractError("repository analysis is still running")

            mapping_payload: dict[str, Any] = {
                "training_entrypoint": selected_training,
            }
            if selected_dataset_argument is not None:
                mapping_payload["dataset_argument"] = selected_dataset_argument
            if selected_inference is not None:
                mapping_payload["inference_entrypoint"] = selected_inference
            mapping_revision = (
                self.repository_analysis_store.create_manual_mapping_revision(
                    task_id,
                    snapshot_id=str(snapshot["snapshot_id"]),
                    snapshot_digest=str(snapshot["content_digest"]),
                    mapping=mapping_payload,
                    created_by="user",
                )
            )
            base_analyzer_version = str(
                current_analysis_record["analysis"].get("analyzer_version")
                or ANALYZER_VERSION
            ).split("+manual-mapping/", 1)[0]
            manual_analyzer_version = (
                f"{base_analyzer_version}+manual-mapping/0.1"
            )
            retried = self.repository_analysis_store.retry(
                task_id,
                str(current_attempt["attempt"]["attempt_id"]),
                analyzer_version=manual_analyzer_version,
                manual_mapping_revision_id=str(
                    mapping_revision["mapping_revision_id"]
                ),
            )
            attempt_id = str(retried["attempt"]["attempt_id"])
            self.repository_analysis_store.mark_running(task_id, attempt_id)

            analysis = deepcopy(current_analysis_record["analysis"])
            manual_ref = (
                f"manual_mapping:{mapping_revision['mapping_revision_id']}:"
                "training_entrypoint"
            )
            manual_evidence = {
                "kind": "manual_mapping",
                "ref": manual_ref,
                "snapshot_id": snapshot["snapshot_id"],
                "resolved_commit": snapshot["resolved_commit"],
                "mapping_revision_id": mapping_revision[
                    "mapping_revision_id"
                ],
                "mapping_revision_digest": mapping_revision["content_digest"],
            }
            manual_training = {
                "path": selected_training,
                "confidence": 1.0,
                "evidence_refs": [manual_ref],
                "evidence": [manual_evidence],
            }
            existing_training = [
                item
                for item in analysis.get("training_entrypoints", [])
                if isinstance(item, dict)
                and item.get("path") != selected_training
            ]
            analysis["training_entrypoints"] = [
                manual_training,
                *existing_training,
            ]

            existing_inference = [
                item
                for item in analysis.get("inference_entrypoints", [])
                if isinstance(item, dict)
                and item.get("path") != selected_inference
            ]
            if selected_inference is not None:
                inference_ref = (
                    f"manual_mapping:{mapping_revision['mapping_revision_id']}:"
                    "inference_entrypoint"
                )
                existing_inference.insert(
                    0,
                    {
                        "path": selected_inference,
                        "confidence": 1.0,
                        "evidence_refs": [inference_ref],
                        "evidence": [
                            {
                                **manual_evidence,
                                "ref": inference_ref,
                            }
                        ],
                    },
                )
            analysis["inference_entrypoints"] = existing_inference
            analysis["entrypoints"] = [
                {"kind": "train", "symbol": None, **item}
                for item in analysis["training_entrypoints"]
            ] + [
                {"kind": "inference", "symbol": None, **item}
                for item in analysis["inference_entrypoints"]
            ]

            if selected_dataset_argument is not None:
                data_ref = (
                    f"manual_mapping:{mapping_revision['mapping_revision_id']}:"
                    "dataset_argument"
                )
                manual_data_contract = {
                    "name": f"dataset_argument:{selected_dataset_argument}",
                    "evidence_refs": [data_ref],
                    "evidence": [{**manual_evidence, "ref": data_ref}],
                }
                existing_contracts = [
                    item
                    for item in analysis.get("data_contract_hints", [])
                    if isinstance(item, dict)
                    and item.get("name") != manual_data_contract["name"]
                ]
                analysis["data_contract_hints"] = [
                    manual_data_contract,
                    *existing_contracts,
                ]
                analysis["data_contract_candidates"] = deepcopy(
                    analysis["data_contract_hints"]
                )

            risks = analysis.get("risks", [])
            has_blocking_risk = any(
                isinstance(item, dict)
                and str(item.get("severity", "")).lower()
                in {"critical", "high"}
                for item in risks
            )
            is_blocked = bool(analysis.get("downstream_blockers")) or has_blocking_risk
            analysis["status"] = "blocked" if is_blocked else "complete"
            analysis["next_action"] = (
                str(analysis.get("next_action") or "resolve_repository_blocker")
                if is_blocked
                else "ready_for_environment_check"
            )
            analysis["analysis_id"] = (
                "analysis_manual_"
                f"{str(mapping_revision['content_digest'])[:20]}"
            )
            analysis["analyzer_version"] = manual_analyzer_version
            analysis["manual_mapping"] = {
                "mapping_revision_id": mapping_revision[
                    "mapping_revision_id"
                ],
                "mapping_revision_digest": mapping_revision["content_digest"],
                "mapping": deepcopy(mapping_payload),
                "created_by": mapping_revision["created_by"],
            }

            self.repository_analysis_store.complete(
                task_id, attempt_id, analysis=analysis
            )
            stored_analysis = self.model_source_store.create_analysis(
                task_id,
                snapshot_id=str(snapshot["snapshot_id"]),
                analysis=analysis,
            )
            base_binding_revision = int(current_binding["revision"])
            intent = self.model_source_store.prepare_binding_intent(
                task_id,
                snapshot_id=str(snapshot["snapshot_id"]),
                analysis_id=str(stored_analysis["analysis_id"]),
                idempotency_key=(
                    f"{task_id}:{current_spec['revision']}:"
                    f"{mapping_revision['mapping_revision_id']}"
                ),
                base_spec_revision=int(current_spec["revision"]),
                base_binding_revision=base_binding_revision,
            )
            binding = self.model_source_store.commit_binding_intent(
                task_id,
                str(intent["intent_id"]),
                expected_intent_digest=str(intent["content_digest"]),
                current_spec_revision=int(current_spec["revision"]),
            )
            self._activate_model_binding_on_task(
                task,
                binding,
                bound_spec_revision=int(current_spec["revision"]),
            )
            write_json(self._task_path(task_id), task)
            if analysis["status"] == "complete":
                self.blocker_store.resolve_active_stage(
                    task_id,
                    "repository_analysis",
                    action="manual_mapping_confirmed",
                    related_object_type="RepositoryAnalysis",
                    related_object_id=str(stored_analysis["analysis_id"]),
                )
            else:
                self._record_repository_analysis_blocker(
                    task_id,
                    stored_analysis,
                )
            binding_context = self.model_source_store.binding_context(
                task_id, str(binding["binding_revision_id"])
            )
            assert binding_context is not None
            return {
                "task": self.get_task(task_id),
                "binding": self._model_binding_projection(
                    task,
                    binding,
                    binding_context,
                    current_binding_id=str(binding["binding_revision_id"]),
                ),
                "analysis": deepcopy(stored_analysis["analysis"]),
                "analysis_attempt": self.repository_analysis_store.get_attempt(
                    task_id, attempt_id
                ),
                "manual_mapping_revision": mapping_revision,
            }

    def attach_huggingface_model(
        self,
        task_id: str,
        *,
        repo_id: str,
        commit: str,
        approval_confirmed: bool,
        token: str | None = None,
    ) -> dict[str, Any]:
        if approval_confirmed is not True:
            raise HarnessError("Hugging Face模型下载需要明确批准")
        with self._lock:
            task = read_json(self._task_path(task_id))
            spec = self._ensure_spec_revision(task)
            if task.get("status") == "running":
                raise HarnessError("运行中不能更换模型资产")
            if self.model_source_store.current_binding(task_id) is not None:
                raise HarnessError(
                    "任务已有通用模型来源绑定；请通过模型来源换绑流程更新，不能并行维护第二套来源"
                )
            capability = spec.get("capability_request", {})
            if capability.get("modality") != "image" or capability.get("objective") != "classification":
                raise HarnessError("当前HF ONNX资产绑定仅支持图片分类任务")
            spec_revision = int(spec["revision"])

        card = self.huggingface_model_card(
            repo_id,
            revision=commit,
            token=token,
        )
        if card.get("compatibility", {}).get("state") != "compatible_candidate":
            reasons = card.get("compatibility", {}).get("blocking_reasons", [])
            raise HarnessError(f"Hugging Face模型与当前本地训练引擎不兼容：{reasons}")
        asset = download_huggingface_asset(
            self.model_assets,
            repo_id=repo_id,
            commit=commit,
            allow_patterns=("model.onnx", "config.json", "README.md"),
            token=token,
            downloader=self.huggingface_downloader,
        )
        handle = resolve_training_asset(
            self.model_assets,
            asset.asset_id,
            required_files=("model.onnx", "config.json"),
        )
        binding = {
            "asset_id": asset.asset_id,
            "provider": asset.provider,
            "repository": asset.repo_id,
            "requested_revision": asset.requested_revision,
            "resolved_commit": asset.resolved_commit,
            "license": asset.license,
            "manifest_sha256": asset.manifest_sha256,
            "security_status": asset.security_status,
            "binding": "image_classification_onnx_feature_v1",
            "attached_spec_revision": spec_revision,
            "root": str(handle.root),
            "files": [
                {
                    "path": item.relative_path,
                    "size_bytes": item.size_bytes,
                    "sha256": item.sha256,
                }
                for item in asset.files
            ],
            "compatibility": deepcopy(card["compatibility"]),
        }
        with self._lock:
            task = read_json(self._task_path(task_id))
            current_spec = self._ensure_spec_revision(task)
            if int(current_spec["revision"]) != spec_revision:
                raise HarnessError("TaskSpec已修订，资产未绑定到任务")
            history = list(task.get("model_asset_ids", []))
            if asset.asset_id not in history:
                history.append(asset.asset_id)
            task["model_asset_ids"] = history
            task["selected_model_asset_id"] = asset.asset_id
            task["model_asset_binding"] = binding
            task["contract_confirmed"] = False
            task["confirmations"] = {}
            task["confirmed_contract_sha256"] = None
            task["confirmed_contract_revision_id"] = None
            task["current_approval_decision_id"] = None
            task["updated_at_utc"] = _utc_now()
            if self._contract_path(task_id).is_file() and task.get("dataset_id"):
                contract = read_json(self._contract_path(task_id))
                contract["model_asset"] = deepcopy(binding)
                validate_contract(contract, registry=self.runs.registry)
                write_json(self._contract_path(task_id), contract)
                self._record_contract_revision(task, contract)
            write_json(self._task_path(task_id), task)
        return {
            "task": self.get_task(task_id),
            "model_asset": asset.to_dict(),
            "compatibility": card["compatibility"],
        }

    def verify_task_model_asset(self, task_id: str) -> dict[str, Any]:
        task = read_json(self._task_path(task_id))
        asset_id = task.get("selected_model_asset_id")
        if not asset_id:
            raise FileNotFoundError("task model asset not found")
        return self.model_assets.verify(str(asset_id)).to_dict()

    def list_task_spec_revisions(self, task_id: str) -> list[dict[str, Any]]:
        with self._lock:
            task = read_json(self._task_path(task_id))
            self._ensure_spec_revision(task)
            revision_count = int(task["current_spec_revision"])
            return [
                read_json(self._spec_revision_path(task_id, revision))
                for revision in range(1, revision_count + 1)
            ]

    def get_task_spec_revision(self, task_id: str, revision: int) -> dict[str, Any]:
        if revision < 1:
            raise FileNotFoundError("task spec revision not found")
        with self._lock:
            task = read_json(self._task_path(task_id))
            self._ensure_spec_revision(task)
            if revision > int(task["current_spec_revision"]):
                raise FileNotFoundError("task spec revision not found")
            return read_json(self._spec_revision_path(task_id, revision))

    def update_task_spec(
        self,
        task_id: str,
        changes: dict[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(changes, dict):
            raise ContractError("TaskSpec修订必须是对象")
        if "reparse" in changes and not isinstance(changes["reparse"], bool):
            raise ContractError("reparse必须是布尔值")
        with self._lock:
            task = read_json(self._task_path(task_id))
            if task.get("status") == "running":
                raise HarnessError("运行中不能修改任务规格")
            current_spec = self._ensure_spec_revision(task)
            current_revision = int(current_spec["revision"])
            base_revision = changes.get("base_revision")
            if base_revision is not None:
                try:
                    requested_base = int(base_revision)
                except (TypeError, ValueError) as exc:
                    raise ContractError("base_revision必须是整数") from exc
                if requested_base != current_revision:
                    raise HarnessError(
                        f"TaskSpec已更新到 revision {current_revision}，请刷新后重试"
                    )

            selected_name = str(changes.get("name", current_spec["name"])).strip()
            selected_goal = str(
                changes.get("business_goal", current_spec["business_goal"])
            ).strip()
            if not selected_name:
                raise ContractError("任务名称不能为空")
            if not selected_goal:
                raise ContractError("业务目标不能为空")

            capability = deepcopy(current_spec.get("capability_request", {}))
            capability_changes = changes.get("capability_request")
            if capability_changes is not None:
                if not isinstance(capability_changes, dict):
                    raise ContractError("capability_request必须是对象")
                for key, value in capability_changes.items():
                    if value is None or (isinstance(value, str) and not value.strip()):
                        capability.pop(key, None)
                    else:
                        capability[key] = value

            requested_family = changes.get(
                "selected_family",
                changes.get("capability_family"),
            )
            if changes.get("confirm") is True and requested_family is None:
                requested_family = current_spec.get("capability_decision", {}).get(
                    "selected_family"
                )
            if requested_family is not None:
                family = normalize_family(requested_family)
                if family is None:
                    raise ContractError(f"未知能力类型：{requested_family}")
                if family == "custom" and not capability.get("modality"):
                    inferred_modality = modality_from_candidate_families(
                        [
                            item.get("family")
                            for item in current_spec.get(
                                "capability_decision", {}
                            ).get("candidates", [])
                            if isinstance(item, dict)
                        ]
                    )
                    if inferred_modality is not None:
                        capability["modality"] = inferred_modality
                capability = capability_for_family(family, capability)
            capability = self._normalize_capability(capability)

            user_note_value = changes.get("user_note")
            user_note = (
                str(user_note_value).strip()
                if user_note_value is not None and str(user_note_value).strip()
                else None
            )
            revision = current_revision + 1
            now = _utc_now()
            spec = build_task_spec_revision(
                task_id=task_id,
                revision=revision,
                name=selected_name,
                business_goal=selected_goal,
                capability_request=capability,
                created_at_utc=now,
                source="user_revision",
                supersedes_revision=current_revision,
                user_note=user_note,
            )
            if (
                spec["name"] == current_spec["name"]
                and spec["business_goal"] == current_spec["business_goal"]
                and spec["capability_request"]
                == current_spec.get("capability_request", {})
                and (
                    changes.get("reparse") is not True
                    or spec["capability_decision"]
                    == current_spec.get("capability_decision", {})
                )
            ):
                raise ContractError("修订未改变任务规格")

            revision_path = self._spec_revision_path(task_id, revision)
            if revision_path.exists():
                raise HarnessError(f"TaskSpec revision {revision}已存在")
            write_json(revision_path, spec)
            self._apply_spec_to_task(task, spec)
            task["updated_at_utc"] = now
            write_json(self._task_path(task_id), task)
        return self.get_task(task_id)

    def stage_asset(
        self,
        task_id: str,
        payload: bytes,
        filename: str,
        spec_revision: int | None = None,
    ) -> dict[str, Any]:
        """Safely stage Recipe-building samples for the current audio spec.

        Staging is intentionally independent from Dataset import and Run
        creation. A rejected payload may add a quarantined evidence object, but
        this method never mutates ``task.json``.
        """

        with self._lock:
            task = read_json(self._task_path(task_id))
            current_spec = self._ensure_spec_revision(task)
            current_revision = int(current_spec["revision"])
            if spec_revision is not None:
                if isinstance(spec_revision, bool) or not isinstance(spec_revision, int):
                    raise ContractError("spec_revision必须是正整数")
                if spec_revision != current_revision:
                    raise HarnessError(
                        f"TaskSpec已更新到 revision {current_revision}，"
                        "过期规格不能接收暂存样例"
                    )
            decision = current_spec.get("capability_decision", {})
            family = str(decision.get("selected_family") or "")
            if decision.get("status") != "resolved":
                raise HarnessError("任务规格尚未确认，不能暂存Recipe样例")
            if family != "audio_classification":
                raise HarnessError("当前仅支持为已确认的语音分类任务暂存样例")
            if task.get("status") != "needs_recipe" or task.get("capability_status") != "needs_recipe":
                raise HarnessError("当前任务不在等待Recipe构建的状态")
            asset = self._staged_asset_store(task_id).stage_audio_zip(
                payload,
                filename,
                current_revision,
            )
        return {
            "asset": asset,
            "task": self.get_task(task_id),
        }

    def list_staged_assets(self, task_id: str) -> list[dict[str, Any]]:
        with self._lock:
            read_json(self._task_path(task_id))
            return self._staged_asset_store(task_id).list_assets()

    def get_staged_asset(
        self,
        task_id: str,
        asset_id: str,
    ) -> dict[str, Any]:
        with self._lock:
            read_json(self._task_path(task_id))
            try:
                return self._staged_asset_store(task_id).get_asset(asset_id)
            except StagedAssetNotFound as exc:
                # A task-scoped lookup intentionally does not disclose whether
                # the identifier belongs to another task.
                raise FileNotFoundError("staged asset not found") from exc

    def start_recipe_build(
        self,
        task_id: str,
        spec: dict[str, Any] | None = None,
        *,
        build_type: str = "declarative",
    ) -> dict[str, Any]:
        """Author, validate and prepare a task-owned Recipe registration.

        Only the declarative trusted audio engine is accepted. Executable
        source requests are durably recorded as ``blocked_environment`` and
        are never imported or executed by the Harness process.
        """

        with self._lock:
            task = read_json(self._task_path(task_id))
            current_spec = self._ensure_spec_revision(task)
            decision = current_spec.get("capability_decision", {})
            if decision.get("status") != "resolved":
                raise HarnessError("任务规格尚未确认，不能构建Recipe")
            if decision.get("selected_family") != "audio_classification":
                raise HarnessError("当前可信Recipe工厂只支持离线语音关键词分类")
            if task.get("capability_status") != "needs_recipe":
                raise HarnessError("当前任务不在等待Recipe构建的状态")
            staged = [
                asset
                for asset in self._staged_asset_store(task_id).list_assets()
                if int(asset.get("spec_revision", 0))
                == int(current_spec["revision"])
                and asset.get("status") in {"staged", "consumed"}
            ]
            if not staged:
                raise HarnessError("请先为当前TaskSpec上传并通过校验的语音样例ZIP")

            selected_spec = deepcopy(spec or self.recipe_factory.spec_template())
            attempt = self.recipe_factory.start_build(
                task_id=task_id,
                base_spec_revision=int(current_spec["revision"]),
                spec=selected_spec,
                build_type=build_type,
            )
            if attempt["status"] == "authoring":
                attempt = self.recipe_factory.validate(str(attempt["attempt_id"]))
            intent = None
            if attempt["status"] == "awaiting_registration":
                intent = self.recipe_factory.prepare_registration(
                    str(attempt["attempt_id"])
                )
                latest_asset = staged[-1]
                if latest_asset.get("status") == "staged":
                    self._staged_asset_store(task_id).mark_consumed(
                        str(latest_asset["asset_id"])
                    )

            attempt_ids = list(task.get("recipe_build_attempt_ids", []))
            if attempt["attempt_id"] not in attempt_ids:
                attempt_ids.append(attempt["attempt_id"])
            task["recipe_build_attempt_ids"] = attempt_ids
            task["current_recipe_build_id"] = attempt["attempt_id"]
            task["updated_at_utc"] = _utc_now()
            write_json(self._task_path(task_id), task)
        return {
            "task": self.get_task(task_id),
            "build_attempt": self.recipe_factory.get_attempt(
                str(attempt["attempt_id"])
            ),
            "validation_report": (
                self.recipe_factory.validation_report(str(attempt["attempt_id"]))
                if attempt.get("validation_digest")
                else None
            ),
            "registration_intent": intent,
        }

    def list_recipe_builds(self, task_id: str) -> list[dict[str, Any]]:
        task = read_json(self._task_path(task_id))
        attempts: list[dict[str, Any]] = []
        for attempt_id in task.get("recipe_build_attempt_ids", []):
            attempt = self.recipe_factory.get_attempt(str(attempt_id))
            attempts.append(self._recipe_build_view(attempt))
        return attempts

    def get_recipe_build(self, task_id: str, attempt_id: str) -> dict[str, Any]:
        task = read_json(self._task_path(task_id))
        if attempt_id not in task.get("recipe_build_attempt_ids", []):
            raise FileNotFoundError("recipe build not found")
        return self._recipe_build_view(self.recipe_factory.get_attempt(attempt_id))

    def register_recipe_build(
        self,
        task_id: str,
        attempt_id: str,
        approval: dict[str, Any],
        *,
        candidate_digest: str,
        validation_digest: str,
    ) -> dict[str, Any]:
        with self._lock:
            task = read_json(self._task_path(task_id))
            if attempt_id not in task.get("recipe_build_attempt_ids", []):
                raise FileNotFoundError("recipe build not found")
            current_spec = self._ensure_spec_revision(task)
            intent = self.recipe_factory.register(
                attempt_id,
                approval=approval,
                candidate_digest=candidate_digest,
                validation_digest=validation_digest,
                current_spec_revision=int(current_spec["revision"]),
                activate=self._activate_recipe_version,
            )
        return {
            "task": self.get_task(task_id),
            "build_attempt": self._recipe_build_view(
                self.recipe_factory.get_attempt(attempt_id)
            ),
            "registration_intent": intent,
        }

    def reject_recipe_build(
        self,
        task_id: str,
        attempt_id: str,
        *,
        actor: str,
        reason: str,
    ) -> dict[str, Any]:
        task = read_json(self._task_path(task_id))
        if attempt_id not in task.get("recipe_build_attempt_ids", []):
            raise FileNotFoundError("recipe build not found")
        intent = self.recipe_factory.reject_registration(
            attempt_id,
            actor=actor,
            reason=reason,
        )
        return {
            "task": self.get_task(task_id),
            "build_attempt": self._recipe_build_view(
                self.recipe_factory.get_attempt(attempt_id)
            ),
            "registration_intent": intent,
        }

    def select_recipe(self, task_id: str, recipe_id: str) -> dict[str, Any]:
        with self._lock:
            task = read_json(self._task_path(task_id))
            if task["status"] == "running":
                raise HarnessError("运行中不能更换Recipe")
            plugin = self.runs.registry.get_recipe(recipe_id)
            current_spec = self._ensure_spec_revision(task)
            original_capability = deepcopy(
                current_spec.get("capability_request", {})
            )
            if recipe_id not in self._eligible_recipe_ids_for_capability(
                original_capability
            ):
                raise ContractError("所选Recipe与已确认的原始能力规格不匹配")
            if task.get("data_adapter_id") and plugin.manifest.data_adapter != task["data_adapter_id"]:
                raise ContractError("所选Recipe与当前数据适配器不兼容")
            task["recipe_id"] = recipe_id
            task["recipe_source"] = "explicit"
            task["capability_status"] = "matched"
            task["status"] = "data_ready" if task.get("dataset_id") else "awaiting_data"
            task["updated_at_utc"] = _utc_now()
            self._resolve_missing_recipe_evidence(
                task_id,
                action="verified_recipe_selected",
                recipe_id=recipe_id,
            )
            request_path = self._recipe_request_path(task_id)
            if request_path.is_file():
                request = read_json(request_path)
                request["status"] = "resolved"
                request["resolved_recipe_id"] = recipe_id
                request["resolved_at_utc"] = _utc_now()
                request["updated_at_utc"] = request["resolved_at_utc"]
                write_json(request_path, request)
            write_json(self._task_path(task_id), task)
        return self.get_task(task_id)

    def attach_dataset(
        self,
        task_id: str,
        payload: bytes,
        filename: str,
        options: dict[str, Any] | None = None,
        *,
        upload_request_digest_sha256: str | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            task = read_json(self._task_path(task_id))
            if task["status"] == "running":
                raise HarnessError("运行中不能替换数据集")
            selected_options = dict(options or {})
            adapter_id = str(selected_options.get("data_adapter", "")).strip()
            recipe_id = task.get("recipe_id")
            if not adapter_id and recipe_id:
                # ZIP is shared by image-folder and audio-folder adapters. A
                # confirmed Recipe is the authoritative disambiguation signal.
                plugin = self.runs.registry.get_recipe(str(recipe_id))
                adapter_id = str(plugin.manifest.data_adapter or "")
            if adapter_id:
                adapter = self.data_adapters.get(adapter_id)
                if not adapter.supports(filename):
                    raise ContractError(f"数据文件与适配器{adapter_id}不兼容")
            else:
                adapters = self.data_adapters.infer(filename)
                if not adapters:
                    raise ContractError(
                        "没有匹配的数据适配器；请先创建并验证Data Adapter插件"
                    )
                if len(adapters) > 1:
                    raise ContractError("多个数据适配器可以读取该文件，请明确指定data_adapter")
                adapter = adapters[0]

            if recipe_id:
                plugin = self.runs.registry.get_recipe(str(recipe_id))
                if plugin.manifest.data_adapter != adapter.manifest.adapter_id:
                    raise ContractError("当前Recipe与上传文件的数据适配器不兼容")
            else:
                capability = {
                    **task.get("capability_request", {}),
                    "data_adapter": adapter.manifest.adapter_id,
                }
                matches = self.runs.registry.match_recipes(capability)
                if not matches:
                    self._persist_missing_recipe_evidence(
                        task_id,
                        capability,
                        task_spec=self._ensure_spec_revision(task),
                    )
                    task["capability_status"] = "needs_recipe"
                    task["status"] = "needs_recipe"
                    task["updated_at_utc"] = _utc_now()
                    write_json(self._task_path(task_id), task)
                    raise HarnessError("没有匹配Recipe，已生成Recipe Build Request")
                plugin = self.runs.registry.get_recipe(str(matches[0]["plugin_id"]))
                recipe_id = plugin.manifest.plugin_id

            task_dir = self._task_dir(task_id)
            imported = adapter.import_data(
                task_dir / "datasets",
                payload,
                filename,
                {
                    **selected_options,
                    "objective": task.get("capability_request", {}).get("objective", ""),
                },
            )
            report = imported.report
            # Persist the exact upload identity before the task projection is
            # committed.  A processing receipt can then be reconciled after a
            # process crash without guessing from history length alone.
            report["source_payload_sha256"] = hashlib.sha256(payload).hexdigest()
            if upload_request_digest_sha256:
                report["upload_request_digest_sha256"] = str(
                    upload_request_digest_sha256
                )
            write_json(imported.dataset_dir / "dataset_report.json", report)
            if task.get("recipe_source") != "recipe-factory":
                self._append_spec_for_recipe(task, plugin, "dataset_import")
            template = deepcopy(plugin.template())
            contract_overrides = deepcopy(
                task.get("recipe_contract_overrides", {})
            )
            _deep_update(
                template,
                contract_overrides,
            )
            template["task_id"] = task_id
            template["business_goal"] = task["business_goal"]
            template["dataset"].update(imported.contract_dataset)
            prepare_contract = getattr(plugin, "prepare_contract_for_dataset", None)
            if callable(prepare_contract):
                release_gate_overrides = contract_overrides.get("release_gates", {})
                if not isinstance(release_gate_overrides, dict):
                    raise ContractError("recipe_contract_overrides.release_gates必须是对象")
                template = prepare_contract(
                    template,
                    report,
                    overridden_release_gates=set(release_gate_overrides),
                )
            if task.get("model_asset_binding"):
                template["model_asset"] = deepcopy(task["model_asset_binding"])
            current_binding = self.model_source_store.current_binding(task_id)
            if current_binding is not None:
                binding_context = self.model_source_store.binding_context(
                    task_id, str(current_binding["binding_revision_id"])
                )
                assert binding_context is not None
                binding_view = self._model_binding_projection(
                    task,
                    current_binding,
                    binding_context,
                    current_binding_id=str(current_binding["binding_revision_id"]),
                )
                if binding_view["status"] != "active":
                    raise HarnessError("模型来源绑定已失效，不能生成训练合同")
                template["model_binding"] = self._contract_model_binding(
                    binding_view
                )
            task["dataset_id"] = report["dataset_id"]
            task["dataset_history"] = [*task.get("dataset_history", []), report["dataset_id"]]
            task["recipe_id"] = recipe_id
            task["recipe_source"] = task.get("recipe_source") or "matched-from-data"
            task["capability_status"] = "matched"
            self._resolve_missing_recipe_evidence(
                task_id,
                action="verified_recipe_matched_from_data",
                recipe_id=str(recipe_id),
            )
            task["data_adapter_id"] = adapter.manifest.adapter_id
            task["contract_confirmed"] = False
            task["confirmations"] = {}
            task["confirmed_contract_sha256"] = None
            if task.get("current_run_id"):
                task["last_run_id"] = task["current_run_id"]
                task["current_run_id"] = None
            task["status"] = "data_ready"
            task["updated_at_utc"] = _utc_now()
            write_json(self._contract_path(task_id), template)
            self._record_contract_revision(task, template)
            write_json(self._task_path(task_id), task)
        return self.get_task(task_id)

    @staticmethod
    def _normalize_dataset_upload_request_id(request_id: str) -> str:
        selected = str(request_id or "").strip()
        if not selected:
            raise ContractError("x-request-id不能为空")
        if len(selected) > 256 or any(ord(character) < 32 for character in selected):
            raise ContractError("x-request-id格式无效")
        return selected

    @staticmethod
    def _dataset_upload_request_digest(
        task_id: str,
        request_id: str,
        payload: bytes,
        filename: str,
        options: Mapping[str, Any],
    ) -> tuple[str, str]:
        payload_sha256 = hashlib.sha256(payload).hexdigest()
        request_digest = _canonical_digest(
            {
                "task_id": task_id,
                "request_id": request_id,
                "payload_sha256": payload_sha256,
                "filename": filename,
                "options": deepcopy(dict(options)),
            }
        )
        return payload_sha256, request_digest

    @staticmethod
    def _seal_dataset_upload_receipt(receipt: Mapping[str, Any]) -> dict[str, Any]:
        selected = deepcopy(dict(receipt))
        selected.pop("receipt_sha256", None)
        selected["receipt_sha256"] = _canonical_digest(selected)
        return selected

    def _read_dataset_upload_receipt(
        self,
        task_id: str,
        request_id: str,
    ) -> dict[str, Any]:
        selected_request_id = self._normalize_dataset_upload_request_id(request_id)
        path = self._dataset_upload_receipt_path(task_id, selected_request_id)
        if not path.is_file():
            raise FileNotFoundError("dataset upload receipt not found")
        receipt = read_json(path)
        if (
            receipt.get("task_id") != task_id
            or receipt.get("request_id") != selected_request_id
        ):
            raise HarnessError("dataset upload receipt identity mismatch")
        expected_seal = str(receipt.get("receipt_sha256") or "")
        unsigned = {
            key: value for key, value in receipt.items() if key != "receipt_sha256"
        }
        if (
            not re.fullmatch(r"[0-9a-f]{64}", expected_seal)
            or expected_seal != _canonical_digest(unsigned)
        ):
            raise HarnessError("dataset upload receipt integrity mismatch")
        if receipt.get("status") == "completed":
            dataset_id = str(receipt.get("dataset_id") or "")
            task = read_json(self._task_path(task_id))
            report_path = (
                self._task_dir(task_id)
                / "datasets"
                / dataset_id
                / "dataset_report.json"
            )
            if (
                dataset_id not in task.get("dataset_history", [])
                or not report_path.is_file()
            ):
                raise HarnessError(
                    "dataset upload receipt points to unavailable dataset"
                )
        return receipt

    @contextmanager
    def _dataset_upload_process_lock(self, task_id: str) -> Any:
        """Serialize dataset receipt allocation across local server processes."""

        lock_path = self._task_dir(task_id) / "dataset_upload_receipts" / ".upload.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        handle = lock_path.open("a+b")
        lock_acquired = False
        try:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                lock_acquired = True
            elif msvcrt is not None:  # pragma: no cover - Windows only
                if handle.tell() == 0 and lock_path.stat().st_size == 0:
                    handle.write(b"\0")
                    handle.flush()
                handle.seek(0)
                deadline = time.monotonic() + DATASET_UPLOAD_LOCK_TIMEOUT_SECONDS
                while True:
                    try:
                        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                        lock_acquired = True
                        break
                    except OSError as error:
                        if time.monotonic() >= deadline:
                            raise HarnessError(
                                "另一进程正在导入该任务的数据，请稍后用同一请求重试"
                            ) from error
                        time.sleep(DATASET_UPLOAD_LOCK_POLL_SECONDS)
            else:  # pragma: no cover - unsupported Python platform
                raise HarnessError("当前平台不支持安全的数据导入进程锁")
            yield
        finally:
            if lock_acquired and fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            elif lock_acquired and msvcrt is not None:  # pragma: no cover - Windows only
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            handle.close()

    def _reconcile_processing_dataset_upload_receipt(
        self,
        task_id: str,
        receipt_path: Path,
        receipt: Mapping[str, Any],
    ) -> dict[str, Any] | None:
        """Recover a receipt interrupted around the task commit boundary.

        ``attach_dataset`` commits the inspected dataset and task projection
        before the receipt becomes ``completed``.  After a process crash, the
        immutable task history therefore tells us whether that commit happened.
        We only recover when exactly one new task-owned Dataset appeared; any
        ambiguous history fails closed instead of binding the request to the
        wrong data.
        """

        if receipt.get("status") != "processing":
            return deepcopy(dict(receipt))
        task = read_json(self._task_path(task_id))
        current_history = list(task.get("dataset_history", []))
        history_before = receipt.get("dataset_history_before")
        if history_before is not None:
            if not isinstance(history_before, list) or any(
                not isinstance(item, str) or not item for item in history_before
            ):
                raise HarnessError("数据导入收据缺少可核对的历史快照")
            if current_history[: len(history_before)] != history_before:
                raise HarnessError("数据导入期间任务历史发生冲突，不能自动恢复")
            history_size_before = len(history_before)
        else:
            # Read compatibility for processing receipts created before the
            # exact history snapshot was introduced.
            history_size_before = int(receipt.get("dataset_history_size_before", -1))
            if history_size_before < 0 or len(current_history) < history_size_before:
                raise HarnessError("数据导入收据的历史边界无效")

        added_dataset_ids = current_history[history_size_before:]
        if not added_dataset_ids:
            # The dataset never reached the authoritative task projection.
            # Retrying the same exact request is safe; an orphan temporary or
            # unreferenced dataset directory is not treated as committed data.
            receipt_path.unlink(missing_ok=True)
            return None
        if (
            len(added_dataset_ids) != 1
            or task.get("dataset_id") != added_dataset_ids[0]
        ):
            raise HarnessError("数据导入期间出现多个任务版本，不能自动恢复")

        dataset_id = added_dataset_ids[0]
        report_path = (
            self._task_dir(task_id)
            / "datasets"
            / dataset_id
            / "dataset_report.json"
        )
        if not report_path.is_file():
            raise HarnessError("数据导入任务已提交，但数据体检报告不可用")
        report = read_json(report_path)
        expected_filename = Path(str(receipt.get("filename") or "")).name
        if (
            report.get("dataset_id") != dataset_id
            or report.get("source_filename") != expected_filename
            or report.get("source_payload_sha256") != receipt.get("payload_sha256")
            or report.get("upload_request_digest_sha256")
            != receipt.get("request_digest_sha256")
        ):
            raise HarnessError("数据导入任务已提交，但上传身份无法核对")
        completed_receipt = self._seal_dataset_upload_receipt(
            {
                **dict(receipt),
                "status": "completed",
                "dataset_id": dataset_id,
                "completed_at_utc": _utc_now(),
                "recovered_after_restart": True,
            }
        )
        write_json(receipt_path, completed_receipt)
        return completed_receipt

    def get_dataset_upload_receipt(
        self,
        task_id: str,
        request_id: str,
    ) -> dict[str, Any]:
        with self._lock:
            # Resolve the task first so a request id can never probe another
            # task directory through a 404 side channel.
            read_json(self._task_path(task_id))
            return self._read_dataset_upload_receipt(task_id, request_id)

    def attach_dataset_idempotent(
        self,
        task_id: str,
        payload: bytes,
        filename: str,
        *,
        request_id: str,
        options: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any], bool]:
        selected_request_id = self._normalize_dataset_upload_request_id(request_id)
        selected_options = dict(options or {})
        payload_sha256, request_digest = self._dataset_upload_request_digest(
            task_id,
            selected_request_id,
            payload,
            filename,
            selected_options,
        )
        with self._lock, self._dataset_upload_process_lock(task_id):
            task_before = read_json(self._task_path(task_id))
            receipt_path = self._dataset_upload_receipt_path(
                task_id,
                selected_request_id,
            )
            if receipt_path.is_file():
                receipt = self._read_dataset_upload_receipt(
                    task_id,
                    selected_request_id,
                )
                if receipt.get("request_digest_sha256") != request_digest:
                    raise HarnessError(
                        "x-request-id已绑定另一份数据或导入选项，不能复用"
                    )
                if receipt.get("status") == "processing":
                    receipt = self._reconcile_processing_dataset_upload_receipt(
                        task_id,
                        receipt_path,
                        receipt,
                    )
                    if receipt is None:
                        task_before = read_json(self._task_path(task_id))
                    else:
                        return self.get_task(task_id), receipt, True
                elif receipt.get("status") != "completed":
                    raise HarnessError("同一数据导入请求尚未形成可核对结果")
                else:
                    return self.get_task(task_id), receipt, True

            now = _utc_now()
            pending_receipt = self._seal_dataset_upload_receipt(
                {
                    "schema_version": "1.0",
                    "object_type": "DatasetUploadReceipt",
                    "task_id": task_id,
                    "request_id": selected_request_id,
                    "request_digest_sha256": request_digest,
                    "payload_sha256": payload_sha256,
                    "filename": filename,
                    "options": deepcopy(selected_options),
                    "status": "processing",
                    "dataset_id": None,
                    "dataset_history_size_before": len(
                        task_before.get("dataset_history", [])
                    ),
                    "dataset_history_before": list(
                        task_before.get("dataset_history", [])
                    ),
                    "recovered_after_restart": False,
                    "created_at_utc": now,
                    "completed_at_utc": None,
                }
            )
            write_json(receipt_path, pending_receipt)
            try:
                task = self.attach_dataset(
                    task_id,
                    payload,
                    filename,
                    options=selected_options,
                    upload_request_digest_sha256=request_digest,
                )
            except Exception:
                # Validation failures have no successful response to replay.
                # Remove only this pending marker; successful receipts remain
                # immutable and replayable.
                receipt_path.unlink(missing_ok=True)
                raise
            dataset_id = str(task.get("dataset_id") or "")
            if not dataset_id:
                receipt_path.unlink(missing_ok=True)
                raise HarnessError("数据导入完成但没有返回dataset_id")
            completed_receipt = self._seal_dataset_upload_receipt(
                {
                    **pending_receipt,
                    "status": "completed",
                    "dataset_id": dataset_id,
                    "completed_at_utc": _utc_now(),
                }
            )
            write_json(receipt_path, completed_receipt)
            return task, completed_receipt, False

    def update_contract(self, task_id: str, changes: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            task = read_json(self._task_path(task_id))
            spec = self._ensure_spec_revision(task)
            if spec.get("capability_decision", {}).get("status") != "resolved":
                raise HarnessError("必须先确认任务规格和模型输出形式")
            if not task.get("dataset_id"):
                raise HarnessError("请先导入数据集")
            if task["status"] == "running":
                raise HarnessError("运行中不能修改合同")
            contract = read_json(self._contract_path(task_id))
            gates = changes.get("release_gates", {})
            if gates:
                if not isinstance(gates, dict):
                    raise ContractError("release_gates必须是对象")
                contract["release_gates"].update(gates)
                plugin = self.runs.registry.get_recipe(str(task["recipe_id"]))
                record_overrides = getattr(
                    plugin, "record_release_gate_overrides", None
                )
                if callable(record_overrides):
                    contract = record_overrides(contract, gates)
            options = changes.get("recipe_options", {})
            if options:
                if not isinstance(options, dict):
                    raise ContractError("recipe_options必须是对象")
                contract["recipe_options"].update(options)
            validate_contract(contract, registry=self.runs.registry)
            self._assert_contract_model_binding_current(task, contract)
            task["contract_confirmed"] = False
            task["confirmations"] = {}
            task["confirmed_contract_sha256"] = None
            if task.get("current_run_id"):
                task["last_run_id"] = task["current_run_id"]
                task["current_run_id"] = None
            task["status"] = "data_ready"
            task["updated_at_utc"] = _utc_now()
            write_json(self._contract_path(task_id), contract)
            self._record_contract_revision(task, contract)
            write_json(self._task_path(task_id), task)
        return self.get_task(task_id)

    def confirm_contract(self, task_id: str, confirmations: dict[str, Any]) -> dict[str, Any]:
        required = ("data_authorized", "labels_reviewed", "gates_reviewed")
        missing = [name for name in required if confirmations.get(name) is not True]
        if missing:
            raise ContractError(f"必须明确确认：{', '.join(missing)}")
        with self._lock:
            task = read_json(self._task_path(task_id))
            spec = self._ensure_spec_revision(task)
            if spec.get("capability_decision", {}).get("status") != "resolved":
                raise HarnessError("必须先确认任务规格和模型输出形式")
            if not task.get("dataset_id"):
                raise HarnessError("请先导入数据集")
            contract = read_json(self._contract_path(task_id))
            validate_contract(contract, registry=self.runs.registry)
            self._assert_contract_model_binding_current(task, contract)
            expected = confirmations.get("expected_contract_revision")
            revision = self._assert_expected_contract_revision(task, expected)
            approval = confirmations.get("approval")
            if approval is None:
                approval = {
                    "actor": confirmations.get("actor"),
                    "checkpoint_id": confirmations.get("checkpoint_id"),
                }
            if not isinstance(approval, Mapping):
                raise ContractError("approval必须包含actor与checkpoint_id")
            actor = str(approval.get("actor") or "").strip()
            checkpoint_id = str(approval.get("checkpoint_id") or "").strip()
            if not actor or not checkpoint_id:
                raise ContractError("确认合同必须记录actor与checkpoint_id")
            decision = ApprovalDecision.create(
                approval_decision_id=f"approval-decision-{uuid4().hex[:12]}",
                revision=revision,
                actor=actor,
                checkpoint_id=checkpoint_id,
                confirmations={name: True for name in required},
            ).to_dict()
            decision_path = self._approval_decision_path(
                task_id, str(decision["approval_decision_id"])
            )
            if decision_path.exists():
                raise ApprovalDecisionIntegrityError("approval decision already exists")
            write_json(decision_path, decision)
            task["contract_confirmed"] = True
            task["confirmed_contract_sha256"] = revision["contract_sha256"]
            task["confirmed_contract_revision_id"] = revision[
                "contract_revision_id"
            ]
            approval_ids = list(task.get("approval_decision_ids") or [])
            approval_ids.append(decision["approval_decision_id"])
            task["approval_decision_ids"] = approval_ids
            task["current_approval_decision_id"] = decision[
                "approval_decision_id"
            ]
            task["confirmations"] = {
                **{name: True for name in required},
                "confirmed_at_utc": decision["created_at_utc"],
                "approval_decision_id": decision["approval_decision_id"],
                "checkpoint_id": checkpoint_id,
            }
            task["status"] = "ready"
            task["updated_at_utc"] = _utc_now()
            write_json(self._task_path(task_id), task)
        return self.get_task(task_id)

    def list_contract_revisions(self, task_id: str) -> list[dict[str, Any]]:
        with self._lock:
            task = read_json(self._task_path(task_id))
            if self._contract_path(task_id).is_file() and task.get("dataset_id"):
                self._ensure_contract_revision(task)
            revisions = [
                self.get_contract_revision(task_id, str(revision_id))
                for revision_id in task.get("contract_revision_ids", [])
            ]
        return revisions

    def get_contract_revision(
        self, task_id: str, contract_revision_id: str
    ) -> dict[str, Any]:
        path = self._contract_revision_path(task_id, contract_revision_id)
        if not path.is_file():
            raise FileNotFoundError(
                f"contract revision not found: {contract_revision_id}"
            )
        revision = ContractRevision.from_record(read_json(path)).to_dict()
        if revision["task_id"] != task_id:
            raise ContractRevisionIntegrityError(
                "contract revision belongs to another task"
            )
        return revision

    def list_approval_decisions(self, task_id: str) -> list[dict[str, Any]]:
        task = read_json(self._task_path(task_id))
        return [
            self.get_approval_decision(task_id, str(decision_id))
            for decision_id in task.get("approval_decision_ids", [])
        ]

    def get_approval_decision(
        self, task_id: str, approval_decision_id: str
    ) -> dict[str, Any]:
        path = self._approval_decision_path(task_id, approval_decision_id)
        if not path.is_file():
            raise FileNotFoundError(
                f"approval decision not found: {approval_decision_id}"
            )
        decision = ApprovalDecision.from_record(read_json(path)).to_dict()
        if decision["task_id"] != task_id:
            raise ApprovalDecisionIntegrityError(
                "approval decision belongs to another task"
            )
        return decision

    def _dataset_identity(self, task: Mapping[str, Any]) -> tuple[str, str]:
        dataset_id = str(task.get("dataset_id") or "").strip()
        if not dataset_id:
            raise HarnessError("训练合同没有绑定数据集")
        report_path = (
            self._task_dir(str(task["task_id"]))
            / "datasets"
            / dataset_id
            / "dataset_report.json"
        )
        if not report_path.is_file():
            raise HarnessError("数据集体检报告不存在，不能创建合同版本")
        report = read_json(report_path)
        fingerprint = str(report.get("fingerprint_sha256") or "").strip()
        if not re.fullmatch(r"[0-9a-f]{64}", fingerprint):
            raise HarnessError("数据集体检报告缺少有效指纹")
        return dataset_id, fingerprint

    def _record_contract_revision(
        self,
        task: dict[str, Any],
        contract: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Append an immutable revision after every authoritative contract write."""

        task_id = str(task["task_id"])
        spec = self._ensure_spec_revision(task)
        dataset_id, fingerprint = self._dataset_identity(task)
        revision = ContractRevision.create(
            contract_revision_id=f"contract-revision-{uuid4().hex[:12]}",
            task_id=task_id,
            spec_revision_id=str(spec["revision_id"]),
            dataset_id=dataset_id,
            dataset_fingerprint_sha256=fingerprint,
            contract_snapshot=contract,
        ).to_dict()
        contract_path = self._contract_path(task_id)
        if not contract_path.is_file() or sha256_file(contract_path) != revision[
            "contract_sha256"
        ]:
            raise ContractRevisionIntegrityError(
                "contract file and revision snapshot differ"
            )
        revision_path = self._contract_revision_path(
            task_id, str(revision["contract_revision_id"])
        )
        if revision_path.exists():
            raise ContractRevisionIntegrityError("contract revision already exists")
        write_json(revision_path, revision)
        revision_ids = list(task.get("contract_revision_ids") or [])
        revision_ids.append(revision["contract_revision_id"])
        task["contract_revision_ids"] = revision_ids
        task["current_contract_revision_id"] = revision["contract_revision_id"]
        task["confirmed_contract_revision_id"] = None
        task["current_approval_decision_id"] = None
        return revision

    def _ensure_contract_revision(self, task: dict[str, Any]) -> dict[str, Any]:
        """Return the current revision, migrating only an unversioned legacy contract."""

        task_id = str(task["task_id"])
        revision_id = str(task.get("current_contract_revision_id") or "")
        known_ids = list(task.get("contract_revision_ids") or [])
        if revision_id:
            if known_ids and revision_id not in known_ids:
                raise ContractRevisionIntegrityError(
                    "current contract revision is absent from task history"
                )
            return self.get_contract_revision(task_id, revision_id)
        if known_ids:
            raise ContractRevisionIntegrityError(
                "contract revision history exists without a current pointer"
            )
        contract_path = self._contract_path(task_id)
        if not contract_path.is_file():
            raise FileNotFoundError(f"contract not found: {task_id}")
        revision = self._record_contract_revision(task, read_json(contract_path))
        write_json(self._task_path(task_id), task)
        return revision

    def _assert_expected_contract_revision(
        self,
        task: dict[str, Any],
        expected: Any,
    ) -> dict[str, Any]:
        if not isinstance(expected, Mapping):
            raise ContractRevisionConflictError(
                "确认请求缺少expected_contract_revision；请刷新后确认当前合同版本"
            )
        revision = self._ensure_contract_revision(task)
        identity_fields = (
            "contract_revision_id",
            "contract_sha256",
            "task_id",
            "spec_revision_id",
            "dataset_id",
            "dataset_fingerprint_sha256",
        )
        mismatches = [
            field
            for field in identity_fields
            if str(expected.get(field) or "") != str(revision[field])
        ]
        spec = self._ensure_spec_revision(task)
        dataset_id, fingerprint = self._dataset_identity(task)
        current_context = {
            "task_id": str(task["task_id"]),
            "spec_revision_id": str(spec["revision_id"]),
            "dataset_id": dataset_id,
            "dataset_fingerprint_sha256": fingerprint,
            "contract_sha256": sha256_file(self._contract_path(str(task["task_id"]))),
        }
        mismatches.extend(
            field
            for field, value in current_context.items()
            if str(revision[field]) != value and field not in mismatches
        )
        if task.get("contract_stale"):
            mismatches.append("contract_stale")
        if mismatches:
            raise ContractRevisionConflictError(
                "合同、任务规格或数据版本已经变化；请刷新后重新审阅。"
                f" mismatch={sorted(set(mismatches))}"
            )
        return revision

    def _current_approval_decision(
        self, task: Mapping[str, Any], revision: Mapping[str, Any]
    ) -> dict[str, Any]:
        approval_id = str(task.get("current_approval_decision_id") or "")
        if not approval_id:
            raise ApprovalDecisionIntegrityError(
                "当前合同没有独立的ApprovalDecision，必须重新确认"
            )
        try:
            decision = self.get_approval_decision(
                str(task["task_id"]), approval_id
            )
        except FileNotFoundError as exc:
            raise ApprovalDecisionIntegrityError(
                "当前合同的ApprovalDecision不存在，必须重新确认"
            ) from exc
        if (
            decision["contract_revision_id"] != revision["contract_revision_id"]
            or decision["contract_sha256"] != revision["contract_sha256"]
            or decision["decision"] != "approved"
        ):
            raise ApprovalDecisionIntegrityError(
                "ApprovalDecision未绑定当前合同版本，必须重新确认"
            )
        return decision

    def task_exists(self, task_id: str) -> bool:
        """Return whether ``task_id`` is owned by this workspace without creating it."""

        return (self._task_dir(task_id) / "task.json").is_file()

    @staticmethod
    def _require_task_mutable(task: dict[str, Any], action: str) -> None:
        if task.get("archived_at_utc"):
            raise HarnessError(f"归档任务为只读，不能{action}")
        if task.get("status") == "running":
            raise HarnessError(f"训练运行中，不能{action}")

    def task_id_for_run(self, run_id: str) -> str | None:
        """Identify a workspace-owned Run, including an orphaned legacy bypass."""

        state = self.runs.status(run_id)
        task_id = str(state.get("task_id") or "")
        return task_id if task_id and self.task_exists(task_id) else None

    def _recover_pending_runs(self) -> None:
        """Reconcile durable run intents left by a crash or ledger write failure."""

        with self._lock:
            for task_path in sorted(self.tasks_dir.glob("*/task.json")):
                self._reconcile_pending_run(read_json(task_path))

    def _reconcile_pending_run(
        self,
        task: dict[str, Any],
    ) -> tuple[dict[str, Any], bool]:
        pending = task.get("pending_run")
        if not isinstance(pending, dict):
            return task, False
        run_id = str(pending.get("run_id") or "")
        if not run_id or Path(run_id).name != run_id:
            raise HarnessError("任务包含无效的pending RunIntent")
        state_path = self.runs.runs_dir / run_id / "run_state.json"
        if not state_path.is_file():
            task["pending_run"] = None
            task["status"] = str(
                pending.get("previous_status") or task.get("status") or "ready"
            )
            task["updated_at_utc"] = _utc_now()
            write_json(self._task_path(str(task["task_id"])), task)
            return task, False

        state = read_json(state_path)
        if state.get("task_id") != task.get("task_id"):
            raise HarnessError("pending RunIntent指向了其他任务的运行")
        if state.get("parent_run_id") != pending.get("parent_run_id"):
            raise HarnessError("pending RunIntent的父运行血缘不一致")
        run_ids = list(task.get("run_ids") or [])
        if run_id not in run_ids:
            run_ids.append(run_id)
        status = str(state.get("status") or "interrupted")
        task["run_ids"] = run_ids
        task["current_run_id"] = run_id
        task["status"] = (
            status
            if status in {"completed", "failed", "cancelled", "interrupted"}
            else "running"
        )
        task["pending_run"] = None
        task["updated_at_utc"] = _utc_now()
        write_json(self._task_path(str(task["task_id"])), task)
        return task, True

    def _begin_run_intent(
        self,
        task: dict[str, Any],
        *,
        operation: str,
        parent_run_id: str | None = None,
        strategy_id: str | None = None,
    ) -> str:
        if task.get("pending_run"):
            raise HarnessError("当前任务已有待对账的RunIntent")
        run_id = new_run_id(str(task["task_id"]))
        task["pending_run"] = {
            "run_id": run_id,
            "operation": operation,
            "parent_run_id": parent_run_id,
            "strategy_id": strategy_id,
            "previous_status": task.get("status"),
            "created_at_utc": _utc_now(),
        }
        task["updated_at_utc"] = _utc_now()
        write_json(self._task_path(str(task["task_id"])), task)
        return run_id

    def _rollback_run_intent_if_uncreated(
        self,
        task_id: str,
        run_id: str,
    ) -> None:
        if (self.runs.runs_dir / run_id / "run_state.json").is_file():
            return
        task = read_json(self._task_path(task_id))
        pending = task.get("pending_run")
        if isinstance(pending, dict) and pending.get("run_id") == run_id:
            task["pending_run"] = None
            task["status"] = str(
                pending.get("previous_status") or task.get("status") or "ready"
            )
            task["updated_at_utc"] = _utc_now()
            write_json(self._task_path(task_id), task)

    def _finalize_run_intent(self, task_id: str, run_id: str) -> None:
        task = read_json(self._task_path(task_id))
        pending = task.get("pending_run")
        if not isinstance(pending, dict) or pending.get("run_id") != run_id:
            raise HarnessError("RunIntent在运行创建后丢失，停止写入任务血缘")
        run_ids = list(task.get("run_ids") or [])
        if run_id not in run_ids:
            run_ids.append(run_id)
        task["current_run_id"] = run_id
        task["run_ids"] = run_ids
        task["pending_run"] = None
        task["status"] = "running"
        task["updated_at_utc"] = _utc_now()
        write_json(self._task_path(task_id), task)

    def _authorize_task_run_creation(
        self,
        task_id: str,
        *,
        parent_run_id: str | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Fail closed before any root or child Run directory can be created."""

        task = read_json(self._task_path(task_id))
        if task.get("archived_at_utc"):
            raise HarnessError("归档任务不能启动新的训练运行")
        spec = self._ensure_spec_revision(task)
        if spec.get("capability_decision", {}).get("status") != "resolved":
            raise HarnessError("当前任务规格尚未澄清并确认")
        current_run_id = str(task.get("current_run_id") or "")
        if current_run_id and current_run_id != str(parent_run_id or ""):
            try:
                if self.runs.status(current_run_id).get("status") in ACTIVE_STATUSES:
                    raise HarnessError("当前任务已有运行正在执行")
            except FileNotFoundError:
                raise HarnessError("当前任务的运行血缘不可恢复") from None
        if not task.get("contract_confirmed"):
            raise HarnessError("必须先确认数据授权、标签和验收门槛")
        contract_path = self._contract_path(task_id)
        revision = self._ensure_contract_revision(task)
        confirmed_digest = task.get("confirmed_contract_sha256")
        confirmed_revision_id = task.get("confirmed_contract_revision_id")
        if (
            not confirmed_digest
            or confirmed_digest != sha256_file(contract_path)
            or confirmed_digest != revision["contract_sha256"]
            or confirmed_revision_id != revision["contract_revision_id"]
        ):
            task["contract_confirmed"] = False
            task["confirmations"] = {}
            task["confirmed_contract_sha256"] = None
            task["confirmed_contract_revision_id"] = None
            task["current_approval_decision_id"] = None
            task["status"] = "data_ready"
            task["updated_at_utc"] = _utc_now()
            write_json(self._task_path(task_id), task)
            raise HarnessError(
                "训练合同在确认之后被修改，必须重新确认数据授权、标签和验收门槛"
            )
        try:
            self._current_approval_decision(task, revision)
        except ApprovalDecisionIntegrityError as exc:
            task["contract_confirmed"] = False
            task["confirmations"] = {}
            task["confirmed_contract_sha256"] = None
            task["confirmed_contract_revision_id"] = None
            task["current_approval_decision_id"] = None
            task["status"] = "data_ready"
            task["updated_at_utc"] = _utc_now()
            write_json(self._task_path(task_id), task)
            raise HarnessError(str(exc)) from exc
        contract = read_json(contract_path)
        if contract.get("task_id") != task_id:
            raise HarnessError("训练合同 task_id 与当前任务不一致")
        validate_contract(contract, registry=self.runs.registry)
        self._assert_contract_model_binding_current(task, contract)
        self.authorize_v09_execution(task_id)
        active_blockers = self.blocker_store.list(task_id, active_only=True)
        if active_blockers:
            raise HarnessError(
                f"当前任务仍有活动阻断：{active_blockers[0].get('code', 'unknown')}"
            )
        if parent_run_id is not None:
            _owned_task, parent_state = self._require_owned_run(
                task_id, parent_run_id
            )
            if parent_state.get("task_id") != task_id:
                raise HarnessError("父运行与当前训练任务不一致")
            parent_contract = read_json(
                self.runs.runs_dir / parent_run_id / "task_contract.json"
            )
            if parent_contract.get("task_id") != task_id:
                raise HarnessError("父运行合同与当前训练任务不一致")
            validate_contract(parent_contract, registry=self.runs.registry)
            self._assert_contract_model_binding_current(task, parent_contract)
            lineage_run_id = parent_run_id
            seen_run_ids: set[str] = set()
            while True:
                if lineage_run_id in seen_run_ids:
                    raise HarnessError("父运行血缘存在循环，禁止创建子运行")
                seen_run_ids.add(lineage_run_id)
                _lineage_task, lineage_state = self._require_owned_run(
                    task_id,
                    lineage_run_id,
                )
                ancestor = str(lineage_state.get("parent_run_id") or "")
                if not ancestor:
                    root_contract_path = (
                        self.runs.runs_dir
                        / lineage_run_id
                        / "task_contract.json"
                    )
                    if sha256_file(root_contract_path) != confirmed_digest:
                        raise HarnessError(
                            "父运行血缘不是由当前已确认训练合同创建，禁止重试或应用策略"
                        )
                    break
                lineage_run_id = ancestor
        return task, contract

    def authorize_v09_execution(self, task_id: str) -> dict[str, Any] | None:
        """Authorize a BYOM execution only from the exact approved fit lineage.

        Legacy registered Recipes do not have a v0.9 TrainingPlan and continue
        through their existing contract gates.  Once a task has entered the
        Universal BYOM planning protocol, however, every execution surface must
        fail closed until the current immutable plan, source analysis,
        EnvironmentLock, ResourceProbe and ResourceFitReport all agree.
        """

        task = read_json(self._task_path(task_id))
        plan = self.training_plan_store.current_revision(task_id)
        binding = self.model_source_store.current_binding(task_id)
        if plan is None and binding is None:
            return None
        if plan is None:
            raise HarnessError("当前BYOM模型来源尚无已批准训练计划，禁止启动训练")
        if binding is None:
            raise HarnessError("当前BYOM模型来源绑定不存在")
        if (
            task.get("current_model_binding_revision_id")
            != binding.get("binding_revision_id")
            or task.get("model_binding_stale_for_spec_revision") is True
            or int(binding.get("base_spec_revision", 0))
            != int(task["current_spec_revision"])
        ):
            raise HarnessError("当前BYOM模型来源绑定已失效")
        context = self.model_source_store.binding_context(
            task_id, str(binding["binding_revision_id"])
        )
        if context is None:
            raise HarnessError("当前BYOM来源血缘不可恢复")
        analysis_record = context["analysis"]
        analysis = analysis_record.get("analysis") or {}
        if str(analysis.get("status") or "") != "complete":
            raise HarnessError("当前BYOM仓库分析未完成或存在未解决高风险")
        if (
            plan.get("analysis_id") != analysis_record.get("analysis_id")
            or plan.get("analysis_digest") != analysis_record.get("content_digest")
        ):
            raise HarnessError("当前BYOM训练计划与当前仓库分析血缘不一致")
        plan_view = self.current_training_plan(task_id)
        if plan_view is None or plan_view.get("stale") is True:
            raise HarnessError("当前BYOM训练计划已失效，禁止启动训练")
        authorized_plan = self.training_plan_store.authorize_use(
            task_id,
            str(plan["training_plan_revision_id"]),
            expected_plan_sha256=str(plan["plan_sha256"]),
            current_spec_revision=int(task["current_spec_revision"]),
            source_snapshot_id=str(context["snapshot"]["snapshot_id"]),
            snapshot_digest=str(context["snapshot"]["content_digest"]),
            analysis_id=str(context["analysis"]["analysis_id"]),
            analysis_digest=str(context["analysis"]["content_digest"]),
        )
        bundle = self.feasibility_store.current_bundle(task_id)
        probe = bundle.get("resource_probe")
        lock = bundle.get("environment_lock")
        report = bundle.get("resource_fit_report")
        if not all(isinstance(item, dict) for item in (probe, lock, report)):
            raise HarnessError("当前BYOM计划尚无完整资源资格证据，禁止启动训练")
        assert isinstance(probe, dict)
        assert isinstance(lock, dict)
        assert isinstance(report, dict)
        lineage_changed = (
            report.get("training_plan_revision_id")
            != authorized_plan["training_plan_revision_id"]
            or report.get("training_plan_sha256") != authorized_plan["plan_sha256"]
            or report.get("resource_probe_id") != probe.get("resource_probe_id")
            or report.get("resource_probe_sha256") != probe.get("probe_sha256")
            or report.get("environment_lock_id")
            != lock.get("environment_lock_id")
            or report.get("environment_lock_sha256") != lock.get("lock_sha256")
        )
        if lineage_changed:
            raise HarnessError("BYOM资源资格证据与当前计划血缘不一致")
        if report.get("decision") != "fit":
            raise HarnessError(
                "当前BYOM资源结论不是fit；请先处理阻断或采纳降级方案并重新批准"
            )
        active_blockers = [
            item
            for item in self.blocker_store.list(task_id, active_only=True)
            if item.get("stage")
            in {
                "source_resolution",
                "source_snapshot",
                "repository_analysis",
                "training_plan",
                "resource_probe",
                "environment_lock",
                "resource_fit",
            }
        ]
        if active_blockers:
            raise HarnessError(
                f"BYOM仍有活动阻断：{active_blockers[0].get('code', 'unknown')}"
            )
        raise HarnessError(
            "V3只完成静态预算与本机资源匹配；尚未完成L3镜像拉取、依赖构建和隔离环境资格验证，禁止执行第三方训练代码"
        )

    def _task_run_start_scope(
        self,
        task_id: str,
        *,
        expected_contract_sha256: str | None = None,
        expected_dataset_id: str | None = None,
        expected_dataset_fingerprint_sha256: str | None = None,
        expected_spec_revision: int | None = None,
    ) -> dict[str, Any]:
        task, _contract = self._authorize_task_run_creation(task_id)
        task_status = str(task.get("status") or "")
        recoverable_statuses = {"failed", "cancelled", "interrupted"}
        if task_status != "ready" and task_status not in recoverable_statuses:
            raise DeliveryAuthorizationError(
                "run-start authorization requires a ready or recoverable task"
            )
        current_run_id = str(task.get("current_run_id") or "")
        if task.get("pending_run"):
            raise DeliveryAuthorizationError(
                "run-start authorization requires no pending run"
            )
        current_run_status: str | None = None
        if current_run_id:
            current_run_status = str(self.runs.status(current_run_id).get("status") or "")
            if current_run_status not in recoverable_statuses:
                raise DeliveryAuthorizationError(
                    "run-start authorization cannot replace a non-recoverable run"
                )
        elif task_status in recoverable_statuses:
            raise DeliveryAuthorizationError(
                "recoverable run-start authorization requires prior run lineage"
            )
        revision = self._ensure_contract_revision(task)
        contract_sha256 = str(task.get("confirmed_contract_sha256") or "")
        # The authoritative dataset report lives beside the imported dataset;
        # ``dataset_report`` is only attached to the public task view and is
        # not persisted in the raw task record read above.  Reuse the same
        # on-disk identity check as contract revisioning so an otherwise valid
        # native approval cannot fail with an empty fingerprint.
        dataset_id, dataset_fingerprint_sha256 = self._dataset_identity(task)
        spec_revision = int(task.get("current_spec_revision") or 0)
        checks = (
            (expected_contract_sha256, contract_sha256, "contract digest"),
            (expected_dataset_id, dataset_id, "dataset id"),
            (
                expected_dataset_fingerprint_sha256,
                dataset_fingerprint_sha256,
                "dataset fingerprint",
            ),
            (expected_spec_revision, spec_revision, "task spec revision"),
        )
        for expected, actual, label in checks:
            if expected is not None and expected != actual:
                raise DeliveryAuthorizationError(
                    f"run-start authorization {label} changed"
                )
        return {
            "action": "start_task_run",
            "task_id": task_id,
            "contract_revision_id": revision["contract_revision_id"],
            "contract_sha256": contract_sha256,
            "dataset_id": dataset_id,
            "dataset_fingerprint_sha256": dataset_fingerprint_sha256,
            "spec_revision": spec_revision,
            "spec_revision_id": revision["spec_revision_id"],
            "contract_approval_decision_id": task.get(
                "current_approval_decision_id"
            ),
            "prior_task_status": task_status,
            "prior_run_id": current_run_id or None,
            "prior_run_status": current_run_status,
        }

    def authorize_task_run_start(
        self,
        task_id: str,
        *,
        contract_sha256: str,
        dataset_id: str,
        dataset_fingerprint_sha256: str,
        spec_revision: int,
        approval: Mapping[str, Any],
    ) -> dict[str, Any]:
        with self._lock:
            scope = self._task_run_start_scope(
                task_id,
                expected_contract_sha256=contract_sha256,
                expected_dataset_id=dataset_id,
                expected_dataset_fingerprint_sha256=(
                    dataset_fingerprint_sha256
                ),
                expected_spec_revision=spec_revision,
            )
            record, token = self.delivery_authorization_store.issue(
                task_id=task_id,
                action="start_task_run",
                scope=scope,
                approval=approval,
            )
            self._record_delivery_authorization(
                task_id,
                str(record["authorization_id"]),
            )
            return {
                "task": self.get_task(task_id),
                "run_authorization": self.delivery_authorization_store.public(
                    record
                ),
                "authorization_token": token,
            }

    def start_run_with_authorization(
        self,
        task_id: str,
        *,
        run_authorization_id: str,
        authorization_token: str,
        run_request_sha256: str,
    ) -> dict[str, Any]:
        with self._lock:
            authorization = self.delivery_authorization_store.get(
                task_id,
                run_authorization_id,
            )
            approved_scope = authorization.get("scope") or {}
            if (
                authorization.get("action") != "start_task_run"
                or approved_scope.get("task_id") != task_id
            ):
                raise DeliveryAuthorizationError(
                    "run-start authorization belongs to another action or task"
                )
            current_scope = self._task_run_start_scope(task_id)
            self.delivery_authorization_store.reserve(
                task_id=task_id,
                authorization_id=run_authorization_id,
                authorization_token=authorization_token,
                action="start_task_run",
                approved_scope_sha256=run_request_sha256,
                current_scope=current_scope,
            )
            try:
                task = self.start_run(task_id)
            except Exception as exc:
                self.delivery_authorization_store.complete(
                    task_id=task_id,
                    authorization_id=run_authorization_id,
                    succeeded=False,
                    outcome={
                        "status": "run_start_failed",
                        "error_type": type(exc).__name__,
                    },
                )
                raise
            run_id = str(task.get("current_run_id") or "")
            if not run_id:
                self.delivery_authorization_store.complete(
                    task_id=task_id,
                    authorization_id=run_authorization_id,
                    succeeded=False,
                    outcome={"status": "run_identity_missing"},
                )
                raise DeliveryAuthorizationError(
                    "authorized run start produced no canonical run id"
                )
            completed = self.delivery_authorization_store.complete(
                task_id=task_id,
                authorization_id=run_authorization_id,
                succeeded=True,
                outcome={
                    "status": "run_started",
                    "run_id": run_id,
                },
            )
            return {
                "task": task,
                "run": self.runs.status(run_id),
                "run_authorization": self.delivery_authorization_store.public(
                    completed
                ),
            }

    def start_run(self, task_id: str) -> dict[str, Any]:
        with self._lock:
            _task, recovered = self._reconcile_pending_run(
                read_json(self._task_path(task_id))
            )
            if recovered:
                return self.get_task(task_id)
            task, contract = self._authorize_task_run_creation(task_id)
            run_id = self._begin_run_intent(task, operation="start")
            try:
                self.runs.submit(
                    contract,
                    run_id=run_id,
                    workspace_task_id=task_id,
                )
            except Exception:
                self._rollback_run_intent_if_uncreated(task_id, run_id)
                raise
            self._finalize_run_intent(task_id, run_id)
        return self.get_task(task_id)

    def apply_strategy(self, task_id: str, run_id: str, strategy_id: str) -> dict[str, Any]:
        with self._lock:
            _task, recovered = self._reconcile_pending_run(
                read_json(self._task_path(task_id))
            )
            if recovered:
                return self.get_task(task_id)
            task, _contract = self._authorize_task_run_creation(
                task_id,
                parent_run_id=run_id,
            )
            child_run_id = self._begin_run_intent(
                task,
                operation="apply_strategy",
                parent_run_id=run_id,
                strategy_id=strategy_id,
            )
            try:
                self.runs.apply_strategy(
                    run_id,
                    strategy_id,
                    child_run_id=child_run_id,
                    workspace_task_id=task_id,
                )
            except Exception:
                self._rollback_run_intent_if_uncreated(task_id, child_run_id)
                raise
            self._finalize_run_intent(task_id, child_run_id)
        return self.get_task(task_id)

    def resume_run(self, task_id: str, run_id: str) -> dict[str, Any]:
        with self._lock:
            _task, recovered = self._reconcile_pending_run(
                read_json(self._task_path(task_id))
            )
            if recovered:
                return self.get_task(task_id)
            task, _contract = self._authorize_task_run_creation(
                task_id,
                parent_run_id=run_id,
            )
            child_run_id = self._begin_run_intent(
                task,
                operation="resume",
                parent_run_id=run_id,
            )
            try:
                self.runs.resume(
                    run_id,
                    child_run_id=child_run_id,
                    workspace_task_id=task_id,
                )
            except Exception:
                self._rollback_run_intent_if_uncreated(task_id, child_run_id)
                raise
            self._finalize_run_intent(task_id, child_run_id)
        return self.get_task(task_id)

    def cancel_run(
        self,
        task_id: str,
        run_id: str,
        *,
        actor: str = "user",
        reason: str = "requested by user",
        cancellation_kind: str = "user_requested",
        scope: str = "training_run",
    ) -> dict[str, Any]:
        """Request cancellation only after proving the Run belongs to the Task."""

        with self._lock:
            task = read_json(self._task_path(task_id))
            if run_id not in task.get("run_ids", []):
                raise HarnessError("该运行不属于当前训练任务")
            run_state = self.runs.status(run_id)
            if run_state.get("task_id") != task_id:
                raise HarnessError("运行所有者与当前训练任务不一致")
            accepted = self.runs.cancel(
                run_id,
                workspace_task_id=task_id,
                actor=actor,
                reason=reason,
                cancellation_kind=cancellation_kind,
                scope=scope,
            )
            if accepted:
                task["updated_at_utc"] = _utc_now()
                write_json(self._task_path(task_id), task)
            run_state = self.runs.status(run_id)
        return {
            "task": self.get_task(task_id),
            "run_id": run_id,
            "cancel_requested": accepted,
            "run": run_state,
        }

    def task_background_actions(self, task_id: str) -> list[dict[str, Any]]:
        """Return task-owned work whose worker may outlive an Agent response."""

        task = read_json(self._task_path(task_id))
        actions: list[dict[str, Any]] = []
        for run_id in task.get("run_ids", []):
            if not isinstance(run_id, str) or not run_id:
                continue
            try:
                actions.append(
                    self.runs.background_action(
                        run_id,
                        workspace_task_id=task_id,
                    )
                )
            except FileNotFoundError:
                continue
        for attempt in self.list_model_binding_attempts(task_id):
            current = attempt.get("current_state", {})
            if not isinstance(current, Mapping):
                continue
            attempt_record = attempt.get("attempt", {})
            attempt_id = (
                attempt_record.get("attempt_id")
                if isinstance(attempt_record, Mapping)
                else None
            )
            if not isinstance(attempt_id, str) or not attempt_id:
                continue
            with self._lock:
                future = self._binding_futures.get(attempt_id)
            worker_running = bool(future is not None and not future.done())
            domain_status = str(current.get("status") or "unknown")
            running = worker_running or domain_status in {"queued", "running"}
            cancellation = current.get("cancellation")
            cancellation_projection = None
            if isinstance(cancellation, Mapping):
                cancellation_projection = {
                    "actor": "unknown",
                    "kind": "unattributed",
                    "reason": cancellation.get("reason"),
                    "scope": "model_binding_analysis",
                }
            actions.append(
                {
                    "action_id": f"model-binding:{attempt_id}",
                    "action_type": "model_binding_analysis",
                    "task_id": task_id,
                    "attempt_id": attempt_id,
                    "status": (
                        "cancel_requested"
                        if domain_status == "cancelled" and worker_running
                        else domain_status
                    ),
                    "domain_status": domain_status,
                    "running": running,
                    "worker_running": worker_running,
                    "cancel_requested": domain_status == "cancelled",
                    "cancel_reason": current.get("reason")
                    or current.get("error"),
                    "cancel": cancellation_projection,
                    "event_seq": current.get("state_revision"),
                    "updated_at_utc": current.get("created_at_utc"),
                    "last_event": {
                        "event_id": current.get("event_id"),
                        "seq": current.get("state_revision"),
                        "type": f"model_binding.{domain_status}",
                        "timestamp_utc": current.get("created_at_utc"),
                    },
                }
            )
        return sorted(
            actions,
            key=lambda item: (
                str(item.get("updated_at_utc") or ""),
                str(item.get("action_id") or ""),
            ),
        )

    def cancel_task_background_actions(
        self,
        task_id: str,
        cancellation: Mapping[str, Any] | str = "Agent stop requested by user",
    ) -> list[dict[str, Any]]:
        """Cascade Agent cancellation to every active task-owned worker."""

        if isinstance(cancellation, Mapping):
            actor = str(cancellation.get("actor") or "user")
            reason = str(cancellation.get("reason") or "Stop requested")
            cancellation_kind = str(
                cancellation.get("kind") or "user_requested"
            )
            scope = str(cancellation.get("scope") or "task_execution")
        else:
            actor = "user"
            reason = str(cancellation)
            cancellation_kind = "user_requested"
            scope = "task_execution"

        for action in self.task_background_actions(task_id):
            if action.get("running") is not True:
                continue
            if action.get("action_type") == "training_run":
                run_id = action.get("run_id")
                if isinstance(run_id, str) and run_id:
                    self.cancel_run(
                        task_id,
                        run_id,
                        actor=actor,
                        reason=reason,
                        cancellation_kind=cancellation_kind,
                        scope=scope,
                    )
            elif action.get("action_type") == "model_binding_analysis":
                attempt_id = action.get("attempt_id")
                if isinstance(attempt_id, str) and attempt_id:
                    self.cancel_model_binding_attempt(
                        task_id,
                        attempt_id,
                        reason=reason,
                    )
        return self.task_background_actions(task_id)

    def evaluation_report(self, task_id: str, run_id: str) -> dict[str, Any]:
        self._require_owned_run(task_id, run_id)
        return {
            "task": self.get_task(task_id),
            "run_id": run_id,
            "evaluation_report": self.runs.evaluation_report(run_id),
        }

    def run_sample_inference(
        self,
        task_id: str,
        run_id: str,
        sample: str | Path | dict[str, Any],
        *,
        sample_type: str | None = None,
        expected: Any | None = None,
    ) -> dict[str, Any]:
        self._require_owned_run(task_id, run_id)
        report = self.runs.sample_inference(
            run_id,
            sample,
            sample_type=sample_type,
            expected=expected,
        )
        return {
            "task": self.get_task(task_id),
            "run_id": run_id,
            "sample_inference": report,
        }

    def list_sample_inferences(
        self,
        task_id: str,
        run_id: str,
    ) -> dict[str, Any]:
        self._require_owned_run(task_id, run_id)
        return {
            "task": self.get_task(task_id),
            "run_id": run_id,
            "sample_inferences": self.runs.sample_inference_checks(run_id),
        }

    def get_sample_inference(
        self,
        task_id: str,
        run_id: str,
        check_id: str,
    ) -> dict[str, Any]:
        self._require_owned_run(task_id, run_id)
        return {
            "task": self.get_task(task_id),
            "run_id": run_id,
            "sample_inference": self.runs.sample_inference_check(
                run_id,
                check_id,
            ),
        }

    def stage_inference_input(
        self,
        task_id: str,
        run_id: str,
        payload: bytes,
        *,
        filename: str,
        sample_type: str,
    ) -> dict[str, Any]:
        with self._lock:
            _, run_state = self._require_owned_run(task_id, run_id)
            if run_state.get("status") != "completed":
                raise InferenceInputError(
                    "inference input requires a completed task-owned run"
                )
            record = self.inference_input_store.stage(
                task_id=task_id,
                run_id=run_id,
                payload=payload,
                filename=filename,
                sample_type=sample_type,
            )
        return {
            "task": self.get_task(task_id),
            "run_id": run_id,
            "inference_input": record,
            "object_refs": [self.inference_input_store.object_ref(record)],
        }

    def list_inference_inputs(
        self,
        task_id: str,
        run_id: str,
    ) -> dict[str, Any]:
        self._require_owned_run(task_id, run_id)
        return {
            "task": self.get_task(task_id),
            "run_id": run_id,
            "inference_inputs": self.inference_input_store.list(
                task_id, run_id=run_id
            ),
        }

    def get_inference_input(
        self,
        task_id: str,
        run_id: str,
        inference_input_id: str,
    ) -> dict[str, Any]:
        self._require_owned_run(task_id, run_id)
        record = self.inference_input_store.get(task_id, inference_input_id)
        if record.get("run_id") != run_id:
            raise InferenceInputError("inference input belongs to another run")
        return {
            "task": self.get_task(task_id),
            "run_id": run_id,
            "inference_input": record,
            "object_refs": [self.inference_input_store.object_ref(record)],
        }

    def _sample_inference_scope(
        self,
        task_id: str,
        run_id: str,
        inference_input_id: str,
        *,
        expected_inference_input_sha256: str | None = None,
    ) -> dict[str, Any]:
        _, run_state = self._require_owned_run(task_id, run_id)
        if run_state.get("status") != "completed":
            raise DeliveryAuthorizationError(
                "sample inference authorization requires a completed run"
            )
        record, _ = self.inference_input_store.resolve_staged(
            task_id=task_id,
            run_id=run_id,
            inference_input_id=inference_input_id,
            expected_sha256=expected_inference_input_sha256,
        )
        return {
            "action": "run_sample_inference",
            "task_id": task_id,
            "run_id": run_id,
            "inference_input_id": record["inference_input_id"],
            "inference_input_sha256": record["sha256"],
            "inference_input_record_sha256": record["record_sha256"],
            "sample_type": record["sample_type"],
            "size_bytes": record["size_bytes"],
        }

    def authorize_sample_inference(
        self,
        task_id: str,
        run_id: str,
        *,
        inference_input_id: str,
        inference_input_sha256: str,
        approval: Mapping[str, Any],
    ) -> dict[str, Any]:
        with self._lock:
            scope = self._sample_inference_scope(
                task_id,
                run_id,
                inference_input_id,
                expected_inference_input_sha256=inference_input_sha256,
            )
            record, token = self.delivery_authorization_store.issue(
                task_id=task_id,
                action="run_sample_inference",
                scope=scope,
                approval=approval,
            )
            self._record_delivery_authorization(
                task_id, str(record["authorization_id"])
            )
            input_record = self.inference_input_store.get(
                task_id, inference_input_id
            )
            return {
                "task": self.get_task(task_id),
                "run_id": run_id,
                "inference_input": input_record,
                "object_refs": [
                    self.inference_input_store.object_ref(input_record)
                ],
                "sample_inference_authorization": (
                    self.delivery_authorization_store.public(record)
                ),
                "authorization_token": token,
            }

    def run_sample_inference_with_authorization(
        self,
        task_id: str,
        run_id: str,
        *,
        inference_input_id: str,
        sample_inference_authorization_id: str,
        authorization_token: str,
        sample_inference_request_sha256: str,
    ) -> dict[str, Any]:
        with self._lock:
            authorization = self.delivery_authorization_store.get(
                task_id, sample_inference_authorization_id
            )
            approved_scope = authorization.get("scope") or {}
            if (
                authorization.get("action") != "run_sample_inference"
                or approved_scope.get("task_id") != task_id
                or approved_scope.get("run_id") != run_id
                or approved_scope.get("inference_input_id")
                != inference_input_id
            ):
                raise DeliveryAuthorizationError(
                    "sample inference does not match its approved task/run/input scope"
                )
            current_scope = self._sample_inference_scope(
                task_id,
                run_id,
                inference_input_id,
                expected_inference_input_sha256=str(
                    approved_scope.get("inference_input_sha256") or ""
                ),
            )
            self.delivery_authorization_store.reserve(
                task_id=task_id,
                authorization_id=sample_inference_authorization_id,
                authorization_token=authorization_token,
                action="run_sample_inference",
                approved_scope_sha256=sample_inference_request_sha256,
                current_scope=current_scope,
            )
            try:
                input_record, sample_path = self.inference_input_store.reserve(
                    task_id=task_id,
                    run_id=run_id,
                    inference_input_id=inference_input_id,
                    expected_sha256=str(
                        approved_scope["inference_input_sha256"]
                    ),
                )
            except Exception as exc:
                self.delivery_authorization_store.complete(
                    task_id=task_id,
                    authorization_id=sample_inference_authorization_id,
                    succeeded=False,
                    outcome={
                        "status": "input_reservation_failed",
                        "error_type": type(exc).__name__,
                    },
                )
                raise
            try:
                report = self.runs.sample_inference(
                    run_id,
                    sample_path,
                    sample_type=str(input_record["sample_type"]),
                )
            except SampleInferenceBlocked as exc:
                input_record = self.inference_input_store.complete(
                    task_id=task_id,
                    run_id=run_id,
                    inference_input_id=inference_input_id,
                    outcome={
                        "status": "blocked",
                        "sample_inference_check_id": exc.check_id,
                    },
                )
                self.delivery_authorization_store.complete(
                    task_id=task_id,
                    authorization_id=sample_inference_authorization_id,
                    succeeded=True,
                    outcome={
                        "status": "inference_blocked",
                        "inference_input_id": inference_input_id,
                        "sample_inference_check_id": exc.check_id,
                    },
                )
                raise
            except Exception as exc:
                self.inference_input_store.complete(
                    task_id=task_id,
                    run_id=run_id,
                    inference_input_id=inference_input_id,
                    outcome={
                        "status": "failed",
                        "error_type": type(exc).__name__,
                    },
                )
                self.delivery_authorization_store.complete(
                    task_id=task_id,
                    authorization_id=sample_inference_authorization_id,
                    succeeded=False,
                    outcome={
                        "status": "inference_failed",
                        "inference_input_id": inference_input_id,
                        "error_type": type(exc).__name__,
                    },
                )
                raise
            input_record = self.inference_input_store.complete(
                task_id=task_id,
                run_id=run_id,
                inference_input_id=inference_input_id,
                outcome={
                    "status": "passed",
                    "sample_inference_check_id": report.get("check_id"),
                },
            )
            completed = self.delivery_authorization_store.complete(
                task_id=task_id,
                authorization_id=sample_inference_authorization_id,
                succeeded=True,
                outcome={
                    "status": "inference_completed",
                    "inference_input_id": inference_input_id,
                    "sample_inference_check_id": report.get("check_id"),
                },
            )
            return {
                "task": self.get_task(task_id),
                "run_id": run_id,
                "inference_input": input_record,
                "object_refs": [
                    self.inference_input_store.object_ref(input_record)
                ],
                "sample_inference": report,
                "sample_inference_authorization": (
                    self.delivery_authorization_store.public(completed)
                ),
            }

    def _record_delivery_authorization(
        self,
        task_id: str,
        authorization_id: str,
    ) -> None:
        task = read_json(self._task_path(task_id))
        authorization_ids = list(task.get("delivery_authorization_ids") or [])
        if authorization_id not in authorization_ids:
            authorization_ids.append(authorization_id)
        task["delivery_authorization_ids"] = authorization_ids
        task["updated_at_utc"] = _utc_now()
        write_json(self._task_path(task_id), task)

    def get_delivery_authorization(
        self,
        task_id: str,
        authorization_id: str,
    ) -> dict[str, Any]:
        task = read_json(self._task_path(task_id))
        if authorization_id not in task.get("delivery_authorization_ids", []):
            raise DeliveryAuthorizationError(
                "delivery authorization does not belong to this task"
            )
        record = self.delivery_authorization_store.get(task_id, authorization_id)
        return {
            "task_id": task_id,
            "delivery_authorization": self.delivery_authorization_store.public(
                record
            ),
        }

    def _artifact_bundle_build_scope(
        self,
        task_id: str,
        run_id: str,
        *,
        sample_inference_check_id: str | None = None,
        inference_check_id: str | None = None,
        expected_evaluation_report_id: str | None = None,
        expected_evaluation_report_sha256: str | None = None,
    ) -> tuple[dict[str, Any], str | None]:
        _, run_state = self._require_owned_run(task_id, run_id)
        if run_state.get("status") != "completed":
            raise DeliveryAuthorizationError(
                "artifact bundle authorization requires a completed run"
            )
        if sample_inference_check_id and inference_check_id:
            raise ContractError(
                "sample_inference_check_id and inference_check_id are mutually exclusive"
            )
        evaluation = self.runs.evaluation_report(run_id)
        if evaluation.get("task_id") != task_id or evaluation.get("run_id") != run_id:
            raise DeliveryAuthorizationError(
                "EvaluationReport belongs to another task or run"
            )
        if evaluation.get("run_status") != "completed":
            raise DeliveryAuthorizationError(
                "artifact bundle authorization requires a completed EvaluationReport"
            )
        if evaluation.get("integrity_status") != "passed":
            raise DeliveryAuthorizationError(
                "artifact bundle authorization requires passed run integrity"
            )
        calculated_report_sha256 = delivery_scope_sha256(
            {
                key: value
                for key, value in evaluation.items()
                if key not in {"report_sha256", "updated_at"}
            }
        )
        if evaluation.get("report_sha256") != calculated_report_sha256:
            raise DeliveryAuthorizationError(
                "EvaluationReport digest does not match its canonical contents"
            )
        if (
            expected_evaluation_report_id is not None
            and evaluation.get("report_id") != expected_evaluation_report_id
        ):
            raise DeliveryAuthorizationError(
                "EvaluationReport id changed before authorization"
            )
        if (
            expected_evaluation_report_sha256 is not None
            and evaluation.get("report_sha256")
            != expected_evaluation_report_sha256
        ):
            raise DeliveryAuthorizationError(
                "EvaluationReport digest changed before authorization"
            )
        selected_inference_id = inference_check_id
        sample_evidence_sha256 = None
        inference_evidence_sha256 = None
        if sample_inference_check_id:
            sample_report = self.runs.sample_inference_check(
                run_id,
                sample_inference_check_id,
            )
            if sample_report.get("status") != "passed":
                raise HarnessError(
                    "only a passed sample inference can enter an artifact bundle"
                )
            selected_inference_id = sample_report.get("inference_check_id")
            if not selected_inference_id:
                raise HarnessError(
                    "sample inference has no trusted inference check"
                )
            if (
                sample_report.get("task_id") != task_id
                or sample_report.get("run_id") != run_id
                or sample_report.get("check_id") != sample_inference_check_id
            ):
                raise DeliveryAuthorizationError(
                    "sample inference evidence belongs to another scope"
                )
            sample_evidence_sha256 = delivery_scope_sha256(
                {
                    "task_id": task_id,
                    "run_id": run_id,
                    "check_id": sample_inference_check_id,
                    "inference_check_id": selected_inference_id,
                    "sample_sha256": (sample_report.get("sample") or {}).get(
                        "sha256"
                    ),
                    "model_sha256": (sample_report.get("model") or {}).get(
                        "sha256"
                    ),
                    "prediction_sha256": sample_report.get("prediction_sha256"),
                }
            )
        if selected_inference_id:
            inference_report = next(
                (
                    item
                    for item in self.runs.inference_checks(run_id)
                    if item.get("check_id") == selected_inference_id
                ),
                None,
            )
            if inference_report is None:
                raise FileNotFoundError("inference check not found")
            if (
                inference_report.get("status") != "passed"
                or inference_report.get("task_id") != task_id
                or inference_report.get("run_id") != run_id
                or inference_report.get("check_id") != selected_inference_id
            ):
                raise DeliveryAuthorizationError(
                    "inference evidence is not a passed check for this task and run"
                )
            inference_evidence_sha256 = delivery_scope_sha256(inference_report)
        scope = {
            "action": "build_artifact_bundle",
            "task_id": task_id,
            "run_id": run_id,
            "evaluation_report_id": evaluation.get("report_id"),
            "evaluation_report_sha256": evaluation.get("report_sha256"),
            "sample_inference_check_id": sample_inference_check_id,
            "inference_check_id": inference_check_id,
            "sample_inference_evidence_sha256": sample_evidence_sha256,
            "inference_evidence_sha256": inference_evidence_sha256,
        }
        return scope, str(selected_inference_id) if selected_inference_id else None

    def authorize_artifact_bundle_build(
        self,
        task_id: str,
        run_id: str,
        *,
        evaluation_report_id: str,
        evaluation_report_sha256: str,
        approval: Mapping[str, Any],
        sample_inference_check_id: str | None = None,
        inference_check_id: str | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            scope, _ = self._artifact_bundle_build_scope(
                task_id,
                run_id,
                sample_inference_check_id=sample_inference_check_id,
                inference_check_id=inference_check_id,
                expected_evaluation_report_id=evaluation_report_id,
                expected_evaluation_report_sha256=evaluation_report_sha256,
            )
            record, token = self.delivery_authorization_store.issue(
                task_id=task_id,
                action="build_artifact_bundle",
                scope=scope,
                approval=approval,
            )
            self._record_delivery_authorization(
                task_id, str(record["authorization_id"])
            )
            return {
                "task": self.get_task(task_id),
                "run_id": run_id,
                "artifact_bundle_authorization": (
                    self.delivery_authorization_store.public(record)
                ),
                "authorization_token": token,
            }

    def build_artifact_bundle(
        self,
        task_id: str,
        run_id: str,
        *,
        artifact_bundle_authorization_id: str,
        authorization_token: str,
        bundle_request_sha256: str,
        sample_inference_check_id: str | None = None,
        inference_check_id: str | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            authorization = self.delivery_authorization_store.get(
                task_id, artifact_bundle_authorization_id
            )
            approved_scope = authorization.get("scope") or {}
            if (
                authorization.get("action") != "build_artifact_bundle"
                or approved_scope.get("task_id") != task_id
                or approved_scope.get("run_id") != run_id
                or approved_scope.get("sample_inference_check_id")
                != sample_inference_check_id
                or approved_scope.get("inference_check_id") != inference_check_id
            ):
                raise DeliveryAuthorizationError(
                    "artifact bundle build does not match its approved task/run scope"
                )
            current_scope, selected_inference_id = self._artifact_bundle_build_scope(
                task_id,
                run_id,
                sample_inference_check_id=sample_inference_check_id,
                inference_check_id=inference_check_id,
            )
            reserved = self.delivery_authorization_store.reserve(
                task_id=task_id,
                authorization_id=artifact_bundle_authorization_id,
                authorization_token=authorization_token,
                action="build_artifact_bundle",
                approved_scope_sha256=bundle_request_sha256,
                current_scope=current_scope,
            )
            approval_decision = reserved["approval_decision"]
            authorization_lineage = {
                "authorization_id": reserved["authorization_id"],
                "action": reserved["action"],
                "scope_sha256": reserved["scope_sha256"],
                "approval_decision_id": approval_decision["decision_id"],
                "approval_decision_sha256": approval_decision["decision_sha256"],
                "approval_actor": approval_decision["actor"],
                "approval_checkpoint_id": approval_decision["checkpoint_id"],
                "evaluation_report_id": reserved["scope"][
                    "evaluation_report_id"
                ],
                "evaluation_report_sha256": reserved["scope"][
                    "evaluation_report_sha256"
                ],
                "sample_inference_check_id": reserved["scope"].get(
                    "sample_inference_check_id"
                ),
                "sample_inference_evidence_sha256": reserved["scope"].get(
                    "sample_inference_evidence_sha256"
                ),
                "inference_check_id": reserved["scope"].get(
                    "inference_check_id"
                ),
                "inference_evidence_sha256": reserved["scope"].get(
                    "inference_evidence_sha256"
                ),
            }
            try:
                bundle = self.runs.build_artifact_bundle(
                    run_id,
                    inference_check_id=selected_inference_id,
                    authorization_lineage=authorization_lineage,
                )
            except Exception as exc:
                self.delivery_authorization_store.complete(
                    task_id=task_id,
                    authorization_id=artifact_bundle_authorization_id,
                    succeeded=False,
                    outcome={
                        "status": "build_failed",
                        "error_type": type(exc).__name__,
                    },
                )
                raise
            completed = self.delivery_authorization_store.complete(
                task_id=task_id,
                authorization_id=artifact_bundle_authorization_id,
                succeeded=True,
                outcome={
                    "status": "bundle_built",
                    "bundle_id": bundle.get("bundle_id"),
                    "manifest_sha256": bundle.get("manifest_sha256"),
                    "archive_sha256": (bundle.get("archive") or {}).get("sha256"),
                },
            )
        return {
            "task": self.get_task(task_id),
            "run_id": run_id,
            "artifact_bundle": bundle,
            "artifact_bundle_authorization": (
                self.delivery_authorization_store.public(completed)
            ),
        }

    def list_artifact_bundles(
        self,
        task_id: str,
        run_id: str,
    ) -> dict[str, Any]:
        self._require_owned_run(task_id, run_id)
        return {
            "task": self.get_task(task_id),
            "run_id": run_id,
            "artifact_bundles": self.runs.artifact_bundles(run_id),
        }

    def get_artifact_bundle(
        self,
        task_id: str,
        run_id: str,
        bundle_id: str,
    ) -> dict[str, Any]:
        self._require_owned_run(task_id, run_id)
        bundle = next(
            (
                item
                for item in self.runs.artifact_bundles(run_id)
                if item.get("bundle_id") == bundle_id
            ),
            None,
        )
        if bundle is None:
            raise FileNotFoundError("artifact bundle not found")
        return {
            "task": self.get_task(task_id),
            "run_id": run_id,
            "artifact_bundle": bundle,
        }

    def _artifact_bundle_download_scope(
        self,
        task_id: str,
        run_id: str,
        bundle_id: str,
        *,
        expected_manifest_sha256: str | None = None,
        expected_archive_sha256: str | None = None,
    ) -> tuple[dict[str, Any], Path]:
        detail = self.get_artifact_bundle(task_id, run_id, bundle_id)
        bundle = detail["artifact_bundle"]
        manifest_sha256 = str(bundle.get("manifest_sha256") or "")
        archive = bundle.get("archive") or {}
        archive_sha256 = str(archive.get("sha256") or "")
        if (
            expected_manifest_sha256 is not None
            and manifest_sha256 != expected_manifest_sha256
        ):
            raise DeliveryAuthorizationError(
                "artifact bundle manifest changed before download authorization"
            )
        if (
            expected_archive_sha256 is not None
            and archive_sha256 != expected_archive_sha256
        ):
            raise DeliveryAuthorizationError(
                "artifact bundle archive changed before download authorization"
            )
        path = self.runs.artifact_bundle_path(run_id, bundle_id)
        if sha256_file(path) != archive_sha256:
            raise DeliveryAuthorizationError(
                "artifact bundle archive no longer matches canonical metadata"
            )
        scope = {
            "action": "download_artifact_bundle",
            "task_id": task_id,
            "run_id": run_id,
            "bundle_id": bundle_id,
            "manifest_sha256": manifest_sha256,
            "archive_sha256": archive_sha256,
            "archive_size_bytes": archive.get("size_bytes"),
        }
        return scope, path

    def authorize_artifact_bundle_download(
        self,
        task_id: str,
        run_id: str,
        bundle_id: str,
        *,
        manifest_sha256: str,
        archive_sha256: str,
        approval: Mapping[str, Any],
    ) -> dict[str, Any]:
        with self._lock:
            scope, _ = self._artifact_bundle_download_scope(
                task_id,
                run_id,
                bundle_id,
                expected_manifest_sha256=manifest_sha256,
                expected_archive_sha256=archive_sha256,
            )
            record, token = self.delivery_authorization_store.issue(
                task_id=task_id,
                action="download_artifact_bundle",
                scope=scope,
                approval=approval,
            )
            self._record_delivery_authorization(
                task_id, str(record["authorization_id"])
            )
            return {
                "task_id": task_id,
                "run_id": run_id,
                "bundle_id": bundle_id,
                "artifact_bundle_download_authorization": (
                    self.delivery_authorization_store.public(record)
                ),
                "authorization_token": token,
            }

    def consume_artifact_bundle_download(
        self,
        task_id: str,
        run_id: str,
        bundle_id: str,
        *,
        artifact_bundle_download_authorization_id: str,
        authorization_token: str,
        download_request_sha256: str,
    ) -> tuple[Path, dict[str, Any]]:
        with self._lock:
            authorization = self.delivery_authorization_store.get(
                task_id, artifact_bundle_download_authorization_id
            )
            approved_scope = authorization.get("scope") or {}
            if (
                authorization.get("action") != "download_artifact_bundle"
                or approved_scope.get("task_id") != task_id
                or approved_scope.get("run_id") != run_id
                or approved_scope.get("bundle_id") != bundle_id
            ):
                raise DeliveryAuthorizationError(
                    "artifact bundle download does not match its approved scope"
                )
            current_scope, path = self._artifact_bundle_download_scope(
                task_id,
                run_id,
                bundle_id,
            )
            self.delivery_authorization_store.reserve(
                task_id=task_id,
                authorization_id=artifact_bundle_download_authorization_id,
                authorization_token=authorization_token,
                action="download_artifact_bundle",
                approved_scope_sha256=download_request_sha256,
                current_scope=current_scope,
            )
            completed = self.delivery_authorization_store.complete(
                task_id=task_id,
                authorization_id=artifact_bundle_download_authorization_id,
                succeeded=True,
                outcome={
                    "status": "download_opened",
                    "bundle_id": bundle_id,
                    "manifest_sha256": current_scope["manifest_sha256"],
                    "archive_sha256": current_scope["archive_sha256"],
                },
            )
            return path, self.delivery_authorization_store.public(completed)

    def _require_owned_run(
        self,
        task_id: str,
        run_id: str,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        task = read_json(self._task_path(task_id))
        if run_id not in task.get("run_ids", []):
            raise HarnessError("该运行不属于当前训练任务")
        run_state = self.runs.status(run_id)
        if run_state.get("task_id") != task_id:
            raise HarnessError("运行所有者与当前训练任务不一致")
        return task, run_state

    def dataset_file(self, task_id: str, dataset_id: str, relative_path: str) -> Path:
        task = read_json(self._task_path(task_id))
        if dataset_id not in task.get("dataset_history", []):
            raise FileNotFoundError("dataset not found")
        dataset_dir = (self._task_dir(task_id) / "datasets" / dataset_id).resolve()
        target = (dataset_dir / relative_path).resolve()
        if target == dataset_dir or dataset_dir not in target.parents or not target.is_file():
            raise FileNotFoundError("dataset file not found")
        return target

    def scaffold_recipe(self, task_id: str) -> dict[str, Any]:
        with self._lock:
            task = read_json(self._task_path(task_id))
            request_path = self._recipe_request_path(task_id)
            if not request_path.is_file():
                raise HarnessError("当前任务没有Recipe Build Request")
            request = read_json(request_path)
            result = self.recipe_builder.create(self._task_dir(task_id), request)
            request["status"] = "scaffold_ready"
            request["scaffold"] = result
            request["updated_at_utc"] = _utc_now()
            task["updated_at_utc"] = request["updated_at_utc"]
            write_json(request_path, request)
            write_json(self._task_path(task_id), task)
        return {**result, "task_id": task_id}

    def recipe_scaffold_file(self, task_id: str, archive_name: str) -> Path:
        if Path(archive_name).name != archive_name or not archive_name.endswith(".zip"):
            raise HarnessError("invalid scaffold archive name")
        target = (self._task_dir(task_id) / "recipe_builds" / archive_name).resolve()
        build_root = (self._task_dir(task_id) / "recipe_builds").resolve()
        if target.parent != build_root or not target.is_file():
            raise FileNotFoundError("recipe scaffold not found")
        return target

    def _restore_model_binding_task_projections(self) -> None:
        """Finish any explicitly committed binding after a process restart."""

        for task_path in sorted(self.tasks_dir.glob("*/task.json")):
            task_id = task_path.parent.name
            pointer_path = task_path.parent / "model_sources" / "current_binding.json"
            if not pointer_path.is_file():
                continue
            task = read_json(task_path)
            binding = self.model_source_store.current_binding(task_id)
            if binding is None or task.get(
                "current_model_binding_revision_id"
            ) == binding.get("binding_revision_id"):
                continue
            context = self.model_source_store.binding_context(
                task_id, str(binding["binding_revision_id"])
            )
            if context is None:
                continue
            bound_spec_revision = int(
                context["resolution"].get("details", {}).get(
                    "base_spec_revision", 0
                )
            )
            self._activate_model_binding_on_task(
                task,
                binding,
                bound_spec_revision=bound_spec_revision,
            )
            write_json(task_path, task)

    def _recover_model_binding_commits(self) -> None:
        def current_spec_revision(task_id: str) -> int:
            task = read_json(self._task_path(task_id))
            return int(self._ensure_spec_revision(task)["revision"])

        self.model_source_store.recover_pending_commits(
            resolve_spec_revision=current_spec_revision
        )

    def _activate_model_binding_on_task(
        self,
        task: dict[str, Any],
        binding: dict[str, Any],
        *,
        bound_spec_revision: int,
    ) -> None:
        """Activate a binding while preserving historical data and Run evidence."""

        binding_id = str(binding["binding_revision_id"])
        previous_binding = task.get("current_model_binding_revision_id")
        if previous_binding and previous_binding != binding_id:
            task["last_model_binding_revision_id"] = previous_binding
        task["current_model_binding_revision_id"] = binding_id
        task["model_binding_bound_spec_revision"] = bound_spec_revision
        task["model_binding_stale_for_spec_revision"] = (
            bound_spec_revision < 1
            or int(task.get("current_spec_revision", 0) or 0)
            != bound_spec_revision
        )

        task["contract_confirmed"] = False
        task["confirmations"] = {}
        task["confirmed_contract_sha256"] = None
        task["confirmed_contract_revision_id"] = None
        task["current_approval_decision_id"] = None
        task["contract_stale"] = True
        if task.get("current_run_id"):
            task["last_run_id"] = task["current_run_id"]
            task["current_run_id"] = None

        previous_recipe = task.get("recipe_id")
        if previous_recipe:
            task["last_recipe_id"] = previous_recipe
        task["recipe_id"] = None
        task["recipe_source"] = None
        task["capability_status"] = "needs_recipe"
        task["status"] = "needs_recipe"

        selected_asset_id = task.get("selected_model_asset_id")
        if selected_asset_id:
            task["last_model_asset_id"] = selected_asset_id
        task["selected_model_asset_id"] = None
        task["model_asset_binding"] = None
        task["updated_at_utc"] = _utc_now()
        self._persist_missing_recipe_evidence(
            str(task["task_id"]),
            deepcopy(task.get("capability_request", {})),
            task_spec=self._ensure_spec_revision(task),
        )

    @staticmethod
    def _model_binding_projection(
        task: dict[str, Any],
        binding: dict[str, Any],
        context: dict[str, Any],
        *,
        current_binding_id: str | None,
    ) -> dict[str, Any]:
        resolution = context["resolution"]
        snapshot = context["snapshot"]
        analysis_record = context["analysis"]
        analysis = analysis_record["analysis"]
        bound_spec_revision = int(
            resolution.get("details", {}).get("base_spec_revision", 0)
        )
        current_spec_revision = int(task.get("current_spec_revision", 0) or 0)
        binding_id = str(binding["binding_revision_id"])
        if current_binding_id != binding_id:
            status = "superseded"
        elif (
            bound_spec_revision != current_spec_revision
            or task.get("model_binding_stale_for_spec_revision") is True
        ):
            status = "stale"
        else:
            status = "active"
        files = sorted(
            (deepcopy(item) for item in snapshot.get("files", [])),
            key=lambda item: str(item.get("path") or ""),
        )
        known_sizes = [
            int(item["size_bytes"])
            for item in files
            if isinstance(item.get("size_bytes"), int)
            and not isinstance(item.get("size_bytes"), bool)
            and int(item["size_bytes"]) >= 0
        ]
        remote_code_files = [
            str(item.get("path"))
            for item in files
            if item.get("kind") == "executable"
            or str(item.get("path", "")).lower().endswith(
                (".py", ".sh", ".bash", ".zsh", ".ps1")
            )
        ]
        snapshot_summary = {
            "file_count": len(files),
            "known_size_bytes": sum(known_sizes),
            "unknown_size_count": len(files) - len(known_sizes),
            "size_semantics": (
                "git_tree_blob_bytes_lfs_may_be_additional"
                if resolution["provider"] == "github"
                else "provider_declared_file_bytes"
            ),
            "manifest_sha256": snapshot["tree_manifest_sha256"],
            "file_preview": files[:20],
            "file_preview_truncated": len(files) > 20,
            "remote_code": {
                "declared": bool(remote_code_files),
                "file_count": len(remote_code_files),
                "file_preview": remote_code_files[:12],
                "execution_policy": "static_only_never_execute",
            },
        }
        return {
            **deepcopy(binding),
            "status": status,
            "bound_spec_revision": bound_spec_revision,
            "current_spec_revision": current_spec_revision,
            "provider": resolution["provider"],
            "repository": resolution["repository"],
            "requested_revision": resolution["requested_revision"],
            "resolved_commit": resolution["resolved_commit"],
            "license": snapshot["license"],
            "license_status": snapshot["license_status"],
            "license_policy": deepcopy(
                dict(snapshot.get("details", {}).get("license_policy") or {})
            )
            or _license_policy(
                str(snapshot["license"]), str(snapshot["license_status"])
            ),
            "tree_manifest_sha256": snapshot["tree_manifest_sha256"],
            "snapshot_summary": snapshot_summary,
            "analysis_status": analysis["status"],
            "analysis_next_action": analysis["next_action"],
            "execution_policy": snapshot["execution_policy"],
        }

    @staticmethod
    def _contract_model_binding(binding: dict[str, Any]) -> dict[str, Any]:
        return {
            "model_binding_revision_id": binding["binding_revision_id"],
            "binding_digest": binding["content_digest"],
            "source_snapshot_id": binding["snapshot_id"],
            "source_snapshot_digest": binding["snapshot_digest"],
            "repository_analysis_id": binding["analysis_id"],
            "repository_analysis_digest": binding["analysis_digest"],
            "provider": binding["provider"],
            "repository": binding["repository"],
            "resolved_commit": binding["resolved_commit"],
            "tree_manifest_sha256": binding["tree_manifest_sha256"],
            "bound_spec_revision": binding["bound_spec_revision"],
        }

    def _assert_contract_model_binding_current(
        self,
        task: dict[str, Any],
        contract: dict[str, Any],
    ) -> None:
        if not task.get("current_model_binding_revision_id"):
            return
        binding = self.current_model_binding(str(task["task_id"]))
        if binding is None:
            raise HarnessError("当前模型来源绑定不可用")
        if binding["status"] != "active":
            raise HarnessError("模型来源绑定已因TaskSpec变化失效，请重新解析并批准")
        expected = self._contract_model_binding(binding)
        if contract.get("model_binding") != expected:
            raise HarnessError("训练合同未冻结当前模型来源绑定，必须重新生成并确认")

    def _view(self, task: dict[str, Any]) -> dict[str, Any]:
        task = deepcopy(task)
        with self._lock:
            current_spec = self._ensure_spec_revision(task)
        current_run_id = task.get("current_run_id")
        current_result = None
        if current_run_id:
            try:
                current_result = self.runs.result(current_run_id)
                run_status = current_result["status"]
                mapped = (
                    run_status
                    if run_status
                    in {"completed", "failed", "cancelled", "interrupted"}
                    else "running"
                )
                if task.get("status") == "running" and task.get("status") != mapped:
                    task["status"] = mapped
                    task["updated_at_utc"] = _utc_now()
                    write_json(self._task_path(task["task_id"]), task)
            except FileNotFoundError:
                current_result = None
        dataset_report = None
        if task.get("dataset_id"):
            report_path = self._task_dir(task["task_id"]) / "datasets" / task["dataset_id"] / "dataset_report.json"
            if report_path.is_file():
                dataset_report = read_json(report_path)
        contract = read_json(self._contract_path(task["task_id"])) if self._contract_path(task["task_id"]).is_file() else None
        contract_is_active = bool(contract and not task.get("contract_stale"))
        contract_revision = None
        if contract_is_active and task.get("dataset_id"):
            contract_revision = self._ensure_contract_revision(task)
        if contract_is_active and not task.get("recipe_id"):
            task["recipe_id"] = contract.get("recipe")
            if task["recipe_id"]:
                task["capability_status"] = "matched"
        if contract_is_active and not task.get("data_adapter_id"):
            dataset_kind = contract.get("dataset", {}).get("kind")
            task["data_adapter_id"] = {
                "image_folder": "image-folder-zip",
                "tabular_csv": "tabular-csv",
                "audio_keyword_class_folder": "audio-keyword-class-folder-zip",
            }.get(dataset_kind)
        task["dataset_report"] = dataset_report
        task["contract"] = contract if contract_is_active else None
        task["contract_revision"] = contract_revision
        approval_decision = None
        approval_decision_id = str(task.get("current_approval_decision_id") or "")
        if approval_decision_id:
            try:
                approval_decision = self.get_approval_decision(
                    str(task["task_id"]), approval_decision_id
                )
            except (ApprovalDecisionIntegrityError, FileNotFoundError):
                # A task read must remain available so the product can explain
                # and recover from corrupt approval evidence.  Fail closed by
                # revoking only the still-current confirmation pointer while
                # retaining the immutable decision id/file for audit.
                with self._lock:
                    persisted = read_json(self._task_path(str(task["task_id"])))
                    if (
                        str(persisted.get("current_approval_decision_id") or "")
                        == approval_decision_id
                    ):
                        persisted["contract_confirmed"] = False
                        persisted["confirmations"] = {}
                        persisted["confirmed_contract_sha256"] = None
                        persisted["confirmed_contract_revision_id"] = None
                        persisted["current_approval_decision_id"] = None
                        if persisted.get("status") == "ready":
                            persisted["status"] = "data_ready"
                        persisted["updated_at_utc"] = _utc_now()
                        write_json(
                            self._task_path(str(task["task_id"])), persisted
                        )
                        task.update(
                            {
                                field: deepcopy(persisted.get(field))
                                for field in (
                                    "contract_confirmed",
                                    "confirmations",
                                    "confirmed_contract_sha256",
                                    "confirmed_contract_revision_id",
                                    "current_approval_decision_id",
                                    "status",
                                    "updated_at_utc",
                                )
                            }
                        )
        task["approval_decision"] = approval_decision
        task["current_result"] = current_result
        recipe_request_path = self._recipe_request_path(task["task_id"])
        task["recipe_request"] = read_json(recipe_request_path) if recipe_request_path.is_file() else None
        task["task_spec"] = current_spec
        task["capability_decision"] = deepcopy(
            current_spec.get("capability_decision", {})
        )
        task["staged_assets"] = self._staged_assets_summary(
            task["task_id"],
            int(current_spec["revision"]),
        )
        current_build_id = task.get("current_recipe_build_id")
        task["current_recipe_build"] = (
            self._recipe_build_view(
                self.recipe_factory.get_attempt(str(current_build_id))
            )
            if current_build_id
            else None
        )
        selected_asset_id = task.get("selected_model_asset_id")
        if selected_asset_id:
            try:
                selected_asset = self.model_assets.get(str(selected_asset_id))
                task["model_asset"] = selected_asset.to_dict()
                task["model_asset_verification"] = self.model_assets.verify(
                    str(selected_asset_id)
                ).to_dict()
            except (FileNotFoundError, ModelAssetError):
                task["model_asset"] = None
                task["model_asset_verification"] = {
                    "ok": False,
                    "errors": ["model_asset_unavailable"],
                }
        else:
            task["model_asset"] = None
            task["model_asset_verification"] = None
        binding_attempt = self.binding_analysis_attempt_store.current_attempt(
            task["task_id"]
        )
        task["model_binding_attempt"] = binding_attempt
        current_binding = self.model_source_store.current_binding(task["task_id"])
        if current_binding is not None:
            binding_context = self.model_source_store.binding_context(
                task["task_id"], str(current_binding["binding_revision_id"])
            )
            assert binding_context is not None
            task["model_binding"] = self._model_binding_projection(
                task,
                current_binding,
                binding_context,
                current_binding_id=str(current_binding["binding_revision_id"]),
            )
            task["repository_analysis"] = {
                **deepcopy(binding_context["analysis"]["analysis"]),
                "analysis_digest": binding_context["analysis"]["content_digest"],
                "snapshot_digest": binding_context["snapshot"]["content_digest"],
            }
            task["repository_analysis_attempt"] = (
                self.repository_analysis_store.current_attempt(
                    task["task_id"], str(binding_context["snapshot"]["snapshot_id"])
                )
            )
        else:
            task["model_binding"] = None
            task["repository_analysis"] = None
            task["repository_analysis_attempt"] = binding_attempt
        task["training_plan"] = self.current_training_plan(task["task_id"])
        task["resource_feasibility"] = self.current_resource_feasibility(
            task["task_id"]
        )
        task["blockers"] = self.blocker_store.list(
            task["task_id"], active_only=True
        )
        task["control"] = self._control_projection(
            task,
            current_spec,
            current_result,
        )
        return task

    def _ensure_spec_revision(self, task: dict[str, Any]) -> dict[str, Any]:
        current_revision = int(task.get("current_spec_revision", 0) or 0)
        if current_revision > 0:
            path = self._spec_revision_path(task["task_id"], current_revision)
            if path.is_file():
                return read_json(path)

        capability = self._normalize_capability(task.get("capability_request", {}))
        recipe_id = task.get("recipe_id")
        if recipe_id:
            try:
                plugin = self.runs.registry.get_recipe(str(recipe_id))
                capability = self._capability_for_recipe(plugin, capability)
            except Exception:
                pass
        now = task.get("created_at_utc") or _utc_now()
        spec = build_task_spec_revision(
            task_id=task["task_id"],
            revision=1,
            name=str(task.get("name", "training task")),
            business_goal=str(task.get("business_goal", "specialist model training")),
            capability_request=capability,
            created_at_utc=str(now),
            source="legacy_task_migration",
            supersedes_revision=None,
        )
        write_json(self._spec_revision_path(task["task_id"], 1), spec)
        task["schema_version"] = TASK_SCHEMA_VERSION
        task["current_spec_revision"] = 1
        task["spec_revision_ids"] = [spec["revision_id"]]
        task["capability_request"] = capability
        write_json(self._task_path(task["task_id"]), task)
        return spec

    def _append_spec_for_recipe(
        self,
        task: dict[str, Any],
        plugin: Any,
        source: str,
    ) -> dict[str, Any]:
        current = self._ensure_spec_revision(task)
        capability = self._capability_for_recipe(
            plugin,
            current.get("capability_request", {}),
        )
        if (
            current.get("capability_request") == capability
            and current.get("capability_decision", {}).get("status") == "resolved"
        ):
            return current
        revision = int(current["revision"]) + 1
        spec = build_task_spec_revision(
            task_id=task["task_id"],
            revision=revision,
            name=current["name"],
            business_goal=current["business_goal"],
            capability_request=capability,
            created_at_utc=_utc_now(),
            source=source,
            supersedes_revision=int(current["revision"]),
        )
        write_json(self._spec_revision_path(task["task_id"], revision), spec)
        self._apply_spec_to_task(task, spec)
        return spec

    def _apply_spec_to_task(
        self,
        task: dict[str, Any],
        spec: dict[str, Any],
    ) -> None:
        task["schema_version"] = TASK_SCHEMA_VERSION
        task["name"] = spec["name"]
        task["business_goal"] = spec["business_goal"]
        task["capability_request"] = deepcopy(spec["capability_request"])
        task["current_spec_revision"] = int(spec["revision"])
        revision_ids = list(task.get("spec_revision_ids", []))
        if spec["revision_id"] not in revision_ids:
            revision_ids.append(spec["revision_id"])
        task["spec_revision_ids"] = revision_ids
        self._resolve_superseded_recipe_evidence(task["task_id"], spec)
        self._supersede_stale_assets(
            task["task_id"],
            int(spec["revision"]),
        )
        selected_model_asset_id = task.get("selected_model_asset_id")
        if selected_model_asset_id:
            capability = spec.get("capability_request", {})
            compatible = (
                capability.get("modality") == "image"
                and capability.get("objective") == "classification"
            )
            if compatible and isinstance(task.get("model_asset_binding"), dict):
                task["model_asset_binding"]["attached_spec_revision"] = int(
                    spec["revision"]
                )
            else:
                task["last_model_asset_id"] = selected_model_asset_id
                task["selected_model_asset_id"] = None
                task["model_asset_binding"] = None

        current_model_binding_id = task.get("current_model_binding_revision_id")
        if current_model_binding_id:
            bound_spec_revision = int(
                task.get("model_binding_bound_spec_revision", 0) or 0
            )
            task["model_binding_stale_for_spec_revision"] = (
                bound_spec_revision != int(spec["revision"])
            )

        decision_status = spec.get("capability_decision", {}).get("status")
        selected_recipe = None
        if decision_status == "resolved":
            selected_recipe = self._select_recipe_for_capability(
                spec["capability_request"]
            )

        previous_recipe = task.get("recipe_id")
        task["recipe_id"] = selected_recipe
        task["recipe_source"] = "matched-from-spec" if selected_recipe else None
        task["capability_status"] = (
            "matched"
            if selected_recipe
            else "needs_recipe"
            if decision_status == "resolved"
            else decision_status
        )
        task["contract_confirmed"] = False
        task["confirmations"] = {}
        task["confirmed_contract_sha256"] = None
        task["confirmed_contract_revision_id"] = None
        task["current_approval_decision_id"] = None
        if task.get("current_run_id"):
            task["last_run_id"] = task["current_run_id"]
            task["current_run_id"] = None

        dataset_id = task.get("dataset_id")
        data_adapter_id = task.get("data_adapter_id")
        compatible_dataset = False
        if selected_recipe and dataset_id:
            plugin = self.runs.registry.get_recipe(selected_recipe)
            compatible_dataset = plugin.manifest.data_adapter == data_adapter_id
        if dataset_id and selected_recipe and not compatible_dataset:
            task["last_dataset_id"] = dataset_id
            task["dataset_id"] = None
            task["data_adapter_id"] = None
        task["contract_stale"] = bool(
            task.get("model_binding_stale_for_spec_revision")
            or (
                dataset_id
                and (
                    not selected_recipe
                    or not compatible_dataset
                    or previous_recipe != selected_recipe
                )
            )
        )

        if decision_status == "needs_clarification":
            task["status"] = "needs_clarification"
        elif decision_status == "needs_confirmation":
            task["status"] = "needs_confirmation"
        elif not selected_recipe:
            task["status"] = "needs_recipe"
            self._persist_missing_recipe_evidence(
                task["task_id"],
                spec["capability_request"],
                task_spec=spec,
            )
        elif task.get("dataset_id"):
            self._resolve_missing_recipe_evidence(
                task["task_id"],
                action="verified_recipe_matched_from_spec",
                recipe_id=str(selected_recipe),
            )
            task["status"] = "data_ready"
            contract_path = self._contract_path(task["task_id"])
            if contract_path.is_file():
                contract = read_json(contract_path)
                contract["task_id"] = task["task_id"]
                contract["business_goal"] = spec["business_goal"]
                contract["recipe"] = selected_recipe
                write_json(contract_path, contract)
                self._record_contract_revision(task, contract)
                task["contract_stale"] = False
        else:
            self._resolve_missing_recipe_evidence(
                task["task_id"],
                action="verified_recipe_matched_from_spec",
                recipe_id=str(selected_recipe),
            )
            task["status"] = "awaiting_data"

    def _select_recipe_for_capability(
        self,
        capability: dict[str, Any],
    ) -> str | None:
        matches = self._eligible_recipe_matches_for_capability(capability)
        if not matches:
            return None
        if len(matches) > 1 and int(matches[0]["score"]) == int(matches[1]["score"]):
            return None
        return str(matches[0]["plugin_id"])

    def _eligible_recipe_matches_for_capability(
        self,
        capability: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Return registered Recipes eligible for the original capability.

        Registry membership is the verified boundary. Teaching/reference
        Recipes remain opt-in and cannot satisfy an ordinary production task.
        """

        match_capability = deepcopy(capability)
        family = normalize_family(match_capability.get("family"))
        if family is not None:
            match_capability = capability_for_family(
                family,
                match_capability,
            )
        matches = self.runs.registry.match_recipes(match_capability)
        requested_tags = {
            str(value).strip().lower()
            for value in capability.get("tags", [])
            if str(value).strip()
        }
        if not requested_tags.intersection({"teaching", "builtin-data", "digits"}):
            production_matches = [
                match
                for match in matches
                if not any(
                    marker in str(match["manifest"].get("purpose", "")).lower()
                    for marker in ("teaching", "reference")
                )
            ]
            if production_matches:
                matches = production_matches
            elif matches:
                return []
        return matches

    def _eligible_recipe_ids_for_capability(
        self,
        capability: dict[str, Any],
    ) -> set[str]:
        return {
            str(match["plugin_id"])
            for match in self._eligible_recipe_matches_for_capability(capability)
            if match.get("plugin_id")
        }

    @staticmethod
    def _capability_for_recipe(
        plugin: Any,
        current: dict[str, Any],
    ) -> dict[str, Any]:
        manifest = plugin.manifest
        if manifest.plugin_id == "image-folder-classification":
            family = "image_classification"
        elif manifest.plugin_id == "tabular-regression":
            family = "tabular_regression"
        elif manifest.plugin_id == "digit-classification":
            family = "image_classification"
        else:
            objective = manifest.objectives[0] if manifest.objectives else ""
            modality = manifest.modalities[0] if manifest.modalities else ""
            if objective == "classification" and modality == "audio":
                family = "audio_classification"
            elif objective == "classification" and modality == "image":
                family = "image_classification"
            elif objective == "regression" and modality == "tabular":
                family = "tabular_regression"
            elif objective in {"ocr", "text_recognition"}:
                family = "ocr"
            elif objective in {"detection", "object_detection"}:
                family = "object_detection"
            else:
                family = objective or "classification"
        capability = capability_for_family(family, current)
        if manifest.data_adapter:
            capability["data_adapter"] = manifest.data_adapter
        if manifest.target_kinds and not capability.get("target_kind"):
            capability["target_kind"] = manifest.target_kinds[0]
        if manifest.capability_tags:
            capability["tags"] = sorted(
                {
                    *[
                        str(value).strip().lower()
                        for value in capability.get("tags", [])
                        if str(value).strip()
                    ],
                    *[
                        str(value).strip().lower()
                        for value in manifest.capability_tags
                        if str(value).strip()
                    ],
                }
            )
        return capability

    def _control_projection(
        self,
        task: dict[str, Any],
        spec: dict[str, Any],
        current_result: dict[str, Any] | None,
    ) -> dict[str, Any]:
        task_id = task["task_id"]
        decision = spec.get("capability_decision", {})
        decision_status = decision.get("status")
        blocked_by: list[dict[str, str]] = []

        if decision_status == "needs_clarification":
            blocked_by.append(
                {
                    "code": "task_spec_ambiguous",
                    "message": str(decision.get("question") or "需要澄清任务输出"),
                }
            )
            return {
                "current_stage": "task_understanding",
                "blocked_by": blocked_by,
                "next_action": self._next_action(
                    "clarify_task_spec",
                    "澄清模型的唯一输出",
                    "PATCH",
                    f"/tasks/{task_id}/spec",
                ),
            }
        if decision_status == "needs_confirmation":
            blocked_by.append(
                {
                    "code": "task_spec_confirmation_required",
                    "message": "候选能力已推断，需要用户确认后才能准备数据",
                }
            )
            return {
                "current_stage": "task_understanding",
                "blocked_by": blocked_by,
                "next_action": self._next_action(
                    "confirm_task_spec",
                    "确认任务规格",
                    "PATCH",
                    f"/tasks/{task_id}/spec",
                ),
            }
        source_stages = {
            "source_discovery",
            "source_resolution",
            "source_snapshot",
            "repository_analysis",
        }
        source_blocker = next(
            (
                item
                for item in task.get("blockers", [])
                if item.get("active") is not False
                and item.get("stage") in source_stages
            ),
            None,
        )
        if source_blocker is not None:
            return {
                "current_stage": str(source_blocker["stage"]),
                "blocked_by": [
                    {
                        "code": str(source_blocker["code"]),
                        "message": str(source_blocker["message"]),
                        "blocker_id": str(source_blocker["blocker_id"]),
                    }
                ],
                "next_action": self._next_action(
                    str(source_blocker["retry_action"]),
                    "处理模型来源阻断",
                    "GET",
                    f"/tasks/{task_id}/blockers?active_only=true",
                ),
            }
        training_blocker = next(
            (
                item
                for item in task.get("blockers", [])
                if item.get("active") is not False
                and item.get("stage") == "training_plan"
            ),
            None,
        )
        if training_blocker is not None:
            return {
                "current_stage": "training_plan",
                "blocked_by": [
                    {
                        "code": str(training_blocker["code"]),
                        "message": str(training_blocker["message"]),
                        "blocker_id": str(training_blocker["blocker_id"]),
                    }
                ],
                "next_action": self._next_action(
                    str(training_blocker["retry_action"]),
                    "处理训练计划阻断",
                    "GET",
                    f"/tasks/{task_id}/blockers?active_only=true",
                ),
            }
        resource_blocker = next(
            (
                item
                for item in task.get("blockers", [])
                if item.get("active") is not False
                and item.get("stage")
                in {"resource_probe", "environment_lock", "resource_fit"}
            ),
            None,
        )
        if resource_blocker is not None:
            return {
                "current_stage": str(resource_blocker["stage"]),
                "blocked_by": [
                    {
                        "code": str(resource_blocker["code"]),
                        "message": str(resource_blocker["message"]),
                        "blocker_id": str(resource_blocker["blocker_id"]),
                    }
                ],
                "next_action": self._next_action(
                    str(resource_blocker["retry_action"]),
                    "查看资源事实并处理阻断",
                    "GET",
                    f"/tasks/{task_id}/resource-feasibility",
                ),
            }
        model_binding = task.get("model_binding")
        if isinstance(model_binding, dict):
            if model_binding.get("status") == "stale":
                return {
                    "current_stage": "source_resolution",
                    "blocked_by": [
                        {
                            "code": "model_binding_stale_for_task_spec",
                            "message": "TaskSpec 已更新，需要为当前版本重新选择并批准模型来源",
                        }
                    ],
                    "next_action": self._next_action(
                        "replace_model_source",
                        "重新选择模型来源",
                        "POST",
                        f"/tasks/{task_id}/model-source-searches",
                    ),
                }
            training_plan = task.get("training_plan")
            if isinstance(training_plan, dict):
                if training_plan.get("stale") is True:
                    return {
                        "current_stage": "training_plan",
                        "blocked_by": [
                            {
                                "code": "training_plan_stale",
                                "message": "任务规格或模型来源已变化，需要创建并批准新的训练计划 revision",
                            }
                        ],
                        "next_action": self._next_action(
                            "revise_training_plan",
                            "重新生成训练计划",
                            "POST",
                            f"/tasks/{task_id}/training-plans",
                        ),
                    }
                if training_plan.get("effective_status") != "approved":
                    return {
                        "current_stage": "training_plan",
                        "blocked_by": [
                            {
                                "code": "training_plan_approval_required",
                                "message": "训练计划已经生成，必须批准当前显示的精确 digest 后才能检查资源",
                            }
                        ],
                        "next_action": self._next_action(
                            "approve_training_plan",
                            "审阅并批准训练计划",
                            "POST",
                            f"/tasks/{task_id}/training-plans/{training_plan['plan']['training_plan_revision_id']}/decisions",
                        ),
                    }
                feasibility = task.get("resource_feasibility") or {}
                if feasibility.get("resource_fit_report"):
                    return {
                        "current_stage": "resource_fit",
                        "blocked_by": [],
                        "next_action": self._next_action(
                            "review_resource_feasibility",
                            "审阅本机可行性证据",
                            "GET",
                            f"/tasks/{task_id}/resource-feasibility",
                        ),
                    }
                return {
                    "current_stage": "resource_probe",
                    "blocked_by": [],
                    "next_action": self._next_action(
                        "check_resource_feasibility",
                        "检查这台机器能否训练",
                        "POST",
                        f"/tasks/{task_id}/resource-feasibility-checks",
                    ),
                }
            analysis = task.get("repository_analysis") or {}
            analysis_status = str(analysis.get("status") or "")
            if analysis_status in {"needs_input", "needs_manual_mapping"}:
                return {
                    "current_stage": "repository_analysis",
                    "blocked_by": [
                        {
                            "code": "repository_analysis_needs_input",
                            "message": "固定快照中没有足够证据确认训练入口；必须先补充映射并创建新的分析 revision",
                        }
                    ],
                    "next_action": self._next_action(
                        "map_training_entrypoint",
                        "补充仓库入口映射",
                        "GET",
                        f"/tasks/{task_id}/repository-analyses/{analysis.get('analysis_id', '')}",
                    ),
                }
            if analysis_status != "complete":
                return {
                    "current_stage": "repository_analysis",
                    "blocked_by": [
                        {
                            "code": "repository_analysis_blocked",
                            "message": "仓库静态分析发现未解决的高风险或下游阻断；训练计划、环境与运行保持关闭",
                        }
                    ],
                    "next_action": self._next_action(
                        str(analysis.get("next_action") or "review_repository_risks"),
                        "审阅仓库风险证据",
                        "GET",
                        f"/tasks/{task_id}/repository-analyses/{analysis.get('analysis_id', '')}",
                    ),
                }
            return {
                "current_stage": "training_plan",
                "blocked_by": [],
                "next_action": self._next_action(
                    "create_training_plan",
                    "审阅分析并生成训练计划",
                    "POST",
                    f"/tasks/{task_id}/training-plans",
                ),
            }
        source_store = getattr(self, "model_source_store", None)
        pending_resolutions = [
            item
            for item in (
                source_store.list_resolutions(task_id)
                if source_store is not None
                else []
            )
            if item.get("details", {}).get("base_spec_revision")
            == int(spec["revision"])
        ]
        if pending_resolutions:
            selected = pending_resolutions[-1]
            return {
                "current_stage": "source_resolution",
                "blocked_by": [
                    {
                        "code": "model_source_binding_approval_required",
                        "message": "模型来源已解析为固定 commit，需要用户批准后才能读取仓库清单",
                    }
                ],
                "next_action": self._next_action(
                    "approve_model_source_binding",
                    "检查并批准模型来源",
                    "POST",
                    f"/tasks/{task_id}/model-source-resolutions/{selected['resolution_id']}/bind",
                ),
            }
        if task.get("capability_status") == "needs_recipe":
            capability_gap = next(
                (
                    item
                    for item in task.get("blockers", [])
                    if item.get("active") is not False
                    and item.get("stage") == "build"
                    and item.get("code") == "recipe_unavailable"
                ),
                None,
            )
            blocked_by.append(
                {
                    "code": "verified_recipe_unavailable",
                    "message": (
                        str(capability_gap["message"])
                        if capability_gap is not None
                        else "当前没有与规格匹配且通过验证的 Recipe"
                    ),
                    **(
                        {
                            "blocker_id": str(capability_gap["blocker_id"]),
                            "blocker_digest": str(
                                capability_gap["content_digest"]
                            ),
                        }
                        if capability_gap is not None
                        else {}
                    ),
                }
            )
            if decision.get("selected_family") == "audio_classification":
                current_build = task.get("current_recipe_build") or {}
                build_status = str(current_build.get("status") or "")
                if build_status == "awaiting_registration":
                    attempt_id = str(current_build["attempt_id"])
                    blocked_by.append(
                        {
                            "code": "recipe_registration_approval_required",
                            "message": "Recipe声明与验证已完成，需要明确批准摘要和摘要哈希后才能注册",
                        }
                    )
                    return {
                        "current_stage": "capability_resolution",
                        "blocked_by": blocked_by,
                        "next_action": self._next_action(
                            "approve_recipe_registration",
                            "审阅并注册训练能力",
                            "POST",
                            f"/tasks/{task_id}/recipe-builds/{attempt_id}/register",
                        ),
                    }
                staged_assets = task.get("staged_assets", {})
                if int(staged_assets.get("current_usable_count", 0)) == 0:
                    blocked_by.append(
                        {
                            "code": "recipe_samples_required",
                            "message": "请先上传少量WAV样例，用于构建和验证训练能力",
                        }
                    )
                    return {
                        "current_stage": "capability_resolution",
                        "blocked_by": blocked_by,
                        "next_action": self._next_action(
                            "stage_recipe_samples",
                            "上传语音样例",
                            "POST",
                            f"/tasks/{task_id}/staged-assets",
                        ),
                    }
                return {
                    "current_stage": "capability_resolution",
                    "blocked_by": blocked_by,
                    "next_action": self._next_action(
                        "start_recipe_build",
                        "构建并验证训练能力",
                        "POST",
                        f"/tasks/{task_id}/recipe-builds",
                    ),
                }
            return {
                "current_stage": "capability_resolution",
                "blocked_by": blocked_by,
                "next_action": self._next_action(
                    "review_capability_gap",
                    "联网查找模型或训练仓库",
                    "POST",
                    f"/tasks/{task_id}/model-source-searches",
                ),
            }
        if not task.get("dataset_id"):
            return {
                "current_stage": "data_preparation",
                "blocked_by": [],
                "next_action": self._next_action(
                    "upload_dataset",
                    "导入并检查数据",
                    "POST",
                    f"/tasks/{task_id}/dataset",
                ),
            }
        if not task.get("contract_confirmed"):
            blocked_by.append(
                {
                    "code": "training_contract_confirmation_required",
                    "message": "数据授权、标签和验收门槛尚未确认",
                }
            )
            return {
                "current_stage": "contract_review",
                "blocked_by": blocked_by,
                "next_action": self._next_action(
                    "confirm_training_contract",
                    "审阅并确认训练合同",
                    "POST",
                    f"/tasks/{task_id}/confirm",
                ),
            }
        if task.get("status") == "running":
            run_stage = str((current_result or {}).get("status") or "running")
            return {
                "current_stage": f"run_{run_stage}",
                "blocked_by": [],
                "next_action": self._next_action(
                    "view_run_progress",
                    "查看真实运行进度",
                    "GET",
                    f"/tasks/{task_id}",
                ),
            }
        if task.get("status") == "completed":
            return {
                "current_stage": "evaluation",
                "blocked_by": [],
                "next_action": self._next_action(
                    "review_evaluation",
                    "审阅评测证据与产物",
                    "GET",
                    f"/tasks/{task_id}",
                ),
            }
        if task.get("status") in {"failed", "cancelled", "interrupted"}:
            return {
                "current_stage": "run_recovery",
                "blocked_by": [
                    {
                        "code": f"run_{task['status']}",
                        "message": "上一次运行未完成；旧 Run 证据会保留，可检查后基于同一冻结合同重新训练",
                    }
                ],
                "next_action": self._next_action(
                    "retry_training_run",
                    "检查证据并重新训练",
                    "POST",
                    f"/tasks/{task_id}/runs",
                ),
            }
        return {
            "current_stage": "ready_to_run",
            "blocked_by": [],
            "next_action": self._next_action(
                "start_training_run",
                "开始训练",
                "POST",
                f"/tasks/{task_id}/runs",
            ),
        }

    @staticmethod
    def _next_action(
        action_id: str,
        label: str,
        method: str,
        href: str,
    ) -> dict[str, str]:
        return {
            "id": action_id,
            "label": label,
            "method": method,
            "href": href,
        }

    def _normalize_capability(self, value: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise ContractError("capability_request必须是对象")
        result: dict[str, Any] = {}
        for key in (
            "family",
            "modality",
            "objective",
            "target_kind",
            "target_column",
            "primary_metric",
            "data_adapter",
        ):
            selected = str(value.get(key, "")).strip().lower()
            if selected:
                result[key] = selected
        tags = sorted(
            {
                str(tag).strip().lower()
                for tag in value.get("tags", [])
                if str(tag).strip()
            }
        )
        if tags:
            result["tags"] = tags
        constraints = value.get("constraints")
        if constraints is not None:
            if not isinstance(constraints, dict):
                raise ContractError("capability_request.constraints必须是对象")
            result["constraints"] = deepcopy(constraints)
        return result

    def _new_recipe_request(
        self,
        task_id: str,
        capability: dict[str, Any],
        *,
        task_spec: dict[str, Any],
    ) -> dict[str, Any]:
        now = _utc_now()
        modality = str(capability.get("modality", "specialist"))
        objective = str(capability.get("objective", "training"))
        task_spec_digest = _canonical_digest(task_spec)
        return {
            "schema_version": "0.2",
            "recipe_request_id": f"recipe-request-{uuid4().hex[:10]}",
            "task_id": task_id,
            "task_spec_revision_id": task_spec["revision_id"],
            "task_spec_revision_digest": task_spec_digest,
            "status": "needs_implementation",
            "suggested_plugin_id": _safe_slug(f"{modality}-{objective}", "custom-recipe"),
            "capability_request": deepcopy(capability),
            "original_capability_request": deepcopy(
                task_spec.get("capability_request", {})
            ),
            "required_outputs": [
                "RecipeManifest与合同模板",
                "数据适配器或已验证的现有Adapter绑定",
                "合同校验、训练、独立评测和制品打包",
                "至少一个成功测试、一个无效数据测试和一次深度制品验证",
                "资源、许可、隐私和生产边界说明",
            ],
            "created_at_utc": now,
            "updated_at_utc": now,
        }

    def _persist_missing_recipe_evidence(
        self,
        task_id: str,
        capability: dict[str, Any],
        *,
        task_spec: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Persist one Recipe request and its task-owned capability-gap fact.

        ``needs_recipe`` is an honest product boundary, not a failed Run.  The
        request remains the mutable recovery object while BlockerEvidence
        seals the exact request snapshot that caused training to stay closed.
        """

        task_spec_snapshot = deepcopy(task_spec)
        if task_spec_snapshot.get("task_id") != task_id:
            raise ContractError("TaskSpecRevision不属于当前任务")
        task_spec_digest = _canonical_digest(task_spec_snapshot)
        self._resolve_superseded_recipe_evidence(task_id, task_spec_snapshot)
        for existing in self.blocker_store.list(task_id, active_only=True):
            if existing.get("code") != "recipe_unavailable":
                continue
            verified = verify_recipe_unavailable_evidence(
                existing,
                allow_active_projection=True,
            )
            if (
                verified["facts"].get("task_spec_revision_id")
                == task_spec_snapshot.get("revision_id")
                and verified["facts"].get("task_spec_revision_digest")
                == task_spec_digest
            ):
                return (
                    deepcopy(
                        verified["facts"]["recipe_build_request_snapshot"]
                    ),
                    verified,
                )

        request = self._new_recipe_request(
            task_id,
            capability,
            task_spec=task_spec_snapshot,
        )
        write_json(self._recipe_request_path(task_id), request)
        request_digest = _canonical_digest(request)
        registered_recipe_ids = self.runs.registry.recipe_ids()
        matches = self._eligible_recipe_matches_for_capability(
            task_spec_snapshot.get("capability_request", {})
        )
        blocker = self.blocker_store.append(
            task_id,
            stage="build",
            code="recipe_unavailable",
            message=(
                "当前任务规格没有匹配且已验证的训练 Recipe；真实训练保持关闭，"
                "可继续查找模型来源或构建并注册新能力。"
            ),
            retry_action="review_capability_gap",
            related_object_type="RecipeBuildRequest",
            related_object_id=str(request["recipe_request_id"]),
            related_object_digest=request_digest,
            details={
                "reason_code": "verified_recipe_unavailable",
                "recipe_request_id": request["recipe_request_id"],
                "recipe_request_digest": request_digest,
                "task_spec_revision_id": task_spec_snapshot["revision_id"],
                "task_spec_revision_digest": task_spec_digest,
            },
            detector="model_harness.workspace.recipe_registry_match@1.0",
            facts={
                "original_capability_request": deepcopy(
                    task_spec_snapshot.get("capability_request", {})
                ),
                "requested_capability_request": deepcopy(capability),
                "task_spec_revision_id": task_spec_snapshot["revision_id"],
                "task_spec_revision_digest": task_spec_digest,
                "task_spec_revision_snapshot": task_spec_snapshot,
                "recipe_build_request_digest": request_digest,
                "recipe_build_request_snapshot": deepcopy(request),
                "registered_recipe_ids": registered_recipe_ids,
                "matched_recipe_ids": [
                    str(item["plugin_id"])
                    for item in matches
                    if item.get("plugin_id")
                ],
            },
            rule={
                "requires_verified_recipe": True,
                "matched_recipe_count": len(matches),
                "run_creation_allowed": False,
            },
            evidence_refs=[
                f"/tasks/{task_id}",
                (
                    f"/tasks/{task_id}/spec/revisions/"
                    f"{int(task_spec_snapshot['revision'])}"
                ),
                "/recipes",
                "/data-adapters",
            ],
            recovery_actions=[
                "search_model_sources",
                "build_and_register_recipe",
                "select_verified_recipe",
            ],
            retryable=True,
        )
        return request, blocker

    def _resolve_superseded_recipe_evidence(
        self,
        task_id: str,
        task_spec: dict[str, Any],
    ) -> None:
        """Close an old capability gap only because its TaskSpec was replaced."""

        selected_digest = _canonical_digest(task_spec)
        selected_revision_id = str(task_spec.get("revision_id") or "")
        for blocker in self.blocker_store.list(task_id, active_only=True):
            is_legacy_gap = (
                blocker.get("code") == "qualification_failed"
                and (blocker.get("details") or {}).get("reason_code")
                == "verified_recipe_unavailable"
            )
            if blocker.get("code") == "recipe_unavailable":
                verified = verify_recipe_unavailable_evidence(
                    blocker,
                    allow_active_projection=True,
                )
                same_revision = (
                    verified["facts"].get("task_spec_revision_id")
                    == selected_revision_id
                    and verified["facts"].get("task_spec_revision_digest")
                    == selected_digest
                )
                if same_revision:
                    continue
            elif not is_legacy_gap:
                continue
            self.blocker_store.resolve(
                task_id,
                str(blocker["blocker_id"]),
                action="task_spec_superseded",
                related_object_type="TaskSpecRevision",
            )

    def _resolve_missing_recipe_evidence(
        self,
        task_id: str,
        *,
        action: str,
        recipe_id: str,
    ) -> list[dict[str, Any]]:
        """Resolve a gap only after matching the Recipe to its original spec."""

        active_recipe_blockers = [
            blocker
            for blocker in self.blocker_store.list(task_id, active_only=True)
            if blocker.get("code") == "recipe_unavailable"
        ]
        if not active_recipe_blockers:
            return []
        task = read_json(self._task_path(task_id))
        current_spec = self._ensure_spec_revision(task)
        self.runs.registry.get_recipe(recipe_id)
        if recipe_id not in self._eligible_recipe_ids_for_capability(
            deepcopy(current_spec.get("capability_request", {}))
        ):
            raise ContractError("所选Recipe与已确认的原始能力规格不匹配")
        self._resolve_superseded_recipe_evidence(task_id, current_spec)
        current_spec_digest = _canonical_digest(current_spec)
        resolutions: list[dict[str, Any]] = []
        for blocker in active_recipe_blockers:
            verified = verify_recipe_unavailable_evidence(
                blocker,
                allow_active_projection=True,
            )
            facts = verified["facts"]
            if (
                facts.get("task_spec_revision_id")
                != current_spec.get("revision_id")
                or facts.get("task_spec_revision_digest")
                != current_spec_digest
            ):
                continue
            original_capability = deepcopy(
                facts.get("original_capability_request", {})
            )
            if recipe_id not in self._eligible_recipe_ids_for_capability(
                original_capability
            ):
                raise ContractError(
                    "所选Recipe不能证明满足产生该Blocker的原始能力规格"
                )
            resolutions.append(
                self.blocker_store.resolve(
                    task_id,
                    str(verified["blocker_id"]),
                    action=action,
                    related_object_type="RecipePlugin",
                    related_object_id=recipe_id,
                )
            )
        return resolutions

    def _register_audio_runtime(self) -> None:
        """Register only the audited in-process audio implementation."""

        from .audio_keyword import ADAPTER as AUDIO_ADAPTER
        from .recipes.audio_keyword_plugin import PLUGIN as AUDIO_PLUGIN

        if AUDIO_PLUGIN.manifest.plugin_id not in self.runs.registry.recipe_ids():
            self.runs.registry.register_recipe(AUDIO_PLUGIN)
        if AUDIO_ADAPTER.manifest.adapter_id not in self.data_adapters.adapter_ids():
            self.data_adapters.register(AUDIO_ADAPTER)

    def _restore_registered_recipe_versions(self) -> None:
        """Restore active runtime bindings and replay interrupted registrations."""

        for task_path in sorted(self.tasks_dir.glob("*/task.json")):
            task = read_json(task_path)
            active = self.recipe_factory.version_store.active_for_task(
                str(task["task_id"])
            )
            if not active:
                continue
            intent = self.recipe_factory.version_store.get_intent(
                str(active["intent_id"])
            )
            candidate = self.recipe_factory.candidate(str(intent["attempt_id"]))
            recipe_version = self.recipe_factory.version_store.get_recipe_version(
                str(active["recipe_version_id"])
            )
            adapter_version = self.recipe_factory.version_store.get_adapter_version(
                str(active["adapter_version_id"])
            )
            self._activate_recipe_version(
                recipe_version,
                adapter_version,
                candidate,
                intent,
            )

        self.recipe_factory.recover_registrations(
            resolve_spec_revision=lambda task_id: int(
                self._ensure_spec_revision(read_json(self._task_path(task_id)))[
                    "revision"
                ]
            ),
            activate=self._activate_recipe_version,
        )

    def _activate_recipe_version(
        self,
        recipe_version: dict[str, Any],
        adapter_version: dict[str, Any],
        candidate: dict[str, Any],
        intent: dict[str, Any],
    ) -> None:
        """Idempotently bind a validated version to its existing TrainingTask."""

        task_id = str(intent["task_id"])
        if recipe_version.get("recipe_id") != "audio-keyword-classification":
            raise ContractError("未审计的RecipeVersion不能激活")
        if adapter_version.get("adapter_id") != "audio-keyword-class-folder-zip":
            raise ContractError("未审计的AdapterVersion不能激活")
        if candidate.get("engine") != "sklearn_audio_keyword_v1":
            raise ContractError("未知的可信训练引擎")
        task = read_json(self._task_path(task_id))
        current_spec = self._ensure_spec_revision(task)
        if int(current_spec["revision"]) != int(intent["base_spec_revision"]):
            already_bound = (
                task.get("recipe_version_id") == recipe_version.get("version_id")
                and task.get("recipe_id") == "audio-keyword-classification"
                and current_spec.get("capability_decision", {}).get(
                    "selected_family"
                )
                == "audio_classification"
            )
            if not already_bound:
                # The immutable version remains auditable, but a later TaskSpec
                # must not be silently overwritten on restart.
                return

        self._register_audio_runtime()
        task["recipe_id"] = "audio-keyword-classification"
        task["recipe_source"] = "recipe-factory"
        task["recipe_version_id"] = recipe_version["version_id"]
        task["adapter_version_id"] = adapter_version["version_id"]
        task["recipe_registration_intent_id"] = intent["intent_id"]
        task["recipe_candidate_digest"] = intent["candidate_digest"]
        task["recipe_validation_digest"] = intent["validation_digest"]
        task["recipe_contract_overrides"] = deepcopy(
            candidate.get("compiled_contract_overrides", {})
        )
        task["capability_status"] = "matched"
        if not task.get("dataset_id") and task.get("status") in {
            "needs_recipe",
            "needs_confirmation",
            "needs_clarification",
        }:
            task["status"] = "awaiting_data"
        task["updated_at_utc"] = _utc_now()
        request_path = self._recipe_request_path(task_id)
        if request_path.is_file():
            request = read_json(request_path)
            request.update(
                {
                    "status": "resolved",
                    "resolved_recipe_id": task["recipe_id"],
                    "resolved_recipe_version_id": recipe_version["version_id"],
                    "resolved_at_utc": _utc_now(),
                    "updated_at_utc": _utc_now(),
                }
            )
            write_json(request_path, request)
        self._resolve_missing_recipe_evidence(
            task_id,
            action="verified_recipe_registered",
            recipe_id=str(task["recipe_id"]),
        )
        write_json(self._task_path(task_id), task)

    def _recipe_build_view(self, attempt: dict[str, Any]) -> dict[str, Any]:
        result = deepcopy(attempt)
        attempt_id = str(attempt["attempt_id"])
        result["events"] = self.recipe_factory.events(attempt_id)
        result["validation_report"] = None
        result["candidate"] = None
        result["registration_intent"] = None
        if attempt.get("validation_digest"):
            result["validation_report"] = self.recipe_factory.validation_report(
                attempt_id
            )
        if attempt.get("candidate_digest"):
            result["candidate"] = self.recipe_factory.candidate(attempt_id)
        if attempt.get("registration_intent_id"):
            result["registration_intent"] = (
                self.recipe_factory.version_store.get_intent(
                    str(attempt["registration_intent_id"])
                )
            )
        return result

    def _staged_asset_store(self, task_id: str) -> StagedAssetStore:
        return StagedAssetStore(self._task_dir(task_id), task_id)

    def _staged_assets_summary(
        self,
        task_id: str,
        current_spec_revision: int,
    ) -> dict[str, Any]:
        assets = self._staged_asset_store(task_id).list_assets()
        current_assets = [
            asset
            for asset in assets
            if int(asset.get("spec_revision", 0)) == current_spec_revision
        ]
        current_staged = [
            asset for asset in current_assets if asset.get("status") == "staged"
        ]
        latest = max(
            current_assets,
            key=lambda item: (str(item.get("created_at", "")), item["asset_id"]),
            default=None,
        )
        return {
            "count": len(assets),
            "current_spec_revision": current_spec_revision,
            "current_spec_count": len(current_assets),
            "current_staged_count": len(current_staged),
            "current_usable_count": sum(
                asset.get("status") in {"staged", "consumed"}
                for asset in current_assets
            ),
            "staged_count": sum(asset.get("status") == "staged" for asset in assets),
            "quarantined_count": sum(
                asset.get("status") == "quarantined" for asset in assets
            ),
            "superseded_count": sum(
                asset.get("status") == "superseded" for asset in assets
            ),
            "latest": self._staged_asset_summary(latest) if latest else None,
        }

    @staticmethod
    def _staged_asset_summary(asset: dict[str, Any]) -> dict[str, Any]:
        report = asset.get("report", {})
        return {
            "asset_id": asset["asset_id"],
            "task_id": asset["task_id"],
            "spec_revision": asset["spec_revision"],
            "status": asset["status"],
            "sha256": asset["sha256"],
            "source_filename": asset.get("source_filename"),
            "size_bytes": asset.get("size_bytes"),
            "created_at": asset.get("created_at"),
            "report": {
                "status": report.get("status"),
                "file_count": report.get("file_count"),
                "total_duration_seconds": report.get("total_duration_seconds"),
                "labels_inferred_from_parent_folders": report.get(
                    "labels_inferred_from_parent_folders", []
                ),
                "failure_code": report.get("failure_code"),
                "failure_message": report.get("failure_message"),
            },
        }

    def _supersede_stale_assets(
        self,
        task_id: str,
        current_spec_revision: int,
    ) -> None:
        store = self._staged_asset_store(task_id)
        for asset in store.list_assets(status="staged"):
            if int(asset.get("spec_revision", 0)) != current_spec_revision:
                store.mark_superseded(asset["asset_id"])

    def _task_dir(self, task_id: str) -> Path:
        if not task_id or Path(task_id).name != task_id:
            raise HarnessError("invalid task id")
        target = (self.tasks_dir / task_id).resolve()
        if target.parent != self.tasks_dir:
            raise HarnessError("invalid task id")
        return target

    def _task_path(self, task_id: str) -> Path:
        path = self._task_dir(task_id) / "task.json"
        if not path.is_file() and not path.parent.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
        if not path.is_file() and any(self._task_dir(task_id).iterdir()):
            raise FileNotFoundError(f"task not found: {task_id}")
        return path

    def _contract_path(self, task_id: str) -> Path:
        return self._task_dir(task_id) / "task_contract.json"

    def _dataset_upload_receipt_path(
        self,
        task_id: str,
        request_id: str,
    ) -> Path:
        selected_request_id = self._normalize_dataset_upload_request_id(request_id)
        request_key = hashlib.sha256(selected_request_id.encode("utf-8")).hexdigest()
        return (
            self._task_dir(task_id)
            / "dataset_upload_receipts"
            / f"{request_key}.json"
        )

    def _contract_revision_path(
        self, task_id: str, contract_revision_id: str
    ) -> Path:
        if (
            not contract_revision_id
            or Path(contract_revision_id).name != contract_revision_id
        ):
            raise HarnessError("invalid contract revision id")
        return (
            self._task_dir(task_id)
            / "contract_revisions"
            / f"{contract_revision_id}.json"
        )

    def _approval_decision_path(
        self, task_id: str, approval_decision_id: str
    ) -> Path:
        if (
            not approval_decision_id
            or Path(approval_decision_id).name != approval_decision_id
        ):
            raise HarnessError("invalid approval decision id")
        return (
            self._task_dir(task_id)
            / "approval_decisions"
            / f"{approval_decision_id}.json"
        )

    def _spec_revision_path(self, task_id: str, revision: int) -> Path:
        if revision < 1:
            raise HarnessError("invalid task spec revision")
        return self._task_dir(task_id) / "spec_revisions" / f"r{revision}.json"

    def _recipe_request_path(self, task_id: str) -> Path:
        return self._task_dir(task_id) / "recipe_request.json"
