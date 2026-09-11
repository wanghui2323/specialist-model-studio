#!/usr/bin/env python3
"""Opt-in live acceptance for the v0.9 L1 model-source workflow.

The script is deliberately inert unless ``MH_LIVE_ACCEPTANCE=1``.  A live run
uses the product HTTP API and the real official Hugging Face/GitHub providers,
but never executes source code and only downloads bounded static documents.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.error import HTTPError
from urllib.parse import quote
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EVIDENCE_PATH = (
    ROOT / "plans" / "v0.9-universal-byom" / "l1-evidence.json"
)
COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
MAX_ACCEPTED_REPOSITORY_BYTES = 50 * 1024 * 1024
BINDING_POLL_TIMEOUT_SECONDS = 90.0
BINDING_POLL_INTERVAL_SECONDS = 0.05
OWNED_PATHS: tuple[str, ...] = (
    "scripts/verify_v09_l1_live.py",
    "scripts/check_v09_status.py",
    "tests/test_verify_v09_l1_live.py",
    "model_harness/model_sources.py",
    "model_harness/model_source_store.py",
    "model_harness/github_source.py",
    "model_harness/huggingface_source.py",
    "model_harness/repository_analysis.py",
    "model_harness/repository_analysis_store.py",
    "model_harness/training_plans.py",
    "model_harness/training_plan_compiler.py",
    "model_harness/blockers.py",
    "model_harness/workspace.py",
    "model_harness/server.py",
    "plans/v0.9-universal-byom/requirements.md",
    "plans/v0.9-universal-byom/acceptance-contract.md",
)

PUBLIC_CASES: tuple[dict[str, str], ...] = (
    {
        "case_id": "huggingface-public-tag",
        "provider": "huggingface",
        "repository": "Fachuan/orientation-classifier",
        "requested_revision": "v1.0-acc996",
        "search_query": "orientation classifier",
        "source_reference": "https://huggingface.co/Fachuan/orientation-classifier",
        "official_origin": "https://huggingface.co",
        "catalog_operation": "HfApi.list_models",
    },
    {
        "case_id": "github-public-branch",
        "provider": "github",
        "repository": "explainingai-code/VAE-Pytorch",
        "requested_revision": "main",
        "search_query": "repo:explainingai-code/VAE-Pytorch",
        "source_reference": "https://github.com/explainingai-code/VAE-Pytorch",
        "official_origin": "https://api.github.com",
        "catalog_operation": "GET /search/repositories",
    },
)


class LiveAcceptanceFailure(RuntimeError):
    """A sanitized acceptance assertion failure."""


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise LiveAcceptanceFailure(message)


def _verified_blocker_evidence(
    value: Any,
    *,
    expected_task_id: str,
    expected_stage: str,
    expected_code: str,
) -> dict[str, Any]:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from model_harness.blockers import verify_blocker_evidence
    from model_harness.errors import ContractError

    try:
        sealed = verify_blocker_evidence(value, allow_active_projection=True)
    except ContractError as error:
        raise LiveAcceptanceFailure(
            f"invalid sealed BlockerEvidence: {error}"
        ) from error
    _require(value.get("active") is True, "blocker evidence is not active")
    _require(sealed["task_id"] == expected_task_id, "wrong blocker task")
    _require(sealed["stage"] == expected_stage, "wrong blocker stage")
    _require(sealed["code"] == expected_code, "wrong canonical blocker code")
    return sealed


def _has_verified_blocker_evidence(
    item: Any,
    *,
    expected_stage: str,
    expected_code: str,
) -> bool:
    if not isinstance(item, Mapping):
        return False
    task_id = item.get("task_id")
    blocker = item.get("blocker")
    if not isinstance(task_id, str) or not isinstance(blocker, Mapping):
        return False
    projected = dict(blocker)
    projected["active"] = True
    try:
        _verified_blocker_evidence(
            projected,
            expected_task_id=task_id,
            expected_stage=expected_stage,
            expected_code=expected_code,
        )
    except LiveAcceptanceFailure:
        return False
    return True


def _git_head() -> str | None:
    try:
        value = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip().lower()
    except (OSError, subprocess.SubprocessError):
        return None
    return value if COMMIT_PATTERN.fullmatch(value) else None


def _secret_values() -> tuple[str, ...]:
    names = (
        "MH_L1_HF_TOKEN",
        "MH_L1_GITHUB_TOKEN",
        "MH_L1_PRIVATE_TOKEN",
    )
    return tuple(value for name in names if (value := os.environ.get(name)))


def _scrub(value: Any, secrets: Iterable[str]) -> Any:
    selected_secrets = tuple(secret for secret in secrets if secret)
    if isinstance(value, Mapping):
        return {
            str(key): _scrub(item, selected_secrets)
            for key, item in value.items()
            if str(key).lower() not in {"authorization", "token", "access_token"}
        }
    if isinstance(value, (list, tuple)):
        return [_scrub(item, selected_secrets) for item in value]
    if isinstance(value, str):
        result = value
        for secret in selected_secrets:
            result = result.replace(secret, "[REDACTED]")
            result = result.replace(quote(secret, safe=""), "[REDACTED]")
        return re.sub(
            r"(?i)bearer\s+[A-Za-z0-9._~+/=-]+",
            "Bearer [REDACTED]",
            result,
        )
    return value


def _atomic_json(path: Path, value: Mapping[str, Any], secrets: Iterable[str]) -> None:
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        _scrub(dict(value), secrets),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ) + "\n"
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        handle.write(payload)
        temporary = Path(handle.name)
    os.replace(temporary, path)


def _directory_bytes(root: Path) -> bytes:
    chunks: list[bytes] = []
    for path in sorted(root.rglob("*")):
        if path.is_file():
            chunks.append(path.read_bytes())
    return b"".join(chunks)


class ApiTrace:
    """Record product API status and timing without recording request headers."""

    def __init__(self) -> None:
        self.entries: list[dict[str, Any]] = []

    def request(self, client: Any, method: str, path: str, **kwargs: Any) -> Any:
        started = time.monotonic()
        response = client.request(method, path, **kwargs)
        self.entries.append(
            {
                "method": method.upper(),
                "path": path,
                "http_status": int(response.status_code),
                "elapsed_ms": round((time.monotonic() - started) * 1000, 2),
            }
        )
        return response


def _expect_status(response: Any, expected: int, operation: str) -> dict[str, Any]:
    if int(response.status_code) != expected:
        detail = response.text[:500]
        raise LiveAcceptanceFailure(
            f"{operation}: expected HTTP {expected}, got {response.status_code}: {detail}"
        )
    try:
        value = response.json()
    except ValueError as error:
        raise LiveAcceptanceFailure(f"{operation}: response is not JSON") from error
    if not isinstance(value, dict):
        raise LiveAcceptanceFailure(f"{operation}: response is not an object")
    return value


def _headers(provider: str, token: str | None) -> dict[str, str]:
    if not token:
        return {}
    if provider == "github":
        return {"X-GitHub-Token": token}
    if provider == "huggingface":
        return {"X-HF-Token": token}
    raise LiveAcceptanceFailure("unsupported provider")


def _create_task(trace: ApiTrace, client: Any, label: str) -> dict[str, Any]:
    response = trace.request(
        client,
        "POST",
        "/tasks",
        json={
            "name": f"v0.9 L1 live {label}",
            "business_goal": "验证用户搜索、选择并绑定一个公开训练来源",
            "capability_request": {
                "modality": "image",
                "objective": "classification",
                "target_kind": "multiclass",
            },
        },
    )
    task = _expect_status(response, 201, "create task")["task"]
    _require(
        task.get("capability_decision", {}).get("status") == "resolved",
        "acceptance task spec was not resolved",
    )
    _require(isinstance(task.get("current_spec_revision"), int), "missing spec revision")
    return task


def _resolve_direct(
    trace: ApiTrace,
    client: Any,
    *,
    task: Mapping[str, Any],
    case: Mapping[str, str],
    token: str | None,
) -> dict[str, Any]:
    response = trace.request(
        client,
        "POST",
        f"/tasks/{task['task_id']}/model-source-resolutions",
        json={
            "source_reference": case["source_reference"],
            "requested_revision": case["requested_revision"],
            "base_spec_revision": task["current_spec_revision"],
        },
        headers=_headers(case["provider"], token),
    )
    return _expect_status(response, 201, "resolve fixed revision")["resolution"]


def _bind(
    trace: ApiTrace,
    client: Any,
    *,
    task: Mapping[str, Any],
    resolution: Mapping[str, Any],
    provider: str,
    token: str | None,
) -> dict[str, Any]:
    response = trace.request(
        client,
        "POST",
        (
            f"/tasks/{task['task_id']}/model-source-resolutions/"
            f"{resolution['resolution_id']}/bind"
        ),
        json={
            "approval_confirmed": True,
            "expected_resolved_commit": resolution["resolved_commit"],
            "base_spec_revision": task["current_spec_revision"],
        },
        headers=_headers(provider, token),
    )
    accepted = _expect_status(response, 202, "queue fixed source binding")
    attempt = accepted.get("binding_attempt")
    _require(isinstance(attempt, Mapping), "binding response omitted its attempt")
    attempt_record = attempt.get("attempt")
    _require(
        isinstance(attempt_record, Mapping),
        "binding response omitted its immutable attempt record",
    )
    attempt_id = str(attempt_record.get("attempt_id", ""))
    _require(bool(attempt_id), "binding response omitted its attempt id")
    expected_poll_url = (
        f"/tasks/{task['task_id']}/model-binding-attempts/{attempt_id}"
    )
    _require(
        accepted.get("poll_url") == expected_poll_url,
        "binding response returned a non-canonical poll URL",
    )

    deadline = time.monotonic() + BINDING_POLL_TIMEOUT_SECONDS
    while True:
        attempt_record = attempt.get("attempt")
        state = attempt.get("current_state")
        _require(
            isinstance(attempt_record, Mapping) and isinstance(state, Mapping),
            "binding attempt projection is incomplete",
        )
        _require(
            attempt_record.get("task_id") == task["task_id"]
            and attempt_record.get("attempt_id") == attempt_id,
            "binding attempt identity changed while polling",
        )
        status = str(state.get("status", ""))
        if status == "completed":
            break
        if status in {"failed", "cancelled", "canceled"}:
            failure = state.get("failure")
            code = (
                str(failure.get("code", "unknown"))
                if isinstance(failure, Mapping)
                else "unknown"
            )
            raise LiveAcceptanceFailure(
                f"bind fixed source reached terminal {status}: {code}"
            )
        _require(
            status in {"queued", "running"},
            f"binding attempt returned an unknown state: {status or 'missing'}",
        )
        if time.monotonic() >= deadline:
            raise LiveAcceptanceFailure("bind fixed source timed out")
        if BINDING_POLL_INTERVAL_SECONDS > 0:
            time.sleep(BINDING_POLL_INTERVAL_SECONDS)
        polled = trace.request(client, "GET", expected_poll_url)
        attempt = _expect_status(
            polled, 200, "poll fixed source binding"
        ).get("binding_attempt")
        _require(
            isinstance(attempt, Mapping),
            "binding poll response omitted its attempt",
        )

    result = state.get("result")
    _require(isinstance(result, Mapping), "completed binding omitted its result")
    binding_revision_id = str(result.get("binding_revision_id", ""))
    analysis_id = str(result.get("analysis_id", ""))
    _require(bool(binding_revision_id), "completed binding omitted its revision id")
    _require(bool(analysis_id), "completed binding omitted its analysis id")

    binding_payload = _expect_status(
        trace.request(
            client,
            "GET",
            f"/tasks/{task['task_id']}/model-bindings/current",
        ),
        200,
        "read completed model binding",
    )
    binding = binding_payload.get("binding")
    _require(isinstance(binding, Mapping), "current binding response is incomplete")
    _require(
        binding.get("binding_revision_id") == binding_revision_id,
        "completed attempt and current binding revision do not match",
    )
    _require(
        binding.get("resolution_id") == resolution["resolution_id"],
        "completed binding points to a different resolution",
    )

    analysis_payload = _expect_status(
        trace.request(
            client,
            "GET",
            f"/tasks/{task['task_id']}/repository-analyses/{analysis_id}",
        ),
        200,
        "read completed repository analysis",
    )
    analysis = analysis_payload.get("analysis")
    _require(isinstance(analysis, Mapping), "analysis response is incomplete")
    _require(
        analysis.get("analysis_id") == analysis_id,
        "completed attempt and analysis detail do not match",
    )
    return {
        "binding": dict(binding),
        "analysis": dict(analysis),
        "binding_attempt": dict(attempt),
    }


def _binding_static_facts(workspace: Any, result: Mapping[str, Any]) -> dict[str, Any]:
    binding = result["binding"]
    context = workspace.model_source_store.binding_context(
        str(binding["task_id"]), str(binding["binding_revision_id"])
    )
    _require(context is not None, "binding context is missing")
    snapshot = context["snapshot"]
    files = list(snapshot.get("files", []))
    documents = list(snapshot.get("documents", []))
    lfs_paths = {
        str(item.get("path")) for item in files if item.get("lfs_sha256") is not None
    }
    document_paths = {str(item.get("path")) for item in documents}
    _require(not (lfs_paths & document_paths), "an LFS file was downloaded as a document")
    return {
        "snapshot_id": str(snapshot["snapshot_id"]),
        "snapshot_digest": str(snapshot["content_digest"]),
        "file_count": len(files),
        "known_size_bytes": int(
            result["binding"]["snapshot_summary"]["known_size_bytes"]
        ),
        "unknown_size_count": int(
            result["binding"]["snapshot_summary"]["unknown_size_count"]
        ),
        "document_count": len(documents),
        "document_paths": sorted(document_paths),
        "lfs_file_count": len(lfs_paths),
        "lfs_documents_downloaded": 0,
        "execution_policy": str(snapshot["execution_policy"]),
        "source_code_executed": False,
    }


def _list_runs(trace: ApiTrace, client: Any, operation: str) -> list[dict[str, Any]]:
    payload = _expect_status(
        trace.request(client, "GET", "/runs"),
        200,
        operation,
    )
    runs = payload.get("runs")
    _require(isinstance(runs, list), f"{operation}: runs response is incomplete")
    return [dict(item) for item in runs if isinstance(item, Mapping)]


def _verify_snapshot_tamper_fails_closed(
    trace: ApiTrace,
    client: Any,
    workspace: Any,
    *,
    task_id: str,
    snapshot_id: str,
) -> dict[str, Any]:
    """Change exactly one byte in an owned snapshot record and verify the seal."""

    from model_harness.model_source_store import ModelSourceIntegrityError

    runs_before = _list_runs(trace, client, "snapshot tamper runs before")
    _require(not runs_before, "a Run existed before the snapshot integrity negative")
    store = workspace.model_source_store
    record_path = store._record_path(  # noqa: SLF001 - acceptance inspects owned evidence
        task_id, "snapshots", snapshot_id
    )
    original = record_path.read_bytes()
    marker = b'"content_base64"'
    marker_offset = original.find(marker)
    _require(
        marker_offset >= 0,
        "real downloaded snapshot did not contain a static document to tamper",
    )
    colon_offset = original.find(b":", marker_offset + len(marker))
    quote_offset = original.find(b'"', colon_offset + 1)
    _require(
        colon_offset >= 0 and quote_offset >= 0 and quote_offset + 1 < len(original),
        "downloaded snapshot document content could not be located",
    )
    changed_offset = quote_offset + 1
    original_byte = original[changed_offset]
    _require(
        chr(original_byte)
        in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/",
        "downloaded snapshot document content is empty or not base64",
    )
    mutated = bytearray(original)
    mutated[changed_offset] = ord("A") if original_byte != ord("A") else ord("B")
    changed_bytes = sum(
        before != after for before, after in zip(original, mutated, strict=True)
    )
    _require(changed_bytes == 1, "snapshot tamper did not change exactly one byte")
    integrity_error: ModelSourceIntegrityError | None = None
    product_read_status: int | None = None
    restored = False
    try:
        record_path.write_bytes(bytes(mutated))
        try:
            store.get_snapshot(task_id, snapshot_id)
        except ModelSourceIntegrityError as error:
            integrity_error = error
        product_read = trace.request(
            client,
            "GET",
            f"/tasks/{task_id}/model-bindings/current",
        )
        product_read_status = int(product_read.status_code)
        _require(
            product_read_status == 409,
            "tampered snapshot did not fail closed through the product API",
        )
    finally:
        record_path.write_bytes(original)
        restored = True
    _require(
        integrity_error is not None,
        "tampered snapshot record was accepted by an integrity read",
    )
    # Prove the restoration itself is valid before continuing with restart checks.
    restored_snapshot = store.get_snapshot(task_id, snapshot_id)
    _require(
        restored_snapshot.get("snapshot_id") == snapshot_id,
        "restored snapshot identity changed",
    )
    runs_after = _list_runs(trace, client, "snapshot tamper runs after")
    _require(not runs_after, "snapshot integrity verification created a Run")
    return {
        "case_id": "downloaded-snapshot-single-byte-tamper",
        "status": "verified",
        "verified": True,
        "formal_evidence": True,
        "task_id": task_id,
        "snapshot_id": snapshot_id,
        "owned_path": str(record_path.resolve()),
        "mutated_field": "documents[0].content_base64",
        "mutated_bytes": changed_bytes,
        "integrity_read_failed": True,
        "integrity_error_type": integrity_error.__class__.__name__,
        "product_api_read_http_status": product_read_status,
        "record_restored": restored,
        "run_count_before": len(runs_before),
        "run_count_after": len(runs_after),
        "run_created": False,
        "source_code_executed": False,
    }


def _run_public_case(
    trace: ApiTrace,
    client: Any,
    workspace: Any,
    case: Mapping[str, str],
    *,
    token: str | None,
) -> tuple[dict[str, Any], dict[str, str]]:
    started = time.monotonic()
    task = _create_task(trace, client, case["case_id"])
    task_id = str(task["task_id"])
    revision = int(task["current_spec_revision"])

    search_response = trace.request(
        client,
        "POST",
        f"/tasks/{task_id}/model-source-searches",
        json={
            "query": case["search_query"],
            "providers": [case["provider"]],
            "limit_per_provider": 10,
            "base_spec_revision": revision,
        },
        headers=_headers(case["provider"], token),
    )
    search = _expect_status(search_response, 200, "official provider search")
    _require(not search.get("provider_errors"), "official search returned provider errors")
    candidate = next(
        (
            item
            for item in search.get("candidates", [])
            if item.get("provider") == case["provider"]
            and item.get("repository") == case["repository"]
        ),
        None,
    )
    _require(isinstance(candidate, dict), "expected repository was not in search results")
    search_record = workspace.model_source_store.get_search_record(
        task_id, str(search["search_id"])
    )
    _require(
        any(
            item.get("candidate_id") == candidate["candidate_id"]
            for item in search_record.get("candidates", [])
        ),
        "candidate was not persisted in the server-owned search record",
    )

    rejected = trace.request(
        client,
        "POST",
        f"/tasks/{task_id}/model-source-selections",
        json={
            "search_id": search["search_id"],
            "candidate_id": candidate["candidate_id"],
            "approval_confirmed": False,
            "base_spec_revision": revision,
        },
        headers=_headers(case["provider"], token),
    )
    _expect_status(rejected, 409, "selection without approval")

    confirmed_response = trace.request(
        client,
        "POST",
        f"/tasks/{task_id}/model-source-selections",
        json={
            "search_id": search["search_id"],
            "candidate_id": candidate["candidate_id"],
            "approval_confirmed": True,
            "base_spec_revision": revision,
        },
        headers=_headers(case["provider"], token),
    )
    confirmed_resolution = _expect_status(
        confirmed_response, 201, "confirmed search selection"
    )["resolution"]
    selection_context = confirmed_resolution.get("details", {}).get(
        "selection_context", {}
    )
    _require(
        selection_context.get("origin") == "official_catalog_search",
        "confirmed resolution lost official search provenance",
    )
    _require(
        selection_context.get("search_id") == search["search_id"],
        "confirmed resolution lost its server search record",
    )

    # Hugging Face catalog candidates intentionally resolve `main`.  After the
    # human has selected the repository, the user-selected tag is resolved in a
    # second explicit API step so the final binding is revision-exact.
    if confirmed_resolution["requested_revision"] == case["requested_revision"]:
        resolution = confirmed_resolution
    else:
        resolution = _resolve_direct(
            trace, client, task=task, case=case, token=token
        )
    _require(
        resolution["requested_revision"] == case["requested_revision"],
        "requested revision was silently changed",
    )
    _require(
        COMMIT_PATTERN.fullmatch(str(resolution["resolved_commit"])) is not None,
        "resolved revision is not a 40-character commit",
    )
    bound = _bind(
        trace,
        client,
        task=task,
        resolution=resolution,
        provider=case["provider"],
        token=token,
    )
    binding = bound["binding"]
    _require(binding.get("status") == "active", "binding is not active")
    _require(
        SHA256_PATTERN.fullmatch(str(binding.get("tree_manifest_sha256", "")))
        is not None,
        "tree manifest is missing",
    )
    _require(
        bool(binding.get("license_policy", {}).get("decision")),
        "license decision is missing",
    )
    static_facts = _binding_static_facts(workspace, bound)
    _require(static_facts["file_count"] > 0, "source snapshot is empty")
    _require(
        static_facts["known_size_bytes"] < MAX_ACCEPTED_REPOSITORY_BYTES,
        "acceptance repository exceeds the 50MB bounded-source threshold",
    )
    _require(
        static_facts["execution_policy"] == "never_execute_in_l1",
        "L1 snapshot execution policy changed",
    )

    repeat_task = _create_task(trace, client, f"{case['case_id']}-repeat")
    repeat_resolution = _resolve_direct(
        trace, client, task=repeat_task, case=case, token=token
    )
    repeat_bound = _bind(
        trace,
        client,
        task=repeat_task,
        resolution=repeat_resolution,
        provider=case["provider"],
        token=token,
    )
    _require(
        repeat_resolution["resolved_commit"] == resolution["resolved_commit"],
        "the repeated resolution produced a different commit",
    )
    _require(
        repeat_bound["binding"]["tree_manifest_sha256"]
        == binding["tree_manifest_sha256"],
        "the repeated snapshot produced a different manifest",
    )

    evidence = {
        "case_id": case["case_id"],
        "provider": case["provider"],
        "repository": case["repository"],
        "source_url": case["source_reference"],
        "official_catalog": {
            "origin": case["official_origin"],
            "operation": case["catalog_operation"],
            "result": "success",
            "authenticated": token is not None,
        },
        "task_id": task_id,
        "base_spec_revision": revision,
        "search_id": search["search_id"],
        "search_record_digest": search_record["content_digest"],
        "candidate_id": candidate["candidate_id"],
        "manual_selection": {
            "rejected_without_confirmation": True,
            "confirmed": True,
            "server_record_enforced": True,
        },
        "requested_revision": resolution["requested_revision"],
        "resolved_commit": resolution["resolved_commit"],
        "resolution_id": resolution["resolution_id"],
        "binding_revision_id": binding["binding_revision_id"],
        "snapshot_id": binding["snapshot_id"],
        "manifest_sha256": binding["tree_manifest_sha256"],
        "license": {
            "name": binding["license"],
            "status": binding["license_status"],
            "decision": binding["license_policy"]["decision"],
            "policy_version": binding["license_policy"].get("policy_version"),
        },
        "static_snapshot": static_facts,
        "repeat": {
            "task_id": repeat_task["task_id"],
            "binding_revision_id": repeat_bound["binding"]["binding_revision_id"],
            "snapshot_id": repeat_bound["binding"]["snapshot_id"],
            "resolved_commit": repeat_resolution["resolved_commit"],
            "manifest_sha256": repeat_bound["binding"]["tree_manifest_sha256"],
            "matches_first": True,
        },
        "restart_recovery": {"status": "pending"},
        "elapsed_ms": round((time.monotonic() - started) * 1000, 2),
    }
    restart_expectation = {
        "task_id": task_id,
        "binding_revision_id": str(binding["binding_revision_id"]),
        "resolved_commit": str(resolution["resolved_commit"]),
        "manifest_sha256": str(binding["tree_manifest_sha256"]),
        "search_id": str(search["search_id"]),
        "search_record_digest": str(search_record["content_digest"]),
    }
    return evidence, restart_expectation


def _assert_failed_resolution_left_no_source(
    trace: ApiTrace,
    client: Any,
    *,
    task_id: str,
    label: str,
) -> dict[str, Any]:
    resolutions = _expect_status(
        trace.request(
            client, "GET", f"/tasks/{task_id}/model-source-resolutions"
        ),
        200,
        f"{label} list resolutions",
    )["resolutions"]
    _require(not resolutions, f"{label} left a source resolution behind")
    bindings = _expect_status(
        trace.request(client, "GET", f"/tasks/{task_id}/model-bindings"),
        200,
        f"{label} list bindings",
    )["bindings"]
    _require(not bindings, f"{label} left a trainable binding behind")
    current = trace.request(
        client, "GET", f"/tasks/{task_id}/model-bindings/current"
    )
    _require(current.status_code == 404, f"{label} unexpectedly has a current binding")
    blockers = _expect_status(
        trace.request(
            client, "GET", f"/tasks/{task_id}/blockers?active_only=true"
        ),
        200,
        f"{label} active blocker",
    )["blockers"]
    _require(len(blockers) == 1, f"{label} did not persist one active blocker")
    blocker = _verified_blocker_evidence(
        blockers[0],
        expected_task_id=task_id,
        expected_stage="source_resolution",
        expected_code="blocked_repository",
    )
    return {
        "no_resolution": True,
        "no_binding": True,
        "blocker": blocker,
    }


def _run_safe_negative(
    trace: ApiTrace,
    client: Any,
    *,
    label: str,
    repository: str,
    revision: str,
    token: str | None,
    expected_provider_markers: tuple[str, ...],
) -> dict[str, Any]:
    task = _create_task(trace, client, f"negative-{label}")
    task_id = str(task["task_id"])
    response = trace.request(
        client,
        "POST",
        f"/tasks/{task_id}/model-source-resolutions",
        json={
            "provider": "github",
            "repository": repository,
            "requested_revision": revision,
            "base_spec_revision": task["current_spec_revision"],
        },
        headers=_headers("github", token),
    )
    _require(response.status_code == 502, f"{label} did not fail closed")
    detail = str(response.json().get("detail", ""))
    _require(
        any(marker in detail for marker in expected_provider_markers),
        f"{label} returned an unexpected provider failure code",
    )
    clean_failure = _assert_failed_resolution_left_no_source(
        trace, client, task_id=task_id, label=label
    )
    return {
        "case_id": label,
        "status": "verified",
        "verified": True,
        "formal_evidence": True,
        "http_status": int(response.status_code),
        "provider_code": detail,
        "failure_closed": True,
        "task_id": task_id,
        **clean_failure,
    }


def verify_synthetic_rate_limit_contract() -> dict[str, Any]:
    """Exercise the real transport error mapping without touching the network."""

    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from model_harness.github_source import GitHubRestTransport
    from model_harness.model_sources import ModelSourceUpstreamError

    class RateLimitedOpener:
        def open(self, request: Any, timeout: float) -> Any:
            del timeout
            raise HTTPError(
                request.full_url,
                403,
                "Forbidden",
                {"X-RateLimit-Remaining": "0"},
                None,
            )

    transport = GitHubRestTransport(opener=RateLimitedOpener())  # type: ignore[arg-type]
    try:
        transport.request_json(
            "/search/repositories", query={"q": "offline-contract-probe"}
        )
    except ModelSourceUpstreamError as error:
        _require(str(error) == "github_rate_limited", "rate limit was misclassified")
    else:
        raise LiveAcceptanceFailure("synthetic rate limit unexpectedly succeeded")
    return {
        "case_id": "github-rate-limit-transport-contract",
        "status": "verified",
        "verified": True,
        "synthetic": True,
        "formal_evidence": False,
        "evidence_class": "synthetic_non_formal_transport_contract",
        "real_quota_exhausted": False,
        "network_requests": 0,
        "provider_code": "github_rate_limited",
        "retryable": True,
    }


def _unknown_license_fixture() -> dict[str, str]:
    repository = os.environ.get(
        "MH_L1_UNKNOWN_LICENSE_REPOSITORY", "octocat/Hello-World"
    ).strip()
    revision = os.environ.get("MH_L1_UNKNOWN_LICENSE_REVISION", "master").strip()
    _require(bool(repository), "unknown-license repository is empty")
    _require(bool(revision), "unknown-license revision is empty")
    return {
        "provider": "github",
        "repository": repository,
        "requested_revision": revision,
        "source_reference": f"https://github.com/{repository}",
    }


def _run_unknown_license_negative(
    trace: ApiTrace,
    client: Any,
    workspace: Any,
    *,
    token: str | None,
) -> dict[str, Any]:
    case = _unknown_license_fixture()
    task = _create_task(trace, client, "negative-unknown-license")
    task_id = str(task["task_id"])
    resolution = _resolve_direct(
        trace,
        client,
        task=task,
        case=case,
        token=token,
    )
    result = _bind(
        trace,
        client,
        task=task,
        resolution=resolution,
        provider="github",
        token=token,
    )
    binding = result["binding"]
    policy = dict(binding.get("license_policy") or {})
    _require(
        binding.get("license_status") == "unknown",
        "unknown-license fixture now exposes known license metadata; configure another fixture",
    )
    _require(
        policy.get("decision") != "allow",
        "unknown-license fixture was incorrectly allowed",
    )
    stored_analysis = result["analysis"]
    _require(
        isinstance(stored_analysis, Mapping),
        "unknown-license repository analysis is incomplete",
    )
    downstream = stored_analysis.get("downstream_blockers")
    _require(
        isinstance(downstream, list)
        and any(
            isinstance(item, Mapping)
            and item.get("code") == "blocked_license_unknown"
            for item in downstream
        ),
        "repository analysis omitted its unknown-license downstream blocker",
    )
    runs_before = _list_runs(trace, client, "unknown license runs before")
    _require(not runs_before, "a Run existed before the unknown-license negative")
    plan_response = trace.request(
        client,
        "POST",
        f"/tasks/{task_id}/training-plans",
        json={"base_spec_revision": task["current_spec_revision"]},
    )
    _require(
        plan_response.status_code == 409,
        "unknown-license source did not block downstream training-plan creation",
    )
    plan_detail = str(plan_response.json().get("detail", ""))
    current_plan = trace.request(
        client, "GET", f"/tasks/{task_id}/training-plans/current"
    )
    _require(
        current_plan.status_code == 404,
        "unknown-license source left a current training plan behind",
    )
    blockers = _expect_status(
        trace.request(
            client, "GET", f"/tasks/{task_id}/blockers?active_only=true"
        ),
        200,
        "unknown license active blockers",
    )["blockers"]
    license_blocker = next(
        (
            item
            for item in blockers
            if item.get("stage") == "training_plan"
            and item.get("code") == "blocked_license"
        ),
        None,
    )
    _require(
        isinstance(license_blocker, Mapping),
        "unknown-license source did not persist a training-plan blocker",
    )
    sealed_license_blocker = _verified_blocker_evidence(
        license_blocker,
        expected_task_id=task_id,
        expected_stage="training_plan",
        expected_code="blocked_license",
    )
    runs_after = _list_runs(trace, client, "unknown license runs after")
    _require(not runs_after, "unknown-license verification created a Run")
    static_facts = _binding_static_facts(workspace, result)
    return {
        "case_id": "unknown-license-blocks-training-plan",
        "status": "verified",
        "verified": True,
        "formal_evidence": True,
        "provider": "github",
        "repository": case["repository"],
        "requested_revision": case["requested_revision"],
        "resolved_commit": resolution["resolved_commit"],
        "task_id": task_id,
        "binding_revision_id": binding["binding_revision_id"],
        "license": {
            "name": binding["license"],
            "status": binding["license_status"],
            "decision": policy.get("decision"),
            "policy_version": policy.get("policy_version"),
        },
        "analysis_downstream_code": "blocked_license_unknown",
        "training_plan_http_status": int(plan_response.status_code),
        "training_plan_failure": plan_detail,
        "current_training_plan_absent": True,
        "blocker": sealed_license_blocker,
        "static_snapshot": static_facts,
        "run_count_before": len(runs_before),
        "run_count_after": len(runs_after),
        "run_created": False,
        "source_code_executed": False,
    }


def _private_fixture() -> dict[str, str] | None:
    values = {
        "provider": os.environ.get("MH_L1_PRIVATE_PROVIDER", "").strip().lower(),
        "repository": os.environ.get("MH_L1_PRIVATE_REPOSITORY", "").strip(),
        "requested_revision": os.environ.get(
            "MH_L1_PRIVATE_REVISION", ""
        ).strip(),
        "token": os.environ.get("MH_L1_PRIVATE_TOKEN", ""),
    }
    if not any(values.values()):
        return None
    if not all(values.values()):
        return None
    if values["provider"] not in {"github", "huggingface"}:
        raise LiveAcceptanceFailure("private fixture provider is invalid")
    values["source_reference"] = (
        f"https://github.com/{values['repository']}"
        if values["provider"] == "github"
        else f"https://huggingface.co/{values['repository']}"
    )
    return values


def _run_private_unauthenticated_negative(
    trace: ApiTrace,
    client: Any,
    fixture: Mapping[str, str],
) -> dict[str, Any]:
    task = _create_task(trace, client, "private-fixture-unauthenticated")
    task_id = str(task["task_id"])
    response = trace.request(
        client,
        "POST",
        f"/tasks/{task_id}/model-source-resolutions",
        json={
            "source_reference": fixture["source_reference"],
            "requested_revision": fixture["requested_revision"],
            "base_spec_revision": task["current_spec_revision"],
        },
        headers={},
    )
    _require(
        response.status_code == 502,
        "private fixture unexpectedly resolved without its token",
    )
    try:
        detail = str(response.json().get("detail", ""))
    except (AttributeError, ValueError):
        detail = ""
    clean_failure = _assert_failed_resolution_left_no_source(
        trace,
        client,
        task_id=task_id,
        label="private-fixture-unauthenticated",
    )
    return {
        "case_id": "private-fixture-unauthenticated",
        "status": "verified",
        "verified": True,
        "formal_evidence": True,
        "http_status": int(response.status_code),
        "provider_code": detail,
        "failure_closed": True,
        "token_sent": False,
        "task_id": task_id,
        **clean_failure,
    }


def _run_private_fixture(
    trace: ApiTrace,
    client: Any,
    workspace: Any,
    fixture: Mapping[str, str] | None,
) -> dict[str, Any]:
    if fixture is None:
        supplied = any(
            os.environ.get(name)
            for name in (
                "MH_L1_PRIVATE_PROVIDER",
                "MH_L1_PRIVATE_REPOSITORY",
                "MH_L1_PRIVATE_REVISION",
                "MH_L1_PRIVATE_TOKEN",
            )
        )
        return {
            "status": "not_run",
            "verified": False,
            "formal_evidence": False,
            "reason": (
                "explicit_fixture_incomplete" if supplied else "explicit_fixture_not_configured"
            ),
        }
    unauthenticated = _run_private_unauthenticated_negative(
        trace, client, fixture
    )
    task = _create_task(trace, client, "private-fixture")
    case = {
        "provider": fixture["provider"],
        "source_reference": fixture["source_reference"],
        "requested_revision": fixture["requested_revision"],
    }
    resolution = _resolve_direct(
        trace, client, task=task, case=case, token=fixture["token"]
    )
    result = _bind(
        trace,
        client,
        task=task,
        resolution=resolution,
        provider=fixture["provider"],
        token=fixture["token"],
    )
    static_facts = _binding_static_facts(workspace, result)
    return {
        "status": "verified",
        "verified": True,
        "formal_evidence": True,
        "provider": fixture["provider"],
        "repository_sha256": hashlib.sha256(
            fixture["repository"].encode("utf-8")
        ).hexdigest(),
        "requested_revision": fixture["requested_revision"],
        "resolved_commit": resolution["resolved_commit"],
        "manifest_sha256": result["binding"]["tree_manifest_sha256"],
        "task_id": task["task_id"],
        "static_snapshot": static_facts,
        "unauthenticated_access": unauthenticated,
        "authenticated_access": {
            "status": "verified",
            "http_flow_completed": True,
            "token_sent_ephemerally": True,
        },
        "credential_persisted": False,
    }


def _formal_missing_requirements(evidence: Mapping[str, Any]) -> list[str]:
    missing: list[str] = []
    source_commit = evidence.get("source_commit")
    owned_paths = evidence.get("owned_paths")
    if not (
        isinstance(source_commit, str)
        and COMMIT_PATTERN.fullmatch(source_commit) is not None
        and isinstance(owned_paths, list)
        and bool(owned_paths)
        and len(owned_paths) == len(set(owned_paths))
        and all(
            isinstance(item, str)
            and bool(item)
            and not Path(item).is_absolute()
            and ".." not in Path(item).parts
            and Path(item).as_posix() == item
            for item in owned_paths
        )
    ):
        missing.append("evidence_source_commit_and_owned_paths")
    public_sources = evidence.get("public_sources")
    if (
        not isinstance(public_sources, list)
        or len(public_sources) != len(PUBLIC_CASES)
        or {
            str(item.get("provider"))
            for item in public_sources
            if isinstance(item, Mapping)
        }
        != {"github", "huggingface"}
    ):
        missing.append("public_huggingface_and_github_sources")
    elif any(
        not isinstance(item, Mapping)
        or item.get("restart_recovery", {}).get("status") != "verified"
        for item in public_sources
    ):
        missing.append("public_source_restart_recovery")

    raw_safe_negatives = evidence.get("safe_negatives")
    safe_negatives = (
        raw_safe_negatives if isinstance(raw_safe_negatives, list) else []
    )
    formal_negative_ids = {
        str(item.get("case_id"))
        for item in safe_negatives
        if isinstance(item, Mapping)
        and item.get("status") == "verified"
        and item.get("formal_evidence") is True
        and item.get("synthetic") is not True
    }
    if not {
        "repository-does-not-exist",
        "invalid-revision-no-fallback",
    }.issubset(formal_negative_ids):
        missing.append("real_source_resolution_negatives")
    elif any(
        not _has_verified_blocker_evidence(
            item,
            expected_stage="source_resolution",
            expected_code="blocked_repository",
        )
        for item in safe_negatives
        if isinstance(item, Mapping)
        and item.get("case_id")
        in {"repository-does-not-exist", "invalid-revision-no-fallback"}
    ):
        missing.append("real_source_resolution_blocker_evidence")
    if "unknown-license-blocks-training-plan" not in formal_negative_ids:
        missing.append("real_unknown_license_plan_block_negative")
    else:
        unknown_license = next(
            (
                item
                for item in safe_negatives
                if isinstance(item, Mapping)
                and item.get("case_id")
                == "unknown-license-blocks-training-plan"
            ),
            None,
        )
        if not _has_verified_blocker_evidence(
            unknown_license,
            expected_stage="training_plan",
            expected_code="blocked_license",
        ):
            missing.append("real_unknown_license_blocker_evidence")

    tamper = evidence.get("snapshot_integrity_negative")
    if not (
        isinstance(tamper, Mapping)
        and tamper.get("status") == "verified"
        and tamper.get("formal_evidence") is True
        and tamper.get("integrity_read_failed") is True
        and tamper.get("product_api_read_http_status") == 409
        and tamper.get("mutated_bytes") == 1
        and tamper.get("record_restored") is True
        and tamper.get("run_count_before") == 0
        and tamper.get("run_count_after") == 0
        and tamper.get("run_created") is False
        and tamper.get("source_code_executed") is False
    ):
        missing.append("real_snapshot_integrity_tamper_negative")

    private_fixture = evidence.get("private_fixture")
    private_unauthenticated = (
        private_fixture.get("unauthenticated_access")
        if isinstance(private_fixture, Mapping)
        else None
    )
    private_authenticated = (
        private_fixture.get("authenticated_access")
        if isinstance(private_fixture, Mapping)
        else None
    )
    if not (
        isinstance(private_fixture, Mapping)
        and private_fixture.get("verified") is True
        and private_fixture.get("formal_evidence") is True
        and isinstance(private_unauthenticated, Mapping)
        and private_unauthenticated.get("status") == "verified"
        and private_unauthenticated.get("http_status") == 502
        and private_unauthenticated.get("no_resolution") is True
        and private_unauthenticated.get("no_binding") is True
        and _has_verified_blocker_evidence(
            private_unauthenticated,
            expected_stage="source_resolution",
            expected_code="blocked_repository",
        )
        and isinstance(private_authenticated, Mapping)
        and private_authenticated.get("status") == "verified"
        and private_fixture.get("credential_persisted") is False
    ):
        missing.append("private_fixture_unauthenticated_and_authenticated")
    return missing


def _finalize_evidence(
    evidence: dict[str, Any], *, formal: bool
) -> dict[str, Any]:
    missing = _formal_missing_requirements(evidence)
    evidence["formal_requested"] = formal
    evidence["missing_requirements"] = missing
    evidence["verified"] = not missing
    evidence["status"] = (
        "verified" if not missing else ("blocked" if formal else "partial")
    )
    evidence["completed_at_utc"] = utc_now()
    safe_negatives = evidence.get("safe_negatives", [])
    evidence["summary"] = {
        "public_sources_verified": len(evidence.get("public_sources", [])),
        "real_safe_negatives_verified": sum(
            isinstance(item, Mapping)
            and item.get("status") == "verified"
            and item.get("formal_evidence") is True
            and item.get("synthetic") is not True
            for item in safe_negatives
        ),
        "synthetic_transport_contracts_observed": sum(
            isinstance(item, Mapping)
            and item.get("status") == "verified"
            and item.get("synthetic") is True
            for item in safe_negatives
        ),
        "synthetic_transport_contracts_counted_as_formal": 0,
        "snapshot_integrity_negative_verified": (
            evidence.get("snapshot_integrity_negative", {}).get("status")
            == "verified"
        ),
        "private_fixture_verified": evidence.get("private_fixture", {}).get(
            "verified"
        )
        is True,
        "formal_requirements_satisfied": not missing,
    }
    return evidence


def _run_live(*, negatives: bool, formal: bool = False) -> dict[str, Any]:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    try:
        from fastapi.testclient import TestClient
    except ImportError as error:
        raise LiveAcceptanceFailure("FastAPI TestClient is unavailable") from error
    from model_harness.server import create_app

    trace = ApiTrace()
    tokens = {
        "huggingface": os.environ.get("MH_L1_HF_TOKEN") or None,
        "github": os.environ.get("MH_L1_GITHUB_TOKEN") or None,
    }
    evidence: dict[str, Any] = {
        "schema_version": "0.1",
        "object_type": "v09_l1_live_acceptance",
        "status": "running",
        "verified": False,
        "formal_requested": formal,
        "missing_requirements": [],
        "generated_at_utc": utc_now(),
        "source_commit": _git_head(),
        "live_acceptance_enabled": True,
        "network_policy": {
            "official_origins_only": [
                "https://api.github.com",
                "https://huggingface.co",
            ],
            "source_code_execution": "forbidden",
            "huggingface_lfs_weights": "metadata_only_never_downloaded",
            "github_rate_limit": "synthetic_non_formal_transport_contract_only",
            "remote_resource_creation": "forbidden",
        },
        "owned_paths": list(OWNED_PATHS),
        "public_sources": [],
        "safe_negatives": [],
        "snapshot_integrity_negative": {
            "status": "not_run",
            "verified": False,
        },
        "private_fixture": {"status": "not_run", "verified": False},
        "http_trace": trace.entries,
    }
    restart_expectations: list[tuple[dict[str, Any], dict[str, str]]] = []
    with tempfile.TemporaryDirectory(prefix="model-harness-v09-l1-") as temporary:
        temporary_root = Path(temporary)
        runs_dir = temporary_root / "runs"
        prior_hf_home = os.environ.get("HF_HOME")
        os.environ["HF_HOME"] = str(temporary_root / "hf-cache")
        try:
            app = create_app(
                runs_dir,
                conversation_url="http://127.0.0.1:1",
            )
            with TestClient(app) as client:
                workspace = app.state.training_workspace
                for case in PUBLIC_CASES:
                    case_evidence, expectation = _run_public_case(
                        trace,
                        client,
                        workspace,
                        case,
                        token=tokens[case["provider"]],
                    )
                    evidence["public_sources"].append(case_evidence)
                    restart_expectations.append((case_evidence, expectation))

                first_repeat = evidence["public_sources"][0]["repeat"]
                evidence["snapshot_integrity_negative"] = (
                    _verify_snapshot_tamper_fails_closed(
                        trace,
                        client,
                        workspace,
                        task_id=str(first_repeat["task_id"]),
                        snapshot_id=str(first_repeat["snapshot_id"]),
                    )
                )
                if negatives:
                    nonce = uuid4().hex[:16]
                    evidence["safe_negatives"] = [
                        _run_safe_negative(
                            trace,
                            client,
                            label="repository-does-not-exist",
                            repository=f"specialist-model-studio-live/missing-{nonce}",
                            revision="main",
                            token=tokens["github"],
                            expected_provider_markers=("not_found",),
                        ),
                        _run_safe_negative(
                            trace,
                            client,
                            label="invalid-revision-no-fallback",
                            repository="explainingai-code/VAE-Pytorch",
                            revision=f"missing-revision-{nonce}",
                            token=tokens["github"],
                            # GitHub currently answers this commit endpoint with
                            # 422, which the provider deliberately exposes only
                            # as a sanitized generic upstream failure.  The
                            # important safety contract here is no fallback to
                            # `main`, no resolution, and no binding.
                            expected_provider_markers=(
                                "not_found",
                                "github_api_request_failed",
                            ),
                        ),
                        _run_unknown_license_negative(
                            trace,
                            client,
                            workspace,
                            token=tokens["github"],
                        ),
                        verify_synthetic_rate_limit_contract(),
                    ]
                else:
                    evidence["safe_negatives"] = [
                        {
                            "case_id": case_id,
                            "status": "not_run",
                            "reason": "run_with_--negatives",
                            "verified": False,
                            "formal_evidence": case_id
                            != "github-rate-limit-transport-contract",
                        }
                        for case_id in (
                            "repository-does-not-exist",
                            "invalid-revision-no-fallback",
                            "unknown-license-blocks-training-plan",
                            "github-rate-limit-transport-contract",
                        )
                    ]

                evidence["private_fixture"] = _run_private_fixture(
                    trace, client, workspace, _private_fixture()
                )

            restarted = create_app(
                runs_dir,
                conversation_url="http://127.0.0.1:1",
            )
            with TestClient(restarted) as client:
                workspace = restarted.state.training_workspace
                for case_evidence, expected in restart_expectations:
                    current = _expect_status(
                        trace.request(
                            client,
                            "GET",
                            f"/tasks/{expected['task_id']}/model-bindings/current",
                        ),
                        200,
                        "restart current binding",
                    )["binding"]
                    search_record = workspace.model_source_store.get_search_record(
                        expected["task_id"], expected["search_id"]
                    )
                    _require(
                        current["binding_revision_id"]
                        == expected["binding_revision_id"],
                        "binding revision changed after restart",
                    )
                    _require(
                        current["resolved_commit"] == expected["resolved_commit"],
                        "resolved commit changed after restart",
                    )
                    _require(
                        current["tree_manifest_sha256"]
                        == expected["manifest_sha256"],
                        "manifest changed after restart",
                    )
                    _require(
                        search_record["content_digest"]
                        == expected["search_record_digest"],
                        "server search record changed after restart",
                    )
                    case_evidence["restart_recovery"] = {
                        "status": "verified",
                        "binding_revision_id_unchanged": True,
                        "resolved_commit_unchanged": True,
                        "manifest_unchanged": True,
                        "search_record_unchanged": True,
                    }

            disk = _directory_bytes(temporary_root)
            for secret in _secret_values():
                _require(
                    secret.encode("utf-8") not in disk,
                    "credential material was persisted in the acceptance workspace",
                )
        finally:
            if prior_hf_home is None:
                os.environ.pop("HF_HOME", None)
            else:
                os.environ["HF_HOME"] = prior_hf_home

    evidence["http_trace"] = trace.entries
    return _finalize_evidence(evidence, formal=formal)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--negatives",
        action="store_true",
        help=(
            "also run the real not-found, invalid-revision and unknown-license "
            "fail-closed cases"
        ),
    )
    parser.add_argument(
        "--formal",
        action="store_true",
        help=(
            "require all real public/private/negative evidence; write blocked "
            "evidence and return non-zero when any formal requirement is missing"
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if os.environ.get("MH_LIVE_ACCEPTANCE") != "1":
        print(
            "[SKIP] V0.9 L1 live acceptance disabled: "
            "set MH_LIVE_ACCEPTANCE=1 to allow official-provider network calls."
        )
        return 0

    evidence_path = Path(
        os.environ.get("MH_L1_EVIDENCE_PATH", str(DEFAULT_EVIDENCE_PATH))
    )
    secrets = _secret_values()
    try:
        evidence = _run_live(
            negatives=bool(args.negatives or args.formal),
            formal=bool(args.formal),
        )
    except Exception as error:
        failed = {
            "schema_version": "0.1",
            "object_type": "v09_l1_live_acceptance",
            "status": "failed",
            "generated_at_utc": utc_now(),
            "source_commit": _git_head(),
            "live_acceptance_enabled": True,
            "failure": {
                "type": error.__class__.__name__,
                "message": str(error)[:1000],
            },
            "verified": False,
            "owned_paths": list(OWNED_PATHS),
        }
        _atomic_json(evidence_path, failed, secrets)
        print(f"[FAIL] V0.9 L1 live acceptance: {_scrub(str(error), secrets)}")
        print(f"Failure evidence: {evidence_path.resolve()}")
        return 1

    _atomic_json(evidence_path, evidence, secrets)
    commits = ", ".join(
        str(item["resolved_commit"]) for item in evidence["public_sources"]
    )
    if evidence.get("status") == "verified":
        print(f"[PASS] V0.9 L1 live acceptance: {commits}")
    elif evidence.get("status") == "blocked":
        print(
            "[BLOCKED] V0.9 L1 formal acceptance missing: "
            + ", ".join(evidence.get("missing_requirements", []))
        )
    else:
        print(
            "[PARTIAL] V0.9 L1 public acceptance completed; missing: "
            + ", ".join(evidence.get("missing_requirements", []))
        )
    print(f"Evidence: {evidence_path.resolve()}")
    if evidence["private_fixture"].get("status") == "not_run":
        print("Private fixture: not_run (not claimed as verified)")
    if args.formal and evidence.get("status") != "verified":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
