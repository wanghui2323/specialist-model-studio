"""Freeze explicitly selected material bytes into disjoint generic splits.

Host operations are limited to bounded file/ZIP/UTF-8 CSV IO and hashing. Custom
parsing, preprocessing and training remain in the isolated execution bundle.
"""
from __future__ import annotations

import csv
import io
import json
import os
import shutil
import stat
import tempfile
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping

from .data_adapters import DataImportResult
from .errors import ContractError
from .generic_protocol import SPLITS, canonical_digest, safe_relative_path, validate_data_mapping
from .io_utils import read_json, sha256_file, write_json
from .material_inspection import MAX_COMPRESSION_RATIO, MAX_ENTRIES, MAX_MATERIAL_BYTES, MAX_UNCOMPRESSED_BYTES, MaterialInspectionStore
from .staged_assets import _canonical_member_name, _member_kind, _read_member

MAX_DATASET_BYTES = 256 * 1024 * 1024
MAX_DATASET_FILES = 4096


def _safe_directory(path: Path) -> Path:
    if path.is_symlink():
        raise ContractError("generic dataset paths cannot be symbolic links")
    return path


def _zip_members(payload: bytes) -> tuple[zipfile.ZipFile, dict[str, zipfile.ZipInfo]]:
    bundle = zipfile.ZipFile(io.BytesIO(payload))
    try:
        entries = bundle.infolist()
        if len(entries) > MAX_ENTRIES:
            raise ContractError("material ZIP exceeds entry limit")
        seen, files = set(), {}
        total = 0
        for entry in entries:
            name, key = _canonical_member_name(entry.orig_filename, limit=512)
            safe_relative_path(name)
            kind = _member_kind(entry)
            if key in seen or kind in {"symlink", "special"} or entry.flag_bits & 1:
                raise ContractError("material ZIP contains ambiguous, linked or encrypted members")
            seen.add(key)
            if kind == "directory":
                continue
            total += entry.file_size
            if entry.file_size > MAX_MATERIAL_BYTES or total > MAX_UNCOMPRESSED_BYTES or entry.file_size / max(1, entry.compress_size) > MAX_COMPRESSION_RATIO:
                raise ContractError("material ZIP exceeds bounded decompression limits")
            if entry.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
                raise ContractError("unsupported material ZIP compression")
            files[name] = entry
        return bundle, files
    except Exception:
        bundle.close()
        raise


def _csv(payload: bytes) -> tuple[list[str], list[list[str]], str]:
    text = payload.decode("utf-8-sig")
    if "\0" in text:
        raise ContractError("CSV contains NUL")
    try:
        delimiter = csv.Sniffer().sniff(text[:8192], delimiters=",;\t|").delimiter
    except csv.Error:
        delimiter = ","
    iterator = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter, strict=True)
    headers = next(iterator, [])
    if not headers or len(headers) > 256 or len(set(headers)) != len(headers):
        raise ContractError("CSV has invalid headers")
    rows = []
    for row in iterator:
        if not row:
            continue  # csv.DictReader used during inspection also skips blank lines.
        if len(row) != len(headers) or len(rows) >= 100_000 or (len(rows) + 1) * len(headers) > 2_000_000:
            raise ContractError("CSV row shape or inspection bounds changed")
        rows.append(row)
    if not rows:
        raise ContractError("CSV has no data rows")
    return headers, rows, delimiter


def _row_indices(selection: Any, count: int) -> list[int]:
    if selection is None:
        return list(range(count))
    if isinstance(selection, dict):
        indices = list(range(selection["start"], selection["stop"]))
    else:
        indices = list(selection)
    if not indices or indices[-1] >= count:
        raise ContractError("csv_rows references a row outside the inspected material")
    return indices


def _contract(root: Path, report: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    return {"kind": "generic_files", "dataset_id": report["dataset_id"], "root": str(root),
        "manifest_path": str(root / "dataset_manifest.json"), "report_path": str(root / "dataset_report.json"),
        "fingerprint_sha256": report["fingerprint_sha256"], "report_sha256": sha256_file(root / "dataset_report.json"),
        "splits": manifest["splits"]}


def create_generic_dataset(task_dir: Path, material_store: MaterialInspectionStore, owner_id: str, data_mapping: Any) -> DataImportResult:
    mapping = validate_data_mapping(data_mapping)
    task_dir = Path(task_dir)
    expected = material_store.root / "tasks" / owner_id
    if not task_dir.is_absolute() or ".." in task_dir.parts or not (expected / "task.json").is_file():
        raise ContractError("generic dataset requires an owned task directory")
    resolved = task_dir.resolve()
    owner_root = expected.resolve()
    if resolved != owner_root and owner_root not in resolved.parents:
        raise ContractError("generic dataset destination is outside its bound task")
    for parent in (task_dir, *task_dir.parents):
        _safe_directory(parent)
        if parent.resolve() == expected.parent.resolve():
            break
    task_dir = resolved
    with material_store.lock:
        material_store.owner(owner_id, writing=True)
        datasets = _safe_directory(task_dir / "datasets")
        datasets.mkdir(parents=True, exist_ok=True)
        temporary = Path(tempfile.mkdtemp(prefix=".generic-", dir=datasets))
        for split in SPLITS:
            (temporary / split).mkdir()
        splits: dict[str, list[dict[str, Any]]] = {split: [] for split in SPLITS}
        grouped = defaultdict(list)
        for item in mapping:
            grouped[item["material_id"]].append(item)
        sources = []
        selected_units: set[tuple[str, str]] = set()
        output_paths: set[tuple[str, str]] = set()
        content_splits: dict[str, str] = {}
        row_splits: dict[str, str] = {}
        total_bytes = file_count = duplicate_files_within_split = 0
        csv_row_counts = {split: 0 for split in SPLITS}

        def emit(split: str, relative: str, content: bytes, provenance: dict[str, Any]) -> None:
            nonlocal total_bytes, file_count, duplicate_files_within_split
            relative = safe_relative_path(relative)
            identity = (split, relative.casefold())
            if identity in output_paths:
                raise ContractError("multiple material selections collide in one split; select unique original paths")
            output_paths.add(identity)
            total_bytes += len(content)
            file_count += 1
            if total_bytes > MAX_DATASET_BYTES or file_count > MAX_DATASET_FILES:
                raise ContractError("generic dataset exceeds byte/file limits")
            import hashlib
            digest = hashlib.sha256(content).hexdigest()
            prior = content_splits.get(digest)
            if prior is not None and prior != split:
                raise ContractError("identical file content appears across train/validation/test")
            duplicate_files_within_split += prior == split
            content_splits[digest] = split
            target = temporary / split / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as handle:
                handle.write(content)
            target.chmod(0o444)
            splits[split].append({"relative_path": relative, "sha256": digest, "bytes": len(content), "source": provenance})

        try:
            for material_id, selections in grouped.items():
                digests = {item["inspection_sha256"] for item in selections}
                if len(digests) != 1:
                    raise ContractError("one material_id cannot refer to different inspection snapshots")
                record, payload = material_store.retained_source(owner_id, material_id, inspection_sha256=next(iter(digests)), for_import=True)
                sources.append({"material_id": material_id, "inspection_sha256": record["inspection_sha256"], "file_sha256": record["file"]["sha256"]})
                filename = record["file"]["name"]
                suffix = Path(filename).suffix.lower()
                if suffix == ".zip":
                    archive, members = _zip_members(payload)
                    with archive:
                        for selection in selections:
                            if "csv_rows" in selection or not (selection.get("member_paths") or selection.get("member_prefixes")):
                                raise ContractError("ZIP mappings require explicit member_paths/member_prefixes")
                            picked = set()
                            for member in selection.get("member_paths", []):
                                if member not in members:
                                    raise ContractError("selected ZIP member is missing")
                                picked.add(member)
                            for prefix in selection.get("member_prefixes", []):
                                matches = {name for name in members if name.startswith(prefix)}
                                if not matches:
                                    raise ContractError("selected ZIP prefix contains no files")
                                picked.update(matches)
                            for member in sorted(picked):
                                unit = (material_id, "member:" + member)
                                if unit in selected_units:
                                    raise ContractError("a source ZIP member is selected more than once across split mappings")
                                selected_units.add(unit)
                                content = _read_member(archive, members[member], max_bytes=MAX_MATERIAL_BYTES)
                                emit(selection["split"], member, content, {"material_id": material_id, "member_path": member})
                elif suffix == ".csv":
                    headers, rows, delimiter = _csv(payload)
                    for selection in selections:
                        if selection.get("member_paths") or selection.get("member_prefixes"):
                            raise ContractError("standalone CSV mappings use csv_rows, not ZIP selectors")
                        indices = _row_indices(selection.get("csv_rows"), len(rows))
                        for index in indices:
                            unit = (material_id, "csv_row:" + str(index))
                            if unit in selected_units:
                                raise ContractError("a source CSV row is selected more than once across split mappings")
                            selected_units.add(unit)
                            signature = canonical_digest({"headers": headers, "row": rows[index]})
                            prior = row_splits.get(signature)
                            if prior is not None and prior != selection["split"]:
                                raise ContractError("identical CSV records appear across train/validation/test")
                            row_splits[signature] = selection["split"]
                        output = io.StringIO(newline="")
                        writer = csv.writer(output, delimiter=delimiter, lineterminator="\n")
                        writer.writerow(headers)
                        writer.writerows(rows[index] for index in indices)
                        csv_row_counts[selection["split"]] += len(indices)
                        emit(selection["split"], filename, output.getvalue().encode("utf-8"), {"material_id": material_id, "csv_row_count": len(indices), "csv_row_indices_sha256": canonical_digest(indices), "selection": selection.get("csv_rows", {"start": 0, "stop": len(rows)})})
                else:
                    for selection in selections:
                        if any(field in selection for field in ("member_paths", "member_prefixes", "csv_rows")):
                            raise ContractError("member/row selectors do not apply to this standalone file")
                        unit = (material_id, "file")
                        if unit in selected_units:
                            raise ContractError("a standalone source file cannot be reused across split mappings")
                        selected_units.add(unit)
                        emit(selection["split"], filename, payload, {"material_id": material_id})
            if not splits["train"] or not splits["test"]:
                raise ContractError("train and test must contain separately selected data")
            for files in splits.values():
                files.sort(key=lambda item: item["relative_path"])
            manifest = {"schema_version": "0.1", "kind": "generic_files", "owner_id": owner_id,
                "source_materials": sorted(sources, key=lambda item: item["material_id"]), "data_mapping": mapping, "splits": splits}
            write_json(temporary / "dataset_manifest.json", manifest)
            fingerprint = sha256_file(temporary / "dataset_manifest.json")
            dataset_id = "dataset-" + fingerprint[:24]
            final = _safe_directory(datasets / dataset_id)
            counts = {split: {"file_count": len(files), "bytes": sum(item["bytes"] for item in files), "csv_row_count": csv_row_counts[split]} for split, files in splits.items()}
            report = {"schema_version": "0.1", "dataset_id": dataset_id, "kind": "generic_files", "data_adapter": "generic-files",
                "fingerprint_sha256": fingerprint, "owner_id": owner_id, "total_files": file_count, "total_bytes": total_bytes,
                "split_counts": counts, "sources": manifest["source_materials"],
                "split_policy": "explicit_immutable_material_member_or_row_selection",
                "duplicate_files_within_split": duplicate_files_within_split,
                "overlapping_source_units": 0, "cross_split_identical_file_content": 0, "cross_split_identical_csv_records": 0,
                "semantic_leakage_checked": False, "sample_counts_are_not_training_sufficiency": True,
                "execution_authorized": False}
            write_json(temporary / "dataset_report.json", report)
            if final.exists():
                existing = _contract(final, read_json(final / "dataset_report.json"), read_json(final / "dataset_manifest.json"))
                verify_generic_dataset_integrity(existing)
                if existing["fingerprint_sha256"] != fingerprint:
                    raise ContractError("generic dataset identity collides with different bytes")
                return DataImportResult(read_json(final / "dataset_report.json"), final, existing)
            material_store.owner(owner_id, writing=True)
            os.replace(temporary, final)
            return DataImportResult(report, final, _contract(final, report, manifest))
        except (zipfile.BadZipFile, UnicodeError, csv.Error, ValueError, OSError) as exc:
            if isinstance(exc, ContractError):
                raise
            raise ContractError("generic material mapping could not be safely frozen") from exc
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)


def verify_generic_dataset_integrity(dataset: Mapping[str, Any]) -> dict[str, Any]:
    try:
        if dataset.get("kind") != "generic_files":
            raise ContractError("not a generic_files dataset")
        root = Path(str(dataset["root"]))
        if not root.is_absolute() or root.is_symlink():
            raise ContractError("generic dataset root is not a safe absolute directory")
        root = root.resolve()
        manifest_path, report_path = root / "dataset_manifest.json", root / "dataset_report.json"
        if Path(str(dataset["manifest_path"])) != manifest_path or Path(str(dataset["report_path"])) != report_path or manifest_path.is_symlink() or report_path.is_symlink():
            raise ContractError("generic manifest/report paths are not owned by this dataset")
        if sha256_file(manifest_path) != dataset["fingerprint_sha256"]:
            raise ContractError("generic dataset manifest bytes changed")
        if dataset.get("report_sha256") and sha256_file(report_path) != dataset["report_sha256"]:
            raise ContractError("generic dataset report changed")
        manifest, report = read_json(manifest_path), read_json(report_path)
        if manifest.get("kind") != "generic_files" or set(manifest.get("splits", {})) != set(SPLITS) or dataset.get("splits") != manifest["splits"] or report.get("dataset_id") != dataset["dataset_id"] or report.get("fingerprint_sha256") != dataset["fingerprint_sha256"]:
            raise ContractError("generic dataset contract differs from its frozen manifest")
        total = count = 0
        all_content_splits: dict[str, str] = {}
        for split in SPLITS:
            split_root = _safe_directory(root / split)
            expected = set()
            for item in manifest["splits"][split]:
                relative = safe_relative_path(item["relative_path"])
                if relative.casefold() in expected:
                    raise ContractError("generic dataset split contains duplicate file identities")
                expected.add(relative.casefold())
                path = split_root / relative
                for parent in (path, *path.parents):
                    if parent == root:
                        break
                    _safe_directory(parent)
                info = path.stat()
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size != item["bytes"] or sha256_file(path) != item["sha256"]:
                    raise ContractError("generic dataset file identity or bytes changed")
                prior = all_content_splits.get(item["sha256"])
                if prior is not None and prior != split:
                    raise ContractError("generic dataset contains cross-split identical content")
                all_content_splits[item["sha256"]] = split
                total += info.st_size
                count += 1
            observed = set()
            directory_count = 0
            for parent, directories, files in os.walk(split_root, followlinks=False):
                directory_count += len(directories)
                if directory_count > MAX_DATASET_FILES * 4 + 16:
                    raise ContractError("generic split contains excessive undeclared directories")
                for name in directories:
                    _safe_directory(Path(parent) / name)
                for name in files:
                    path = Path(parent) / name
                    _safe_directory(path)
                    observed.add(path.relative_to(split_root).as_posix().casefold())
                    if len(observed) > len(expected):
                        raise ContractError("generic split contains undeclared files")
            if observed != expected:
                raise ContractError("generic split contains missing or undeclared files")
        if total > MAX_DATASET_BYTES or count > MAX_DATASET_FILES:
            raise ContractError("generic dataset exceeds frozen IO limits")
        return manifest
    except ContractError:
        raise
    except (KeyError, TypeError, ValueError, OSError):
        raise ContractError("generic dataset integrity could not be verified") from None


def generic_split_input_files(dataset: Mapping[str, Any], splits: Iterable[str]) -> dict[str, Path]:
    selected = tuple(splits)
    if not selected or len(set(selected)) != len(selected) or any(split not in SPLITS for split in selected):
        raise ContractError("stage inputs require explicit unique split names")
    manifest = verify_generic_dataset_integrity(dataset)
    root = Path(str(dataset["root"]))
    return {f"{split}/{item['relative_path']}": root / split / item["relative_path"] for split in selected for item in manifest["splits"][split]}
