"""Bounded, task-agnostic declaration for a trusted OCI execution bridge.

Business capability and configuration are open JSON. Safety constraints apply to
paths, resources, identities, explicit split selection and output declarations;
there is no model-family or training-framework allowlist here.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from copy import deepcopy
from pathlib import PurePosixPath
from typing import Any, Mapping

from .errors import ContractError
from .isolated_execution import ExecutionBundle

SPLITS = ("train", "validation", "test")
MAX_MAPPING_ENTRIES = 128
MAX_SELECTED_ROWS = 100_000
MAX_SPEC_BYTES = 3 * 1024 * 1024
_SHA = re.compile(r"^[0-9a-f]{64}$")
_MATERIAL = re.compile(r"^material-[0-9a-f]{24}$")
_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,95}$")
_EXTENSION = re.compile(r"^\.[a-z0-9][a-z0-9_.-]{0,20}$")


def _metric_name(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip()) and len(value) <= 96 and not any(ord(char) < 32 or ord(char) == 127 for char in value)


def _finite_number(value: Any) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def canonical_digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def safe_relative_path(value: Any, *, directory: bool = False) -> str:
    if not isinstance(value, str) or not value or len(value) > 512 or "\\" in value or ":" in value or any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ContractError("generic paths must be bounded relative POSIX paths")
    selected = value[:-1] if directory and value.endswith("/") else value
    path = PurePosixPath(selected)
    if path.is_absolute() or any(part in {"", ".", ".."} or len(part) > 255 for part in selected.split("/")):
        raise ContractError("generic paths must not traverse directories")
    return path.as_posix() + ("/" if directory else "")


def _json_copy(value: Any, *, label: str, max_bytes: int = MAX_SPEC_BYTES) -> Any:
    nodes = 0
    def inspect(item: Any, depth: int) -> None:
        nonlocal nodes
        nodes += 1
        if nodes > 200_000 or depth > 24:
            raise ContractError(f"{label} exceeds JSON structural limits")
        if item is None or isinstance(item, (bool, int)):
            return
        if isinstance(item, float):
            if not math.isfinite(item):
                raise ContractError(f"{label} contains a non-finite number")
            return
        if isinstance(item, str):
            return
        if isinstance(item, list):
            for child in item:
                inspect(child, depth + 1)
            return
        if isinstance(item, dict):
            if any(not isinstance(key, str) or not key or len(key) > 512 for key in item):
                raise ContractError(f"{label} has invalid JSON object keys")
            for child in item.values():
                inspect(child, depth + 1)
            return
        raise ContractError(f"{label} must contain JSON values only")
    inspect(value, 0)
    try:
        payload = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
    except (ValueError, UnicodeError, OverflowError):
        raise ContractError(f"{label} cannot be encoded as bounded JSON") from None
    if len(payload) > max_bytes:
        raise ContractError(f"{label} exceeds its byte limit")
    return json.loads(payload)


def validate_data_mapping(raw: Any) -> list[dict[str, Any]]:
    value = _json_copy(raw, label="data_mapping", max_bytes=1024 * 1024)
    if not isinstance(value, list) or not 1 <= len(value) <= MAX_MAPPING_ENTRIES:
        raise ContractError("data_mapping must contain 1 to 128 explicit selections")
    result = []
    for item in value:
        allowed = {"material_id", "inspection_sha256", "split", "member_paths", "member_prefixes", "csv_rows"}
        if not isinstance(item, dict) or set(item) - allowed:
            raise ContractError("invalid data_mapping entry fields")
        if not isinstance(item.get("material_id"), str) or not _MATERIAL.fullmatch(item["material_id"]):
            raise ContractError("data_mapping requires an observed material_id")
        if not isinstance(item.get("inspection_sha256"), str) or not _SHA.fullmatch(item["inspection_sha256"]):
            raise ContractError("data_mapping requires the exact material inspection SHA")
        if item.get("split") not in SPLITS:
            raise ContractError("split must be train, validation or test")
        selected = {key: item[key] for key in ("material_id", "inspection_sha256", "split")}
        for field in ("member_paths", "member_prefixes"):
            if field in item:
                paths = item[field]
                if not isinstance(paths, list) or not 1 <= len(paths) <= 1024:
                    raise ContractError(f"{field} must contain bounded explicit paths")
                normalized = [safe_relative_path(path, directory=field == "member_prefixes") for path in paths]
                if len(set(path.casefold() for path in normalized)) != len(normalized):
                    raise ContractError(f"{field} has duplicate or case-colliding paths")
                selected[field] = sorted(normalized)
        if "csv_rows" in item:
            if "member_paths" in item or "member_prefixes" in item:
                raise ContractError("csv_rows applies only to a standalone CSV, not ZIP members")
            rows = item["csv_rows"]
            if isinstance(rows, dict):
                if set(rows) != {"start", "stop"} or any(type(rows[key]) is not int for key in rows) or not 0 <= rows["start"] < rows["stop"] <= MAX_SELECTED_ROWS:
                    raise ContractError("csv_rows range is a zero-based half-open {start,stop} interval")
                selected["csv_rows"] = {"start": rows["start"], "stop": rows["stop"]}
            elif isinstance(rows, list) and 1 <= len(rows) <= MAX_SELECTED_ROWS and all(type(row) is int and 0 <= row < MAX_SELECTED_ROWS for row in rows):
                if len(rows) != len(set(rows)):
                    raise ContractError("csv_rows contains duplicate indices")
                selected["csv_rows"] = sorted(rows)
            else:
                raise ContractError("csv_rows must be explicit zero-based row indices or {start,stop}")
        result.append(selected)
    selected_splits = {item["split"] for item in result}
    if not {"train", "test"} <= selected_splits:
        raise ContractError("data_mapping requires separate nonempty train and test selections")
    return result


def validate_execution_spec(raw: Any) -> dict[str, Any]:
    value = _json_copy(raw, label="execution_spec")
    fields = {"schema_version", "bundle", "bundle_sha256", "capability", "config", "data_mapping", "evaluation", "artifacts", "inference", "description", "asset_ids"}
    if not isinstance(value, dict):
        raise ContractError("execution_spec must be an object")
    unknown = sorted(set(value) - fields)
    if unknown:
        raise ContractError("unknown execution_spec field(s): " + ", ".join(unknown) + "; read execution_spec_schema for allowed fields")
    if value.get("schema_version", "0.1") != "0.1":
        raise ContractError("unsupported execution_spec schema")
    bundle = ExecutionBundle.from_dict(value.get("bundle", {}))
    if value.get("bundle_sha256") is not None and value["bundle_sha256"] != bundle.digest:
        raise ContractError("execution_spec bundle_sha256 does not match its source and commands")
    if not {"qualify", "train", "evaluate", "predict"} <= set(dict(bundle.stages)):
        raise ContractError("execution bundle requires qualify, train, evaluate and predict stage argv declarations")
    capability = value.get("capability")
    if not isinstance(capability, dict) or not capability:
        raise ContractError("capability must describe the intended input/output objective as an open JSON object")
    config = value.get("config", {})
    if not isinstance(config, dict):
        raise ContractError("config must be an open JSON object")
    description = value.get("description", "")
    if not isinstance(description, str) or not description.strip() or len(description) > 4000:
        raise ContractError("execution_spec requires a bounded description")
    evaluation = value.get("evaluation")
    if not isinstance(evaluation, dict) or set(evaluation) != {"primary_metric", "gates", "minimum_test_samples", "test_unit"}:
        raise ContractError("evaluation requires primary_metric, gates, minimum_test_samples and test_unit")
    primary = evaluation["primary_metric"]
    if not _metric_name(primary):
        raise ContractError("invalid primary_metric identifier")
    gates = evaluation["gates"]
    if not isinstance(gates, dict) or not 1 <= len(gates) <= 32 or primary not in gates:
        raise ContractError("evaluation gates must include the primary metric")
    for name, gate in gates.items():
        if not _metric_name(name) or not isinstance(gate, dict) or set(gate) != {"operator", "threshold"}:
            raise ContractError("metric gates require named operator and threshold")
        threshold = gate["threshold"]
        if not isinstance(gate["operator"], str) or gate["operator"] not in {"lte", "gte"} or not _finite_number(threshold):
            raise ContractError("metric gate needs lte/gte and a finite numeric threshold")
    minimum = evaluation["minimum_test_samples"]
    if type(minimum) is not int or not 1 <= minimum <= 10_000_000:
        raise ContractError("minimum_test_samples must be a positive bounded integer")
    if not isinstance(evaluation["test_unit"], str) or not evaluation["test_unit"].strip() or len(evaluation["test_unit"]) > 256:
        raise ContractError("test_unit must explicitly describe one counted evaluation unit")
    asset_ids = value.get("asset_ids", [])
    if not isinstance(asset_ids, list) or len(asset_ids) > 32 or any(not isinstance(asset_id, str) or not re.fullmatch(r"asset-[0-9a-f]{24}", asset_id) for asset_id in asset_ids) or len(asset_ids) != len(set(asset_ids)):
        raise ContractError("asset_ids must list bounded observed immutable model assets")
    artifacts = value.get("artifacts")
    if not isinstance(artifacts, list) or not 1 <= len(artifacts) <= 128:
        raise ContractError("artifacts must be a bounded explicit path/role/export manifest")
    seen = set()
    for artifact in artifacts:
        if not isinstance(artifact, dict) or not {"path", "role", "export"} <= set(artifact) or set(artifact) - {"path", "role", "export", "stage"}:
            raise ContractError("each artifact requires path, role, export and optional train/evaluate stage")
        artifact["path"] = safe_relative_path(artifact["path"])
        if artifact["path"].casefold() in seen:
            raise ContractError("artifact paths collide")
        seen.add(artifact["path"].casefold())
        if not isinstance(artifact["role"], str) or not _NAME.fullmatch(artifact["role"]) or type(artifact["export"]) is not bool:
            raise ContractError("artifact role must be a bounded identifier and export an explicit boolean")
        stage = artifact.get("stage", "train")
        if stage not in ("train", "evaluate"):
            raise ContractError("training artifacts may only come from train or evaluate")
        if stage == "evaluate" and artifact["role"].lower() in {"model", "weights", "checkpoint", "adapter", "model_weights", "model_checkpoint", "model_state", "optimizer_state"}:
            raise ContractError("model checkpoints must be produced by train, never final-test evaluation")
    inference = value.get("inference")
    if not isinstance(inference, dict) or set(inference) - {"extensions", "max_bytes", "schema", "output_schema"}:
        raise ContractError("invalid inference declaration")
    extensions = inference.get("extensions")
    if not isinstance(extensions, list) or not 1 <= len(extensions) <= 16 or any(not isinstance(ext, str) or not _EXTENSION.fullmatch(ext) for ext in extensions) or len(set(extensions)) != len(extensions):
        raise ContractError("inference extensions must be explicit lowercase suffixes")
    max_bytes = inference.get("max_bytes")
    if type(max_bytes) is not int or not 1 <= max_bytes <= 25 * 1024 * 1024:
        raise ContractError("inference.max_bytes must be 1 byte to 25 MiB")
    if any(field in inference and not isinstance(inference[field], dict) for field in ("schema", "output_schema")):
        raise ContractError("inference schemas must be JSON objects")
    from .generic_io_schema import validate_schema_definition
    for field in ("schema", "output_schema"):
        if field in inference:
            validate_schema_definition(inference[field], label=f"inference.{field}")
    return {"schema_version": "0.1", "bundle": bundle.to_dict(), "bundle_sha256": bundle.digest,
        "capability": deepcopy(capability), "config": deepcopy(config), "description": description.strip(),
        "data_mapping": validate_data_mapping(value.get("data_mapping")), "evaluation": deepcopy(evaluation),
        "artifacts": deepcopy(artifacts), "inference": deepcopy(inference), "asset_ids": list(asset_ids)}


def execution_path_guide() -> dict[str, Any]:
    """Describe actual OCI paths without normalizing caller argv or source."""
    return {
        "working_directory": "/workspace/output",
        "working_directory_initial_state": "empty writable directory created independently for each stage",
        "source_reference_policy": "bundle.files keys are relative to the read-only /workspace/source mount, not the working directory. Reference bundled scripts as /workspace/source/<relative-file>, or explicitly arrange an equivalent entrypoint/module path in your argv.",
        "source_argv_example": ["python", "/workspace/source/run.py", "qualify"],
        "relative_argv_policy": "argv is passed unchanged. For example, python run.py qualify looks for /workspace/output/run.py, which is absent initially; the executor does not copy source there or rewrite relative arguments.",
    }


def execution_result_protocol() -> dict[str, Any]:
    """Discoverable worker output contracts; examples are shapes, not evidence.

    Runtime acceptance remains in ExecutionWorkspace and GenericIsolatedRecipe.
    JSON Schema cannot express candidate-key membership or compare metrics with
    another frozen document, so those rules are stated separately and explicitly.
    """
    dialect = "https://json-schema.org/draft/2020-12/schema"
    required_checks = ["input_validation", "invalid_input_rejected", "parameter_update", "model_reload", "prediction_shape"]
    relative = {"type": "string", "minLength": 1,
                "description": "Existing regular file relative to this stage's output directory; no absolute path or traversal."}
    metrics = {"type": "object", "minProperties": 1, "additionalProperties": {"type": "number"},
               "description": "Flat metric-name to finite JSON number map. No booleans, null, strings, NaN/Infinity, arrays or nested objects."}
    qualify = {"$schema": dialect, "type": "object", "required": ["valid", "checks"],
        "properties": {"valid": {"type": "boolean"}, "checks": {"type": "array", "items": {
            "type": "object", "required": ["name", "passed"],
            "properties": {"name": {"type": "string"}, "passed": {"type": "boolean"}}, "additionalProperties": True}}},
        "allOf": [{"if": {"properties": {"valid": {"const": True}}}, "then": {"properties": {"checks": {
            "items": {"properties": {"passed": {"const": True}}},
            "allOf": [{"contains": {"properties": {"name": {"const": name}}, "required": ["name"]}} for name in required_checks]}}}}],
        "additionalProperties": True}
    train = {"$schema": dialect, "type": "object", "required": ["selected_model", "validation_candidates", "split_counts", "model_files"],
        "properties": {"selected_model": {"type": "string", "pattern": r"\S", "description": "The selected candidate KEY in validation_candidates; not the checkpoint filename."},
            "validation_candidates": {"type": "object", "minProperties": 1, "additionalProperties": deepcopy(metrics)},
            "split_counts": {"type": "object", "required": ["train", "validation"], "properties": {
                "train": {"type": "integer", "minimum": 0}, "validation": {"type": "integer", "minimum": 0}}, "additionalProperties": True,
                "description": "Actual counted training/validation units. Use validation=0 when absent. Omit test: only evaluate measures final-test sample_count; the host ignores a training claim about it."},
            "model_files": {"type": "array", "minItems": 1, "uniqueItems": True, "items": deepcopy(relative)}}, "additionalProperties": True}
    evaluate = {"$schema": dialect, "type": "object", "required": ["metrics", "sample_count"],
        "properties": {"metrics": deepcopy(metrics), "sample_count": {"type": "integer", "minimum": 0},
            "failure_samples": {"type": "array", "maxItems": 1000}}, "additionalProperties": True}
    predict = {"$schema": dialect, "type": "object", "required": ["prediction"],
        "properties": {"prediction": {}, "artifacts": {"type": "array", "uniqueItems": True, "items": deepcopy(relative)}}, "additionalProperties": True}
    examples = {
        "qualify": {"valid": True, "checks": [{"name": name, "passed": True} for name in required_checks]},
        "train": {"selected_model": "candidate_a", "validation_candidates": {
            "candidate_a": {"objective_error": 0.12}, "candidate_b": {"objective_error": 0.2}},
            "split_counts": {"train": 3, "validation": 1}, "model_files": ["model/custom.weights"]},
        "evaluate": {"metrics": {"objective_error": 0.15}, "sample_count": 2, "failure_samples": []},
        "predict": {"prediction": {"value": 0.4}, "artifacts": []},
    }
    filenames = {"qualify": "qualification.json", "train": "train_result.json", "evaluate": "evaluate_result.json", "predict": "infer_result.json"}
    requirements = {
        "qualify": ["Acceptance requires exit code 0, valid=true and every check record passed=true, including all five required names. checks is an ARRAY; status, all_checks_passed or check_results never replace valid/checks.",
                    "Each passed check must come from actual input rejection, parameter change, saved-model reload or prediction evidence. Record a failure as valid=false with failed checks and exit nonzero; never copy example success values as evidence.",
                    "Exercise the same input parser, reload and prediction implementation used by the real predict entrypoint, including the exact declared file encodings. Test each allowed schema/extension variant (JSON values, objects, or UTF-8 text where declared); a hand-built in-memory prediction that bypasses the real input path is insufficient. Use only train/validation examples, never final-test data."],
        "train": ["selected_model MUST equal an existing key of validation_candidates. Keep configurations, histories, status strings and nested diagnostics outside each candidate's flat numeric metric map.",
                  "Every model_files path must be declared in execution_spec.artifacts with stage=train (or omitted), and must exist in this stage output. These are the only trained files mounted for evaluate and predict. Use the minimal reload dependencies; training reports are not model weights.",
                  "Portable delivery requires every model_files dependency to be exportable. A private/export=false dependency makes delivery incomplete. Keep raw data and private test references out of the portable model; do not make private data public just to pass packaging."],
        "evaluate": ["metrics MUST contain every exact key in the frozen execution_spec.evaluation.gates. A gate_table, nested metrics, aliases, or all_passed flag does not replace these top-level numeric values. The host recomputes gates; do not lower thresholds.",
                     "sample_count is the actual number of frozen test units evaluated. Satisfying the JSON shape does not prove the minimum sample count or quality gates passed."],
        "predict": ["prediction is required. execution_spec.inference.output_schema validates this COMPLETE envelope, not prediction alone. artifacts is an optional list of existing relative output filenames, not artifact descriptor objects.",
                    "Validate new input against the same IDs, units and shapes the implementation accepts. Derive entity/label vocabulary from legitimate training evidence; do not invent enum values. Reject unknown inputs clearly."],
    }
    contracts = {stage: {"filename": filenames[stage], "schema": schema, "example": examples[stage], "requirements": requirements[stage]}
                 for stage, schema in (("qualify", qualify), ("train", train), ("evaluate", evaluate), ("predict", predict))}
    contracts["qualify"]["failure_example"] = {"valid": False, "checks": [{"name": "model_reload", "passed": False}], "failure": "saved model could not be reloaded"}
    return {"stage_result_contracts": contracts,
        "result_example_policy": "All examples are illustrative JSON shapes with invented numbers. Compute results from actual isolated execution; examples are not scripts, pretrained results, gates or evidence.",
        "result_encoding": "Write UTF-8 JSON objects, at most 4 MiB per result, under the specified filename in /workspace/output. Convert date objects and framework scalars/tensors to JSON-compatible values; reject non-finite numbers.",
        "stage_transfer_rules": [
            "Input budgets count ALL staged bytes: approved public base assets, selected trained reload files, stage data and config together. Evaluate/predict may need both base assets and trained files (e.g. adapters); budget them explicitly rather than copying the smaller qualify budget. If the bound is too small, create and requalify a reviewed proposal; never silently raise it.",
            "Every stage starts with an empty output directory. Previous outputs are absent unless explicitly mounted by the host; no shared working directory or automatic artifact propagation.",
            "A train model_files entry model/custom.weights is mounted for evaluate/predict at /workspace/input/model/model/custom.weights: the host prepends model/ to the FULL declared relative path.",
            "artifacts.stage selects the real producing stage (train or evaluate; default train). Evaluation reports belong to evaluate. Declared files must exist in that stage; a report in another stage does not satisfy the declaration.",
            "Evaluation-stage artifacts are never model_files or automatic predict inputs. Do not place held-out labels, raw samples or private evaluation context into an exported checkpoint. Final-test data must not change learned parameters or code selection.",
            "Plan required pre-test history/context before freezing the proposal: evaluation mounts test plus the declared train model files, never the original training/validation directories. New prediction gets only the trained reload dependencies plus its explicit sample. If prediction requires fresh private context, declare it in the new-input contract instead of expecting evaluation outputs to reappear.",
            "Source files, config and approved public base assets are automatically packaged separately. Mark raw data, held-out per-record labels/predictions and private logs export=false with an appropriate private role; a custom role name is not a privacy guarantee.",
        ]}


def execution_spec_schema() -> dict[str, Any]:
    """Discovery schema for Agent authors; capability remains an open object."""
    relative = {"type": "string", "minLength": 1, "maxLength": 512,
        "description": "Safe relative POSIX path. No absolute path, backslash, drive, control character, empty/dot/dot-dot segment. ZIP paths keep original spelling; no glob expansion."}
    argv = {"type": "array", "minItems": 1, "maxItems": 128,
        "items": {"type": "string", "minLength": 1, "maxLength": 4096},
        "description": "Explicit container argv; first item is entrypoint. Initial cwd is /workspace/output, an empty per-stage writable directory. Bundled scripts live read-only under /workspace/source: use e.g. [python, /workspace/source/run.py, qualify], or explicitly configure an equivalent entrypoint/module path. Relative arguments are passed unchanged and are not resolved against bundle.files."}
    gate = {"type": "object", "additionalProperties": False, "required": ["operator", "threshold"],
        "properties": {"operator": {"enum": ["lte", "gte"]}, "threshold": {"type": "number"}}}
    limits = {"memory_bytes": (64 * 1024**2, 64 * 1024**3, "integer"), "cpus": (.1, 32, "number"),
        "pids": (8, 512, "integer"), "timeout_seconds": (.1, 86400, "number"),
        "max_log_bytes": (1024, 16 * 1024**2, "integer"), "max_artifact_bytes": (1024, 1024**3, "integer"),
        "max_artifact_files": (1, 1024, "integer"), "max_input_bytes": (1, 4 * 1024**3, "integer"),
        "tmpfs_bytes": (1024**2, 1024**3, "integer")}
    selection = {"type": "object", "additionalProperties": False,
        "required": ["material_id", "inspection_sha256", "split"], "properties": {
            "material_id": {"type": "string", "pattern": "^material-[0-9a-f]{24}$", "description": "Observed owner-scoped MaterialInspection identity."},
            "inspection_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$", "description": "inspection_sha256 from that material, not its file.sha256."},
            "split": {"enum": list(SPLITS)},
            "member_paths": {"type": "array", "minItems": 1, "maxItems": 1024, "uniqueItems": True, "items": relative, "description": "Exact files selected from ZIP. Unselected members never enter the Dataset."},
            "member_prefixes": {"type": "array", "minItems": 1, "maxItems": 1024, "uniqueItems": True, "items": relative, "description": "Explicit ZIP directory prefixes such as train/; boundary is a path separator, never substring or glob."},
            "csv_rows": {"oneOf": [
                {"type": "array", "minItems": 1, "maxItems": MAX_SELECTED_ROWS, "uniqueItems": True, "items": {"type": "integer", "minimum": 0, "maximum": MAX_SELECTED_ROWS - 1}},
                {"type": "object", "additionalProperties": False, "required": ["start", "stop"], "properties": {"start": {"type": "integer", "minimum": 0, "maximum": MAX_SELECTED_ROWS - 1}, "stop": {"type": "integer", "minimum": 1, "maximum": MAX_SELECTED_ROWS}}}],
                "description": "Standalone CSV data-row indices, zero-based excluding header and blank lines, or half-open {start,stop} with start < stop. Cannot combine with ZIP selectors. Omit to select the entire standalone file."}},
        "description": "Train and test selections are required, validation optional. No source row/member or identical record/file bytes may overlap splits. Original relative names are preserved under /workspace/input/<split>/."}
    return {"$schema": "https://json-schema.org/draft/2020-12/schema", "title": "Generic isolated model execution specification",
        "type": "object", "additionalProperties": False,
        "required": ["bundle", "capability", "data_mapping", "evaluation", "artifacts", "inference", "description"],
        "properties": {
            "schema_version": {"const": "0.1", "default": "0.1"},
            "bundle": {"type": "object", "additionalProperties": False, "required": ["files", "stages", "image"], "properties": {
                "schema_version": {"const": "0.1", "default": "0.1"},
                "files": {"type": "object", "minProperties": 1, "maxProperties": 128, "additionalProperties": {"type": "string"}, "description": "Relative filename -> complete UTF-8 source text, at most 2 MiB total. A key run.py is mounted at /workspace/source/run.py; initial cwd /workspace/output contains no source files. Implement the actual requested task; this is not a host plugin or code stub."},
                "stages": {"type": "object", "required": ["qualify", "train", "evaluate", "predict"], "minProperties": 4, "maxProperties": 16, "propertyNames": {"pattern": "^[a-z][a-z0-9_-]{0,47}$"}, "additionalProperties": argv},
                "image": {"type": "string", "pattern": "^(?:[A-Za-z0-9][A-Za-z0-9._:/-]*@)?sha256:[0-9a-f]{64}$", "description": "Immutable local image ID or registry digest from an observed available environment. Tags alone are not execution identities."},
                "limits": {"type": "object", "additionalProperties": False, "properties": {key: {"type": kind, "minimum": low, "maximum": high} for key, (low, high, kind) in limits.items()}, "description": "Default maximum budget for each individual stage, not a total workflow budget. Omitted limits use bounded executor defaults. tmpfs_bytes must not exceed memory_bytes."},
                "stage_limits": {"type": "object", "maxProperties": 16, "propertyNames": {"pattern": "^[a-z][a-z0-9_-]{0,47}$"},
                    "additionalProperties": {"type": "object", "additionalProperties": False, "properties": {key: {"type": kind, "minimum": low, "maximum": high} for key, (low, high, kind) in limits.items()}},
                    "description": "Optional tighter budgets by declared stage. Every value must be <= the default limits; unspecified fields inherit them. For qualification 60 seconds and training 180 seconds, use limits.timeout_seconds=180 and stage_limits.qualify.timeout_seconds=60. Omission preserves legacy descriptor digests."}}},
            "bundle_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$", "description": "Optional exact digest; omit rather than invent. Server calculates the normalized bundle digest and rejects mismatch."},
            "capability": {"type": "object", "minProperties": 1, "additionalProperties": True, "description": "Open business objective and input/output semantics. Preserve the selected modality, objective and training_route. No model-family enum."},
            "config": {"type": "object", "additionalProperties": True, "default": {}, "description": "Open bounded JSON parameters, available as /workspace/input/config.json; no secrets or host paths."},
            "asset_ids": {"type": "array", "maxItems": 32, "uniqueItems": True, "default": [], "items": {"type": "string", "pattern": "^asset-[0-9a-f]{24}$"}, "description": "Observed task-owned immutable acquisition receipts; central binding verifies bytes and ownership."},
            "data_mapping": {"type": "array", "minItems": 2, "maxItems": MAX_MAPPING_ENTRIES, "items": selection},
            "evaluation": {"type": "object", "additionalProperties": False, "required": ["primary_metric", "gates", "minimum_test_samples", "test_unit"], "properties": {
                "primary_metric": {"type": "string", "minLength": 1, "maxLength": 96},
                "gates": {"type": "object", "minProperties": 1, "maxProperties": 32, "additionalProperties": gate, "description": "Metric-name -> gate, including primary_metric. Thresholds are frozen and reviewed; never lower a failed gate automatically."},
                "minimum_test_samples": {"type": "integer", "minimum": 1, "maximum": 10000000}, "test_unit": {"type": "string", "minLength": 1, "maxLength": 256}}},
            "artifacts": {"type": "array", "minItems": 1, "maxItems": 128, "items": {"type": "object", "additionalProperties": False, "required": ["path", "role", "export"], "properties": {"path": relative, "role": {"type": "string", "pattern": "^[A-Za-z][A-Za-z0-9_.-]{0,95}$"}, "export": {"type": "boolean"}, "stage": {"enum": ["train", "evaluate"], "default": "train", "description": "Producing stage. Named final-test reports/predictions belong to evaluate; selected model/checkpoint files must belong to train. Predict outputs are new-input evidence, not training artifacts."}}}, "description": "Exact relative output paths, roles and producing stages. Omitted stage means train and stays compatible with existing specs. export is an export candidate, not permission to publish raw data or authorize a download."},
            "inference": {"type": "object", "additionalProperties": False, "required": ["extensions", "max_bytes"], "properties": {"extensions": {"type": "array", "minItems": 1, "maxItems": 16, "uniqueItems": True, "items": {"type": "string", "pattern": "^\\.[a-z0-9][a-z0-9_.-]{0,20}$"}}, "max_bytes": {"type": "integer", "minimum": 1, "maximum": 25 * 1024 * 1024},
                "schema": {"type": "object", "description": "Optional Draft 2020-12 schema, <=128 KiB, one document with local JSON pointer $ref/$dynamicRef only; no external retrieval or nested $id. Host validates .json as parsed JSON and .txt as one UTF-8 string. CSV/media/other raw formats require worker validation; extensions never imply row decoding. Omission means no declared schema check. format/content annotations are not asserted."},
                "output_schema": {"type": "object", "description": "Optional Draft 2020-12 schema for the COMPLETE infer_result.json envelope: {prediction: ..., artifacts?: [relative_output_path, ...]}. Host validates this before accepting prediction or copying media. It does not apply to prediction alone. Same offline reference and size policy as schema."}}},
            "description": {"type": "string", "minLength": 1, "maxLength": 4000}},
        "x-protocol": {**execution_path_guide(), "source": "/workspace/source", "input": "/workspace/input", "output": "/workspace/output",
            "result_contracts_location": "execution_workspace.protocol.stage_result_contracts (schemas, examples and cross-document requirements)",
            "stage_inputs": {"qualify": ["train", "validation", "config.json", "assets"], "train": ["train", "validation", "config.json", "assets"], "evaluate": ["test", "model", "config.json", "assets"], "predict": ["sample", "model", "config.json", "assets"]},
            "stage_outputs": {"qualify": "qualification.json", "train": "train_result.json", "evaluate": "evaluate_result.json", "predict": "infer_result.json"},
            "inference_schema_policy": {"dialect": "https://json-schema.org/draft/2020-12/schema", "references": "local_json_pointer_only_no_retrieval", "host_inputs": {".json": "parsed JSON value", ".txt": "one UTF-8 string"}, "other_inputs": "opaque bytes; worker must validate domain/record structure", "output_schema_target": "complete infer_result.json envelope", "omitted_schema": "not_declared, never verified", "quality_gates": "unchanged; schema validation does not assess model quality"},
            "test_policy": "Final-test bytes are physically absent from qualify/train mounts. Qualification and code repair must not use final-test for selection."}}
