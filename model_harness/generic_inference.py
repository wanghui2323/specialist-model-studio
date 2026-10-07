"""New-input inference for the trusted OCI bridge, with existing evidence IDs."""
from __future__ import annotations

import json
import mimetypes
import shutil
import time
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4
from urllib.parse import quote

from .errors import ContractError
from .execution_workspace import digest
from .generic_recipe import GenericIsolatedRecipePlugin, read_stage_json, _verified_stage_file
from .io_utils import read_json, sha256_file, write_json
from .plugin_api import RunExecutionContext


def run_generic_sample(adapter: Any, sample: Any, *, sample_type: str | None, expected: Any, cancel_check: Callable[[], bool] | None = None) -> dict[str, Any]:
    from .evidence import EvidenceError, InferenceCheck, _integrity_snapshot
    from .sample_inference import SampleInferenceBlocked
    started = time.perf_counter()
    check_id = "sample-" + uuid4().hex[:12]
    input_sha = None
    try:
        integrity = _integrity_snapshot(adapter.run_dir)
        state, manifest = integrity["state"], integrity["manifest"]
        if state.get("status") != "completed" or integrity["status"] != "passed":
            raise EvidenceError("generic prediction requires completed verified run artifacts")
        contract = read_json(adapter.run_dir / "task_contract.json")
        if contract.get("recipe") != "generic-isolated-execution" or manifest.get("recipe") != contract["recipe"] or contract["task_id"] != state["task_id"]:
            raise EvidenceError("generic run identity mismatch")
        if sample_type not in {None, "generic"}:
            raise EvidenceError("generic model requires its frozen input declaration")
        declaration = contract["execution_spec"]["inference"]
        path, input_sha, size = adapter._external_file(sample, contract, maximum_bytes=declaration["max_bytes"], kind="generic")
        if path.suffix.lower() not in declaration["extensions"]:
            raise EvidenceError("new input extension is outside the frozen declaration")
        from .generic_io_schema import validate_input_file
        input_schema_validation = validate_input_file(path, declaration)
        # The staged blob is opaque. Its original name is not necessary for
        # decoding, so this predictable basename is part of the worker protocol.
        input_name = "sample/input" + path.suffix.lower()
        from .execution_runtime import execution_root
        context = RunExecutionContext(task_id=state["task_id"], run_id=state["run_id"], run_dir=adapter.run_dir,
            cancel_check=cancel_check,
            isolated_root=execution_root(Path.home() / ".local/share/specialist-model-studio/isolated-jobs"))
        plugin = GenericIsolatedRecipePlugin()
        result = plugin.predict(contract, model_dir=adapter.run_dir / "artifacts", input_files={input_name: path}, context=context)
        if cancel_check is not None and cancel_check():
            raise ContractError("sample inference was stopped; no prediction was accepted")
        reference_match = None if expected is None else result["prediction"] == expected
        if reference_match is False:
            raise EvidenceError("generic new-input prediction does not match the explicit reference")
        artifacts = []
        for item in result.get("artifacts", []):
            source = _verified_stage_file(context, result["stage_execution"], item["path"])
            target = adapter.reports_dir / check_id / item["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            if sha256_file(target) != item["sha256"]:
                raise EvidenceError("generic prediction media changed while being saved")
            artifacts.append({"name": item["path"], "sha256": item["sha256"], "bytes": item["bytes"],
                              "media_type": mimetypes.guess_type(item["path"])[0] or "application/octet-stream",
                              "url": f"/tasks/{state['task_id']}/runs/{state['run_id']}/sample-inferences/{check_id}/files/{quote(item['path'], safe='/')}"})
        inference_id = "inference-" + uuid4().hex[:12]
        elapsed = round((time.perf_counter() - started) * 1000, 6)
        inference = {"schema_version": "0.1", "check_id": inference_id, "task_id": state["task_id"], "run_id": state["run_id"],
                     "status": "passed", "blocked": False, "recipe": contract["recipe"],
                     "model": {"artifact": "generic_model.json", "sha256": result["model_sha256"]},
                     "input": {"sha256": input_sha, "size_bytes": size, "type": "generic"},
                     "input_schema_validation": input_schema_validation,
                     "output_schema_validation": result["output_schema_validation"],
                     "output": result["prediction"], "output_sha256": digest(result["prediction"]),
                     "reference_match": reference_match, "elapsed_ms": elapsed,
                     "execution_id": result["execution_id"], "execution_evidence_sha256": result["execution_evidence_sha256"],
                     "created_at": result["stage_execution"]["created_at"]}
        InferenceCheck(adapter.run_dir)._persist(inference)
        report = {"schema_version": "0.1", "check_id": check_id, "task_id": state["task_id"], "run_id": state["run_id"],
                  "recipe": contract["recipe"], "status": "passed", "blocked": False,
                  "sample": {"type": "generic", "source_name": path.name, "sha256": input_sha, "size_bytes": size},
                  "input_schema_validation": input_schema_validation,
                  "output_schema_validation": result["output_schema_validation"],
                  "contract": {"sha256": sha256_file(adapter.run_dir / "task_contract.json")}, "model": inference["model"],
                  "prediction": result["prediction"], "prediction_sha256": inference["output_sha256"],
                  "reference_match": reference_match, "inference_check_id": inference_id, "artifacts": artifacts,
                  "execution_id": result["execution_id"], "elapsed_ms": elapsed, "created_at": inference["created_at"]}
        adapter._persist(report)
        return report
    except Exception as exc:
        report = adapter._blocked_report(check_id, adapter._public_error(exc), started,
                                         source_name=adapter._safe_source_name(sample), input_sha256=input_sha, inspection=None)
        adapter._persist(report)
        raise SampleInferenceBlocked(str(exc), report) from exc


def generic_sample_artifact(adapter: Any, check_id: str, name: str) -> Path:
    report = adapter.get(check_id)
    records = [item for item in report.get("artifacts", []) if item.get("name") == name]
    if len(records) != 1 or not name or Path(name).is_absolute() or ".." in Path(name).parts or "\\" in name:
        raise FileNotFoundError("sample output artifact not found")
    root = adapter.reports_dir / check_id
    path = root / name
    if path.is_symlink() or root.resolve() not in path.resolve().parents or not path.is_file() or sha256_file(path) != records[0]["sha256"]:
        raise ContractError("sample output artifact changed")
    return path
