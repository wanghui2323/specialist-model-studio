from __future__ import annotations

import json
import platform
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import sklearn

from .contracts import TaskContract, load_contract
from .io_utils import read_json, sha256_file, write_json
from .recipes import digit_classification
from .state import RunState


def _safe_slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", value).strip("-.")
    return slug or "model-run"


def _default_run_id(task_id: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{_safe_slug(task_id)}"


def _learning_report(contract: dict[str, Any], metrics: dict[str, Any]) -> str:
    candidates = "\n".join(
        f"- `{name}`：validation Macro-F1 {values['macro_f1']:.4f}"
        for name, values in metrics["validation_candidates"].items()
    )
    stresses = "\n".join(
        f"- `{name}`：Accuracy {values['accuracy']:.4f}，最差类别Recall {values['worst_class_recall']:.4f}"
        for name, values in metrics["stress_tests"].items()
    )
    failed = [
        name
        for name, passed in metrics["gate_checks"].items()
        if name != "all_offline_gates_passed" and not passed
    ]
    gate_summary = "全部通过" if not failed else f"未通过：{', '.join(failed)}"
    return f"""# Learning Report

## 这次任务是什么

{contract['business_goal']}

Harness使用 `{contract['recipe']}` Recipe。当前任务是多类别分类：输入固定长度的像素特征，输出0—9中的一个类别。

## 为什么需要三份数据

- 训练集用于拟合候选模型；
- 验证集用于比较候选模型，决定谁胜出；
- 测试集不参与选择，只在最终模型确定后检查未知样本表现。

本次切分为训练 {metrics['split_counts']['train']}、验证 {metrics['split_counts']['validation']}、测试 {metrics['split_counts']['test']}。

## Agent比较了什么

{candidates}

胜出模型是 `{metrics['selected_model']}`。选择依据是合同中冻结的验证集Macro-F1，而不是最终测试集分数。

## 最终结果怎样理解

- Clean Accuracy：{metrics['clean_test']['accuracy']:.4f}
- Clean Macro-F1：{metrics['clean_test']['macro_f1']:.4f}
- Worst-class Recall：{metrics['clean_test']['worst_class_recall']:.4f}
- Model size：{metrics['model_size_mb']:.4f} MB
- Single-sample p95：{metrics['latency']['p95_ms']:.4f} ms
- Offline gates：{gate_summary}

Accuracy看整体答对比例；Macro-F1让每个数字类别获得相同权重；Worst-class Recall直接暴露最容易漏掉的类别。

## 为什么高分仍然不能直接上线

{stresses}

压力测试通过人为加入噪声或移动像素，检查输入分布变化时模型是否脆弱。它们只负责暴露风险，不代表真实业务中的发生概率，也不会被Agent用来自动修改用户冻结的门槛。

## 人还需要决定什么

- 真实任务中的错误代价和标签语义；
- 客户数据是否授权、是否代表真实设备和环境；
- 哪些失败切片必须进入独立发布集；
- 何时进入影子测试、灰度和生产发布。

这份报告帮助用户理解本次运行，但不把教学实验包装成生产验收。
"""


def _write_manifest(
    run_dir: Path,
    contract: TaskContract,
    artifact_dir: Path,
) -> dict[str, Any]:
    artifacts = {
        path.name: {
            "sha256": sha256_file(path),
            "bytes": path.stat().st_size,
        }
        for path in sorted(artifact_dir.iterdir())
        if path.is_file()
    }
    manifest = {
        "schema_version": "0.1",
        "task_id": contract.task_id,
        "recipe": contract.recipe,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "python": sys.version,
        "platform": platform.platform(),
        "dependencies": {
            "numpy": np.__version__,
            "scikit_learn": sklearn.__version__,
            "joblib": joblib.__version__,
        },
        "contract_snapshot_sha256": sha256_file(run_dir / "task_contract.json"),
        "artifacts": artifacts,
        "reproduce": "small-model-harness run <task_contract.json>",
    }
    write_json(run_dir / "run_manifest.json", manifest)
    return manifest


def run_task(
    contract_path: str | Path,
    runs_dir: str | Path = "runs",
    run_id: str | None = None,
) -> Path:
    contract = load_contract(contract_path)
    resolved_runs_dir = Path(runs_dir).expanduser().resolve()
    selected_run_id = _safe_slug(run_id or _default_run_id(contract.task_id))
    run_dir = resolved_runs_dir / selected_run_id
    if run_dir.exists():
        raise FileExistsError(f"run directory already exists: {run_dir}")
    run_dir.mkdir(parents=True)
    state = RunState(run_dir, contract.task_id, selected_run_id)
    try:
        state.transition("preflight")
        write_json(run_dir / "task_contract.json", contract.raw)
        state.event(
            "preflight_completed",
            {
                "recipe": contract.recipe,
                "mode": contract.mode,
                "candidate_count": len(
                    contract.raw["model_selection"]["candidates"]
                ),
            },
        )

        state.transition("training")
        training = digit_classification.train(contract.raw)
        state.event(
            "model_selected",
            {
                "selected_model": training.selected_name,
                "selection_metric": "validation_macro_f1",
            },
        )

        state.transition("evaluating")
        evaluation = digit_classification.evaluate(training, contract.raw)
        state.event(
            "evaluation_completed",
            {
                "clean_test_accuracy": evaluation.metrics["clean_test"]["accuracy"],
                "stress_tests": list(evaluation.metrics["stress_tests"]),
            },
        )

        state.transition("packaging")
        artifact_dir = run_dir / "artifacts"
        metrics = digit_classification.package(
            training, evaluation, contract.raw, artifact_dir
        )
        (artifact_dir / "learning_report.md").write_text(
            _learning_report(contract.raw, metrics),
            encoding="utf-8",
        )
        manifest = _write_manifest(run_dir, contract, artifact_dir)
        state.event(
            "artifacts_packaged",
            {
                "artifact_count": len(manifest["artifacts"]),
                "offline_gates_passed": metrics["gate_checks"][
                    "all_offline_gates_passed"
                ],
            },
        )
        state.transition(
            "completed",
            offline_gates_passed=metrics["gate_checks"][
                "all_offline_gates_passed"
            ],
        )
        return run_dir
    except Exception as exc:
        state.fail(f"{type(exc).__name__}: {exc}")
        raise


def verify_run(run_dir: str | Path, deep: bool = False) -> dict[str, Any]:
    resolved = Path(run_dir).expanduser().resolve()
    manifest = read_json(resolved / "run_manifest.json")
    state = read_json(resolved / "run_state.json")
    errors: list[str] = []
    if state.get("status") != "completed":
        errors.append(f"run status is {state.get('status')}, expected completed")
    contract_path = resolved / "task_contract.json"
    if sha256_file(contract_path) != manifest["contract_snapshot_sha256"]:
        errors.append("task contract hash mismatch")
    artifact_dir = resolved / "artifacts"
    for name, expected in manifest["artifacts"].items():
        path = artifact_dir / name
        if not path.is_file():
            errors.append(f"missing artifact: {name}")
            continue
        if sha256_file(path) != expected["sha256"]:
            errors.append(f"artifact hash mismatch: {name}")

    metrics_path = artifact_dir / "metrics.json"
    if metrics_path.is_file():
        metrics = read_json(metrics_path)
        if not metrics["gate_checks"]["all_offline_gates_passed"]:
            errors.append("one or more offline gates failed")

    deep_verified = False
    if deep and not errors:
        # The hash checks above must pass before loading this pickle-based artifact.
        model = joblib.load(artifact_dir / "model.joblib")
        reference = np.load(artifact_dir / "test_reference.npz")
        actual = model.predict(reference["X"])
        if not np.array_equal(actual, reference["predictions"]):
            errors.append("persisted model predictions do not match reference")
        else:
            deep_verified = True

    return {
        "run_dir": str(resolved),
        "ok": not errors,
        "deep_verified": deep_verified,
        "errors": errors,
        "artifact_count": len(manifest.get("artifacts", {})),
    }


def initialize_workspace(recipe: str, output: str | Path, force: bool = False) -> Path:
    from .templates import get_template

    output_dir = Path(output).expanduser().resolve()
    contract_path = output_dir / "task_contract.json"
    if contract_path.exists() and not force:
        raise FileExistsError(f"contract already exists: {contract_path}")
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(contract_path, get_template(recipe))
    return contract_path
