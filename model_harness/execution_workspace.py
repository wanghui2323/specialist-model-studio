"""Task-owned engineering proposals feeding the existing training Run service.

Generated code is data here. Only the trusted OCI bridge executes it, after a
native approval and with an immutable task/data/code scope. Qualification is
engineering evidence, never a TrainingRun or model quality verdict.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from threading import Event, RLock
from typing import Any
from uuid import uuid4

from .errors import ContractError, HarnessError
from .io_utils import read_json, write_json

_ID = re.compile(r"^execution-[a-f0-9]{24}$")
_SHA = re.compile(r"^[a-f0-9]{64}$")


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def seal(record: dict[str, Any], field: str) -> dict[str, Any]:
    value = deepcopy(record)
    value.pop(field, None)
    value[field] = digest(value)
    return value


def verified(path: Path, field: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError("execution record not found")
    value = read_json(path)
    if not isinstance(value, dict) or value.get(field) != digest({k: v for k, v in value.items() if k != field}):
        raise ContractError("execution evidence digest changed")
    return value


def approval_record(value: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("actor") != "user" or value.get("verified_by") != "agent_bridge_token":
        raise ContractError("execution requires verified native user approval")
    checkpoint = str(value.get("checkpoint_id") or "").strip()
    token_hash = str(value.get("bridge_token_sha256") or "")
    if not checkpoint or len(checkpoint) > 256 or not _SHA.fullmatch(token_hash):
        raise ContractError("execution approval identity is incomplete")
    return {"actor": "user", "checkpoint_id": checkpoint, "verified_by": "agent_bridge_token",
            "bridge_token_sha256": token_hash, "decided_at": datetime.now(UTC).isoformat()}


class ExecutionWorkspace:
    def __init__(self, workspace: Any, materials: Any, *, executor: Any = None,
                 isolated_root: Path | None = None, image: str | None = None) -> None:
        from .isolated_execution import OCIExecutor
        self.workspace = workspace
        self.materials = materials
        self.executor = executor or OCIExecutor()
        from .execution_runtime import execution_root, execution_runtime_config
        config = execution_runtime_config()
        self.isolated_root = execution_root(Path.home() / ".local/share/specialist-model-studio/isolated-jobs", explicit=isolated_root)
        self.image = str(image or os.environ.get("MODEL_HARNESS_EXECUTION_IMAGE") or config.get("image") or "")
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="execution-qualification")
        self.lock = RLock()
        self.running: dict[str, tuple[Any, Event]] = {}
        self._recover()

    def _recover(self) -> None:
        for path in self.workspace.tasks_dir.glob("*/execution_proposals/execution-*/state.json"):
            state = read_json(path)
            if state.get("status") == "qualifying":
                state.update(status="interrupted", failure="service restarted during qualification")
                write_json(path, state)

    def close(self) -> None:
        with self.lock:
            for _, cancel in self.running.values():
                cancel.set()
        self.pool.shutdown(wait=True, cancel_futures=False)

    def _task(self, task_id: str, *, writing: bool = False) -> dict[str, Any]:
        value = read_json(self.workspace._task_path(task_id))
        if writing:
            self.workspace._require_task_mutable(value, "准备通用执行方案")
            if value.get("status") == "running":
                raise HarnessError("running task cannot change engineering implementation")
        return value

    def _dir(self, task_id: str, proposal_id: str) -> Path:
        self._task(task_id)
        if not isinstance(proposal_id, str) or not _ID.fullmatch(proposal_id):
            raise FileNotFoundError("execution proposal not found")
        parent = self.workspace._task_dir(task_id) / "execution_proposals"
        if parent.is_symlink():
            raise ContractError("execution proposal directory is unsafe")
        path = parent / proposal_id
        if path.is_symlink():
            raise ContractError("execution proposal directory is unsafe")
        return path

    def get(self, task_id: str, proposal_id: str) -> dict[str, Any]:
        path = self._dir(task_id, proposal_id)
        record = verified(path / "proposal.json", "proposal_sha256")
        if record.get("task_id") != task_id or record.get("proposal_id") != proposal_id:
            raise ContractError("execution proposal owner mismatch")
        state = read_json(path / "state.json")
        qualification = None
        qid = state.get("qualification_id")
        if qid:
            qpath = path / "qualifications" / str(qid) / "qualification.json"
            if qpath.is_file():
                qualification = verified(qpath, "qualification_sha256")
            else:
                qualification = {"qualification_id": qid, "status": "running" if state.get("status") == "qualifying" else state.get("status")}
        if qualification and isinstance(qualification.get("execution"), dict):
            execution = qualification["execution"]
            job_id = str(execution.get("job_directory") or "")
            log_info = execution.get("log") or {}
            if re.fullmatch(r"stage-[a-f0-9]{32}", job_id) and job_id == execution.get("execution_id"):
                path_to_log = self.isolated_root / job_id / "logs/stdio.log"
                if path_to_log.is_file() and not path_to_log.is_symlink() and path_to_log.stat().st_size <= 16 * 1024**2:
                    payload = path_to_log.read_bytes()
                    if hashlib.sha256(payload).hexdigest() == log_info.get("sha256"):
                        qualification = {**qualification, "log_tail": payload[-16_000:].decode("utf-8", errors="replace"),
                                         "log_is_untrusted_execution_output": True, "log_truncated": len(payload) > 16_000 or log_info.get("truncated", False)}
        return {**record, "status": state["status"], "qualification": qualification,
                "failure": state.get("failure"), "activated_at": state.get("activated_at")}

    def list(self, task_id: str) -> list[dict[str, Any]]:
        self._task(task_id)
        return [self.get(task_id, p.parent.name) for p in sorted(
            (self.workspace._task_dir(task_id) / "execution_proposals").glob("execution-*/proposal.json"))]

    def runtime_readiness(self) -> dict[str, Any]:
        """Observe the configured immutable image, without inspecting task state."""
        from .isolated_execution import ExecutionBundle
        probe = self.executor.probe()
        result = {"ready": False, "image_reference": self.image or None,
                  "runtime": probe, "reason": "isolation_runtime_unavailable"}
        if not probe.get("available"):
            return result
        result["reason"] = "immutable_execution_image_unavailable"
        try:
            # Validation only: neither this source nor any container is executed.
            ExecutionBundle.create(files={"probe.py": "pass"}, stages={"probe": ["python", "/workspace/source/probe.py"]}, image=self.image)
            observed = self.executor._query([probe["executable"], "image", "inspect", self.image, "--format",
                '{"id":{{json .Id}},"repo_digests":{{json .RepoDigests}},"architecture":{{json .Architecture}},"os":{{json .Os}}}'])
            image = json.loads(observed.stdout) if observed.returncode == 0 else None
            matches = isinstance(image, dict) and (
                image.get("id") == self.image if self.image.startswith("sha256:")
                else any(str(item).endswith("@" + self.image.split("@", 1)[1]) for item in image.get("repo_digests") or []))
            if matches and isinstance(image.get("id"), str) and re.fullmatch(r"sha256:[0-9a-f]{64}", image["id"]):
                result.update(ready=True, reason=None, image=image)
        except (ContractError, OSError, ValueError, KeyError, subprocess.SubprocessError):
            pass
        return result

    def info(self, task_id: str) -> dict[str, Any]:
        from .generic_protocol import execution_path_guide, execution_result_protocol, execution_spec_schema
        task = self._task(task_id)
        readiness = self.runtime_readiness()
        probe = readiness["runtime"]
        image_ready = readiness["ready"]
        environment = None
        if image_ready:
            try:
                observed = self.executor._query([probe["executable"], "info", "--format", '{"memory_bytes":{{.MemTotal}},"cpu_count":{{.NCPU}}}'])
                measured = json.loads(observed.stdout) if observed.returncode == 0 else {}
                environment = {"image": self.image, "ready": True, "device": "cpu", **measured,
                               "recommended_limits": {"memory_bytes": min(3 * 1024**3, max(512 * 1024**2, int(measured.get("memory_bytes", 1024**3) * 0.7))),
                                                      "cpus": min(2, measured.get("cpu_count", 1)), "timeout_seconds": 600,
                                                      "max_input_bytes": 1024**3, "max_artifact_bytes": 1024**3}}
            except (OSError, ValueError, subprocess.SubprocessError):
                pass
        return {"task_id": task_id, "spec_revision": task["current_spec_revision"],
                "capability": task.get("capability_request", {}), "runtime": probe,
                "available_environments": [environment or {"image": self.image, "ready": True, "device": "cpu"}] if image_ready else [],
                "materials": [{key: record.get(key) for key in ("material_id", "inspection_sha256", "status", "file")}
                              for record in self.materials.list(task_id)], "execution_spec_schema": execution_spec_schema(),
                "proposals": [{k: v.get(k) for k in ("proposal_id", "proposal_sha256", "status", "qualification", "failure")} for v in self.list(task_id)],
                "protocol": {**execution_path_guide(), **execution_result_protocol(),
                    "source_directory": "/workspace/source", "input_directory": "/workspace/input", "output_directory": "/workspace/output",
                    "stage_inputs": {"qualify": ["train", "validation", "assets", "config.json"], "train": ["train", "validation", "assets", "config.json"],
                                     "evaluate": ["test", "model", "assets", "config.json"], "predict": ["sample", "model", "assets", "config.json"]},
                    "outputs": {"qualify": "qualification.json", "train": "train_result.json", "evaluate": "evaluate_result.json", "predict": "infer_result.json"},
                    "qualification_required_checks": ["input_validation", "invalid_input_rejected", "parameter_update", "model_reload", "prediction_shape"],
                    "train_result": {"selected_model": "exact key in validation_candidates, not a weights filename", "validation_candidates": "candidate -> flat finite numeric metrics; no nested diagnostics", "split_counts": "actual train/validation counts; test is measured only by evaluate", "model_files": "existing declared train-stage reload dependencies"},
                    "evaluate_result": {"metrics": "named finite numbers", "sample_count": "actual final-test count", "failure_samples": "bounded diagnostic records"},
                    "predict_result": {"prediction": "JSON compatible output", "artifacts": "optional declared media outputs"},
                    "instructions": "Write actual task-specific implementation code in bundle.files. Each stage starts in an empty /workspace/output working directory; bundled source is read-only under /workspace/source. Use /workspace/source/<file> in script argv, or explicitly set up an equivalent module/entrypoint; bare run.py is not automatically resolved to the source mount. Stages are explicit argv, not host commands. Train and select only on train/validation. Reload the selected model in evaluate/predict. Inspect true errors and create a new proposal revision to repair them. Never use final-test to choose code or parameters. Do not ask the user to develop code or provide host paths."}}

    def create(self, task_id: str, *, base_spec_revision: int, execution_spec: dict[str, Any], request_id: str) -> dict[str, Any]:
        from .generic_protocol import validate_execution_spec
        from .generic_data import create_generic_dataset
        if not isinstance(request_id, str) or not re.fullmatch(r"[A-Za-z0-9._:-]{1,160}", request_id):
            raise ContractError("invalid execution proposal request_id")
        spec = validate_execution_spec(execution_spec)
        with self.workspace._lock:
            task = self._task(task_id, writing=True)
            if type(base_spec_revision) is not int or task["current_spec_revision"] != base_spec_revision:
                raise HarnessError("task specification changed before proposal creation")
            goal = self.workspace._ensure_spec_revision(task)
            capability = task.get("capability_request", {})
            for key in ("modality", "objective", "training_route"):
                if capability.get(key) and spec.get("capability", {}).get(key, capability[key]) != capability[key]:
                    raise ContractError(f"execution proposal changes the selected {key}")
            spec["capability"] = {**capability, **spec.get("capability", {})}
            request = {"task_id": task_id, "base_spec_revision": base_spec_revision, "spec": spec, "request_id": request_id}
            request_hash = digest(request)
            proposal_id = "execution-" + digest({"task_id": task_id, "request_id": request_id})[:24]
            path = self._dir(task_id, proposal_id)
            if path.exists():
                if not (path / "proposal.json").exists():
                    # A failed import or crash before the immutable proposal
                    # commit leaves only task-owned staging bytes. Rebuild the
                    # same request instead of routing forever to a missing 404.
                    shutil.rmtree(path)
                else:
                    committed = verified(path / "proposal.json", "proposal_sha256")
                    if committed.get("request_sha256") != request_hash:
                        raise HarnessError("execution request_id belongs to a different proposal")
                    if not (path / "state.json").exists():
                        # No qualification/activation is inferred from a lost
                        # projection: a fresh native approval is still needed.
                        write_json(path / "state.json", {"status": "proposed", "qualification_id": None})
                    return self.get(task_id, proposal_id)
            if len(self.list(task_id)) >= 32:
                raise ContractError("task engineering proposal budget exceeded")
            path.mkdir(parents=True, mode=0o700)
            try:
                imported = create_generic_dataset(path, self.materials, task_id, spec["data_mapping"])
                assets = []
                for asset_id in spec.get("asset_ids", []):
                    assets.append(self.workspace.execution_assets.get(task_id, asset_id, private=True))
                record = seal({"schema_version": "0.1", "object_type": "ExecutionProposal", "task_id": task_id,
                               "proposal_id": proposal_id, "base_spec_revision": base_spec_revision,
                               "goal_sha256": digest(goal), "execution_spec": spec,
                               "dataset": imported.contract_dataset, "dataset_report": imported.report,
                               "assets": assets, "request_id": request_id, "request_sha256": request_hash,
                               "created_at": datetime.now(UTC).isoformat()}, "proposal_sha256")
                write_json(path / "proposal.json", record)
                write_json(path / "state.json", {"status": "proposed", "qualification_id": None})
                return self.get(task_id, proposal_id)
            except Exception:
                if not (path / "proposal.json").exists() and path.exists():
                    shutil.rmtree(path)
                raise

    def _current(self, task_id: str, proposal_id: str, expected: str) -> dict[str, Any]:
        task = self._task(task_id, writing=True)
        value = self.get(task_id, proposal_id)
        if value["proposal_sha256"] != expected:
            raise ContractError("execution proposal digest mismatch")
        goal = self.workspace._ensure_spec_revision(task)
        if value["base_spec_revision"] != task["current_spec_revision"] or value["goal_sha256"] != digest(goal):
            raise HarnessError("execution proposal targets an obsolete goal")
        return value

    def start_qualification(self, task_id: str, proposal_id: str, *, expected_proposal_sha256: str,
                            approval: dict[str, Any], local_experiment_only: bool = False) -> dict[str, Any]:
        granted = approval_record(approval)
        with self.workspace._lock:
            proposal = self._current(task_id, proposal_id, expected_proposal_sha256)
            if any(asset.get("license_review_required") for asset in proposal.get("assets", [])) and local_experiment_only is not True:
                raise ContractError("asset license metadata is unresolved; explicit local-experiment-only review is required")
            if proposal["status"] in {"qualifying", "qualified", "activated"}:
                return proposal
            path = self._dir(task_id, proposal_id)
            prior = list((path / "qualifications").glob("qualification-*/approval.json"))
            if len(prior) >= 3:
                raise ContractError("proposal qualification retry budget exceeded")
            qid = "qualification-" + uuid4().hex[:24]
            qpath = path / "qualifications" / qid
            qpath.mkdir(parents=True, mode=0o700)
            write_json(qpath / "approval.json", seal({**granted, "task_id": task_id, "proposal_id": proposal_id,
                                                     "proposal_sha256": proposal["proposal_sha256"], "qualification_id": qid,
                                                     "local_experiment_only": local_experiment_only}, "approval_sha256"))
            write_json(path / "state.json", {"status": "qualifying", "qualification_id": qid})
            cancel = Event()
            future = self.pool.submit(self._qualify, task_id, proposal_id, qid, cancel)
            with self.lock:
                self.running[qid] = future, cancel
            return self.get(task_id, proposal_id)

    def _contract(self, proposal: dict[str, Any]) -> dict[str, Any]:
        from .generic_recipe import GenericIsolatedRecipePlugin
        contract = deepcopy(GenericIsolatedRecipePlugin().template())
        contract.update(task_id=proposal["task_id"], business_goal=self._task(proposal["task_id"])["business_goal"],
                        execution_spec=proposal["execution_spec"], dataset=proposal["dataset"], execution_assets=proposal.get("assets", []))
        if any(asset.get("license_review_required") for asset in proposal.get("assets", [])):
            contract["release_restrictions"] = ["model_asset_license_review_pending"]
        return contract

    def _qualify(self, task_id: str, proposal_id: str, qid: str, cancel: Event) -> None:
        from .generic_recipe import GenericIsolatedRecipePlugin, read_stage_json
        from .plugin_api import RunExecutionContext
        path = self._dir(task_id, proposal_id)
        qpath = path / "qualifications" / qid
        result: dict[str, Any] = {"schema_version": "0.1", "object_type": "QualificationEvidence", "qualification_id": qid,
                                  "task_id": task_id, "proposal_id": proposal_id, "status": "failed", "checks": [],
                                  "creates_training_run": False, "failure": None}
        result["local_experiment_only"] = verified(qpath / "approval.json", "approval_sha256").get("local_experiment_only", False)
        try:
            proposal = self.get(task_id, proposal_id)
            result["proposal_sha256"] = proposal["proposal_sha256"]
            context = RunExecutionContext(task_id=task_id, run_id=qid, run_dir=qpath,
                                          cancel_check=cancel.is_set, isolated_root=self.isolated_root)
            plugin = GenericIsolatedRecipePlugin(executor=self.executor)
            execution = plugin.qualify(self._contract(proposal), context)
            result["execution"] = execution
            if execution.get("status") == "cancelled":
                result["status"] = "cancelled"
            if execution.get("status") != "completed" or execution.get("executed") is not True:
                raise ContractError("isolated qualification did not complete: " + str(execution.get("errors")))
            report = read_stage_json(context, execution, "qualification.json")
            checks = report.get("checks")
            required = {"input_validation", "invalid_input_rejected", "parameter_update", "model_reload", "prediction_shape"}
            if not isinstance(checks, list) or any(not isinstance(c, dict) for c in checks):
                raise ContractError("qualification checks must be explicit records")
            successful = {str(c.get("name")) for c in checks if c.get("passed") is True}
            if report.get("valid") is not True or not required <= successful or any(c.get("passed") is not True for c in checks):
                raise ContractError("qualification must pass data, invalid-input, parameter-update, reload and prediction checks")
            result.update(status="passed", checks=checks, report=report)
        except Exception as exc:
            result["failure"] = f"{type(exc).__name__}: {exc}"[:4000]
        finally:
            result["created_at"] = datetime.now(UTC).isoformat()
            result = seal(result, "qualification_sha256")
            with self.workspace._lock:
                write_json(qpath / "qualification.json", result)
                state = read_json(path / "state.json")
                if state.get("qualification_id") == qid:
                    state.update(status="qualified" if result["status"] == "passed" else "cancelled" if result["status"] == "cancelled" else "qualification_failed", failure=result.get("failure"))
                    write_json(path / "state.json", state)
            with self.lock:
                self.running.pop(qid, None)

    def background_actions(self, task_id: str) -> list[dict[str, Any]]:
        values = []
        for proposal in self.list(task_id):
            if proposal["status"] == "qualifying":
                q = proposal.get("qualification") or {}
                values.append({"action_id": f"qualification:{q.get('qualification_id')}", "action_type": "execution_qualification",
                               "task_id": task_id, "proposal_id": proposal["proposal_id"], "qualification_id": q.get("qualification_id"),
                               "status": "running", "domain_status": "running", "running": True, "worker_running": True,
                               "cancel_requested": False, "updated_at_utc": proposal["created_at"]})
        return values

    def cancel_task(self, task_id: str) -> None:
        for proposal in self.list(task_id):
            qid = (proposal.get("qualification") or {}).get("qualification_id")
            with self.lock:
                active = self.running.get(qid)
                if active:
                    active[1].set()

    def activate(self, task_id: str, proposal_id: str, *, expected_proposal_sha256: str,
                 qualification_id: str, expected_qualification_sha256: str, approval: dict[str, Any]) -> dict[str, Any]:
        granted = approval_record(approval)
        with self.workspace._lock:
            proposal = self._current(task_id, proposal_id, expected_proposal_sha256)
            qualification = proposal.get("qualification") or {}
            if (qualification.get("qualification_id") != qualification_id
                    or qualification.get("qualification_sha256") != expected_qualification_sha256
                    or qualification.get("status") != "passed"
                    or qualification.get("task_id") != task_id
                    or qualification.get("proposal_id") != proposal_id
                    or qualification.get("proposal_sha256") != proposal["proposal_sha256"]):
                raise ContractError("activation requires the exact passed qualification evidence")
            path = self._dir(task_id, proposal_id)
            task = self._task(task_id, writing=True)
            if task.get("current_execution_proposal_id") == proposal_id and proposal["status"] == "activated":
                return {"proposal": proposal, "task": self.workspace.get_task(task_id), "dataset_id": task.get("dataset_id")}
            contract = self._contract(proposal)
            contract["execution_binding"] = {"proposal_id": proposal_id, "proposal_sha256": proposal["proposal_sha256"],
                                              "qualification_id": qualification_id, "qualification_sha256": expected_qualification_sha256,
                                              "base_spec_revision": proposal["base_spec_revision"]}
            contract["diagnostics"]["minimum_test_samples"] = proposal["execution_spec"]["evaluation"]["minimum_test_samples"]
            from .contracts import validate_contract
            validate_contract(contract, registry=self.workspace.runs.registry)
            write_json(path / "activation.json", seal({**granted, "task_id": task_id, "proposal_id": proposal_id,
                                                       "proposal_sha256": proposal["proposal_sha256"], "qualification_sha256": expected_qualification_sha256}, "activation_sha256"))
            dataset_id = proposal["dataset"]["dataset_id"]
            task.update(recipe_id="generic-isolated-execution", recipe_source="qualified-execution", capability_status="matched",
                        dataset_id=dataset_id, data_adapter_id="generic-files", status="data_ready", contract_confirmed=False,
                        confirmations={}, confirmed_contract_sha256=None, confirmed_contract_revision_id=None,
                        current_approval_decision_id=None, contract_stale=False,
                        current_execution_proposal_id=proposal_id, updated_at_utc=datetime.now(UTC).isoformat())
            task["dataset_history"] = list(dict.fromkeys([*task.get("dataset_history", []), dataset_id]))
            # Dataset evidence remains task-owned and is projected via the same
            # existing dataset-report path used by every Recipe.
            target = self.workspace._task_dir(task_id) / "datasets" / dataset_id
            target.mkdir(parents=True, exist_ok=True)
            write_json(target / "dataset_report.json", proposal["dataset_report"])
            if task.get("current_run_id"):
                task["last_run_id"] = task.pop("current_run_id")
                task["current_run_id"] = None
            write_json(self.workspace._contract_path(task_id), contract)
            self.workspace._record_contract_revision(task, contract)
            self.workspace._resolve_missing_recipe_evidence(task_id, action="qualified_generic_execution_activated", recipe_id="generic-isolated-execution")
            write_json(self.workspace._task_path(task_id), task)
            write_json(path / "state.json", {"status": "activated", "qualification_id": qualification_id, "activated_at": datetime.now(UTC).isoformat()})
            return {"proposal": self.get(task_id, proposal_id), "task": self.workspace.get_task(task_id), "dataset_id": dataset_id}

    def authorize_contract(self, task_id: str, contract: dict[str, Any], *, require_activated: bool = True) -> dict[str, Any]:
        binding = contract.get("execution_binding") or {}
        proposal = self._current(task_id, str(binding.get("proposal_id") or ""), str(binding.get("proposal_sha256") or ""))
        q = proposal.get("qualification") or {}
        valid_states = {"activated"} if require_activated else {"qualified", "activated"}
        if (proposal["status"] not in valid_states or q.get("status") != "passed"
                or q.get("qualification_sha256") != binding.get("qualification_sha256")
                or q.get("qualification_id") != binding.get("qualification_id")
                or q.get("task_id") != task_id or q.get("proposal_id") != proposal["proposal_id"]
                or q.get("proposal_sha256") != proposal["proposal_sha256"]
                or binding.get("base_spec_revision") != proposal["base_spec_revision"]):
            raise HarnessError("current isolated implementation is not qualified and activated")
        if contract.get("execution_spec") != proposal["execution_spec"] or contract.get("dataset") != proposal["dataset"] or contract.get("execution_assets", []) != proposal.get("assets", []):
            raise HarnessError("isolated implementation/data/assets drifted from the activated version")
        activation = verified(self._dir(task_id, proposal["proposal_id"]) / "activation.json", "activation_sha256")
        if activation.get("task_id") != task_id or activation.get("proposal_id") != proposal["proposal_id"] or activation.get("proposal_sha256") != proposal["proposal_sha256"] or activation.get("qualification_sha256") != q["qualification_sha256"] or activation.get("actor") != "user" or activation.get("verified_by") != "agent_bridge_token":
            raise ContractError("activation approval scope changed")
        return deepcopy(binding)
