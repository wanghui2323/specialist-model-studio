from __future__ import annotations

import csv
import hashlib
import io
import os
import shutil
import stat
import time
import wave
import zipfile
from collections import Counter, defaultdict
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import uuid4

import joblib
import numpy as np
from scipy.fft import dct
from scipy.io import wavfile
from scipy.signal import stft
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import ExtraTreesClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, confusion_matrix, f1_score, recall_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from .data_adapters import (
    DataAdapterManifest,
    DataImportResult,
    verify_training_dataset_integrity,
)
from .errors import ContractError
from .io_utils import read_json, write_json


MAX_ARCHIVE_BYTES = 200 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 750 * 1024 * 1024
MAX_AUDIO_FILES = 20_000
MIN_SAMPLES_PER_CLASS = 6
MIN_SPEAKERS = 5
DEFAULT_SAMPLE_RATE = 16_000
DEFAULT_MIN_DURATION_SECONDS = 0.20
DEFAULT_MAX_DURATION_SECONDS = 3.00


@dataclass
class AudioTrainingContext:
    X: np.ndarray
    y: np.ndarray
    speaker_ids: np.ndarray
    relative_paths: list[str]
    absolute_paths: list[Path]
    train_idx: np.ndarray
    validation_idx: np.ndarray
    test_idx: np.ndarray
    selected_name: str
    final_model: Any
    validation_results: dict[str, dict[str, Any]]
    labels: list[str]
    sample_rate: int
    clip_seconds: float
    n_mels: int
    n_mfcc: int


@dataclass
class AudioEvaluationContext:
    prediction: np.ndarray
    metrics: dict[str, Any]
    failure_samples: list[dict[str, Any]]


def _safe_slug(value: str, fallback: str) -> str:
    selected = "".join(
        character if character.isalnum() or character in "._-" else "-"
        for character in value
    ).strip("-.")
    return selected[:80] or fallback


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


def _speaker_id(filename: str) -> str:
    """Return the Speech Commands speaker prefix without treating clips as people."""

    stem = Path(filename).stem
    if "_nohash_" in stem:
        selected = stem.split("_nohash_", 1)[0]
    elif "_" in stem:
        selected = stem.rsplit("_", 1)[0]
    else:
        selected = stem
    return _safe_slug(selected, "unknown-speaker")


def _archive_entries(
    archive: zipfile.ZipFile,
) -> list[tuple[zipfile.ZipInfo, tuple[str, ...]]]:
    candidates: list[tuple[zipfile.ZipInfo, tuple[str, ...]]] = []
    uncompressed = 0
    seen_names: set[str] = set()
    for info in archive.infolist():
        if info.is_dir():
            continue
        parts = _safe_zip_parts(info.filename)
        if parts is None or Path(parts[-1]).suffix.lower() != ".wav":
            continue
        normalized_name = "/".join(parts)
        if normalized_name in seen_names:
            raise ContractError(f"ZIP包含重复文件名：{normalized_name}")
        seen_names.add(normalized_name)
        unix_mode = info.external_attr >> 16
        if unix_mode and stat.S_ISLNK(unix_mode):
            raise ContractError(f"ZIP不允许符号链接：{info.filename}")
        if info.file_size < 0 or info.compress_size < 0:
            raise ContractError(f"ZIP文件尺寸无效：{info.filename}")
        uncompressed += int(info.file_size)
        if uncompressed > MAX_UNCOMPRESSED_BYTES:
            raise ContractError("解压后的WAV总量超过750MB安全上限")
        candidates.append((info, parts))
    if len(candidates) > MAX_AUDIO_FILES:
        raise ContractError(f"WAV数量超过{MAX_AUDIO_FILES}个安全上限")
    if not candidates:
        raise ContractError("ZIP中没有找到WAV文件")

    first_parts = {parts[0] for _, parts in candidates}
    drop_common_root = len(first_parts) == 1 and all(
        len(parts) >= 3 for _, parts in candidates
    )
    normalized: list[tuple[zipfile.ZipInfo, tuple[str, ...]]] = []
    for info, parts in candidates:
        selected = parts[1:] if drop_common_root else parts
        if len(selected) != 2:
            raise ContractError(
                "音频必须按 类别/说话人_nohash_序号.wav 组织；类别内不允许额外嵌套目录"
            )
        normalized.append((info, selected))
    return normalized


def _inspect_pcm_wav(raw: bytes) -> tuple[int, int, float, int]:
    try:
        with wave.open(io.BytesIO(raw), "rb") as source:
            if source.getcomptype() != "NONE":
                raise ValueError("WAV必须是未压缩PCM")
            channels = int(source.getnchannels())
            sample_rate = int(source.getframerate())
            frames = int(source.getnframes())
            sample_width = int(source.getsampwidth())
    except (wave.Error, EOFError) as exc:
        raise ValueError("无法解码PCM WAV") from exc
    if sample_rate <= 0 or frames <= 0:
        raise ValueError("WAV缺少有效采样")
    if sample_width not in {1, 2, 3, 4}:
        raise ValueError(f"不支持{sample_width * 8}bit PCM")
    return sample_rate, channels, frames / sample_rate, sample_width


class AudioKeywordZipAdapter:
    manifest = DataAdapterManifest(
        adapter_id="audio-keyword-class-folder-zip",
        version="0.1.0",
        description=(
            "Inspect and import labelled short PCM WAV clips for offline keyword "
            "classification; this adapter does not provide ASR or streaming detection."
        ),
        modalities=("audio",),
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
        if not payload:
            raise ContractError("上传文件为空")
        if len(payload) > MAX_ARCHIVE_BYTES:
            raise ContractError("ZIP文件超过200MB上传上限")
        if not self.supports(filename):
            raise ContractError("audio-keyword-class-folder-zip只接受ZIP文件")
        sample_rate_required = int(options.get("sample_rate", DEFAULT_SAMPLE_RATE))
        channels_required = int(options.get("channels", 1))
        min_duration = float(
            options.get("min_duration_seconds", DEFAULT_MIN_DURATION_SECONDS)
        )
        max_duration = float(
            options.get("max_duration_seconds", DEFAULT_MAX_DURATION_SECONDS)
        )
        if sample_rate_required < 8_000 or sample_rate_required > 96_000:
            raise ContractError("sample_rate必须在8000到96000之间")
        if channels_required != 1:
            raise ContractError("当前可信配方只接受单声道WAV")
        if min_duration <= 0 or max_duration <= min_duration or max_duration > 30:
            raise ContractError("音频时长边界无效")

        dataset_id = f"dataset-{uuid4().hex[:10]}"
        temporary_dir = datasets_dir / f".{dataset_id}.tmp"
        final_dir = datasets_dir / dataset_id
        files_dir = temporary_dir / "files"
        files_dir.mkdir(parents=True, exist_ok=False)
        samples: list[dict[str, Any]] = []
        rejected: list[dict[str, str]] = []
        hashes: dict[str, list[tuple[str, str]]] = defaultdict(list)
        duplicate_hashes: set[str] = set()
        duration_values: list[float] = []

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
                    previous = hashes.get(digest, [])
                    if previous:
                        if any(previous_label != label for previous_label, _ in previous):
                            raise ContractError(
                                "发现相同WAV被放入不同类别，请先修正标签冲突"
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
                    try:
                        sample_rate, channels, duration, sample_width = _inspect_pcm_wav(raw)
                        if sample_rate != sample_rate_required:
                            raise ValueError(
                                f"采样率为{sample_rate}Hz，要求{sample_rate_required}Hz"
                            )
                        if channels != channels_required:
                            raise ValueError(
                                f"声道数为{channels}，要求{channels_required}"
                            )
                        if duration < min_duration or duration > max_duration:
                            raise ValueError(
                                f"时长{duration:.3f}s不在{min_duration:.3f}-{max_duration:.3f}s内"
                            )
                    except ValueError as exc:
                        rejected.append({"path": info.filename, "reason": str(exc)})
                        continue

                    speaker_id = _speaker_id(parts[-1])
                    class_dir = files_dir / _safe_slug(label, "class")
                    class_dir.mkdir(parents=True, exist_ok=True)
                    target_name = (
                        f"{index:05d}-{_safe_slug(Path(parts[-1]).stem, 'clip')}.wav"
                    )
                    target = class_dir / target_name
                    target.write_bytes(raw)
                    relative = target.relative_to(temporary_dir).as_posix()
                    samples.append(
                        {
                            "label": label,
                            "speaker_id": speaker_id,
                            "relative_path": relative,
                            "original_path": info.filename,
                            "sha256": digest,
                            "sample_rate": sample_rate,
                            "channels": channels,
                            "sample_width_bytes": sample_width,
                            "duration_seconds": float(duration),
                        }
                    )
                    hashes[digest].append((label, info.filename))
                    duration_values.append(float(duration))

            counts = Counter(sample["label"] for sample in samples)
            if len(counts) < 2:
                raise ContractError("至少需要2个关键词类别目录")
            too_small = {
                label: count
                for label, count in counts.items()
                if count < MIN_SAMPLES_PER_CLASS
            }
            if too_small:
                details = "、".join(
                    f"{label}={count}" for label, count in sorted(too_small.items())
                )
                raise ContractError(
                    f"每类至少需要{MIN_SAMPLES_PER_CLASS}个有效WAV；当前 {details}"
                )
            speakers = sorted({sample["speaker_id"] for sample in samples})
            if len(speakers) < MIN_SPEAKERS:
                raise ContractError(
                    f"至少需要{MIN_SPEAKERS}个说话人分组；当前{len(speakers)}个"
                )
            label_speaker_counts = {
                label: len(
                    {
                        sample["speaker_id"]
                        for sample in samples
                        if sample["label"] == label
                    }
                )
                for label in counts
            }
            insufficient_speakers = {
                label: count
                for label, count in label_speaker_counts.items()
                if count < 3
            }
            if insufficient_speakers:
                raise ContractError(
                    "每个类别至少覆盖3个说话人，才能做无说话人泄漏的三段划分"
                )

            ordered_hashes = "\n".join(
                f"{item['label']}:{item['speaker_id']}:{item['sha256']}"
                for item in sorted(samples, key=lambda item: item["relative_path"])
            )
            imbalance_ratio = max(counts.values()) / min(counts.values())
            risks: list[dict[str, str]] = []
            if rejected:
                risks.append(
                    {
                        "level": "warning",
                        "message": f"{len(rejected)}个无效或重复WAV已从划分中排除",
                    }
                )
            if duplicate_hashes:
                risks.append(
                    {
                        "level": "warning",
                        "message": f"发现{len(duplicate_hashes)}组同标签重复WAV，已去重以防划分泄漏",
                    }
                )
            if imbalance_ratio >= 1.5:
                risks.append(
                    {
                        "level": "warning",
                        "message": f"最大类别是最小类别的{imbalance_ratio:.1f}倍",
                    }
                )
            if not risks:
                risks.append({"level": "ok", "message": "未发现阻断训练的数据问题"})
            report = {
                "schema_version": "0.1",
                "dataset_id": dataset_id,
                "source_filename": Path(filename).name,
                "fingerprint_sha256": hashlib.sha256(
                    ordered_hashes.encode("utf-8")
                ).hexdigest(),
                "total_audio": len(samples),
                "class_count": len(counts),
                "class_counts": dict(sorted(counts.items())),
                "minimum_class_count": min(counts.values()),
                "speaker_count": len(speakers),
                "speaker_counts_by_class": dict(sorted(label_speaker_counts.items())),
                "sample_rate": sample_rate_required,
                "channels": channels_required,
                "duration_seconds": {
                    "min": min(duration_values),
                    "max": max(duration_values),
                    "mean": float(np.mean(duration_values)),
                },
                "imbalance_ratio": float(imbalance_ratio),
                "duplicate_groups": len(duplicate_hashes),
                "cross_label_duplicate_groups": 0,
                "rejected_count": len(rejected),
                "rejected_files": rejected[:100],
                "split_group": "speaker_id from the Speech Commands filename prefix",
                "risks": risks,
                "scope": "offline labelled short-audio keyword classification; not ASR and not streaming wake-word detection",
            }
            write_json(temporary_dir / "dataset_manifest.json", {"samples": samples})
            write_json(temporary_dir / "dataset_report.json", report)
            datasets_dir.mkdir(parents=True, exist_ok=True)
            os.replace(temporary_dir, final_dir)
        except Exception:
            shutil.rmtree(temporary_dir, ignore_errors=True)
            raise

        return DataImportResult(
            report=report,
            dataset_dir=final_dir,
            contract_dataset={
                "kind": "audio_keyword_class_folder",
                "dataset_id": dataset_id,
                "root": str(final_dir),
                "manifest_path": str(final_dir / "dataset_manifest.json"),
                "report_path": str(final_dir / "dataset_report.json"),
                "fingerprint_sha256": report["fingerprint_sha256"],
                "sample_rate": sample_rate_required,
                "channels": channels_required,
                "random_seed": int(options.get("random_seed", 42)),
                "split": {"train": 0.60, "validation": 0.20, "test": 0.20},
                "group_by": "speaker_id",
                "boundary": (
                    "speaker-disjoint offline split does not prove generalization across "
                    "devices, rooms, microphones, languages, time, or streaming conditions"
                ),
            },
        )


def _pcm_to_float(path: Path) -> tuple[int, np.ndarray]:
    sample_rate, values = wavfile.read(path)
    if values.ndim != 1:
        raise ValueError("expected mono PCM WAV")
    if values.dtype == np.uint8:
        audio = (values.astype(np.float32) - 128.0) / 128.0
    elif np.issubdtype(values.dtype, np.signedinteger):
        limit = float(max(abs(np.iinfo(values.dtype).min), np.iinfo(values.dtype).max))
        audio = values.astype(np.float32) / limit
    else:
        raise ValueError("expected integer PCM WAV")
    return int(sample_rate), np.nan_to_num(audio, copy=False)


def _hz_to_mel(value: np.ndarray | float) -> np.ndarray:
    return 2595.0 * np.log10(1.0 + np.asarray(value) / 700.0)


def _mel_to_hz(value: np.ndarray | float) -> np.ndarray:
    return 700.0 * (10.0 ** (np.asarray(value) / 2595.0) - 1.0)


def _mel_filterbank(sample_rate: int, n_fft: int, n_mels: int) -> np.ndarray:
    mel_points = np.linspace(
        _hz_to_mel(60.0), _hz_to_mel(sample_rate / 2.0), n_mels + 2
    )
    bins = np.floor((n_fft + 1) * _mel_to_hz(mel_points) / sample_rate).astype(int)
    bins = np.clip(bins, 0, n_fft // 2)
    filters = np.zeros((n_mels, n_fft // 2 + 1), dtype=np.float64)
    for index in range(1, n_mels + 1):
        left, center, right = bins[index - 1 : index + 2]
        center = max(center, left + 1)
        right = max(right, center + 1)
        for position in range(left, min(center, filters.shape[1])):
            filters[index - 1, position] = (position - left) / (center - left)
        for position in range(center, min(right, filters.shape[1])):
            filters[index - 1, position] = (right - position) / (right - center)
    return filters


def extract_audio_feature(
    path: str | Path,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
    clip_seconds: float = 1.0,
    n_mels: int = 24,
    n_mfcc: int = 13,
) -> np.ndarray:
    actual_rate, audio = _pcm_to_float(Path(path))
    if actual_rate != sample_rate:
        raise ValueError(f"expected {sample_rate}Hz, received {actual_rate}Hz")
    target_size = int(round(sample_rate * clip_seconds))
    if len(audio) >= target_size:
        audio = audio[:target_size]
    else:
        audio = np.pad(audio, (0, target_size - len(audio)))
    audio = audio - float(np.mean(audio))
    peak = float(np.max(np.abs(audio)))
    if peak > 1e-9:
        audio = audio / peak
    emphasized = np.empty_like(audio)
    emphasized[0] = audio[0]
    emphasized[1:] = audio[1:] - 0.97 * audio[:-1]
    n_fft = 512
    _, _, spectrum = stft(
        emphasized,
        fs=sample_rate,
        window="hann",
        nperseg=400,
        noverlap=240,
        nfft=n_fft,
        boundary=None,
        padded=False,
    )
    power = np.abs(spectrum) ** 2
    mel_energy = _mel_filterbank(sample_rate, n_fft, n_mels) @ power
    log_mel = np.log(np.maximum(mel_energy, 1e-10))
    coefficients = dct(log_mel, type=2, axis=0, norm="ortho")[:n_mfcc]
    delta = np.diff(coefficients, axis=1, prepend=coefficients[:, :1])
    return np.concatenate(
        [
            coefficients.mean(axis=1),
            coefficients.std(axis=1),
            delta.mean(axis=1),
            delta.std(axis=1),
            log_mel.mean(axis=1),
            log_mel.std(axis=1),
            np.asarray(
                [
                    float(np.sqrt(np.mean(audio**2))),
                    float(np.mean(np.abs(np.diff(np.signbit(audio))))),
                ]
            ),
        ]
    ).astype(np.float32)


def _grouped_split_indices(
    y: np.ndarray,
    groups: np.ndarray,
    labels: list[str],
    split: dict[str, float],
    seed: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    unique_groups = sorted({str(value) for value in groups})
    if len(unique_groups) < MIN_SPEAKERS:
        raise ValueError(f"at least {MIN_SPEAKERS} speaker groups are required")
    test_count = max(1, int(round(len(unique_groups) * float(split["test"]))))
    validation_count = max(
        1, int(round(len(unique_groups) * float(split["validation"])))
    )
    if test_count + validation_count > len(unique_groups) - 1:
        raise ValueError("speaker groups are insufficient for a three-way split")
    rng = np.random.default_rng(seed)
    for _ in range(512):
        shuffled = np.asarray(unique_groups, dtype=object)
        rng.shuffle(shuffled)
        test_groups = set(shuffled[:test_count])
        validation_groups = set(
            shuffled[test_count : test_count + validation_count]
        )
        train_groups = set(shuffled[test_count + validation_count :])
        selections = []
        for selected_groups in (train_groups, validation_groups, test_groups):
            indices = np.asarray(
                [
                    index
                    for index, speaker in enumerate(groups)
                    if str(speaker) in selected_groups
                ],
                dtype=np.int64,
            )
            selections.append(np.sort(indices))
        if all({str(y[index]) for index in indices} == set(labels) for indices in selections):
            return selections[0], selections[1], selections[2]
    raise ValueError(
        "speaker-disjoint split could not preserve every label in train, validation and test"
    )


def classification_metrics(
    y_true: np.ndarray, y_pred: np.ndarray, labels: list[str]
) -> dict[str, Any]:
    recalls = recall_score(
        y_true, y_pred, labels=labels, average=None, zero_division=0
    )
    return {
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "macro_f1": float(
            f1_score(
                y_true, y_pred, labels=labels, average="macro", zero_division=0
            )
        ),
        "worst_class_recall": float(np.min(recalls)),
        "per_class_recall": {
            label: float(value) for label, value in zip(labels, recalls, strict=True)
        },
    }


def _candidates(seed: int, estimators: int) -> dict[str, Any]:
    return {
        "most_frequent_baseline": DummyClassifier(strategy="most_frequent"),
        "logistic_regression": Pipeline(
            [
                ("scale", StandardScaler()),
                (
                    "model",
                    LogisticRegression(
                        max_iter=2_000,
                        class_weight="balanced",
                        random_state=seed,
                    ),
                ),
            ]
        ),
        "extra_trees": ExtraTreesClassifier(
            n_estimators=estimators,
            class_weight="balanced",
            min_samples_leaf=1,
            random_state=seed,
            n_jobs=1,
        ),
    }


def train_audio_keyword(contract: dict[str, Any]) -> AudioTrainingContext:
    verify_training_dataset_integrity(contract["dataset"])
    dataset = contract["dataset"]
    root = Path(dataset["root"]).expanduser().resolve()
    manifest = read_json(Path(dataset["manifest_path"]))
    samples = manifest["samples"]
    relative_paths = [str(item["relative_path"]) for item in samples]
    absolute_paths = [root / path for path in relative_paths]
    labels = sorted({str(item["label"]) for item in samples})
    y = np.asarray([str(item["label"]) for item in samples], dtype=str)
    groups = np.asarray([str(item["speaker_id"]) for item in samples], dtype=str)
    options = contract.get("recipe_options", {})
    sample_rate = int(dataset["sample_rate"])
    clip_seconds = float(options.get("clip_seconds", 1.0))
    n_mels = int(options.get("n_mels", 24))
    n_mfcc = int(options.get("n_mfcc", 13))
    X = np.vstack(
        [
            extract_audio_feature(
                path,
                sample_rate=sample_rate,
                clip_seconds=clip_seconds,
                n_mels=n_mels,
                n_mfcc=n_mfcc,
            )
            for path in absolute_paths
        ]
    )
    train_idx, validation_idx, test_idx = _grouped_split_indices(
        y,
        groups,
        labels,
        dataset["split"],
        int(dataset["random_seed"]),
    )
    candidates = _candidates(
        int(dataset["random_seed"]), int(options.get("extra_trees_estimators", 160))
    )
    validation_results: dict[str, dict[str, Any]] = {}
    for name in contract["model_selection"]["candidates"]:
        model = deepcopy(candidates[name])
        started = time.perf_counter()
        model.fit(X[train_idx], y[train_idx])
        prediction = model.predict(X[validation_idx])
        result = classification_metrics(y[validation_idx], prediction, labels)
        result["fit_seconds"] = float(time.perf_counter() - started)
        validation_results[name] = result
    selected_name = max(
        validation_results,
        key=lambda name: (
            validation_results[name]["macro_f1"],
            validation_results[name]["accuracy"],
            name != "most_frequent_baseline",
        ),
    )
    final_model = deepcopy(candidates[selected_name])
    final_model.fit(
        X[np.concatenate([train_idx, validation_idx])],
        y[np.concatenate([train_idx, validation_idx])],
    )
    return AudioTrainingContext(
        X=X,
        y=y,
        speaker_ids=groups,
        relative_paths=relative_paths,
        absolute_paths=absolute_paths,
        train_idx=train_idx,
        validation_idx=validation_idx,
        test_idx=test_idx,
        selected_name=selected_name,
        final_model=final_model,
        validation_results=validation_results,
        labels=labels,
        sample_rate=sample_rate,
        clip_seconds=clip_seconds,
        n_mels=n_mels,
        n_mfcc=n_mfcc,
    )


def _latency(context: AudioTrainingContext) -> dict[str, Any]:
    values: list[float] = []
    for index in context.test_idx[: min(100, len(context.test_idx))]:
        started = time.perf_counter_ns()
        feature = extract_audio_feature(
            context.absolute_paths[int(index)],
            sample_rate=context.sample_rate,
            clip_seconds=context.clip_seconds,
            n_mels=context.n_mels,
            n_mfcc=context.n_mfcc,
        )
        context.final_model.predict(feature.reshape(1, -1))
        values.append((time.perf_counter_ns() - started) / 1_000_000)
    return {
        "median_ms": float(np.median(values)),
        "p95_ms": float(np.percentile(values, 95)),
        "max_ms": float(np.max(values)),
        "measurement_note": (
            "local synchronous WAV decode, feature extraction and one-clip predict; "
            "not a streaming or network latency SLA"
        ),
    }


def evaluate_audio_keyword(
    context: AudioTrainingContext, contract: dict[str, Any]
) -> AudioEvaluationContext:
    prediction = context.final_model.predict(context.X[context.test_idx])
    clean = classification_metrics(
        context.y[context.test_idx], prediction, context.labels
    )
    limit = int(contract.get("diagnostics", {}).get("failure_sample_limit", 24))
    failures: list[dict[str, Any]] = []
    for index, predicted in zip(context.test_idx, prediction, strict=True):
        actual = str(context.y[int(index)])
        if actual != str(predicted):
            failures.append(
                {
                    "relative_path": context.relative_paths[int(index)],
                    "speaker_id": str(context.speaker_ids[int(index)]),
                    "actual": actual,
                    "predicted": str(predicted),
                }
            )
        if len(failures) >= limit:
            break
    report = read_json(Path(contract["dataset"]["report_path"]))
    split_speakers = {
        name: sorted({str(context.speaker_ids[index]) for index in indices})
        for name, indices in (
            ("train", context.train_idx),
            ("validation", context.validation_idx),
            ("test", context.test_idx),
        )
    }
    metrics = {
        "task_id": contract["task_id"],
        "recipe": contract["recipe"],
        "scope": "offline_keyword_classification",
        "selected_model": context.selected_name,
        "selection_policy": "validation_macro_f1_only",
        "test_set_used_for_selection": False,
        "split_counts": {
            "train": int(len(context.train_idx)),
            "validation": int(len(context.validation_idx)),
            "test": int(len(context.test_idx)),
        },
        "speaker_split": {
            "group_by": "speaker_id",
            "disjoint": not (
                set(split_speakers["train"]) & set(split_speakers["validation"])
                or set(split_speakers["train"]) & set(split_speakers["test"])
                or set(split_speakers["validation"]) & set(split_speakers["test"])
            ),
            "counts": {name: len(value) for name, value in split_speakers.items()},
        },
        "training": {
            "sample_rate": context.sample_rate,
            "clip_seconds": context.clip_seconds,
            "feature": "log-mel-mfcc-summary-v1",
            "feature_count": int(context.X.shape[1]),
        },
        "dataset": {
            "dataset_id": report["dataset_id"],
            "fingerprint_sha256": report["fingerprint_sha256"],
            "total_audio": report["total_audio"],
            "class_count": report["class_count"],
            "class_counts": report["class_counts"],
            "speaker_count": report["speaker_count"],
        },
        "validation_candidates": context.validation_results,
        "clean_test": clean,
        "failure_count": int(
            np.sum(context.y[context.test_idx] != prediction)
        ),
        "latency": _latency(context),
    }
    return AudioEvaluationContext(
        prediction=prediction, metrics=metrics, failure_samples=failures
    )


def _gate_checks(metrics: dict[str, Any], gates: dict[str, float]) -> dict[str, bool]:
    checks = {
        "clean_test_accuracy": metrics["clean_test"]["accuracy"]
        >= gates["clean_test_accuracy_min"],
        "clean_test_macro_f1": metrics["clean_test"]["macro_f1"]
        >= gates["clean_test_macro_f1_min"],
        "clean_test_worst_class_recall": metrics["clean_test"][
            "worst_class_recall"
        ]
        >= gates["clean_test_worst_class_recall_min"],
        "speaker_split_disjoint": bool(metrics["speaker_split"]["disjoint"]),
        "model_size_mb": metrics["model_size_mb"] <= gates["model_size_mb_max"],
        "single_clip_p95_latency_ms": metrics["latency"]["p95_ms"]
        <= gates["single_clip_p95_latency_ms_max"],
    }
    checks["all_offline_gates_passed"] = all(checks.values())
    return checks


def _write_confusion_matrix(
    path: Path, matrix: np.ndarray, labels: list[str]
) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["actual\\predicted", *labels])
        for label, row in zip(labels, matrix, strict=True):
            writer.writerow([label, *row.tolist()])


def package_audio_keyword(
    context: AudioTrainingContext,
    evaluation: AudioEvaluationContext,
    contract: dict[str, Any],
    artifact_dir: Path,
) -> dict[str, Any]:
    artifact_dir.mkdir(parents=True, exist_ok=False)
    model_path = artifact_dir / "model.joblib"
    joblib.dump(
        {
            "estimator": context.final_model,
            "labels": context.labels,
            "sample_rate": context.sample_rate,
            "clip_seconds": context.clip_seconds,
            "n_mels": context.n_mels,
            "n_mfcc": context.n_mfcc,
            "feature_version": "log-mel-mfcc-summary-v1",
            "scope": "offline_keyword_classification",
        },
        model_path,
        compress=3,
    )
    metrics = evaluation.metrics
    metrics["model_size_mb"] = float(model_path.stat().st_size / (1024 * 1024))
    metrics["gate_checks"] = _gate_checks(metrics, contract["release_gates"])
    write_json(artifact_dir / "metrics.json", metrics)
    write_json(
        artifact_dir / "failure_samples.json",
        {"samples": evaluation.failure_samples},
    )
    write_json(
        artifact_dir / "dataset_report.json",
        read_json(Path(contract["dataset"]["report_path"])),
    )
    _write_confusion_matrix(
        artifact_dir / "confusion_matrix.csv",
        confusion_matrix(
            context.y[context.test_idx],
            evaluation.prediction,
            labels=context.labels,
        ),
        context.labels,
    )
    joblib.dump(
        {
            "X": context.X[context.test_idx],
            "y": context.y[context.test_idx],
            "predictions": evaluation.prediction,
        },
        artifact_dir / "test_reference.joblib",
        compress=3,
    )
    gate_lines = "\n".join(
        f"- `{name}`: {'PASS' if passed else 'FAIL'}"
        for name, passed in metrics["gate_checks"].items()
    )
    (artifact_dir / "model_card.md").write_text(
        f"""# Model Card: {contract['task_id']}

## Intended use

{contract['business_goal']}

This is an offline classifier for already-segmented, labelled short PCM WAV clips. It does not transcribe speech (ASR), find keyword boundaries, listen continuously, or provide a streaming wake-word detector.

## Data and selection

- Dataset fingerprint: `{metrics['dataset']['fingerprint_sha256']}`
- Clips: {metrics['dataset']['total_audio']}; classes: {metrics['dataset']['class_count']}; speakers: {metrics['dataset']['speaker_count']}
- Speaker-disjoint split: {metrics['speaker_split']['disjoint']}
- Selected model: `{metrics['selected_model']}` by validation Macro-F1; the test set was not used for selection
- Test Accuracy: {metrics['clean_test']['accuracy']:.4f}
- Test Macro-F1: {metrics['clean_test']['macro_f1']:.4f}
- Worst-class Recall: {metrics['clean_test']['worst_class_recall']:.4f}
- Local one-clip p95: {metrics['latency']['p95_ms']:.2f} ms
- Model size: {metrics['model_size_mb']:.3f} MB

## Offline gates

{gate_lines}

## Known limits

- The split prevents the same `speaker_id` prefix from appearing in multiple splits, but filenames are only a proxy for human identity.
- Offline performance does not prove robustness across microphones, rooms, background noise, accents, languages, time, or devices.
- A real wake-word product still needs streaming segmentation, false-accepts-per-hour evaluation, long negative audio, and on-device profiling.
- Review failure samples and load Joblib artifacts only from trusted, hash-verified runs.
""",
        encoding="utf-8",
    )
    (artifact_dir / "inference_example.py").write_text(
        """from pathlib import Path
import joblib
from model_harness.audio_keyword import extract_audio_feature

bundle = joblib.load('model.joblib')  # trusted artifact only
feature = extract_audio_feature(
    Path('one-segmented-clip.wav'),
    sample_rate=bundle['sample_rate'],
    clip_seconds=bundle['clip_seconds'],
    n_mels=bundle['n_mels'],
    n_mfcc=bundle['n_mfcc'],
)
print(bundle['estimator'].predict(feature.reshape(1, -1))[0])
""",
        encoding="utf-8",
    )
    return metrics


ADAPTER = AudioKeywordZipAdapter()
