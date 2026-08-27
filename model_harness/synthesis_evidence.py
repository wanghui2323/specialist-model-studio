from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Literal, Mapping, Sequence

from .object_refs import (
    CanonicalObjectRef,
    ObjectRefValidationError,
    normalize_object_refs,
)


SYNTHESIS_VERDICT_VERSION = "1.0"


@dataclass(frozen=True)
class RunBoundary:
    """Immutable DSH source boundary captured before one prompt is queued."""

    run_id: str
    queued_at_utc: str
    queue_event_seq: int
    source_seq_floor_by_session: tuple[tuple[str, int], ...]
    boundary_complete: bool = True


@dataclass(frozen=True)
class VerifiedChildBinding:
    """One lineage-verified delegation, kept separate from role aggregation."""

    run_id: str
    delegation_call_id: str
    parent_turn_id: str
    parent_session_id: str
    child_session_id: str
    created_in_run: bool
    lineage_verified: bool = True


@dataclass(frozen=True)
class EvidenceToolRule:
    """Explicit allow-list rule for a tool that can produce completion evidence."""

    accepted_ref_types: frozenset[str]
    require_task_argument: bool = True
    run_argument: str | None = None


EvidenceObjectRef = CanonicalObjectRef


@dataclass(frozen=True)
class SynthesisEventVerdict:
    candidate_event_id: str
    run_id: str | None
    accepted: bool
    effective_category: Literal["final", "narration"]
    effective_type: Literal["final_synthesis", "coordinator_note"]
    effective_status: Literal["completed", "observed"]
    reason_codes: tuple[str, ...]
    evidence_event_ids: tuple[str, ...]
    evidence_object_refs: tuple[EvidenceObjectRef, ...]
    evidence_digest: str | None


@dataclass(frozen=True)
class RunEvidenceVerdict:
    run_id: str
    accepted_candidate_event_id: str | None
    evidence_event_ids: tuple[str, ...]
    evidence_digest: str | None
    reason_codes: tuple[str, ...]


@dataclass(frozen=True)
class SynthesisVerdictIndex:
    version: str
    event_verdicts: tuple[SynthesisEventVerdict, ...]
    run_verdicts: tuple[RunEvidenceVerdict, ...]

    def event(self, event_id: str) -> SynthesisEventVerdict | None:
        return next(
            (
                verdict
                for verdict in self.event_verdicts
                if verdict.candidate_event_id == event_id
            ),
            None,
        )

    def run(self, run_id: str) -> RunEvidenceVerdict | None:
        return next(
            (verdict for verdict in self.run_verdicts if verdict.run_id == run_id),
            None,
        )


DEFAULT_EVIDENCE_TOOL_POLICY: Mapping[str, EvidenceToolRule] = MappingProxyType(
    {
        "model_harness_search_model_sources": EvidenceToolRule(
            accepted_ref_types=frozenset({"model_source_search"}),
        ),
        "model_harness_select_model_source_candidate": EvidenceToolRule(
            accepted_ref_types=frozenset({"model_source_resolution"}),
        ),
        "model_harness_resolve_model_source": EvidenceToolRule(
            accepted_ref_types=frozenset({"model_source_resolution"}),
        ),
        "model_harness_get_repository_analysis": EvidenceToolRule(
            accepted_ref_types=frozenset({"repository_analysis"}),
        ),
        "model_harness_create_training_plan": EvidenceToolRule(
            accepted_ref_types=frozenset({"training_plan"}),
        ),
        "model_harness_revise_training_plan": EvidenceToolRule(
            accepted_ref_types=frozenset({"training_plan"}),
        ),
        "model_harness_decide_training_plan": EvidenceToolRule(
            accepted_ref_types=frozenset({"training_plan"}),
        ),
        "model_harness_get_training_plan": EvidenceToolRule(
            accepted_ref_types=frozenset({"training_plan"}),
        ),
        "model_harness_check_resource_feasibility": EvidenceToolRule(
            accepted_ref_types=frozenset({"resource_feasibility", "blocker"}),
        ),
        "model_harness_stage_recipe_samples": EvidenceToolRule(
            accepted_ref_types=frozenset({"staged_asset"}),
        ),
        "model_harness_build_recipe": EvidenceToolRule(
            accepted_ref_types=frozenset({"recipe_build"}),
        ),
        "model_harness_get_recipe_build": EvidenceToolRule(
            accepted_ref_types=frozenset({"recipe_build"}),
        ),
        "model_harness_get_evaluation_report": EvidenceToolRule(
            accepted_ref_types=frozenset({"evaluation_report"}),
            run_argument="run_id",
        ),
        "model_harness_build_artifact_bundle": EvidenceToolRule(
            accepted_ref_types=frozenset({"artifact_bundle"}),
            run_argument="run_id",
        ),
        "model_harness_get_artifact_bundle": EvidenceToolRule(
            accepted_ref_types=frozenset({"artifact_bundle"}),
            run_argument="run_id",
        ),
    }
)

OBSERVATION_ONLY_TOOLS = frozenset(
    {
        "model_harness_get_task",
        "model_harness_list_tasks",
        "model_harness_list_model_source_providers",
        "model_harness_get_resource_feasibility",
        "model_harness_hf_capability",
        "model_harness_hf_card",
        "model_harness_hf_search",
        "list_agents",
    }
)


@dataclass(frozen=True)
class _EvidenceFact:
    run_id: str
    event_id: str
    source_key: str
    tool_name: str
    refs: tuple[EvidenceObjectRef, ...]
    session_id: str
    source_seq: int
    root_gate_source_seq: int


def _integer(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _payload(event: Mapping[str, Any]) -> Mapping[str, Any]:
    value = event.get("payload")
    return value if isinstance(value, Mapping) else {}


def _event_type(event: Mapping[str, Any]) -> str:
    return str(event.get("event_type") or event.get("type") or "")


def _session_id(event: Mapping[str, Any]) -> str | None:
    for key in ("session_id", "observed_session_id"):
        value = event.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _call_id(event: Mapping[str, Any]) -> str | None:
    for value in (event.get("call_id"), _payload(event).get("call_id")):
        if isinstance(value, str) and value:
            return value
    return None


def _explicit_run_is_compatible(
    event: Mapping[str, Any],
    derived_run_id: str,
) -> bool:
    explicit = event.get("agent_run_id")
    if explicit is None:
        return True
    return isinstance(explicit, str) and explicit == derived_run_id


def _delegated_child_session_id(event: Mapping[str, Any]) -> str | None:
    payload_value = _payload(event).get("dsh_session_id")
    if isinstance(payload_value, str) and payload_value:
        return payload_value
    event_value = event.get("dsh_session_id")
    if (
        isinstance(event_value, str)
        and event_value
        and event_value != _session_id(event)
    ):
        return event_value
    return None


def _source_seq(event: Mapping[str, Any]) -> int | None:
    return _integer(event.get("source_seq"))


def _source_key(event: Mapping[str, Any]) -> str | None:
    value = event.get("source_key")
    return value if isinstance(value, str) and value else None


def _event_id(event: Mapping[str, Any]) -> str | None:
    value = event.get("event_id")
    return value if isinstance(value, str) and value else None


def _event_sort_key(event: Mapping[str, Any]) -> tuple[str, int, int, str]:
    return (
        _session_id(event) or "",
        _source_seq(event) if _source_seq(event) is not None else 2**63 - 1,
        _integer(event.get("seq")) or 0,
        _source_key(event) or "",
    )


def _identity_matches(
    event: Mapping[str, Any],
    *,
    task_id: str,
    team_id: str,
    root_session_id: str,
    projector_revision: str,
) -> bool:
    return (
        event.get("task_id") == task_id
        and event.get("team_id") == team_id
        and event.get("root_session_id") == root_session_id
        and event.get("source") == "dsh"
        and event.get("projector_revision") == projector_revision
    )


def _floors(boundary: RunBoundary) -> dict[str, int] | None:
    result: dict[str, int] = {}
    for session_id, source_seq in boundary.source_seq_floor_by_session:
        if not session_id or isinstance(source_seq, bool) or not isinstance(source_seq, int):
            return None
        if session_id in result:
            return None
        result[session_id] = source_seq
    return result


def _root_run_for_event(
    event: Mapping[str, Any],
    *,
    root_session_id: str,
    ordered_runs: Sequence[RunBoundary],
    floor_maps: Mapping[str, Mapping[str, int]],
) -> str | None:
    if _session_id(event) != root_session_id:
        return None
    event_source_seq = _source_seq(event)
    if event_source_seq is None:
        return None
    matches: list[str] = []
    for index, boundary in enumerate(ordered_runs):
        if not boundary.boundary_complete:
            continue
        lower = floor_maps.get(boundary.run_id, {}).get(root_session_id)
        if lower is None or event_source_seq <= lower:
            continue
        if index + 1 < len(ordered_runs):
            next_boundary = ordered_runs[index + 1]
            if not next_boundary.boundary_complete:
                continue
            upper = floor_maps.get(next_boundary.run_id, {}).get(root_session_id)
            if upper is None or event_source_seq > upper:
                continue
        matches.append(boundary.run_id)
    if len(matches) != 1:
        return None
    selected = matches[0]
    return selected if _explicit_run_is_compatible(event, selected) else None


def _is_call(event: Mapping[str, Any]) -> bool:
    payload = _payload(event)
    event_type = _event_type(event)
    return (
        event_type in {"tool_call", "delegation"}
        and "arguments" in payload
        and "result" not in payload
        and "is_error" not in payload
    )


def _is_result(event: Mapping[str, Any]) -> bool:
    payload = _payload(event)
    return _event_type(event) in {
        "tool_result",
        "specialist_output",
        "delegation",
    } and ("result" in payload or "is_error" in payload)


def _tool_name(event: Mapping[str, Any]) -> str | None:
    value = _payload(event).get("tool_name")
    return value if isinstance(value, str) and value else None


def _canonical_refs(
    value: Any,
    *,
    task_id: str,
    expected_run_id: str | None,
    rule: EvidenceToolRule,
) -> tuple[tuple[EvidenceObjectRef, ...] | None, str | None]:
    try:
        refs = normalize_object_refs(
            value,
            expected_task_id=task_id,
            expected_run_id=expected_run_id,
            accepted_types=rule.accepted_ref_types,
            require_nonempty=True,
        )
    except ObjectRefValidationError as exc:
        message = str(exc)
        if "cannot be empty" in message or "must be a list" in message:
            return None, "missing_object_ref"
        if "another task" in message:
            return None, "cross_task_object_ref"
        if "not evidence-eligible" in message or "unknown" in message:
            return None, "unsupported_object_ref_type"
        return None, "invalid_object_ref"
    return refs, None


def _digest(
    *,
    task_id: str,
    team_id: str,
    run_id: str,
    candidate_source_key: str,
    evidence: Sequence[_EvidenceFact],
) -> str:
    canonical = {
        "version": SYNTHESIS_VERDICT_VERSION,
        "task_id": task_id,
        "team_id": team_id,
        "run_id": run_id,
        "candidate_source_key": candidate_source_key,
        "evidence": [
            {
                "source_key": fact.source_key,
                "tool_name": fact.tool_name,
                "refs": [ref.as_dict() for ref in fact.refs],
            }
            for fact in sorted(evidence, key=lambda item: (item.source_key, item.tool_name))
        ],
    }
    encoded = json.dumps(
        canonical,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def evaluate_synthesis_evidence(
    *,
    task_id: str,
    team_id: str,
    root_session_id: str,
    projector_revision: str,
    events: Sequence[Mapping[str, Any]],
    runs: Sequence[RunBoundary],
    verified_children: Sequence[VerifiedChildBinding] = (),
    tool_policy: Mapping[
        str, EvidenceToolRule
    ] = DEFAULT_EVIDENCE_TOOL_POLICY,
) -> SynthesisVerdictIndex:
    """Return one deterministic, fail-closed verdict snapshot.

    The function performs no I/O, reads no clock, and never mutates its inputs.
    Raw projector classifications remain audit facts; callers use these verdicts
    to derive both effective public events and run completion state.
    """

    ordered_runs = tuple(sorted(runs, key=lambda item: item.queue_event_seq))
    run_ids = {run.run_id for run in ordered_runs}
    floor_maps: dict[str, Mapping[str, int]] = {}
    invalid_boundaries: set[str] = set()
    for boundary in ordered_runs:
        selected = _floors(boundary)
        if selected is None or not boundary.boundary_complete:
            invalid_boundaries.add(boundary.run_id)
            floor_maps[boundary.run_id] = {}
        else:
            floor_maps[boundary.run_id] = selected

    selected_events = tuple(
        sorted(
            (
                event
                for event in events
                if _identity_matches(
                    event,
                    task_id=task_id,
                    team_id=team_id,
                    root_session_id=root_session_id,
                    projector_revision=projector_revision,
                )
            ),
            key=_event_sort_key,
        )
    )

    calls_by_session_and_id: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    for event in selected_events:
        session_id = _session_id(event)
        call_id = _call_id(event)
        if session_id and call_id and _is_call(event):
            calls_by_session_and_id.setdefault((session_id, call_id), []).append(event)

    root_run_by_event: dict[str, str] = {}
    for event in selected_events:
        event_id = _event_id(event)
        if event_id is None:
            continue
        run_id = _root_run_for_event(
            event,
            root_session_id=root_session_id,
            ordered_runs=ordered_runs,
            floor_maps=floor_maps,
        )
        if run_id is not None:
            root_run_by_event[event_id] = run_id

    valid_delegations: dict[tuple[str, str], tuple[VerifiedChildBinding, int]] = {}
    for binding in verified_children:
        if (
            binding.run_id not in run_ids
            or binding.run_id in invalid_boundaries
            or not binding.lineage_verified
            or binding.parent_session_id != root_session_id
            or not binding.child_session_id
            or not binding.delegation_call_id
        ):
            continue
        matching_results = []
        for event in selected_events:
            event_id = _event_id(event)
            payload = _payload(event)
            if (
                event_id is None
                or root_run_by_event.get(event_id) != binding.run_id
                or _session_id(event) != root_session_id
                or not _is_result(event)
                or _call_id(event) != binding.delegation_call_id
                or payload.get("is_error") is not False
                or _delegated_child_session_id(event) != binding.child_session_id
                or not _explicit_run_is_compatible(event, binding.run_id)
            ):
                continue
            calls = calls_by_session_and_id.get(
                (root_session_id, binding.delegation_call_id),
                [],
            )
            paired = [
                call
                for call in calls
                if root_run_by_event.get(_event_id(call) or "") == binding.run_id
                and _explicit_run_is_compatible(call, binding.run_id)
            ]
            if len(paired) == 1:
                matching_results.append(event)
        if len(matching_results) == 1:
            gate_seq = _source_seq(matching_results[0])
            if gate_seq is not None:
                valid_delegations[(binding.run_id, binding.child_session_id)] = (
                    binding,
                    gate_seq,
                )

    # Assign tool activity to one run before checking call/result closure. Root
    # events use the captured source window. Child events additionally require
    # a verified delegation and must be newer than that child's source floor.
    # This prevents a later run or historical child result from closing a call.
    tool_run_by_event: dict[str, str] = dict(root_run_by_event)
    for event in selected_events:
        event_id = _event_id(event)
        session_id = _session_id(event)
        event_source_seq = _source_seq(event)
        if (
            event_id is None
            or event_id in tool_run_by_event
            or session_id is None
            or event_source_seq is None
        ):
            continue
        child_matches = [
            (run_id, details)
            for (run_id, child_session_id), details in valid_delegations.items()
            if child_session_id == session_id
        ]
        if len(child_matches) != 1:
            continue
        run_id, (binding, _root_gate_source_seq) = child_matches[0]
        if not _explicit_run_is_compatible(event, run_id):
            continue
        floor = floor_maps.get(run_id, {}).get(session_id)
        if not binding.created_in_run and (
            floor is None or event_source_seq <= floor
        ):
            continue
        tool_run_by_event[event_id] = run_id

    def run_has_unpaired_tool_call(run_id: str) -> bool:
        calls: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
        results: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
        missing_identity_call = False
        for event in selected_events:
            event_id = _event_id(event)
            if event_id is None or tool_run_by_event.get(event_id) != run_id:
                continue
            if not _is_call(event) and not _is_result(event):
                continue
            session_id = _session_id(event)
            call_id = _call_id(event)
            if _is_call(event) and (not session_id or not call_id):
                missing_identity_call = True
                continue
            if not session_id or not call_id:
                continue
            key = (session_id, call_id)
            if _is_call(event):
                calls.setdefault(key, []).append(event)
            elif _is_result(event):
                results.setdefault(key, []).append(event)
        if missing_identity_call:
            return True
        return any(
            len(call_events) != 1 or len(results.get(key, ())) != 1
            for key, call_events in calls.items()
        )

    invalid_reasons: dict[str, set[str]] = {
        run.run_id: set() for run in ordered_runs
    }
    for run_id in invalid_boundaries:
        invalid_reasons.setdefault(run_id, set()).add("incomplete_source_boundary")
    evidence_by_run: dict[str, list[_EvidenceFact]] = {
        run.run_id: [] for run in ordered_runs
    }

    for result in selected_events:
        if not _is_result(result):
            continue
        event_id = _event_id(result)
        source_key = _source_key(result)
        session_id = _session_id(result)
        result_source_seq = _source_seq(result)
        call_id = _call_id(result)
        if not event_id or not source_key or not session_id or result_source_seq is None:
            continue

        root_run_id = root_run_by_event.get(event_id)
        child_matches = [
            (run_id, details)
            for (run_id, child_session_id), details in valid_delegations.items()
            if child_session_id == session_id
        ]
        if root_run_id is not None:
            run_id = root_run_id
            root_gate_source_seq = result_source_seq
            child_binding: VerifiedChildBinding | None = None
        elif len(child_matches) == 1:
            run_id, (child_binding, root_gate_source_seq) = child_matches[0]
            if not _explicit_run_is_compatible(result, run_id):
                continue
        else:
            continue

        calls = calls_by_session_and_id.get((session_id, call_id or ""), [])
        if child_binding is None:
            paired_calls = [
                call
                for call in calls
                if root_run_by_event.get(_event_id(call) or "") == run_id
            ]
        else:
            floor = floor_maps.get(run_id, {}).get(session_id)
            if not child_binding.created_in_run and floor is None:
                invalid_reasons[run_id].add("missing_child_source_floor")
                continue
            if not child_binding.created_in_run and (
                floor is not None and result_source_seq <= floor
            ):
                invalid_reasons[run_id].add("historical_child_evidence")
                continue
            paired_calls = []
            for call in calls:
                call_source_seq = _source_seq(call)
                if call_source_seq is None:
                    continue
                if (
                    not child_binding.created_in_run
                    and floor is not None
                    and call_source_seq <= floor
                ):
                    continue
                if not _explicit_run_is_compatible(call, run_id):
                    continue
                paired_calls.append(call)

        if len(paired_calls) != 1:
            invalid_reasons[run_id].add(
                "orphan_tool_result" if not paired_calls else "ambiguous_tool_call"
            )
            continue
        call = paired_calls[0]
        tool_name = _tool_name(call) or _tool_name(result)
        if not tool_name:
            invalid_reasons[run_id].add("missing_tool_name")
            continue
        if tool_name in OBSERVATION_ONLY_TOOLS:
            invalid_reasons[run_id].add("observation_only_tool")
            continue
        rule = tool_policy.get(tool_name)
        if rule is None:
            invalid_reasons[run_id].add("tool_not_evidence_eligible")
            continue
        payload = _payload(result)
        if payload.get("is_error") is not False or result.get("status") != "completed":
            invalid_reasons[run_id].add("failed_tool_result")
            continue
        arguments = _payload(call).get("arguments")
        if rule.require_task_argument and (
            not isinstance(arguments, Mapping)
            or arguments.get("task_id") != task_id
        ):
            invalid_reasons[run_id].add("tool_task_mismatch")
            continue
        expected_domain_run_id: str | None = None
        if rule.run_argument is not None:
            selected_run_id = (
                arguments.get(rule.run_argument)
                if isinstance(arguments, Mapping)
                else None
            )
            if not isinstance(selected_run_id, str) or not selected_run_id:
                invalid_reasons[run_id].add("tool_run_identity_missing")
                continue
            expected_domain_run_id = selected_run_id
        refs, ref_error = _canonical_refs(
            payload.get("object_refs"),
            task_id=task_id,
            expected_run_id=expected_domain_run_id,
            rule=rule,
        )
        if ref_error is not None or refs is None:
            invalid_reasons[run_id].add(ref_error or "invalid_object_ref")
            continue
        evidence_by_run[run_id].append(
            _EvidenceFact(
                run_id=run_id,
                event_id=event_id,
                source_key=source_key,
                tool_name=tool_name,
                refs=refs,
                session_id=session_id,
                source_seq=result_source_seq,
                root_gate_source_seq=root_gate_source_seq,
            )
        )

    candidates_by_run: dict[str, list[Mapping[str, Any]]] = {
        run.run_id: [] for run in ordered_runs
    }
    unbound_candidates: list[Mapping[str, Any]] = []
    for event in selected_events:
        candidate_shape = (
            event.get("category") == "synthesis_candidate"
            or _event_type(event) == "synthesis_candidate"
            or (
                event.get("category") == "final"
                and _event_type(event) == "final_synthesis"
            )
        )
        if _session_id(event) != root_session_id or not candidate_shape:
            continue
        event_id = _event_id(event)
        run_id = root_run_by_event.get(event_id or "")
        if run_id is None:
            unbound_candidates.append(event)
        else:
            candidates_by_run[run_id].append(event)

    event_verdicts: list[SynthesisEventVerdict] = []
    run_verdicts: list[RunEvidenceVerdict] = []
    for boundary in ordered_runs:
        run_id = boundary.run_id
        candidates = sorted(candidates_by_run[run_id], key=_event_sort_key)
        has_unpaired_tool_call = run_has_unpaired_tool_call(run_id)
        if has_unpaired_tool_call:
            invalid_reasons[run_id].add("unpaired_tool_call")
        if not candidates:
            reasons = tuple(
                sorted(invalid_reasons[run_id] | {"missing_synthesis_candidate"})
            )
            run_verdicts.append(
                RunEvidenceVerdict(
                    run_id=run_id,
                    accepted_candidate_event_id=None,
                    evidence_event_ids=(),
                    evidence_digest=None,
                    reason_codes=reasons,
                )
            )
            continue

        terminal = candidates[-1]
        terminal_id = _event_id(terminal)
        terminal_source_seq = _source_seq(terminal)
        terminal_source_key = _source_key(terminal)
        for candidate in candidates[:-1]:
            candidate_id = _event_id(candidate)
            if candidate_id:
                event_verdicts.append(
                    SynthesisEventVerdict(
                        candidate_event_id=candidate_id,
                        run_id=run_id,
                        accepted=False,
                        effective_category="narration",
                        effective_type="coordinator_note",
                        effective_status="observed",
                        reason_codes=("superseded_synthesis_candidate",),
                        evidence_event_ids=(),
                        evidence_object_refs=(),
                        evidence_digest=None,
                    )
                )

        eligible_evidence = [
            fact
            for fact in evidence_by_run[run_id]
            if terminal_source_seq is not None
            and fact.root_gate_source_seq <= terminal_source_seq
        ]
        accepted = bool(
            terminal_id
            and terminal_source_key
            and terminal_source_seq is not None
            and eligible_evidence
            and run_id not in invalid_boundaries
            and not has_unpaired_tool_call
        )
        if accepted:
            selected_evidence = tuple(
                sorted(
                    eligible_evidence,
                    key=lambda item: (item.source_key, item.tool_name),
                )
            )
            evidence_ids = tuple(item.event_id for item in selected_evidence)
            unique_refs = {
                repr(sorted(ref.as_dict().items())): ref
                for item in selected_evidence
                for ref in item.refs
            }
            refs = tuple(unique_refs[key] for key in sorted(unique_refs))
            evidence_digest = _digest(
                task_id=task_id,
                team_id=team_id,
                run_id=run_id,
                candidate_source_key=terminal_source_key,
                evidence=selected_evidence,
            )
            reasons: tuple[str, ...] = ()
        else:
            evidence_ids = ()
            refs = ()
            evidence_digest = None
            reasons = tuple(
                sorted(invalid_reasons[run_id] | {"missing_qualifying_evidence"})
            )
        if terminal_id:
            event_verdicts.append(
                SynthesisEventVerdict(
                    candidate_event_id=terminal_id,
                    run_id=run_id,
                    accepted=accepted,
                    effective_category="final" if accepted else "narration",
                    effective_type=(
                        "final_synthesis" if accepted else "coordinator_note"
                    ),
                    effective_status="completed" if accepted else "observed",
                    reason_codes=reasons,
                    evidence_event_ids=evidence_ids,
                    evidence_object_refs=refs,
                    evidence_digest=evidence_digest,
                )
            )
        run_verdicts.append(
            RunEvidenceVerdict(
                run_id=run_id,
                accepted_candidate_event_id=terminal_id if accepted else None,
                evidence_event_ids=evidence_ids,
                evidence_digest=evidence_digest,
                reason_codes=reasons,
            )
        )

    for candidate in sorted(unbound_candidates, key=_event_sort_key):
        candidate_id = _event_id(candidate)
        if candidate_id:
            event_verdicts.append(
                SynthesisEventVerdict(
                    candidate_event_id=candidate_id,
                    run_id=None,
                    accepted=False,
                    effective_category="narration",
                    effective_type="coordinator_note",
                    effective_status="observed",
                    reason_codes=("candidate_outside_run_boundary",),
                    evidence_event_ids=(),
                    evidence_object_refs=(),
                    evidence_digest=None,
                )
            )

    return SynthesisVerdictIndex(
        version=SYNTHESIS_VERDICT_VERSION,
        event_verdicts=tuple(
            sorted(
                event_verdicts,
                key=lambda item: (
                    item.run_id or "",
                    item.candidate_event_id,
                ),
            )
        ),
        run_verdicts=tuple(run_verdicts),
    )


__all__ = [
    "DEFAULT_EVIDENCE_TOOL_POLICY",
    "EvidenceObjectRef",
    "EvidenceToolRule",
    "RunBoundary",
    "RunEvidenceVerdict",
    "SYNTHESIS_VERDICT_VERSION",
    "SynthesisEventVerdict",
    "SynthesisVerdictIndex",
    "VerifiedChildBinding",
    "evaluate_synthesis_evidence",
]
