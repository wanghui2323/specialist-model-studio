from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any


CSV_TARGET_RECOMMENDATION_SCHEMA_VERSION = "1.0"

_PREDICTION_MARKER = re.compile(
    r"(?:预测|预估|估算|推断|输出|forecast(?:ing)?|predict(?:ing)?|"
    r"target(?:\s+(?:column|field))?)\s*(?:是|为|:|：|=)?\s*",
    re.IGNORECASE,
)
_CLAUSE_END = re.compile(r"[，,。；;\n\r]")
_SAFE_TARGET_NAMES = frozenset(
    {
        "target",
        "label",
        "price",
        "quality",
        "score",
        "result",
        "outcome",
        "disease_progression",
        "dependent_variable",
    }
)


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _normalize_columns(columns: Sequence[Any]) -> list[str]:
    selected = [str(value).strip() for value in columns]
    if len(selected) < 2 or any(not value for value in selected):
        raise ValueError("CSV target recommendation requires at least two named columns")
    if len(set(selected)) != len(selected):
        raise ValueError("CSV target recommendation columns must be unique")
    return selected


def _declared_targets(task: Mapping[str, Any]) -> list[str]:
    task_spec = _mapping(task.get("task_spec"))
    sources = (
        _mapping(task.get("capability_request")),
        _mapping(task_spec.get("capability_request")),
    )
    targets: list[str] = []
    normalized: set[str] = set()
    for source in sources:
        target = str(source.get("target_column") or "").strip()
        folded = target.casefold()
        if target and folded not in normalized:
            normalized.add(folded)
            targets.append(target)
    return targets


def _description_text(task: Mapping[str, Any]) -> str:
    task_spec = _mapping(task.get("task_spec"))
    values = (
        task.get("business_goal"),
        task_spec.get("business_goal"),
        task_spec.get("user_note"),
        task.get("title"),
        task.get("name"),
    )
    return "\n".join(
        str(value).strip() for value in values if str(value or "").strip()
    )


def _column_in_clause(clause: str, column: str) -> bool:
    escaped = re.escape(column)
    if re.fullmatch(r"[A-Za-z0-9_]+", column):
        return (
            re.search(
                rf"(?<![A-Za-z0-9_]){escaped}(?![A-Za-z0-9_])",
                clause,
                re.IGNORECASE,
            )
            is not None
        )
    return column.casefold() in clause.casefold()


def _prediction_phrase_targets(text: str, columns: Sequence[str]) -> list[str]:
    matches: list[str] = []
    normalized: set[str] = set()
    for marker in _PREDICTION_MARKER.finditer(text):
        remainder = text[marker.end() :]
        clause = _CLAUSE_END.split(remainder, maxsplit=1)[0]
        mentioned = [
            column for column in columns if _column_in_clause(clause, column)
        ]
        if len(mentioned) != 1:
            continue
        selected = mentioned[0]
        folded = selected.casefold()
        if folded not in normalized:
            normalized.add(folded)
            matches.append(selected)
    return matches


def _decision(
    *,
    status: str,
    target_column: str | None,
    source: str | None,
    confidence: str,
    reason_code: str,
    message: str,
    declared_target_column: str | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": CSV_TARGET_RECOMMENDATION_SCHEMA_VERSION,
        "status": status,
        "target_column": target_column,
        "declared_target_column": declared_target_column,
        "source": source,
        "confidence": confidence,
        "reason_code": reason_code,
        "message": message,
    }


def recommend_csv_target_column(
    task: Mapping[str, Any],
    columns: Sequence[Any],
) -> dict[str, Any]:
    """Recommend a CSV target only when task-owned evidence is unambiguous.

    A declared TaskSpec target always wins. If that declaration is absent from
    the uploaded header, the function stops instead of silently substituting a
    different column. Prose and common-name heuristics are intentionally
    conservative and never fall back to the last CSV column.
    """

    selected_columns = _normalize_columns(columns)
    columns_by_name: dict[str, list[str]] = {}
    for column in selected_columns:
        columns_by_name.setdefault(column.casefold(), []).append(column)

    declared = _declared_targets(task)
    if len(declared) > 1:
        return _decision(
            status="needs_confirmation",
            target_column=None,
            source=None,
            confidence="none",
            reason_code="conflicting_declared_targets",
            message="任务规范中存在冲突的目标字段，请先确认要预测哪一列。",
        )
    if declared:
        requested = declared[0]
        matches = columns_by_name.get(requested.casefold(), [])
        if len(matches) == 1:
            return _decision(
                status="recommended",
                target_column=matches[0],
                declared_target_column=requested,
                source="task_capability",
                confidence="high",
                reason_code="declared_target_matches_header",
                message=f"任务规范明确声明预测字段为“{matches[0]}”。",
            )
        return _decision(
            status="declared_target_missing",
            target_column=None,
            declared_target_column=requested,
            source="task_capability",
            confidence="none",
            reason_code="declared_target_not_in_header",
            message=f"任务规范声明的预测字段“{requested}”不在 CSV 表头中。",
        )

    prose_matches = _prediction_phrase_targets(
        _description_text(task),
        selected_columns,
    )
    if len(prose_matches) == 1:
        return _decision(
            status="recommended",
            target_column=prose_matches[0],
            source="task_prediction_phrase",
            confidence="high",
            reason_code="prediction_phrase_matches_header",
            message=f"任务描述明确要预测“{prose_matches[0]}”。",
        )
    if len(prose_matches) > 1:
        return _decision(
            status="needs_confirmation",
            target_column=None,
            source=None,
            confidence="none",
            reason_code="ambiguous_prediction_phrases",
            message="任务描述对应多个可能的预测字段，请手动确认。",
        )

    common = [
        column
        for column in selected_columns
        if column.casefold() in _SAFE_TARGET_NAMES
    ]
    if len(common) == 1:
        return _decision(
            status="recommended",
            target_column=common[0],
            source="safe_common_target_name",
            confidence="medium",
            reason_code="one_safe_common_target_name",
            message=f"CSV 中只有“{common[0]}”符合常见目标字段命名，请核对。",
        )

    return _decision(
        status="needs_confirmation",
        target_column=None,
        source=None,
        confidence="none",
        reason_code=(
            "multiple_safe_common_target_names"
            if len(common) > 1
            else "target_not_declared"
        ),
        message="任务没有唯一、可靠的目标字段信息，请手动选择要预测的列。",
    )
