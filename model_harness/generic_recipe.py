"""One trusted bridge for task-agnostic training code executed only in OCI.

The host validates identities, stage outputs and metric gates. It never imports
bundle source, unpickles a model, or treats worker success prose as Run state.
"""
from __future__ import annotations

import hashlib
import json
import math
import shutil
import stat
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from .errors import ContractError, RunCancelled
from .io_utils import read_json, sha256_file, write_json
from .isolated_execution import ExecutionBundle, OCIExecutor
from .plugin_api import RecipeManifest, RunExecutionContext, StrategyProposal


PLUGIN_ID = "generic-isolated-execution"
MODEL_MANIFEST = "generic_model.json"
_HOST_ARTIFACTS = {MODEL_MANIFEST, "generic_execution.json", "config.json", "metrics.json", "failure_samples.json", "optimization_strategies.json", "learning_report.md"}
_MAX_RESULT_BYTES = 4 * 1024 * 1024


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _relative(value: Any) -> str:
    if not isinstance(value, str) or not value or "\\" in value or ":" in value or any(ord(c) < 32 for c in value):
        raise ContractError("generic artifact must have a safe relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in value.split("/")):
        raise ContractError("generic artifact must have a safe relative path")
    return path.as_posix()


def _safe_file(root: Path, relative: Any) -> Path:
    selected = root / _relative(relative)
    if root.is_symlink() or any(path.is_symlink() for path in [selected, *selected.parents] if path == root or root in path.parents):
        raise ContractError("generic artifact cannot be a symlink")
    resolved = selected.resolve()
    if root.resolve() not in resolved.parents or not resolved.is_file():
        raise ContractError("generic artifact is missing or outside its evidence directory")
    info = resolved.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ContractError("generic artifact must be a regular unlinked file")
    return resolved


def _finite(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ContractError(f"{label} must be finite numeric data")
    return float(value)


def _count(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ContractError(f"{label} must be a non-negative integer")
    return value


def _json(path: Path) -> dict[str, Any]:
    if path.stat().st_size > _MAX_RESULT_BYTES:
        raise ContractError("generic stage result exceeds the JSON limit")
    def pairs(values):
        result = {}
        for key, value in values:
            if key in result:
                raise ContractError("duplicate stage result JSON key")
            result[key] = value
        return result
    def invalid_constant(value):
        raise ContractError("non-finite stage result JSON")
    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=pairs, parse_constant=invalid_constant)
        json.dumps(value, allow_nan=False)
    except (ValueError, UnicodeError, OSError) as exc:
        raise ContractError("invalid generic stage result JSON") from exc
    if not isinstance(value, dict):
        raise ContractError("generic stage result must be a JSON object")
    return value


def _spec(contract: Mapping[str, Any]) -> dict[str, Any]:
    from .generic_protocol import validate_execution_spec
    spec = validate_execution_spec(contract.get("execution_spec"))
    bundle = ExecutionBundle.from_dict(spec["bundle"])
    if spec.get("bundle_sha256") != bundle.digest:
        raise ContractError("generic execution bundle digest mismatch")
    if not {"train", "evaluate", "predict"}.issubset(dict(bundle.stages)):
        raise ContractError("generic bundle requires train, evaluate and predict stages")
    for item in spec.get("artifacts", []):
        name = _relative(item["path"]).casefold()
        if name in _HOST_ARTIFACTS or name.startswith(("source/", "assets/")):
            raise ContractError("declared artifact collides with host evidence")
    if "all_offline_gates_passed" in spec["evaluation"]["gates"]:
        raise ContractError("evaluation metric collides with the host aggregate gate")
    def safe_config(value):
        if isinstance(value, dict):
            for child in value.values():
                safe_config(child)
        elif isinstance(value, list):
            for child in value:
                safe_config(child)
        elif isinstance(value, str) and (value.startswith(("file://", "~/", "~\\")) or (len(value) > 1 and value.startswith("/") and not value.startswith("/workspace/")) or (len(value) > 2 and value[1:3] in {":\\", ":/"})):
            raise ContractError("execution config must use container or relative paths, not host paths")
    safe_config(spec.get("config", {}))
    return spec


def _asset_files(contract: Mapping[str, Any]) -> dict[str, tuple[Path, Mapping[str, Any]]]:
    result = {}
    assets = contract.get("execution_assets", [])
    if not isinstance(assets, list):
        raise ContractError("execution assets must be immutable references")
    for asset in assets:
        if not isinstance(asset, dict) or not isinstance(asset.get("manifest_sha256"), str) or len(asset["manifest_sha256"]) != 64:
            raise ContractError("execution asset manifest identity is missing")
        if asset.get("task_id") != contract.get("task_id") or asset["manifest_sha256"] != _digest({key: value for key, value in asset.items() if key not in {"root", "manifest_sha256"}}):
            raise ContractError("execution asset owner or manifest digest changed")
        asset_id = _relative(asset.get("asset_id"))
        if "/" in asset_id:
            raise ContractError("execution asset id must be one path segment")
        root = Path(str(asset.get("root", "")))
        if not root.is_absolute() or not isinstance(asset.get("files"), list) or not asset["files"]:
            raise ContractError("execution asset has no verified local files")
        for row in asset["files"]:
            relative = _relative(row.get("path"))
            source = _safe_file(root, relative)
            if source.stat().st_size != row.get("bytes") or sha256_file(source) != row.get("sha256"):
                raise ContractError("execution asset file integrity changed")
            key = f"assets/{asset_id}/{relative}"
            if key in result:
                raise ContractError("execution asset paths collide")
            result[key] = (source, row)
    required = set((contract.get("execution_spec") or {}).get("asset_ids", []))
    if required != {asset["asset_id"] for asset in assets}:
        raise ContractError("execution assets do not match the frozen spec asset ids")
    return result


def _stage_output_root(context: RunExecutionContext, evidence: Mapping[str, Any]) -> Path:
    job = _relative(evidence.get("job_directory"))
    if "/" in job or job != evidence.get("execution_id"):
        raise ContractError("stage job directory does not match its execution identity")
    root = context.isolated_root.resolve() / job / "output"
    if root.is_symlink() or root.parent.is_symlink() or not root.is_dir():
        raise ContractError("stage output directory is missing or unsafe")
    return root


def _verified_stage_file(context: RunExecutionContext, evidence: Mapping[str, Any], relative: str) -> Path:
    rows = evidence.get("artifacts")
    if not isinstance(rows, list):
        raise ContractError("stage artifact manifest is missing")
    matches = [item for item in rows if isinstance(item, dict) and item.get("path") == relative]
    if len(matches) != 1:
        raise ContractError("stage artifact is not uniquely declared by the executor")
    record = matches[0]
    path = _safe_file(_stage_output_root(context, evidence), relative)
    if path.stat().st_size != record.get("bytes") or sha256_file(path) != record.get("sha256"):
        raise ContractError("stage artifact changed after execution")
    return path


def read_stage_json(context: RunExecutionContext, evidence: Mapping[str, Any], filename: str) -> dict[str, Any]:
    """Root qualification and the trusted bridge share the same hash check."""
    return _json(_verified_stage_file(context, evidence, _relative(filename)))


def _test_content(dataset: Mapping[str, Any]) -> tuple[dict[str, str], set[str]]:
    """Content identities omit upload, proposal and member names.

    For row-selected CSVs, also retain record identities so regrouping or
    reordering the same rows cannot manufacture a new independent holdout.
    """
    from .generic_data import _csv
    expected: dict[str, str] = {}
    content: set[str] = set()
    for row in dataset.get("splits", {}).get("test", []):
        relative = _relative(row.get("relative_path"))
        sha = row.get("sha256")
        if not isinstance(sha, str) or len(sha) != 64:
            raise ContractError("final-test content identity is missing")
        expected["test/" + relative] = sha
        content.add("file:" + sha)
        if "csv_row_count" in (row.get("source") or {}):
            path = _safe_file(Path(dataset["root"]) / "test", relative)
            if sha256_file(path) != sha or path.stat().st_size != row.get("bytes"):
                raise ContractError("frozen final-test CSV content changed")
            headers, values, _delimiter = _csv(path.read_bytes())
            # Header order is metadata for a named record; row order and CSV
            # delimiters do not create fresh evidence either.
            content.update("csv_record:" + _digest(dict(zip(headers, value, strict=True))) for value in values)
    if not expected:
        raise ContractError("final-test dataset has no content identities")
    return expected, content


def _test_exposure_lineage(contract: Mapping[str, Any], context: RunExecutionContext) -> dict[str, Any]:
    """Compare actual earlier evaluation inputs within the canonical Run store.

    Qualification, train-only failures and another task's runs are not final
    test exposure. A failed evaluate process did receive its input bytes and
    therefore counts even if it never produced a valid metrics report.
    """
    _inputs, current = _test_content(contract["dataset"])
    overlaps = []
    for prior_dir in sorted(context.run_dir.parent.iterdir()):
        if prior_dir == context.run_dir or prior_dir.is_symlink() or not prior_dir.is_dir():
            continue
        state_path, contract_path = prior_dir / "run_state.json", prior_dir / "task_contract.json"
        if not state_path.is_file() or state_path.is_symlink() or not contract_path.is_file() or contract_path.is_symlink():
            continue
        state = read_json(state_path)
        if state.get("task_id") != context.task_id:
            continue
        if state.get("run_id") != prior_dir.name:
            raise ContractError("prior final-test Run identity changed")
        prior = read_json(contract_path)
        if prior.get("recipe") != PLUGIN_ID:
            continue
        if prior.get("task_id") != context.task_id:
            raise ContractError("prior final-test contract owner changed")
        stage_dir = prior_dir / "evidence" / "isolated_stages"
        if stage_dir.is_symlink() or (prior_dir / "evidence").is_symlink():
            raise ContractError("prior final-test evidence directory is unsafe")
        executions = []
        for path in sorted(stage_dir.glob("stage-*.json")):
            record = _json(_safe_file(stage_dir, path.name))
            stage = record.get("execution") or {}
            if stage.get("stage") != "evaluate":
                continue
            if (record.get("task_id") != context.task_id or record.get("run_id") != prior_dir.name
                    or stage.get("execution_id") != path.stem
                    or stage.get("bundle_sha256") != (prior.get("execution_spec") or {}).get("bundle_sha256")
                    or stage.get("evidence_sha256") != _digest({key: value for key, value in stage.items() if key != "evidence_sha256"})):
                raise ContractError("prior final-test execution identity or digest changed")
            if stage.get("executed") is True:
                executions.append(stage)
        if not executions:
            continue
        expected_bundle = ExecutionBundle.from_dict(prior["execution_spec"]["bundle"]).digest
        if expected_bundle != prior["execution_spec"].get("bundle_sha256"):
            raise ContractError("prior final-test bundle identity changed")
        expected, previous = _test_content(prior["dataset"])
        shared = sorted(current & previous)
        if not shared:
            continue
        for stage in executions:
            inputs = stage.get("inputs")
            if not isinstance(inputs, list):
                raise ContractError("prior final-test execution input manifest is missing")
            observed = {row.get("path"): row.get("sha256") for row in inputs if isinstance(row, dict) and str(row.get("path", "")).startswith("test/")}
            if observed != expected:
                raise ContractError("prior final-test execution inputs differ from the frozen dataset")
            overlaps.append({"run_id": prior_dir.name,
                "proposal_id": (prior.get("execution_binding") or {}).get("proposal_id"),
                "execution_id": stage["execution_id"], "execution_evidence_sha256": stage["evidence_sha256"],
                "overlapping_content_identity_count": len(shared),
                "overlapping_content_sha256": _digest(shared),
                "content_identity_sample": shared[:16]})
    return {"policy": "same_task_prior_executed_evaluation_content_overlap",
            "test_content_sha256": _digest(sorted(current)), "test_contaminated": bool(overlaps),
            "prior_run_ids": sorted({row["run_id"] for row in overlaps}), "overlaps": overlaps,
            "reasons": ["final_test_content_previously_exposed_to_evaluation"] if overlaps else []}


class _CancellationSignal:
    def __init__(self, context: RunExecutionContext) -> None:
        self.context = context

    def is_set(self) -> bool:
        return self.context.is_cancelled()


@dataclass
class GenericTraining:
    selected_name: str
    validation_results: dict[str, dict[str, float]]
    split_counts: dict[str, int]
    model_files: list[str]
    stage_evidence: dict[str, Any]
    context: RunExecutionContext
    execution_records: list[dict[str, Any]] = field(default_factory=list)
    minimum_test_samples: int = 20
    selection_metric: str = ""

    @property
    def execution_environment(self) -> dict[str, Any]:
        return {"executor": "oci", "bundle_sha256": self.stage_evidence["bundle_sha256"],
                "image_reference": self.stage_evidence.get("image_reference"), "image": self.stage_evidence.get("image"),
                "runtime": self.stage_evidence.get("runtime"), "dependencies": {},
                "stages": [{"stage": item["stage"], "execution_id": item["execution_id"], "evidence_sha256": item["evidence_sha256"]} for item in self.execution_records]}


@dataclass
class GenericEvaluation:
    metrics: dict[str, Any]
    stage_evidence: dict[str, Any]
    failure_samples: list[Any]


class GenericIsolatedRecipePlugin:
    manifest = RecipeManifest(plugin_id=PLUGIN_ID, version="0.1.0", contract_schema_version="0.2",
        description="Trusted OCI execution bridge; domain semantics come from a qualified immutable bundle.",
        task_type="generic_execution", input_description="Frozen generic Dataset files and split manifest.",
        output_description="Declared model artifacts, named metrics and an isolated prediction entrypoint.",
        device="qualified-worker", purpose="general user-owned model training", data_adapter="generic-files")

    def __init__(self, executor: OCIExecutor | None = None) -> None:
        self.executor = executor or OCIExecutor()

    def template(self) -> dict[str, Any]:
        return {"schema_version": "0.2", "task_id": "generic-task", "business_goal": "User-defined training outcome",
                "recipe": PLUGIN_ID, "interaction": {"mode": "delegate", "learning_report": True},
                "dataset": {"kind": "generic_files"}, "execution_spec": {},
                "model_selection": {"primary_metric": "validation_metric", "candidates": []},
                "release_gates": {}, "optimization": {"mode": "recommend", "max_iterations": 1, "require_approval": True},
                "diagnostics": {}, "human_gates": ["Data rights, target meaning and immutable acceptance criteria", "Exact isolated execution scope"]}

    def validate_contract(self, contract: dict[str, Any]) -> None:
        from .generic_data import verify_generic_dataset_integrity
        if contract.get("recipe") != PLUGIN_ID:
            raise ContractError("generic recipe identity mismatch")
        if contract.get("dataset", {}).get("kind") != "generic_files":
            raise ContractError("generic execution requires a frozen generic_files Dataset")
        _spec(contract)
        verify_generic_dataset_integrity(contract["dataset"])

    def _stage(self, contract: dict[str, Any], stage: str, context: RunExecutionContext, inputs: Mapping[str, Path], *, require_success: bool = True) -> dict[str, Any]:
        if context.task_id != contract.get("task_id"):
            raise ContractError("generic RunContext task identity mismatch")
        if context.is_cancelled():
            raise RunCancelled("generic stage cancelled before execution")
        spec = _spec(contract)
        assets = _asset_files(contract)
        if any(name in inputs for name in assets):
            raise ContractError("stage input collides with a model asset")
        inputs = {**inputs, **{name: source for name, (source, _record) in assets.items()}}
        controls = context.run_dir / "execution_controls"
        controls.mkdir(parents=True, exist_ok=True)
        config_path = controls / f"{stage}-config.json"
        # Only explicitly declared JSON config crosses this boundary. The full
        # host contract contains paths and test references and is never mounted.
        write_json(config_path, spec.get("config", {}))
        if "config.json" in inputs:
            raise ContractError("stage input collides with config.json")
        mounted = {**inputs, "config.json": config_path}
        expected_inputs = {name: sha256_file(path) for name, path in mounted.items()}
        for split, rows in contract.get("dataset", {}).get("splits", {}).items():
            for row in rows:
                key = f"{split}/{row['relative_path']}"
                if key in expected_inputs:
                    expected_inputs[key] = row["sha256"]
        for name, (_path, row) in assets.items():
            expected_inputs[name] = row["sha256"]
        context.emit("execution.stage_started", {"stage": stage, "bundle_sha256": spec["bundle_sha256"]})
        evidence = self.executor.run_stage(ExecutionBundle.from_dict(spec["bundle"]), stage,
            expected_bundle_digest=spec["bundle_sha256"], isolated_root=context.isolated_root,
            input_files=mounted, cancel_event=_CancellationSignal(context))
        identity = evidence.get("execution_id")
        if not isinstance(identity, str) or "/" in identity or not identity.startswith("stage-"):
            raise ContractError("executor returned an invalid stage identity")
        if evidence.get("stage") != stage or evidence.get("bundle_sha256") != spec["bundle_sha256"]:
            raise ContractError("executor returned a foreign stage or bundle")
        if evidence.get("evidence_sha256") != _digest({key: value for key, value in evidence.items() if key != "evidence_sha256"}):
            raise ContractError("stage execution evidence digest mismatch")
        evidence_dir = context.run_dir / "evidence" / "isolated_stages"
        evidence_dir.mkdir(parents=True, exist_ok=True)
        write_json(evidence_dir / f"{identity}.json", {"schema_version": "0.1", "task_id": context.task_id, "run_id": context.run_id, "execution": evidence})
        context.emit("execution.stage_finished", {"stage": stage, "execution_id": identity, "status": evidence.get("status"), "evidence_sha256": evidence["evidence_sha256"]})
        if evidence.get("executed") is True:
            observed_inputs = evidence.get("inputs")
            if not isinstance(observed_inputs, list) or len(observed_inputs) != len(expected_inputs) or {row.get("path"): row.get("sha256") for row in observed_inputs if isinstance(row, dict)} != expected_inputs:
                raise ContractError("worker input snapshots do not match the frozen dataset/model inputs")
        if not require_success:
            return evidence
        if evidence.get("status") == "cancelled":
            raise RunCancelled("isolated worker acknowledged cancellation")
        if evidence.get("status") != "completed" or evidence.get("executed") is not True or type(evidence.get("exit_code")) is not int or evidence["exit_code"] != 0 or evidence.get("container_removed") is not True:
            setup = evidence.get("setup_failure") or {}
            detail = (f"; {setup['code']}: required {setup['required_bytes']} bytes, approved {setup['limit_bytes']} bytes; revise scope and obtain a new approval"
                      if setup.get("code") == "input_bytes_exceed_approved_limit" else "")
            raise ContractError(f"isolated {stage} did not complete: {evidence.get('status', 'unknown')}{detail}")
        return evidence

    def qualify(self, contract: dict[str, Any], context: RunExecutionContext) -> dict[str, Any]:
        from .generic_data import generic_split_input_files
        self.validate_contract(contract)
        return self._stage(contract, "qualify", context, generic_split_input_files(contract["dataset"], ("train", "validation")), require_success=False)

    def train(self, contract: dict[str, Any]) -> Any:
        raise ContractError("generic training requires the canonical RunExecutionContext")

    def train_with_context(self, contract: dict[str, Any], context: RunExecutionContext) -> GenericTraining:
        from .generic_data import generic_split_input_files
        self.validate_contract(contract)
        evidence = self._stage(contract, "train", context, generic_split_input_files(contract["dataset"], ("train", "validation")))
        result = read_stage_json(context, evidence, "train_result.json")
        selected = result.get("selected_model")
        if not isinstance(selected, str) or not selected.strip():
            raise ContractError("train_result.selected_model must identify the selected candidate")
        candidates = result.get("validation_candidates")
        if not isinstance(candidates, dict) or not candidates or selected not in candidates:
            raise ContractError("validation_candidates must contain the selected model and named metrics")
        normalized = {}
        for name, values in candidates.items():
            if not isinstance(values, dict) or not values:
                raise ContractError("validation candidate metrics must be non-empty objects")
            normalized[name] = {metric: _finite(value, f"validation metric {metric}") for metric, value in values.items()}
        counts = result.get("split_counts")
        if not isinstance(counts, dict) or not {"train", "validation"}.issubset(counts):
            raise ContractError("train_result requires train and validation sample counts")
        split_counts = {key: _count(counts[key], f"{key} sample count") for key in ("train", "validation")}
        model_files = result.get("model_files")
        if not isinstance(model_files, list) or not model_files or any(not isinstance(path, str) for path in model_files) or len(set(model_files)) != len(model_files):
            raise ContractError("train_result.model_files must list unique model artifact paths")
        declared = {item["path"] for item in _spec(contract)["artifacts"] if item.get("stage", "train") == "train"}
        for path in model_files:
            if _relative(path) not in declared:
                raise ContractError("selected model file must be declared as a train-stage artifact")
            _verified_stage_file(context, evidence, path)
        evaluation_spec = _spec(contract)["evaluation"]
        return GenericTraining(selected, normalized, split_counts, model_files, evidence, context, [evidence], evaluation_spec.get("minimum_test_samples", 20), evaluation_spec["primary_metric"])

    def evaluate(self, training: GenericTraining, contract: dict[str, Any]) -> GenericEvaluation:
        from .generic_data import generic_split_input_files
        # Evaluate against earlier canonical Runs before this Run mounts test
        # data. The worker cannot clear or replace this host-owned lineage.
        test_lineage = _test_exposure_lineage(contract, training.context)
        model_inputs = {f"model/{path}": _verified_stage_file(training.context, training.stage_evidence, path) for path in training.model_files}
        evidence = self._stage(contract, "evaluate", training.context, {**generic_split_input_files(contract["dataset"], ("test",)), **model_inputs})
        result = read_stage_json(training.context, evidence, "evaluate_result.json")
        supplied = result.get("metrics")
        if not isinstance(supplied, dict) or not supplied:
            raise ContractError("evaluate_result.metrics must contain named finite metrics")
        observed = {key: _finite(value, f"evaluation metric {key}") for key, value in supplied.items()}
        count = _count(result.get("sample_count"), "evaluation sample_count")
        gates = {}
        for name, rule in _spec(contract)["evaluation"]["gates"].items():
            if name not in observed:
                raise ContractError(f"required evaluation metric is missing: {name}")
            gates[name] = observed[name] <= rule["threshold"] if rule["operator"] == "lte" else observed[name] >= rule["threshold"]
        failures = result.get("failure_samples", [])
        if not isinstance(failures, list) or len(failures) > 1000:
            raise ContractError("failure_samples must be a bounded list")
        metrics = {"schema_version": "0.2", "selected_model": training.selected_name,
                   "validation_candidates": training.validation_results, "clean_test": observed,
                   "split_counts": {**training.split_counts, "test": count},
                   "gate_checks": {**gates, "all_offline_gates_passed": bool(gates) and all(gates.values())},
                   "failure_count": len(failures), "stress_tests": {}, "test_contaminated": test_lineage["test_contaminated"],
                   "test_lineage": test_lineage, "contamination_reasons": test_lineage["reasons"],
                   "evaluation_execution_id": evidence["execution_id"], "evaluation_evidence_sha256": evidence["evidence_sha256"]}
        training.execution_records.append(evidence)
        return GenericEvaluation(metrics, evidence, failures)

    def package(self, training: GenericTraining, evaluation: GenericEvaluation, contract: dict[str, Any], artifact_dir: Path) -> dict[str, Any]:
        artifact_dir.mkdir(parents=True, exist_ok=False)
        spec = _spec(contract)
        records = []
        train_paths = {item["path"] for item in spec["artifacts"] if item.get("stage", "train") == "train"}
        if not set(training.model_files) <= train_paths:
            raise ContractError("selected checkpoint cannot include evaluation-stage artifacts")
        for declaration in spec["artifacts"]:
            path = declaration["path"]
            stage = declaration.get("stage", "train")
            evidence = training.stage_evidence if stage == "train" else evaluation.stage_evidence
            if evidence.get("stage") != stage or evidence.get("bundle_sha256") != spec["bundle_sha256"] or evidence.get("status") != "completed" or evidence.get("evidence_sha256") != _digest({key: value for key, value in evidence.items() if key != "evidence_sha256"}):
                raise ContractError("artifact producing stage or evidence identity does not match the frozen specification")
            source = _verified_stage_file(training.context, evidence, path)
            target = artifact_dir / _relative(path)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            recorded = next(row for row in evidence["artifacts"] if row["path"] == path)
            if sha256_file(target) != recorded["sha256"] or target.stat().st_size != recorded["bytes"]:
                raise ContractError("declared artifact changed while packaging")
            records.append({**declaration, "stage": stage, "source_execution_id": evidence["execution_id"],
                "source_execution_sha256": evidence["evidence_sha256"], "sha256": sha256_file(target), "bytes": target.stat().st_size})
        for relative, (source, row) in _asset_files(contract).items():
            target = artifact_dir / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            if sha256_file(target) != row["sha256"] or target.stat().st_size != row["bytes"]:
                raise ContractError("public base asset changed while packaging")
            records.append({"path": relative, "role": "base_model_dependency", "export": True, "sha256": row["sha256"], "bytes": row["bytes"]})
        for relative, text in spec["bundle"]["files"].items():
            target = artifact_dir / "source" / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
            records.append({"path": f"source/{relative}", "role": "inference_source", "export": True, "sha256": sha256_file(target), "bytes": target.stat().st_size})
        portable = {"schema_version": "0.1", "bundle": deepcopy(spec["bundle"]), "bundle_sha256": spec["bundle_sha256"],
                    "config": deepcopy(spec.get("config", {})), "inference": deepcopy(spec.get("inference", {})),
                    "model_manifest": MODEL_MANIFEST,
                    "base_assets": [{"asset_id": item["asset_id"], "manifest_sha256": item["manifest_sha256"], "files": deepcopy(item["files"])} for item in contract.get("execution_assets", [])]}
        for filename, value in (("generic_execution.json", portable), ("config.json", spec.get("config", {}))):
            target = artifact_dir / filename
            write_json(target, value)
            records.append({"path": filename, "role": "inference_configuration", "export": True, "sha256": sha256_file(target), "bytes": target.stat().st_size})
        model_manifest = {"schema_version": "0.1", "task_id": contract["task_id"], "run_id": training.context.run_id,
            "bundle_sha256": spec["bundle_sha256"], "selected_model": training.selected_name,
            "model_files": list(training.model_files), "artifacts": records,
            "inference": deepcopy(spec.get("inference", {})), "execution_environment": training.execution_environment}
        model_manifest["model_sha256"] = _digest(model_manifest)
        write_json(artifact_dir / MODEL_MANIFEST, model_manifest)
        write_json(artifact_dir / "metrics.json", evaluation.metrics)
        write_json(artifact_dir / "failure_samples.json", {"samples": evaluation.failure_samples})
        return deepcopy(evaluation.metrics)

    def predict(self, contract: dict[str, Any], *, model_dir: Path, input_files: Mapping[str, Path], context: RunExecutionContext) -> dict[str, Any]:
        model_manifest_path = _safe_file(model_dir, MODEL_MANIFEST)
        run_manifest = read_json(context.run_dir / "run_manifest.json")
        expected = run_manifest.get("artifacts", {}).get(MODEL_MANIFEST, {})
        if run_manifest.get("task_id") != context.task_id or run_manifest.get("run_id") != context.run_id or expected.get("sha256") != sha256_file(model_manifest_path) or expected.get("bytes") != model_manifest_path.stat().st_size:
            raise ContractError("generic model manifest no longer matches the canonical Run")
        manifest = _json(model_manifest_path)
        if manifest.get("task_id") != context.task_id or manifest.get("run_id") != context.run_id or manifest.get("bundle_sha256") != _spec(contract)["bundle_sha256"]:
            raise ContractError("generic model belongs to another task, run or execution bundle")
        if manifest.get("model_sha256") != _digest({key: value for key, value in manifest.items() if key != "model_sha256"}):
            raise ContractError("generic model manifest digest mismatch")
        inputs = {}
        rows = {row["path"]: row for row in manifest["artifacts"]}
        for path in manifest["model_files"]:
            source = _safe_file(model_dir, path)
            row = rows.get(path, {})
            if row.get("stage", "train") != "train":
                raise ContractError("prediction cannot load a checkpoint produced from final-test evaluation")
            if source.stat().st_size != row.get("bytes") or sha256_file(source) != row.get("sha256"):
                raise ContractError("generic model artifact changed")
            inputs[f"model/{path}"] = source
        for key, value in input_files.items():
            relative = _relative(key)
            if relative == "config.json" or relative.startswith(("model/", "train/", "validation/", "test/")):
                raise ContractError("prediction input collides with a protected input scope")
            source = Path(value).resolve()
            dataset_root = Path(str(contract.get("dataset", {}).get("root", ""))).resolve()
            if source == dataset_root or dataset_root in source.parents or model_dir.resolve() == source or model_dir.resolve() in source.parents:
                raise ContractError("prediction requires new input, not training data or model artifacts")
            inputs[relative] = Path(value)
        if not input_files:
            raise ContractError("generic prediction requires an explicit new input")
        evidence = self._stage(contract, "predict", context, inputs)
        result = read_stage_json(context, evidence, "infer_result.json")
        from .generic_io_schema import validate_output_result
        schema_validation = validate_output_result(result, _spec(contract)["inference"])
        if "prediction" not in result:
            raise ContractError("infer_result.prediction is required")
        artifacts = []
        outputs = result.get("artifacts", [])
        if not isinstance(outputs, list) or any(not isinstance(item, str) for item in outputs) or len(outputs) != len(set(outputs)):
            raise ContractError("inference artifacts must be distinct output paths")
        for relative in outputs:
            path = _verified_stage_file(context, evidence, relative)
            artifacts.append({"path": relative, "sha256": sha256_file(path), "bytes": path.stat().st_size, "private": True})
        return {"prediction": result["prediction"], "artifacts": artifacts, "model_sha256": manifest["model_sha256"],
                "output_schema_validation": schema_validation,
                "execution_id": evidence["execution_id"], "execution_evidence_sha256": evidence["evidence_sha256"], "stage_execution": evidence}

    def propose_strategies(self, metrics: dict[str, Any], contract: dict[str, Any]) -> list[StrategyProposal]:
        return []

    def apply_strategy(self, contract: dict[str, Any], strategy_id: str) -> dict[str, Any]:
        raise ContractError("generic implementation changes require a new reviewed execution spec and contract")

    def learning_report(self, contract: dict[str, Any], metrics: dict[str, Any], strategies: list[StrategyProposal]) -> str:
        return "# Training evidence\n\n" + json.dumps({"goal": contract["business_goal"], "selected_model": metrics["selected_model"], "test_metrics": metrics["clean_test"], "gates": metrics["gate_checks"]}, ensure_ascii=False, indent=2) + "\n"

    def deep_verify(self, artifact_dir: Path) -> list[str]:
        try:
            manifest = _json(_safe_file(artifact_dir, MODEL_MANIFEST))
            if manifest.get("model_sha256") != _digest({key: value for key, value in manifest.items() if key != "model_sha256"}):
                return ["generic model manifest digest mismatch"]
            by_path = {row["path"]: row for row in manifest["artifacts"]}
            if any(by_path.get(path, {}).get("stage", "train") != "train" for path in manifest["model_files"]):
                return ["generic selected checkpoint includes an evaluation-stage artifact"]
            for row in manifest["artifacts"]:
                path = _safe_file(artifact_dir, row["path"])
                if path.stat().st_size != row.get("bytes") or sha256_file(path) != row.get("sha256"):
                    return ["generic model artifact integrity mismatch"]
            return []
        except (ContractError, OSError, KeyError, TypeError, ValueError) as exc:
            return [f"generic artifact verification failed: {type(exc).__name__}"]


PLUGIN = GenericIsolatedRecipePlugin()
