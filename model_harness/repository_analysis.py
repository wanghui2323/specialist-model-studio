from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

from .errors import HarnessError
from .model_sources import (
    SourceDocument,
    SourceSnapshot,
    evaluate_license_policy,
    verify_source_snapshot,
)


ANALYZER_VERSION = "repository-analysis/0.4"
MAX_SELECTED_DOCUMENTS = 64
MAX_SELECTED_DOCUMENT_BYTES = 256 * 1024
MAX_TOTAL_SELECTED_DOCUMENT_BYTES = 2 * 1024 * 1024

_TEXT_SUFFIXES = {
    ".cfg",
    ".ini",
    ".json",
    ".md",
    ".py",
    ".rst",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}
_TEXT_BASENAMES = {
    "dockerfile",
    "makefile",
    "pipfile",
    "pipfile.lock",
    "poetry.lock",
    "uv.lock",
}
_TRAIN_ENTRY_BASENAMES = {
    "train.py": 0.98,
    "trainer.py": 0.86,
    "finetune.py": 0.97,
    "fine_tune.py": 0.97,
    "run_train.py": 0.95,
    "run_training.py": 0.95,
    "run_glue.py": 0.95,
    "run_clm.py": 0.95,
    "run_mlm.py": 0.95,
    "main.py": 0.55,
}
_TRAINING_TEXT_SIGNALS = (
    "trainer(",
    "trainingarguments(",
    "model.fit(",
    "trainer.fit(",
    "loss.backward(",
    "optimizer.step(",
    "accelerator.prepare(",
    "torchrun ",
    "accelerate launch ",
)
_INFERENCE_ENTRY_BASENAMES = {
    "infer.py": 0.98,
    "inference.py": 0.98,
    "predict.py": 0.96,
    "prediction.py": 0.9,
    "serve.py": 0.88,
}
_INFERENCE_TEXT_SIGNALS = (
    "model.eval(",
    "pipeline(",
    "model.predict(",
    "predict_proba(",
    "generate(",
)
_DEPENDENCY_BASENAMES = {
    "pyproject.toml": "python-project",
    "setup.cfg": "setuptools-config",
    "setup.py": "setuptools-executable",
    "environment.yml": "conda-environment",
    "environment.yaml": "conda-environment",
    "conda.yml": "conda-environment",
    "conda.yaml": "conda-environment",
    "pipfile": "pipenv",
    "pipfile.lock": "pipenv-lock",
    "poetry.lock": "poetry-lock",
    "uv.lock": "uv-lock",
    "package.json": "node-package",
    "package-lock.json": "npm-lock",
    "pnpm-lock.yaml": "pnpm-lock",
    "yarn.lock": "yarn-lock",
    "cargo.toml": "rust-package",
    "cargo.lock": "rust-lock",
    "dockerfile": "container-build",
}
_WEIGHT_SUFFIXES = {
    ".safetensors": "safetensors",
    ".onnx": "onnx",
    ".pt": "pytorch-pickle",
    ".pth": "pytorch-pickle",
    ".bin": "binary-weights",
    ".ckpt": "checkpoint-pickle",
    ".h5": "keras-hdf5",
    ".keras": "keras",
    ".pb": "tensorflow-protobuf",
    ".joblib": "joblib-pickle",
    ".pkl": "pickle",
    ".pickle": "pickle",
    ".model": "generic-model",
    ".gguf": "gguf",
}
_UNSAFE_WEIGHT_FORMATS = {
    "binary-weights",
    "checkpoint-pickle",
    "joblib-pickle",
    "pickle",
    "pytorch-pickle",
}

_TASK_CANDIDATE_RULES = {
    "automatic-speech-recognition": (
        0.94,
        (
            "automatic speech recognition",
            "speech recognition",
            "whisperforconditionalgeneration",
            "wav2vec2forctc",
        ),
    ),
    "image-classification": (
        0.92,
        (
            "image classification",
            "automodelforimageclassification",
            "imagefolder",
        ),
    ),
    "object-detection": (
        0.92,
        ("object detection", "fasterrcnn", "yolo("),
    ),
    "semantic-segmentation": (
        0.92,
        ("semantic segmentation", "mask2former", "segmentationmodel"),
    ),
    "tabular-classification": (
        0.86,
        ("tabular classification", "classifier.fit("),
    ),
    "tabular-regression": (
        0.86,
        ("tabular regression", "regressor.fit("),
    ),
    "text-classification": (
        0.94,
        (
            "text classification",
            "automodelforsequenceclassification",
            "sequenceclassification",
        ),
    ),
    "time-series-forecasting": (
        0.9,
        ("time series forecasting", "timeseries forecasting"),
    ),
}

_MANIFEST_TASK_CANDIDATES = {
    "run_clm.py": ("causal-language-modeling", 0.82),
    "run_glue.py": ("text-classification", 0.82),
    "run_mlm.py": ("masked-language-modeling", 0.82),
}

_METRIC_RULES = {
    "accuracy": ("accuracy_score(", "compute_accuracy("),
    "bleu": ("bleu.compute(", "sacrebleu"),
    "macro-f1": (
        "f1_score(",
        'metric_for_best_model="f1',
        "metric_for_best_model='f1",
    ),
    "mae": ("mean_absolute_error(",),
    "precision": ("precision_score(",),
    "recall": ("recall_score(",),
    "rmse": ("root_mean_squared_error(", "mean_squared_error("),
    "wer": ("word_error_rate(", "compute_wer("),
}

_ARTIFACT_RULES = {
    "keras-model": ("model.save(",),
    "metrics-json": ("metrics.json", "json.dump(metrics"),
    "onnx-model": ("torch.onnx.export(",),
    "pretrained-model": ("save_pretrained(",),
    "pytorch-checkpoint": ("torch.save(", "save_checkpoint("),
    "tokenizer": ("tokenizer.save_pretrained(",),
}

_WEIGHT_ARTIFACT_NAMES = {
    "binary-weights": "binary-model-weights",
    "checkpoint-pickle": "model-checkpoint",
    "generic-model": "generic-model-artifact",
    "gguf": "gguf-model",
    "joblib-pickle": "joblib-model",
    "keras": "keras-model",
    "keras-hdf5": "keras-model",
    "onnx": "onnx-model",
    "pickle": "pickle-model",
    "pytorch-pickle": "pytorch-checkpoint",
    "safetensors": "safetensors-model",
    "tensorflow-protobuf": "tensorflow-model",
}


class RepositoryAnalysisError(HarnessError):
    """A safe, expected failure while statically inspecting a source snapshot."""


def _evidence_kind(reference: str) -> str:
    if reference.startswith("manifest:"):
        return "tree_manifest"
    if ":L" in reference and "#sha256=" in reference:
        return "text_line"
    if reference.startswith("source_snapshot:"):
        return "snapshot_metadata"
    return "unknown"


_TEXT_EVIDENCE_PATTERN = re.compile(
    r"^(?P<path>.+):L(?P<line>[1-9][0-9]*)#sha256=(?P<sha256>[0-9a-f]{64})$"
)
_MANIFEST_EVIDENCE_PATTERN = re.compile(
    r"^manifest:(?P<sha256>[0-9a-f]{64}):(?P<path>.+)#basis=(?P<basis>[^#]+)$"
)


def _evidence_records(
    references: tuple[str, ...],
    *,
    snapshot_id: str | None = None,
    resolved_commit: str | None = None,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for reference in references:
        record: dict[str, Any] = {
            "kind": _evidence_kind(reference),
            "ref": reference,
        }
        if snapshot_id is not None:
            record["snapshot_id"] = snapshot_id
        if resolved_commit is not None:
            record["resolved_commit"] = resolved_commit
        text_match = _TEXT_EVIDENCE_PATTERN.match(reference)
        if text_match is not None:
            record.update(
                {
                    "path": text_match.group("path"),
                    "line": int(text_match.group("line")),
                    "document_sha256": text_match.group("sha256"),
                }
            )
        manifest_match = _MANIFEST_EVIDENCE_PATTERN.match(reference)
        if manifest_match is not None:
            record["kind"] = "manifest_entry"
            record["manifest_entry"] = {
                "path": manifest_match.group("path"),
                "tree_manifest_sha256": manifest_match.group("sha256"),
                "basis": manifest_match.group("basis"),
            }
        records.append(record)
    return records


def _manifest_evidence(tree_sha256: str, path: str, basis: str) -> str:
    return f"manifest:{tree_sha256}:{path}#basis={basis}"


@dataclass(frozen=True)
class AnalysisSignal:
    name: str
    evidence_refs: tuple[str, ...]

    def to_dict(
        self,
        *,
        snapshot_id: str | None = None,
        resolved_commit: str | None = None,
    ) -> dict[str, Any]:
        return {
            "name": self.name,
            "evidence_refs": list(self.evidence_refs),
            "evidence": _evidence_records(
                self.evidence_refs,
                snapshot_id=snapshot_id,
                resolved_commit=resolved_commit,
            ),
        }


@dataclass(frozen=True)
class TaskCandidate:
    task: str
    confidence: float
    evidence_refs: tuple[str, ...]

    def to_dict(
        self,
        *,
        snapshot_id: str | None = None,
        resolved_commit: str | None = None,
    ) -> dict[str, Any]:
        return {
            "task": self.task,
            "confidence": self.confidence,
            "evidence_refs": list(self.evidence_refs),
            "evidence": _evidence_records(
                self.evidence_refs,
                snapshot_id=snapshot_id,
                resolved_commit=resolved_commit,
            ),
        }


@dataclass(frozen=True)
class DependencyManifest:
    path: str
    kind: str
    evidence_refs: tuple[str, ...] = ()

    def to_dict(
        self,
        *,
        snapshot_id: str | None = None,
        resolved_commit: str | None = None,
    ) -> dict[str, Any]:
        return {
            "path": self.path,
            "kind": self.kind,
            "evidence_refs": list(self.evidence_refs),
            "evidence": _evidence_records(
                self.evidence_refs,
                snapshot_id=snapshot_id,
                resolved_commit=resolved_commit,
            ),
        }


@dataclass(frozen=True)
class TrainingEntrypointCandidate:
    path: str
    confidence: float
    evidence_refs: tuple[str, ...]

    def to_dict(
        self,
        *,
        snapshot_id: str | None = None,
        resolved_commit: str | None = None,
    ) -> dict[str, Any]:
        return {
            "path": self.path,
            "confidence": self.confidence,
            "evidence_refs": list(self.evidence_refs),
            "evidence": _evidence_records(
                self.evidence_refs,
                snapshot_id=snapshot_id,
                resolved_commit=resolved_commit,
            ),
        }


@dataclass(frozen=True)
class RepositoryRisk:
    code: str
    severity: str
    evidence_refs: tuple[str, ...]

    def to_dict(
        self,
        *,
        snapshot_id: str | None = None,
        resolved_commit: str | None = None,
    ) -> dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity,
            "evidence_refs": list(self.evidence_refs),
            "evidence": _evidence_records(
                self.evidence_refs,
                snapshot_id=snapshot_id,
                resolved_commit=resolved_commit,
            ),
        }


@dataclass(frozen=True)
class DownstreamBlocker:
    code: str
    stage: str
    message: str
    evidence_refs: tuple[str, ...]

    def to_dict(
        self,
        *,
        snapshot_id: str | None = None,
        resolved_commit: str | None = None,
    ) -> dict[str, Any]:
        return {
            "code": self.code,
            "stage": self.stage,
            "message": self.message,
            "evidence_refs": list(self.evidence_refs),
            "evidence": _evidence_records(
                self.evidence_refs,
                snapshot_id=snapshot_id,
                resolved_commit=resolved_commit,
            ),
        }


@dataclass(frozen=True)
class BaseModelCandidate:
    model_id: str
    evidence_refs: tuple[str, ...]

    def to_dict(
        self,
        *,
        snapshot_id: str | None = None,
        resolved_commit: str | None = None,
    ) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "evidence_refs": list(self.evidence_refs),
            "evidence": _evidence_records(
                self.evidence_refs,
                snapshot_id=snapshot_id,
                resolved_commit=resolved_commit,
            ),
        }


@dataclass(frozen=True)
class RepositoryAnalysis:
    analysis_id: str
    task_id: str
    source_snapshot_id: str
    resolved_commit: str
    analyzer_version: str
    status: str
    next_action: str
    execution_policy: str
    license: str
    license_status: str
    frameworks: tuple[AnalysisSignal, ...]
    dependency_manifests: tuple[DependencyManifest, ...]
    training_entrypoints: tuple[TrainingEntrypointCandidate, ...]
    data_contract_hints: tuple[AnalysisSignal, ...]
    weight_formats: tuple[AnalysisSignal, ...]
    risks: tuple[RepositoryRisk, ...]
    downstream_blockers: tuple[DownstreamBlocker, ...]
    task_candidates: tuple[TaskCandidate, ...] = ()
    metrics: tuple[AnalysisSignal, ...] = ()
    artifacts: tuple[AnalysisSignal, ...] = ()
    inference_entrypoints: tuple[TrainingEntrypointCandidate, ...] = ()
    base_model_candidates: tuple[BaseModelCandidate, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        evidence_context = {
            "snapshot_id": self.source_snapshot_id,
            "resolved_commit": self.resolved_commit,
        }
        frameworks = [
            item.to_dict(**evidence_context) for item in self.frameworks
        ]
        task_candidates = [
            item.to_dict(**evidence_context) for item in self.task_candidates
        ]
        dependencies = [
            item.to_dict(**evidence_context) for item in self.dependency_manifests
        ]
        training_entrypoints = [
            item.to_dict(**evidence_context) for item in self.training_entrypoints
        ]
        inference_entrypoints = [
            item.to_dict(**evidence_context) for item in self.inference_entrypoints
        ]
        data_contracts = [
            item.to_dict(**evidence_context) for item in self.data_contract_hints
        ]
        risks = [item.to_dict(**evidence_context) for item in self.risks]
        entrypoints = [
            {"kind": "train", "symbol": None, **item}
            for item in training_entrypoints
        ] + [
            {"kind": "inference", "symbol": None, **item}
            for item in inference_entrypoints
        ]
        return {
            "analysis_id": self.analysis_id,
            "task_id": self.task_id,
            "source_snapshot_id": self.source_snapshot_id,
            "resolved_commit": self.resolved_commit,
            "analyzer_version": self.analyzer_version,
            "status": self.status,
            "next_action": self.next_action,
            "execution_policy": self.execution_policy,
            "license": self.license,
            "license_status": self.license_status,
            "frameworks": frameworks,
            "task_candidates": task_candidates,
            "entrypoints": entrypoints,
            "data_contract_candidates": data_contracts,
            "dependency_files": dependencies,
            "risk_findings": risks,
            "inference_entrypoints": inference_entrypoints,
            "base_model_candidates": [
                item.to_dict(**evidence_context)
                for item in self.base_model_candidates
            ],
            # Backward-compatible projections used by the existing Workspace/UI.
            "dependency_manifests": dependencies,
            "training_entrypoints": training_entrypoints,
            "data_contract_hints": data_contracts,
            "weight_formats": [
                item.to_dict(**evidence_context) for item in self.weight_formats
            ],
            "metrics": [
                item.to_dict(**evidence_context) for item in self.metrics
            ],
            "artifacts": [
                item.to_dict(**evidence_context) for item in self.artifacts
            ],
            "risks": risks,
            "downstream_blockers": [
                item.to_dict(**evidence_context)
                for item in self.downstream_blockers
            ],
        }


@dataclass(frozen=True)
class _SelectedText:
    path: str
    text: str
    sha256: str


def _line_evidence(document: _SelectedText, needle: str) -> str:
    selected = needle.casefold()
    line = next(
        (
            line_number
            for line_number, content in enumerate(document.text.splitlines(), start=1)
            if selected in content.casefold()
        ),
        1,
    )
    return f"{document.path}:L{line}#sha256={document.sha256}"


class StaticRepositoryAnalyzer:
    """Analyze trusted snapshot metadata without loading repository code.

    The analyzer reads only the immutable file manifest and the bounded text
    documents embedded by the source provider. It never reads repository paths
    from disk and never imports or executes source content.
    """

    def analyze(self, snapshot: SourceSnapshot) -> RepositoryAnalysis:
        snapshot_errors = tuple(verify_source_snapshot(snapshot))
        if snapshot_errors:
            selected = ",".join(sorted(set(snapshot_errors)))
            raise RepositoryAnalysisError(
                f"source_snapshot_integrity_failed:{selected}"
            )
        if snapshot.execution_policy != "never_execute_in_l1":
            raise RepositoryAnalysisError("unsafe_source_snapshot_execution_policy")

        selected_texts = _validated_selected_texts(snapshot)
        file_paths = tuple(
            sorted(
                item.path
                for item in snapshot.files
                if item.kind in {"blob", "executable", "symlink", "submodule"}
            )
        )
        text_by_path = {item.path: item for item in selected_texts}

        frameworks = _detect_frameworks(selected_texts)
        task_candidates = _task_candidates(
            selected_texts,
            file_paths,
            snapshot.tree_manifest_sha256,
        )
        dependencies = _dependency_manifests(
            file_paths,
            snapshot.tree_manifest_sha256,
        )
        entrypoints = _training_entrypoints(
            file_paths,
            text_by_path,
            snapshot.tree_manifest_sha256,
        )
        inference_entrypoints = _inference_entrypoints(
            file_paths,
            text_by_path,
            snapshot.tree_manifest_sha256,
        )
        base_models = _base_model_candidates(selected_texts)
        data_hints = _data_contract_hints(selected_texts)
        weight_formats = _weight_formats(
            file_paths,
            snapshot.tree_manifest_sha256,
        )
        metrics = _signals_from_text(selected_texts, _METRIC_RULES)
        artifacts = _artifact_candidates(
            selected_texts,
            file_paths,
            snapshot.tree_manifest_sha256,
        )
        risks = _repository_risks(
            snapshot=snapshot,
            file_paths=file_paths,
            selected_texts=selected_texts,
            weight_formats=weight_formats,
        )
        blockers = _downstream_blockers(snapshot)
        status = _analysis_status(
            snapshot=snapshot,
            training_entrypoints=entrypoints,
            risks=risks,
        )
        next_action = _next_action(
            status=status,
            blockers=blockers,
            risks=risks,
        )
        analysis_id = _analysis_id(snapshot)

        return RepositoryAnalysis(
            analysis_id=analysis_id,
            task_id=snapshot.task_id,
            source_snapshot_id=snapshot.snapshot_id,
            resolved_commit=snapshot.resolved_commit,
            analyzer_version=ANALYZER_VERSION,
            status=status,
            next_action=next_action,
            execution_policy="static_only_never_execute",
            license=snapshot.license,
            license_status=snapshot.license_status,
            frameworks=frameworks,
            dependency_manifests=dependencies,
            training_entrypoints=entrypoints,
            data_contract_hints=data_hints,
            weight_formats=weight_formats,
            risks=risks,
            downstream_blockers=blockers,
            task_candidates=task_candidates,
            metrics=metrics,
            artifacts=artifacts,
            inference_entrypoints=inference_entrypoints,
            base_model_candidates=base_models,
        )


def analyze_repository_snapshot(snapshot: SourceSnapshot) -> RepositoryAnalysis:
    return StaticRepositoryAnalyzer().analyze(snapshot)


def _analysis_id(snapshot: SourceSnapshot) -> str:
    value = {
        "analyzer_version": ANALYZER_VERSION,
        "snapshot_id": snapshot.snapshot_id,
        "tree_manifest_sha256": snapshot.tree_manifest_sha256,
        "license": snapshot.license,
        "license_status": snapshot.license_status,
        "license_policy": dict(snapshot.license_policy),
        "documents": [
            {
                "path": document.path,
                "size_bytes": document.size_bytes,
                "sha256": document.sha256,
            }
            for document in sorted(snapshot.documents, key=lambda item: item.path)
        ],
    }
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"analysis_{hashlib.sha256(payload).hexdigest()[:20]}"


def _validated_selected_texts(snapshot: SourceSnapshot) -> tuple[_SelectedText, ...]:
    if len(snapshot.documents) > MAX_SELECTED_DOCUMENTS:
        raise RepositoryAnalysisError("too_many_selected_documents")
    file_paths = {item.path for item in snapshot.files if item.kind == "blob"}
    selected: list[_SelectedText] = []
    total_bytes = 0
    seen: set[str] = set()
    for document in sorted(snapshot.documents, key=lambda item: item.path):
        if document.path in seen:
            raise RepositoryAnalysisError("duplicate_selected_document")
        seen.add(document.path)
        if document.path not in file_paths:
            raise RepositoryAnalysisError("selected_document_not_in_snapshot")
        if not _allowed_text_path(document.path):
            raise RepositoryAnalysisError("unsupported_selected_document_type")
        if not isinstance(document.content, bytes):
            raise RepositoryAnalysisError("selected_document_content_not_bytes")
        actual_size = len(document.content)
        if (
            actual_size != document.size_bytes
            or actual_size > MAX_SELECTED_DOCUMENT_BYTES
        ):
            raise RepositoryAnalysisError("selected_document_size_mismatch")
        if hashlib.sha256(document.content).hexdigest() != document.sha256:
            raise RepositoryAnalysisError("selected_document_sha256_mismatch")
        total_bytes += actual_size
        if total_bytes > MAX_TOTAL_SELECTED_DOCUMENT_BYTES:
            raise RepositoryAnalysisError("selected_documents_total_too_large")
        try:
            text = document.content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise RepositoryAnalysisError(
                "selected_document_not_utf8"
            ) from exc
        selected.append(
            _SelectedText(path=document.path, text=text, sha256=document.sha256)
        )
    return tuple(selected)


def _allowed_text_path(path: str) -> bool:
    selected = PurePosixPath(path)
    basename = selected.name.lower()
    return (
        selected.suffix.lower() in _TEXT_SUFFIXES
        or basename in _TEXT_BASENAMES
        or basename.startswith("readme")
        or basename.startswith("license")
        or basename.startswith("notice")
        or basename.startswith("requirements")
    )


def _detect_frameworks(
    selected_texts: tuple[_SelectedText, ...],
) -> tuple[AnalysisSignal, ...]:
    rules = {
        "pytorch": ("import torch", "from torch", "pytorch", "torch.nn"),
        "transformers": (
            "from transformers",
            "import transformers",
            "automodelfor",
            "trainingarguments(",
        ),
        "tensorflow": ("import tensorflow", "from tensorflow", "tf.keras"),
        "keras": ("import keras", "from keras", "keras.models"),
        "scikit-learn": ("import sklearn", "from sklearn", "scikit-learn"),
        "ultralytics": ("from ultralytics", "import ultralytics", "yolo("),
        "xgboost": ("import xgboost", "from xgboost", "xgboost"),
        "lightgbm": ("import lightgbm", "from lightgbm", "lightgbm"),
        "jax": ("import jax", "from jax", "flax.linen"),
    }
    return _signals_from_text(selected_texts, rules)


def _task_candidates(
    selected_texts: tuple[_SelectedText, ...],
    file_paths: tuple[str, ...],
    tree_manifest_sha256: str,
) -> tuple[TaskCandidate, ...]:
    evidence: dict[str, set[str]] = {}
    confidence: dict[str, float] = {}
    for document in selected_texts:
        folded = document.text.casefold()
        for task, (score, needles) in _TASK_CANDIDATE_RULES.items():
            for needle in needles:
                if needle in folded:
                    evidence.setdefault(task, set()).add(
                        _line_evidence(document, needle)
                    )
                    confidence[task] = max(score, confidence.get(task, 0.0))

    for path in file_paths:
        basename = PurePosixPath(path).name.casefold()
        match = _MANIFEST_TASK_CANDIDATES.get(basename)
        if match is None:
            continue
        task, score = match
        evidence.setdefault(task, set()).add(
            _manifest_evidence(
                tree_manifest_sha256,
                path,
                "task-filename",
            )
        )
        confidence[task] = max(score, confidence.get(task, 0.0))

    return tuple(
        TaskCandidate(
            task=task,
            confidence=round(confidence[task], 2),
            evidence_refs=tuple(sorted(references)),
        )
        for task, references in sorted(evidence.items())
    )


def _dependency_manifests(
    file_paths: tuple[str, ...],
    tree_manifest_sha256: str,
) -> tuple[DependencyManifest, ...]:
    selected: list[DependencyManifest] = []
    for path in file_paths:
        basename = PurePosixPath(path).name.lower()
        kind = _DEPENDENCY_BASENAMES.get(basename)
        if kind is None and basename.startswith("requirements") and basename.endswith(
            ".txt"
        ):
            kind = "pip-requirements"
        if kind is not None:
            selected.append(
                DependencyManifest(
                    path=path,
                    kind=kind,
                    evidence_refs=(
                        _manifest_evidence(
                            tree_manifest_sha256,
                            path,
                            "dependency-filename",
                        ),
                    ),
                )
            )
    return tuple(sorted(selected, key=lambda item: item.path))


def _training_entrypoints(
    file_paths: tuple[str, ...],
    text_by_path: dict[str, _SelectedText],
    tree_manifest_sha256: str,
) -> tuple[TrainingEntrypointCandidate, ...]:
    selected: list[TrainingEntrypointCandidate] = []
    for path in file_paths:
        pure_path = PurePosixPath(path)
        basename = pure_path.name.lower()
        is_python_entrypoint = pure_path.suffix.lower() == ".py"
        confidence = (
            _TRAIN_ENTRY_BASENAMES.get(basename)
            if is_python_entrypoint
            else None
        )
        evidence: list[str] = []
        if confidence is not None:
            evidence.append(
                _manifest_evidence(tree_manifest_sha256, path, "training-filename")
            )
        elif basename.startswith(
            ("train_", "finetune_", "fine_tune_")
        ) and basename.endswith(".py"):
            confidence = 0.92
            evidence.append(
                _manifest_evidence(tree_manifest_sha256, path, "training-filename")
            )
        elif basename.startswith("run_") and basename.endswith(".py"):
            confidence = 0.68
            evidence.append(
                _manifest_evidence(tree_manifest_sha256, path, "training-filename")
            )

        document = text_by_path.get(path) if is_python_entrypoint else None
        if document is not None:
            folded = document.text.casefold()
            matched = [signal for signal in _TRAINING_TEXT_SIGNALS if signal in folded]
            if matched:
                confidence = min(0.99, (confidence or 0.52) + 0.12)
                evidence.extend(
                    _line_evidence(document, signal) for signal in matched[:3]
                )
        if confidence is not None:
            selected.append(
                TrainingEntrypointCandidate(
                    path=path,
                    confidence=round(confidence, 2),
                    evidence_refs=tuple(dict.fromkeys(evidence)),
                )
            )
    return tuple(sorted(selected, key=lambda item: (-item.confidence, item.path)))


def _inference_entrypoints(
    file_paths: tuple[str, ...],
    text_by_path: dict[str, _SelectedText],
    tree_manifest_sha256: str,
) -> tuple[TrainingEntrypointCandidate, ...]:
    selected: list[TrainingEntrypointCandidate] = []
    for path in file_paths:
        pure_path = PurePosixPath(path)
        basename = pure_path.name.casefold()
        is_python_entrypoint = pure_path.suffix.lower() == ".py"
        confidence = (
            _INFERENCE_ENTRY_BASENAMES.get(basename)
            if is_python_entrypoint
            else None
        )
        evidence: list[str] = []
        if confidence is not None:
            evidence.append(
                _manifest_evidence(tree_manifest_sha256, path, "inference-filename")
            )

        document = text_by_path.get(path) if is_python_entrypoint else None
        if document is not None:
            folded = document.text.casefold()
            matched = [
                signal for signal in _INFERENCE_TEXT_SIGNALS if signal in folded
            ]
            if matched:
                confidence = min(0.99, (confidence or 0.52) + 0.12)
                evidence.extend(
                    _line_evidence(document, signal) for signal in matched[:3]
                )
        if confidence is not None:
            selected.append(
                TrainingEntrypointCandidate(
                    path=path,
                    confidence=round(confidence, 2),
                    evidence_refs=tuple(dict.fromkeys(evidence)),
                )
            )
    return tuple(sorted(selected, key=lambda item: (-item.confidence, item.path)))


_BASE_MODEL_PATTERNS = (
    re.compile(r"from_pretrained\s*\(\s*['\"]([^'\"]+)['\"]", re.IGNORECASE),
    re.compile(
        r"model_name_or_path\s*=\s*['\"]([^'\"]+)['\"]",
        re.IGNORECASE,
    ),
)


def _base_model_candidates(
    selected_texts: tuple[_SelectedText, ...],
) -> tuple[BaseModelCandidate, ...]:
    evidence: dict[str, set[str]] = {}
    for document in selected_texts:
        for pattern in _BASE_MODEL_PATTERNS:
            for match in pattern.finditer(document.text):
                model_id = match.group(1).strip()
                if not model_id or len(model_id) > 200 or any(
                    character.isspace() for character in model_id
                ):
                    continue
                evidence.setdefault(model_id, set()).add(
                    _line_evidence(document, match.group(0))
                )
    return tuple(
        BaseModelCandidate(
            model_id=model_id,
            evidence_refs=tuple(sorted(references)),
        )
        for model_id, references in sorted(evidence.items())
    )


def _data_contract_hints(
    selected_texts: tuple[_SelectedText, ...],
) -> tuple[AnalysisSignal, ...]:
    rules = {
        "huggingface-datasets": ("load_dataset(", "datasets.load_dataset("),
        "torch-dataloader": ("dataloader(", "dataset[", "__getitem__("),
        "split-files": ("train_file", "validation_file", "test_file"),
        "text-label-columns": (
            '"text"',
            "'text'",
            '"label"',
            "'label'",
            "text and label",
            "text,label",
        ),
        "image-class-folders": ("imagefolder", "image_folder", "class_names"),
        "audio-waveform": ("sampling_rate", "audio_column", "waveform"),
        "csv": ("read_csv(", ".csv", "csv_path"),
        "json-or-jsonl": ("read_json(", ".jsonl", "json_path"),
        "parquet": ("read_parquet(", ".parquet"),
    }
    return _signals_from_text(selected_texts, rules)


def _weight_formats(
    file_paths: tuple[str, ...],
    tree_manifest_sha256: str,
) -> tuple[AnalysisSignal, ...]:
    evidence: dict[str, list[str]] = {}
    for path in file_paths:
        selected_path = path.casefold()
        matched: str | None = None
        for suffix, name in _WEIGHT_SUFFIXES.items():
            if selected_path.endswith(suffix):
                matched = name
                break
        if matched is not None:
            evidence.setdefault(matched, []).append(
                _manifest_evidence(tree_manifest_sha256, path, "weight-suffix")
            )
    return tuple(
        AnalysisSignal(name=name, evidence_refs=tuple(sorted(refs)))
        for name, refs in sorted(evidence.items())
    )


def _artifact_candidates(
    selected_texts: tuple[_SelectedText, ...],
    file_paths: tuple[str, ...],
    tree_manifest_sha256: str,
) -> tuple[AnalysisSignal, ...]:
    evidence: dict[str, set[str]] = {
        item.name: set(item.evidence_refs)
        for item in _signals_from_text(selected_texts, _ARTIFACT_RULES)
    }
    for path in file_paths:
        selected_path = path.casefold()
        for suffix, format_name in _WEIGHT_SUFFIXES.items():
            if not selected_path.endswith(suffix):
                continue
            artifact_name = _WEIGHT_ARTIFACT_NAMES[format_name]
            evidence.setdefault(artifact_name, set()).add(
                _manifest_evidence(tree_manifest_sha256, path, "artifact-suffix")
            )
            break
    return tuple(
        AnalysisSignal(name=name, evidence_refs=tuple(sorted(references)))
        for name, references in sorted(evidence.items())
    )


def _repository_risks(
    *,
    snapshot: SourceSnapshot,
    file_paths: tuple[str, ...],
    selected_texts: tuple[_SelectedText, ...],
    weight_formats: tuple[AnalysisSignal, ...],
) -> tuple[RepositoryRisk, ...]:
    findings: dict[tuple[str, str], list[str]] = {}

    def add(code: str, severity: str, evidence_ref: str) -> None:
        findings.setdefault((code, severity), []).append(evidence_ref)

    for item in snapshot.files:
        basename = PurePosixPath(item.path).name.casefold()
        suffix = PurePosixPath(item.path).suffix.casefold()
        if item.kind == "symlink":
            add(
                "symlink_present",
                "high",
                _manifest_evidence(
                    snapshot.tree_manifest_sha256,
                    item.path,
                    "kind-symlink",
                ),
            )
        elif item.kind == "submodule":
            add(
                "submodule_present",
                "high",
                _manifest_evidence(
                    snapshot.tree_manifest_sha256,
                    item.path,
                    "kind-submodule",
                ),
            )
        elif item.kind == "executable":
            add(
                "executable_source_file",
                "high",
                _manifest_evidence(
                    snapshot.tree_manifest_sha256,
                    item.path,
                    "kind-executable",
                ),
            )
        if basename == "setup.py":
            add(
                "executable_installer",
                "high",
                _manifest_evidence(
                    snapshot.tree_manifest_sha256,
                    item.path,
                    "installer-filename",
                ),
            )
        if suffix in {".sh", ".bash", ".zsh", ".bat", ".cmd", ".ps1"}:
            add(
                "shell_script_present",
                "high",
                _manifest_evidence(
                    snapshot.tree_manifest_sha256,
                    item.path,
                    "shell-suffix",
                ),
            )
        if suffix in {".so", ".dylib", ".dll", ".exe"}:
            add(
                "native_binary_present",
                "high",
                _manifest_evidence(
                    snapshot.tree_manifest_sha256,
                    item.path,
                    "native-binary-suffix",
                ),
            )

    for item in weight_formats:
        if item.name in _UNSAFE_WEIGHT_FORMATS:
            for evidence_ref in item.evidence_refs:
                add("unsafe_deserialization_format", "high", evidence_ref)

    executable_text_suffixes = {
        ".bat",
        ".bash",
        ".cmd",
        ".ps1",
        ".py",
        ".pyx",
        ".sh",
        ".zsh",
    }
    text_rules = {
        "dynamic_code_loading": (
            r"\btrust_remote_code\s*=\s*true\b",
            r"\bimportlib\.import_module\s*\(",
            r"(?<![\w.])__import__\s*\(",
            r"\brunpy\.run_\w*\s*\(",
        ),
        "direct_code_execution": (
            r"(?<![\w.])exec\s*\(",
            r"(?<![\w.])eval\s*\(",
            r"\bos\.system\s*\(",
            r"\bsubprocess\.",
        ),
        "network_download_during_run": (
            r"\brequests\.get\s*\(",
            r"\burllib\.request\b",
            r"\bsnapshot_download\s*\(",
            r"\bhf_hub_download\s*\(",
            r"\bgit\s+clone\s+",
            r"\bcurl\s+",
            r"\bwget\s+",
        ),
        "credential_access": (
            r"\bos\.environ\b",
            r"(?<![\w.])getenv\s*\(",
            r"\bapi_token\b",
            r"\baccess_token\b",
        ),
    }
    for document in selected_texts:
        folded = document.text.casefold()
        is_executable_text = (
            PurePosixPath(document.path).suffix.casefold()
            in executable_text_suffixes
        )
        for code, patterns in text_rules.items():
            for pattern in patterns:
                match = re.search(pattern, folded)
                if match is None:
                    continue
                if is_executable_text:
                    add(code, "high", _line_evidence(document, match.group(0)))
                elif code == "network_download_during_run":
                    add(
                        "network_download_documentation",
                        "medium",
                        _line_evidence(document, match.group(0)),
                    )

    return tuple(
        RepositoryRisk(
            code=code,
            severity=severity,
            evidence_refs=tuple(sorted(set(refs))),
        )
        for (code, severity), refs in sorted(findings.items())
    )


def _downstream_blockers(snapshot: SourceSnapshot) -> tuple[DownstreamBlocker, ...]:
    policy = dict(snapshot.license_policy) or evaluate_license_policy(
        snapshot.license, snapshot.license_status
    )
    decision = policy.get("decision")
    if decision == "allow":
        return ()
    if decision == "deny":
        code = "blocked_license_denied"
        message = (
            "The declared source license is restricted by the current product "
            "policy. Static analysis may be reviewed, but plan approval, "
            "environment preparation and execution remain blocked."
        )
    elif snapshot.license_status == "unknown":
        code = "blocked_license_unknown"
        message = (
            "Source license is unknown. Static analysis may be reviewed, but "
            "plan approval, environment preparation and execution must remain "
            "blocked until the license is resolved."
        )
    else:
        code = "blocked_license_review"
        message = (
            "The declared source license is not in the current permissive "
            "allowlist. Static analysis may be reviewed, but plan approval, "
            "environment preparation and execution require a policy review."
        )
    return (
        DownstreamBlocker(
            code=code,
            stage="before_training_plan_environment_or_execution",
            message=message,
            evidence_refs=(
                f"source_snapshot:{snapshot.snapshot_id}#license_policy:"
                f"{policy.get('policy_version', 'unknown')}",
            ),
        ),
    )


def _analysis_status(
    *,
    snapshot: SourceSnapshot,
    training_entrypoints: tuple[TrainingEntrypointCandidate, ...],
    risks: tuple[RepositoryRisk, ...],
) -> str:
    policy = dict(snapshot.license_policy) or evaluate_license_policy(
        snapshot.license, snapshot.license_status
    )
    has_blocking_risk = any(
        item.severity.casefold() in {"critical", "high"} for item in risks
    )
    if policy.get("decision") == "deny" or has_blocking_risk:
        return "blocked"
    if not training_entrypoints:
        return "needs_input"
    return "complete"


def _next_action(
    *,
    status: str,
    blockers: tuple[DownstreamBlocker, ...],
    risks: tuple[RepositoryRisk, ...],
) -> str:
    if status == "needs_input":
        return "map_training_entrypoint"
    if status == "blocked" and any(
        item.code == "blocked_license_denied" for item in blockers
    ):
        return "resolve_license"
    if status == "blocked" and any(
        item.severity.casefold() in {"critical", "high"} for item in risks
    ):
        return "review_repository_risks"
    if blockers:
        return "resolve_license"
    return "ready_for_environment_check"


def _signals_from_text(
    selected_texts: tuple[_SelectedText, ...],
    rules: dict[str, tuple[str, ...]],
) -> tuple[AnalysisSignal, ...]:
    evidence: dict[str, list[str]] = {}
    for document in selected_texts:
        folded = document.text.casefold()
        for name, needles in rules.items():
            for needle in needles:
                if needle in folded:
                    evidence.setdefault(name, []).append(
                        _line_evidence(document, needle)
                    )
    return tuple(
        AnalysisSignal(name=name, evidence_refs=tuple(sorted(set(refs))))
        for name, refs in sorted(evidence.items())
    )
