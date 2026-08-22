from __future__ import annotations

from collections.abc import Iterator
from typing import Any


TEST_EVIDENCE_ROOTS = frozenset(
    {
        "clean_test",
        "stress_tests",
        "failure_count",
        "failure_samples",
        "test_predictions",
        "test_reference",
    }
)


class TrackedMetrics(dict[str, Any]):
    """A dict-compatible read tracker for optimization evidence provenance."""

    def __init__(
        self,
        value: Any = (),
        accesses: set[str] | None = None,
        path: tuple[str, ...] = (),
    ) -> None:
        super().__init__(value)
        # ``dataclasses.asdict`` reconstructs dict subclasses from an iterator
        # of pairs. Optional tracker state keeps that serialization path safe.
        self._accesses = accesses if accesses is not None else set()
        self._path = path

    def __getitem__(self, key: str) -> Any:
        selected = str(key)
        path = (*self._path, selected)
        self._accesses.add(".".join(path))
        return self._wrap(super().__getitem__(key), path)

    def get(self, key: str, default: Any = None) -> Any:
        if key not in self:
            return default
        return self[key]

    def items(self) -> Iterator[tuple[str, Any]]:  # type: ignore[override]
        for key in super().keys():
            yield key, self[key]

    def values(self) -> Iterator[Any]:  # type: ignore[override]
        for key in super().keys():
            yield self[key]

    def _wrap(self, value: Any, path: tuple[str, ...]) -> Any:
        if isinstance(value, dict):
            return TrackedMetrics(value, self._accesses, path)
        return value


def propose_strategies_with_provenance(
    plugin: Any,
    metrics: dict[str, Any],
    contract: dict[str, Any],
) -> tuple[list[Any], dict[str, Any]]:
    """Run a plugin proposal step and record whether held-out evidence was read.

    Existing Recipe plugins remain API-compatible. The conservative report is
    later attached to every returned proposal; an approved child Run can then
    inherit an explicit contamination marker instead of silently reusing the
    parent's final test evidence for hyperparameter decisions.
    """

    accesses: set[str] = set()
    tracked = TrackedMetrics(metrics, accesses)
    strategies = plugin.propose_strategies(tracked, contract)
    test_paths = sorted(
        path for path in accesses if path.split(".", 1)[0] in TEST_EVIDENCE_ROOTS
    )
    evidence_paths: set[str] = set()
    for strategy in strategies:
        payload = strategy.to_dict()
        _collect_test_evidence_keys(payload.get("evidence", {}), (), evidence_paths)
    reasons: list[str] = []
    if test_paths:
        reasons.append(
            "optimization proposal read held-out test metrics: "
            + ", ".join(test_paths)
        )
    if evidence_paths:
        reasons.append(
            "strategy evidence embeds held-out test values: "
            + ", ".join(sorted(evidence_paths))
        )
    return strategies, {
        "schema_version": "0.1",
        "accessed_metric_paths": sorted(accesses),
        "test_metric_paths": test_paths,
        "test_evidence_fields": sorted(evidence_paths),
        "uses_test_evidence": bool(test_paths or evidence_paths),
        "contamination_reasons": reasons,
        "policy": (
            "child_run_must_be_marked_test_contaminated"
            if test_paths or evidence_paths
            else "validation_or_training_evidence_only"
        ),
    }


def attach_provenance(
    strategy: Any,
    provenance: dict[str, Any],
) -> dict[str, Any]:
    value = strategy.to_dict()
    value["evidence_provenance"] = {
        "uses_test_evidence": bool(provenance.get("uses_test_evidence")),
        "test_metric_paths": list(provenance.get("test_metric_paths", [])),
        "test_evidence_fields": list(
            provenance.get("test_evidence_fields", [])
        ),
        "contamination_reasons": list(
            provenance.get("contamination_reasons", [])
        ),
        "policy": provenance.get("policy"),
    }
    return value


def _collect_test_evidence_keys(
    value: Any,
    path: tuple[str, ...],
    output: set[str],
) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            selected = str(key)
            selected_path = (*path, selected)
            lowered = selected.casefold()
            if any(
                token in lowered
                for token in ("clean_test", "test_", "test-", "failure")
            ):
                output.add(".".join(selected_path))
            _collect_test_evidence_keys(item, selected_path, output)
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _collect_test_evidence_keys(item, (*path, str(index)), output)


__all__ = [
    "TEST_EVIDENCE_ROOTS",
    "TrackedMetrics",
    "attach_provenance",
    "propose_strategies_with_provenance",
]
