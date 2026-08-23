from __future__ import annotations

import csv
import time
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import joblib
import numpy as np
from sklearn.compose import ColumnTransformer
from sklearn.dummy import DummyRegressor
from sklearn.ensemble import ExtraTreesRegressor, RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, r2_score, root_mean_squared_error
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from ..data_adapters import verify_training_dataset_integrity
from ..io_utils import read_json, write_json
from ..plugin_api import StrategyProposal


@dataclass
class TrainingContext:
    X: np.ndarray
    y: np.ndarray
    row_numbers: np.ndarray
    train_idx: np.ndarray
    validation_idx: np.ndarray
    test_idx: np.ndarray
    selected_name: str
    final_model: Any
    validation_results: dict[str, dict[str, Any]]
    feature_columns: list[str]
    target_column: str


@dataclass
class EvaluationContext:
    prediction: np.ndarray
    metrics: dict[str, Any]
    failure_samples: list[dict[str, Any]]


def _load_rows(contract: dict[str, Any]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    dataset = contract["dataset"]
    feature_columns = list(dataset["feature_columns"])
    target_column = str(dataset["target_column"])
    rows: list[list[Any]] = []
    targets: list[float] = []
    row_numbers: list[int] = []
    with Path(dataset["csv_path"]).open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row_number, row in enumerate(reader, start=2):
            rows.append([row.get(column, "") for column in feature_columns])
            targets.append(float(str(row[target_column]).strip()))
            row_numbers.append(row_number)
    return (
        np.asarray(rows, dtype=object),
        np.asarray(targets, dtype=np.float64),
        np.asarray(row_numbers, dtype=np.int64),
    )


def _split_indices(size: int, split: dict[str, float], seed: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    if size < 10:
        raise ValueError("表格数据不足以完成训练、验证、测试三段划分")
    indices = np.arange(size, dtype=np.int64)
    rng = np.random.default_rng(seed)
    rng.shuffle(indices)
    test_count = max(1, int(round(size * float(split["test"]))))
    validation_count = max(1, int(round(size * float(split["validation"]))))
    if test_count + validation_count > size - 2:
        raise ValueError("表格数据不足以完成训练、验证、测试三段划分")
    test_idx = np.sort(indices[:test_count])
    validation_idx = np.sort(indices[test_count : test_count + validation_count])
    train_idx = np.sort(indices[test_count + validation_count :])
    return train_idx, validation_idx, test_idx


def _preprocessor(dataset: dict[str, Any]) -> ColumnTransformer:
    feature_columns = list(dataset["feature_columns"])
    numeric = [feature_columns.index(name) for name in dataset.get("numeric_columns", [])]
    categorical = [feature_columns.index(name) for name in dataset.get("categorical_columns", [])]
    transformers: list[tuple[str, Any, list[int]]] = []
    if numeric:
        transformers.append(
            (
                "numeric",
                Pipeline(
                    [
                        ("impute", SimpleImputer(strategy="median")),
                        ("scale", StandardScaler()),
                    ]
                ),
                numeric,
            )
        )
    if categorical:
        transformers.append(
            (
                "categorical",
                Pipeline(
                    [
                        ("impute", SimpleImputer(strategy="most_frequent")),
                        (
                            "encode",
                            OneHotEncoder(handle_unknown="ignore", sparse_output=False),
                        ),
                    ]
                ),
                categorical,
            )
        )
    return ColumnTransformer(transformers=transformers, remainder="drop")


def _candidate(model: Any, dataset: dict[str, Any]) -> Pipeline:
    return Pipeline([("prepare", _preprocessor(dataset)), ("model", model)])


def _build_candidates(contract: dict[str, Any]) -> dict[str, Any]:
    seed = int(contract["dataset"]["random_seed"])
    trees = int(contract.get("recipe_options", {}).get("forest_estimators", 180))
    dataset = contract["dataset"]
    return {
        "mean_baseline": _candidate(DummyRegressor(strategy="mean"), dataset),
        "ridge": _candidate(Ridge(alpha=1.0), dataset),
        "random_forest": _candidate(
            RandomForestRegressor(
                n_estimators=trees,
                min_samples_leaf=2,
                random_state=seed,
                n_jobs=1,
            ),
            dataset,
        ),
        "extra_trees": _candidate(
            ExtraTreesRegressor(
                n_estimators=trees,
                min_samples_leaf=2,
                random_state=seed,
                n_jobs=1,
            ),
            dataset,
        ),
    }


def regression_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float]:
    return {
        "mae": float(mean_absolute_error(y_true, y_pred)),
        "rmse": float(root_mean_squared_error(y_true, y_pred)),
        "r2": float(r2_score(y_true, y_pred)),
    }


def train(contract: dict[str, Any]) -> TrainingContext:
    verify_training_dataset_integrity(contract["dataset"])
    X, y, row_numbers = _load_rows(contract)
    dataset = contract["dataset"]
    train_idx, validation_idx, test_idx = _split_indices(
        len(y), dataset["split"], int(dataset["random_seed"])
    )
    candidates = _build_candidates(contract)
    validation_results: dict[str, dict[str, Any]] = {}
    for name in contract["model_selection"]["candidates"]:
        model = deepcopy(candidates[name])
        started = time.perf_counter()
        model.fit(X[train_idx], y[train_idx])
        prediction = model.predict(X[validation_idx])
        result = regression_metrics(y[validation_idx], prediction)
        result["fit_seconds"] = float(time.perf_counter() - started)
        validation_results[name] = result
    selected_name = min(
        validation_results,
        key=lambda name: (
            validation_results[name]["mae"],
            validation_results[name]["rmse"],
        ),
    )
    final_model = deepcopy(candidates[selected_name])
    final_indices = np.concatenate([train_idx, validation_idx])
    final_model.fit(X[final_indices], y[final_indices])
    return TrainingContext(
        X=X,
        y=y,
        row_numbers=row_numbers,
        train_idx=train_idx,
        validation_idx=validation_idx,
        test_idx=test_idx,
        selected_name=selected_name,
        final_model=final_model,
        validation_results=validation_results,
        feature_columns=list(dataset["feature_columns"]),
        target_column=str(dataset["target_column"]),
    )


def _latency(context: TrainingContext) -> dict[str, Any]:
    samples: list[float] = []
    for index in context.test_idx[: min(100, len(context.test_idx))]:
        started = time.perf_counter_ns()
        context.final_model.predict(context.X[int(index)].reshape(1, -1))
        samples.append((time.perf_counter_ns() - started) / 1_000_000)
    return {
        "median_ms": float(np.median(samples)),
        "p95_ms": float(np.percentile(samples, 95)),
        "max_ms": float(np.max(samples)),
        "measurement_note": "本机同步执行单行预处理和predict，不是生产网络SLA",
    }


def evaluate(context: TrainingContext, contract: dict[str, Any]) -> EvaluationContext:
    prediction = context.final_model.predict(context.X[context.test_idx])
    clean = regression_metrics(context.y[context.test_idx], prediction)
    errors = np.abs(context.y[context.test_idx] - prediction)
    order = np.argsort(errors)[::-1]
    limit = int(contract.get("diagnostics", {}).get("failure_sample_limit", 24))
    failures: list[dict[str, Any]] = []
    for position in order[:limit]:
        source_index = int(context.test_idx[int(position)])
        failures.append(
            {
                "row_number": int(context.row_numbers[source_index]),
                "actual": float(context.y[source_index]),
                "predicted": float(prediction[int(position)]),
                "absolute_error": float(errors[int(position)]),
            }
        )
    report = read_json(Path(contract["dataset"]["report_path"]))
    metrics = {
        "task_id": contract["task_id"],
        "recipe": contract["recipe"],
        "selected_model": context.selected_name,
        "split_counts": {
            "train": int(len(context.train_idx)),
            "validation": int(len(context.validation_idx)),
            "test": int(len(context.test_idx)),
        },
        "dataset": {
            "dataset_id": report["dataset_id"],
            "fingerprint_sha256": report["fingerprint_sha256"],
            "row_count": report["row_count"],
            "feature_count": len(report["feature_columns"]),
            "target_column": report["target_column"],
        },
        "validation_candidates": context.validation_results,
        "clean_test": clean,
        "failure_count": len(failures),
        "latency": _latency(context),
    }
    return EvaluationContext(prediction=prediction, metrics=metrics, failure_samples=failures)


def _gate_checks(metrics: dict[str, Any], gates: dict[str, float]) -> dict[str, bool]:
    checks = {
        "clean_test_mae": metrics["clean_test"]["mae"] <= gates["clean_test_mae_max"],
        "clean_test_rmse": metrics["clean_test"]["rmse"] <= gates["clean_test_rmse_max"],
        "clean_test_r2": metrics["clean_test"]["r2"] >= gates["clean_test_r2_min"],
        "model_size_mb": metrics["model_size_mb"] <= gates["model_size_mb_max"],
        "single_sample_p95_latency_ms": metrics["latency"]["p95_ms"] <= gates["single_sample_p95_latency_ms_max"],
    }
    checks["all_offline_gates_passed"] = all(checks.values())
    return checks


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
            "feature_columns": context.feature_columns,
            "target_column": context.target_column,
            "task_type": "regression",
        },
        model_path,
        compress=3,
    )
    metrics = evaluation.metrics
    metrics["model_size_mb"] = float(model_path.stat().st_size / (1024 * 1024))
    metrics["gate_checks"] = _gate_checks(metrics, contract["release_gates"])
    write_json(artifact_dir / "metrics.json", metrics)
    write_json(artifact_dir / "failure_samples.json", {"samples": evaluation.failure_samples})
    write_json(
        artifact_dir / "dataset_report.json",
        read_json(Path(contract["dataset"]["report_path"])),
    )
    with (artifact_dir / "test_predictions.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["row_number", "actual", "predicted", "absolute_error"])
        for index, predicted in zip(context.test_idx, evaluation.prediction, strict=True):
            writer.writerow(
                [
                    int(context.row_numbers[int(index)]),
                    float(context.y[int(index)]),
                    float(predicted),
                    float(abs(context.y[int(index)] - predicted)),
                ]
            )
    joblib.dump(
        {
            "X": context.X[context.test_idx],
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

This local model predicts `{context.target_column}` from a user-imported CSV. Offline evaluation is not production-release approval.

## Data and selection

- Dataset fingerprint: `{metrics['dataset']['fingerprint_sha256']}`
- Rows: {metrics['dataset']['row_count']}; features: {metrics['dataset']['feature_count']}
- Selected model: `{metrics['selected_model']}` by validation MAE
- Test MAE: {metrics['clean_test']['mae']:.4f}
- Test RMSE: {metrics['clean_test']['rmse']:.4f}
- Test R2: {metrics['clean_test']['r2']:.4f}
- Local p95: {metrics['latency']['p95_ms']:.2f} ms
- Model size: {metrics['model_size_mb']:.3f} MB

## Offline gates

{gate_lines}

## Known limits

- Random row splitting cannot prove generalization across time, sites, machines or populations.
- Review high-error rows and run a domain-appropriate temporal or grouped split before production use.
- Load Joblib artifacts only from trusted runs after hash verification.
""",
        encoding="utf-8",
    )
    (artifact_dir / "inference_example.py").write_text(
        """import csv\nimport joblib\n\nbundle = joblib.load('model.joblib')  # trusted artifact only\nwith open('one-row.csv', encoding='utf-8', newline='') as handle:\n    row = next(csv.DictReader(handle))\nX = [[row.get(name, '') for name in bundle['feature_columns']]]\nprint(bundle['estimator'].predict(X)[0])\n""",
        encoding="utf-8",
    )
    return metrics


def learning_report(
    contract: dict[str, Any],
    metrics: dict[str, Any],
    strategies: list[StrategyProposal],
) -> str:
    candidates = "\n".join(
        f"- `{name}`：验证集 MAE {values['mae']:.4f}，R2 {values['r2']:.4f}，训练 {values['fit_seconds']:.3f}s"
        for name, values in metrics["validation_candidates"].items()
    )
    strategy_lines = "\n".join(
        f"- `{item.strategy_id}`：{item.title}（{'批准后可执行' if item.actionable else '需要补充外部条件'}）"
        for item in strategies
    )
    return f"""# Learning Report

## 任务和数据

{contract['business_goal']}

本轮读取 {metrics['dataset']['row_count']} 行表格数据和 {metrics['dataset']['feature_count']} 个特征，目标列为 `{metrics['dataset']['target_column']}`。数据指纹为 `{metrics['dataset']['fingerprint_sha256']}`。

## Harness实际比较了什么

{candidates}

胜出模型为 `{metrics['selected_model']}`。模型选择只使用验证集；测试集在选择完成后才打开。

## 验收结果

- MAE：{metrics['clean_test']['mae']:.4f}
- RMSE：{metrics['clean_test']['rmse']:.4f}
- R2：{metrics['clean_test']['r2']:.4f}
- 本地p95：{metrics['latency']['p95_ms']:.2f} ms
- 离线门槛：{'全部通过' if metrics['gate_checks']['all_offline_gates_passed'] else '存在未通过项'}

## 下一轮建议

{strategy_lines}
"""
