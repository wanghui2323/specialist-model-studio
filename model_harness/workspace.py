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
from .recipe_builder import RecipeScaffoldBuilder
from .service import RunService


TASK_SCHEMA_VERSION = "0.1"
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
        self._lock = RLock()

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
        selected_recipe = None
        recipe_source = None
        capability_status = "unresolved"
        if recipe_id:
            selected_recipe = self.runs.registry.get_recipe(recipe_id).manifest.plugin_id
            recipe_source = "explicit"
            capability_status = "matched"
        elif capability:
            matches = self.runs.registry.match_recipes(capability)
            if matches and (len(matches) == 1 or matches[0]["score"] > matches[1]["score"]):
                selected_recipe = str(matches[0]["plugin_id"])
                recipe_source = "matched"
                capability_status = "matched"
            else:
                capability_status = "needs_recipe"
        task = {
            "schema_version": TASK_SCHEMA_VERSION,
            "task_id": task_id,
            "name": selected_name,
            "business_goal": selected_goal,
            "status": "awaiting_data" if selected_recipe else "needs_recipe" if capability_status == "needs_recipe" else "draft",
            "capability_request": capability,
            "capability_status": capability_status,
            "recipe_id": selected_recipe,
            "recipe_source": recipe_source,
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

    def select_recipe(self, task_id: str, recipe_id: str) -> dict[str, Any]:
        with self._lock:
            task = read_json(self._task_path(task_id))
            if task["status"] == "running":
                raise HarnessError("运行中不能更换Recipe")
            plugin = self.runs.registry.get_recipe(recipe_id)
            if task.get("data_adapter_id") and plugin.manifest.data_adapter != task["data_adapter_id"]:
                raise ContractError("所选Recipe与当前数据适配器不兼容")
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

            recipe_id = task.get("recipe_id")
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
            template = deepcopy(plugin.template())
            template["task_id"] = task_id
            template["business_goal"] = task["business_goal"]
            template["dataset"].update(imported.contract_dataset)
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
        current_run_id = task.get("current_run_id")
        current_result = None
        if current_run_id:
            try:
                current_result = self.runs.result(current_run_id)
                run_status = current_result["status"]
                mapped = "completed" if run_status == "completed" else "failed" if run_status in {"failed", "cancelled", "interrupted"} else "running"
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
        if contract and not task.get("recipe_id"):
            task["recipe_id"] = contract.get("recipe")
            if task["recipe_id"]:
                task["capability_status"] = "matched"
        if contract and not task.get("data_adapter_id"):
            dataset_kind = contract.get("dataset", {}).get("kind")
            task["data_adapter_id"] = {
                "image_folder": "image-folder-zip",
                "tabular_csv": "tabular-csv",
            }.get(dataset_kind)
        task["dataset_report"] = dataset_report
        task["contract"] = contract
        task["current_result"] = current_result
        recipe_request_path = self._recipe_request_path(task["task_id"])
        task["recipe_request"] = read_json(recipe_request_path) if recipe_request_path.is_file() else None
        return task

    def _normalize_capability(self, value: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise ContractError("capability_request必须是对象")
        result: dict[str, Any] = {}
        for key in (
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

    def _recipe_request_path(self, task_id: str) -> Path:
        return self._task_dir(task_id) / "recipe_request.json"
