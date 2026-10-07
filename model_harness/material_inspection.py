"""Owner-scoped, bounded material inspection independent of training data.

Archives remain opaque blobs: no extraction, execution, model loading, network
request, dependency installation, TaskSpec write or training authorization.
"""
from __future__ import annotations

import csv
import fcntl
import hashlib
import io
import json
import math
import os
import re
import shutil
import stat
import tempfile
import unicodedata
import zipfile
import zlib
from collections import Counter
from contextlib import contextmanager
from datetime import UTC, date, datetime
from pathlib import Path, PurePosixPath
from threading import RLock
from typing import Any

from PIL import Image, UnidentifiedImageError

from .errors import ContractError, HarnessError
from .io_utils import read_json, write_json
from .staged_assets import _canonical_member_name, _inspect_pcm_wav, _member_kind, _read_member

MAX_MATERIAL_BYTES = 25 * 1024 * 1024
MAX_ENTRIES = 1024
MAX_UNCOMPRESSED_BYTES = 100 * 1024 * 1024
MAX_COMPRESSION_RATIO = 250
MAX_ROWS = 100_000
MAX_COLUMNS = 256
MAX_CELLS = 2_000_000
MAX_IMAGE_PIXELS = 20_000_000
MAX_TOTAL_IMAGE_PIXELS = 100_000_000
PREVIEW_CHARS = 6000
MAX_PROFILE_COLUMNS = 24
MAX_PROFILE_DISTINCT = 4096
MAX_GROUP_CARDINALITY = 32
MAX_GROUP_DATE_PAIRS = 20_000
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
ANNOTATION_COLUMNS = {"text", "transcript", "transcription", "label", "labels", "target"}
REFERENCE_COLUMNS = {"audio", "image", "file", "path", "audio_path", "image_path", "file_path", "filename", "file_name"}
REQUEST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")
MATERIAL_ID = re.compile(r"^material-[0-9a-f]{24}$")


class MaterialConflict(HarnessError):
    pass


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object field")
        result[key] = value
    return result


def validate_metadata(filename: str, request_id: str) -> tuple[str, str]:
    if not isinstance(request_id, str) or not REQUEST_ID.fullmatch(request_id):
        raise ContractError("X-Request-ID必须是1至160位字母、数字或._:-")
    if not isinstance(filename, str):
        raise ContractError("X-Filename必须提供文件名")
    selected = unicodedata.normalize("NFC", filename.strip())
    if not selected or len(selected) > 180 or any(ch in selected for ch in "/\\\x00") or any(ord(ch) < 32 for ch in selected):
        raise ContractError("X-Filename必须是安全的文件名，不接受本机路径")
    return selected, request_id


def _iso_date(value: Any) -> int | None:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value.strip()):
        return None
    try:
        return date.fromisoformat(value.strip()).toordinal()
    except ValueError:
        return None


def _date_coverage(days: set[int], minimum: int | None, maximum: int | None, *, truncated: bool = False) -> dict[str, Any]:
    ordered = sorted(days)
    return {"min": date.fromordinal(minimum).isoformat() if minimum is not None else None,
        "max": date.fromordinal(maximum).isoformat() if maximum is not None else None,
        "distinct_count": len(days), "distinct_count_is_lower_bound": truncated,
        "calendar_span_days": maximum - minimum + 1 if minimum is not None and maximum is not None else 0,
        "missing_calendar_days": None if truncated else (maximum - minimum + 1 - len(days) if minimum is not None and maximum is not None else 0),
        "gap_count": None if truncated else sum(right - left > 1 for left, right in zip(ordered, ordered[1:])),
        "max_gap_days": None if truncated else max((right - left - 1 for left, right in zip(ordered, ordered[1:])), default=0),
        "calendar_gap_basis": "consecutive_calendar_days_not_an_assumed_sampling_schedule"}


class _ColumnProfile:
    def __init__(self) -> None:
        self.non_empty = self.text_count = self.numeric_count = self.date_count = 0
        self.distinct: set[str] = set()
        self.distinct_truncated = self.dates_truncated = False
        self.text_min = self.text_max = self.numeric_min = self.numeric_max = None
        self.date_min = self.date_max = None
        self.days: set[int] = set()

    def add(self, value: Any) -> None:
        if value is None or (isinstance(value, str) and not value.strip()):
            return
        self.non_empty += 1
        identity = _digest(value)
        if identity not in self.distinct:
            if len(self.distinct) < MAX_PROFILE_DISTINCT:
                self.distinct.add(identity)
            else:
                self.distinct_truncated = True
        if isinstance(value, str):
            length = len(value)
            self.text_count += 1
            self.text_min = length if self.text_min is None else min(self.text_min, length)
            self.text_max = length if self.text_max is None else max(self.text_max, length)
        if not isinstance(value, bool) and isinstance(value, (str, int, float)):
            try:
                numeric = float(value)
            except (ValueError, OverflowError):
                numeric = math.nan
            if math.isfinite(numeric):
                self.numeric_count += 1
                self.numeric_min = numeric if self.numeric_min is None else min(self.numeric_min, numeric)
                self.numeric_max = numeric if self.numeric_max is None else max(self.numeric_max, numeric)
        ordinal = _iso_date(value)
        if ordinal is not None:
            self.date_count += 1
            self.date_min = ordinal if self.date_min is None else min(self.date_min, ordinal)
            self.date_max = ordinal if self.date_max is None else max(self.date_max, ordinal)
            if ordinal not in self.days:
                if len(self.days) < MAX_PROFILE_DISTINCT:
                    self.days.add(ordinal)
                else:
                    self.dates_truncated = True

    def report(self) -> dict[str, Any]:
        return {"non_empty_count": self.non_empty, "distinct_count": len(self.distinct),
            "distinct_count_is_lower_bound": self.distinct_truncated, "distinct_basis": "typed_source_values_without_trimming",
            "text_length": {"count": self.text_count, "min": self.text_min, "max": self.text_max, "unit": "unicode_codepoints"},
            "numeric": {"count": self.numeric_count, "min": self.numeric_min, "max": self.numeric_max},
            "iso_date": {"count": self.date_count, "format": "YYYY-MM-DD", **_date_coverage(self.days, self.date_min, self.date_max, truncated=self.dates_truncated)}}


def _grouped_date_profiles(profiles: dict[str, _ColumnProfile], rows: Any) -> list[dict[str, Any]]:
    dates = [key for key, profile in profiles.items() if profile.non_empty and profile.date_count == profile.non_empty][:2]
    group_columns = [key for key, profile in profiles.items() if profile.date_count != profile.non_empty and 1 < len(profile.distinct) <= MAX_GROUP_CARDINALITY and not profile.distinct_truncated][:4]
    if not dates or not group_columns:
        return []
    pairs = {(group, day): {"groups": {}, "analyzed": 0, "missing": 0, "duplicates": 0, "tracked_pairs": 0, "truncated": False} for group in group_columns for day in dates}
    for row in rows():
        for (group_column, date_column), pair in pairs.items():
            group_value = row.get(group_column)
            ordinal = _iso_date(row.get(date_column))
            if group_value is None or (isinstance(group_value, str) and not group_value.strip()) or ordinal is None:
                pair["missing"] += 1
                continue
            pair["analyzed"] += 1
            group_key = _digest(group_value)
            group = pair["groups"].setdefault(group_key, {"row_count": 0, "days": set(), "min": ordinal, "max": ordinal, "truncated": False})
            group["row_count"] += 1
            group["min"] = min(group["min"], ordinal)
            group["max"] = max(group["max"], ordinal)
            if ordinal in group["days"]:
                pair["duplicates"] += 1
            elif pair["tracked_pairs"] < MAX_GROUP_DATE_PAIRS:
                group["days"].add(ordinal)
                pair["tracked_pairs"] += 1
            else:
                pair["truncated"] = group["truncated"] = True
    return [{"group_column": group_column, "date_column": date_column,
        "group_count": len(pair["groups"]), "analyzed_row_count": pair["analyzed"], "missing_pair_count": pair["missing"],
        "duplicate_pair_count": pair["duplicates"], "duplicate_pair_count_is_lower_bound": pair["truncated"],
        "pair_unique": None if pair["truncated"] else pair["duplicates"] == 0,
        "groups": [{"group_index": index, "row_count": group["row_count"],
            "date_coverage": _date_coverage(group["days"], group["min"], group["max"], truncated=group["truncated"])}
            for index, group in enumerate(pair["groups"].values(), 1)],
        "group_values_disclosed": False,
    } for (group_column, date_column), pair in pairs.items()]


class _Inspector:
    def __init__(self) -> None:
        self.facts = {"format": None, "file_count": 0, "files_inspected": 0,
                      "total_uncompressed_bytes": 0, "extension_counts": {}, "table_count": 0,
                      "row_count": 0, "image_count": 0, "wav_count": 0, "total_audio_seconds": 0.0,
                      "paired_reference_count": 0, "missing_reference_count": 0,
                      "duplicate_reference_count": 0, "duplicate_content_groups": 0,
                      "conflicting_annotation_count": 0,
                      "preview_truncated": False}
        self.errors: list[dict[str, Any]] = []
        self.warnings: list[dict[str, Any]] = []
        self.issue_counts = Counter()
        self.tables: list[dict[str, Any]] = []
        self.media = {"images": [], "wav": [], "pairings": []}
        self.preview_remaining = PREVIEW_CHARS
        self.names: set[str] | None = None
        self.content_counts = Counter()
        self.reference_tables: dict[str, set[str]] = {}
        self.reference_annotations: dict[tuple[str, str], str] = {}
        self.pixels = 0
        self.cells = 0

    def issue(self, code: str, message: str, *, file: str | None = None, row: int | None = None, warning: bool = False) -> None:
        target = self.warnings if warning else self.errors
        self.issue_counts["warnings" if warning else "errors"] += 1
        if len(target) >= 32:
            self.facts["preview_truncated"] = True
            return
        item: dict[str, Any] = {"code": code, "message": message[:160]}
        if file is not None:
            item["file"] = file[:180]
        if row is not None:
            item["row"] = row
        target.append(item)

    def preview(self, value: Any) -> Any:
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, allow_nan=False)
        allowed = min(120, self.preview_remaining)
        self.preview_remaining -= min(len(text), allowed)
        if len(text) > allowed:
            self.facts["preview_truncated"] = True
        return text[:allowed]

    def reference(self, table: str, row: int, column: str, value: Any, seen: set[str], annotations: dict[str, str]) -> None:
        if not isinstance(value, str) or not value.strip():
            self.issue("empty_or_invalid_reference", "文件引用必须是非空相对路径文本", file=table, row=row)
            return
        if self.names is None:
            return  # A standalone table cannot prove external file presence.
        reference = value.strip()
        resolved = None
        try:
            canonical, _ = _canonical_member_name(reference, limit=512)
            options = {canonical, (PurePosixPath(table).parent / canonical).as_posix()}
            matches = options & self.names
            if len(matches) == 1:
                resolved = matches.pop()
            elif len(matches) > 1:
                self.issue("ambiguous_reference", "引用同时匹配根目录和标注文件相对目录，请明确引用", file=table, row=row)
        except ValueError:
            self.issue("unsafe_reference", "配对文件引用必须是包内安全相对路径", file=table, row=row)
        if resolved is None:
            self.facts["missing_reference_count"] += 1
            self.issue("missing_reference", "标注引用的文件在材料包中不存在或无法唯一定位", file=table, row=row)
        else:
            suffix = PurePosixPath(resolved).suffix.lower()
            if (column.lower().startswith("audio") and suffix != ".wav") or (column.lower().startswith("image") and suffix not in IMAGE_EXTENSIONS):
                self.issue("reference_media_type_mismatch", "引用文件类型与音频或图片列不一致", file=table, row=row)
            self.facts["paired_reference_count"] += 1
            if resolved in seen:
                self.facts["duplicate_reference_count"] += 1
            seen.add(resolved)
            self.reference_tables.setdefault(resolved, set()).add(table)
            for key, annotation in annotations.items():
                identity = (resolved, key)
                prior = self.reference_annotations.get(identity)
                if prior is not None and prior != annotation:
                    self.facts["conflicting_annotation_count"] += 1
                    self.issue("conflicting_annotation", "同一文件在标注表中对应不同的标注值，请核对", file=table, row=row)
                self.reference_annotations[identity] = annotation
        if len(self.media["pairings"]) < 20:
            self.media["pairings"].append({"table": table[:180], "row": row, "column": column[:80],
                "reference": reference[:180], "resolved_file": resolved[:180] if resolved else None,
                "status": "found" if resolved else "missing_or_ambiguous"})
        else:
            self.facts["preview_truncated"] = True

    def table(self, name: str, payload: bytes, suffix: str) -> None:
        text = payload.decode("utf-8-sig")
        if "\x00" in text:
            raise ValueError("NUL in text table")
        columns: list[str] = []
        if suffix == ".csv":
            try:
                delimiter = csv.Sniffer().sniff(text[:8192], delimiters=",;\t|").delimiter
            except csv.Error:
                delimiter = ","
            reader = csv.DictReader(io.StringIO(text, newline=""), delimiter=delimiter, strict=True)
            original = reader.fieldnames or []
            columns = [value.strip() for value in original]
            if not columns or any(not value or len(value) > 128 for value in columns) or len(set(columns)) != len(columns):
                raise ValueError("CSV headers empty, duplicate or too long")
            if columns != original:
                self.issue("header_whitespace", "表头含首尾空格，报告按去除空格后的列名展示；原文件未修改", file=name, warning=True)
            if len(columns) > MAX_COLUMNS:
                raise ValueError("table exceeds column limit")
            reader.fieldnames = columns
            iterator = iter(reader)
            def rows_again():
                selected = csv.DictReader(io.StringIO(text, newline=""), delimiter=delimiter, strict=True)
                selected.fieldnames = [value.strip() for value in selected.fieldnames or []]
                return selected
        else:
            def json_lines():
                for line in io.StringIO(text):
                    if line.strip():
                        yield json.loads(line, object_pairs_hook=_json_object, parse_constant=lambda _: (_ for _ in ()).throw(ValueError("non-finite JSON")))
            iterator = json_lines()
            rows_again = json_lines
        missing: Counter[str] = Counter()
        seen_rows: set[str] = set()
        seen_references: set[str] = set()
        previews = []
        profiles: dict[str, _ColumnProfile] = {}
        count = duplicates = 0
        for row in iterator:
            if not isinstance(row, dict) or None in row or (suffix == ".csv" and any(v is None for v in row.values())):
                raise ValueError("row must be an object with the declared column count")
            for key in row:
                if not isinstance(key, str) or not key.strip() or len(key) > 128:
                    raise ValueError("invalid column name")
                if key not in columns:
                    columns.append(key)
                    missing[key] = count
            if len(columns) > MAX_COLUMNS:
                raise ValueError("table exceeds column limit")
            count += 1
            self.facts["row_count"] += 1
            self.cells += len(columns)
            if self.facts["row_count"] > MAX_ROWS or self.cells > MAX_CELLS:
                raise ValueError("table row or cell inspection limit exceeded")
            annotations = {
                key.strip().lower(): str(value).strip() if isinstance(value, (str, int, float, bool)) else _digest(value)
                for key, value in row.items() if key.strip().lower() in ANNOTATION_COLUMNS and value is not None
            }
            for key in columns:
                value = row.get(key)
                if value is None or (isinstance(value, str) and not value.strip()):
                    missing[key] += 1
                if key in columns[:MAX_PROFILE_COLUMNS]:
                    profiles.setdefault(key, _ColumnProfile()).add(value)
                if key.strip().lower() in REFERENCE_COLUMNS:
                    self.reference(name, count, key, value, seen_references, annotations)
            signature = _digest(row)
            duplicates += signature in seen_rows
            seen_rows.add(signature)
            if count <= 5 and self.preview_remaining:
                previews.append({key[:80]: self.preview(row.get(key)) for key in columns[:8]})
        if count == 0:
            self.issue("empty_table", "表格没有数据行", file=name)
        self.facts["table_count"] += 1
        if duplicates:
            self.issue("duplicate_rows", f"表内发现{duplicates}条完全重复记录；仅报告事实，未自动删行", file=name, warning=True)
        if any(missing[key] == count for key in columns if key.lower() in ANNOTATION_COLUMNS) and count:
            self.issue("empty_annotation_column", "标注列全部为空，需补齐后才能用于有监督训练", file=name, warning=True)
        if self.names is None and set(key.lower() for key in columns) & REFERENCE_COLUMNS:
            self.issue("external_pairing_unverified", "单独表格中的文件引用尚未提供，无法核对配对文件存在性", file=name, warning=True)
        if len(self.tables) < 10:
            self.tables.append({"file": name[:180], "format": suffix[1:], "row_count": count,
                "column_count": len(columns), "columns": columns[:24], "columns_truncated": len(columns) > 24,
                "missing_counts": {key: missing[key] for key in columns[:24]},
                "duplicate_row_count": duplicates, "preview": previews,
                "column_profiles": {key: profile.report() for key, profile in profiles.items()},
                "profiled_column_count": len(profiles), "profiles_truncated": len(columns) > MAX_PROFILE_COLUMNS,
                "grouped_date_profiles": _grouped_date_profiles(profiles, rows_again),
                "profile_limits": {"max_columns": MAX_PROFILE_COLUMNS, "distinct_values_per_column": MAX_PROFILE_DISTINCT, "group_columns": 4, "date_columns": 2, "tracked_pairs_per_profile": MAX_GROUP_DATE_PAIRS},
                "profile_schema_version": "0.1",
                "profile_scope": "observed_structure_only_not_semantic_accuracy_or_training_sufficiency"})
        else:
            self.facts["preview_truncated"] = True

    def file(self, name: str, payload: bytes) -> None:
        self.facts["files_inspected"] += 1
        self.content_counts[_sha(payload)] += 1
        suffix = PurePosixPath(name).suffix.lower()
        try:
            if suffix in {".csv", ".jsonl", ".ndjson"}:
                self.table(name, payload, ".jsonl" if suffix == ".ndjson" else suffix)
            elif suffix == ".json":
                json.loads(payload.decode("utf-8-sig"), object_pairs_hook=_json_object, parse_constant=lambda _: (_ for _ in ()).throw(ValueError("non-finite JSON")))
            elif suffix in {".txt", ".md"}:
                payload.decode("utf-8-sig")
            elif suffix in IMAGE_EXTENSIONS:
                with Image.open(io.BytesIO(payload)) as picture:
                    width, height = picture.size
                    pixels = width * height
                    self.pixels += pixels
                    if pixels > MAX_IMAGE_PIXELS or self.pixels > MAX_TOTAL_IMAGE_PIXELS:
                        raise ValueError("decoded image pixel budget exceeded")
                    picture.load()
                    self.facts["image_count"] += 1
                    if len(self.media["images"]) < 20:
                        self.media["images"].append({"file": name[:180], "width": width, "height": height, "mode": picture.mode})
                    else:
                        self.facts["preview_truncated"] = True
            elif suffix == ".wav":
                wav = _inspect_pcm_wav(payload, name)
                self.facts["wav_count"] += 1
                self.facts["total_audio_seconds"] += wav["duration_seconds"]
                if len(self.media["wav"]) < 20:
                    self.media["wav"].append({"file": name[:180], "sample_rate_hz": wav["sample_rate_hz"],
                        "channels": wav["channels"], "sample_width_bytes": wav["sample_width_bits"] // 8,
                        "frames": wav["frame_count"], "duration_seconds": wav["duration_seconds"]})
                else:
                    self.facts["preview_truncated"] = True
            else:
                self.issue("content_not_decoded", "此文件仅核对字节与大小，未执行、解包或解析其内容", file=name, warning=True)
        except (UnicodeError, ValueError, csv.Error, RecursionError, OSError, UnidentifiedImageError, Image.DecompressionBombError):
            self.issue("invalid_or_over_limit_content", "文件编码、语法、媒体解码或检查限额不满足要求", file=name)

    def inspect(self, payload: bytes, filename: str) -> dict[str, Any]:
        suffix = Path(filename).suffix.lower()
        self.facts["format"] = "image" if suffix in IMAGE_EXTENSIONS else suffix.lstrip(".") or "unsupported"
        if suffix == ".zip":
            try:
                with zipfile.ZipFile(io.BytesIO(payload)) as bundle:
                    entries = bundle.infolist()
                    if len(entries) > MAX_ENTRIES:
                        raise ValueError("too many ZIP entries")
                    seen: set[str] = set()
                    files = []
                    total = 0
                    for entry in entries:
                        name, key = _canonical_member_name(entry.orig_filename, limit=512)
                        if any(ord(ch) < 32 or ord(ch) == 127 for ch in name):
                            raise ValueError("ZIP member contains control characters")
                        kind = _member_kind(entry)
                        if key in seen or kind in {"symlink", "special"} or entry.flag_bits & 1:
                            raise ValueError("ambiguous, linked, special or encrypted ZIP entry")
                        seen.add(key)
                        if kind == "directory":
                            continue
                        if entry.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
                            raise ValueError("unsupported ZIP compression")
                        total += entry.file_size
                        if entry.file_size > MAX_MATERIAL_BYTES or total > MAX_UNCOMPRESSED_BYTES:
                            raise ValueError("ZIP decompression size budget exceeded")
                        if entry.file_size / max(1, entry.compress_size) > MAX_COMPRESSION_RATIO:
                            raise ValueError("ZIP compression ratio budget exceeded")
                        files.append((name, entry))
                    self.names = {name for name, _ in files}
                    file_keys = {name.casefold() for name in self.names}
                    if any(parent.as_posix().casefold() in file_keys
                           for name in self.names for parent in PurePosixPath(name).parents
                           if parent.as_posix() != "."):
                        raise ValueError("ZIP file is also a parent directory")
                    self.facts.update(file_count=len(files), total_uncompressed_bytes=total,
                        extension_counts=dict(Counter(ext if ext in IMAGE_EXTENSIONS | {".csv", ".jsonl", ".ndjson", ".json", ".txt", ".md", ".wav", ".zip"} else "other" for ext in (PurePosixPath(name).suffix.lower() for name, _ in files))))
                    if not files:
                        raise ValueError("empty ZIP")
                    for name, entry in files:
                        self.file(name, _read_member(bundle, entry, max_bytes=MAX_MATERIAL_BYTES))
            except (ValueError, zipfile.BadZipFile, RuntimeError, NotImplementedError, OSError, EOFError, zlib.error):
                self.issue("unsafe_or_invalid_archive", "ZIP存在不安全路径、重复名称、链接、加密、损坏或超过解压限额；未解包或执行")
        elif suffix in {".csv", ".jsonl", ".ndjson", ".json", ".txt", ".md", ".wav"} | IMAGE_EXTENSIONS:
            self.facts.update(file_count=1, total_uncompressed_bytes=len(payload), extension_counts={suffix: 1})
            self.file(filename, payload)
        else:
            self.issue("unsupported_material_format", "材料检查支持ZIP、UTF-8 CSV/JSONL/JSON/文本、常见图片和PCM WAV")
        self.facts["duplicate_content_groups"] = sum(count > 1 for count in self.content_counts.values())
        self.facts["unique_referenced_files"] = len(self.reference_tables)
        self.facts["total_audio_seconds"] = round(self.facts["total_audio_seconds"], 6)
        if self.facts["duplicate_content_groups"]:
            self.issue("duplicate_file_content", "多个文件的字节内容完全相同；未自动删改", warning=True)
        if self.facts["duplicate_reference_count"]:
            self.issue("repeated_pairing_reference", "同一表中重复引用了相同文件，需核对标注意图", warning=True)
        if any(len(tables) > 1 for tables in self.reference_tables.values()):
            self.issue("references_shared_by_tables", "多个表引用了相同文件，可能是CSV/JSONL等价副本；后续导入需选择格式，避免重复计数", warning=True)
        report = {"facts": self.facts, "errors": self.errors, "warnings": self.warnings,
                  "error_count": self.issue_counts["errors"], "warning_count": self.issue_counts["warnings"],
                  "tables": self.tables, "media": self.media}
        if len(json.dumps(report, ensure_ascii=False).encode()) > 64 * 1024:
            self.facts["preview_truncated"] = True
            for table in self.tables:
                table["preview"] = []
                table["columns"] = table["columns"][:8]
                table["missing_counts"] = {key: value for key, value in list(table["missing_counts"].items())[:8]}
                table["columns_truncated"] = True
            for values in self.media.values():
                del values[5:]
            for table in self.tables:
                table["column_profiles"] = dict(list(table.get("column_profiles", {}).items())[:8])
                table["profiled_column_count"] = len(table["column_profiles"])
                table["profiles_truncated"] = table["column_count"] > table["profiled_column_count"]
                grouped = table.get("grouped_date_profiles", [])
                if len(grouped) > 2:
                    table["grouped_profiles_truncated"] = True
                    del grouped[2:]
                for item in grouped:
                    if len(item["groups"]) > 4:
                        item["groups_truncated"] = True
                        del item["groups"][4:]
            while len(json.dumps(report, ensure_ascii=False).encode()) > 64 * 1024 and len(self.tables) > 1:
                self.tables.pop()
        return report


class MaterialInspectionStore:
    def __init__(self, workspace_root: Path, owner_lock: Any | None = None) -> None:
        self.root = Path(workspace_root).resolve()
        self.materials = self.root / "materials"
        self.lock = owner_lock if owner_lock is not None else RLock()

    def _safe(self, path: Path) -> Path:
        if self.root not in path.absolute().parents:
            raise MaterialConflict("材料存储路径越界")
        for candidate in (path, *path.parents):
            if candidate == self.root:
                break
            if candidate.is_symlink():
                raise MaterialConflict("材料或owner存储不能使用符号链接")
        return path

    def owner(self, owner_id: str, *, writing: bool = False) -> dict[str, Any]:
        if not isinstance(owner_id, str) or not re.fullmatch(r"[\w][\w.-]{0,159}", owner_id):
            raise FileNotFoundError("材料owner不存在")
        task_path = self._safe(self.root / "tasks" / owner_id / "task.json")
        conversation_path = self._safe(self.root / "conversations" / owner_id / "conversation.json")
        path = task_path if task_path.is_file() else conversation_path
        if not path.is_file():
            raise FileNotFoundError("材料owner不存在")
        try:
            value = read_json(path)
        except (ValueError, OSError):
            raise MaterialConflict("材料owner记录无法读取") from None
        if not isinstance(value, dict) or value.get("task_id") != owner_id:
            raise MaterialConflict("材料owner身份不一致")
        if writing and value.get("archived_at_utc"):
            raise MaterialConflict("已归档任务不能上传新材料")
        return value

    @contextmanager
    def _file_lock(self, directory: Path):
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = self._safe(directory / ".lock")
        with path.open("a+b") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    @staticmethod
    def material_id(owner_id: str, request_id: str) -> str:
        return "material-" + hashlib.sha256(f"{owner_id}\0{request_id}".encode()).hexdigest()[:24]

    def upload(self, owner_id: str, payload: bytes, filename: str, request_id: str) -> tuple[dict[str, Any], bool]:
        filename, request_id = validate_metadata(filename, request_id)
        if not payload or len(payload) > MAX_MATERIAL_BYTES:
            raise ContractError("材料必须非空且不超过25MiB")
        with self.lock:
            owner = self.owner(owner_id, writing=True)
            directory = self._safe(self.materials / owner_id)
            material_id = self.material_id(owner_id, request_id)
            final = self._safe(directory / material_id)
            with self._file_lock(directory):
                if final.exists():
                    previous = self.get(owner_id, material_id)
                    if previous["file"]["sha256"] != _sha(payload) or previous["file"]["name"] != filename:
                        raise MaterialConflict("X-Request-ID已绑定不同文件或内容")
                    return previous, True
                report = _Inspector().inspect(payload, filename)
                accepted = report["error_count"] == 0
                record = {"schema_version": "0.1", "object_type": "MaterialInspection", "material_id": material_id,
                    "owner_id": owner_id, "owner_type_at_inspection": "conversation" if owner.get("record_type") == "conversation_draft" else "task",
                    "request_id": request_id, "file": {"name": filename, "bytes": len(payload), "sha256": _sha(payload), "retained": accepted},
                    "status": "inspected" if accepted else "rejected", "created_at": datetime.now(UTC).isoformat(),
                    "untrusted_content": True, "data_inspected_only": True, "dataset_imported": False,
                    "execution_authorized": False, "report": report}
                record["inspection_sha256"] = _digest(record)
                temporary = Path(tempfile.mkdtemp(prefix=".material-", dir=directory))
                try:
                    if accepted:
                        (temporary / "source.bin").write_bytes(payload)
                        (temporary / "source.bin").chmod(0o400)
                    write_json(temporary / "inspection.json", record)
                    (temporary / "inspection.json").chmod(0o600)
                    self.owner(owner_id, writing=True)
                    os.replace(temporary, final)
                finally:
                    if temporary.exists():
                        shutil.rmtree(temporary)
                return record, False

    def get(self, owner_id: str, material_id: str) -> dict[str, Any]:
        self.owner(owner_id)
        if not isinstance(material_id, str) or not MATERIAL_ID.fullmatch(material_id):
            raise FileNotFoundError("材料记录不存在")
        path = self._safe(self.materials / owner_id / material_id / "inspection.json")
        if not path.is_file():
            raise FileNotFoundError("材料记录不存在")
        try:
            record = read_json(path)
        except (ValueError, OSError):
            raise MaterialConflict("材料检查记录无法读取") from None
        if not isinstance(record, dict):
            raise MaterialConflict("材料检查记录格式不一致")
        digest = record.get("inspection_sha256")
        try:
            actual_digest = _digest({k: v for k, v in record.items() if k != "inspection_sha256"})
        except (ValueError, TypeError, RecursionError):
            raise MaterialConflict("材料检查记录格式不一致") from None
        if record.get("owner_id") != owner_id or record.get("material_id") != material_id or actual_digest != digest:
            raise MaterialConflict("材料记录身份或检查摘要不一致")
        return record

    def retained_source(
        self, owner_id: str, material_id: str, *, inspection_sha256: str | None = None,
        for_import: bool = False,
    ) -> tuple[dict[str, Any], bytes]:
        """Read only this owner's original accepted bytes and verify integrity.

        No caller-supplied path is accepted. Callers importing data must retain
        the shared workspace lock through the original gated Dataset operation.
        """
        with self.lock:
            self.owner(owner_id, writing=for_import)
            record = self.get(owner_id, material_id)
            if inspection_sha256 is not None and (
                not isinstance(inspection_sha256, str)
                or not re.fullmatch(r"[0-9a-f]{64}", inspection_sha256)
                or record["inspection_sha256"] != inspection_sha256
            ):
                raise MaterialConflict("材料检查摘要已经变化或身份不匹配，请刷新后重试")
            if record["status"] != "inspected" or record["file"].get("retained") is not True:
                raise MaterialConflict("材料检查未通过，不能作为训练数据复用")
            path = self._safe(self.materials / owner_id / material_id / "source.bin")
            try:
                descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
                with os.fdopen(descriptor, "rb") as handle:
                    source_stat = os.fstat(handle.fileno())
                    if not stat.S_ISREG(source_stat.st_mode) or source_stat.st_size != record["file"]["bytes"] or not 0 < source_stat.st_size <= MAX_MATERIAL_BYTES:
                        raise MaterialConflict("已保存材料的文件类型或大小与检查回执不一致")
                    payload = handle.read(MAX_MATERIAL_BYTES + 1)
            except (FileNotFoundError, OSError):
                raise MaterialConflict("已保存材料无法读取，请重新上传") from None
            if len(payload) != record["file"]["bytes"] or _sha(payload) != record["file"]["sha256"]:
                raise MaterialConflict("已保存材料内容与检查回执不一致")
            return record, payload

    def csv_schema(self, owner_id: str, material_id: str) -> dict[str, Any]:
        record, payload = self.retained_source(owner_id, material_id)
        if Path(record["file"]["name"]).suffix.lower() != ".csv":
            raise ContractError("只有已检查的独立CSV文件可读取表头")
        text = payload.decode("utf-8-sig")
        try:
            delimiter = csv.Sniffer().sniff(text[:8192], delimiters=",;\t|").delimiter
        except csv.Error:
            delimiter = ","
        columns = next(csv.reader(io.StringIO(text, newline=""), delimiter=delimiter, strict=True), [])
        columns = [value.strip() for value in columns]
        if not columns or len(columns) > MAX_COLUMNS or len(set(columns)) != len(columns):
            raise MaterialConflict("已保存CSV表头与检查结构不一致")
        return {"owner_id": owner_id, "material_id": material_id,
            "inspection_sha256": record["inspection_sha256"], "columns": columns, "delimiter": delimiter,
            "untrusted_content": True, "data_inspected_only": True,
            "dataset_imported": False, "execution_authorized": False}

    def receipt(self, owner_id: str, request_id: str) -> dict[str, Any]:
        if not isinstance(request_id, str) or not REQUEST_ID.fullmatch(request_id):
            raise ContractError("request_id格式非法")
        record = self.get(owner_id, self.material_id(owner_id, request_id))
        if record.get("request_id") != request_id:
            raise MaterialConflict("材料回执请求身份不一致")
        return record

    def list(self, owner_id: str) -> list[dict[str, Any]]:
        self.owner(owner_id)
        directory = self._safe(self.materials / owner_id)
        if not directory.exists():
            return []
        records = [self.get(owner_id, path.name) for path in directory.iterdir() if MATERIAL_ID.fullmatch(path.name)]
        return sorted(records, key=lambda item: (item["created_at"], item["material_id"]))

    def summary(self, owner_id: str) -> dict[str, Any]:
        records = self.list(owner_id)
        latest = records[-1] if records else None
        return {"count": len(records), "latest_material_id": latest["material_id"] if latest else None,
            "latest_status": latest["status"] if latest else None,
            "latest": ({key: latest[key] for key in ("material_id", "file", "status", "created_at")} | {
                "report": {key: latest["report"][key] for key in ("facts", "error_count", "warning_count")}}
                if latest else None),
            "untrusted_content": True, "data_inspected_only": True, "dataset_imported": False, "execution_authorized": False}

    @staticmethod
    def brief(record: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in record.items() if key != "report"} | {
            "report": {key: record["report"][key] for key in ("facts", "error_count", "warning_count")},
            "detail_available": True,
        }

    @staticmethod
    def agent_detail(record: dict[str, Any]) -> dict[str, Any]:
        """Compact table-scoped facts; never raw rows or an unbounded preview.

        This projection does not alter the immutable source report or its SHA.
        All column counts remain under their own named table and row count.
        """
        report = record["report"]
        result = MaterialInspectionStore.brief(record)
        result["report_projection"] = "agent_facts"
        facts = dict(report["facts"])
        has_references = any(set(str(key).lower() for key in table.get("columns", [])) & REFERENCE_COLUMNS for table in report["tables"])
        media_pairing_applicable = bool(facts.get("image_count") or facts.get("wav_count") or has_references)
        if not media_pairing_applicable:
            for key in ("paired_reference_count", "missing_reference_count", "duplicate_reference_count", "conflicting_annotation_count", "unique_referenced_files"):
                facts.pop(key, None)
        elif "conflicting_annotation_count" in facts:
            facts["conflicting_media_reference_annotation_count"] = facts.pop("conflicting_annotation_count")
        checks = ["decoding_and_structure", "column_missingness", "exact_duplicate_rows", "bounded_column_statistics"]
        if facts.get("image_count") or facts.get("wav_count"):
            checks.append("media_decoding")
        if media_pairing_applicable and facts.get("format") == "zip":
            checks.append("provided_file_reference_consistency")
        result["report"] = {"facts": facts, "error_count": report["error_count"], "warning_count": report["warning_count"],
            "errors": report["errors"], "warnings": report["warnings"], "media_pairing": "applicable" if media_pairing_applicable else "not_applicable",
            "checks_performed": checks,
            "not_checked": ["derived_field_semantic_consistency", "annotation_semantics", "train_test_split_leakage", "training_sufficiency", "model_quality"],
            "profile_scope": "observed_structure_only_not_semantic_accuracy_or_training_sufficiency", "range_encoding": "single_value_if_constant_otherwise_min_max_pair", "tables": []}
        for table in report["tables"]:
            selected = {key: table[key] for key in ("file", "row_count", "columns", "duplicate_row_count")}
            selected["missing_counts"] = {key: value for key, value in table.get("missing_counts", {}).items() if value}
            if table.get("columns_truncated"):
                selected["columns_truncated"] = True
            profiles = {}
            for column, raw in table.get("column_profiles", {}).items():
                non_empty = raw.get("non_empty_count")
                if not isinstance(non_empty, int) or not 0 <= non_empty <= table["row_count"]:
                    selected["profiles_omitted_for_invalid_counts"] = True
                    continue
                value = {"non_empty_count": non_empty, "distinct_count": raw["distinct_count"]}
                if raw.get("distinct_count_is_lower_bound"):
                    value["distinct_count_is_lower_bound"] = True
                for source, target in (("text_length", "text_length"), ("numeric", "numeric")):
                    typed = raw.get(source, {})
                    if typed.get("count"):
                        value[target] = typed["min"] if typed["min"] == typed["max"] else [typed["min"], typed["max"]]
                        if typed["count"] != non_empty:
                            value[f"{target}_count"] = typed["count"]
                dates = raw.get("iso_date", {})
                if dates.get("count"):
                    value["iso_date"] = {key: dates[key] for key in ("min", "max", "distinct_count", "missing_calendar_days", "gap_count", "max_gap_days") if dates.get(key) is not None}
                    if dates["count"] != non_empty:
                        value["iso_date"]["count"] = dates["count"]
                    if dates.get("distinct_count_is_lower_bound"):
                        value["iso_date"]["distinct_count_is_lower_bound"] = True
                profiles[column] = value
            if profiles:
                selected["column_profiles"] = profiles
            if table.get("profiles_truncated"):
                selected["profiles_truncated"] = True
            grouped = []
            for raw in table.get("grouped_date_profiles", []):
                item = {key: raw[key] for key in ("group_column", "date_column", "group_count", "analyzed_row_count", "missing_pair_count", "duplicate_pair_count", "pair_unique")}
                if raw.get("duplicate_pair_count_is_lower_bound"):
                    item["duplicate_pair_count_is_lower_bound"] = True
                # Non-unique alternatives such as weekday buckets are not
                # independent series; per-bucket date gaps would be misleading.
                if raw.get("pair_unique") is True:
                    item["groups"] = [{"group_index": group["group_index"], "row_count": group["row_count"],
                        "date_coverage": {key: group["date_coverage"][key] for key in ("min", "max", "distinct_count", "missing_calendar_days") if group["date_coverage"].get(key) is not None}}
                        for group in raw["groups"]]
                    if raw.get("groups_truncated"):
                        item["groups_truncated"] = True
                grouped.append(item)
            if grouped:
                selected["grouped_date_profiles"] = grouped
            result["report"]["tables"].append(selected)
        media = {}
        for kind, count_key, fields in (("images", "image_count", ("width", "height", "mode")), ("wav", "wav_count", ("sample_rate_hz", "channels", "sample_width_bytes"))):
            samples = report["media"][kind]
            if not facts.get(count_key):
                continue
            specs = Counter(tuple(item[field] for field in fields) for item in samples)
            media[kind] = {"total_count": facts[count_key], "sampled_count": len(samples), "sample_complete": len(samples) == facts[count_key],
                "specifications": [{**dict(zip(fields, values)), "sample_count": count} for values, count in specs.items()]}
        result["report"]["media"] = media
        return result

    def briefs(self, owner_id: str) -> list[dict[str, Any]]:
        return [self.brief(item) for item in self.list(owner_id)[-20:]]
