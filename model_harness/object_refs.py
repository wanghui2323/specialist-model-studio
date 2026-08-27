from __future__ import annotations

import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping, Sequence
from urllib.parse import quote


OBJECT_REF_SCHEMA_VERSION = "1.0"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_ABSOLUTE_PATH = re.compile(r"(?:^|\s)(?:/Users/|/home/|/var/|[A-Za-z]:[\\/])")
_SECRET = re.compile(
    r"(?:authorization\s*:|bearer\s+|(?:hf|ghp|github_pat)_[A-Za-z0-9_-]{8,}|token\s*[=:])",
    re.IGNORECASE,
)


class ObjectRefValidationError(ValueError):
    """A projected reference is incomplete, unknown, or outside its owner scope."""


@dataclass(frozen=True)
class ObjectRefDescriptor:
    type: str
    required_fields: tuple[str, ...]
    identity_fields: tuple[str, ...]
    digest_fields: tuple[str, ...]
    endpoint_template: str | None
    response_selector: str | None
    task_scope_rule: str = "exact_task"
    run_scope_rule: str = "not_applicable"
    redaction_policy: str = "canonical_fields_only"
    producer_ready: bool = True

    def endpoint(self, ref: Mapping[str, Any]) -> str:
        if self.endpoint_template is None:
            raise ObjectRefValidationError(f"{self.type} has no exact endpoint")
        values = {
            key: quote(str(value), safe="")
            for key, value in ref.items()
            if value is not None
        }
        if self.type == "resource_feasibility":
            kind = ref.get("record_kind")
            segment = {
                "resource_probe": "resource-probes",
                "environment_lock": "environment-locks",
                "resource_fit_report": "resource-fit-reports",
            }.get(kind)
            if segment is None:
                raise ObjectRefValidationError(
                    "resource_feasibility requires a supported record_kind"
                )
            values["resource_segment"] = segment
        try:
            return self.endpoint_template.format_map(values)
        except KeyError as exc:
            raise ObjectRefValidationError(
                f"{self.type} endpoint is missing {exc.args[0]}"
            ) from exc


@dataclass(frozen=True)
class CanonicalObjectRef:
    type: str
    id: str
    task_id: str
    digest: str | None = None
    label: str | None = None
    run_id: str | None = None
    base_spec_revision: int | None = None
    resolved_commit: str | None = None
    revision: int | None = None
    record_kind: str | None = None
    candidate_digest: str | None = None
    validation_digest: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            key: value
            for key, value in self.__dict__.items()
            if value is not None
        }


def _descriptor(
    ref_type: str,
    *,
    required: Sequence[str],
    identity: Sequence[str],
    digests: Sequence[str] = (),
    endpoint: str | None,
    selector: str | None,
    run_scope: str = "not_applicable",
    producer_ready: bool = True,
) -> ObjectRefDescriptor:
    return ObjectRefDescriptor(
        type=ref_type,
        required_fields=tuple(required),
        identity_fields=tuple(identity),
        digest_fields=tuple(digests),
        endpoint_template=endpoint,
        response_selector=selector,
        run_scope_rule=run_scope,
        producer_ready=producer_ready,
    )


OBJECT_REF_DESCRIPTORS: Mapping[str, ObjectRefDescriptor] = MappingProxyType(
    {
        "model_source_search": _descriptor(
            "model_source_search",
            required=("type", "id", "task_id", "base_spec_revision"),
            identity=("task_id", "id", "base_spec_revision"),
            endpoint="/tasks/{task_id}/model-source-searches/{id}",
            selector="search",
        ),
        "model_source_resolution": _descriptor(
            "model_source_resolution",
            required=("type", "id", "task_id", "digest", "resolved_commit"),
            identity=("task_id", "id", "resolved_commit"),
            digests=("digest",),
            endpoint="/tasks/{task_id}/model-source-resolutions/{id}",
            selector="resolution",
        ),
        "model_binding": _descriptor(
            "model_binding",
            required=("type", "id", "task_id", "digest", "revision"),
            identity=("task_id", "id", "revision"),
            digests=("digest",),
            endpoint="/tasks/{task_id}/model-bindings/{id}",
            selector="binding",
        ),
        "model_binding_attempt": _descriptor(
            "model_binding_attempt",
            required=("type", "id", "task_id", "digest"),
            identity=("task_id", "id"),
            digests=("digest",),
            endpoint="/tasks/{task_id}/model-binding-attempts/{id}",
            selector="binding_attempt",
        ),
        "repository_analysis": _descriptor(
            "repository_analysis",
            required=("type", "id", "task_id", "digest"),
            identity=("task_id", "id"),
            digests=("digest",),
            endpoint="/tasks/{task_id}/repository-analyses/{id}",
            selector="analysis",
        ),
        "training_plan": _descriptor(
            "training_plan",
            required=("type", "id", "task_id", "digest", "revision"),
            identity=("task_id", "id", "revision"),
            digests=("digest",),
            endpoint="/tasks/{task_id}/training-plans/{id}",
            selector="training_plan",
        ),
        "resource_feasibility": _descriptor(
            "resource_feasibility",
            required=("type", "id", "task_id", "digest", "record_kind"),
            identity=("task_id", "record_kind", "id"),
            digests=("digest",),
            endpoint="/tasks/{task_id}/{resource_segment}/{id}",
            selector=None,
        ),
        "staged_asset": _descriptor(
            "staged_asset",
            required=("type", "id", "task_id", "digest", "revision"),
            identity=("task_id", "id", "revision"),
            digests=("digest",),
            endpoint="/tasks/{task_id}/staged-assets/{id}",
            selector="staged_asset",
        ),
        "recipe_build": _descriptor(
            "recipe_build",
            required=(
                "type",
                "id",
                "task_id",
                "candidate_digest",
                "validation_digest",
            ),
            identity=("task_id", "id"),
            digests=("candidate_digest", "validation_digest"),
            endpoint="/tasks/{task_id}/recipe-builds/{id}",
            selector="recipe_build",
        ),
        "evaluation_report": _descriptor(
            "evaluation_report",
            required=("type", "id", "task_id", "run_id", "digest"),
            identity=("task_id", "run_id", "id"),
            digests=("digest",),
            endpoint="/tasks/{task_id}/runs/{run_id}/evaluation-report",
            selector=None,
            run_scope="exact_run",
            producer_ready=True,
        ),
        "inference_input": _descriptor(
            "inference_input",
            required=("type", "id", "task_id", "run_id", "digest"),
            identity=("task_id", "run_id", "id"),
            digests=("digest",),
            endpoint=(
                "/tasks/{task_id}/runs/{run_id}/inference-inputs/{id}"
            ),
            selector="inference_input",
            run_scope="exact_run",
            producer_ready=True,
        ),
        "artifact_bundle": _descriptor(
            "artifact_bundle",
            required=("type", "id", "task_id", "run_id", "digest"),
            identity=("task_id", "run_id", "id"),
            digests=("digest",),
            endpoint="/tasks/{task_id}/runs/{run_id}/artifact-bundles/{id}",
            selector=None,
            run_scope="exact_run",
            producer_ready=True,
        ),
        "blocker": _descriptor(
            "blocker",
            required=("type", "id", "task_id", "digest"),
            identity=("task_id", "id"),
            digests=("digest",),
            endpoint="/tasks/{task_id}/blockers/{id}",
            selector="blocker",
        ),
    }
)


_CANONICAL_FIELDS = frozenset(CanonicalObjectRef.__dataclass_fields__)


def _nonempty(value: Any) -> bool:
    return value is not None and not isinstance(value, bool) and (
        not isinstance(value, str) or bool(value.strip())
    )


def _redacted_label(value: Any, ref_type: str) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    selected = value.strip()
    if _ABSOLUTE_PATH.search(selected) or _SECRET.search(selected):
        return ref_type.replace("_", " ")
    return selected[:160]


def normalize_object_ref(
    value: Mapping[str, Any],
    *,
    expected_task_id: str,
    expected_run_id: str | None = None,
    require_producer_ready: bool = True,
) -> CanonicalObjectRef:
    if not isinstance(value, Mapping):
        raise ObjectRefValidationError("object ref must be an object")
    ref_type = value.get("type")
    if not isinstance(ref_type, str) or ref_type not in OBJECT_REF_DESCRIPTORS:
        raise ObjectRefValidationError("object ref type is unknown")
    descriptor = OBJECT_REF_DESCRIPTORS[ref_type]
    if require_producer_ready and not descriptor.producer_ready:
        raise ObjectRefValidationError(f"{ref_type} producer is not evidence-ready")
    selected = {key: value.get(key) for key in _CANONICAL_FIELDS}
    selected["type"] = ref_type
    selected["label"] = _redacted_label(value.get("label"), ref_type)
    for field in descriptor.required_fields:
        if not _nonempty(selected.get(field)):
            raise ObjectRefValidationError(f"{ref_type} requires {field}")
    if selected.get("task_id") != expected_task_id:
        raise ObjectRefValidationError("object ref belongs to another task")
    if descriptor.run_scope_rule == "exact_run":
        if expected_run_id is not None and selected.get("run_id") != expected_run_id:
            raise ObjectRefValidationError("object ref belongs to another run")
    for field in ("base_spec_revision", "revision"):
        item = selected.get(field)
        if item is not None and (isinstance(item, bool) or not isinstance(item, int) or item < 1):
            raise ObjectRefValidationError(f"{field} must be a positive integer")
    for field in descriptor.digest_fields:
        digest = selected.get(field)
        if not isinstance(digest, str) or _SHA256.fullmatch(digest.lower()) is None:
            raise ObjectRefValidationError(f"{field} must be a sha256 digest")
        selected[field] = digest.lower()
    if selected.get("resolved_commit") is not None:
        commit = str(selected["resolved_commit"]).lower()
        if _COMMIT.fullmatch(commit) is None:
            raise ObjectRefValidationError("resolved_commit must be immutable")
        selected["resolved_commit"] = commit
    if ref_type == "resource_feasibility" and selected.get("record_kind") not in {
        "resource_probe",
        "environment_lock",
        "resource_fit_report",
    }:
        raise ObjectRefValidationError("resource_feasibility record_kind is invalid")
    return CanonicalObjectRef(**selected)


def normalize_object_refs(
    value: Any,
    *,
    expected_task_id: str,
    expected_run_id: str | None = None,
    accepted_types: frozenset[str] | None = None,
    require_nonempty: bool = False,
    require_producer_ready: bool = True,
) -> tuple[CanonicalObjectRef, ...]:
    if not isinstance(value, list):
        raise ObjectRefValidationError("object_refs must be a list")
    if require_nonempty and not value:
        raise ObjectRefValidationError("object_refs cannot be empty")
    refs: dict[str, CanonicalObjectRef] = {}
    for item in value:
        ref = normalize_object_ref(
            item,
            expected_task_id=expected_task_id,
            expected_run_id=expected_run_id,
            require_producer_ready=require_producer_ready,
        )
        if accepted_types is not None and ref.type not in accepted_types:
            raise ObjectRefValidationError("object ref type is not evidence-eligible")
        key = repr(sorted(ref.as_dict().items()))
        refs[key] = ref
    return tuple(refs[key] for key in sorted(refs))


def exact_object_ref_endpoint(ref: CanonicalObjectRef) -> str:
    return OBJECT_REF_DESCRIPTORS[ref.type].endpoint(ref.as_dict())


__all__ = [
    "CanonicalObjectRef",
    "OBJECT_REF_DESCRIPTORS",
    "OBJECT_REF_SCHEMA_VERSION",
    "ObjectRefDescriptor",
    "ObjectRefValidationError",
    "exact_object_ref_endpoint",
    "normalize_object_ref",
    "normalize_object_refs",
]
