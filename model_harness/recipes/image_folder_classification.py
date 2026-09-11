from __future__ import annotations

import csv
import shutil
import time
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import joblib
import numpy as np
from PIL import Image, ImageOps
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression, SGDClassifier
from sklearn.metrics import accuracy_score, confusion_matrix, f1_score, recall_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from ..data_adapters import verify_training_dataset_integrity
from ..io_utils import read_json, write_json
from ..huggingface_assets import TrainingModelAsset
from ..model_assets import ModelAsset, ModelAssetFile
from ..onnx_image_features import OnnxImageFeatureExtractor
from ..plugin_api import StrategyProposal


@dataclass
class TrainingContext:
    X: np.ndarray
    y: np.ndarray
    relative_paths: list[str]
    absolute_paths: list[Path]
    train_idx: np.ndarray
    validation_idx: np.ndarray
    test_idx: np.ndarray
    selected_name: str
    final_model: Any
    validation_results: dict[str, dict[str, Any]]
    labels: list[str]
    image_size: int
    class_weight_balanced: bool
    onnx_extractor: OnnxImageFeatureExtractor | None
    onnx_timings_ms: list[float]
    onnx_provenance: dict[str, Any] | None


@dataclass
class EvaluationContext:
    prediction: np.ndarray
    metrics: dict[str, Any]
    failure_samples: list[dict[str, Any]]


def extract_image_feature(path: str | Path, image_size: int) -> np.ndarray:
    with Image.open(path) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
        resized = image.resize((image_size, image_size), Image.Resampling.BILINEAR)
        pixels = np.asarray(resized, dtype=np.float32) / 255.0
    gray = (
        pixels[:, :, 0] * 0.299
        + pixels[:, :, 1] * 0.587
        + pixels[:, :, 2] * 0.114
    )
    gradient_y, gradient_x = np.gradient(gray)
    color_stats = np.concatenate(
        [pixels.mean(axis=(0, 1)), pixels.std(axis=(0, 1))]
    )
    return np.concatenate(
        [
            pixels.reshape(-1),
            gradient_x.reshape(-1),
            gradient_y.reshape(-1),
            color_stats,
        ]
    ).astype(np.float32)


def training_model_asset_from_binding(binding: dict[str, Any]) -> TrainingModelAsset:
    if not isinstance(binding, dict):
        raise ValueError("model_asset must be an object")
    root = Path(str(binding.get("root", ""))).expanduser().resolve()
    raw_files = binding.get("files")
    if not root.is_dir() or not isinstance(raw_files, list) or not raw_files:
        raise ValueError("model_asset files are unavailable")
    files = tuple(
        ModelAssetFile(
            relative_path=str(item["path"]),
            size_bytes=int(item["size_bytes"]),
            sha256=str(item["sha256"]),
        )
        for item in raw_files
    )
    asset = ModelAsset(
        asset_id=str(binding.get("asset_id", "")),
        provider=str(binding.get("provider", "")),
        repo_id=str(binding.get("repository", "")),
        requested_revision=str(binding.get("requested_revision", "")),
        resolved_commit=str(binding.get("resolved_commit", "")),
        license=str(binding.get("license", "unknown")),
        security_status=str(binding.get("security_status", "")),
        allow_patterns=tuple(item.relative_path for item in files),
        files=files,
        manifest_sha256=str(binding.get("manifest_sha256", "")),
        status="active",
        created_at=str(binding.get("created_at", "contract-bound")),
    )
    pairs = tuple((item.relative_path, root / item.relative_path) for item in files)
    return TrainingModelAsset(asset=asset, root=root, files=pairs)


def _features(
    path: Path,
    image_size: int,
    extractor: OnnxImageFeatureExtractor | None,
) -> tuple[np.ndarray, float | None, dict[str, Any] | None]:
    handcrafted = extract_image_feature(path, image_size)
    if extractor is None:
        return handcrafted, None, None
    result = extractor.extract(path)
    return (
        np.concatenate([result.features, handcrafted]).astype(np.float32),
        result.inference_ms,
        result.provenance.to_dict(),
    )


def extract_packaged_image_feature(
    image_path: str | Path,
    bundle_dir: str | Path,
) -> np.ndarray:
    """Reproduce the exact packaged feature path for a new image."""

    root = Path(bundle_dir).expanduser().resolve()
    bundle = joblib.load(root / "model.joblib")
    image_size = int(bundle["image_size"])
    if bundle.get("feature_version") != "hf-onnx-plus-rgb-gradient-v1":
        return extract_image_feature(image_path, image_size)
    descriptor = read_json(root / "model_asset_provenance.json")
    provenance = descriptor["provenance"]
    base_model = root / "base_model"
    binding = {
        "asset_id": provenance["model_asset_id"],
        "provider": provenance["provider"],
        "repository": provenance["repo_id"],
        "requested_revision": provenance["requested_revision"],
        "resolved_commit": provenance["resolved_commit"],
        "license": "see model card",
        "manifest_sha256": provenance["manifest_sha256"],
        "security_status": "verified",
        "root": str(base_model),
        "files": [
            {
                "path": "model.onnx",
                "size_bytes": (base_model / "model.onnx").stat().st_size,
                "sha256": provenance["model_sha256"],
            },
            {
                "path": "config.json",
                "size_bytes": (base_model / "config.json").stat().st_size,
                "sha256": provenance["config_sha256"],
            },
        ],
    }
    extractor = OnnxImageFeatureExtractor(training_model_asset_from_binding(binding))
    feature, _, _ = _features(Path(image_path), image_size, extractor)
    return feature


def classification_metrics(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    labels: list[str],
) -> dict[str, Any]:
    recalls = recall_score(
        y_true,
        y_pred,
        labels=labels,
        average=None,
        zero_division=0,
    )
    return {
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "macro_f1": float(f1_score(y_true, y_pred, labels=labels, average="macro", zero_division=0)),
        "worst_class_recall": float(np.min(recalls)),
        "per_class_recall": {
            label: float(value) for label, value in zip(labels, recalls, strict=True)
        },
    }


def _split_indices(
    y: np.ndarray,
    labels: list[str],
    split: dict[str, float],
    seed: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    train: list[int] = []
    validation: list[int] = []
    test: list[int] = []
    for label in labels:
        indices = np.flatnonzero(y == label)
        rng.shuffle(indices)
        test_count = max(1, int(round(len(indices) * float(split["test"]))))
        validation_count = max(1, int(round(len(indices) * float(split["validation"]))))
        if test_count + validation_count > len(indices) - 2:
            overflow = test_count + validation_count - (len(indices) - 2)
            validation_count = max(1, validation_count - overflow)
        if test_count + validation_count > len(indices) - 2:
            raise ValueError(f"类别 {label} 的样本不足以完成三段划分")
        test.extend(indices[:test_count].tolist())
        validation.extend(indices[test_count : test_count + validation_count].tolist())
        train.extend(indices[test_count + validation_count :].tolist())
    return (
        np.asarray(sorted(train), dtype=np.int64),
        np.asarray(sorted(validation), dtype=np.int64),
        np.asarray(sorted(test), dtype=np.int64),
    )


def _build_candidates(seed: int, balanced: bool) -> dict[str, Any]:
    class_weight = "balanced" if balanced else None
    return {
        "most_frequent_baseline": DummyClassifier(strategy="most_frequent"),
        "logistic_regression": Pipeline(
            [
                ("scale", StandardScaler()),
                (
                    "model",
                    LogisticRegression(
                        max_iter=1200,
                        solver="lbfgs",
                        class_weight=class_weight,
                        random_state=seed,
                    ),
                ),
            ]
        ),
        "linear_hinge_sgd": Pipeline(
            [
                ("scale", StandardScaler()),
                (
                    "model",
                    SGDClassifier(
                        loss="hinge",
                        alpha=0.0001,
                        class_weight=class_weight,
                        random_state=seed,
                        tol=1e-3,
                        max_iter=2_000,
                    ),
                ),
            ]
        ),
        "random_forest": RandomForestClassifier(
            n_estimators=180,
            min_samples_leaf=1,
            class_weight=class_weight,
            random_state=seed,
            n_jobs=1,
        ),
    }


def train(contract: dict[str, Any]) -> TrainingContext:
    verify_training_dataset_integrity(contract["dataset"])
    dataset = contract["dataset"]
    root = Path(dataset["root"]).expanduser().resolve()
    manifest = read_json(Path(dataset["manifest_path"]))
    samples = manifest["samples"]
    image_size = int(contract.get("recipe_options", {}).get("image_size", 24))
    absolute_paths = [root / item["relative_path"] for item in samples]
    relative_paths = [item["relative_path"] for item in samples]
    model_asset = contract.get("model_asset")
    onnx_extractor = (
        OnnxImageFeatureExtractor(training_model_asset_from_binding(model_asset))
        if isinstance(model_asset, dict)
        else None
    )
    feature_rows: list[np.ndarray] = []
    onnx_timings_ms: list[float] = []
    onnx_provenance: dict[str, Any] | None = None
    for path in absolute_paths:
        feature, inference_ms, provenance = _features(path, image_size, onnx_extractor)
        feature_rows.append(feature)
        if inference_ms is not None:
            onnx_timings_ms.append(inference_ms)
        if provenance is not None:
            onnx_provenance = provenance
    X = np.vstack(feature_rows)
    y = np.asarray([item["label"] for item in samples], dtype=str)
    labels = sorted({str(value) for value in y})
    seed = int(dataset["random_seed"])
    train_idx, validation_idx, test_idx = _split_indices(
        y,
        labels,
        dataset["split"],
        seed,
    )
    balanced = bool(contract.get("recipe_options", {}).get("class_weight_balanced", False))
    candidates = _build_candidates(seed, balanced)
    requested = contract["model_selection"]["candidates"]
    validation_results: dict[str, dict[str, Any]] = {}
    for name in requested:
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
        ),
    )
    final_model = deepcopy(candidates[selected_name])
    final_indices = np.concatenate([train_idx, validation_idx])
    final_model.fit(X[final_indices], y[final_indices])
    return TrainingContext(
        X=X,
        y=y,
        relative_paths=relative_paths,
        absolute_paths=absolute_paths,
        train_idx=train_idx,
        validation_idx=validation_idx,
        test_idx=test_idx,
        selected_name=selected_name,
        final_model=final_model,
        validation_results=validation_results,
        labels=labels,
        image_size=image_size,
        class_weight_balanced=balanced,
        onnx_extractor=onnx_extractor,
        onnx_timings_ms=onnx_timings_ms,
        onnx_provenance=onnx_provenance,
    )


def _latency(context: TrainingContext) -> dict[str, Any]:
    samples: list[float] = []
    selected = context.test_idx[: min(100, len(context.test_idx))]
    for index in selected:
        started = time.perf_counter_ns()
        feature, _, _ = _features(
            context.absolute_paths[int(index)],
            context.image_size,
            context.onnx_extractor,
        )
        context.final_model.predict(feature.reshape(1, -1))
        samples.append((time.perf_counter_ns() - started) / 1_000_000)
    return {
        "median_ms": float(np.median(samples)),
        "p95_ms": float(np.percentile(samples, 95)),
        "max_ms": float(np.max(samples)),
        "measurement_note": "本机同步执行图片读取、缩放、特征提取和单样本predict，不是生产网络SLA",
    }


def evaluate(context: TrainingContext, contract: dict[str, Any]) -> EvaluationContext:
    prediction = context.final_model.predict(context.X[context.test_idx])
    clean = classification_metrics(
        context.y[context.test_idx],
        prediction,
        context.labels,
    )
    report = read_json(Path(contract["dataset"]["report_path"]))
    limit = int(contract.get("diagnostics", {}).get("failure_sample_limit", 24))
    failures: list[dict[str, Any]] = []
    for index, predicted in zip(context.test_idx, prediction, strict=True):
        actual = str(context.y[index])
        if actual != str(predicted):
            failures.append(
                {
                    "relative_path": context.relative_paths[int(index)],
                    "actual": actual,
                    "predicted": str(predicted),
                }
            )
        if len(failures) >= limit:
            break
    metrics = {
        "task_id": contract["task_id"],
        "recipe": contract["recipe"],
        "selected_model": context.selected_name,
        "split_counts": {
            "train": int(len(context.train_idx)),
            "validation": int(len(context.validation_idx)),
            "test": int(len(context.test_idx)),
        },
        "training": {
            "image_size": context.image_size,
            "feature_count": int(context.X.shape[1]),
            "class_weight_balanced": context.class_weight_balanced,
            "feature_source": (
                "huggingface_onnx_plus_rgb_gradient_v1"
                if context.onnx_extractor is not None
                else "rgb_gradient_v1"
            ),
            "model_asset": context.onnx_provenance,
            "onnx_runtime": (
                {
                    "provider": "CPUExecutionProvider",
                    "init_ms": context.onnx_extractor.init_ms,
                    "sample_count": len(context.onnx_timings_ms),
                    "inference_total_ms": float(sum(context.onnx_timings_ms)),
                    "inference_p50_ms": float(np.median(context.onnx_timings_ms)),
                    "inference_p95_ms": float(np.percentile(context.onnx_timings_ms, 95)),
                }
                if context.onnx_extractor is not None and context.onnx_timings_ms
                else None
            ),
        },
        "dataset": {
            "dataset_id": report["dataset_id"],
            "fingerprint_sha256": report["fingerprint_sha256"],
            "total_images": report["total_images"],
            "class_count": report["class_count"],
            "class_counts": report["class_counts"],
            "minimum_class_count": report["minimum_class_count"],
            "imbalance_ratio": report["imbalance_ratio"],
        },
        "validation_candidates": context.validation_results,
        "clean_test": clean,
        "failure_count": int(np.sum(context.y[context.test_idx] != prediction)),
        "latency": _latency(context),
    }
    return EvaluationContext(prediction=prediction, metrics=metrics, failure_samples=failures)


def _gate_checks(metrics: dict[str, Any], gates: dict[str, float]) -> dict[str, bool]:
    checks = {
        "clean_test_accuracy": metrics["clean_test"]["accuracy"] >= gates["clean_test_accuracy_min"],
        "clean_test_macro_f1": metrics["clean_test"]["macro_f1"] >= gates["clean_test_macro_f1_min"],
        "clean_test_worst_class_recall": metrics["clean_test"]["worst_class_recall"] >= gates["clean_test_worst_class_recall_min"],
        "model_size_mb": metrics["model_size_mb"] <= gates["model_size_mb_max"],
        "single_sample_p95_latency_ms": metrics["latency"]["p95_ms"] <= gates["single_sample_p95_latency_ms_max"],
    }
    checks["all_offline_gates_passed"] = all(checks.values())
    return checks


def _write_confusion_matrix(path: Path, matrix: np.ndarray, labels: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["actual\\predicted", *labels])
        for label, row in zip(labels, matrix, strict=True):
            writer.writerow([label, *row.tolist()])


def _write_model_card(path: Path, contract: dict[str, Any], metrics: dict[str, Any]) -> None:
    gate_lines = "\n".join(
        f"- `{name}`: {'PASS' if passed else 'FAIL'}"
        for name, passed in metrics["gate_checks"].items()
    )
    model_asset = contract.get("model_asset") if isinstance(contract.get("model_asset"), dict) else None
    asset_lines = (
        "\n".join(
            [
                f"- Base model repository: `{model_asset['repository']}`",
                f"- Base model commit: `{model_asset['resolved_commit']}`",
                f"- Base model license: `{model_asset['license']}`",
                f"- Base model manifest: `{model_asset['manifest_sha256']}`",
                "- Feature path: pinned ONNX inference on CPU plus local RGB-gradient features",
            ]
        )
        if model_asset
        else "- Feature path: local RGB-gradient features; no external base model"
    )
    path.write_text(
        f"""# Model Card: {contract['task_id']}

## Intended use

{contract['business_goal']}

This model was trained from the locally imported dataset `{metrics['dataset']['dataset_id']}`. Offline test results are not production-release approval.

## Data and selection

- Dataset fingerprint: `{metrics['dataset']['fingerprint_sha256']}`
- Classes: {metrics['dataset']['class_count']}; images: {metrics['dataset']['total_images']}
- Split: train {metrics['split_counts']['train']}, validation {metrics['split_counts']['validation']}, test {metrics['split_counts']['test']}
- Selected model: `{metrics['selected_model']}` by validation Macro-F1
- Test Accuracy: {metrics['clean_test']['accuracy']:.4f}
- Test Macro-F1: {metrics['clean_test']['macro_f1']:.4f}
- Worst-class Recall: {metrics['clean_test']['worst_class_recall']:.4f}
- End-to-end local p95: {metrics['latency']['p95_ms']:.2f} ms
- Model size: {metrics['model_size_mb']:.3f} MB

## Model asset lineage

{asset_lines}

## Offline gates

{gate_lines}

## Known limits

- Random file-level splitting cannot prove generalization across people, devices, time periods or production sites.
- This feasibility classifier and any optional task-specific ONNX feature source are not a universal CV solution.
- Review the failure samples and a representative shadow-test set before production use.
- Load Joblib artifacts only from trusted runs after hash verification.
""",
        encoding="utf-8",
    )


def package(
    context: TrainingContext,
    evaluation: EvaluationContext,
    contract: dict[str, Any],
    artifact_dir: Path,
) -> dict[str, Any]:
    artifact_dir.mkdir(parents=True, exist_ok=False)
    model_path = artifact_dir / "model.joblib"
    joblib.dump(
        {
            "estimator": context.final_model,
            "labels": context.labels,
            "image_size": context.image_size,
            "feature_version": (
                "hf-onnx-plus-rgb-gradient-v1"
                if context.onnx_extractor is not None
                else "rgb-gradient-v1"
            ),
            "model_asset_provenance": context.onnx_provenance,
        },
        model_path,
        compress=3,
    )
    metrics = evaluation.metrics
    delivery_bytes = model_path.stat().st_size
    if context.onnx_extractor is not None:
        base_model_dir = artifact_dir / "base_model"
        base_model_dir.mkdir()
        for source in (
            context.onnx_extractor.model_path,
            context.onnx_extractor.config_path,
        ):
            target = base_model_dir / source.name
            shutil.copyfile(source, target)
            delivery_bytes += target.stat().st_size
        write_json(
            artifact_dir / "model_asset_provenance.json",
            context.onnx_extractor.describe(),
        )
    metrics["model_size_mb"] = float(delivery_bytes / (1024 * 1024))
    metrics["gate_checks"] = _gate_checks(metrics, contract["release_gates"])
    write_json(artifact_dir / "metrics.json", metrics)
    write_json(artifact_dir / "failure_samples.json", {"samples": evaluation.failure_samples})
    write_json(artifact_dir / "dataset_report.json", read_json(Path(contract["dataset"]["report_path"])))
    _write_confusion_matrix(
        artifact_dir / "confusion_matrix.csv",
        confusion_matrix(
            context.y[context.test_idx],
            evaluation.prediction,
            labels=context.labels,
        ),
        context.labels,
    )
    np.savez_compressed(
        artifact_dir / "test_reference.npz",
        X=context.X[context.test_idx],
        y=context.y[context.test_idx],
        predictions=evaluation.prediction,
    )
    _write_model_card(artifact_dir / "model_card.md", contract, metrics)
    (artifact_dir / "inference_example.py").write_text(
        """from pathlib import Path\nimport joblib\nfrom model_harness.recipes.image_folder_classification import extract_packaged_image_feature\n\nroot = Path(__file__).resolve().parent\nbundle = joblib.load(root / 'model.joblib')  # load trusted, hash-verified artifacts only\nfeature = extract_packaged_image_feature(Path('example.jpg'), root)\nprint(bundle['estimator'].predict(feature.reshape(1, -1))[0])\n""",
        encoding="utf-8",
    )
    return metrics


def learning_report(
    contract: dict[str, Any],
    metrics: dict[str, Any],
    strategies: list[StrategyProposal],
) -> str:
    candidates = "\n".join(
        f"- `{name}`：验证集 Macro-F1 {values['macro_f1']:.4f}，训练 {values['fit_seconds']:.3f}s"
        for name, values in metrics["validation_candidates"].items()
    )
    strategy_lines = "\n".join(
        f"- `{item.strategy_id}`：{item.title}（{'批准后可执行' if item.actionable else '需要补充外部条件'}）"
        for item in strategies
    )
    return f"""# Learning Report

## 任务和数据

{contract['business_goal']}

本轮读取了 {metrics['dataset']['total_images']} 张用户导入图片，共 {metrics['dataset']['class_count']} 个类别。数据指纹为 `{metrics['dataset']['fingerprint_sha256']}`，保证本轮合同、训练和结果指向同一份数据。

## Harness实际比较了什么

{candidates}

胜出模型为 `{metrics['selected_model']}`。候选模型只看训练集和验证集；测试集在选择完成后才用于本轮最终评估。

## 验收结果

- Accuracy：{metrics['clean_test']['accuracy']:.4f}
- Macro-F1：{metrics['clean_test']['macro_f1']:.4f}
- 最差类别Recall：{metrics['clean_test']['worst_class_recall']:.4f}
- 测试集失败样本：{metrics['failure_count']}
- 本地端到端p95：{metrics['latency']['p95_ms']:.2f} ms
- 离线门槛：{'全部通过' if metrics['gate_checks']['all_offline_gates_passed'] else '存在未通过项'}

## 下一轮建议

{strategy_lines}

建议不会自动覆盖当前运行。只有明确批准的可执行策略才会创建带父子关系的新运行；数据授权、标签含义、验收门槛和生产发布仍由人负责。
"""
