from __future__ import annotations

import csv
import hashlib
import io
import os
from dataclasses import asdict, dataclass
from importlib import metadata
from pathlib import Path
from threading import Lock
from typing import Any, Iterable, Protocol, runtime_checkable
from uuid import uuid4

from .errors import ContractError, PluginError
from .io_utils import read_json, sha256_file, write_json


ENTRY_POINT_GROUP = "ai_pm_model_harness.data_adapters"
MAX_CSV_BYTES = 50 * 1024 * 1024
MAX_CSV_ROWS = 200_000
MAX_CSV_COLUMNS = 512
MIN_CSV_ROWS = 30


@dataclass(frozen=True)
class DataAdapterManifest:
    adapter_id: str
    version: str
    description: str
    modalities: tuple[str, ...]
    file_extensions: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["modalities"] = list(self.modalities)
        value["file_extensions"] = list(self.file_extensions)
        return value


@dataclass(frozen=True)
class DataImportResult:
    report: dict[str, Any]
    dataset_dir: Path
    contract_dataset: dict[str, Any]


def verify_training_dataset_integrity(dataset: dict[str, Any]) -> None:
    """Fail closed when live training data differs from the inspected dataset."""

    def fail(reason: str) -> None:
        raise ContractError(f"数据完整性校验失败：{reason}")

    expected = str(dataset.get("fingerprint_sha256", "")).strip()
    if not expected:
        fail("训练合同缺少数据指纹")
    kind = str(dataset.get("kind", ""))
    try:
        if kind == "tabular_csv":
            if sha256_file(Path(str(dataset["csv_path"]))) != expected:
                fail("表格文件与导入时的数据指纹不一致")
            return

        if kind not in {"image_folder", "audio_keyword_class_folder"}:
            fail(f"不支持的数据类型 {kind or '<empty>'}")
        root = Path(str(dataset["root"])).expanduser().resolve()
        manifest = read_json(Path(str(dataset["manifest_path"])))
        samples = manifest.get("samples")
        if not isinstance(samples, list) or not samples:
            fail("数据清单没有可训练样本")
        fingerprint_rows: list[str] = []
        for sample in sorted(
            samples,
            key=lambda item: (
                str(item.get("relative_path", "")) if isinstance(item, dict) else ""
            ),
        ):
            if not isinstance(sample, dict):
                fail("数据清单包含无效样本记录")
            relative_path = Path(str(sample.get("relative_path", "")))
            if relative_path.is_absolute() or not relative_path.parts:
                fail("数据清单包含无效样本路径")
            sample_path = (root / relative_path).resolve()
            try:
                sample_path.relative_to(root)
            except ValueError:
                fail("数据清单中的样本路径越出数据目录")
            actual_digest = sha256_file(sample_path)
            if actual_digest != str(sample.get("sha256", "")):
                fail(f"样本 {relative_path.as_posix()} 与导入记录不一致")
            label = str(sample.get("label", ""))
            if kind == "image_folder":
                fingerprint_rows.append(f"{label}:{actual_digest}")
            else:
                speaker_id = str(sample.get("speaker_id", ""))
                fingerprint_rows.append(f"{label}:{speaker_id}:{actual_digest}")
        actual_fingerprint = hashlib.sha256(
            "\n".join(fingerprint_rows).encode("utf-8")
        ).hexdigest()
        if actual_fingerprint != expected:
            fail("样本清单与导入时的数据指纹不一致")
    except ContractError:
        raise
    except (KeyError, OSError, TypeError, ValueError) as exc:
        raise ContractError(f"数据完整性校验失败：无法读取训练数据（{exc}）") from exc


@runtime_checkable
class DataAdapter(Protocol):
    manifest: DataAdapterManifest

    def supports(self, filename: str) -> bool: ...

    def import_data(
        self,
        datasets_dir: Path,
        payload: bytes,
        filename: str,
        options: dict[str, Any],
    ) -> DataImportResult: ...


class ImageFolderZipAdapter:
    manifest = DataAdapterManifest(
        adapter_id="image-folder-zip",
        version="0.1.0",
        description="Inspect and import class-folder image ZIP archives.",
        modalities=("image",),
        file_extensions=(".zip",),
    )

    def supports(self, filename: str) -> bool:
        return filename.lower().endswith(".zip")

    def import_data(
        self,
        datasets_dir: Path,
        payload: bytes,
        filename: str,
        options: dict[str, Any],
    ) -> DataImportResult:
        # Imported lazily to keep the adapter registry independent from the
        # TrainingWorkspace lifecycle while the legacy importer is migrated.
        from .workspace import import_image_archive

        report, dataset_dir = import_image_archive(datasets_dir, payload, filename)
        return DataImportResult(
            report=report,
            dataset_dir=dataset_dir,
            contract_dataset={
                "kind": "image_folder",
                "dataset_id": report["dataset_id"],
                "root": str(dataset_dir),
                "manifest_path": str(dataset_dir / "dataset_manifest.json"),
                "report_path": str(dataset_dir / "dataset_report.json"),
                "fingerprint_sha256": report["fingerprint_sha256"],
            },
        )


def _numeric(values: Iterable[str]) -> bool:
    seen = False
    for value in values:
        selected = value.strip()
        if not selected:
            continue
        seen = True
        try:
            float(selected)
        except ValueError:
            return False
    return seen


class TabularCsvAdapter:
    manifest = DataAdapterManifest(
        adapter_id="tabular-csv",
        version="0.1.0",
        description="Inspect and import UTF-8 CSV tables with a declared target column.",
        modalities=("tabular",),
        file_extensions=(".csv",),
    )

    def supports(self, filename: str) -> bool:
        return filename.lower().endswith(".csv")

    def import_data(
        self,
        datasets_dir: Path,
        payload: bytes,
        filename: str,
        options: dict[str, Any],
    ) -> DataImportResult:
        if not payload:
            raise ContractError("上传文件为空")
        if len(payload) > MAX_CSV_BYTES:
            raise ContractError("CSV文件超过50MB上传上限")
        if not self.supports(filename):
            raise ContractError("tabular-csv只接受CSV文件")
        try:
            text = payload.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ContractError("CSV必须使用UTF-8编码") from exc

        delimiter = str(options.get("delimiter", "")).strip()
        if not delimiter:
            try:
                delimiter = csv.Sniffer().sniff(text[:8192], delimiters=",;\t|").delimiter
            except csv.Error:
                delimiter = ","
        if len(delimiter) != 1:
            raise ContractError("CSV delimiter必须是单个字符")
        reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
        headers = [str(value).strip() for value in (reader.fieldnames or [])]
        if not headers or any(not header for header in headers):
            raise ContractError("CSV必须包含非空表头")
        if len(headers) > MAX_CSV_COLUMNS:
            raise ContractError(f"CSV列数超过{MAX_CSV_COLUMNS}列上限")
        if len(set(headers)) != len(headers):
            raise ContractError("CSV表头不能重复")

        target_column = str(options.get("target_column", "")).strip()
        if not target_column:
            raise ContractError("导入表格数据必须指定target_column")
        if target_column not in headers:
            raise ContractError(f"目标列不存在：{target_column}")
        ignored_columns = {
            str(value).strip()
            for value in options.get("ignored_columns", [])
            if str(value).strip()
        }
        unknown_ignored = sorted(ignored_columns - set(headers))
        if unknown_ignored:
            raise ContractError(f"忽略列不存在：{unknown_ignored}")
        if target_column in ignored_columns:
            raise ContractError("target_column不能同时被忽略")

        rows: list[dict[str, str]] = []
        rejected_rows: list[dict[str, Any]] = []
        seen_rows: set[tuple[str, ...]] = set()
        for row_number, raw in enumerate(reader, start=2):
            if row_number - 1 > MAX_CSV_ROWS:
                raise ContractError(f"CSV行数超过{MAX_CSV_ROWS}行上限")
            row = {header: str(raw.get(header) or "").strip() for header in headers}
            if not row[target_column]:
                rejected_rows.append({"row": row_number, "reason": "目标值为空"})
                continue
            signature = tuple(row[header] for header in headers)
            if signature in seen_rows:
                rejected_rows.append({"row": row_number, "reason": "整行重复"})
                continue
            seen_rows.add(signature)
            rows.append(row)
        if len(rows) < MIN_CSV_ROWS:
            raise ContractError(f"至少需要{MIN_CSV_ROWS}行有效数据；当前{len(rows)}行")

        feature_columns = [
            header
            for header in headers
            if header != target_column and header not in ignored_columns
        ]
        if not feature_columns:
            raise ContractError("除目标列外至少需要一个特征列")
        numeric_columns = [
            column for column in feature_columns if _numeric(row[column] for row in rows)
        ]
        categorical_columns = [
            column for column in feature_columns if column not in numeric_columns
        ]
        target_is_numeric = _numeric(row[target_column] for row in rows)
        objective = str(options.get("objective", "")).strip().lower()
        if objective == "regression" and not target_is_numeric:
            raise ContractError("回归任务的目标列必须是数值")
        target_values = [row[target_column] for row in rows]
        if objective == "classification" and len(set(target_values)) < 2:
            raise ContractError("分类任务至少需要两个目标类别")

        missing_counts = {
            column: sum(1 for row in rows if not row[column])
            for column in feature_columns
        }
        dataset_id = f"dataset-{uuid4().hex[:10]}"
        temporary_dir = datasets_dir / f".{dataset_id}.tmp"
        final_dir = datasets_dir / dataset_id
        temporary_dir.mkdir(parents=True, exist_ok=False)
        try:
            normalized_csv = temporary_dir / "dataset.csv"
            with normalized_csv.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=headers)
                writer.writeheader()
                writer.writerows(rows)
            fingerprint = hashlib.sha256(normalized_csv.read_bytes()).hexdigest()
            numeric_targets = [float(value) for value in target_values] if target_is_numeric else []
            report = {
                "schema_version": "0.1",
                "dataset_id": dataset_id,
                "source_filename": Path(filename).name,
                "fingerprint_sha256": fingerprint,
                "row_count": len(rows),
                "column_count": len(headers),
                "target_column": target_column,
                "target_kind": "numeric" if target_is_numeric else "categorical",
                "target_unique_count": len(set(target_values)),
                "target_summary": (
                    {
                        "min": min(numeric_targets),
                        "max": max(numeric_targets),
                        "mean": sum(numeric_targets) / len(numeric_targets),
                    }
                    if numeric_targets
                    else {"classes": sorted(set(target_values))[:100]}
                ),
                "feature_columns": feature_columns,
                "numeric_columns": numeric_columns,
                "categorical_columns": categorical_columns,
                "ignored_columns": sorted(ignored_columns),
                "missing_counts": missing_counts,
                "rejected_count": len(rejected_rows),
                "rejected_rows": rejected_rows[:50],
                "delimiter": delimiter,
                "risks": [
                    {
                        "level": "warning",
                        "message": f"{sum(1 for value in missing_counts.values() if value)}个特征列包含缺失值，训练管线将执行插补",
                    }
                ]
                if any(missing_counts.values())
                else [{"level": "ok", "message": "未发现阻断训练的数据问题"}],
            }
            write_json(temporary_dir / "dataset_manifest.json", {"headers": headers})
            write_json(temporary_dir / "dataset_report.json", report)
            datasets_dir.mkdir(parents=True, exist_ok=True)
            os.replace(temporary_dir, final_dir)
        except Exception:
            import shutil

            shutil.rmtree(temporary_dir, ignore_errors=True)
            raise
        return DataImportResult(
            report=report,
            dataset_dir=final_dir,
            contract_dataset={
                "kind": "tabular_csv",
                "dataset_id": dataset_id,
                "root": str(final_dir),
                "csv_path": str(final_dir / "dataset.csv"),
                "manifest_path": str(final_dir / "dataset_manifest.json"),
                "report_path": str(final_dir / "dataset_report.json"),
                "fingerprint_sha256": report["fingerprint_sha256"],
                "target_column": target_column,
                "feature_columns": feature_columns,
                "numeric_columns": numeric_columns,
                "categorical_columns": categorical_columns,
                "ignored_columns": sorted(ignored_columns),
            },
        )


class DataAdapterRegistry:
    def __init__(self, include_builtins: bool = True) -> None:
        self._adapters: dict[str, DataAdapter] = {}
        if include_builtins:
            self.register(ImageFolderZipAdapter())
            self.register(TabularCsvAdapter())

    def register(self, adapter: DataAdapter) -> None:
        if not isinstance(adapter, DataAdapter):
            raise PluginError("data adapter does not satisfy the DataAdapter protocol")
        adapter_id = adapter.manifest.adapter_id
        if not adapter_id or adapter_id in self._adapters:
            raise PluginError(f"duplicate or empty data adapter id: {adapter_id!r}")
        self._adapters[adapter_id] = adapter

    def discover(self) -> None:
        entry_points = metadata.entry_points()
        selected: Iterable[metadata.EntryPoint]
        if hasattr(entry_points, "select"):
            selected = entry_points.select(group=ENTRY_POINT_GROUP)
        else:  # pragma: no cover
            selected = entry_points.get(ENTRY_POINT_GROUP, [])
        for entry_point in selected:
            loaded = entry_point.load()
            adapter = loaded() if isinstance(loaded, type) else loaded
            self.register(adapter)

    def get(self, adapter_id: str) -> DataAdapter:
        try:
            return self._adapters[adapter_id]
        except KeyError as exc:
            raise PluginError(
                f"unknown data adapter: {adapter_id}; available: {self.adapter_ids()}"
            ) from exc

    def adapter_ids(self) -> list[str]:
        return sorted(self._adapters)

    def manifests(self) -> list[dict[str, Any]]:
        return [self._adapters[key].manifest.to_dict() for key in self.adapter_ids()]

    def infer(self, filename: str) -> list[DataAdapter]:
        return [self._adapters[key] for key in self.adapter_ids() if self._adapters[key].supports(filename)]


_default_registry: DataAdapterRegistry | None = None
_default_lock = Lock()


def default_data_adapter_registry() -> DataAdapterRegistry:
    global _default_registry
    with _default_lock:
        if _default_registry is None:
            registry = DataAdapterRegistry(include_builtins=True)
            registry.discover()
            _default_registry = registry
        return _default_registry
