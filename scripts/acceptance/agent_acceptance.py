#!/usr/bin/env python3
"""Evidence checker for adaptive, page-driven Agent acceptance.

No model calls, browser automation, approvals, training or executable loading.
Page actions are performed by the CUA driver; this independent checker reads
its captures and explicit reviewer decisions. Missing evidence stays incomplete.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def confined(root: Path, relative: str) -> Path:
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("evidence reference must be relative to its capture directory")
    target = (root / path).resolve()
    if not target.is_relative_to(root.resolve()):
        raise ValueError("evidence reference escapes the capture directory")
    return target


def validate_case(case: dict[str, Any]) -> None:
    if not isinstance(case.get("id"), str) or not case["id"]:
        raise ValueError("case requires an id")
    for collection in ("checks", "reviews"):
        rows = case.get(collection, [])
        if not isinstance(rows, list):
            raise ValueError(f"{collection} must be a list")
        ids = [row.get("id") for row in rows]
        if any(not isinstance(value, str) or not value for value in ids) or len(set(ids)) != len(ids):
            raise ValueError(f"{collection} requires unique nonempty ids")
    for check in case.get("checks", []):
        if check.get("kind") not in {"page_action", "page_text", "fact"}:
            raise ValueError("unknown check kind; add a reviewed checker before using it")
    if not case.get("checks") and not case.get("reviews"):
        raise ValueError("case must define at least one acceptance criterion")


def get_field(value: Any, field: str) -> Any:
    for key in field.split("."):
        if not isinstance(value, dict) or key not in value:
            raise KeyError(field)
        value = value[key]
    return value


def check_capture(root: Path, row: dict[str, Any]) -> dict[str, Any]:
    """Validate bytes rather than trusting a filename or an Agent's verdict."""
    capture = dict(row)
    for key in ("snapshot", "screenshot"):
        ref = capture.get(key)
        if not isinstance(ref, dict):
            raise ValueError(f"capture lacks {key}")
        path = confined(root, ref["path"])
        if not path.is_file() or digest(path) != ref.get("sha256"):
            raise ValueError(f"{key} missing or changed")
        if key == "snapshot":
            capture["text"] = path.read_text(encoding="utf-8")
    if not capture.get("url") or not capture.get("id"):
        raise ValueError("capture lacks identity or URL")
    return capture


def evaluate(case: dict[str, Any], root: Path) -> dict[str, Any]:
    validate_case(case)
    journal = root / "journal.jsonl"
    rows = [json.loads(line) for line in journal.read_text(encoding="utf-8").splitlines() if line.strip()] if journal.exists() else []
    captures: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    seen: set[str] = set()
    for row in rows:
        if row.get("case_id") != case["id"]:
            errors.append("journal contains another case")
            continue
        if not row.get("id") or row["id"] in seen:
            errors.append("journal contains missing or duplicate observation id")
            continue
        seen.add(row["id"])
        try:
            captures[row["id"]] = check_capture(root, row)
        except (KeyError, ValueError, OSError, UnicodeError) as exc:
            errors.append(f"invalid capture {row.get('id')}: {exc}")

    facts: dict[str, Any] = {}
    fact_refs: dict[str, str] = {}
    facts_index = root / "facts.json"
    if facts_index.exists():
        for ref in read(facts_index).get("sources", []):
            try:
                path = confined(root, ref["path"])
                if digest(path) != ref["sha256"]:
                    raise ValueError("fact bytes changed")
                if ref["id"] in facts:
                    raise ValueError("duplicate fact source id")
                facts[ref["id"]] = read(path)
                fact_refs[ref["id"]] = ref["sha256"]
            except (KeyError, ValueError, OSError) as exc:
                errors.append(f"invalid fact reference: {exc}")

    outcomes = []
    for check in case.get("checks", []):
        status, evidence = "incomplete", []
        if check["kind"] == "page_action":
            selected = [row for row in captures.values() if row.get("action", {}).get("kind") == check["action"]]
            if "label" in check:
                selected = [row for row in selected if row["action"].get("label") == check["label"]]
            successes = [row for row in selected if row.get("action_status") == "completed"]
            if successes:
                status, evidence = "passed", [row["id"] for row in successes]
            elif selected:
                status, evidence = "failed", [row["id"] for row in selected]
        elif check["kind"] == "page_text":
            selected = [row for row in captures.values() if check["text"] in row["text"]]
            if selected:
                status, evidence = "passed", [row["id"] for row in selected]
        elif check["kind"] == "fact":
            source = check["source"]
            if source in facts:
                try:
                    actual = get_field(facts[source], check["field"])
                    # Exact equality only. Numeric quality comparisons belong
                    # to the existing frozen EvaluationReport, not new gates.
                    status = "passed" if actual == check["equals"] else "failed"
                    evidence = [source + ":" + fact_refs[source]]
                except KeyError:
                    status, evidence = "failed", [source + ":field_missing"]
        outcomes.append({"id": check["id"], "dimension": check.get("dimension", "functional"), "status": status, "evidence": evidence})

    review_path = root / "reviews.json"
    reviews = read(review_path).get("reviews", []) if review_path.exists() else []
    for criterion in case.get("reviews", []):
        candidates = [item for item in reviews if item.get("criterion_id") == criterion["id"]]
        status, evidence = "needs_review", []
        if len(candidates) == 1:
            review = candidates[0]
            # An explicit independent reviewer must bind the verdict to the
            # captured bytes and quote actual page content. Executor self-
            # evaluation and missing references never count as acceptance.
            valid = review.get("reviewer_role") in {"independent_agent", "human"} and bool(review.get("reviewer_id")) and bool(review.get("rationale"))
            refs = review.get("evidence", [])
            valid = valid and bool(refs)
            for ref in refs:
                captured = captures.get(ref.get("observation_id"))
                valid = valid and bool(captured) and bool(ref.get("quote"))
                if captured:
                    valid = valid and ref.get("snapshot_sha256") == captured["snapshot"]["sha256"] and ref.get("quote", "") in captured["text"]
                    evidence.append(captured["id"])
            if valid and review.get("verdict") in {"passed", "failed"}:
                status = review["verdict"]
        outcomes.append({"id": criterion["id"], "dimension": criterion.get("dimension", "dialogue"), "status": status, "evidence": evidence})

    if errors or any(row["status"] == "failed" for row in outcomes):
        verdict = "failed"
    elif any(row["status"] in {"incomplete", "needs_review"} for row in outcomes):
        verdict = "incomplete"
    else:
        verdict = "passed"
    return {"schema_version": "1.0", "case_id": case["id"], "verdict": verdict, "criteria": outcomes, "evidence_errors": errors, "observation_count": len(captures), "scope": case.get("scope", "page_acceptance"), "quality_is_separate_from_flow": True}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    result = evaluate(read(args.case), args.evidence)
    rendered = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    raise SystemExit(0 if result["verdict"] == "passed" else 1)


if __name__ == "__main__":
    main()
