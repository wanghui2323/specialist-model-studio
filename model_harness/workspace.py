from __future__ import annotations

import hashlib
import io
import os
import re
import shutil
import zipfile
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from threading import RLock
from typing import Any
from uuid import uuid4

from PIL import Image, UnidentifiedImageError

from .contracts import validate_contract
from .data_adapters import DataAdapterRegistry, default_data_adapter_registry
from .errors import ContractError, HarnessError
from .io_utils import read_json, write_json
from .huggingface_assets import (
    HuggingFaceHubDownloader,
    download_huggingface_asset,
    resolve_training_asset,
)
from .huggingface_catalog import HuggingFaceCatalog
from .model_assets import ModelAssetError, ModelAssetStore
from .recipe_builder import RecipeScaffoldBuilder
from .recipe_factory import RecipeFactory
from .service import RunService
from .staged_assets import StagedAssetNotFound, StagedAssetStore
from .task_specs import (
    build_task_spec_revision,
    capability_for_family,
    normalize_family,
)


TASK_SCHEMA_VERSION = "0.2"
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
MAX_ARCHIVE_BYTES = 200 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 750 * 1024 * 1024
MAX_IMAGE_FILES = 10_000
MIN_IMAGES_PER_CLASS = 5


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


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
        self.data_adapters = data_adapters or default_data_adapter_registry()
        self.recipe_builder = RecipeScaffoldBuilder()
        self.recipe_factory = RecipeFactory(self.root / "recipe_factory")
        self.model_assets = ModelAssetStore(self.root / "model_assets")
        self.huggingface_catalog = HuggingFaceCatalog()
        self.huggingface_downloader = HuggingFaceHubDownloader()
        self._lock = RLock()
        self._restore_registered_recipe_versions()

    def create_task(
        self,
        name: str,
        business_goal: str,
        capability_request: dict[str, Any] | None = None,
        recipe_id: str | None = None,
    ) -> dict[str, Any]:
        selected_name = name.strip()
        selected_goal = business_goal.strip()
        if not selected_name:
            raise ContractError("任务名称不能为空")
        if not selected_goal:
            raise ContractError("业务目标不能为空")
        task_id = f"{_safe_slug(selected_name, 'training-task')}-{uuid4().hex[:8]}"
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
            selected_recipe = plugin.manifest.plugin_id
            capability = self._capability_for_recipe(plugin, capability)
            spec = build_task_spec_revision(
                task_id=task_id,
                revision=1,
                name=selected_name,
                business_goal=selected_goal,
                capability_request=capability,
                created_at_utc=now,
                source="task_created_with_recipe",
                supersedes_revision=None,
            )
            decision_status = spec["capability_decision"]["status"]
            recipe_source = "explicit"
            capability_status = "matched"
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
            "current_run_id": None,
            "last_run_id": None,
            "run_ids": [],
            "created_at_utc": now,
            "updated_at_utc": now,
        }
        with self._lock:
            write_json(self._task_path(task_id), task)
            write_json(self._spec_revision_path(task_id, 1), spec)
            if capability_status == "needs_recipe":
                write_json(
                    self._recipe_request_path(task_id),
                    self._new_recipe_request(task_id, capability),
                )
        return self.get_task(task_id)

    def list_tasks(self) -> list[dict[str, Any]]:
        tasks = [self._view(read_json(path)) for path in self.tasks_dir.glob("*/task.json")]
        return sorted(tasks, key=lambda item: item["updated_at_utc"], reverse=True)

    def get_task(self, task_id: str) -> dict[str, Any]:
        return self._view(read_json(self._task_path(task_id)))

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
            task["updated_at_utc"] = _utc_now()
            if self._contract_path(task_id).is_file() and task.get("dataset_id"):
                contract = read_json(self._contract_path(task_id))
                contract["model_asset"] = deepcopy(binding)
                validate_contract(contract, registry=self.runs.registry)
                write_json(self._contract_path(task_id), contract)
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
            if task.get("data_adapter_id") and plugin.manifest.data_adapter != task["data_adapter_id"]:
                raise ContractError("所选Recipe与当前数据适配器不兼容")
            self._append_spec_for_recipe(task, plugin, "recipe_selected")
            task["recipe_id"] = recipe_id
            task["recipe_source"] = "explicit"
            task["capability_status"] = "matched"
            task["status"] = "data_ready" if task.get("dataset_id") else "awaiting_data"
            task["updated_at_utc"] = _utc_now()
            request_path = self._recipe_request_path(task_id)
            if request_path.is_file():
                request = read_json(request_path)
                request["status"] = "resolved"
                request["resolved_recipe_id"] = recipe_id
                request["resolved_at_utc"] = _utc_now()
                write_json(request_path, request)
            write_json(self._task_path(task_id), task)
        return self.get_task(task_id)

    def attach_dataset(
        self,
        task_id: str,
        payload: bytes,
        filename: str,
        options: dict[str, Any] | None = None,
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
                    request = self._new_recipe_request(task_id, capability)
                    write_json(self._recipe_request_path(task_id), request)
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
            if task.get("recipe_source") != "recipe-factory":
                self._append_spec_for_recipe(task, plugin, "dataset_import")
            template = deepcopy(plugin.template())
            _deep_update(
                template,
                deepcopy(task.get("recipe_contract_overrides", {})),
            )
            template["task_id"] = task_id
            template["business_goal"] = task["business_goal"]
            template["dataset"].update(imported.contract_dataset)
            if task.get("model_asset_binding"):
                template["model_asset"] = deepcopy(task["model_asset_binding"])
            task["dataset_id"] = report["dataset_id"]
            task["dataset_history"] = [*task.get("dataset_history", []), report["dataset_id"]]
            task["recipe_id"] = recipe_id
            task["recipe_source"] = task.get("recipe_source") or "matched-from-data"
            task["capability_status"] = "matched"
            task["data_adapter_id"] = adapter.manifest.adapter_id
            task["contract_confirmed"] = False
            task["confirmations"] = {}
            if task.get("current_run_id"):
                task["last_run_id"] = task["current_run_id"]
                task["current_run_id"] = None
            task["status"] = "data_ready"
            task["updated_at_utc"] = _utc_now()
            write_json(self._contract_path(task_id), template)
            write_json(self._task_path(task_id), task)
        return self.get_task(task_id)

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
            options = changes.get("recipe_options", {})
            if options:
                if not isinstance(options, dict):
                    raise ContractError("recipe_options必须是对象")
                contract["recipe_options"].update(options)
            validate_contract(contract, registry=self.runs.registry)
            task["contract_confirmed"] = False
            task["confirmations"] = {}
            if task.get("current_run_id"):
                task["last_run_id"] = task["current_run_id"]
                task["current_run_id"] = None
            task["status"] = "data_ready"
            task["updated_at_utc"] = _utc_now()
            write_json(self._contract_path(task_id), contract)
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
            task["contract_confirmed"] = True
            task["confirmations"] = {**{name: True for name in required}, "confirmed_at_utc": _utc_now()}
            task["status"] = "ready"
            task["updated_at_utc"] = _utc_now()
            write_json(self._task_path(task_id), task)
        return self.get_task(task_id)

    def start_run(self, task_id: str) -> dict[str, Any]:
        with self._lock:
            task = read_json(self._task_path(task_id))
            if task["status"] == "running":
                raise HarnessError("当前任务已有运行正在执行")
            if not task.get("contract_confirmed"):
                raise HarnessError("必须先确认数据授权、标签和验收门槛")
            contract = read_json(self._contract_path(task_id))
            validate_contract(contract, registry=self.runs.registry)
            run_dir = self.runs.submit(contract)
            task["current_run_id"] = run_dir.name
            task["run_ids"] = [*task.get("run_ids", []), run_dir.name]
            task["status"] = "running"
            task["updated_at_utc"] = _utc_now()
            write_json(self._task_path(task_id), task)
        return self.get_task(task_id)

    def apply_strategy(self, task_id: str, run_id: str, strategy_id: str) -> dict[str, Any]:
        with self._lock:
            task = read_json(self._task_path(task_id))
            if run_id not in task.get("run_ids", []):
                raise HarnessError("该运行不属于当前训练任务")
            child = self.runs.apply_strategy(run_id, strategy_id)
            task["current_run_id"] = child.name
            task["run_ids"] = [*task.get("run_ids", []), child.name]
            task["status"] = "running"
            task["updated_at_utc"] = _utc_now()
            write_json(self._task_path(task_id), task)
        return self.get_task(task_id)

    def cancel_run(self, task_id: str, run_id: str) -> dict[str, Any]:
        """Request cancellation only after proving the Run belongs to the Task."""

        with self._lock:
            task = read_json(self._task_path(task_id))
            if run_id not in task.get("run_ids", []):
                raise HarnessError("该运行不属于当前训练任务")
            run_state = self.runs.status(run_id)
            if run_state.get("task_id") != task_id:
                raise HarnessError("运行所有者与当前训练任务不一致")
            accepted = self.runs.cancel(run_id)
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

    def build_artifact_bundle(
        self,
        task_id: str,
        run_id: str,
        *,
        sample_inference_check_id: str | None = None,
        inference_check_id: str | None = None,
    ) -> dict[str, Any]:
        self._require_owned_run(task_id, run_id)
        if sample_inference_check_id and inference_check_id:
            raise ContractError(
                "sample_inference_check_id and inference_check_id are mutually exclusive"
            )
        selected_inference_id = inference_check_id
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
        bundle = self.runs.build_artifact_bundle(
            run_id,
            inference_check_id=(
                str(selected_inference_id) if selected_inference_id else None
            ),
        )
        return {
            "task": self.get_task(task_id),
            "run_id": run_id,
            "artifact_bundle": bundle,
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

    def artifact_bundle_file(
        self,
        task_id: str,
        run_id: str,
        bundle_id: str,
    ) -> Path:
        self._require_owned_run(task_id, run_id)
        return self.runs.artifact_bundle_path(run_id, bundle_id)

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
            dataset_id
            and (
                not selected_recipe
                or not compatible_dataset
                or previous_recipe != selected_recipe
            )
        )

        if decision_status == "needs_clarification":
            task["status"] = "needs_clarification"
        elif decision_status == "needs_confirmation":
            task["status"] = "needs_confirmation"
        elif not selected_recipe:
            task["status"] = "needs_recipe"
            write_json(
                self._recipe_request_path(task["task_id"]),
                self._new_recipe_request(task["task_id"], spec["capability_request"]),
            )
        elif task.get("dataset_id"):
            task["status"] = "data_ready"
            contract_path = self._contract_path(task["task_id"])
            if contract_path.is_file():
                contract = read_json(contract_path)
                contract["task_id"] = task["task_id"]
                contract["business_goal"] = spec["business_goal"]
                contract["recipe"] = selected_recipe
                write_json(contract_path, contract)
                task["contract_stale"] = False
        else:
            task["status"] = "awaiting_data"

    def _select_recipe_for_capability(
        self,
        capability: dict[str, Any],
    ) -> str | None:
        matches = self.runs.registry.match_recipes(capability)
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
                return None
        if not matches:
            return None
        if len(matches) > 1 and int(matches[0]["score"]) == int(matches[1]["score"]):
            return None
        return str(matches[0]["plugin_id"])

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
        if task.get("capability_status") == "needs_recipe":
            blocked_by.append(
                {
                    "code": "verified_recipe_unavailable",
                    "message": "当前没有与规格匹配且通过验证的 Recipe",
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
                    "查看缺失的训练能力",
                    "GET",
                    f"/tasks/{task_id}",
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

    def _new_recipe_request(self, task_id: str, capability: dict[str, Any]) -> dict[str, Any]:
        now = _utc_now()
        modality = str(capability.get("modality", "specialist"))
        objective = str(capability.get("objective", "training"))
        return {
            "schema_version": "0.1",
            "recipe_request_id": f"recipe-request-{uuid4().hex[:10]}",
            "task_id": task_id,
            "status": "needs_implementation",
            "suggested_plugin_id": _safe_slug(f"{modality}-{objective}", "custom-recipe"),
            "capability_request": deepcopy(capability),
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

    def _spec_revision_path(self, task_id: str, revision: int) -> Path:
        if revision < 1:
            raise HarnessError("invalid task spec revision")
        return self._task_dir(task_id) / "spec_revisions" / f"r{revision}.json"

    def _recipe_request_path(self, task_id: str) -> Path:
        return self._task_dir(task_id) / "recipe_request.json"
