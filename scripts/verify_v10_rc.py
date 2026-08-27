#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import secrets
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GATE_CONTRACT = ROOT / "acceptance" / "v1.0-gates.json"
REPORT_SCHEMA_VERSION = "1.0"
_TOP_LEVEL_KEYS = {
    "schema_version",
    "iteration",
    "generated_at_utc",
    "candidate",
    "source",
    "gates",
    "summary",
}
_CANDIDATE_KEYS = {
    "product_name",
    "distribution_name",
    "package_version",
    "api_version",
    "distribution_kind",
    "wheel_scope",
}
_SOURCE_KEYS = {"source_commit", "source_dirty", "repository_url"}
_GATE_KEYS = {
    "level_id",
    "gate_id",
    "required",
    "required_for_github_release",
    "status",
    "summary",
    "evidence_refs",
    "blockers",
}
_EVIDENCE_KEYS = {"path", "sha256", "description"}
_SUMMARY_KEYS = {
    "gate_counts",
    "passed_gate_ids",
    "failed_gate_ids",
    "blocked_gate_ids",
    "local_review_status",
    "public_rc_status",
    "github_release_status",
}
_GATE_COUNT_KEYS = {"total", "passed", "failed", "blocked"}


class VerificationError(ValueError):
    """Raised when an RC report cannot prove its own claims."""


def _require_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise VerificationError(f"{label} must be a JSON object")
    return value


def _require_exact_keys(
    value: Mapping[str, Any], expected: set[str], label: str
) -> None:
    observed = set(value)
    missing = sorted(expected - observed)
    unexpected = sorted(observed - expected)
    if missing or unexpected:
        raise VerificationError(
            f"{label} keys mismatch; missing={missing}, unexpected={unexpected}"
        )


def _run_git(source_root: Path, arguments: Sequence[str]) -> str:
    completed = subprocess.run(
        ["git", "-C", str(source_root), *arguments],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=20,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise VerificationError(
            f"git {' '.join(arguments)} failed for {source_root}: {detail}"
        )
    return completed.stdout.strip()


def _validate_commit(value: Any, label: str = "source_commit") -> str:
    if (
        not isinstance(value, str)
        or len(value) != 40
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise VerificationError(f"{label} must be a lowercase 40-character commit")
    return value


def capture_source_state(source_root: str | Path) -> dict[str, Any]:
    selected_root = Path(source_root).expanduser().resolve()
    top_level = Path(
        _run_git(selected_root, ["rev-parse", "--show-toplevel"])
    ).resolve()
    if top_level != selected_root:
        raise VerificationError(
            f"source_root must be the Git checkout root: expected {top_level}, "
            f"observed {selected_root}"
        )
    source_commit = _validate_commit(
        _run_git(selected_root, ["rev-parse", "HEAD"])
    )
    source_dirty = bool(
        _run_git(
            selected_root,
            ["status", "--porcelain", "--untracked-files=normal"],
        )
    )
    remote = subprocess.run(
        ["git", "-C", str(selected_root), "config", "--get", "remote.origin.url"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        timeout=10,
        check=False,
    )
    repository_url = remote.stdout.strip() if remote.returncode == 0 else None
    return {
        "source_commit": source_commit,
        "source_dirty": source_dirty,
        "repository_url": repository_url or None,
    }


def load_gate_contract(path: str | Path = DEFAULT_GATE_CONTRACT) -> dict[str, Any]:
    selected = Path(path)
    try:
        payload = json.loads(selected.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise VerificationError(f"could not read gate contract {selected}: {exc}") from exc
    contract = _require_object(payload, "gate contract")
    if contract.get("schema_version") != REPORT_SCHEMA_VERSION:
        raise VerificationError("gate contract schema_version must equal '1.0'")
    if contract.get("iteration") != "v1.0-conversation-native":
        raise VerificationError(
            "gate contract iteration must equal 'v1.0-conversation-native'"
        )
    candidate = _candidate_from_contract(contract)
    if any(not value for value in candidate.values()):
        raise VerificationError("gate contract candidate metadata must be complete")
    allowed = contract.get("allowed_gate_statuses")
    if allowed != ["passed", "failed", "blocked"]:
        raise VerificationError(
            "gate contract must allow exactly passed, failed and blocked"
        )
    levels = contract.get("levels")
    if not isinstance(levels, list) or len(levels) != 8:
        raise VerificationError("gate contract must declare exactly L0-L6 and release")
    observed_levels = [item.get("level_id") for item in levels if isinstance(item, dict)]
    if observed_levels != ["L0", "L1", "L2", "L3", "L4", "L5", "L6", "release"]:
        raise VerificationError(
            "gate contract levels must be ordered exactly L0-L6 then release"
        )
    gate_ids = [item.get("gate_id") for item in levels if isinstance(item, dict)]
    if len(gate_ids) != len(set(gate_ids)) or any(
        not isinstance(value, str) or not value for value in gate_ids
    ):
        raise VerificationError("gate contract gate_id values must be unique strings")
    for item in levels:
        level_id = item.get("level_id")
        if level_id == "release":
            if item.get("required") is not False or item.get(
                "required_for_github_release"
            ) is not True:
                raise VerificationError(
                    "release gate must be optional locally and required for GitHub release"
                )
        elif item.get("required") is not True:
            raise VerificationError(f"{level_id} must be required")
    return contract


def _candidate_from_contract(contract: Mapping[str, Any]) -> dict[str, str]:
    return {
        "product_name": str(contract.get("expected_product_name", "")),
        "distribution_name": str(contract.get("expected_distribution_name", "")),
        "package_version": str(contract.get("expected_package_version", "")),
        "api_version": str(contract.get("expected_api_version", "")),
        "distribution_kind": str(contract.get("distribution_kind", "")),
        "wheel_scope": str(contract.get("wheel_scope", "")),
    }


def _aggregate_status(statuses: Sequence[str]) -> str:
    if any(status == "failed" for status in statuses):
        return "failed"
    if statuses and all(status == "passed" for status in statuses):
        return "passed"
    return "blocked"


def derive_summary(
    gates: Sequence[Mapping[str, Any]], *, source_dirty: bool
) -> dict[str, Any]:
    by_level = {str(item["level_id"]): str(item["status"]) for item in gates}
    local_status = _aggregate_status(
        [by_level[f"L{index}"] for index in range(6)]
    )
    public_status = _aggregate_status([local_status, by_level["L6"]])
    if public_status == "passed" and source_dirty:
        public_status = "blocked"
    github_status = _aggregate_status([public_status, by_level["release"]])
    statuses = [str(item["status"]) for item in gates]
    return {
        "gate_counts": {
            "total": len(gates),
            "passed": statuses.count("passed"),
            "failed": statuses.count("failed"),
            "blocked": statuses.count("blocked"),
        },
        "passed_gate_ids": [
            str(item["gate_id"]) for item in gates if item["status"] == "passed"
        ],
        "failed_gate_ids": [
            str(item["gate_id"]) for item in gates if item["status"] == "failed"
        ],
        "blocked_gate_ids": [
            str(item["gate_id"]) for item in gates if item["status"] == "blocked"
        ],
        "local_review_status": local_status,
        "public_rc_status": public_status,
        "github_release_status": github_status,
    }


def build_blocked_template(
    contract: Mapping[str, Any], source: Mapping[str, Any]
) -> dict[str, Any]:
    gates = []
    for definition in contract["levels"]:
        gate_id = str(definition["gate_id"])
        gates.append(
            {
                "level_id": str(definition["level_id"]),
                "gate_id": gate_id,
                "required": bool(definition.get("required", False)),
                "required_for_github_release": bool(
                    definition.get("required_for_github_release", False)
                ),
                "status": "blocked",
                "summary": "No verified evidence has been attached to this gate.",
                "evidence_refs": [],
                "blockers": [f"{gate_id} has not been independently verified"],
            }
        )
    source_record = {
        "source_commit": _validate_commit(source.get("source_commit")),
        "source_dirty": bool(source.get("source_dirty")),
        "repository_url": source.get("repository_url"),
    }
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "iteration": str(contract["iteration"]),
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "candidate": _candidate_from_contract(contract),
        "source": source_record,
        "gates": gates,
        "summary": derive_summary(
            gates, source_dirty=source_record["source_dirty"]
        ),
    }


def _validate_generated_at(value: Any) -> None:
    if not isinstance(value, str):
        raise VerificationError("generated_at_utc must be an ISO date-time string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise VerificationError("generated_at_utc must be a valid date-time") from exc
    if parsed.tzinfo is None:
        raise VerificationError("generated_at_utc must include a timezone")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_evidence_ref(
    value: Any, *, report_path: Path, label: str
) -> dict[str, Any]:
    evidence = _require_object(value, label)
    allowed_keys = {"path", "sha256"}
    if "description" in evidence:
        allowed_keys.add("description")
    _require_exact_keys(evidence, allowed_keys, label)
    raw_path = evidence.get("path")
    if not isinstance(raw_path, str) or not raw_path:
        raise VerificationError(f"{label}.path must be a non-empty relative path")
    relative = PurePosixPath(raw_path)
    if relative.is_absolute() or ".." in relative.parts or "." in relative.parts:
        raise VerificationError(
            f"{label}.path must stay below the report directory"
        )
    if "\\" in raw_path:
        raise VerificationError(f"{label}.path must use POSIX separators")
    evidence_path = report_path.parent.joinpath(*relative.parts)
    if evidence_path.is_symlink():
        raise VerificationError(f"{label}.path must not be a symlink")
    resolved_parent = report_path.parent.resolve()
    resolved_evidence = evidence_path.resolve()
    if not resolved_evidence.is_relative_to(resolved_parent):
        raise VerificationError(f"{label}.path escapes the report directory")
    if not resolved_evidence.is_file():
        raise VerificationError(f"{label}.path does not exist: {raw_path}")
    expected_digest = evidence.get("sha256")
    if (
        not isinstance(expected_digest, str)
        or len(expected_digest) != 64
        or any(character not in "0123456789abcdef" for character in expected_digest)
    ):
        raise VerificationError(f"{label}.sha256 must be lowercase SHA-256")
    observed_digest = _sha256_file(resolved_evidence)
    if observed_digest != expected_digest:
        raise VerificationError(
            f"{label}.sha256 mismatch for {raw_path}: expected "
            f"{expected_digest}, observed {observed_digest}"
        )
    description = evidence.get("description")
    if description is not None and (
        not isinstance(description, str) or not description.strip()
    ):
        raise VerificationError(f"{label}.description must be a non-empty string")
    return evidence


def _validate_report_gate(
    value: Any,
    *,
    definition: Mapping[str, Any],
    report_path: Path,
    allowed_statuses: set[str],
) -> dict[str, Any]:
    gate_id = str(definition["gate_id"])
    gate = _require_object(value, f"gate {gate_id}")
    _require_exact_keys(gate, _GATE_KEYS, f"gate {gate_id}")
    expected = {
        "level_id": str(definition["level_id"]),
        "gate_id": gate_id,
        "required": bool(definition.get("required", False)),
        "required_for_github_release": bool(
            definition.get("required_for_github_release", False)
        ),
    }
    for key, expected_value in expected.items():
        if gate.get(key) != expected_value:
            raise VerificationError(
                f"gate {gate_id}.{key} expected {expected_value!r}, "
                f"observed {gate.get(key)!r}"
            )
    status = gate.get("status")
    if status not in allowed_statuses:
        raise VerificationError(
            f"gate {gate_id}.status must be one of {sorted(allowed_statuses)}"
        )
    summary = gate.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        raise VerificationError(f"gate {gate_id}.summary must be non-empty")
    evidence_refs = gate.get("evidence_refs")
    if not isinstance(evidence_refs, list):
        raise VerificationError(f"gate {gate_id}.evidence_refs must be an array")
    seen_evidence: set[tuple[str, str]] = set()
    for index, evidence in enumerate(evidence_refs):
        validated = _validate_evidence_ref(
            evidence,
            report_path=report_path,
            label=f"gate {gate_id}.evidence_refs[{index}]",
        )
        identity = (str(validated["path"]), str(validated["sha256"]))
        if identity in seen_evidence:
            raise VerificationError(f"gate {gate_id} repeats evidence {identity[0]}")
        seen_evidence.add(identity)
    blockers = gate.get("blockers")
    if (
        not isinstance(blockers, list)
        or any(not isinstance(item, str) or not item.strip() for item in blockers)
        or len(blockers) != len(set(blockers))
    ):
        raise VerificationError(
            f"gate {gate_id}.blockers must contain unique non-empty strings"
        )
    if status == "passed":
        if not evidence_refs:
            raise VerificationError(
                f"passed gate {gate_id} must reference verified evidence"
            )
        if blockers:
            raise VerificationError(f"passed gate {gate_id} must not have blockers")
    elif not blockers:
        raise VerificationError(
            f"{status} gate {gate_id} must explain at least one blocker"
        )
    return gate


def validate_report(
    report: Any,
    *,
    report_path: str | Path,
    contract: Mapping[str, Any],
    source_state: Mapping[str, Any],
    expected_source_commit: str,
) -> dict[str, Any]:
    selected_report_path = Path(report_path).expanduser().resolve()
    payload = _require_object(report, "report")
    _require_exact_keys(payload, _TOP_LEVEL_KEYS, "report")
    if payload.get("schema_version") != REPORT_SCHEMA_VERSION:
        raise VerificationError(
            f"schema_version must equal {REPORT_SCHEMA_VERSION!r}"
        )
    if payload.get("iteration") != contract.get("iteration"):
        raise VerificationError("report iteration does not match gate contract")
    _validate_generated_at(payload.get("generated_at_utc"))

    candidate = _require_object(payload.get("candidate"), "candidate")
    _require_exact_keys(candidate, _CANDIDATE_KEYS, "candidate")
    expected_candidate = _candidate_from_contract(contract)
    if candidate != expected_candidate:
        raise VerificationError(
            f"candidate metadata mismatch; expected {expected_candidate}, "
            f"observed {candidate}"
        )

    source = _require_object(payload.get("source"), "source")
    _require_exact_keys(source, _SOURCE_KEYS, "source")
    report_commit = _validate_commit(source.get("source_commit"))
    expected_commit = _validate_commit(
        expected_source_commit, "expected_source_commit"
    )
    observed_commit = _validate_commit(
        source_state.get("source_commit"), "observed source commit"
    )
    if report_commit != expected_commit or report_commit != observed_commit:
        raise VerificationError(
            "source_commit must match both the expected candidate and the "
            f"checked-out source: report={report_commit}, expected={expected_commit}, "
            f"observed={observed_commit}"
        )
    source_dirty = source.get("source_dirty")
    if not isinstance(source_dirty, bool):
        raise VerificationError("source.source_dirty must be boolean")
    observed_dirty = source_state.get("source_dirty")
    if not isinstance(observed_dirty, bool) or source_dirty is not observed_dirty:
        raise VerificationError(
            "source_dirty must match the checked-out source: "
            f"report={source_dirty!r}, observed={observed_dirty!r}"
        )
    repository_url = source.get("repository_url")
    if repository_url is not None and not isinstance(repository_url, str):
        raise VerificationError("source.repository_url must be string or null")
    observed_repository_url = source_state.get("repository_url")
    if repository_url != observed_repository_url:
        raise VerificationError(
            "source.repository_url must match the checked-out source: "
            f"report={repository_url!r}, observed={observed_repository_url!r}"
        )

    raw_gates = payload.get("gates")
    if not isinstance(raw_gates, list) or len(raw_gates) != len(contract["levels"]):
        raise VerificationError("report must contain exactly one result for every gate")
    report_ids = [
        item.get("gate_id") if isinstance(item, dict) else None for item in raw_gates
    ]
    expected_ids = [str(item["gate_id"]) for item in contract["levels"]]
    if report_ids != expected_ids:
        raise VerificationError(
            f"gate order or identity mismatch; expected {expected_ids}, "
            f"observed {report_ids}"
        )
    allowed_statuses = set(contract["allowed_gate_statuses"])
    gates = [
        _validate_report_gate(
            value,
            definition=definition,
            report_path=selected_report_path,
            allowed_statuses=allowed_statuses,
        )
        for value, definition in zip(raw_gates, contract["levels"], strict=True)
    ]

    summary = _require_object(payload.get("summary"), "summary")
    _require_exact_keys(summary, _SUMMARY_KEYS, "summary")
    counts = _require_object(summary.get("gate_counts"), "summary.gate_counts")
    _require_exact_keys(counts, _GATE_COUNT_KEYS, "summary.gate_counts")
    expected_summary = derive_summary(gates, source_dirty=source_dirty)
    if summary != expected_summary:
        raise VerificationError(
            f"summary must be derived from canonical gate results; "
            f"expected {expected_summary}, observed {summary}"
        )
    if summary["public_rc_status"] == "passed" and source_dirty:
        raise VerificationError("public_rc_status cannot pass for a dirty source")
    return expected_summary


def _read_report(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise VerificationError(f"could not read report {path}: {exc}") from exc


def _write_json(path: Path, payload: Mapping[str, Any], *, force: bool) -> None:
    selected = path.expanduser().resolve()
    if selected.exists() and not force:
        raise VerificationError(
            f"refusing to overwrite existing report {selected}; use --force"
        )
    selected.parent.mkdir(parents=True, exist_ok=True)
    temporary = selected.with_name(
        f".{selected.name}.{secrets.token_hex(6)}.tmp"
    )
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(selected)
    finally:
        temporary.unlink(missing_ok=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate or validate a fail-closed v1.0 RC acceptance report."
    )
    parser.add_argument(
        "--gate-contract",
        default=str(DEFAULT_GATE_CONTRACT),
        help="Path to acceptance/v1.0-gates.json.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    template = subparsers.add_parser(
        "template", help="Generate a new all-blocked report template."
    )
    template.add_argument("--output", required=True)
    template.add_argument("--source-root", default=str(ROOT))
    template.add_argument("--expected-source-commit")
    template.add_argument("--force", action="store_true")

    validate = subparsers.add_parser(
        "validate", help="Validate a report and all referenced evidence digests."
    )
    validate.add_argument("--report", required=True)
    validate.add_argument("--source-root", default=str(ROOT))
    validate.add_argument("--expected-source-commit")
    target = validate.add_mutually_exclusive_group()
    target.add_argument("--require-local-review", action="store_true")
    target.add_argument("--require-public-rc", action="store_true")
    target.add_argument("--require-github-release", action="store_true")
    return parser


def _required_target(args: argparse.Namespace) -> str | None:
    if getattr(args, "require_github_release", False):
        return "github_release_status"
    if getattr(args, "require_public_rc", False):
        return "public_rc_status"
    if getattr(args, "require_local_review", False):
        return "local_review_status"
    return None


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        contract = load_gate_contract(args.gate_contract)
        source_state = capture_source_state(args.source_root)
        expected_commit = args.expected_source_commit or source_state["source_commit"]
        expected_commit = _validate_commit(
            expected_commit, "expected_source_commit"
        )
        if expected_commit != source_state["source_commit"]:
            raise VerificationError(
                "expected_source_commit does not match the checked-out source: "
                f"expected={expected_commit}, observed={source_state['source_commit']}"
            )

        if args.command == "template":
            report = build_blocked_template(contract, source_state)
            output = Path(args.output).expanduser().resolve()
            _write_json(output, report, force=args.force)
            print(
                json.dumps(
                    {
                        "created": str(output),
                        "source_commit": source_state["source_commit"],
                        "source_dirty": source_state["source_dirty"],
                        "public_rc_status": report["summary"]["public_rc_status"],
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0

        report_path = Path(args.report).expanduser().resolve()
        summary = validate_report(
            _read_report(report_path),
            report_path=report_path,
            contract=contract,
            source_state=source_state,
            expected_source_commit=expected_commit,
        )
        target = _required_target(args)
        if target is not None and summary[target] != "passed":
            raise VerificationError(
                f"{target} must equal 'passed', observed {summary[target]!r}"
            )
        print(
            json.dumps(
                {
                    "valid": True,
                    "source_commit": source_state["source_commit"],
                    "source_dirty": source_state["source_dirty"],
                    **summary,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    except VerificationError as exc:
        print(
            json.dumps(
                {"valid": False, "error": str(exc)},
                ensure_ascii=False,
                indent=2,
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
